"""Saham Indonesia (IDX) skill CLI.

Subcommands: price, ta, analyze, news, compare, watchlist, ihsg.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from . import feeds
from . import recommend as recommend_mod
from .._shared import chart as chart_mod
from .._shared import ta as ta_mod
from .._shared import llm_summary
from .._shared.output import (
    emit, emit_error, emit_tg,
    watchlist_add, watchlist_load, watchlist_remove,
)


SKILL = "saham_idn"


def cmd_price(args: argparse.Namespace) -> None:
    emit(feeds.quote(args.symbol))


def cmd_ihsg(args: argparse.Namespace) -> None:
    emit(feeds.ihsg())


def cmd_ta(args: argparse.Namespace) -> None:
    df = feeds.ohlcv(args.symbol, timeframe=args.tf)
    if df.empty:
        return emit_error("no OHLCV data", symbol=args.symbol, tf=args.tf)
    snap = ta_mod.snapshot(df, timeframe=args.tf)
    emit({"ok": True, "skill": SKILL, "symbol": feeds.normalize_ticker(args.symbol),
          "timeframe": args.tf, "ta": snap.to_dict()})


def cmd_analyze(args: argparse.Namespace) -> None:
    sym = feeds.normalize_ticker(args.symbol)
    q = feeds.quote(args.symbol)
    df = feeds.ohlcv(args.symbol, timeframe=args.tf)
    if df.empty:
        return emit_error("no OHLCV data", symbol=sym, tf=args.tf)
    snap = ta_mod.snapshot(df, timeframe=args.tf)
    chart_path: str | None = None
    if args.chart:
        try:
            chart_path = chart_mod.candlestick(
                df, title=f"{sym} {args.tf}",
                overlays=("EMA20", "EMA50", "EMA200"),
                show_bb=True, show_volume=True, last_n=120,
            )
        except Exception:
            chart_path = None
    news_out = feeds.news(args.symbol.replace(".JK", "").upper(), limit=5) if args.news else None
    ihsg_snap = feeds.ihsg() if args.ihsg else None

    rec_payload: dict[str, Any] | None = None
    try:
        rec_payload = recommend_mod.evaluate(
            args.symbol, timeframe=args.tf,
            risk_profile="conservative",
            use_mtf=False, use_news=bool(args.news), use_telegram=True,
        )
    except Exception:
        rec_payload = None

    payload: dict[str, Any] = {
        "ok": True, "skill": SKILL, "symbol": sym, "timeframe": args.tf,
        "fundamentals": {k: q.get(k) for k in (
            "name", "sector", "industry", "last", "previous_close", "change_pct",
            "year_low", "year_high", "market_cap", "pe_ratio", "forward_pe",
            "eps_trailing", "eps_forward", "dividend_yield", "book_value",
        )},
        "ihsg": ihsg_snap,
        "ta": snap.to_dict(),
        "news": news_out,
        "chart_path": chart_path,
    }
    if rec_payload and rec_payload.get("ok"):
        payload["recommendation"] = rec_payload.get("recommendation")
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
    emit(feeds.news(args.symbol, limit=args.limit))


def cmd_compare(args: argparse.Namespace) -> None:
    out: dict[str, Any] = {"ok": True, "skill": SKILL, "tf": args.tf, "items": {}}
    for sym in (args.a, args.b):
        q = feeds.quote(sym)
        df = feeds.ohlcv(sym, timeframe=args.tf)
        norm = feeds.normalize_ticker(sym)
        if df.empty:
            out["items"][norm] = {"ok": False, "error": "no data"}
            continue
        snap = ta_mod.snapshot(df, timeframe=args.tf)
        out["items"][norm] = {
            "last": q.get("last"),
            "change_pct": q.get("change_pct"),
            "pe_ratio": q.get("pe_ratio"),
            "dividend_yield": q.get("dividend_yield"),
            "rsi_14": snap.rsi_14,
            "trend_state": snap.trend_state,
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
    )
    if args.narrative and rec.get("ok"):
        rec["narrative"] = llm_summary.summarize(rec)
    if getattr(args, "tg", False):
        emit_tg(rec)
    else:
        emit(rec)


def cmd_watchlist(args: argparse.Namespace) -> None:
    if args.action == "list":
        emit({"ok": True, "skill": SKILL, "items": watchlist_load(SKILL) or feeds.DEFAULT_WATCHLIST})
    elif args.action == "add":
        emit({"ok": True, "skill": SKILL, "items": watchlist_add(SKILL, args.symbol)})
    elif args.action == "rm":
        emit({"ok": True, "skill": SKILL, "items": watchlist_remove(SKILL, args.symbol)})
    else:
        emit_error(f"unknown watchlist action: {args.action}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="skills.saham_idn.analyze",
                                description="Indonesian stock (IDX) market analysis")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("price"); sp.add_argument("symbol"); sp.set_defaults(fn=cmd_price)
    si = sub.add_parser("ihsg"); si.set_defaults(fn=cmd_ihsg)

    st = sub.add_parser("ta"); st.add_argument("symbol")
    st.add_argument("--tf", default="1d"); st.set_defaults(fn=cmd_ta)

    sa = sub.add_parser("analyze"); sa.add_argument("symbol")
    sa.add_argument("--tf", default="1d")
    sa.add_argument("--no-chart", dest="chart", action="store_false", default=True)
    sa.add_argument("--no-news", dest="news", action="store_false", default=True)
    sa.add_argument("--no-ihsg", dest="ihsg", action="store_false", default=True)
    sa.add_argument("--no-narrative", dest="narrative", action="store_false", default=True)
    sa.add_argument("--tg", action="store_true", default=False,
                    help="plain-text Telegram card only (no JSON)")
    sa.set_defaults(fn=cmd_analyze)

    sn = sub.add_parser("news"); sn.add_argument("symbol", nargs="?", default="")
    sn.add_argument("--limit", type=int, default=10); sn.set_defaults(fn=cmd_news)

    sc = sub.add_parser("compare"); sc.add_argument("a"); sc.add_argument("b")
    sc.add_argument("--tf", default="1d"); sc.set_defaults(fn=cmd_compare)

    sw = sub.add_parser("watchlist"); sw.add_argument("action", choices=["list", "add", "rm"])
    sw.add_argument("symbol", nargs="?", default=""); sw.set_defaults(fn=cmd_watchlist)

    sr = sub.add_parser("recommend"); sr.add_argument("symbol")
    sr.add_argument("--tf", default="1d")
    sr.add_argument("--limit", type=int, default=300)
    sr.add_argument("--risk", choices=["conservative", "balanced", "aggressive"], default="conservative")
    sr.add_argument("--mtf", action="store_true", default=False)
    sr.add_argument("--tg", action="store_true", default=False,
                    help="plain-text Telegram card only (no JSON)")
    sr.add_argument("--no-news", dest="news", action="store_false", default=True)
    sr.add_argument("--no-telegram", dest="telegram", action="store_false", default=True)
    sr.add_argument("--no-narrative", dest="narrative", action="store_false", default=True)
    sr.set_defaults(fn=cmd_recommend)

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
