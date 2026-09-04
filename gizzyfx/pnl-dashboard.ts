// @ts-nocheck
/**
 * GizzyFx P&L Dashboard Engine
 *
 * Ports dashboard-pnl-visualization concepts (realized/unrealized split,
 * R-multiple color coding, win-rate overlay, loss streak, cost coverage)
 * from Alpaca/US-stocks Python → TypeScript for GizzyFx forex.
 */

export interface Trade {
  entryTime: number;
  exitTime: number;
  direction: "long" | "short";
  entryPrice: number;
  exitPrice: number;
  sl: number;
  tp: number;
  pnlUsd: number;
  pnlPips: number;
  result: "win" | "loss" | "breakeven";
  reason: "tp" | "sl";
}

export interface OpenPosition {
  symbol: string;
  direction: "long" | "short";
  entryPrice: number;
  currentPrice: number;
  stopPrice: number;
  takeProfit: number;
  size: number;
  entryTime: number;
}

export interface PnLConfig {
  /** Daily data cost in USD (tvremix, etc). */
  costData: number;
  /** Daily software cost in USD (MetaApi, Hermes, etc). */
  costSoftware: number;
  /** Daily prop challenge cost amortized (fee / challenge days). */
  costProp: number;
  /** Risk limit percentage for daily loss cap. */
  riskLimitPct: number;
}

export interface RMultiple {
  value: number | null;
  color: "gray" | "orange" | "green" | "darkgreen";
  label: string;
}

export interface PnLBreakdown {
  grossPnl: number;
  realizedPnl: number;
  unrealizedPnl: number;
  netPnl: number;
  dataCost: number;
  softwareCost: number;
  propCost: number;
  totalCost: number;
  costCoveragePct: number;
}

export interface DashboardStats {
  trades: number;
  wins: number;
  losses: number;
  winRate: number;
  lossStreak: number;
  avgWin: number;
  avgLoss: number;
  profitFactor: number;
  maxDrawdownPct: number;
  sharpeRatio: number;
  totalR: number;
  expectancyR: number;
  grossProfit: number;
}

/**
 * Calculate R-multiple for an open position.
 * R-multiple = profit / risk (in price terms).
 * e.g. entry 1.1000, SL 1.0950 (50 pips risk), current 1.1075 (75 pips profit) → R=1.5
 */
export function calculateRMultiple(pos: OpenPosition): RMultiple {
  const { entryPrice, currentPrice, stopPrice, direction } = pos;
  if (!stopPrice || stopPrice === 0) {
    return { value: null, color: "gray", label: "No SL" };
  }
  let risk: number;
  let profit: number;
  if (direction === "long") {
    risk = entryPrice - stopPrice;
    profit = currentPrice - entryPrice;
  } else {
    risk = stopPrice - entryPrice;
    profit = entryPrice - currentPrice;
  }
  if (risk <= 0) {
    return { value: null, color: "gray", label: "Invalid" };
  }
  const rMultiple = profit / risk;
  let color: RMultiple["color"];
  let label: string;
  if (rMultiple >= 2.0) {
    color = "darkgreen";
    label = `R${rMultiple.toFixed(1)} (Excellent)`;
  } else if (rMultiple >= 1.0) {
    color = "green";
    label = `R${rMultiple.toFixed(1)} (Good)`;
  } else if (rMultiple >= 0) {
    color = "orange";
    label = `R${rMultiple.toFixed(1)} (Below)`;
  } else {
    color = "red" as any;
    label = `R${rMultiple.toFixed(1)} (Loss)`;
  }
  return { value: rMultiple, color, label };
}

/**
 * Calculate P&L breakdown with realized/unrealized split.
 */
export function getPnLBreakdown(
  realizedPnl: number,
  unrealizedPnl: number,
  cfg: PnLConfig,
): PnLBreakdown {
  const grossPnl = realizedPnl + unrealizedPnl;
  const totalCost = cfg.costData + cfg.costSoftware + cfg.costProp;
  const netPnl = grossPnl - totalCost;
  const costCoveragePct = totalCost > 0 ? (grossPnl / totalCost) * 100 : 0;
  return {
    grossPnl,
    realizedPnl,
    unrealizedPnl,
    netPnl,
    dataCost: cfg.costData,
    softwareCost: cfg.costSoftware,
    propCost: cfg.costProp,
    totalCost,
    costCoveragePct,
  };
}

/**
 * Calculate dashboard statistics from a trade list.
 */
export function calcDashboardStats(trades: Trade[]): DashboardStats {
  if (trades.length === 0) {
    return {
      trades: 0, wins: 0, losses: 0, winRate: 0,
      lossStreak: 0, avgWin: 0, avgLoss: 0, profitFactor: 0,
      maxDrawdownPct: 0, sharpeRatio: 0, totalR: 0, expectancyR: 0,
    };
  }
  const wins = trades.filter((t) => t.result === "win");
  const losses = trades.filter((t) => t.result === "loss");
  const winRate = wins.length / trades.length;

  // Loss streak (count consecutive losses from most recent)
  let lossStreak = 0;
  for (let i = trades.length - 1; i >= 0; i--) {
    if (trades[i].result === "loss") lossStreak++;
    else break;
  }

  const grossProfit = wins.reduce((s, t) => s + t.pnlUsd, 0);
  const grossLoss = Math.abs(losses.reduce((s, t) => s + t.pnlUsd, 0));
  const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? Infinity : 0;
  const avgWin = wins.length > 0 ? grossProfit / wins.length : 0;
  const avgLoss = losses.length > 0 ? grossLoss / losses.length : 0;

  // R-multiples per trade (pips won / average loss pips)
  const avgLossPips = losses.length > 0
    ? losses.reduce((s, t) => s + Math.abs(t.pnlPips), 0) / losses.length
    : 1;
  const rMultiples = trades.map((t) => t.pnlPips / avgLossPips);
  const totalR = rMultiples.reduce((a, b) => a + b, 0);
  const expectancyR = totalR / trades.length;

  // Max drawdown from equity curve
  let peak = -Infinity;
  let maxDD = 0;
  let cumulative = 0;
  for (const t of trades) {
    cumulative += t.pnlUsd;
    peak = Math.max(peak, cumulative);
    const dd = peak > 0 ? ((peak - cumulative) / peak) * 100 : 0;
    maxDD = Math.max(maxDD, dd);
  }

  // Sharpe from R-multiples (annualized)
  const meanR = expectancyR;
  const variance = rMultiples.reduce((a, b) => a + (b - meanR) ** 2, 0) / rMultiples.length;
  const stdDev = Math.sqrt(variance);
  const sharpeRatio = stdDev > 0 ? (meanR / stdDev) * Math.sqrt(252) : 0;

  return {
    trades: trades.length,
    wins: wins.length,
    losses: losses.length,
    winRate,
    lossStreak,
    avgWin,
    avgLoss,
    profitFactor,
    maxDrawdownPct: maxDD,
    sharpeRatio,
    totalR,
    expectancyR,
    grossProfit,
  };
}

/**
 * Default config for GizzyFx.
 * $5k prop fee = $28.60 amortized over 60 days ≈ $0.48/day
 * tvremix = free tier (0)
 * MetaApi = free tier for demo accounts
 * Hermes = free tier (nous)
 */
export const DEFAULT_PNL_CONFIG: PnLConfig = {
  costData: 0,
  costSoftware: 0,
  costProp: 0.48,
  riskLimitPct: 10,
};
