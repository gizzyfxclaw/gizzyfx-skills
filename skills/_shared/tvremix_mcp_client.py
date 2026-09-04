"""tvremix_mcp_client.py — HTTP client for the tvremix MCP server.

Usage:
    from tvremix_mcp_client import TvRemixClient
    c = TvRemixClient()
    print(c.call("get_ohlcv", symbol="OANDA:EURUSD", interval="1D", count=100))

Environment:
    TVREMIX_URL (default https://tvremix.xyz/api/mcp/v1)
    TVREMIX_API_KEY (required)
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error

TVREMIX_URL = os.environ.get("TVREMIX_URL", "https://tvremix.xyz/api/mcp/v1")
TVREMIX_API_KEY = os.environ.get("TVREMIX_API_KEY", "")


class TvRemixClient:
    def __init__(self, url: str = TVREMIX_URL, key: str = TVREMIX_API_KEY):
        self.url = url.rstrip("/")
        self.key = key

    def call(self, tool_name: str, **arguments) -> dict:
        """Call an MCP tool via JSON-RPC 2.0 over HTTP."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"

        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return {"ok": False, "error": f"HTTP {e.code}", "body": e.read().decode()[:500]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

        # MCP wraps result in {"result": {"content": [{"type":"text","text":"..."}]}}
        if "result" in body:
            result = body["result"]
            if isinstance(result, dict) and "content" in result:
                # text content
                text_parts = []
                for c in result["content"]:
                    if c.get("type") == "text":
                        text_parts.append(c.get("text", ""))
                combined = " ".join(text_parts).strip()
                try:
                    return json.loads(combined)
                except Exception:
                    return {"ok": True, "text": combined}
            return result
        if "error" in body:
            return {"ok": False, "error": body["error"]}
        return body

    # ---------- convenience wrappers ----------

    def get_ohlcv(self, symbol: str, interval: str = "1D", count: int = 300) -> dict:
        return self.call("get_ohlcv", symbol=symbol, interval=interval, count=count)

    def get_quote(self, symbol: str) -> dict:
        return self.call("get_quote", symbol=symbol)

    def get_technicals(self, symbol: str, interval: str = "1D") -> dict:
        return self.call("get_technicals", symbol=symbol, interval=interval)

    def get_full_technicals(self, symbol: str, timeframes: list | None = None) -> dict:
        return self.call("get_full_technicals", symbol=symbol, timeframes=timeframes)

    def analyze_smc(self, symbol: str, interval: str = "1D", count: int = 300, swing_lookback: int = 5) -> dict:
        return self.call("analyze_smc_tool", symbol=symbol, interval=interval, count=count, swing_lookback=swing_lookback)

    def analyze_swing(self, symbol: str, interval: str = "1D", count: int = 300, swing_lookback: int = 10) -> dict:
        return self.call("analyze_swing_tool", symbol=symbol, interval=interval, count=count, swing_lookback=swing_lookback)

    def analyze_multi_timeframe(self, symbol: str, timeframes: list | None = None) -> dict:
        return self.call("analyze_multi_timeframe", symbol=symbol, timeframes=timeframes)

    def get_economic_calendar(self, **kw) -> dict:
        return self.call("get_economic_calendar", **kw)

    def get_news(self, symbol: str, limit: int = 10) -> dict:
        return self.call("get_news", symbol=symbol, limit=limit)

    def web_search(self, query: str, num_results: int = 3) -> dict:
        return self.call("web_search", query=query, num_results=num_results)


if __name__ == "__main__":
    import sys
    c = TvRemixClient()
    # quick test
    r = c.get_quote("OANDA:EURUSD")
    print(json.dumps(r, indent=2, default=str))
