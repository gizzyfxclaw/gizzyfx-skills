"""Smart Money Concepts (SMC) detectors for crypto/forex price action.

All detectors are pure-pandas / pure-numpy — no extra dependencies. Output is
designed to plug into ``signals.evaluate`` as additional Votes via the
``ctx.smc`` field.

Detector summary
----------------
- ``find_swings`` — ZigZag-style pivot detection with a fractal window.
- ``detect_structure`` — most recent swings classified as HH/HL/LH/LL plus the
  most recent BOS (break of structure) and CHoCH (change of character).
- ``find_order_blocks`` — last opposite-color candle prior to an impulsive
  move; returned as ``[(low, high, kind="bullish"|"bearish", ts)]``.
- ``find_fvg`` — 3-candle imbalance where candle[1] gap is not filled by
  wicks of candle[0] / candle[2].
- ``find_liquidity_sweeps`` — swing high/low broken intrabar then closed back
  inside (false breakout).
- ``premium_discount_zone`` — split of the last range by the 0.5 Fib level.
- ``summarize`` — convenience: assemble all detectors into a single dict
  consumed by ``signals.evaluate``.

The implementation is deliberately conservative: false positives cost more
than missed setups in a rule-based engine, so each detector requires a clear
geometric confirmation (close-based, no wick-only triggers).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd


# ---------------- data classes ----------------


@dataclass
class Swing:
    idx: int
    ts: pd.Timestamp
    price: float
    kind: str  # "high" or "low"


@dataclass
class OrderBlock:
    low: float
    high: float
    kind: str          # "bullish" (demand) | "bearish" (supply)
    ts: pd.Timestamp
    idx: int
    impulse_mag: float  # |impulse close - OB close| / atr ish


@dataclass
class FVG:
    low: float
    high: float
    kind: str          # "bullish" (gap up, unfilled) | "bearish"
    ts: pd.Timestamp
    idx: int
    filled: bool


@dataclass
class Sweep:
    ts: pd.Timestamp
    idx: int
    kind: str          # "bullish" (swept low + closed back up) | "bearish"
    swept_level: float
    close: float


@dataclass
class Structure:
    last_swings: list[Swing]
    bias: str           # "bullish" | "bearish" | "neutral"
    bos: str | None     # "bullish" | "bearish" | None
    choch: str | None   # "bullish" | "bearish" | None
    last_bos_idx: int | None
    last_choch_idx: int | None


# ---------------- helpers ----------------


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return float("nan")
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


# ---------------- swings ----------------


def find_swings(df: pd.DataFrame, window: int = 3) -> list[Swing]:
    """Fractal swing detection.

    A bar is a swing-high if its high is the maximum of the surrounding
    ``window`` bars on both sides; similarly for swing-low. Last/first
    ``window`` bars are skipped (not enough context).
    """
    if df is None or len(df) < 2 * window + 1:
        return []
    high = df["high"].astype(float).to_numpy()
    low = df["low"].astype(float).to_numpy()
    ts = df.index
    swings: list[Swing] = []
    n = len(df)
    for i in range(window, n - window):
        h_window = high[i - window:i + window + 1]
        l_window = low[i - window:i + window + 1]
        if high[i] == h_window.max() and (h_window == high[i]).sum() == 1:
            swings.append(Swing(i, ts[i], float(high[i]), "high"))
        elif low[i] == l_window.min() and (l_window == low[i]).sum() == 1:
            swings.append(Swing(i, ts[i], float(low[i]), "low"))
    return swings


# ---------------- structure (BOS / CHoCH) ----------------


def detect_structure(df: pd.DataFrame, swings: list[Swing] | None = None,
                     window: int = 3) -> Structure:
    """Classify the recent swing sequence and detect BOS / CHoCH.

    Strategy
    ~~~~~~~~
    1. Walk the swing list, alternating high/low to derive HH/HL/LH/LL.
    2. The trailing trio determines bias: HH+HL = bullish, LH+LL = bearish.
    3. BOS = most recent close that breaks the prior swing high (bullish) or
       low (bearish) *in the direction of bias*.
    4. CHoCH = most recent close that breaks the prior swing *against* bias
       (signals a regime change).
    """
    swings = swings if swings is not None else find_swings(df, window=window)
    if not swings or len(df) < 5:
        return Structure([], "neutral", None, None, None, None)

    # alternate to remove consecutive same-kind swings (keep most extreme)
    alt: list[Swing] = []
    for s in swings:
        if alt and alt[-1].kind == s.kind:
            if s.kind == "high" and s.price > alt[-1].price:
                alt[-1] = s
            elif s.kind == "low" and s.price < alt[-1].price:
                alt[-1] = s
        else:
            alt.append(s)

    last = alt[-6:] if len(alt) >= 6 else alt
    bias = "neutral"
    if len(last) >= 4:
        highs = [s.price for s in last if s.kind == "high"][-2:]
        lows = [s.price for s in last if s.kind == "low"][-2:]
        if len(highs) >= 2 and len(lows) >= 2:
            if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
                bias = "bullish"
            elif highs[-1] < highs[-2] and lows[-1] < lows[-2]:
                bias = "bearish"

    closes = df["close"].astype(float).to_numpy()
    bos: str | None = None
    choch: str | None = None
    last_bos_idx: int | None = None
    last_choch_idx: int | None = None
    for s in reversed(alt[:-1]):
        if last_bos_idx is not None and last_choch_idx is not None:
            break
        # check all closes after this swing
        future = closes[s.idx + 1:]
        if s.kind == "high":
            broken = np.where(future > s.price)[0]
            if broken.size:
                rel_idx = int(broken[0]) + s.idx + 1
                if bias == "bullish" and bos is None:
                    bos, last_bos_idx = "bullish", rel_idx
                elif bias == "bearish" and choch is None:
                    choch, last_choch_idx = "bullish", rel_idx
        else:  # low
            broken = np.where(future < s.price)[0]
            if broken.size:
                rel_idx = int(broken[0]) + s.idx + 1
                if bias == "bearish" and bos is None:
                    bos, last_bos_idx = "bearish", rel_idx
                elif bias == "bullish" and choch is None:
                    choch, last_choch_idx = "bearish", rel_idx
    return Structure(alt[-8:], bias, bos, choch, last_bos_idx, last_choch_idx)


# ---------------- order blocks ----------------


def find_order_blocks(df: pd.DataFrame, *, impulse_atr_mult: float = 1.5,
                      window: int = 3, max_age: int = 60) -> list[OrderBlock]:
    """Last opposite-colour candle preceding an impulsive move.

    Bullish OB: down candle (close<open) immediately followed within ``window``
    bars by an impulsive bullish move >= ``impulse_atr_mult`` * ATR(14).
    Bearish OB: mirror.
    """
    if df is None or len(df) < 30:
        return []
    atr = _atr(df, 14)
    if not (atr and atr > 0):
        return []
    opens = df["open"].astype(float).to_numpy()
    highs = df["high"].astype(float).to_numpy()
    lows = df["low"].astype(float).to_numpy()
    closes = df["close"].astype(float).to_numpy()
    ts = df.index
    n = len(df)
    obs: list[OrderBlock] = []
    start = max(0, n - max_age)
    for i in range(start, n - window - 1):
        # bullish OB: candle i is bearish; look ahead window bars
        bearish_candle = closes[i] < opens[i]
        bullish_candle = closes[i] > opens[i]
        future_close_max = closes[i + 1:i + window + 1].max() if i + 1 < n else 0
        future_close_min = closes[i + 1:i + window + 1].min() if i + 1 < n else 0
        if bearish_candle and (future_close_max - closes[i]) >= impulse_atr_mult * atr:
            obs.append(OrderBlock(
                low=float(lows[i]), high=float(highs[i]),
                kind="bullish", ts=ts[i], idx=i,
                impulse_mag=float((future_close_max - closes[i]) / atr),
            ))
        elif bullish_candle and (closes[i] - future_close_min) >= impulse_atr_mult * atr:
            obs.append(OrderBlock(
                low=float(lows[i]), high=float(highs[i]),
                kind="bearish", ts=ts[i], idx=i,
                impulse_mag=float((closes[i] - future_close_min) / atr),
            ))
    return obs[-10:]  # keep last 10 to keep payload small


# ---------------- fair value gaps ----------------


def find_fvg(df: pd.DataFrame, *, max_age: int = 60) -> list[FVG]:
    """3-candle imbalance detection (ICT-style FVG).

    Bullish FVG: low[i+1] > high[i-1]. The gap = (high[i-1], low[i+1]).
    Bearish FVG: high[i+1] < low[i-1]. The gap = (high[i+1], low[i-1]).
    A FVG is "filled" if a later candle's range fully overlaps the gap.
    """
    if df is None or len(df) < 5:
        return []
    highs = df["high"].astype(float).to_numpy()
    lows = df["low"].astype(float).to_numpy()
    ts = df.index
    n = len(df)
    fvgs: list[FVG] = []
    start = max(1, n - max_age)
    for i in range(start, n - 1):
        # bullish FVG at i (gap between i-1 high and i+1 low)
        if lows[i + 1] > highs[i - 1]:
            gap_low, gap_high = float(highs[i - 1]), float(lows[i + 1])
            # filled if any subsequent low <= gap_low (price re-enters fully)
            filled = bool(np.any(lows[i + 2:] <= gap_low)) if i + 2 < n else False
            fvgs.append(FVG(gap_low, gap_high, "bullish", ts[i], i, filled))
        elif highs[i + 1] < lows[i - 1]:
            gap_low, gap_high = float(highs[i + 1]), float(lows[i - 1])
            filled = bool(np.any(highs[i + 2:] >= gap_high)) if i + 2 < n else False
            fvgs.append(FVG(gap_low, gap_high, "bearish", ts[i], i, filled))
    return fvgs[-15:]


# ---------------- liquidity sweeps ----------------


def find_liquidity_sweeps(df: pd.DataFrame, swings: list[Swing] | None = None,
                          *, window: int = 3, max_age: int = 30) -> list[Sweep]:
    """Detect false breakouts of recent swing highs/lows.

    A bullish sweep = bar low pierces a recent swing low, but close > swing low
    (i.e. wick took liquidity, body rejected). Mirror for bearish.
    """
    swings = swings if swings is not None else find_swings(df, window=window)
    if not swings or df is None or len(df) < 10:
        return []
    closes = df["close"].astype(float).to_numpy()
    highs = df["high"].astype(float).to_numpy()
    lows = df["low"].astype(float).to_numpy()
    ts = df.index
    n = len(df)
    sweeps: list[Sweep] = []
    start = max(0, n - max_age)
    for i in range(start, n):
        # check sweep of any swing that is older than i
        for s in swings:
            if s.idx >= i:
                continue
            if i - s.idx > max_age:
                continue
            if s.kind == "low" and lows[i] < s.price and closes[i] > s.price:
                sweeps.append(Sweep(ts[i], i, "bullish", float(s.price), float(closes[i])))
                break
            if s.kind == "high" and highs[i] > s.price and closes[i] < s.price:
                sweeps.append(Sweep(ts[i], i, "bearish", float(s.price), float(closes[i])))
                break
    return sweeps[-10:]


# ---------------- premium / discount ----------------


def premium_discount_zone(df: pd.DataFrame, lookback: int = 50) -> dict[str, Any]:
    """Split last ``lookback`` bars by Fib 0.5; report where current close sits."""
    if df is None or len(df) < 10:
        return {"zone": "unknown"}
    sub = df.tail(min(lookback, len(df)))
    high = float(sub["high"].max())
    low = float(sub["low"].min())
    mid = (high + low) / 2.0
    last = float(df["close"].iloc[-1])
    if last >= mid:
        zone = "premium"
        pct = (last - mid) / (high - mid) if high > mid else 0.0
    else:
        zone = "discount"
        pct = (mid - last) / (mid - low) if mid > low else 0.0
    return {
        "zone": zone,
        "depth_pct": round(float(pct) * 100, 2),
        "range_high": high,
        "range_low": low,
        "range_mid": mid,
    }


# ---------------- top-level summary ----------------


def summarize(df: pd.DataFrame, *, window: int = 3) -> dict[str, Any]:
    """Compute all SMC detectors and return a serialisable summary.

    The output schema is intentionally flat enough to be embedded in the
    recommendation JSON without losing information::

        {
          "structure": {"bias": "bullish"|"bearish"|"neutral",
                          "bos": "bullish"|None, "choch": ...},
          "order_blocks": [...],
          "fvg": [...],
          "sweeps": [...],
          "zone": {...},
          "summary": "bias=bullish; OB(bullish)x2; FVG(bullish unfilled)x1; sweep(bullish)",
        }
    """
    if df is None or df.empty:
        return {"ok": False, "error": "empty dataframe"}
    swings = find_swings(df, window=window)
    structure = detect_structure(df, swings=swings, window=window)
    obs = find_order_blocks(df)
    fvgs = find_fvg(df)
    sweeps = find_liquidity_sweeps(df, swings=swings)
    zone = premium_discount_zone(df)

    parts: list[str] = []
    parts.append(f"bias={structure.bias}")
    if structure.bos:
        parts.append(f"BOS={structure.bos}")
    if structure.choch:
        parts.append(f"CHoCH={structure.choch}")
    bullish_obs = [o for o in obs if o.kind == "bullish"]
    bearish_obs = [o for o in obs if o.kind == "bearish"]
    if bullish_obs:
        parts.append(f"OB_bullish={len(bullish_obs)}")
    if bearish_obs:
        parts.append(f"OB_bearish={len(bearish_obs)}")
    unfilled_b = [f for f in fvgs if f.kind == "bullish" and not f.filled]
    unfilled_s = [f for f in fvgs if f.kind == "bearish" and not f.filled]
    if unfilled_b:
        parts.append(f"FVG_bullish_open={len(unfilled_b)}")
    if unfilled_s:
        parts.append(f"FVG_bearish_open={len(unfilled_s)}")
    recent_sweeps = sweeps[-3:] if sweeps else []
    for sw in recent_sweeps:
        parts.append(f"sweep_{sw.kind}@{sw.swept_level:g}")
    parts.append(f"zone={zone.get('zone')}")

    def _enc_list(items: Iterable[Any]) -> list[dict[str, Any]]:
        return [
            {**asdict(it), "ts": str(getattr(it, "ts", ""))}
            for it in items
        ]

    return {
        "ok": True,
        "structure": {
            "bias": structure.bias,
            "bos": structure.bos,
            "choch": structure.choch,
            "last_bos_idx": structure.last_bos_idx,
            "last_choch_idx": structure.last_choch_idx,
            "swings": _enc_list(structure.last_swings),
        },
        "order_blocks": _enc_list(obs),
        "fvg": _enc_list(fvgs),
        "sweeps": _enc_list(sweeps),
        "zone": zone,
        "summary": "; ".join(parts),
    }


# ---------------- vote helpers consumed by signals.evaluate ----------------


def votes_from_summary(smc: dict[str, Any], last_close: float) -> list[tuple[str, int, str, float]]:
    """Convert SMC summary into ``(name, direction, reason, weight)`` tuples.

    Direction: +1 bullish, -1 bearish, 0 neutral.
    """
    if not smc or not smc.get("ok"):
        return []
    out: list[tuple[str, int, str, float]] = []
    struct = smc.get("structure") or {}
    bias = struct.get("bias")
    if bias == "bullish":
        out.append(("smc_bias", +1, "SMC market structure bullish (HH+HL).", 1.0))
    elif bias == "bearish":
        out.append(("smc_bias", -1, "SMC market structure bearish (LH+LL).", 1.0))
    if struct.get("bos") == "bullish":
        out.append(("smc_bos", +1, "BOS bullish — close break swing high.", 1.0))
    elif struct.get("bos") == "bearish":
        out.append(("smc_bos", -1, "BOS bearish — close break swing low.", 1.0))
    if struct.get("choch") == "bullish":
        out.append(("smc_choch", +1, "CHoCH bullish — regime flip to up.", 1.5))
    elif struct.get("choch") == "bearish":
        out.append(("smc_choch", -1, "CHoCH bearish — regime flip to down.", 1.5))

    # order block retest
    obs = smc.get("order_blocks") or []
    for ob in obs[-3:]:
        if ob.get("kind") == "bullish" and ob["low"] <= last_close <= ob["high"]:
            out.append(("smc_ob_retest", +1, "Price retest bullish order block.", 2.0))
            break
        if ob.get("kind") == "bearish" and ob["low"] <= last_close <= ob["high"]:
            out.append(("smc_ob_retest", -1, "Price retest bearish order block.", 2.0))
            break

    # unfilled FVG bias (price tends to fill)
    fvgs = smc.get("fvg") or []
    open_bull = [f for f in fvgs if f.get("kind") == "bullish" and not f.get("filled")]
    open_bear = [f for f in fvgs if f.get("kind") == "bearish" and not f.get("filled")]
    if open_bull and not open_bear:
        out.append(("smc_fvg", +1, f"{len(open_bull)} unfilled bullish FVG below.", 0.5))
    elif open_bear and not open_bull:
        out.append(("smc_fvg", -1, f"{len(open_bear)} unfilled bearish FVG above.", 0.5))

    # liquidity sweep on most recent bar
    sweeps = smc.get("sweeps") or []
    if sweeps:
        sw = sweeps[-1]
        if sw.get("kind") == "bullish":
            out.append(("smc_sweep", +1, f"Liquidity sweep @ {sw['swept_level']:g} rejected (bullish).", 2.0))
        elif sw.get("kind") == "bearish":
            out.append(("smc_sweep", -1, f"Liquidity sweep @ {sw['swept_level']:g} rejected (bearish).", 2.0))

    # premium/discount zone
    zone = smc.get("zone") or {}
    if zone.get("zone") == "discount" and zone.get("depth_pct", 0) > 50:
        out.append(("smc_zone", +1, "Price in deep discount zone (Fib).", 0.5))
    elif zone.get("zone") == "premium" and zone.get("depth_pct", 0) > 50:
        out.append(("smc_zone", -1, "Price in deep premium zone (Fib).", 0.5))
    return out
