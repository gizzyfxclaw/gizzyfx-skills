"""Sentiment scoring for news items.

Two layers:
1. Fast keyword-based scoring (default) — uses VADER + a small finance-specific
   keyword overlay (rally/surge/all-time-high → bullish; crash/plunge/lawsuit →
   bearish). Works offline, instant.
2. Optional LLM scoring via 9router — pass ``use_llm=True`` if you want a more
   nuanced score. Falls back to keyword scoring on any error.

All scores normalised to the range [-1.0, +1.0].
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterable

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
except Exception:  # pragma: no cover
    SentimentIntensityAnalyzer = None

import requests


BULLISH_KEYWORDS = {
    "surge", "rally", "soar", "jump", "spike", "breakout", "all-time-high", "ath",
    "bullish", "buy", "long", "upgrade", "beats", "outperform", "approve", "approved",
    "partnership", "acquisition", "launch", "release", "growth", "profit", "record",
    "naik", "menguat", "rebound", "untung", "laba", "ekspansi", "akuisisi",
}
BEARISH_KEYWORDS = {
    "crash", "plunge", "tumble", "slump", "drop", "fall", "decline", "selloff",
    "bearish", "sell", "short", "downgrade", "miss", "missed", "underperform",
    "ban", "banned", "lawsuit", "hack", "exploit", "rug", "delist", "delisted",
    "turun", "anjlok", "rugi", "ditolak", "ditangguhkan", "diretas",
}


def _keyword_score(text: str) -> float:
    """Cheap keyword overlay score in [-1, 1]."""
    lower = (text or "").lower()
    bull = sum(1 for w in BULLISH_KEYWORDS if w in lower)
    bear = sum(1 for w in BEARISH_KEYWORDS if w in lower)
    total = bull + bear
    if total == 0:
        return 0.0
    return (bull - bear) / total


def _vader_score(text: str) -> float:
    """VADER compound score normalised to [-1, 1]."""
    if SentimentIntensityAnalyzer is None or not text:
        return 0.0
    try:
        analyzer = SentimentIntensityAnalyzer()
        scores = analyzer.polarity_scores(text)
        return float(scores.get("compound", 0.0))
    except Exception:
        return 0.0


def score_text(text: str) -> float:
    """Combined keyword + VADER score (mean), clipped to [-1, 1]."""
    if not text:
        return 0.0
    kw = _keyword_score(text)
    vd = _vader_score(text)
    raw = (kw + vd) / 2.0
    return max(-1.0, min(1.0, raw))


def score_items(items: Iterable[dict[str, Any]], *, text_keys: Iterable[str] = ("title", "summary", "body", "text")) -> list[dict[str, Any]]:
    """Annotate each news item with a ``sentiment`` score and ``sentiment_label``."""
    annotated = []
    for it in items:
        text = " ".join(str(it.get(k) or "") for k in text_keys).strip()
        s = score_text(text)
        label = (
            "positive" if s >= 0.2
            else "negative" if s <= -0.2
            else "neutral"
        )
        new = dict(it)
        new["sentiment"] = round(s, 3)
        new["sentiment_label"] = label
        annotated.append(new)
    return annotated


def aggregate_score(items: Iterable[dict[str, Any]], *, weight_key: str = "weight") -> float:
    """Weighted average sentiment across many items.

    Each item should already have ``sentiment``; optional ``weight`` field
    (defaults to 1.0). Result clipped to [-1, 1].
    """
    items = list(items)
    if not items:
        return 0.0
    total_w = 0.0
    total = 0.0
    for it in items:
        s = float(it.get("sentiment", 0.0) or 0.0)
        w = float(it.get(weight_key, 1.0) or 1.0)
        total += s * w
        total_w += w
    if total_w == 0:
        return 0.0
    return max(-1.0, min(1.0, total / total_w))


# ---------- optional LLM scoring (slower, more nuanced) ----------

def score_text_via_llm(text: str, *, timeout: float = 15.0) -> float:
    """Score sentiment via 9router. Returns 0.0 on any failure."""
    base = os.environ.get("NINEROUTER_BASE_URL", "http://localhost:20128/v1")
    api = os.environ.get("NINEROUTER_API_KEY", "")
    model = os.environ.get("HERMES_MODEL", "jagrescombo")
    if not text or not api:
        return 0.0
    prompt = (
        "Klasifikasi sentimen news/text di bawah ini terhadap aset finansial yang dibahas. "
        "Output HANYA satu angka float di range -1.0 (sangat bearish) sampai +1.0 (sangat bullish), "
        "tanpa explanation. Contoh output: -0.7 atau 0.3.\n\nText:\n"
        + text[:1500]
    )
    try:
        resp = requests.post(
            base.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {api}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "max_tokens": 12,
                "stream": False,
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            return 0.0
        # SSE fallback (same logic as llm_summary.py).
        ct = (resp.headers.get("content-type") or "").lower()
        if "text/event-stream" in ct or resp.text.lstrip().startswith("data:"):
            chunks: list[str] = []
            for raw in resp.text.splitlines():
                line = raw.strip()
                if not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if not body or body == "[DONE]":
                    continue
                try:
                    obj = json.loads(body)
                    piece = obj.get("choices", [{}])[0].get("delta", {}).get("content")
                    if piece:
                        chunks.append(piece)
                except Exception:
                    continue
            txt = "".join(chunks).strip()
        else:
            data = resp.json()
            txt = (data["choices"][0]["message"]["content"] or "").strip()
        try:
            val = float(txt.split()[0])
            return max(-1.0, min(1.0, val))
        except (ValueError, IndexError):
            return 0.0
    except Exception:
        return 0.0
