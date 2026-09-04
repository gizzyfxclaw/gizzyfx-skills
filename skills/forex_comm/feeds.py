"""Data feeds for the forex + commodities skill — backed by tvremix MCP.

Adapters:
* tvremix MCP (TradingView) — primary for OHLCV + quotes on all forex/commodity
* yfinance — fallback for commodities not covered by TradingView, and for
  saham IDN (not on TradingView)
* ForexFactory scrape — economic calendar (tvremix calendar is also available)

Environment:
    TVREMIX_API_KEY (required for OHLCV + quotes)
    TWELVEDATA_API_KEY (optional — ignored, kept for compat)
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from .._shared.http_cache import cached_get
from .._shared.tvremix_feeds import tv_quote, tv_ohlcv

try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


TWELVEDATA_BASE = "https://api.twelvedata.com"
TWELVEDATA_KEY = os.environ.get("TWELVEDATA_API_KEY", "")


# ---------- symbol routing ----------

_COMMODITY_YF = {
    "GOLD": "GC=F", "XAU": "GC=F", "XAUUSD": "GC=F",
    "SILVER": "SI=F", "XAG": "SI=F", "XAGUSD": "SI=F",
    "OIL": "CL=F", "WTI": "CL=F",
    "BRENT": "BZ=F",
    "GAS": "NG=F", "NATGAS": "NG=F",
    "COPPER": "HG=F",
    "PLATINUM": "PL=F", "PALLADIUM": "PA=F",
}

_FOREX_RE = re.compile(r"^([A-Z]{3})/?([A-Z]{3})$")


def asset_kind(symbol: str) -> str:
    s = symbol.upper().replace("/", "")
    if s in _COMMODITY_YF:
        return "commodity"
    if _FOREX_RE.match(s):
        return "forex"
    return "unknown"


def to_yf_ticker(symbol: str) -> str:
    s = symbol.upper().replace("/", "")
    if s in _COMMODITY_YF:
        return _COMMODITY_YF[s]
    m = _FOREX_RE.match(s)
    if m:
        return f"{m.group(1)}{m.group(2)}=X"
    return s


# ---------- combined router (tvremix primary) ----------

def quote(symbol: str) -> dict[str, Any]:
    """Get the best available quote: tvremix first, yfinance fallback."""
    kind = asset_kind(symbol)
    q = tv_quote(symbol)
    if q.get("ok"):
        q["kind"] = kind
        return q
    # Fallback to yfinance if tvremix failed
    if yf is not None:
        try:
            t = to_yf_ticker(symbol)
            tk = yf.Ticker(t)
            fast = tk.fast_info
            last = getattr(fast, "last_price", None) or (fast.get("last_price") if hasattr(fast, "get") else None)
            prev = getattr(fast, "previous_close", None) or (fast.get("previous_close") if hasattr(fast, "get") else None)
            change_pct = None
            if last is not None and prev:
                change_pct = (float(last) - float(prev)) / float(prev) * 100
            q = {
                "ok": True, "symbol": t, "kind": kind,
                "last": float(last) if last is not None else None,
                "previous_close": float(prev) if prev else None,
                "change_pct": change_pct,
                "source": "yfinance",
            }
            return q
        except Exception:
            pass
    return {"ok": False, "error": "no quote available"}


def ohlcv(symbol: str, *, timeframe: str = "1d") -> pd.DataFrame:
    """OHLCV: tvremix primary, yfinance fallback for commodities."""
    kind = asset_kind(symbol)
    df = tv_ohlcv(symbol, timeframe=timeframe)
    if not df.empty:
        return df
    # Fallback to yfinance
    if yf is not None:
        try:
            t = to_yf_ticker(symbol)
            interval, period = _yf_interval(timeframe)
            yf_df = yf.download(t, interval=interval, period=period, auto_adjust=False, progress=False, threads=False)
            if yf_df is not None and not yf_df.empty:
                if isinstance(yf_df.columns, pd.MultiIndex):
                    yf_df.columns = [c[0] for c in yf_df.columns]
                yf_df = yf_df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
                yf_df.index = pd.to_datetime(yf_df.index, utc=True)
                keep = [c for c in ("open", "high", "low", "close", "volume") if c in yf_df.columns]
                return yf_df[keep].astype(float).sort_index()
        except Exception:
            pass
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def _yf_interval(tf: str) -> tuple:
    mapping = {
        "5m": ("5m", "5d"), "15m": ("15m", "5d"), "30m": ("30m", "60d"),
        "1h": ("60m", "730d"), "4h": ("60m", "730d"), "1d": ("1d", "2y"), "1w": ("1wk", "10y"),
    }
    return mapping.get(tf, ("1d", "2y"))


# ---------- ForexFactory economic calendar ----------

@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
def calendar_today(min_impact: str = "high") -> dict[str, Any]:
    """Scrape today's ForexFactory calendar for high-impact events."""
    if BeautifulSoup is None:
        return {"ok": False, "error": "beautifulsoup4 not installed"}
    headers = {"User-Agent": "Mozilla/5.0 (Hermes Market Skills)"}
    r = cached_get("https://www.forexfactory.com/calendar?day=today", headers=headers, ttl=600)
    if r.status_code != 200:
        return {"ok": False, "error": f"forexfactory HTTP {r.status_code}"}
    soup = BeautifulSoup(r.content, "lxml")
    rows = soup.select("tr.calendar__row")
    impact_rank = {"low": 0, "medium": 1, "high": 2, "holiday": -1}
    threshold = impact_rank.get(min_impact, 2)
    out: list[dict[str, Any]] = []
    for tr in rows:
        impact_el = tr.select_one(".calendar__impact span")
        impact = ""
        if impact_el and impact_el.has_attr("title"):
            impact = impact_el["title"].lower().split()[0]
        if impact_rank.get(impact, -1) < threshold:
            continue
        currency = (tr.select_one(".calendar__currency") or {}).get_text(strip=True) if tr.select_one(".calendar__currency") else ""
        event = (tr.select_one(".calendar__event") or {}).get_text(strip=True) if tr.select_one(".calendar__event") else ""
        time_ = (tr.select_one(".calendar__time") or {}).get_text(strip=True) if tr.select_one(".calendar__time") else ""
        actual = (tr.select_one(".calendar__actual") or {}).get_text(strip=True) if tr.select_one(".calendar__actual") else ""
        forecast = (tr.select_one(".calendar__forecast") or {}).get_text(strip=True) if tr.select_one(".calendar__forecast") else ""
        previous = (tr.select_one(".calendar__previous") or {}).get_text(strip=True) if tr.select_one(".calendar__previous") else ""
        out.append({"time": time_, "currency": currency, "impact": impact, "event": event,
                    "actual": actual, "forecast": forecast, "previous": previous})
    return {"ok": True, "date": datetime.utcnow().date().isoformat(),
            "min_impact": min_impact, "count": len(out), "items": out}


# Defaults
DEFAULT_FOREX_WATCHLIST = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF", "USDCAD", "NZDUSD"]
DEFAULT_COMMODITY_WATCHLIST = ["GOLD", "SILVER", "OIL", "BRENT", "NATGAS", "COPPER"]
