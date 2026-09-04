import { createFileRoute } from "@tanstack/react-router";
import { getCFEnv } from "@/lib/cloudflare-env";
import { summarizeSMC } from "@/lib/smc-engine";

/**
 * SMC analysis endpoint.
 * GET /api/smc?pair=EURUSD&interval=1h&limit=300
 * Returns full SMC summary + raw bars for client-side charting.
 */

interface Bar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

const TVREMIX_URL = "https://tvremix.xyz/api/mcp/v1";

function tvSymbol(pair: string): string {
  return `OANDA:${pair}`;
}

const TV_INTERVAL: Record<string, string> = {
  "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
  "1h": "1h", "4h": "4h", "1d": "1D", "1w": "1W",
};

async function fetchBars(
  apiKey: string,
  pair: string,
  interval: string,
  count: number,
): Promise<Bar[] | null> {
  const tvInterval = TV_INTERVAL[interval] ?? "1h";
  let res: Response;
  try {
    res = await fetch(TVREMIX_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
        Accept: "application/json, text/event-stream",
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "tools/call",
        params: {
          name: "get_ohlcv",
          arguments: { symbol: tvSymbol(pair), interval: tvInterval, count },
        },
      }),
    });
  } catch {
    return null;
  }
  if (!res.ok) return null;
  let json: any;
  try {
    json = await res.json();
  } catch {
    return null;
  }
  if (json.error || json.result?.isError) return null;
  const rawBars: Array<{ t: number; o: number; h: number; l: number; c: number }> | undefined =
    json.result?.structuredContent?.bars;
  if (!Array.isArray(rawBars)) return null;

  return rawBars
    .filter((b) => b.t != null && b.o != null && b.h != null && b.l != null && b.c != null)
    .map((b) => ({ time: b.t, open: b.o, high: b.h, low: b.l, close: b.c }));
}

export const Route = createFileRoute("/api/smc")({
  server: {
    handlers: {
      GET: async ({ request }) => {
        const url = new URL(request.url);
        const pair = (url.searchParams.get("pair") ?? "EURUSD").toUpperCase().replace("/", "");
        const interval = url.searchParams.get("interval") ?? "1h";
        const limitParam = parseInt(url.searchParams.get("limit") ?? "0", 10);
        const count = limitParam > 0 ? Math.min(limitParam, 5000) : 300;

        const apiKey = getCFEnv()?.TVREMIX_API_KEY;
        if (!apiKey) {
          return Response.json(
            { error: "TVREMIX_API_KEY not configured" },
            { status: 503 }
          );
        }

        const bars = await fetchBars(apiKey, pair, interval, count);
        if (!bars || bars.length === 0) {
          return Response.json(
            { error: "no data from upstream" },
            { status: 502 }
          );
        }

        const result = summarizeSMC(bars);

        return Response.json(
          { ...result, pair, interval, barCount: bars.length, bars },
          { headers: { "Cache-Control": "public, max-age=60" } }
        );
      },
    },
  },
});
