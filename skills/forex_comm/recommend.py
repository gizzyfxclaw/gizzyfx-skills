"""Forex + Commodity recommendation logic.

Adds macro & calendar awareness on top of the base signals engine:
- DXY (USD index) directional bias — supports/penalises USD-paired trades
- Economic calendar today (ForexFactory): high-impact events trigger WAIT
- Currency strength heuristic (USD/EUR/JPY/GBP via DXY + cross pairs)
- News from forex/macro feeds + optional Telegram channels
"""

from __future__ import annotations

from typing import Any

from . import feeds
from .._shared import macro, news_aggregator, patterns
from .._shared import signals
from .._shared import smc as smc_mod
from .._shared import ta as ta_mod


FOREX_RSS = (
    "https://www.investing.com/rss/news_25.rss",        # forex news
    "https://www.investing.com/rss/commodities_news.rss",
    "https://www.reuters.com/markets/currencies/rss",
)


def _dxy_overlay_vote(symbol: str) -> signals.Vote | None:
    """If symbol is USD-denominated, factor in DXY direction."""
    s = symbol.upper().replace("=X", "").replace("/", "")
    dxy = macro.dxy_snapshot()
    if not dxy.get("ok") or dxy.get("change_pct") is None:
        return None
    chg = dxy["change_pct"]
    # XXXUSD pair (e.g. EURUSD, GBPUSD): strong DXY → bearish for the pair.
    if s.endswith("USD"):
        if chg >= 0.5:
            return signals.Vote("DXY_BEARISH_FOR_PAIR", -1,
                f"DXY naik {chg:+.2f}% — USD menguat, biasanya pressure {s[:-3]}/USD turun.", weight=0.6)
        if chg <= -0.5:
            return signals.Vote("DXY_BULLISH_FOR_PAIR", +1,
                f"DXY turun {chg:+.2f}% — USD melemah, tailwind buat {s[:-3]}/USD.", weight=0.6)
    # USDXXX pair (e.g. USDJPY): strong DXY → bullish for the pair.
    if s.startswith("USD"):
        if chg >= 0.5:
            return signals.Vote("DXY_BULLISH_FOR_PAIR", +1,
                f"DXY naik {chg:+.2f}% — USD menguat, tailwind buat USD/{s[3:]}.", weight=0.6)
        if chg <= -0.5:
            return signals.Vote("DXY_BEARISH_FOR_PAIR", -1,
                f"DXY turun {chg:+.2f}% — USD melemah, pressure USD/{s[3:]}.", weight=0.6)
    # Commodity (Gold/Silver): historically inverse to DXY.
    if s in {"GOLD", "XAU", "XAG", "SILVER", "GC=F", "SI=F"}:
        if chg >= 0.5:
            return signals.Vote("DXY_BEAR_COMMOD", -1,
                f"DXY naik {chg:+.2f}% — USD kuat biasanya tekan precious metals.", weight=0.4)
        if chg <= -0.5:
            return signals.Vote("DXY_BULL_COMMOD", +1,
                f"DXY turun {chg:+.2f}% — USD lemah biasanya angkat precious metals.", weight=0.4)
    return None


def _calendar_warning(symbol: str) -> tuple[list[dict[str, Any]], bool]:
    """Return (events, has_high_impact_within_24h) for the symbol's currencies."""
    try:
        ev_payload = feeds.calendar_today(min_impact="medium")
    except Exception:
        return [], False
    events = ev_payload.get("items", []) if isinstance(ev_payload, dict) else []
    s = symbol.upper().replace("=X", "").replace("/", "")
    cur_set = set()
    for cur in ("USD", "EUR", "JPY", "GBP", "AUD", "CAD", "CHF", "NZD"):
        if cur in s:
            cur_set.add(cur)
    if "GOLD" in s or s in {"XAU", "GC=F"}:
        cur_set.add("USD")
    relevant = []
    has_high = False
    for ev in events:
        cur = (ev.get("currency") or "").upper()
        if cur_set and cur not in cur_set:
            continue
        if (ev.get("impact") or "").lower() == "high":
            has_high = True
        relevant.append(ev)
    return relevant, has_high


def evaluate(
    symbol: str,
    *,
    timeframe: str = "1d",
    limit: int = 300,
    risk_profile: str = "conservative",
    use_mtf: bool = False,
    use_news: bool = True,
    use_telegram: bool = True,
    use_smc: bool = True,
) -> dict[str, Any]:
    sym = symbol.upper()
    df = feeds.ohlcv(sym, timeframe=timeframe)
    if df.empty:
        return {"ok": False, "error": "no OHLCV data", "symbol": sym, "timeframe": timeframe}
    snap = ta_mod.snapshot(df, timeframe=timeframe)
    pat_list = patterns.detect(df)
    price_snap = feeds.quote(sym)
    kind = feeds.asset_kind(sym)

    mtf_snaps: dict[str, ta_mod.TASnapshot] | None = None
    if use_mtf:
        mtf_snaps = {}
        for tf in ("1w", "4h"):
            if tf == timeframe:
                continue
            try:
                df_hi = feeds.ohlcv(sym, timeframe=tf)
                if not df_hi.empty:
                    mtf_snaps[tf] = ta_mod.snapshot(df_hi, timeframe=tf)
            except Exception:
                pass

    sentiment = None
    news_payload: dict[str, Any] = {}
    if use_news:
        keywords = [sym]
        if kind == "forex":
            cur_a = sym[:3]
            cur_b = sym[3:6] if len(sym) >= 6 else ""
            keywords = [sym, cur_a, cur_b]
        elif kind == "commodity":
            label_map = {"GC=F": "gold", "SI=F": "silver", "CL=F": "oil", "BZ=F": "brent",
                         "NG=F": "natural gas", "HG=F": "copper"}
            keywords = [sym, label_map.get(sym.upper(), sym)]
        news_payload = news_aggregator.fetch(
            rss_feeds=FOREX_RSS,
            keywords=[k for k in keywords if k],
            use_telegram=use_telegram,
            tg_category="forex" if kind == "forex" else None,
            tg_tags=keywords,
            max_items=20,
        )
        sentiment = news_payload.get("agg_sentiment")

    relevant_events, has_high = _calendar_warning(sym)
    smc_summary = smc_mod.summarize(df) if use_smc else None
    ctx = signals.SignalContext(
        patterns=pat_list,
        sentiment_score=sentiment,
        mtf=mtf_snaps,
        calendar_events=relevant_events,
        asset_kind=kind or "forex",
        smc=smc_summary,
    )

    rec = signals.evaluate(
        snap,
        ctx=ctx,
        risk_profile=risk_profile,
        is_long_only=False,
        long_label="BUY",
        short_label="SELL",
    )

    # Add DXY overlay.
    dxy_vote = _dxy_overlay_vote(sym)
    if dxy_vote is not None:
        rec["score"] = round(rec.get("score", 0) + dxy_vote.direction * dxy_vote.weight, 2)
        rec["reasoning"] = list(rec.get("reasoning", [])) + [dxy_vote.reason]
        if dxy_vote.direction > 0:
            rec["bull_count"] = rec.get("bull_count", 0) + 1
        else:
            rec["bear_count"] = rec.get("bear_count", 0) + 1

    # High-impact event within 24h → demote to WAIT.
    if has_high and rec.get("recommendation") not in ("WAIT", "HOLD"):
        rec.setdefault("warnings", []).append(
            "High-impact event dalam 24 jam — volatile, demote ke WAIT sampe news pass."
        )
        rec["recommendation"] = "WAIT"

    # Re-gate after DXY adjustment.
    min_score, min_rr1 = {
        "conservative": (4.0, 2.0),
        "balanced": (2.5, 1.5),
        "aggressive": (1.0, 1.0),
    }[risk_profile]
    score = rec.get("score", 0)
    rr0 = (rec.get("risk_reward") or [None])[0]
    if abs(score) < min_score or (rr0 is not None and rr0 < min_rr1):
        if rec.get("recommendation") not in ("WAIT", "HOLD"):
            rec["recommendation"] = "WAIT"
            rec["entry_zone"] = None
            rec["stop_loss"] = None
            rec["take_profit"] = None
            rec["risk_reward"] = None

    price_now = price_snap.get("last")
    dxy_snap = macro.dxy_snapshot()

    extra_lines: list[str] = []
    if isinstance(dxy_snap, dict):
        dxy_last = dxy_snap.get("last")
        dxy_chg = dxy_snap.get("change_pct")
        if dxy_last is not None:
            try:
                dxy_last_f = float(dxy_last)
                bits = [f"DXY `{dxy_last_f:.2f}`"]
            except Exception:
                bits = [f"DXY `{dxy_last}`"]
            if dxy_chg is not None:
                bits.append(f"{dxy_chg:+.2f}%")
            extra_lines.append(" · ".join(bits))
    if smc_summary:
        zone = (smc_summary.get("zone") or {}).get("zone") if isinstance(smc_summary.get("zone"), dict) else None
        ob_n = len(smc_summary.get("order_blocks") or [])
        fvg_n = len(smc_summary.get("fvg") or [])
        sw_n = len(smc_summary.get("sweeps") or [])
        smc_bits = []
        if zone:
            smc_bits.append(f"zone {zone}")
        smc_bits.append(f"OB {ob_n}")
        smc_bits.append(f"FVG {fvg_n}")
        smc_bits.append(f"sweeps {sw_n}")
        extra_lines.append("SMC: " + " · ".join(smc_bits))
    if relevant_events:
        extra_lines.append(f"Events 24h: {len(relevant_events)} high-impact")
    if news_payload:
        nc = news_payload.get("counts") or {}
        ags = news_payload.get("agg_sentiment")
        tgu = news_payload.get("telegram_used")
        news_bits = []
        if ags is not None:
            news_bits.append(f"sentiment `{ags:+.2f}`")
        if nc:
            news_bits.append(f"{nc.get('positive', 0)}+/{nc.get('negative', 0)}-/{nc.get('neutral', 0)}n")
        if tgu:
            news_bits.append("Telegram ✓")
        if news_bits:
            extra_lines.append("News: " + " · ".join(news_bits))

    return {
        "ok": True,
        "skill": "forex_comm",
        "symbol": sym,
        "kind": kind,
        "timeframe": timeframe,
        "price": {k: price_snap.get(k) for k in (
            "last", "previous_close", "change_pct", "day_low", "day_high", "currency"
        )},
        "ta": snap.to_dict(),
        "patterns": pat_list,
        "dxy": dxy_snap,
        "events_today": relevant_events,
        "smc": smc_summary,
        "news_summary": {
            "agg_sentiment": news_payload.get("agg_sentiment"),
            "counts": news_payload.get("counts"),
            "telegram_used": news_payload.get("telegram_used"),
            "top": (news_payload.get("items") or [])[:5],
        } if use_news else None,
        "mtf_used": list(mtf_snaps.keys()) if mtf_snaps else [],
        "recommendation": rec,
        "summary": signals.summarize_recommendation(rec, symbol=sym, timeframe=timeframe),
        "format_telegram": signals.format_telegram_card(
            rec, symbol=sym, timeframe=timeframe, asset_kind="forex_comm",
            price_now=price_now, extra_lines=extra_lines,
        ),
    }
