"""Data feeds for the crypto skill — backed by tvremix MCP + CoinGecko.

Adapters:
* CoinGecko — price + market cap + rank + ATH (no OHLCV, rate-limited)
* tvremix MCP — OHLCV for BINANCE:BTCUSDT, etc.
* DeFiLlama — protocol TVL
* CryptoPanic — news feed
* alternative.me — Fear & Greed index

Environment:
    COINGECKO_API_KEY (optional — anonymous works with rate limit)
    TVREMIX_API_KEY (required for OHLCV)
    CRYPTOPANIC_API_KEY (optional — news feed)
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from .._shared.http_cache import cached_get
from .._shared.tvremix_feeds import tv_ohlcv

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
COINGECKO_KEY = os.environ.get("COINGECKO_API_KEY", "")
CRYPTOPANIC_BASE = "https://cryptopanic.com/api/v1"
CRYPTOPANIC_KEY = os.environ.get("CRYPTOPANIC_API_KEY", "")

_COINGECKO_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "BNB": "binancecoin",
    "XRP": "ripple", "ADA": "cardano", "DOGE": "dogecoin", "AVAX": "avalanche-2",
    "DOT": "polkadot", "MATIC": "matic-network", "POL": "polygon-ecosystem-token",
    "LINK": "chainlink", "TRX": "tron", "LTC": "litecoin", "BCH": "bitcoin-cash",
    "ATOM": "cosmos", "NEAR": "near", "ARB": "arbitrum", "OP": "optimism",
    "SUI": "sui", "APT": "aptos", "TON": "the-open-network", "SHIB": "shiba-inu",
    "PEPE": "pepe", "WIF": "dogwifcoin", "BONK": "bonk", "FET": "fetch-ai",
    "RNDR": "render-token", "INJ": "injective-protocol", "TIA": "celestia",
    "USDT": "tether", "USDC": "usd-coin",
}


def to_coingecko_id(symbol: str) -> str:
    s = symbol.upper().replace("USDT", "").replace("USD", "").strip()
    return _COINGECKO_IDS.get(s, s.lower())


def to_tvremix_symbol(symbol: str) -> str:
    s = symbol.upper()
    if s in ("USDT", "USDC"):
        return ""
    s = s.replace("USDT", "").replace("USD", "")
    return f"BINANCE:{s}USDT"


# ---------- CoinGecko ----------

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def cg_price(symbol: str) -> dict[str, Any]:
    """Return live price + 24h stats for a single coin."""
    cid = to_coingecko_id(symbol)
    params: dict[str, Any] = {
        "ids": cid, "vs_currencies": "usd,idr",
        "include_market_cap": "true", "include_24hr_vol": "true",
        "include_24hr_change": "true", "include_last_updated_at": "true",
    }
    headers = {"x-cg-demo-api-key": COINGECKO_KEY} if COINGECKO_KEY else {}
    r = cached_get(f"{COINGECKO_BASE}/simple/price", params=params, headers=headers, ttl=15)
    if r.status_code != 200:
        return {"ok": False, "error": f"coingecko HTTP {r.status_code}"}
    data = r.json()
    row = data.get(cid)
    if not row:
        return {"ok": False, "error": f"unknown coingecko id: {cid}"}
    return {
        "ok": True, "symbol": symbol.upper(), "coingecko_id": cid,
        "price_usd": row.get("usd"), "price_idr": row.get("idr"),
        "market_cap_usd": row.get("usd_market_cap"),
        "volume_24h_usd": row.get("usd_24h_vol"),
        "change_24h_pct": row.get("usd_24h_change"),
        "last_updated_at": row.get("last_updated_at"),
    }


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def cg_market_data(symbol: str) -> dict[str, Any]:
    """Return richer market data (rank, ATH, supply, etc.)."""
    cid = to_coingecko_id(symbol)
    params = {"localization": "false", "tickers": "false", "community_data": "false", "developer_data": "false"}
    headers = {"x-cg-demo-api-key": COINGECKO_KEY} if COINGECKO_KEY else {}
    r = cached_get(f"{COINGECKO_BASE}/coins/{cid}", params=params, headers=headers, ttl=120)
    if r.status_code != 200:
        return {"ok": False, "error": f"coingecko HTTP {r.status_code}"}
    j = r.json()
    md = j.get("market_data", {}) or {}
    return {
        "ok": True, "name": j.get("name"), "symbol": (j.get("symbol") or "").upper(),
        "rank": j.get("market_cap_rank"),
        "ath_usd": (md.get("ath") or {}).get("usd"),
        "ath_change_pct": (md.get("ath_change_percentage") or {}).get("usd"),
        "ath_date": (md.get("ath_date") or {}).get("usd"),
        "atl_usd": (md.get("atl") or {}).get("usd"),
        "circulating_supply": md.get("circulating_supply"),
        "max_supply": md.get("max_supply"),
        "categories": j.get("categories"),
    }


# ---------- tvremix OHLCV ----------

def ohlcv(symbol: str, timeframe: str = "1d", limit: int = 300) -> pd.DataFrame:
    """Return OHLCV DataFrame for `symbol` from tvremix (Binance pairs)."""
    tv_sym = to_tvremix_symbol(symbol)
    if not tv_sym:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = tv_ohlcv(symbol, timeframe=timeframe, count=limit)
    if not df.empty:
        return df
    # Fallback: try binance via yfinance
    try:
        import yfinance as yf
        yf_sym = f"{symbol.upper().replace('USDT','').replace('USD','')}-USD"
        tf_map = {"1d": ("1d", "2y"), "1w": ("1wk", "10y"), "1h": ("60m", "730d")}
        interval, period = tf_map.get(timeframe, ("1d", "2y"))
        yf_df = yf.download(yf_sym, interval=interval, period=period, auto_adjust=False, progress=False, threads=False)
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


# ---------- DeFiLlama ----------

DEFILLAMA_BASE = "https://api.llama.fi"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def defillama_tvl(protocol: str) -> dict[str, Any]:
    """Return current TVL for a protocol slug."""
    r = cached_get(f"{DEFILLAMA_BASE}/tvl/{protocol}", ttl=300)
    if r.status_code != 200:
        return {"ok": False, "error": f"defillama HTTP {r.status_code}"}
    try:
        return {"ok": True, "protocol": protocol, "tvl_usd": float(r.text)}
    except ValueError:
        return {"ok": False, "error": "non-numeric response"}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def defillama_chain_tvl(chain: str = "Ethereum") -> dict[str, Any]:
    """Current TVL for an entire chain."""
    r = cached_get(f"{DEFILLAMA_BASE}/v2/historicalChainTvl/{chain}", ttl=300)
    if r.status_code != 200:
        return {"ok": False, "error": f"defillama HTTP {r.status_code}"}
    arr = r.json()
    if not arr:
        return {"ok": False, "error": "empty"}
    return {"ok": True, "chain": chain, "tvl_usd": arr[-1]["tvl"], "ts": arr[-1]["date"]}


# ---------- CryptoPanic ----------

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def cryptopanic_news(query: str = "", limit: int = 10) -> dict[str, Any]:
    """Return recent crypto news, optionally filtered by ticker/keyword."""
    if not CRYPTOPANIC_KEY:
        return {"ok": False, "error": "CRYPTOPANIC_API_KEY not set"}
    params: dict[str, Any] = {"auth_token": CRYPTOPANIC_KEY, "public": "true"}
    if query:
        params["currencies"] = query.upper()
    r = cached_get(f"{CRYPTOPANIC_BASE}/posts/", params=params, ttl=60)
    if r.status_code != 200:
        return {"ok": False, "error": f"cryptopanic HTTP {r.status_code}"}
    j = r.json()
    items = []
    for p in (j.get("results") or [])[:limit]:
        items.append({
            "title": p.get("title"), "url": p.get("url"),
            "domain": (p.get("source") or {}).get("domain"),
            "published": p.get("published_at"),
            "votes": p.get("votes"),
            "currencies": [c.get("code") for c in (p.get("currencies") or [])],
        })
    return {"ok": True, "count": len(items), "items": items}


# ---------- Fear & Greed ----------

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def fear_greed() -> dict[str, Any]:
    """Alternative.me's Fear & Greed Index."""
    r = cached_get("https://api.alternative.me/fng/?limit=1", ttl=600)
    if r.status_code != 200:
        return {"ok": False, "error": f"alt.me HTTP {r.status_code}"}
    j = r.json()
    if not j.get("data"):
        return {"ok": False, "error": "empty"}
    d = j["data"][0]
    return {"ok": True, "value": int(d["value"]), "classification": d["value_classification"], "timestamp": d["timestamp"]}
