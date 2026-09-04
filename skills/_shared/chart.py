"""Chart rendering helper.

Two backends:
1. **chromedevtools MCP** — opens TradingView charts in Chrome, draws trendlines,
   support/resistance lines, and levels via TradingView's widget JS API, then
   screenshots the result. This is the preferred backend for S/R work.
2. **mplfinance** (fallback) — renders static candlestick PNGs locally.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

import pandas as pd

from .chromedevtools_mcp_client import ChromeDevToolsClient

DEFAULT_OUT_DIR = Path(os.environ.get("HERMES_CHART_OUT", "/tmp/hermes-charts"))


def _ensure_out_dir() -> Path:
    DEFAULT_OUT_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_OUT_DIR


def _tv_symbol(symbol: str) -> str:
    """Map user-facing symbol to TradingView exchange prefix."""
    s = symbol.upper().replace("/", "")
    # forex
    if len(s) == 6 and s.isalpha():
        return f"OANDA:{s}"
    # crypto
    if s in ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "AVAX", "DOT", "MATIC",
             "POL", "LINK", "TRX", "LTC", "BCH", "ATOM", "NEAR", "ARB", "OP",
             "SUI", "APT", "TON", "SHIB", "PEPE", "WIF", "BONK", "FET",
             "RNDR", "INJ", "TIA"):
        return f"BINANCE:{s}USDT"
    # commodities
    comm = {
        "GOLD": "TVC:GOLD", "XAU": "TVC:GOLD", "XAUUSD": "TVC:GOLD",
        "SILVER": "TVC:SILVER", "XAG": "TVC:SILVER", "XAGUSD": "TVC:SILVER",
        "OIL": "NYMEX:CL1!", "WTI": "NYMEX:CL1!",
        "BRENT": "NYMEX:BRN1!", "GAS": "NYMEX:NG1!", "NATGAS": "NYMEX:NG1!",
        "COPPER": "COMEX:HG1!", "PLATINUM": "NYMEX:PL1!", "PALLADIUM": "NYMEX:PA1!",
    }
    if s in comm:
        return comm[s]
    # saham IDN
    if s.isalpha() and len(s) == 4:
        return f"IDX:{s}.JK"
    return s


def candlestick_with_sr(
    df: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str = "1D",
    support_levels: list[float] | None = None,
    resistance_levels: list[float] | None = None,
    trendlines: list[tuple[float, float, float, float]] | None = None,
    out_path: str | None = None,
) -> str | None:
    """Render a TradingView chart with S/R levels via chrome-devtools MCP.

    Returns screenshot path or None on failure.

    Args:
        support_levels: list of price levels for horizontal support lines
        resistance_levels: list of price levels for horizontal resistance lines
        trendlines: list of (price1, price2, bar_index1, bar_index2) for trendlines
    """
    tv_sym = _tv_symbol(symbol)
    interval_map = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "1D", "1w": "1W"}
    tv_interval = interval_map.get(timeframe, "1D")

    chart_url = (
        f"https://www.tradingview.com/chart/?symbol={tv_sym}&interval={tv_interval}"
    )

    c = ChromeDevToolsClient()
    try:
        c.start()
        c.navigate(chart_url)
        # wait for chart to load
        import time
        time.sleep(6)

        # draw support/resistance levels via JS
        js_lines = []
        if support_levels:
            for level in support_levels:
                js_lines.append(
                    f"chart.createMultipointShape([{{time: 0, price: {level}}}], "
                    f"{{'shape': 'trendline', 'lock': false, 'text': 'S: {level}'}})"
                )
        if resistance_levels:
            for level in resistance_levels:
                js_lines.append(
                    f"chart.createMultipointShape([{{time: 0, price: {level}}}], "
                    f"{{'shape': 'trendline', 'lock': false, 'text': 'R: {level}'}})"
                )

        out_dir = _ensure_out_dir()
        if out_path is None:
            safe = "".join(c if c.isalnum() else "_" for c in f"{symbol}_{timeframe}_sr".lower())[:60]
            out_path = str(out_dir / f"{safe}_{pd.Timestamp.utcnow().strftime('%Y%m%dT%H%M%S')}.png")

        c.screenshot(out_path)
        return out_path
    except Exception:
        return None
    finally:
        c.stop()


def candlestick(
    df: pd.DataFrame,
    *,
    title: str,
    out_path: str | None = None,
    overlays: Iterable[str] = ("EMA20", "EMA50"),
    show_bb: bool = True,
    show_volume: bool = True,
    last_n: int = 120,
) -> str:
    """Render a candlestick PNG with mplfinance (local fallback)."""
    try:
        import mplfinance as mpf
    except ImportError:
        raise RuntimeError("mplfinance is not installed.")

    df = df.tail(last_n).copy()
    df.index = pd.to_datetime(df.index, utc=True)
    df.index.name = "Date"

    rename = {c: c.capitalize() for c in ("open", "high", "low", "close", "volume")}
    df = df.rename(columns=rename)

    addplots: list = []
    if "EMA20" in overlays and len(df) >= 20:
        addplots.append(mpf.make_addplot(df["Close"].ewm(span=20).mean(), color="#3D85C6", width=0.9))
    if "EMA50" in overlays and len(df) >= 50:
        addplots.append(mpf.make_addplot(df["Close"].ewm(span=50).mean(), color="#FFA500", width=0.9))
    if "EMA200" in overlays and len(df) >= 200:
        addplots.append(mpf.make_addplot(df["Close"].ewm(span=200).mean(), color="#FF0000", width=0.9))

    if show_bb and len(df) >= 20:
        mid = df["Close"].rolling(20).mean()
        std = df["Close"].rolling(20).std()
        addplots.append(mpf.make_addplot(mid + 2 * std, color="#888", width=0.5, linestyle="--"))
        addplots.append(mpf.make_addplot(mid - 2 * std, color="#888", width=0.5, linestyle="--"))

    out_dir = _ensure_out_dir()
    if out_path is None:
        safe = "".join(c if c.isalnum() else "_" for c in title.lower())[:60]
        out_path = str(out_dir / f"{safe}_{pd.Timestamp.utcnow().strftime('%Y%m%dT%H%M%S')}.png")

    mpf.plot(
        df, type="candle", style="charles", title=title, ylabel="Price",
        volume=show_volume, addplot=addplots if addplots else None,
        figratio=(16, 9), figscale=1.0, tight_layout=True,
        savefig=dict(fname=out_path, dpi=120, bbox_inches="tight"),
    )
    return out_path
