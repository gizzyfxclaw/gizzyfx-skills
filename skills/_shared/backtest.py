"""Walk-forward backtest harness for the rule-based signal engine.

Design goals
------------
- **No lookahead bias**: at bar ``t`` we only use OHLCV up to and including
  bar ``t`` (closed bar). Entry simulates being placed on the open of bar
  ``t+1`` (or close of ``t``, configurable). SL/TP checks use intrabar high/low
  of subsequent bars.
- **Independent of feed**: takes a single OHLCV DataFrame (close-aligned),
  applies a user-supplied ``signal_fn`` that returns the same shape as
  ``signals.evaluate`` (verdict, entry_zone, stop_loss, take_profit).
- **Deterministic**: same inputs => same outputs. No randomness, no shuffle.
- **Lean output**: aggregated stats + per-trade list. No plotting (left to
  caller).

Trade lifecycle
~~~~~~~~~~~~~~~
1. Engine runs ``signal_fn(df_up_to_t)`` at every bar after ``warmup``.
2. If a verdict is BUY/LONG (bullish) or SELL/SHORT (bearish) AND no position
   is open, a virtual position opens at the *next* bar's open price.
3. While position is open, each subsequent bar is checked intrabar:
   - LONG: SL hit if ``low <= stop_loss``; TPs hit if ``high >= tp_i``.
   - SHORT: SL hit if ``high >= stop_loss``; TPs hit if ``low <= tp_i``.
4. Position closes when SL is hit, when the highest reached TP is hit, or
   when ``max_hold`` bars elapse (exit at that bar's close).
5. Result recorded as R-multiple of risk (return / |entry - SL|).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

import pandas as pd


SignalFn = Callable[[pd.DataFrame], dict[str, Any]]


@dataclass
class Trade:
    open_idx: int
    open_ts: str
    close_idx: int
    close_ts: str
    side: str             # "long" | "short"
    entry: float
    stop: float
    targets: list[float]
    exit_price: float
    exit_reason: str      # "sl" | "tp1" | "tp2" | "tp3" | "timeout"
    bars_held: int
    pnl_pct: float
    r_multiple: float     # gain / |entry - sl|
    verdict_at_open: str
    confidence: str
    score: float


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    bars_total: int
    bars_scanned: int
    trades: list[Trade] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "bars_total": self.bars_total,
            "bars_scanned": self.bars_scanned,
            "trades": [asdict(t) for t in self.trades],
            "metrics": self.metrics,
        }


# ---------------- helpers ----------------


def _is_bullish(verdict: str) -> bool:
    return verdict in {"BUY", "LONG"}


def _is_bearish(verdict: str) -> bool:
    return verdict in {"SELL", "SHORT"}


def _summarize(trades: list[Trade]) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "avg_r": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_r": 0.0,
            "total_r": 0.0,
            "expectancy_r": 0.0,
        }
    rs = [t.r_multiple for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    total = sum(rs)
    # equity curve for drawdown
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        max_dd = min(max_dd, eq - peak)
    pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else float("inf")
    by_reason: dict[str, int] = {}
    long_count = sum(1 for t in trades if t.side == "long")
    short_count = sum(1 for t in trades if t.side == "short")
    for t in trades:
        by_reason[t.exit_reason] = by_reason.get(t.exit_reason, 0) + 1
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(100.0 * len(wins) / len(trades), 2),
        "avg_r": round(total / len(trades), 3),
        "profit_factor": (round(pf, 3) if pf != float("inf") else None),
        "max_drawdown_r": round(max_dd, 3),
        "total_r": round(total, 3),
        "expectancy_r": round(total / len(trades), 3),
        "long_trades": long_count,
        "short_trades": short_count,
        "exit_breakdown": by_reason,
    }


# ---------------- main entry ----------------


def run_backtest(
    df: pd.DataFrame,
    signal_fn: SignalFn,
    *,
    symbol: str = "?",
    timeframe: str = "?",
    warmup: int = 250,
    max_hold: int = 20,
    entry_mode: str = "next_open",  # "next_open" | "close"
    cooldown: int = 1,
    verbose: bool = False,
) -> BacktestResult:
    """Walk forward through ``df``, calling ``signal_fn`` at every bar.

    ``signal_fn`` must accept a slice of the OHLCV df and return a dict
    matching ``signals.evaluate`` output: ``{recommendation, confidence,
    score, entry_zone, stop_loss, take_profit, ...}``.
    """
    if df is None or len(df) <= warmup + 2:
        return BacktestResult(symbol=symbol, timeframe=timeframe,
                              bars_total=0 if df is None else len(df),
                              bars_scanned=0)

    trades: list[Trade] = []
    in_position = False
    pos_side: str | None = None
    pos_entry = 0.0
    pos_stop = 0.0
    pos_targets: list[float] = []
    pos_open_idx = 0
    pos_verdict = ""
    pos_conf = ""
    pos_score = 0.0
    cooldown_until = 0

    opens = df["open"].astype(float).to_numpy()
    highs = df["high"].astype(float).to_numpy()
    lows = df["low"].astype(float).to_numpy()
    closes = df["close"].astype(float).to_numpy()
    ts = [str(t) for t in df.index]
    n = len(df)
    scanned = 0

    for t in range(warmup, n - 1):
        # -------- check exit on open position first --------
        if in_position:
            bar_high = highs[t]
            bar_low = lows[t]
            exit_price: float | None = None
            exit_reason: str | None = None
            if pos_side == "long":
                if bar_low <= pos_stop:
                    exit_price, exit_reason = pos_stop, "sl"
                else:
                    # check TPs from highest to lowest reached
                    for i, tp in enumerate(pos_targets):
                        if bar_high >= tp:
                            exit_price, exit_reason = tp, f"tp{i + 1}"
            else:  # short
                if bar_high >= pos_stop:
                    exit_price, exit_reason = pos_stop, "sl"
                else:
                    for i, tp in enumerate(pos_targets):
                        if bar_low <= tp:
                            exit_price, exit_reason = tp, f"tp{i + 1}"
            # timeout
            if exit_price is None and (t - pos_open_idx) >= max_hold:
                exit_price, exit_reason = float(closes[t]), "timeout"
            if exit_price is not None and exit_reason is not None:
                risk = abs(pos_entry - pos_stop) or 1e-9
                gain = (exit_price - pos_entry) if pos_side == "long" else (pos_entry - exit_price)
                r_mult = gain / risk
                pnl_pct = (gain / pos_entry) * 100
                trades.append(Trade(
                    open_idx=pos_open_idx, open_ts=ts[pos_open_idx],
                    close_idx=t, close_ts=ts[t],
                    side=pos_side or "?", entry=pos_entry,
                    stop=pos_stop, targets=list(pos_targets),
                    exit_price=float(exit_price), exit_reason=exit_reason,
                    bars_held=int(t - pos_open_idx),
                    pnl_pct=round(pnl_pct, 4), r_multiple=round(r_mult, 3),
                    verdict_at_open=pos_verdict, confidence=pos_conf,
                    score=pos_score,
                ))
                in_position = False
                cooldown_until = t + cooldown
                pos_side = None

        # -------- generate signal on bar t (using closed bar data) --------
        if in_position or t < cooldown_until:
            continue
        try:
            sig = signal_fn(df.iloc[:t + 1])
        except Exception:
            if verbose:
                import traceback; traceback.print_exc()
            continue
        scanned += 1
        if not sig or not isinstance(sig, dict):
            continue
        verdict = sig.get("recommendation")
        entry_zone = sig.get("entry_zone") or []
        sl = sig.get("stop_loss")
        tps = sig.get("take_profit") or []
        if not (_is_bullish(verdict) or _is_bearish(verdict)):
            continue
        if not entry_zone or sl is None or not tps:
            continue
        entry_mid = (float(entry_zone[0]) + float(entry_zone[1])) / 2 if len(entry_zone) >= 2 else float(entry_zone[0])
        if entry_mode == "close":
            fill_price = float(closes[t])
        else:
            if t + 1 >= n:
                continue
            fill_price = float(opens[t + 1])
        in_position = True
        pos_side = "long" if _is_bullish(verdict) else "short"
        pos_entry = float(fill_price)
        pos_stop = float(sl)
        pos_targets = [float(x) for x in tps]
        pos_open_idx = t + 1 if entry_mode == "next_open" else t
        pos_verdict = str(verdict)
        pos_conf = str(sig.get("confidence", "?"))
        pos_score = float(sig.get("score", 0.0))

    # close any open position at last close
    if in_position and pos_open_idx < n:
        last = n - 1
        exit_price = float(closes[last])
        risk = abs(pos_entry - pos_stop) or 1e-9
        gain = (exit_price - pos_entry) if pos_side == "long" else (pos_entry - exit_price)
        r_mult = gain / risk
        trades.append(Trade(
            open_idx=pos_open_idx, open_ts=ts[pos_open_idx],
            close_idx=last, close_ts=ts[last],
            side=pos_side or "?", entry=pos_entry,
            stop=pos_stop, targets=list(pos_targets),
            exit_price=exit_price, exit_reason="eod",
            bars_held=int(last - pos_open_idx),
            pnl_pct=round(gain / pos_entry * 100, 4),
            r_multiple=round(r_mult, 3),
            verdict_at_open=pos_verdict, confidence=pos_conf, score=pos_score,
        ))

    result = BacktestResult(symbol=symbol, timeframe=timeframe,
                            bars_total=n, bars_scanned=scanned,
                            trades=trades, metrics=_summarize(trades))
    return result
