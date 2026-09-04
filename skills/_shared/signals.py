"""Trading-signal recommendation engine.

Consumes a :class:`~skills._shared.ta.TASnapshot` (and optional add-ons like
candlestick patterns, sentiment, macro context) and produces a structured
recommendation dict:

    {
        "recommendation": "BUY" | "SELL" | "LONG" | "SHORT" | "HOLD" | "WAIT",
        "confidence": "high" | "medium" | "low",
        "score": 4,          # net bullish - bearish indicator count
        "entry_zone": [low, high],
        "stop_loss": <float>,
        "take_profit": [tp1, tp2, tp3],
        "risk_reward": [rr1, rr2, rr3],
        "reasoning": [...],
        "warnings": [...],
    }

The engine is intentionally rule-based (no ML / no overfitting). Each rule
contributes a vote (+1 bullish, -1 bearish, 0 neutral) plus a short reason
string. Final verdict combines vote count and a *risk profile* gate
(conservative requires ``score>=4`` and ``RR>=2.0``).

Per asset-class differences (saham vs crypto vs forex) live in their own
``recommend.py`` modules — they add extra rules on top of this base engine
(fundamental overlay for saham, funding rate for crypto, DXY/calendar for
forex).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from .ta import TASnapshot, fibonacci_levels


RiskProfile = Literal["conservative", "balanced", "aggressive"]


@dataclass
class Vote:
    """A single rule's vote with a human-readable reason."""

    name: str
    direction: int  # +1 bullish, -1 bearish, 0 neutral / informational
    reason: str
    weight: float = 1.0


@dataclass
class SignalContext:
    """Optional context that recommendation rules may consume.

    None values mean "not available" — rules must tolerate that gracefully.
    """

    fundamentals: dict[str, Any] | None = None
    patterns: list[dict[str, Any]] = field(default_factory=list)
    sentiment_score: float | None = None  # -1..+1
    macro: dict[str, Any] | None = None
    calendar_events: list[dict[str, Any]] = field(default_factory=list)
    funding_rate: float | None = None  # crypto only (perp funding %)
    fear_greed: int | None = None  # crypto only (0-100)
    mtf: dict[str, TASnapshot] | None = None  # higher TF snapshots if any
    asset_kind: str | None = None  # 'crypto' / 'saham' / 'forex' / 'commodity'
    smc: dict[str, Any] | None = None  # output of skills._shared.smc.summarize()


# ---------- core rules (asset-agnostic) ----------

def _rule_rsi(ta: TASnapshot) -> Vote | None:
    if ta.rsi_14 is None:
        return None
    r = ta.rsi_14
    if r <= 30:
        return Vote("RSI_OVERSOLD", +1, f"RSI(14) {r:.1f} oversold (≤30) — biasanya rebound.")
    if r >= 70:
        return Vote("RSI_OVERBOUGHT", -1, f"RSI(14) {r:.1f} overbought (≥70) — risk koreksi.")
    if r < 45:
        return Vote("RSI_WEAK", -1, f"RSI(14) {r:.1f} di zona lemah (<45).", weight=0.5)
    if r > 55:
        return Vote("RSI_STRONG", +1, f"RSI(14) {r:.1f} di zona kuat (>55).", weight=0.5)
    return Vote("RSI_NEUTRAL", 0, f"RSI(14) {r:.1f} netral.")


def _rule_macd(ta: TASnapshot) -> Vote | None:
    if ta.macd is None or ta.macd_signal is None:
        return None
    cross = ta.macd > ta.macd_signal
    zero = (ta.macd_state or "")
    if cross and "above" in zero:
        return Vote("MACD_BULL_ABOVE0", +1, "MACD di atas signal line dan above zero (momentum bullish).")
    if not cross and "below" in zero:
        return Vote("MACD_BEAR_BELOW0", -1, "MACD di bawah signal line dan below zero (momentum bearish).")
    if cross:
        return Vote("MACD_BULL_CROSS", +1, "MACD cross di atas signal line (momentum membaik).", weight=0.7)
    return Vote("MACD_BEAR_CROSS", -1, "MACD cross di bawah signal line (momentum melemah).", weight=0.7)


def _rule_trend_ema(ta: TASnapshot) -> Vote | None:
    state = ta.trend_state or ""
    if "uptrend-strong" in state:
        return Vote("TREND_UP_STRONG", +1, "Harga di atas EMA20>EMA50>EMA200 (uptrend kuat).")
    if "uptrend" in state:
        return Vote("TREND_UP", +1, "Tren naik (di atas EMA20).", weight=0.7)
    if "downtrend-strong" in state:
        return Vote("TREND_DOWN_STRONG", -1, "Harga di bawah EMA20<EMA50<EMA200 (downtrend kuat).")
    if "downtrend" in state:
        return Vote("TREND_DOWN", -1, "Tren turun (di bawah EMA20).", weight=0.7)
    return Vote("TREND_SIDEWAYS", 0, "Harga sideways di sekitar EMA20.")


def _rule_bbands(ta: TASnapshot) -> Vote | None:
    if ta.bb_pct is None:
        return None
    p = ta.bb_pct
    if p <= 0.05:
        return Vote("BB_OVERSOLD", +1, f"Harga menyentuh BB lower (BB%={p:.2f}) — potensi bounce.")
    if p >= 0.95:
        return Vote("BB_OVERBOUGHT", -1, f"Harga menyentuh BB upper (BB%={p:.2f}) — potensi reject.")
    if p < 0.2:
        return Vote("BB_LOW", +1, f"BB% {p:.2f} dekat lower band.", weight=0.4)
    if p > 0.8:
        return Vote("BB_HIGH", -1, f"BB% {p:.2f} dekat upper band.", weight=0.4)
    return None


def _rule_stoch(ta: TASnapshot) -> Vote | None:
    k, d = ta.stoch_k, ta.stoch_d
    if k is None or d is None:
        return None
    if k < 20 and d < 20:
        if k > d:
            return Vote("STOCH_BULL_REVERSAL", +1, f"Stochastic %K {k:.0f} cross %D {d:.0f} di zona oversold.", weight=0.7)
        return Vote("STOCH_OVERSOLD", +1, f"Stochastic di zona oversold (%K={k:.0f}).", weight=0.4)
    if k > 80 and d > 80:
        if k < d:
            return Vote("STOCH_BEAR_REVERSAL", -1, f"Stochastic %K {k:.0f} cross %D {d:.0f} di zona overbought.", weight=0.7)
        return Vote("STOCH_OVERBOUGHT", -1, f"Stochastic di zona overbought (%K={k:.0f}).", weight=0.4)
    return None


def _rule_volume(ta: TASnapshot) -> Vote | None:
    z = ta.volume_z
    if z is None:
        return None
    if z >= 2.0:
        # Strong volume — bullish if trend up, bearish if trend down.
        if (ta.trend_state or "").startswith("uptrend"):
            return Vote("VOL_SPIKE_BULL", +1, f"Volume spike (z={z:.1f}) konfirmasi uptrend.", weight=0.5)
        if (ta.trend_state or "").startswith("downtrend"):
            return Vote("VOL_SPIKE_BEAR", -1, f"Volume spike (z={z:.1f}) konfirmasi downtrend.", weight=0.5)
    if z <= -1.5:
        return Vote("VOL_DRY", 0, f"Volume kering (z={z:.1f}) — seller/buyer exhausted, tunggu konfirmasi.")
    return None


def _rule_patterns(ctx: SignalContext) -> list[Vote]:
    """Each detected candlestick pattern contributes a vote."""
    votes: list[Vote] = []
    for p in ctx.patterns:
        kind = p.get("kind", "")
        bias = p.get("bias", "neutral")  # bullish / bearish / neutral
        strength = float(p.get("strength", 0.5))
        d = +1 if bias == "bullish" else -1 if bias == "bearish" else 0
        if d == 0:
            continue
        votes.append(Vote(
            f"PATTERN_{kind.upper()}",
            d,
            f"Candlestick pattern '{kind}' ({bias}) terdeteksi di bar terakhir.",
            weight=strength,
        ))
    return votes


def _rule_sentiment(ctx: SignalContext) -> Vote | None:
    s = ctx.sentiment_score
    if s is None:
        return None
    if s >= 0.4:
        return Vote("NEWS_BULLISH", +1, f"News sentiment positif ({s:+.2f}).", weight=0.6)
    if s <= -0.4:
        return Vote("NEWS_BEARISH", -1, f"News sentiment negatif ({s:+.2f}).", weight=0.6)
    return Vote("NEWS_NEUTRAL", 0, f"News sentiment netral ({s:+.2f}).")


def _rule_smc(ctx: SignalContext, ta: TASnapshot) -> list[Vote]:
    """Inject SMC layer votes if ``ctx.smc`` is populated (see _shared.smc)."""
    if not ctx.smc:
        return []
    try:
        from . import smc as smc_mod
    except Exception:
        return []
    last = ta.last_close or 0.0
    tuples = smc_mod.votes_from_summary(ctx.smc, last)
    return [Vote(name, d, reason, weight) for (name, d, reason, weight) in tuples]


def _rule_mtf_alignment(ta: TASnapshot, ctx: SignalContext) -> Vote | None:
    """Higher-TF alignment: if 1d trend up and current TF also up → bonus vote."""
    if not ctx.mtf:
        return None
    bullish_tfs = sum(
        1 for s in ctx.mtf.values()
        if s.trend_state and "uptrend" in s.trend_state
    )
    bearish_tfs = sum(
        1 for s in ctx.mtf.values()
        if s.trend_state and "downtrend" in s.trend_state
    )
    if bullish_tfs >= 2 and (ta.trend_state or "").startswith("uptrend"):
        return Vote("MTF_BULL_ALIGN", +1, f"Multi-TF aligned bullish ({bullish_tfs} higher TF up).", weight=1.0)
    if bearish_tfs >= 2 and (ta.trend_state or "").startswith("downtrend"):
        return Vote("MTF_BEAR_ALIGN", -1, f"Multi-TF aligned bearish ({bearish_tfs} higher TF down).", weight=1.0)
    if bullish_tfs >= 1 and bearish_tfs >= 1:
        return Vote("MTF_CONFLICT", 0, "Multi-TF konflik — higher TF dan current TF berbeda arah, hati-hati.")
    return None


CORE_RULES = (
    _rule_rsi,
    _rule_macd,
    _rule_trend_ema,
    _rule_bbands,
    _rule_stoch,
    _rule_volume,
)


# ---------- entry / stop / target computation ----------

def _entry_zone(ta: TASnapshot, direction: int) -> list[float] | None:
    """Compute a small entry zone around current price using EMA20 and pivot."""
    last = ta.last_close
    if last is None:
        return None
    refs = [r for r in (ta.ema_20, ta.pivot) if r is not None]
    if not refs:
        return [round(last * 0.995, 6), round(last, 6)] if direction > 0 else [round(last, 6), round(last * 1.005, 6)]
    if direction > 0:  # BUY/LONG → entry slightly below current or at EMA20 pullback
        lo = min(refs + [last]) * 0.995
        hi = last
    elif direction < 0:  # SELL/SHORT
        lo = last
        hi = max(refs + [last]) * 1.005
    else:
        return None
    return [round(lo, 6), round(hi, 6)]


def _stop_loss(ta: TASnapshot, direction: int) -> float | None:
    last = ta.last_close
    atr = ta.atr_14
    if last is None or atr is None:
        return None
    if direction > 0:
        # SL below 1.5 * ATR or below S1, whichever is closer to price (tighter)
        candidates = [last - 1.5 * atr]
        if ta.s1 is not None:
            candidates.append(ta.s1)
        if ta.ema_50 is not None and ta.ema_50 < last:
            candidates.append(ta.ema_50 * 0.995)
        sl = max([c for c in candidates if c < last], default=last - 1.5 * atr)
        return round(sl, 6)
    if direction < 0:
        candidates = [last + 1.5 * atr]
        if ta.r1 is not None:
            candidates.append(ta.r1)
        if ta.ema_50 is not None and ta.ema_50 > last:
            candidates.append(ta.ema_50 * 1.005)
        sl = min([c for c in candidates if c > last], default=last + 1.5 * atr)
        return round(sl, 6)
    return None


def _take_profits(ta: TASnapshot, direction: int, entry: float, sl: float) -> list[float] | None:
    """Three TP levels at RR multiples of 2.0 / 3.5 / 5.0."""
    if entry is None or sl is None:
        return None
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    if direction > 0:
        return [round(entry + risk * m, 6) for m in (2.0, 3.5, 5.0)]
    if direction < 0:
        return [round(entry - risk * m, 6) for m in (2.0, 3.5, 5.0)]
    return None


# ---------- main entry point ----------

def evaluate(
    ta: TASnapshot,
    *,
    ctx: SignalContext | None = None,
    risk_profile: RiskProfile = "balanced",
    is_long_only: bool = False,
    long_label: str = "BUY",
    short_label: str = "SELL",
) -> dict[str, Any]:
    """Run all rules over ``ta`` and produce a recommendation dict.

    ``is_long_only`` — set True for cash markets (saham IDN cash). When the
    aggregate score is negative we still return HOLD/WAIT instead of a SELL/
    SHORT signal.

    ``long_label`` / ``short_label`` — let callers customise verbs (e.g. crypto
    uses LONG/SHORT, saham uses BUY/SELL).
    """
    ctx = ctx or SignalContext()

    votes: list[Vote] = []
    for rule in CORE_RULES:
        v = rule(ta)
        if v is not None:
            votes.append(v)
    votes.extend(_rule_patterns(ctx))
    s_vote = _rule_sentiment(ctx)
    if s_vote is not None:
        votes.append(s_vote)
    votes.extend(_rule_smc(ctx, ta))
    mtf_vote = _rule_mtf_alignment(ta, ctx)
    if mtf_vote is not None:
        votes.append(mtf_vote)

    score = sum(v.direction * v.weight for v in votes)
    bull_count = sum(1 for v in votes if v.direction > 0)
    bear_count = sum(1 for v in votes if v.direction < 0)

    # Direction: sign of score.
    direction = 0
    if score >= 1.0:
        direction = +1
    elif score <= -1.0:
        direction = -1
    if is_long_only and direction < 0:
        direction = 0

    # Confidence thresholds.
    abs_score = abs(score)
    if abs_score >= 4.0:
        confidence = "high"
    elif abs_score >= 2.5:
        confidence = "medium"
    else:
        confidence = "low"

    # Compute entry/SL/TP only if we have a directional bias.
    entry = None
    sl = None
    tps: list[float] | None = None
    rr: list[float] | None = None
    if direction != 0:
        entry_zone = _entry_zone(ta, direction)
        if entry_zone is not None:
            entry = (entry_zone[0] + entry_zone[1]) / 2.0
            sl = _stop_loss(ta, direction)
            if sl is not None:
                tps = _take_profits(ta, direction, entry, sl)
                if tps is not None:
                    risk = abs(entry - sl)
                    rr = [round(abs(tp - entry) / risk, 2) for tp in tps] if risk else None
        entry_zone_field = entry_zone
    else:
        entry_zone_field = None

    # Risk-profile gate.
    min_score, min_rr1 = {
        "conservative": (4.0, 2.0),
        "balanced": (2.5, 1.5),
        "aggressive": (1.0, 1.0),
    }[risk_profile]

    verdict: str
    if direction == 0:
        verdict = "HOLD" if is_long_only else "WAIT"
    elif abs_score < min_score or (rr and rr[0] < min_rr1):
        # Setup doesn't meet the configured risk gate → demote to WAIT/HOLD.
        verdict = "HOLD" if is_long_only else "WAIT"
        direction = 0
        entry = sl = tps = rr = None
        entry_zone_field = None
    elif direction > 0:
        verdict = long_label
    else:
        verdict = short_label

    # Compile warnings from calendar / macro context.
    warnings: list[str] = []
    for ev in ctx.calendar_events or []:
        when = ev.get("when") or ev.get("time") or "soon"
        title = ev.get("title") or ev.get("event") or "event"
        impact = ev.get("impact") or "med"
        if impact in ("high", "High"):
            warnings.append(f"Event '{title}' ({impact}) @ {when} — volatile, sizing kecil.")
    if ctx.funding_rate is not None and abs(ctx.funding_rate) >= 0.05:
        side = "overcrowded longs" if ctx.funding_rate > 0 else "overcrowded shorts"
        warnings.append(f"Funding rate {ctx.funding_rate:+.3f}% — {side}, hati-hati squeeze.")
    if ctx.fear_greed is not None:
        if ctx.fear_greed >= 80:
            warnings.append(f"Fear & Greed {ctx.fear_greed} (Extreme Greed) — sentiment terlalu euforia.")
        elif ctx.fear_greed <= 20:
            warnings.append(f"Fear & Greed {ctx.fear_greed} (Extreme Fear) — bisa jadi capitulation.")

    fibs = None
    if ta.last_close is not None and ta.series_close:
        hi = max(ta.series_close)
        lo = min(ta.series_close)
        fibs = fibonacci_levels(hi, lo)

    levels = _key_levels(ta, ctx)
    triggers = _entry_triggers(ta, ctx, levels=levels, is_long_only=is_long_only,
                                long_label=long_label, short_label=short_label)

    return {
        "recommendation": verdict,
        "confidence": confidence,
        "score": round(score, 2),
        "bull_count": bull_count,
        "bear_count": bear_count,
        "entry_zone": entry_zone_field,
        "stop_loss": sl,
        "take_profit": tps,
        "risk_reward": rr,
        "reasoning": [v.reason for v in votes if v.direction != 0],
        "neutral_notes": [v.reason for v in votes if v.direction == 0],
        "warnings": warnings,
        "fib_levels": fibs,
        "levels": levels,
        "triggers": triggers,
        "risk_profile": risk_profile,
    }


def _key_levels(ta: "TASnapshot", ctx: SignalContext) -> dict[str, list[dict[str, Any]]]:
    """Pick up to 3 resistance + 3 support levels from pivot, EMA, BB, SMC."""
    last = ta.last_close
    res: list[dict[str, Any]] = []
    sup: list[dict[str, Any]] = []

    def _add(bucket: list[dict[str, Any]], level: float | None, label: str) -> None:
        if level is None or last is None:
            return
        try:
            f = float(level)
        except Exception:
            return
        if any(abs(x["level"] - f) / max(abs(last), 1e-9) < 0.001 for x in bucket):
            return  # dedupe ~0.1% neighbours
        bucket.append({"level": round(f, 4), "label": label})

    if last is not None:
        for lv, lbl in (
            (ta.r2, "pivot R2"),
            (ta.r1, "pivot R1"),
            (ta.bb_upper, "BB upper"),
            (ta.ema_20, "EMA20"),
            (ta.ema_50, "EMA50"),
            (ta.ema_200, "EMA200"),
        ):
            if lv is not None and lv > last:
                _add(res, lv, lbl)
        for lv, lbl in (
            (ta.s2, "pivot S2"),
            (ta.s1, "pivot S1"),
            (ta.bb_lower, "BB lower"),
            (ta.ema_20, "EMA20"),
            (ta.ema_50, "EMA50"),
            (ta.ema_200, "EMA200"),
        ):
            if lv is not None and lv < last:
                _add(sup, lv, lbl)

    # SMC order-block midpoints (closest unmitigated zones).
    smc = ctx.smc or {}
    for ob in (smc.get("order_blocks") or [])[:6]:
        try:
            top = float(ob.get("top"))
            bot = float(ob.get("bottom"))
        except Exception:
            continue
        mid = (top + bot) / 2.0
        side = (ob.get("side") or ob.get("kind") or "").lower()
        if last is None:
            continue
        if mid > last:
            _add(res, mid, f"OB {side or 'zone'}")
        elif mid < last:
            _add(sup, mid, f"OB {side or 'zone'}")

    res.sort(key=lambda x: x["level"])
    sup.sort(key=lambda x: -x["level"])
    return {"resistance": res[:3], "support": sup[:3]}


def _entry_triggers(
    ta: "TASnapshot",
    ctx: SignalContext,
    *,
    levels: dict[str, list[dict[str, Any]]],
    is_long_only: bool,
    long_label: str,
    short_label: str,
) -> dict[str, str | None]:
    """Build human-readable IF-THEN trigger lines.

    Always emits both legs when available; the format card decides which to
    show. Conditions reference concrete price levels (nearest resistance for
    LONG breakout, nearest support for SHORT break) plus a confirmation cue
    (RSI exit zone, MACD flip, volume spike).
    """
    last = ta.last_close
    res = (levels.get("resistance") or [])
    sup = (levels.get("support") or [])
    nearest_r = res[0] if res else None
    nearest_s = sup[0] if sup else None
    rsi = ta.rsi_14

    long_parts: list[str] = []
    if nearest_r is not None and last is not None:
        long_parts.append(f"close > `{nearest_r['level']}` ({nearest_r['label']})")
    elif ta.ema_20 is not None and last is not None and ta.ema_20 > last:
        long_parts.append(f"close > `{round(ta.ema_20, 4)}` (EMA20)")
    if rsi is not None and rsi < 45:
        long_parts.append("RSI keluar dari oversold (> 45)")
    if ta.macd_state and ("bear" in ta.macd_state or "below" in ta.macd_state):
        long_parts.append("MACD cross up / hist flip positif")
    if ta.volume_z is not None and ta.volume_z < 1.5:
        long_parts.append("volume confirm spike (z > 1.5)")
    long_when = " AND ".join(long_parts) if long_parts else None

    short_parts: list[str] = []
    if is_long_only:
        return {"long_when": long_when, "short_when": None}
    if nearest_s is not None and last is not None:
        short_parts.append(f"close < `{nearest_s['level']}` ({nearest_s['label']})")
    elif ta.ema_20 is not None and last is not None and ta.ema_20 < last:
        short_parts.append(f"close < `{round(ta.ema_20, 4)}` (EMA20)")
    if rsi is not None and rsi > 55:
        short_parts.append("RSI keluar dari overbought (< 55)")
    if ta.macd_state and ("bull" in ta.macd_state or "above" in ta.macd_state):
        short_parts.append("MACD cross down / hist flip negatif")
    if ta.volume_z is not None and ta.volume_z < 1.5:
        short_parts.append("volume confirm spike (z > 1.5)")
    short_when = " AND ".join(short_parts) if short_parts else None

    return {"long_when": long_when, "short_when": short_when}


def summarize_recommendation(rec: dict[str, Any], *, symbol: str, timeframe: str) -> str:
    """One-line human-readable summary for log/Telegram preview."""
    v = rec.get("recommendation", "?")
    c = rec.get("confidence", "?")
    s = rec.get("score", 0)
    parts = [f"{symbol} {timeframe}: {v} ({c}, score={s:+.1f})"]
    rr = rec.get("risk_reward")
    if rec.get("entry_zone") and rec.get("stop_loss") and rec.get("take_profit"):
        ez = rec["entry_zone"]
        sl = rec["stop_loss"]
        tps = rec["take_profit"]
        parts.append(f"entry {ez[0]}-{ez[1]} SL {sl} TP {'/'.join(str(t) for t in tps)}")
        if rr:
            parts.append(f"RR {'/'.join(str(r) for r in rr)}")
    return " | ".join(parts)


_VERDICT_EMOJI = {
    "LONG": "🟢", "BUY": "🟢",
    "SHORT": "🔴", "SELL": "🔴",
    "HOLD": "🟡", "WAIT": "⚪",
}


def _fmt_num(x: Any, decimals: int = 2) -> str:
    """Format a number with thousand separators; passthrough on non-numbers."""
    try:
        f = float(x)
    except Exception:
        return str(x) if x is not None else "—"
    if abs(f) >= 1000:
        return f"{f:,.{decimals}f}"
    if abs(f) >= 1:
        return f"{f:.{decimals}f}"
    return f"{f:.{max(decimals, 4)}f}"


def format_telegram_card(
    rec: dict[str, Any],
    *,
    symbol: str,
    timeframe: str,
    asset_kind: str = "crypto",
    price_now: float | None = None,
    extra_lines: list[str] | None = None,
) -> str:
    """Render a concise Telegram-ready trade-decision card.

    Intentionally terse so Hermes will likely relay it verbatim instead of
    re-narrating into a multi-section essay. Sections always in this order:
        1. Header: verdict emoji + symbol + timeframe + verdict (+ confidence)
        2. Score + price now
        3. Trade plan: entry zone / SL / TP1-3 / RR1-3 (only when verdict is
           directional and these fields are non-empty)
        4. Suggested leverage (crypto only, if present)
        5. Up to 5 reasoning bullets (TA + SMC + macro)
        6. Up to 3 warnings (calendar, sentiment extremes, etc.)
        7. Footer: NFA disclaimer.
    """
    v = (rec.get("recommendation") or "?").upper()
    c = (rec.get("confidence") or "?").lower()
    s = rec.get("score", 0) or 0
    emoji = _VERDICT_EMOJI.get(v, "⚪")

    lines: list[str] = []
    lines.append(f"{emoji} *{symbol} {timeframe}* — *{v}* ({c}, score {s:+.1f})")

    sub: list[str] = []
    if price_now is not None:
        sub.append(f"price `{_fmt_num(price_now)}`")
    bull = rec.get("bull_count")
    bear = rec.get("bear_count")
    if bull is not None and bear is not None:
        sub.append(f"votes {bull}↑ / {bear}↓")
    if sub:
        lines.append(" · ".join(sub))

    ez = rec.get("entry_zone")
    sl = rec.get("stop_loss")
    tps = rec.get("take_profit") or []
    rrs = rec.get("risk_reward") or []
    if v in ("LONG", "SHORT", "BUY", "SELL") and ez and sl and tps:
        lines.append("")
        lines.append("*Plan:*")
        lines.append(f"• Entry: `{_fmt_num(ez[0])} – {_fmt_num(ez[1])}`")
        lines.append(f"• Stop: `{_fmt_num(sl)}`")
        for i, tp in enumerate(tps, start=1):
            rr = rrs[i - 1] if i - 1 < len(rrs) else None
            rr_str = f" (RR {rr})" if rr is not None else ""
            lines.append(f"• TP{i}: `{_fmt_num(tp)}`{rr_str}")
        lev = rec.get("suggested_leverage_x")
        if lev:
            lines.append(f"• Suggested leverage: `{lev}x`")
    else:
        lines.append("")
        lines.append("*Plan:* belum ada setup high-conviction — _gate not satisfied_.")

    # Key levels (top 2 each side, single line per side for terseness).
    lv = rec.get("levels") or {}
    res_lv = (lv.get("resistance") or [])[:2]
    sup_lv = (lv.get("support") or [])[:2]
    if res_lv or sup_lv:
        lines.append("")
        if res_lv:
            res_str = " / ".join(f"`{_fmt_num(x['level'])}` ({x['label']})" for x in res_lv)
            lines.append(f"R: {res_str}")
        if sup_lv:
            sup_str = " / ".join(f"`{_fmt_num(x['level'])}` ({x['label']})" for x in sup_lv)
            lines.append(f"S: {sup_str}")

    # Entry triggers — explicit LONG/SHORT timing IF-THEN.
    tr = rec.get("triggers") or {}
    long_when = tr.get("long_when")
    short_when = tr.get("short_when")
    if long_when or short_when:
        lines.append("")
        lines.append("*Kapan entry:*")
        if long_when:
            tag = "🟢 BUY" if asset_kind == "saham_idn" else "🟢 LONG"
            lines.append(f"• {tag} kalau: {long_when}")
        if short_when and asset_kind != "saham_idn":
            lines.append(f"• 🔴 SHORT kalau: {short_when}")

    reasoning = (rec.get("reasoning") or [])[:3]
    if reasoning:
        lines.append("")
        lines.append("*Alasan:*")
        for r in reasoning:
            lines.append(f"• {r}")

    # Skip warnings when verdict is WAIT/HOLD (gate-not-satisfied line already
    # implies caution); show top 2 only when we're actually firing a trade.
    if v in ("LONG", "SHORT", "BUY", "SELL"):
        warnings = (rec.get("warnings") or [])[:2]
        if warnings:
            lines.append("")
            lines.append("*⚠*")
            for w in warnings:
                lines.append(f"• {w}")

    if extra_lines:
        lines.append("")
        for x in extra_lines:
            lines.append(x)

    lines.append("")
    lines.append("_NFA — bukan saran keuangan. Risiko ditanggung sendiri._")
    return "\n".join(lines)
