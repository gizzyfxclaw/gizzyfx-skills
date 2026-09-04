"""tvremix_feeds.py — Shared market data feeds backed by the tvremix MCP HTTP server.

All three skills (crypto, forex_comm, saham_idn) use this module instead of
their own TwelveData / yfinance / CoinGecko / CCXT adapters.

Symbol mapping:
    - Forex:        EURUSD → OANDA:EURUSD
    - Crypto:       BTC   → BINANCE:BTCUSDT
    - Commodities:  GOLD  → TVC:GOLD, OIL → NYMEX:CL1!, etc.
    - Saham IDN:    BBRI  → IDX:BBRI.JK

Environment:
    TVREMIX_URL     (default https://tvremix.xyz/api/mcp/v1)
    TVREMIX_API_KEY (required)
"""

from __future__ import annotations

import os
import pandas as pd

from .tvremix_mcp_client import TvRemixClient

_client: TvRemixClient | None = None


def _c() -> TvRemixClient:
    global _client
    if _client is None:
        _client = TvRemixClient()
    return _client


# ---------- symbol mapping ----------

_FOREX_PREFIX = "OANDA:"
_CRYPTO_EXCHANGE = "BINANCE:"
_COMMODITY_MAP = {
    "GOLD": "TVC:GOLD",
    "XAU": "TVC:GOLD",
    "XAUUSD": "TVC:GOLD",
    "SILVER": "TVC:SILVER",
    "XAG": "TVC:SILVER",
    "XAGUSD": "TVC:SILVER",
    "OIL": "NYMEX:CL1!",
    "WTI": "NYMEX:CL1!",
    "BRENT": "NYMEX:BRN1!",
    "GAS": "NYMEX:NG1!",
    "NATGAS": "NYMEX:NG1!",
    "COPPER": "COMEX:HG1!",
    "PLATINUM": "NYMEX:PL1!",
    "PALLADIUM": "NYMEX:PA1!",
}

# yfinance still needed for saham IDN (IDX not on TradingView)
_SAHAM_NEEDS_YF = True


def to_tvremix_symbol(symbol: str) -> str:
    """Map a user-facing symbol to TradingView format for tvremix."""
    s = symbol.upper().replace("/", "")

    # commodities
    if s in _COMMODITY_MAP:
        return _COMMODITY_MAP[s]

    # saham IDN — not available on TV, keep yfinance fallback
    if s.isalpha() and len(s) == 4 and not s.startswith("^"):
        return f"IDX:{s}.JK"

    # crypto — BINANCE:BTCUSDT style
    if s in ("BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "DOT",
             "MATIC", "POL", "LINK", "TRX", "LTC", "BCH", "ATOM", "NEAR",
             "ARB", "OP", "SUI", "APT", "TON", "SHIB", "PEPE", "WIF", "BONK",
             "FET", "RNDR", "INJ", "TIA", "XLM", "UNI", "AAVE", "MKR"):
        return f"{_CRYPTO_EXCHANGE}{s}USDT"

    # forex — OANDA:EURUSD style (6-letter pair)
    if len(s) == 6 and s.isalpha():
        return f"{_FOREX_PREFIX}{s}"

    # unknown — pass through
    return s


_INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1D": "1D",
    "1d": "1D",
    "1W": "1W",
    "1w": "1W",
    "1M": "1M",
}


def _to_tv_interval(tf: str) -> str:
    return _INTERVAL_MAP.get(tf, "1D")


# ---------- quote ----------

def tv_quote(symbol: str) -> dict:
    """Get the best available quote via tvremix. Returns dict with last, change_pct, etc."""
    tv_sym = to_tvremix_symbol(symbol)
    r = _c().get_quote(tv_sym)

    if not r:
        return {"ok": False, "error": "empty response"}

    # tvremix returns: {"success": true, "data": {"price": ..., "change_percent": ..., ...}}
    if r.get("success") is True and isinstance(r.get("data"), dict):
        d = r["data"]
        return {
            "ok": True,
            "symbol": symbol.upper(),
            "last": d.get("price"),
            "previous_close": d.get("previous_close"),
            "change_pct": d.get("change_percent"),
            "day_low": d.get("low"),
            "day_high": d.get("high"),
            "open": d.get("open"),
            "volume": d.get("volume"),
            "currency": d.get("currency", "USD"),
            "source": "tvremix",
        }

    if r.get("ok") is False:
        return {"ok": False, "error": r.get("error", "tvremix quote failed")}

    return {"ok": False, "error": "unexpected tvremix response", "raw": str(r)[:200]}


# ---------- OHLCV ----------

def tv_ohlcv(symbol: str, *, timeframe: str = "1d", count: int = 300) -> pd.DataFrame:
    """Fetch OHLCV from tvremix and return a pandas DataFrame indexed by timestamp.

    Returns empty DataFrame on failure (same contract as yfinance fallback).
    """
    tv_sym = to_tvremix_symbol(symbol)
    interval = _to_tv_interval(timeframe)
    # For saham IDN, try yfinance first (TV may not have it)
    if tv_sym.startswith("IDX:"):
        return _saham_yf_ohlcv(symbol, timeframe=timeframe)

    r = _c().get_ohlcv(tv_sym, interval=interval, count=count)
    if not r or r.get("ok") is False:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    bars = r.get("bars") or []
    if not bars:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = pd.DataFrame(bars)
    # tvremix returns: [{t, o, h, l, c, v}, ...]
    df.index = pd.to_datetime(df["t"], unit="s", utc=True)
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df.index.name = "Date"
    df = df.sort_index()
    return df


# ---------- saham fallback (yfinance) ----------

def _saham_yf_ohlcv(symbol: str, *, timeframe: str = "1d") -> pd.DataFrame:
    """Fallback OHLCV for saham IDN via yfinance (tvremix may not cover IDX)."""
    try:
        import yfinance as yf
    except ImportError:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    s = symbol.upper()
    if not s.endswith(".JK") and not s.startswith("^"):
        s = f"{s}.JK"

    tf_map = {"1d": ("1d", "2y"), "1w": ("1wk", "10y"), "1h": ("60m", "730d")}
    interval, period = tf_map.get(timeframe, ("1d", "2y"))

    try:
        df = yf.download(s, interval=interval, period=period, auto_adjust=False, progress=False, threads=False)
        if df is None or df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low",
                                "Close": "close", "Volume": "volume"})
        df.index = pd.to_datetime(df.index, utc=True)
        keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
        return df[keep].astype(float).sort_index()
    except Exception:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def tv_technicals(symbol: str, interval: str = "1D") -> dict:
    """Get full indicator snapshot from tvremix."""
    tv_sym = to_tvremix_symbol(symbol)
    r = _c().get_technicals(tv_sym, interval=interval)
    if not r or r.get("ok") is False:
        return {"ok": False, "error": r.get("error", "tvremix technicals failed") if r else "empty"}
    r["ok"] = True
    return r


def tv_calendar(countries: list | None = None, importance: list | None = None,
                date_from: str | None = None, date_to: str | None = None) -> dict:
    """Get economic calendar from tvremix."""
    r = _c().get_economic_calendar(
        countries=countries, importance=importance,
        date_from=date_from, date_to=date_to,
    )
    if not r or r.get("ok") is False:
        return {"ok": False, "error": r.get("error", "tvremix calendar failed") if r else "empty"}
    r["ok"] = True
    return r


def tv_news(symbol: str, limit: int = 10) -> dict:
    """Get news for a symbol from tvremix."""
    tv_sym = to_tvremix_symbol(symbol)
    r = _c().get_news(tv_sym, limit=limit)
    if not r or r.get("ok") is False:
        return {"ok": False, "error": r.get("error", "tvremix news failed") if r else "empty"}
    r["ok"] = True
    return r


def tv_smc(symbol: str, interval: str = "1D", count: int = 300, swing_lookback: int = 5) -> dict:
    """Get Smart Money Concepts analysis from tvremix."""
    tv_sym = to_tvremix_symbol(symbol)
    r = _c().analyze_smc(tv_sym, interval=interval, count=count, swing_lookback=swing_lookback)
    if not r or r.get("ok") is False:
        return {"ok": False, "error": r.get("error", "tvremix SMC failed") if r else "empty"}
    r["ok"] = True
    return r


def tv_multi_tf(symbol: str, timeframes: list | None = None) -> dict:
    """Get multi-timeframe analysis from tvremix."""
    tv_sym = to_tvremix_symbol(symbol)
    r = _c().analyze_multi_timeframe(tv_sym, timeframes=timeframes)
    if not r or r.get("ok") is False:
        return {"ok": False, "error": r.get("error", "tvremix MTF failed") if r else "empty"}
    r["ok"] = True
    return r


if __name__ == "__main__":
    import json
    print("=== EURUSD quote ===")
    print(json.dumps(tv_quote("EURUSD"), indent=2, default=str))
    print("\n=== BTC OHLCV (last 5 bars) ===")
    df = tv_ohlcv("BTC", interval="1D", count=5)
    print(df.tail())
