"""Macro context fetchers used by the recommendation engine.

All HTTP calls go through :mod:`skills._shared.http_cache` so we stay polite
to free APIs. Each function returns a small dict with an ``ok`` field; on
failure ``ok=False`` and the rest of the recommendation flow simply skips
the macro signal.
"""

from __future__ import annotations

import datetime as _dt
import os
from typing import Any

from .http_cache import cached_get


# ---------- crypto macro ----------

def _json(url: str, *, params: dict | None = None, ttl: int = 300) -> Any:
    """Helper: GET via cache, return parsed JSON or raise."""
    resp = cached_get(url, params=params, ttl=ttl)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    return resp.json()


def btc_dominance() -> dict[str, Any]:
    """BTC market-cap dominance % via CoinGecko /global."""
    try:
        payload = _json("https://api.coingecko.com/api/v3/global", ttl=300)
        data = payload.get("data", {})
        return {
            "ok": True,
            "btc_dominance_pct": data.get("market_cap_percentage", {}).get("btc"),
            "eth_dominance_pct": data.get("market_cap_percentage", {}).get("eth"),
            "total_mcap_usd": data.get("total_market_cap", {}).get("usd"),
            "total_volume_24h_usd": data.get("total_volume", {}).get("usd"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def binance_funding_rate(symbol: str = "BTCUSDT") -> dict[str, Any]:
    """Latest perpetual funding rate from Binance Futures (public, no auth)."""
    try:
        data = _json(
            "https://fapi.binance.com/fapi/v1/premiumIndex",
            params={"symbol": symbol.upper()},
            ttl=120,
        )
        rate = float(data.get("lastFundingRate", 0)) * 100  # convert to %
        return {
            "ok": True,
            "symbol": symbol.upper(),
            "funding_rate_pct": round(rate, 4),
            "mark_price": float(data.get("markPrice", 0)) or None,
            "next_funding_time": data.get("nextFundingTime"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def fear_greed_index() -> dict[str, Any]:
    """alternative.me Fear & Greed (re-export so all macro lives in one module)."""
    try:
        data = _json("https://api.alternative.me/fng/", ttl=600)
        item = (data.get("data") or [{}])[0]
        return {
            "ok": True,
            "value": int(item.get("value", 0)),
            "classification": item.get("value_classification"),
            "timestamp": item.get("timestamp"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------- forex macro ----------

def dxy_snapshot() -> dict[str, Any]:
    """USD index (DXY) snapshot via Yahoo (DX-Y.NYB)."""
    try:
        import yfinance as yf
        tk = yf.Ticker("DX-Y.NYB")
        fast = tk.fast_info
        last = getattr(fast, "last_price", None) or (fast.get("last_price") if hasattr(fast, "get") else None)
        prev = getattr(fast, "previous_close", None) or (fast.get("previous_close") if hasattr(fast, "get") else None)
        change_pct = None
        if last is not None and prev:
            change_pct = (float(last) - float(prev)) / float(prev) * 100
        return {
            "ok": True,
            "last": float(last) if last is not None else None,
            "previous_close": float(prev) if prev else None,
            "change_pct": change_pct,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------- saham macro ----------

def ihsg_snapshot() -> dict[str, Any]:
    """IHSG composite snapshot (^JKSE)."""
    try:
        import yfinance as yf
        tk = yf.Ticker("^JKSE")
        fast = tk.fast_info
        last = getattr(fast, "last_price", None) or (fast.get("last_price") if hasattr(fast, "get") else None)
        prev = getattr(fast, "previous_close", None) or (fast.get("previous_close") if hasattr(fast, "get") else None)
        change_pct = None
        if last is not None and prev:
            change_pct = (float(last) - float(prev)) / float(prev) * 100
        return {
            "ok": True,
            "symbol": "^JKSE",
            "last": float(last) if last is not None else None,
            "previous_close": float(prev) if prev else None,
            "change_pct": change_pct,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
