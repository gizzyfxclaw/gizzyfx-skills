"""Crypto skill CLI.

Subcommands: price, ta, analyze, news, compare, watchlist.

All output is single-line JSON to stdout, suitable for piping to Hermes.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

from . import feeds
from . import recommend as recommend_mod
from .._shared import backtest as backtest_mod
from .._shared import chart as chart_mod
from .._shared import patterns as patterns_mod
from .._shared import signals as signals_mod
from .._shared import smc as smc_mod
from .._shared import ta as ta_mod
from .._shared import llm_summary
from .._shared.output import (
    emit, emit_error, emit_tg,
    watchlist_add, watchlist_load, watchlist_remove,
)


SKILL = "crypto"


# ---------- subcommands ----------

def cmd_price(args: argparse.Namespace) -> None:
    p = feeds.cg_price(args.symbol)
    emit(p)


def cmd_ta(args: argparse.Namespace) -> None:
    df = feeds.ohlcv(args.symbol, timeframe=args.tf, limit=args.limit)
    if df.empty:
        return emit_error("no OHLCV data", symbol=args.symbol, tf=args.tf)
    snap = ta_mod.snapshot(df, timeframe=args.tf)
    emit({
        "ok": True, "skill": SKILL, "symbol": args.symbol.upper(),
        "timeframe": args.tf, "ta": snap.to_dict(),
    })


def cmd_analyze(args: argparse.Namespace) -> None:
    sym = args.symbol.upper()
    price = feeds.cg_price(sym)
    md = feeds.cg_market_data(sym)
    df = feeds.ohlcv(sym, timeframe=args.tf, limit=args.limit)
    if df.empty:
        return emit_error("no OHLCV data", symbol=sym, tf=args.tf)
    snap = ta_mod.snapshot(df, timeframe=args.tf)
    chart_path: str | None = None
    if args.chart:
        try:
            chart_path = chart_mod.candlestick(
                df, title=f"{sym} {args.tf}", overlays=("EMA20", "EMA50", "EMA200"),
                show_bb=True, show_volume=True, last_n=120,
            )
        except Exception as e:
            chart_path = None
    fng = feeds.fear_greed() if args.fng else None
    news = feeds.cryptopanic_news(query=sym, limit=5) if args.news else None

    # Also compute full recommendation + telegram card so Hermes can show
    # a verdict + entry/SL/TP even when the user types "analisa <symbol>".
    rec_payload: dict[str, Any] | None = None
    try:
        rec_payload = recommend_mod.evaluate(
            sym, timeframe=args.tf, limit=args.limit,
            risk_profile="conservative",
            use_mtf=False, use_news=bool(args.news), use_telegram=True, use_smc=True,
        )
    except Exception:
        rec_payload = None

    payload: dict[str, Any] = {
        "ok": True,
        "skill": SKILL,
        "symbol": sym,
        "timeframe": args.tf,
        "price": {k: price.get(k) for k in (
            "price_usd", "price_idr", "market_cap_usd", "volume_24h_usd", "change_24h_pct"
        )},
        "market": {k: md.get(k) for k in (
            "name", "rank", "ath_usd", "ath_change_pct", "circulating_supply", "max_supply"
        )},
        "ta": snap.to_dict(),
        "fear_greed": fng,
        "news": news,
        "chart_path": chart_path,
    }
    if rec_payload and rec_payload.get("ok"):
        payload["recommendation"] = rec_payload.get("recommendation")
        payload["smc"] = rec_payload.get("smc")
        payload["news_summary"] = rec_payload.get("news_summary")
        payload["format_telegram"] = rec_payload.get("format_telegram")
        payload["summary"] = rec_payload.get("summary")
    if args.narrative:
        payload["narrative"] = llm_summary.summarize(payload)
    if getattr(args, "tg", False):
        emit_tg(payload)
    else:
        emit(payload)


def cmd_news(args: argparse.Namespace) -> None:
    n = feeds.cryptopanic_news(query=args.symbol, limit=args.limit)
    emit(n)


def cmd_compare(args: argparse.Namespace) -> None:
    out: dict[str, Any] = {"ok": True, "skill": SKILL, "tf": args.tf, "items": {}}
    for sym in (args.a, args.b):
        df = feeds.ohlcv(sym, timeframe=args.tf, limit=args.limit)
        price = feeds.cg_price(sym)
        if df.empty:
            out["items"][sym.upper()] = {"ok": False, "error": "no data"}
            continue
        snap = ta_mod.snapshot(df, timeframe=args.tf)
        out["items"][sym.upper()] = {
            "price": price.get("price_usd"),
            "change_24h_pct": price.get("change_24h_pct"),
            "rsi_14": snap.rsi_14,
            "trend_state": snap.trend_state,
            "macd_state": snap.macd_state,
        }
    emit(out)


def cmd_recommend(args: argparse.Namespace) -> None:
    rec = recommend_mod.evaluate(
        args.symbol,
        timeframe=args.tf,
        limit=args.limit,
        risk_profile=args.risk,
        use_mtf=args.mtf,
        use_news=args.news,
        use_telegram=args.telegram,
        use_smc=args.smc,
    )
    if args.narrative and rec.get("ok"):
        rec["narrative"] = llm_summary.summarize(rec)
    if getattr(args, "tg", False):
        emit_tg(rec)
    else:
        emit(rec)


def cmd_backtest(args: argparse.Namespace) -> None:
    sym = args.symbol.upper()
    df = feeds.ohlcv(sym, timeframe=args.tf, limit=args.limit)
    if df.empty:
        return emit_error("no OHLCV data", symbol=sym, tf=args.tf)

    risk_profile = args.risk
    use_smc = args.smc

    def signal_fn(d):
        """Run the rule engine on a historical slice (no live macro/news).

        Skips macro/news/Telegram so the backtest is repeatable and offline.
        """
        snap = ta_mod.snapshot(d, timeframe=args.tf)
        pat = patterns_mod.detect(d)
        smc_summary = smc_mod.summarize(d) if use_smc else None
        ctx = signals_mod.SignalContext(
            patterns=pat,
            asset_kind="crypto",
            smc=smc_summary,
        )
        return signals_mod.evaluate(
            snap, ctx=ctx, risk_profile=risk_profile,
            is_long_only=False, long_label="LONG", short_label="SHORT",
        )

    result = backtest_mod.run_backtest(
        df, signal_fn,
        symbol=sym, timeframe=args.tf,
        warmup=args.warmup, max_hold=args.max_hold,
        entry_mode=args.entry_mode, cooldown=args.cooldown,
    )
    payload = result.to_dict()
    payload["profile"] = risk_profile
    payload["smc_used"] = use_smc
    if args.no_trades:
        payload.pop("trades", None)
    emit(payload)


def cmd_watchlist(args: argparse.Namespace) -> None:
    if args.action == "list":
        emit({"ok": True, "skill": SKILL, "items": watchlist_load(SKILL)})
    elif args.action == "add":
        emit({"ok": True, "skill": SKILL, "items": watchlist_add(SKILL, args.symbol)})
    elif args.action == "rm":
        emit({"ok": True, "skill": SKILL, "items": watchlist_remove(SKILL, args.symbol)})
    else:
        emit_error(f"unknown watchlist action: {args.action}")


# ---------- parser ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="skills.crypto.analyze", description="Crypto market analysis")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("price"); sp.add_argument("symbol"); sp.set_defaults(fn=cmd_price)

    st = sub.add_parser("ta"); st.add_argument("symbol")
    st.add_argument("--tf", default="1d"); st.add_argument("--limit", type=int, default=300)
    st.set_defaults(fn=cmd_ta)

    sa = sub.add_parser("analyze"); sa.add_argument("symbol")
    sa.add_argument("--tf", default="1d"); sa.add_argument("--limit", type=int, default=300)
    sa.add_argument("--no-chart", dest="chart", action="store_false", default=True)
    sa.add_argument("--no-news", dest="news", action="store_false", default=True)
    sa.add_argument("--no-fng", dest="fng", action="store_false", default=True)
    sa.add_argument("--no-narrative", dest="narrative", action="store_false", default=True)
    sa.add_argument("--tg", action="store_true", default=False,
                    help="plain-text Telegram card only (no JSON)")
    sa.set_defaults(fn=cmd_analyze)

    sn = sub.add_parser("news"); sn.add_argument("symbol", nargs="?", default="")
    sn.add_argument("--limit", type=int, default=10); sn.set_defaults(fn=cmd_news)

    sc = sub.add_parser("compare"); sc.add_argument("a"); sc.add_argument("b")
    sc.add_argument("--tf", default="1d"); sc.add_argument("--limit", type=int, default=300)
    sc.set_defaults(fn=cmd_compare)

    sw = sub.add_parser("watchlist"); sw.add_argument("action", choices=["list", "add", "rm"])
    sw.add_argument("symbol", nargs="?", default=""); sw.set_defaults(fn=cmd_watchlist)

    sr = sub.add_parser("recommend"); sr.add_argument("symbol")
    sr.add_argument("--tf", default="1d")
    sr.add_argument("--limit", type=int, default=300)
    sr.add_argument("--risk", choices=["conservative", "balanced", "aggressive"], default="conservative")
    sr.add_argument("--mtf", action="store_true", default=False)
    sr.add_argument("--tg", action="store_true", default=False,
                    help="plain-text Telegram card only (no JSON)")
    sr.add_argument("--no-smc", dest="smc", action="store_false", default=True,
                    help="Disable Smart Money Concepts overlay (default ON for crypto).")
    sr.add_argument("--no-news", dest="news", action="store_false", default=True)
    sr.add_argument("--no-telegram", dest="telegram", action="store_false", default=True)
    sr.add_argument("--no-narrative", dest="narrative", action="store_false", default=True)
    sr.set_defaults(fn=cmd_recommend)

    sb = sub.add_parser("backtest"); sb.add_argument("symbol")
    sb.add_argument("--tf", default="1d")
    sb.add_argument("--limit", type=int, default=1000)
    sb.add_argument("--risk", choices=["conservative", "balanced", "aggressive"], default="balanced")
    sb.add_argument("--no-smc", dest="smc", action="store_false", default=True,
                    help="Disable SMC layer in backtest (default ON).")
    sb.add_argument("--warmup", type=int, default=250)
    sb.add_argument("--max-hold", type=int, default=20, dest="max_hold")
    sb.add_argument("--cooldown", type=int, default=1)
    sb.add_argument("--entry-mode", dest="entry_mode",
                    choices=["next_open", "close"], default="next_open")
    sb.add_argument("--no-trades", dest="no_trades", action="store_true", default=False,
                    help="Omit per-trade list in output; metrics only.")
    sb.set_defaults(fn=cmd_backtest)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.fn(args)
        return 0
    except Exception as e:
        emit_error(f"{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
