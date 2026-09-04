"""Saham Indonesia recommendation logic.

Adds fundamental overlay on top of the asset-agnostic :mod:`signals` engine:
- PER vs sector benchmark (cheap valuation bonus when undervalued)
- Dividend yield (yield > 5% adds bullish weight for income angle)
- EPS / forward EPS direction
- IHSG composite context (avoid BUY when IHSG breaking down hard)
- News from Indonesian financial press + optional Telegram

Saham IDN is *cash market*, so the engine is restricted to ``is_long_only=True``
— we only emit BUY / HOLD, never SELL (you can't short Indonesian retail stocks).
"""

from __future__ import annotations

from typing import Any

from . import feeds
from .._shared import macro, news_aggregator, patterns
from .._shared import signals
from .._shared import ta as ta_mod


SAHAM_RSS = (
    "https://www.bisnis.com/rss",
    "https://www.kontan.co.id/rss/",
    "https://investasi.kontan.co.id/rss",
    "https://market.bisnis.com/rss",
)


# Rough sector PER medians (educational benchmark — refresh manually as needed).
SECTOR_PER_BENCHMARK = {
    "Financial Services": 10.0,
    "Energy": 8.0,
    "Basic Materials": 12.0,
    "Industrials": 14.0,
    "Consumer Defensive": 18.0,
    "Consumer Cyclical": 15.0,
    "Healthcare": 22.0,
    "Technology": 25.0,
    "Communication Services": 14.0,
    "Real Estate": 12.0,
    "Utilities": 13.0,
}


def _fundamental_votes(qd: dict[str, Any]) -> list[signals.Vote]:
    """Append fundamental-flavoured votes for saham IDN."""
    out: list[signals.Vote] = []
    sector = qd.get("sector") or ""
    per = qd.get("pe_ratio")
    fwd_per = qd.get("forward_pe")
    dyld = qd.get("dividend_yield")
    eps_t = qd.get("eps_trailing")
    eps_f = qd.get("eps_forward")

    if per and sector:
        bench = SECTOR_PER_BENCHMARK.get(sector)
        if bench:
            if per <= bench * 0.7:
                out.append(signals.Vote("PER_UNDERVALUED", +1,
                    f"PER {per:.1f} di bawah median sektor {sector} ({bench:.1f}) — relatively undervalued.", weight=0.8))
            elif per >= bench * 1.5:
                out.append(signals.Vote("PER_EXPENSIVE", -1,
                    f"PER {per:.1f} di atas 1.5× median sektor {sector} ({bench:.1f}) — premium pricing.", weight=0.5))

    if dyld is not None:
        # yfinance dividend_yield bisa di-format dua cara (sebagai pecahan 0..1 atau persen 0..100).
        # Normalize ke persen.
        dy_pct = dyld * 100 if dyld < 1 else dyld
        if dy_pct >= 7:
            out.append(signals.Vote("HIGH_DIVIDEND", +1,
                f"Dividend yield {dy_pct:.1f}% — income play kuat.", weight=0.6))
        elif dy_pct >= 4:
            out.append(signals.Vote("DECENT_DIVIDEND", +1,
                f"Dividend yield {dy_pct:.1f}%.", weight=0.3))

    if eps_t is not None and eps_f is not None and eps_t > 0:
        delta = (eps_f - eps_t) / abs(eps_t) * 100
        if delta >= 10:
            out.append(signals.Vote("EPS_GROWING", +1,
                f"Forward EPS {eps_f:.0f} > trailing {eps_t:.0f} ({delta:+.1f}%) — pertumbuhan diproyeksikan naik.", weight=0.5))
        elif delta <= -10:
            out.append(signals.Vote("EPS_SHRINKING", -1,
                f"Forward EPS {eps_f:.0f} < trailing {eps_t:.0f} ({delta:+.1f}%) — pertumbuhan diproyeksikan turun.", weight=0.5))
    return out


def _ihsg_context_vote() -> signals.Vote | None:
    """Penalise BUY when IHSG falling >2% (broad risk-off)."""
    try:
        ih = macro.ihsg_snapshot()
        if not ih.get("ok"):
            return None
        chg = ih.get("change_pct")
        if chg is None:
            return None
        if chg <= -2.0:
            return signals.Vote("IHSG_RISK_OFF", -1,
                f"IHSG turun {chg:.2f}% hari ini — risk-off broad market, kurangi exposure.", weight=0.6)
        if chg >= 1.5:
            return signals.Vote("IHSG_RISK_ON", +1,
                f"IHSG naik {chg:.2f}% hari ini — risk-on, tailwind buat saham individu.", weight=0.3)
    except Exception:
        return None
    return None


def evaluate(
    symbol: str,
    *,
    timeframe: str = "1d",
    limit: int = 300,
    risk_profile: str = "conservative",
    use_mtf: bool = False,
    use_news: bool = True,
    use_telegram: bool = True,
) -> dict[str, Any]:
    t = feeds.normalize_ticker(symbol)
    df = feeds.ohlcv(t, timeframe=timeframe)
    if df.empty:
        return {"ok": False, "error": "no OHLCV data", "symbol": t, "timeframe": timeframe}
    snap = ta_mod.snapshot(df, timeframe=timeframe)
    pat_list = patterns.detect(df)
    qd = feeds.quote(t)

    mtf_snaps: dict[str, ta_mod.TASnapshot] | None = None
    if use_mtf:
        mtf_snaps = {}
        for tf in ("1wk", "1h"):
            if tf == timeframe:
                continue
            try:
                df_hi = feeds.ohlcv(t, timeframe=tf)
                if not df_hi.empty:
                    mtf_snaps[tf] = ta_mod.snapshot(df_hi, timeframe=tf)
            except Exception:
                pass

    sentiment = None
    news_payload: dict[str, Any] = {}
    if use_news:
        ticker_no_suffix = t.replace(".JK", "")
        company_name = (qd.get("name") or "").split(" ")[0] if qd else ""
        news_payload = news_aggregator.fetch(
            rss_feeds=SAHAM_RSS,
            keywords=[ticker_no_suffix, company_name] if company_name else [ticker_no_suffix],
            use_telegram=use_telegram,
            tg_category="saham",
            tg_tags=[ticker_no_suffix],
            max_items=20,
        )
        sentiment = news_payload.get("agg_sentiment")

    ctx = signals.SignalContext(
        fundamentals=qd,
        patterns=pat_list,
        sentiment_score=sentiment,
        mtf=mtf_snaps,
        asset_kind="saham",
    )

    # Run the core engine first, then inject fundamental + macro votes manually
    # so they appear in reasoning and influence the score gate.
    rec = signals.evaluate(
        snap,
        ctx=ctx,
        risk_profile=risk_profile,
        is_long_only=True,
        long_label="BUY",
        short_label="SELL",
    )
    extra_votes = _fundamental_votes(qd)
    ih_vote = _ihsg_context_vote()
    if ih_vote is not None:
        extra_votes.append(ih_vote)
    if extra_votes:
        extra_score = sum(v.direction * v.weight for v in extra_votes)
        rec["score"] = round(rec.get("score", 0) + extra_score, 2)
        rec["reasoning"] = list(rec.get("reasoning", [])) + [
            v.reason for v in extra_votes if v.direction != 0
        ]
        rec["bull_count"] = rec.get("bull_count", 0) + sum(1 for v in extra_votes if v.direction > 0)
        rec["bear_count"] = rec.get("bear_count", 0) + sum(1 for v in extra_votes if v.direction < 0)

        # Re-evaluate verdict against risk gate after fundamental injection.
        min_score, min_rr1 = {
            "conservative": (4.0, 2.0),
            "balanced": (2.5, 1.5),
            "aggressive": (1.0, 1.0),
        }[risk_profile]
        score = rec["score"]
        rr0 = (rec.get("risk_reward") or [None])[0]
        if score >= min_score and (rr0 is None or rr0 >= min_rr1):
            rec["recommendation"] = "BUY"
            abs_s = abs(score)
            rec["confidence"] = "high" if abs_s >= 4 else "medium" if abs_s >= 2.5 else "low"
        else:
            # Demote — saham is long-only so anything below the BUY gate is HOLD.
            if rec.get("recommendation") == "BUY":
                rec["recommendation"] = "HOLD"
                rec["entry_zone"] = None
                rec["stop_loss"] = None
                rec["take_profit"] = None
                rec["risk_reward"] = None

    price_now = qd.get("last")
    ihsg_snap = macro.ihsg_snapshot()

    extra_lines: list[str] = []
    if isinstance(ihsg_snap, dict):
        ihsg_last = ihsg_snap.get("last")
        ihsg_chg = ihsg_snap.get("change_pct")
        if ihsg_last is not None:
            try:
                ihsg_last_f = float(ihsg_last)
                bits = [f"IHSG `{ihsg_last_f:,.2f}`"]
            except Exception:
                bits = [f"IHSG `{ihsg_last}`"]
            if ihsg_chg is not None:
                bits.append(f"{ihsg_chg:+.2f}%")
            extra_lines.append(" · ".join(bits))
    per = qd.get("pe_ratio")
    dy = qd.get("dividend_yield")
    fund_bits = []
    if per is not None:
        try:
            fund_bits.append(f"PER `{float(per):.2f}`")
        except Exception:
            fund_bits.append(f"PER `{per}`")
    if dy is not None:
        try:
            fund_bits.append(f"divyield `{float(dy):.2f}%`")
        except Exception:
            fund_bits.append(f"divyield `{dy}%`")
    if fund_bits:
        extra_lines.append("Fundamental: " + " · ".join(fund_bits))
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
        "skill": "saham_idn",
        "symbol": t,
        "timeframe": timeframe,
        "fundamentals": {k: qd.get(k) for k in (
            "name", "sector", "industry", "currency",
            "last", "previous_close", "change_pct",
            "market_cap", "pe_ratio", "forward_pe",
            "eps_trailing", "eps_forward", "dividend_yield", "book_value",
            "year_low", "year_high",
        )},
        "ta": snap.to_dict(),
        "patterns": pat_list,
        "ihsg": ihsg_snap,
        "news_summary": {
            "agg_sentiment": news_payload.get("agg_sentiment"),
            "counts": news_payload.get("counts"),
            "telegram_used": news_payload.get("telegram_used"),
            "top": (news_payload.get("items") or [])[:5],
        } if use_news else None,
        "mtf_used": list(mtf_snaps.keys()) if mtf_snaps else [],
        "recommendation": rec,
        "summary": signals.summarize_recommendation(rec, symbol=t, timeframe=timeframe),
        "format_telegram": signals.format_telegram_card(
            rec, symbol=t, timeframe=timeframe, asset_kind="saham_idn",
            price_now=price_now, extra_lines=extra_lines,
        ),
    }
