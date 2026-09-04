"""Crypto-specific recommendation logic.

Builds on :mod:`skills._shared.signals` and adds crypto-specific context:
- BTC market-cap dominance (rotation cues)
- Binance perp funding rate (overcrowded long/short)
- alternative.me Fear & Greed Index
- News + Telegram channel sentiment

Output: LONG / SHORT / WAIT verdicts (with optional leverage suggestion).
"""

from __future__ import annotations

from typing import Any, Iterable

from . import feeds
from .._shared import macro, news_aggregator, patterns
from .._shared import signals
from .._shared import smc as smc_mod
from .._shared import ta as ta_mod


CRYPTO_RSS = (
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
    "https://cryptoslate.com/feed/",
)


def _leverage_suggestion(score: float, risk_profile: str) -> int:
    """Heuristic leverage cap based on confidence + risk profile."""
    abs_s = abs(score)
    if risk_profile == "conservative":
        if abs_s >= 5:
            return 3
        if abs_s >= 4:
            return 2
        return 1
    if risk_profile == "balanced":
        if abs_s >= 5:
            return 5
        if abs_s >= 4:
            return 3
        if abs_s >= 3:
            return 2
        return 1
    if risk_profile == "aggressive":
        if abs_s >= 5:
            return 10
        if abs_s >= 3:
            return 5
        return 2
    return 1


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
    df = feeds.ohlcv(sym, timeframe=timeframe, limit=limit)
    if df.empty:
        return {"ok": False, "error": "no OHLCV data", "symbol": sym, "timeframe": timeframe}

    snap = ta_mod.snapshot(df, timeframe=timeframe)
    pat_list = patterns.detect(df)

    mtf_snaps: dict[str, ta_mod.TASnapshot] | None = None
    if use_mtf:
        mtf_snaps = {}
        for tf in ("1w", "4h"):
            if tf == timeframe:
                continue
            try:
                df_hi = feeds.ohlcv(sym, timeframe=tf, limit=200)
                if not df_hi.empty:
                    mtf_snaps[tf] = ta_mod.snapshot(df_hi, timeframe=tf)
            except Exception:
                pass

    # Crypto-specific macro / sentiment.
    funding = None
    try:
        f = macro.binance_funding_rate(symbol=f"{sym}USDT")
        if f.get("ok"):
            funding = f.get("funding_rate_pct")
    except Exception:
        pass
    fng = None
    try:
        fg = macro.fear_greed_index()
        if fg.get("ok"):
            fng = fg.get("value")
    except Exception:
        pass

    sentiment = None
    news_payload: dict[str, Any] = {}
    if use_news:
        news_payload = news_aggregator.fetch(
            rss_feeds=CRYPTO_RSS,
            keywords=[sym, sym.lower(), feeds.to_coingecko_id(sym)],
            use_telegram=use_telegram,
            tg_category="crypto",
            tg_tags=[sym],
            max_items=20,
        )
        sentiment = news_payload.get("agg_sentiment")

    smc_summary = smc_mod.summarize(df) if use_smc else None

    ctx = signals.SignalContext(
        patterns=pat_list,
        sentiment_score=sentiment,
        macro={"funding_rate_pct": funding},
        funding_rate=funding,
        fear_greed=fng,
        mtf=mtf_snaps,
        asset_kind="crypto",
        smc=smc_summary,
    )

    rec = signals.evaluate(
        snap,
        ctx=ctx,
        risk_profile=risk_profile,
        is_long_only=False,
        long_label="LONG",
        short_label="SHORT",
    )
    if rec.get("recommendation") in ("LONG", "SHORT"):
        rec["suggested_leverage_x"] = _leverage_suggestion(rec["score"], risk_profile)

    price_snap = feeds.cg_price(sym)
    price_now = price_snap.get("price_usd")

    extra_lines: list[str] = []
    if funding is not None:
        extra_lines.append(f"funding: `{funding:+.4f}%` · F&G `{fng}`" if fng is not None
                          else f"funding: `{funding:+.4f}%`")
    elif fng is not None:
        extra_lines.append(f"F&G `{fng}`")
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
        "skill": "crypto",
        "symbol": sym,
        "timeframe": timeframe,
        "price": {k: price_snap.get(k) for k in (
            "price_usd", "price_idr", "change_24h_pct", "market_cap_usd", "volume_24h_usd"
        )},
        "ta": snap.to_dict(),
        "patterns": pat_list,
        "funding_rate_pct": funding,
        "fear_greed": fng,
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
            rec, symbol=sym, timeframe=timeframe, asset_kind="crypto",
            price_now=price_now, extra_lines=extra_lines,
        ),
    }
