import type { Bar } from "./smc-engine";

export interface PatternResult {
  pattern: string;
  quality: "High" | "Medium" | "Low";
  direction: "bullish" | "bearish" | "neutral";
  timeframe: string;
  priorTrend: "up" | "down" | "range";
  entry: { aggressive: string; conservative: string };
  stopLoss: string;
  targets: { t1: string; t2: string };
  invalidation: string;
  confidence: number;
}

const PIP = 0.0001;
const TOLERANCE = 5 * PIP;

function findSwings(bars: Bar[], lb: number) {
  const highs: number[] = [];
  const lows: number[] = [];
  for (let i = lb; i < bars.length - lb; i++) {
    let isH = true, isL = true;
    for (let j = i - lb; j <= i + lb; j++) {
      if (j === i) continue;
      if (bars[j].high >= bars[i].high) isH = false;
      if (bars[j].low <= bars[i].low) isL = false;
    }
    if (isH) highs.push(i);
    if (isL) lows.push(i);
  }
  return { highs, lows };
}

function detectDoubleTop(bars: Bar[], s: { highs: number[]; lows: number[] }): PatternResult | null {
  if (s.highs.length < 2) return null;
  const h1 = s.highs[s.highs.length - 1], h2 = s.highs[s.highs.length - 2];
  if (Math.abs(bars[h1].high - bars[h2].high) <= TOLERANCE && bars[h1].high > bars[h2].high * 0.99) {
    let neck = Infinity;
    for (let i = h2; i <= h1; i++) neck = Math.min(neck, bars[i].low);
    const h = bars[h1].high - neck;
    return { pattern: "Double Top", quality: "High", direction: "bearish", timeframe: "current", priorTrend: "up",
      entry: { conservative: `Break below neckline at ${neck.toFixed(5)}`, aggressive: `Sell at current price` },
      stopLoss: `Above ${bars[h1].high.toFixed(5)}`, targets: { t1: `${(neck - h * 0.5).toFixed(5)}`, t2: `${(neck - h).toFixed(5)}` },
      invalidation: `Break above ${bars[h1].high.toFixed(5)}`, confidence: 0.75 };
  }
  return null;
}

function detectDoubleBottom(bars: Bar[], s: { highs: number[]; lows: number[] }): PatternResult | null {
  if (s.lows.length < 2) return null;
  const l1 = s.lows[s.lows.length - 1], l2 = s.lows[s.lows.length - 2];
  if (Math.abs(bars[l1].low - bars[l2].low) <= TOLERANCE && bars[l1].low < bars[l2].low * 1.01) {
    let neck = -Infinity;
    for (let i = l2; i <= l1; i++) neck = Math.max(neck, bars[i].high);
    const h = neck - bars[l1].low;
    return { pattern: "Double Bottom", quality: "High", direction: "bullish", timeframe: "current", priorTrend: "down",
      entry: { conservative: `Break above neckline at ${neck.toFixed(5)}`, aggressive: `Buy at current price` },
      stopLoss: `Below ${bars[l1].low.toFixed(5)}`, targets: { t1: `${(neck + h * 0.5).toFixed(5)}`, t2: `${(neck + h).toFixed(5)}` },
      invalidation: `Break below ${bars[l1].low.toFixed(5)}`, confidence: 0.75 };
  }
  return null;
}

function detectTriangle(bars: Bar[], s: { highs: number[]; lows: number[] }): PatternResult | null {
  if (s.highs.length < 3 || s.lows.length < 3) return null;
  const rh = s.highs.slice(-3), rl = s.lows.slice(-3);
  const hTrend = bars[rh[2]].high - bars[rh[0]].high;
  const lTrend = bars[rl[2]].low - bars[rl[0]].low;
  let pattern: string, dir: "bullish" | "bearish" | "neutral";
  if (Math.abs(hTrend) <= TOLERANCE && lTrend > TOLERANCE) { pattern = "Ascending Triangle"; dir = "bullish"; }
  else if (hTrend < -TOLERANCE && Math.abs(lTrend) <= TOLERANCE) { pattern = "Descending Triangle"; dir = "bearish"; }
  else if (hTrend < -TOLERANCE && lTrend > TOLERANCE) { pattern = "Symmetrical Triangle"; dir = "neutral"; }
  else return null;
  const res = Math.min(...rh.map(i => bars[i].high));
  const sup = Math.max(...rl.map(i => bars[i].low));
  const h = res - sup;
  return { pattern, quality: "Medium", direction: dir, timeframe: "current", priorTrend: dir === "bullish" ? "up" : dir === "bearish" ? "down" : "range",
    entry: { conservative: `Break of ${res.toFixed(5)} or ${sup.toFixed(5)}`, aggressive: `Enter at ${(bars[bars.length-1].close + (dir === "bullish" ? h * 0.1 : -h * 0.1)).toFixed(5)}` },
    stopLoss: dir === "bullish" ? `Below ${sup.toFixed(5)}` : dir === "bearish" ? `Above ${res.toFixed(5)}` : `Outside triangle`,
    targets: { t1: dir === "bullish" ? `${(res + h * 0.5).toFixed(5)}` : dir === "bearish" ? `${(sup - h * 0.5).toFixed(5)}` : `${(res + h * 0.5).toFixed(5)} / ${(sup - h * 0.5).toFixed(5)}`,
              t2: dir === "bullish" ? `${(res + h).toFixed(5)}` : dir === "bearish" ? `${(sup - h).toFixed(5)}` : `${(res + h).toFixed(5)} / ${(sup - h).toFixed(5)}` },
    invalidation: `No breakout`, confidence: 0.5 };
}

function detectFlag(bars: Bar[]): PatternResult | null {
  if (bars.length < 20) return null;
  const move = (bars[bars.length-1].close - bars[bars.length-15].close) / bars[bars.length-15].close;
  if (Math.abs(move) < 0.005) return null;
  const bull = move > 0;
  const last5 = bars.slice(-5);
  const avgR = last5.reduce((s, b) => s + (b.high - b.low), 0) / 5;
  const avgR20 = bars.slice(-20).reduce((s, b) => s + (b.high - b.low), 0) / 20;
  if (avgR < avgR20 * 0.7) {
    const fH = Math.max(...last5.map(b => b.high));
    const fL = Math.min(...last5.map(b => b.low));
    return { pattern: bull ? "Bull Flag" : "Bear Flag", quality: "Medium", direction: bull ? "bullish" : "bearish", timeframe: "current", priorTrend: bull ? "up" : "down",
      entry: { conservative: bull ? `Break above ${fH.toFixed(5)}` : `Break below ${fL.toFixed(5)}`, aggressive: `Enter at ${bars[bars.length-1].close.toFixed(5)}` },
      stopLoss: bull ? `Below ${fL.toFixed(5)}` : `Above ${fH.toFixed(5)}`,
      targets: { t1: bull ? `${(fH + (fH - bars[bars.length-15].close) * 0.5).toFixed(5)}` : `${(fL - (bars[bars.length-15].close - fL) * 0.5).toFixed(5)}`,
                t2: bull ? `${(fH + (fH - bars[bars.length-15].close)).toFixed(5)}` : `${(fL - (bars[bars.length-15].close - fL)).toFixed(5)}` },
      invalidation: bull ? `Close below ${fL.toFixed(5)}` : `Close above ${fH.toFixed(5)}`, confidence: 0.6 };
  }
  return null;
}

export function detectPatterns(bars: Bar[]): PatternResult[] {
  if (bars.length < 15) return [];
  const s = findSwings(bars, 5);
  const results: PatternResult[] = [];
  const dt = detectDoubleTop(bars, s); if (dt) results.push(dt);
  const db = detectDoubleBottom(bars, s); if (db) results.push(db);
  const tri = detectTriangle(bars, s); if (tri) results.push(tri);
  const flag = detectFlag(bars); if (flag) results.push(flag);
  return results.sort((a, b) => b.confidence - a.confidence);
}
