"""Lightweight candlestick pattern detector for the last bar of an OHLC frame.

Pure pandas/numpy — no TA-Lib dependency. Returns a list of dicts:

    [{"kind": "engulfing", "bias": "bullish", "strength": 0.8}, ...]

Patterns covered (last bar + previous bar):
    - doji (neutral)
    - hammer / hanging_man
    - shooting_star / inverted_hammer
    - bullish_engulfing / bearish_engulfing
    - bullish_marubozu / bearish_marubozu
    - three_white_soldiers / three_black_crows (last 3 bars)

Strength is a 0..1 confidence heuristic based on body/range ratios.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def _bar(df: pd.DataFrame, i: int) -> dict[str, float]:
    row = df.iloc[i]
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    rng = max(h - l, 1e-9)
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    return {
        "o": o, "h": h, "l": l, "c": c,
        "range": rng, "body": body, "upper": upper, "lower": lower,
        "is_bull": c > o, "is_bear": c < o,
    }


def detect(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Detect candlestick patterns on the last bar(s) of ``df``.

    ``df`` must have columns: open, high, low, close (case-insensitive).
    """
    if df is None or len(df) < 2:
        return []
    norm = df.rename(columns={c: c.lower() for c in df.columns})
    if not {"open", "high", "low", "close"}.issubset(norm.columns):
        return []
    n = len(norm)
    cur = _bar(norm, n - 1)
    prev = _bar(norm, n - 2)
    found: list[dict[str, Any]] = []

    # Doji — body is tiny vs range.
    if cur["body"] / cur["range"] < 0.1:
        found.append({"kind": "doji", "bias": "neutral", "strength": 0.4})

    # Hammer (bullish reversal at bottom) / hanging man (bearish at top).
    # Long lower shadow, small upper shadow, small body, lower shadow >= 2x body.
    if (cur["lower"] >= 2 * cur["body"]
            and cur["upper"] <= cur["body"]
            and cur["body"] / cur["range"] < 0.4):
        # Bias depends on prior trend: use prev bar direction & a 5-bar drift.
        drift = norm["close"].iloc[-1] - norm["close"].iloc[-min(5, n)]
        if drift < 0:
            found.append({"kind": "hammer", "bias": "bullish", "strength": 0.7})
        else:
            found.append({"kind": "hanging_man", "bias": "bearish", "strength": 0.6})

    # Shooting star / inverted hammer.
    if (cur["upper"] >= 2 * cur["body"]
            and cur["lower"] <= cur["body"]
            and cur["body"] / cur["range"] < 0.4):
        drift = norm["close"].iloc[-1] - norm["close"].iloc[-min(5, n)]
        if drift > 0:
            found.append({"kind": "shooting_star", "bias": "bearish", "strength": 0.7})
        else:
            found.append({"kind": "inverted_hammer", "bias": "bullish", "strength": 0.5})

    # Engulfing — current body fully covers previous body and opposite color.
    if cur["is_bull"] and prev["is_bear"] and cur["c"] >= prev["o"] and cur["o"] <= prev["c"]:
        strength = min(1.0, cur["body"] / max(prev["body"], 1e-9) / 2.0)
        found.append({"kind": "bullish_engulfing", "bias": "bullish", "strength": round(strength, 2)})
    if cur["is_bear"] and prev["is_bull"] and cur["o"] >= prev["c"] and cur["c"] <= prev["o"]:
        strength = min(1.0, cur["body"] / max(prev["body"], 1e-9) / 2.0)
        found.append({"kind": "bearish_engulfing", "bias": "bearish", "strength": round(strength, 2)})

    # Marubozu — body fills nearly all range.
    if cur["body"] / cur["range"] >= 0.92:
        if cur["is_bull"]:
            found.append({"kind": "bullish_marubozu", "bias": "bullish", "strength": 0.7})
        else:
            found.append({"kind": "bearish_marubozu", "bias": "bearish", "strength": 0.7})

    # Three soldiers / crows (need 3 bars).
    if n >= 3:
        b1 = _bar(norm, n - 3)
        b2 = prev
        b3 = cur
        if b1["is_bull"] and b2["is_bull"] and b3["is_bull"] and b3["c"] > b2["c"] > b1["c"]:
            found.append({"kind": "three_white_soldiers", "bias": "bullish", "strength": 0.8})
        if b1["is_bear"] and b2["is_bear"] and b3["is_bear"] and b3["c"] < b2["c"] < b1["c"]:
            found.append({"kind": "three_black_crows", "bias": "bearish", "strength": 0.8})

    return found
