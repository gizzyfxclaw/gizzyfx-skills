// @ts-nocheck
/**
 * GizzyFx SMC (Smart Money Concepts) Engine
 *
 * Ports the hermes-market-skills SMC detectors from Python (pandas) to
 * TypeScript so they run deterministically inside the GizzyFx backtest engine
 * and analysis pages. Pure functions only — no I/O.
 *
 * Detectors:
 * - findSwings       — fractal pivot detection
 * - detectStructure  — HH/HL/LH/LL classification, BOS / CHoCH
 * - findOrderBlocks  — last opposite candle before impulsive ATR move
 * - findFVG          — 3-candle imbalance (fair value gap)
 * - findLiquiditySweeps — false breakout of swing high/low
 * - premiumDiscount  — Fib 0.5 zone split
 * - summarize        — convenience: all detectors into one object
 */

/* ── Types ─────────────────────────────────────────────────────────────── */

export interface Bar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

interface Swing {
  idx: number;
  price: number;
  kind: 'high' | 'low';
}

interface OrderBlock {
  low: number;
  high: number;
  kind: 'bullish' | 'bearish';
  idx: number;
  impulseMag: number;
}

interface FVG {
  low: number;
  high: number;
  kind: 'bullish' | 'bearish';
  idx: number;
  filled: boolean;
}

interface Sweep {
  idx: number;
  kind: 'bullish' | 'bearish';
  sweptLevel: number;
  close: number;
}

export interface StructureResult {
  swings: Swing[];
  bias: 'bullish' | 'bearish' | 'neutral';
  bos: 'bullish' | 'bearish' | null;
  choch: 'bullish' | 'bearish' | null;
  lastBosIdx: number | null;
  lastChochIdx: number | null;
}

export interface SMCResult {
  ok: boolean;
  error?: string;
  structure: StructureResult;
  orderBlocks: OrderBlock[];
  fvgs: FVG[];
  sweeps: Sweep[];
  zone: { zone: string; depthPct?: number; rangeHigh?: number; rangeLow?: number; rangeMid?: number };
  summary: string;
}

/* ── Helpers ────────────────────────────────────────────────────────────── */

function atr(bars: Bar[], period = 14): number {
  if (bars.length < period + 1) return NaN;
  const tr: number[] = [];
  for (let i = 0; i < bars.length; i++) {
    const hl = bars[i].high - bars[i].low;
    if (i === 0) {
      tr.push(hl);
    } else {
      const hc = Math.abs(bars[i].high - bars[i - 1].close);
      const lc = Math.abs(bars[i].low - bars[i - 1].close);
      tr.push(Math.max(hl, hc, lc));
    }
  }
  let sum = 0;
  for (let i = 0; i < period; i++) sum += tr[i];
  return sum / period;
}

/* ── Swing Detection ────────────────────────────────────────────────────── */

export function findSwings(bars: Bar[], window = 3): Swing[] {
  if (!bars || bars.length < 2 * window + 1) return [];
  const swings: Swing[] = [];
  const n = bars.length;
  for (let i = window; i < n - window; i++) {
    let isHigh = true;
    let isLow = true;
    for (let j = i - window; j <= i + window; j++) {
      if (j === i) continue;
      if (bars[j].high >= bars[i].high) isHigh = false;
      if (bars[j].low <= bars[i].low) isLow = false;
      if (!isHigh && !isLow) break;
    }
    if (isHigh) swings.push({ idx: i, price: bars[i].high, kind: 'high' });
    else if (isLow) swings.push({ idx: i, price: bars[i].low, kind: 'low' });
  }
  return swings;
}

/* ── Structure Detection (BOS / CHoCH) ──────────────────────────────────── */

export function detectStructure(bars: Bar[], swings?: Swing[], window = 3): StructureResult {
  const sw = swings ?? findSwings(bars, window);
  if (sw.length < 4 || bars.length < 5) {
    return { swings: sw, bias: 'neutral', bos: null, choch: null, lastBosIdx: null, lastChochIdx: null };
  }

  // Alternate: remove consecutive same-kind swings (keep most extreme)
  const alt: Swing[] = [];
  for (const s of sw) {
    if (alt.length > 0 && alt[alt.length - 1].kind === s.kind) {
      const prev = alt[alt.length - 1];
      if (s.kind === 'high' && s.price > prev.price) alt[alt.length - 1] = s;
      else if (s.kind === 'low' && s.price < prev.price) alt[alt.length - 1] = s;
    } else {
      alt.push(s);
    }
  }

  // Determine bias from last 6 swings
  const last = alt.length >= 6 ? alt.slice(-6) : alt;
  let bias: 'bullish' | 'bearish' | 'neutral' = 'neutral';
  const highs = last.filter(s => s.kind === 'high');
  const lows = last.filter(s => s.kind === 'low');
  if (highs.length >= 2 && lows.length >= 2) {
    if (highs[highs.length - 1].price > highs[highs.length - 2].price &&
        lows[lows.length - 1].price > lows[lows.length - 2].price) {
      bias = 'bullish';
    } else if (highs[highs.length - 1].price < highs[highs.length - 2].price &&
               lows[lows.length - 1].price < lows[lows.length - 2].price) {
      bias = 'bearish';
    }
  }

  // BOS and CHoCH detection
  let bos: 'bullish' | 'bearish' | null = null;
  let choch: 'bullish' | 'bearish' | null = null;
  let lastBosIdx: number | null = null;
  let lastChochIdx: number | null = null;

  for (let si = alt.length - 2; si >= 0; si--) {
    if (bos !== null && choch !== null) break;
    const s = alt[si];
    if (s.kind === 'high') {
      for (let k = s.idx + 1; k < bars.length; k++) {
        if (bars[k].close > s.price) {
          if (bias === 'bullish' && bos === null) { bos = 'bullish'; lastBosIdx = k; }
          else if (bias === 'bearish' && choch === null) { choch = 'bullish'; lastChochIdx = k; }
          break;
        }
      }
    } else {
      for (let k = s.idx + 1; k < bars.length; k++) {
        if (bars[k].close < s.price) {
          if (bias === 'bearish' && bos === null) { bos = 'bearish'; lastBosIdx = k; }
          else if (bias === 'bullish' && choch === null) { choch = 'bearish'; lastChochIdx = k; }
          break;
        }
      }
    }
  }

  return { swings: alt.slice(-8), bias, bos, choch, lastBosIdx, lastChochIdx };
}

/* ── Order Blocks ───────────────────────────────────────────────────────── */

export function findOrderBlocks(bars: Bar[], impulseMult = 1.5, maxAge = 60): OrderBlock[] {
  if (!bars || bars.length < 30) return [];
  const a = atr(bars, 14);
  if (!a || a <= 0 || isNaN(a)) return [];

  const obs: OrderBlock[] = [];
  const n = bars.length;
  const start = Math.max(0, n - maxAge - 10);
  const window = 3;

  for (let i = start; i < n - window - 1; i++) {
    const candle = bars[i];
    const bearishCandle = candle.close < candle.open;
    const bullishCandle = candle.close > candle.open;

    let futureMax = -Infinity;
    let futureMin = Infinity;
    for (let j = i + 1; j <= Math.min(i + window, n - 1); j++) {
      futureMax = Math.max(futureMax, bars[j].close);
      futureMin = Math.min(futureMin, bars[j].close);
    }

    if (bearishCandle && (futureMax - candle.close) >= impulseMult * a) {
      obs.push({
        low: candle.low,
        high: candle.high,
        kind: 'bullish',
        idx: i,
        impulseMag: (futureMax - candle.close) / a,
      });
    } else if (bullishCandle && (candle.close - futureMin) >= impulseMult * a) {
      obs.push({
        low: candle.low,
        high: candle.high,
        kind: 'bearish',
        idx: i,
        impulseMag: (candle.close - futureMin) / a,
      });
    }
  }
  return obs.slice(-10);
}

/* ── Fair Value Gaps ────────────────────────────────────────────────────── */

export function findFVG(bars: Bar[], maxAge = 60): FVG[] {
  if (!bars || bars.length < 5) return [];
  const n = bars.length;
  const fvgs: FVG[] = [];
  const start = Math.max(1, n - maxAge);

  for (let i = start; i < n - 1; i++) {
    if (bars[i + 1].low > bars[i - 1].high) {
      // bullish FVG
      const gapLow = bars[i - 1].high;
      const gapHigh = bars[i + 1].low;
      let filled = false;
      for (let k = i + 2; k < n; k++) {
        if (bars[k].low <= gapLow) { filled = true; break; }
      }
      fvgs.push({ low: gapLow, high: gapHigh, kind: 'bullish', idx: i, filled });
    } else if (bars[i + 1].high < bars[i - 1].low) {
      // bearish FVG
      const gapLow = bars[i + 1].high;
      const gapHigh = bars[i - 1].low;
      let filled = false;
      for (let k = i + 2; k < n; k++) {
        if (bars[k].high >= gapHigh) { filled = true; break; }
      }
      fvgs.push({ low: gapLow, high: gapHigh, kind: 'bearish', idx: i, filled });
    }
  }
  return fvgs.slice(-15);
}

/* ── Liquidity Sweeps ───────────────────────────────────────────────────── */

export function findLiquiditySweeps(bars: Bar[], swings?: Swing[], maxAge = 30): Sweep[] {
  const sw = swings ?? findSwings(bars);
  if (sw.length === 0 || !bars || bars.length < 10) return [];

  const sweeps: Sweep[] = [];
  const n = bars.length;
  const start = Math.max(0, n - maxAge);

  for (let i = start; i < n; i++) {
    let found = false;
    for (const s of sw) {
      if (s.idx >= i) continue;
      if (i - s.idx > maxAge) continue;
      if (s.kind === 'low' && bars[i].low < s.price && bars[i].close > s.price) {
        sweeps.push({ idx: i, kind: 'bullish', sweptLevel: s.price, close: bars[i].close });
        found = true;
        break;
      }
      if (s.kind === 'high' && bars[i].high > s.price && bars[i].close < s.price) {
        sweeps.push({ idx: i, kind: 'bearish', sweptLevel: s.price, close: bars[i].close });
        found = true;
        break;
      }
    }
  }
  return sweeps.slice(-10);
}

/* ── Premium / Discount Zone ────────────────────────────────────────────── */

export function premiumDiscount(bars: Bar[], lookback = 50): { zone: string; depthPct?: number; rangeHigh?: number; rangeLow?: number; rangeMid?: number } {
  if (!bars || bars.length < 10) return { zone: 'unknown' };
  const sub = bars.slice(-Math.min(lookback, bars.length));
  let rangeHigh = -Infinity;
  let rangeLow = Infinity;
  for (const b of sub) {
    rangeHigh = Math.max(rangeHigh, b.high);
    rangeLow = Math.min(rangeLow, b.low);
  }
  const mid = (rangeHigh + rangeLow) / 2;
  const last = bars[bars.length - 1].close;
  if (last >= mid) {
    return {
      zone: 'premium',
      depthPct: ((last - mid) / (rangeHigh - mid)) * 100,
      rangeHigh,
      rangeLow,
      rangeMid: mid,
    };
  }
  return {
    zone: 'discount',
    depthPct: ((mid - last) / (mid - rangeLow)) * 100,
    rangeHigh,
    rangeLow,
    rangeMid: mid,
  };
}

/* ── Top-Level Summary ──────────────────────────────────────────────────── */

export function summarizeSMC(bars: Bar[], window = 3): SMCResult {
  if (!bars || bars.length === 0) {
    return {
      ok: false,
      error: 'empty bars',
      structure: { swings: [], bias: 'neutral', bos: null, choch: null, lastBosIdx: null, lastChochIdx: null },
      orderBlocks: [],
      fvgs: [],
      sweeps: [],
      zone: { zone: 'unknown' },
      summary: 'no data',
    };
  }

  const swings = findSwings(bars, window);
  const structure = detectStructure(bars, swings, window);
  const orderBlocks = findOrderBlocks(bars);
  const fvgs = findFVG(bars);
  const sweeps = findLiquiditySweeps(bars, swings);
  const zone = premiumDiscount(bars);

  const parts: string[] = [`bias=${structure.bias}`];
  if (structure.bos) parts.push(`BOS=${structure.bos}`);
  if (structure.choch) parts.push(`CHoCH=${structure.choch}`);
  const bullObs = orderBlocks.filter(o => o.kind === 'bullish');
  const bearObs = orderBlocks.filter(o => o.kind === 'bearish');
  if (bullObs.length) parts.push(`OB_bull=${bullObs.length}`);
  if (bearObs.length) parts.push(`OB_bear=${bearObs.length}`);
  const unfilledBull = fvgs.filter(f => f.kind === 'bullish' && !f.filled);
  const unfilledBear = fvgs.filter(f => f.kind === 'bearish' && !f.filled);
  if (unfilledBull.length) parts.push(`FVG_bull_open=${unfilledBull.length}`);
  if (unfilledBear.length) parts.push(`FVG_bear_open=${unfilledBear.length}`);
  if (sweeps.length) {
    const last = sweeps[sweeps.length - 1];
    parts.push(`sweep_${last.kind}@${last.sweptLevel.toFixed(5)}`);
  }
  parts.push(`zone=${zone.zone}`);

  return {
    ok: true,
    structure,
    orderBlocks,
    fvgs,
    sweeps,
    zone,
    summary: parts.join('; '),
  };
}
