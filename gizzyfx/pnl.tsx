import { createFileRoute } from "@tanstack/react-router";
import { useMemo } from "react";
import { BarChart3, TrendingUp, TrendingDown, Target, AlertTriangle, CheckCircle, XCircle } from "lucide-react";
import { Badge, Button, Card, Field } from "@/components/terminal/ui";

export const Route = createFileRoute("/pnl")({
  head: () => ({
    meta: [{ title: "P&L Dashboard — GizzyFx" }],
  }),
  component: PnLPage,
});

/* ── Mock data — would be fetched from /api/pnl in production ──────────────── */

const MOCK_TRADES: Trade[] = [
  { entryTime: 1725100000, exitTime: 1725103600, direction: "long", entryPrice: 1.08520, exitPrice: 1.08735, sl: 1.08420, tp: 1.08820, pnlUsd: 21.50, pnlPips: 21.5, result: "win", reason: "tp" },
  { entryTime: 1725186400, exitTime: 1725190000, direction: "long", entryPrice: 1.08800, exitPrice: 1.08690, sl: 1.08690, tp: 1.09100, pnlUsd: -11.00, pnlPips: -11, result: "loss", reason: "sl" },
  { entryTime: 1725272800, exitTime: 1725276400, direction: "short", entryPrice: 1.09250, exitPrice: 1.09030, sl: 1.09350, tp: 1.08950, pnlUsd: 22.00, pnlPips: 22, result: "win", reason: "tp" },
  { entryTime: 1725359200, exitTime: 1725362800, direction: "short", entryPrice: 1.08980, exitPrice: 1.08870, sl: 1.08870, tp: 1.09280, pnlUsd: 11.00, pnlPips: 11, result: "win", reason: "tp" },
  { entryTime: 1725445600, exitTime: 1725449200, direction: "long", entryPrice: 1.08650, exitPrice: 1.08560, sl: 1.08560, tp: 1.08950, pnlUsd: -9.00, pnlPips: -9, result: "loss", reason: "sl" },
  { entryTime: 1725532000, exitTime: 1725535600, direction: "long", entryPrice: 1.08400, exitPrice: 1.08710, sl: 1.08300, tp: 1.08700, pnlUsd: 31.00, pnlPips: 31, result: "win", reason: "tp" },
  { entryTime: 1725618400, exitTime: 1725622000, direction: "short", entryPrice: 1.08850, exitPrice: 1.08750, sl: 1.08950, tp: 1.08550, pnlUsd: 10.00, pnlPips: 10, result: "win", reason: "tp" },
  { entryTime: 1725704800, exitTime: 1725708400, direction: "short", entryPrice: 1.08700, exitPrice: 1.08620, sl: 1.08800, tp: 1.08400, pnlUsd: 8.00, pnlPips: 8, result: "win", reason: "tp" },
  { entryTime: 1725791200, exitTime: 1725794800, direction: "long", entryPrice: 1.08500, exitPrice: 1.08400, sl: 1.08400, tp: 1.08800, pnlUsd: -10.00, pnlPips: -10, result: "loss", reason: "sl" },
  { entryTime: 1725877600, exitTime: 1725881200, direction: "long", entryPrice: 1.08350, exitPrice: 1.08650, sl: 1.08250, tp: 1.08650, pnlUsd: 30.00, pnlPips: 30, result: "win", reason: "tp" },
];

const MOCK_OPEN_POSITIONS: OpenPosition[] = [
  { symbol: "EURUSD", direction: "long", entryPrice: 1.09200, currentPrice: 1.09430, stopPrice: 1.09050, takeProfit: 1.09650, size: 0.01, entryTime: Date.now() - 3600000 },
];

/* ── Component ─────────────────────────────────────────────────────────── */

function PnLPage() {
  const stats = useMemo(() => calcDashboardStats(MOCK_TRADES), []);
  const breakdown = useMemo(
    () => getPnLBreakdown(stats.grossProfit, 23, DEFAULT_PNL_CONFIG),
    [stats],
  );
  const openPositions = useMemo(
    () => MOCK_OPEN_POSITIONS.map((p) => ({ ...p, r: calculateRMultiple(p) })),
    [],
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">P&L Dashboard</h1>
        <p className="mt-1 text-[13px] text-muted-foreground">
          Realized vs unrealized, R-multiple position tracking, and cost coverage.
        </p>
      </div>

      {/* ── Open Positions ───────────────────────────────────────────── */}
      {openPositions.length > 0 && (
        <Card title="Open Positions">
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-white/10 text-left text-muted-foreground">
                  <th className="px-2 py-1">Symbol</th>
                  <th className="px-2 py-1">Side</th>
                  <th className="px-2 py-1">Entry</th>
                  <th className="px-2 py-1">Current</th>
                  <th className="px-2 py-1">SL</th>
                  <th className="px-2 py-1">TP</th>
                  <th className="px-2 py-1">R-Multiple</th>
                </tr>
              </thead>
              <tbody>
                {openPositions.map((pos, i) => (
                  <tr key={i} className="border-b border-white/5">
                    <td className="px-2 py-1 font-medium">{pos.symbol}</td>
                    <td className="px-2 py-1">
                      <Badge tone={pos.direction === "long" ? "green" : "red"}>
                        {pos.direction}
                      </Badge>
                    </td>
                    <td className="px-2 py-1 font-mono">{pos.entryPrice.toFixed(5)}</td>
                    <td className="px-2 py-1 font-mono">{pos.currentPrice.toFixed(5)}</td>
                    <td className="px-2 py-1 font-mono text-red-400">{pos.stopPrice.toFixed(5)}</td>
                    <td className="px-2 py-1 font-mono text-emerald-400">{pos.takeProfit.toFixed(5)}</td>
                    <td className="px-2 py-1">
                      <Badge
                        tone={
                          pos.r.color === "darkgreen"
                            ? "green"
                            : pos.r.color === "green"
                              ? "green"
                              : pos.r.color === "orange"
                                ? "amber"
                                : "red"
                        }
                      >
                        {pos.r.label}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* ── P&L Breakdown ────────────────────────────────────────────── */}
      <div className="grid gap-4 sm:grid-cols-2">
        <Card title="P&L Breakdown">
          <div className="space-y-2 text-[13px]">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Realized P&L</span>
              <span className="font-mono">${stats.grossProfit.toFixed(2)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Unrealized P&L</span>
              <span className="font-mono text-emerald-400">+$23.00</span>
            </div>
            <div className="flex justify-between border-t border-white/10 pt-2">
              <span className="text-muted-foreground">Gross P&L</span>
              <span className="font-mono">${(stats.grossProfit + 23).toFixed(2)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Total Cost</span>
              <span className="font-mono text-red-400">-${DEFAULT_PNL_CONFIG.costProp.toFixed(2)}</span>
            </div>
            <div className="flex justify-between border-t border-white/10 pt-2 font-bold">
              <span className="text-muted-foreground">Net P&L</span>
              <span className={`font-mono ${stats.grossProfit + 23 - DEFAULT_PNL_CONFIG.costProp >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                ${(stats.grossProfit + 23 - DEFAULT_PNL_CONFIG.costProp).toFixed(2)}
              </span>
            </div>
          </div>
        </Card>

        <Card title="Cost Coverage">
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <div className="h-2 w-full overflow-hidden rounded-full bg-white/5">
                <div
                  className="h-full bg-emerald-400 transition-all"
                  style={{ width: `${Math.min(breakdown.costCoveragePct, 100)}%` }}
                />
              </div>
              <p className="mt-2 text-[12px] text-muted-foreground">
                Gross P&L covers <span className="font-bold text-foreground">{breakdown.costCoveragePct.toFixed(0)}%</span> of daily costs
              </p>
            </div>
            <div className="text-right">
              <p className="text-[15px] font-bold text-emerald-400">${(stats.grossProfit + 23).toFixed(0)}</p>
              <p className="text-[11px] text-muted-foreground">vs ${breakdown.totalCost.toFixed(0)} cost</p>
            </div>
          </div>
        </Card>
      </div>

      {/* ── Dashboard Stats ──────────────────────────────────────────── */}
      <Card title="Trade Statistics">
        <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-5">
          <StatBox label="Trades" value={stats.trades.toString()} />
          <StatBox
            label="Win Rate"
            value={`${(stats.winRate * 100).toFixed(0)}%`}
            tone={stats.winRate >= 0.5 ? "green" : "red"}
          />
          <StatBox label="Wins / Losses" value={`${stats.wins}W / ${stats.losses}L`} />
          <StatBox
            label="Profit Factor"
            value={isFinite(stats.profitFactor) ? stats.profitFactor.toFixed(2) : "∞"}
            tone={stats.profitFactor >= 1.5 ? "green" : stats.profitFactor >= 1 ? "amber" : "red"}
          />
          <StatBox label="Avg Win" value={`$${stats.avgWin.toFixed(2)}`} tone="green" />
          <StatBox label="Avg Loss" value={`$${stats.avgLoss.toFixed(2)}`} tone="red" />
          <StatBox label="Total R" value={`${stats.totalR.toFixed(1)}R`} tone="blue" />
          <StatBox label="Expectancy" value={`${stats.expectancyR.toFixed(2)}R`} />
          <StatBox
            label="Max Drawdown"
            value={`${stats.maxDrawdownPct.toFixed(1)}%`}
            tone={stats.maxDrawdownPct <= 10 ? "green" : "amber"}
          />
          <StatBox label="Sharpe" value={stats.sharpeRatio.toFixed(2)} tone="blue" />
        </div>
      </Card>

      {/* ── Loss Streak ──────────────────────────────────────────────── */}
      {stats.lossStreak > 0 && (
        <div className="alert alert-red">
          <p className="alert-title">
            <AlertTriangle size={13} /> Loss Streak
          </p>
          <p className="alert-body">
            {stats.lossStreak} consecutive losses. Consider reducing size or waiting for A+ setups.
          </p>
        </div>
      )}

      {/* ── Trade Log ────────────────────────────────────────────────── */}
      <Card title="Recent Trades">
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-white/10 text-left text-muted-foreground">
                <th className="px-2 py-1">Side</th>
                <th className="px-2 py-1">Entry</th>
                <th className="px-2 py-1">Exit</th>
                <th className="px-2 py-1">SL</th>
                <th className="px-2 py-1">TP</th>
                <th className="px-2 py-1">P&L</th>
                <th className="px-2 py-1">Result</th>
                <th className="px-2 py-1">Reason</th>
              </tr>
            </thead>
            <tbody>
              {MOCK_TRADES.map((t, i) => (
                <tr key={i} className="border-b border-white/5">
                  <td className="px-2 py-1">
                    <Badge tone={t.direction === "long" ? "green" : "red"}>
                      {t.direction}
                    </Badge>
                  </td>
                  <td className="px-2 py-1 font-mono">{t.entryPrice.toFixed(5)}</td>
                  <td className="px-2 py-1 font-mono">{t.exitPrice.toFixed(5)}</td>
                  <td className="px-2 py-1 font-mono">{t.sl.toFixed(5)}</td>
                  <td className="px-2 py-1 font-mono">{t.tp.toFixed(5)}</td>
                  <td className={`px-2 py-1 font-mono ${t.pnlUsd >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {t.pnlUsd >= 0 ? "+" : ""}${t.pnlUsd.toFixed(2)}
                  </td>
                  <td className="px-2 py-1">
                    <Badge
                      tone={
                        t.result === "win"
                          ? "green"
                          : t.result === "loss"
                            ? "red"
                            : "neutral"
                      }
                    >
                      {t.result}
                    </Badge>
                  </td>
                  <td className="px-2 py-1">
                    <Badge tone={t.reason === "tp" ? "green" : "red"}>
                      {t.reason.toUpperCase()}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

/* ── Stat Box ─────────────────────────────────────────────────────────── */

function StatBox({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "green" | "red" | "blue" | "amber" | "neutral";
}) {
  const colors: Record<string, string> = {
    green: "text-emerald-400",
    red: "text-red-400",
    blue: "text-blue-400",
    amber: "text-amber-400",
    neutral: "text-foreground",
  };
  return (
    <div className="rounded-md border border-white/5 bg-white/[0.02] p-3">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className={`mt-1 text-[16px] font-bold ${colors[tone]}`}>{value}</p>
    </div>
  );
}

/* ── Imports from pnl-dashboard.ts ─────────────────────────────────────── */

import {
  calculateRMultiple,
  calcDashboardStats,
  getPnLBreakdown,
  DEFAULT_PNL_CONFIG,
  type Trade,
  type OpenPosition,
} from "@/lib/pnl-dashboard";
