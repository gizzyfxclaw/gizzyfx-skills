import { createFileRoute } from "@tanstack/react-router";
import { getCFEnv } from "@/lib/cloudflare-env";
import { detectPatterns } from "@/lib/pattern-engine";

interface Bar { time: number; open: number; high: number; low: number; close: number; }

const TVREMIX_URL = "https://tvremix.xyz/api/mcp/v1";
const TV_INTERVAL: Record<string, string> = { "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1D", "1w": "1W" };

async function fetchBars(apiKey: string, pair: string, interval: string, count: number): Promise<Bar[] | null> {
  let res: Response;
  try {
    res = await fetch(TVREMIX_URL, {
      method: "POST",
      headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json", Accept: "application/json, text/event-stream" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "get_ohlcv", arguments: { symbol: `FX:${pair}`, interval: TV_INTERVAL[interval] ?? "1h", count } } }),
    });
  } catch { return null; }
  if (!res.ok) return null;
  let json: any;
  try { json = await res.json(); } catch { return null; }
  if (json.error || json.result?.isError) return null;
  const raw = json.result?.structuredContent?.bars;
  if (!Array.isArray(raw)) return null;
  return raw.filter((b: any) => b.t != null && b.o != null && b.h != null && b.l != null && b.c != null).map((b: any) => ({ time: b.t, open: b.o, high: b.h, low: b.l, close: b.c }));
}

export const Route = createFileRoute("/api/pattern")({
  server: {
    handlers: {
      GET: async ({ request }) => {
        const url = new URL(request.url);
        const pair = (url.searchParams.get("pair") ?? "EURUSD").toUpperCase().replace("/", "");
        const interval = url.searchParams.get("interval") ?? "1h";
        const count = Math.min(parseInt(url.searchParams.get("limit") ?? "300", 10) || 300, 5000);
        const apiKey = getCFEnv()?.TVREMIX_API_KEY;
        if (!apiKey) return Response.json({ error: "TVREMIX_API_KEY not configured" }, { status: 503 });
        const bars = await fetchBars(apiKey, pair, interval, count);
        if (!bars || bars.length === 0) return Response.json({ error: "no data from upstream" }, { status: 502 });
        const patterns = detectPatterns(bars);
        return Response.json({ patterns, pair, interval, barCount: bars.length }, { headers: { "Cache-Control": "public, max-age=60" } });
      },
    },
  },
});
