import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState, useCallback } from "react";
import {
  TrendingUp,
  TrendingDown,
  Activity,
  BarChart3,
  AlertTriangle,
  Target,
  Crosshair,
} from "lucide-react";
import { Badge, Button, Card, Field, TextInput } from "@/components/terminal/ui";
import { useStore } from "@/lib/store";

export const Route = createFileRoute("/smc")({
  head: () => ({
    meta: [{ title: "SMC Analysis — GizzyFx" }],
  }),
  component: SMCPage,
});

/* ── Types ─────────────────────────────────────────────────────────────── */

interface SMCSummary {
  ok: boolean;
  error?: string;
  structure: {
    swings: Array<{ idx: number; price: number; kind: "high" | "low" }>;
    bias: "bullish" | "bearish" | "neutral";
    bos: "bullish" | "bearish" | null;
    choch: "bullish" | "bearish" | null;
    lastBosIdx: number | null;
    lastChochIdx: number | null;
  };
  orderBlocks: Array<{
    low: number;
    high: number;
    kind: "bullish" | "bearish";
    idx: number;
    impulseMag: number;
  }>;
  fvgs: Array<{
    low: number;
    high: number;
    kind: "bullish" | "bearish";
    idx: number;
    filled: boolean;
  }>;
  sweeps: Array<{
    idx: number;
    kind: "bullish" | "bearish";
    sweptLevel: number;
    close: number;
  }>;
  zone: {
    zone: string;
    depthPct?: number;
    rangeHigh?: number;
    rangeLow?: number;
    rangeMid?: number;
  };
  summary: string;
  pair: string;
  interval: string;
  barCount: number;
}

const PAIRS = ["EURUSD", "USDJPY", "GBPUSD", "AUDUSD", "XAUUSD"];
const TIMEFRAMES = ["15m", "1h", "4h", "1d"] as const;
type TF = (typeof TIMEFRAMES)[number];

/* ── Component ─────────────────────────────────────────────────────────── */

function SMCPage() {
  const { meta } = useStore();

  const [pair, setPair] = useState<string>("EURUSD");
  const [timeframe, setTimeframe] = useState<TF>("1h");
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<SMCSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setData(null);

    const url = `/api/smc?pair=${pair}&interval=${timeframe}&limit=500`;
    try {
      const res = await fetch(url);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error || `HTTP ${res.status}`);
      }
      const json = await res.json();
      if (!json.ok) {
        throw new Error(json.error || "Analysis failed");
      }
      setData(json);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch SMC data");
    } finally {
      setLoading(false);
    }
  }, [pair, timeframe]);

  useEffect(() => {
    load();
  }, [load]);

  const bias = data?.structure?.bias ?? "neutral";
  const biasColor =
    bias === "bullish" ? "green" : bias === "bearish" ? "red" : "neutral";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">
          SMC Analysis
        </h1>
        <p className="mt-1 text-[13px] text-muted-foreground">
          Smart Money Concepts — market structure, order blocks, FVGs, and
          liquidity sweeps.
        </p>
      </div>

      {/* ── Controls ─────────────────────────────────────────────────── */}
      <Card title="Configuration">
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Pair">
            <select
              className="w-full rounded-md border border-white/10 bg-background px-3 py-2 text-[13px]"
              value={pair}
              onChange={(e) => setPair(e.target.value)}
            >
              {PAIRS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Timeframe">
            <select
              className="w-full rounded-md border border-white/10 bg-background px-3 py-2 text-[13px]"
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value as TF)}
            >
              {TIMEFRAMES.map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Actions">
            <Button
              onClick={load}
              disabled={loading}
              className="w-full justify-center"
            >
              <Activity size={12} />
              {loading ? "Analyzing…" : "Refresh Analysis"}
            </Button>
          </Field>
        </div>
      </Card>

      {/* ── Error ────────────────────────────────────────────────────── */}
      {error && (
        <div className="alert alert-red">
          <p className="alert-title">
            <AlertTriangle size={13} /> Error
          </p>
          <p className="alert-body">{error}</p>
        </div>
      )}

      {/* ── Summary Badge ────────────────────────────────────────────── */}
      {data && (
        <Card>
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-[13px] font-medium text-muted-foreground">
              {data.pair} · {data.interval.toUpperCase()} · {data.barCount} bars
            </span>
            <span className="text-[13px] font-mono text-muted-foreground">
              {data.summary}
            </span>
          </div>
        </Card>
      )}

      {/* ── Bias + Zone ───────────────────────────────────────────────── */}
      {data && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Card title="Market Structure">
            <div className="flex items-center gap-3">
              {bias === "bullish" ? (
                <TrendingUp size={20} className="text-emerald-400" />
              ) : bias === "bearish" ? (
                <TrendingDown size={20} className="text-red-400" />
              ) : (
                <BarChart3 size={20} className="text-amber-400" />
              )}
              <div>
                <p className="text-[15px] font-bold capitalize text-foreground">
                  {bias}
                </p>
                <p className="text-[12px] text-muted-foreground">
                  {data.structure.bos ? `BOS ${data.structure.bos}` : ""}
                  {data.structure.choch
                    ? ` · CHoCH ${data.structure.choch}`
                    : ""}
                  {!data.structure.bos && !data.structure.choch
                    ? "No recent structure break"
                    : ""}
                </p>
              </div>
            </div>
          </Card>
          <Card title="Premium / Discount Zone">
            <div className="flex items-center gap-3">
              <Crosshair size={20} className="text-blue-400" />
              <div>
                <p className="text-[15px] font-bold capitalize text-foreground">
                  {data.zone.zone}
                </p>
                {data.zone.depthPct !== undefined && (
                  <p className="text-[12px] text-muted-foreground">
                    Depth: {data.zone.depthPct.toFixed(1)}% · Range:{" "}
                    {data.zone.rangeLow?.toFixed(5)} –{" "}
                    {data.zone.rangeHigh?.toFixed(5)}
                  </p>
                )}
              </div>
            </div>
          </Card>
        </div>
      )}

      {/* ── Order Blocks ─────────────────────────────────────────────── */}
      {data && data.orderBlocks.length > 0 && (
        <Card title={`Order Blocks (${data.orderBlocks.length})`}>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-white/10 text-left text-muted-foreground">
                  <th className="px-2 py-1">Type</th>
                  <th className="px-2 py-1">Low</th>
                  <th className="px-2 py-1">High</th>
                  <th className="px-2 py-1">Impulse</th>
                </tr>
              </thead>
              <tbody>
                {data.orderBlocks.slice(-5).map((ob, i) => (
                  <tr key={i} className="border-b border-white/5">
                    <td className="px-2 py-1">
                      <Badge tone={ob.kind === "bullish" ? "green" : "red"}>
                        {ob.kind}
                      </Badge>
                    </td>
                    <td className="px-2 py-1 font-mono">{ob.low.toFixed(5)}</td>
                    <td className="px-2 py-1 font-mono">{ob.high.toFixed(5)}</td>
                    <td className="px-2 py-1 font-mono">
                      {ob.impulseMag.toFixed(1)}× ATR
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* ── Fair Value Gaps ───────────────────────────────────────────── */}
      {data && data.fvgs.length > 0 && (
        <Card title={`Fair Value Gaps (${data.fvgs.length})`}>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-white/10 text-left text-muted-foreground">
                  <th className="px-2 py-1">Type</th>
                  <th className="px-2 py-1">Low</th>
                  <th className="px-2 py-1">High</th>
                  <th className="px-2 py-1">Status</th>
                </tr>
              </thead>
              <tbody>
                {data.fvgs
                  .filter((f) => !f.filled)
                  .slice(-5)
                  .map((fvg, i) => (
                    <tr key={i} className="border-b border-white/5">
                      <td className="px-2 py-1">
                        <Badge tone={fvg.kind === "bullish" ? "green" : "red"}>
                          {fvg.kind}
                        </Badge>
                      </td>
                      <td className="px-2 py-1 font-mono">
                        {fvg.low.toFixed(5)}
                      </td>
                      <td className="px-2 py-1 font-mono">
                        {fvg.high.toFixed(5)}
                      </td>
                      <td className="px-2 py-1">
                        <Badge tone="green">Unfilled</Badge>
                      </td>
                    </tr>
                  ))}
                {data.fvgs.filter((f) => !f.filled).length === 0 && (
                  <tr>
                    <td
                      colSpan={4}
                      className="px-2 py-3 text-center text-muted-foreground"
                    >
                      All FVGs have been filled
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* ── Liquidity Sweeps ──────────────────────────────────────────── */}
      {data && data.sweeps.length > 0 && (
        <Card title={`Liquidity Sweeps (${data.sweeps.length})`}>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-white/10 text-left text-muted-foreground">
                  <th className="px-2 py-1">Type</th>
                  <th className="px-2 py-1">Level Swept</th>
                  <th className="px-2 py-1">Close</th>
                  <th className="px-2 py-1">Rejection</th>
                </tr>
              </thead>
              <tbody>
                {data.sweeps.slice(-5).map((sw, i) => {
                  const rejectionPct =
                    sw.kind === "bullish"
                      ? ((sw.close - sw.sweptLevel) /
                          (sw.close - sw.sweptLevel || 1)) *
                        100
                      : 0;
                  return (
                    <tr key={i} className="border-b border-white/5">
                      <td className="px-2 py-1">
                        <Badge tone={sw.kind === "bullish" ? "green" : "red"}>
                          {sw.kind}
                        </Badge>
                      </td>
                      <td className="px-2 py-1 font-mono">
                        {sw.sweptLevel.toFixed(5)}
                      </td>
                      <td className="px-2 py-1 font-mono">
                        {sw.close.toFixed(5)}
                      </td>
                      <td className="px-2 py-1 text-[12px] text-emerald-400">
                        {rejectionPct.toFixed(1)}% wick rejection
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* ── Confluence Score ─────────────────────────────────────────── */}
      {data && <ConfluenceCard data={data} />}
    </div>
  );
}

/* ── Confluence Score Card ─────────────────────────────────────────────── */

function ConfluenceCard({ data }: { data: SMCSummary }) {
  let longScore = 0;
  let shortScore = 0;

  if (data.structure.bias === "bullish") longScore += 1;
  if (data.structure.bias === "bearish") shortScore += 1;
  if (data.structure.bos === "bullish") longScore += 1;
  if (data.structure.bos === "bearish") shortScore += 1;
  if (data.structure.choch === "bullish") longScore += 1.5;
  if (data.structure.choch === "bearish") shortScore += 1.5;

  for (const ob of data.orderBlocks.slice(-3)) {
    if (ob.kind === "bullish") longScore += 2;
    if (ob.kind === "bearish") shortScore += 2;
  }

  const unfilledBullFVG = data.fvgs.filter((f) => f.kind === "bullish" && !f.filled).length;
  const unfilledBearFVG = data.fvgs.filter((f) => f.kind === "bearish" && !f.filled).length;
  longScore += unfilledBullFVG * 0.5;
  shortScore += unfilledBearFVG * 0.5;

  if (data.sweeps.length > 0) {
    const last = data.sweeps[data.sweeps.length - 1];
    if (last.kind === "bullish") longScore += 2;
    if (last.kind === "bearish") shortScore += 2;
  }

  if (data.zone.zone === "discount" && (data.zone.depthPct ?? 0) > 50) longScore += 0.5;
  if (data.zone.zone === "premium" && (data.zone.depthPct ?? 0) > 50) shortScore += 0.5;

  const total = longScore + shortScore;
  const verdict =
    longScore >= 4 && longScore > shortScore * 1.5
      ? "STRONG LONG"
      : longScore >= 2.5 && longScore > shortScore
        ? "LEAN LONG"
        : shortScore >= 4 && shortScore > longScore * 1.5
          ? "STRONG SHORT"
          : shortScore >= 2.5 && shortScore > longScore
            ? "LEAN SHORT"
            : "NEUTRAL";

  const verdictColor =
    verdict.includes("LONG")
      ? "green"
      : verdict.includes("SHORT")
        ? "red"
        : "amber";

  return (
    <Card title="SMC Confluence Score">
      <div className="flex items-center gap-6">
        <div className="flex-1">
          <div className="flex items-center justify-between text-[13px]">
            <span className="text-emerald-400">Long: {longScore.toFixed(1)}</span>
            <span className="text-red-400">Short: {shortScore.toFixed(1)}</span>
          </div>
          <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-white/5">
            <div
              className="h-full bg-emerald-400 transition-all"
              style={{
                width: `${total > 0 ? (longScore / total) * 100 : 50}%`,
              }}
            />
          </div>
        </div>
        <div>
          <Badge tone={verdictColor}>
            <Target size={12} />
            {verdict}
          </Badge>
        </div>
      </div>
    </Card>
  );
}
