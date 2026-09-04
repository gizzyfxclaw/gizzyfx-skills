"""Unified news aggregation across RSS feeds + Telegram channels.

Each skill (crypto / saham / forex) provides its own list of RSS URLs; this
module adds:
- Sentiment scoring (via :mod:`skills._shared.sentiment`)
- Optional keyword filtering
- Optional Telegram channel ingestion (via :mod:`skills._shared.telegram_news`)
- Deduplication by URL/title
- Aggregate sentiment score for downstream rules

Result shape:

    {
        "ok": True,
        "items": [
            {"source": "rss", "url": "...", "title": "...",
             "sentiment": 0.6, "sentiment_label": "positive", ...},
            ...
        ],
        "agg_sentiment": 0.31,
        "counts": {"positive": 4, "neutral": 6, "negative": 1, "total": 11},
        "telegram_used": True,
    }
"""

from __future__ import annotations

from typing import Any, Iterable

try:
    import feedparser
except Exception:  # pragma: no cover
    feedparser = None

from . import telegram_news as tg
from .sentiment import score_items, aggregate_score


def _rss(url: str, *, limit: int = 15) -> list[dict[str, Any]]:
    if feedparser is None:
        return []
    try:
        d = feedparser.parse(url)
    except Exception:
        return []
    out = []
    for entry in (d.entries or [])[:limit]:
        out.append({
            "source": "rss",
            "feed": url,
            "url": getattr(entry, "link", None),
            "title": getattr(entry, "title", "") or "",
            "summary": getattr(entry, "summary", "") or "",
            "published": getattr(entry, "published", None) or getattr(entry, "updated", None),
            "weight": 1.0,
        })
    return out


def _match_keywords(item: dict[str, Any], keywords: Iterable[str]) -> bool:
    if not keywords:
        return True
    text = (item.get("title", "") + " " + item.get("summary", "")).lower()
    return any(k.lower() in text for k in keywords)


def fetch(
    rss_feeds: Iterable[str] = (),
    *,
    keywords: Iterable[str] | None = None,
    use_telegram: bool = True,
    tg_category: str | None = None,
    tg_tags: Iterable[str] | None = None,
    tg_window_hours: int = 48,
    tg_limit_per_channel: int = 15,
    per_feed_limit: int = 15,
    max_items: int = 30,
) -> dict[str, Any]:
    """Aggregate RSS + Telegram, score sentiment, dedupe, and return.

    ``keywords`` is an optional case-insensitive substring filter applied to
    title+summary. Useful for symbol-specific news (e.g. ['BTC', 'bitcoin']).
    """
    # RSS items are filtered by symbol-keyword (RSS feeds are broad, need
    # narrowing). Telegram items are NOT filtered here — they are already
    # pre-filtered upstream by channel category + tag in telegram_news.fetch,
    # and content (e.g. geopolitical headlines that move gold) often doesn't
    # contain the literal symbol/keyword in the text.
    rss_items: list[dict[str, Any]] = []
    for url in rss_feeds:
        rss_items.extend(_rss(url, limit=per_feed_limit))
    if keywords:
        rss_items = [it for it in rss_items if _match_keywords(it, keywords)]

    telegram_items: list[dict[str, Any]] = []
    telegram_used = False
    tg_errors: list[str] = []
    if use_telegram:
        try:
            tg_out = tg.fetch(
                category=tg_category,
                tags=tg_tags,
                limit_per_channel=tg_limit_per_channel,
                window_hours=tg_window_hours,
            )
            if tg_out.get("ok"):
                telegram_used = True
                for it in tg_out.get("items", []):
                    it = dict(it)
                    it["source"] = "telegram"
                    telegram_items.append(it)
            tg_errors.extend(tg_out.get("errors", []) or [])
        except Exception as e:
            tg_errors.append(f"{type(e).__name__}: {e}")

    items: list[dict[str, Any]] = rss_items + telegram_items

    seen = set()
    deduped = []
    for it in items:
        key = (it.get("url") or "") + "|" + (it.get("title") or "")[:80]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)

    deduped = deduped[:max_items]
    scored = score_items(deduped)
    agg = aggregate_score(scored)
    counts = {"positive": 0, "negative": 0, "neutral": 0, "total": len(scored)}
    for it in scored:
        counts[it.get("sentiment_label", "neutral")] = counts.get(it.get("sentiment_label", "neutral"), 0) + 1

    return {
        "ok": True,
        "items": scored,
        "agg_sentiment": round(agg, 3),
        "counts": counts,
        "telegram_used": telegram_used,
        "telegram_errors": tg_errors,
    }
