"""Read-only Telegram channel/group ingestion via Telethon (user session).

Hermes uses a *user* account (not a bot) so it can read any channel/group the
account is a member of. Session lives at ``~/.agent/credentials/telegram-user.session``
(chmod 600) and is reused across calls — first run requires an OTP login flow
driven by ``scripts/telegram_login.py``.

Channel subscriptions are configured in ``~/.agent/credentials/tg-channels.yaml``
(or path overridden by ``HERMES_TG_CHANNELS_FILE``):

    channels:
      - id: "@cryptosignals_id"
        category: crypto          # crypto | saham | forex | macro
        tags: [BTC, ETH]
        weight: 0.7
      - id: -1001234567890        # numeric chat id also OK
        category: forex
        tags: [EURUSD, USD]
        weight: 0.9

This module never sends messages, never reacts, never forwards — purely read.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from telethon import TelegramClient
    from telethon.errors import RPCError
except Exception:  # pragma: no cover
    TelegramClient = None
    RPCError = Exception

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


DEFAULT_SESSION_PATH = os.path.expanduser("~/.agent/credentials/telegram-user.session")
DEFAULT_CHANNELS_FILE = os.path.expanduser("~/.agent/credentials/tg-channels.yaml")


@dataclass
class ChannelConfig:
    id: Any
    category: str = "macro"
    tags: list[str] | None = None
    weight: float = 1.0
    title: str | None = None


def _credentials() -> tuple[int | None, str | None, str]:
    api_id = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    session_path = os.environ.get("HERMES_TG_SESSION", DEFAULT_SESSION_PATH)
    try:
        return int(api_id) if api_id else None, api_hash or None, session_path
    except ValueError:
        return None, api_hash or None, session_path


def load_channels(path: str | None = None) -> list[ChannelConfig]:
    """Load channel subscriptions from YAML/JSON config."""
    p = Path(path or os.environ.get("HERMES_TG_CHANNELS_FILE") or DEFAULT_CHANNELS_FILE)
    if not p.exists():
        return []
    try:
        text = p.read_text()
        if p.suffix in (".yaml", ".yml") and yaml is not None:
            data = yaml.safe_load(text) or {}
        else:
            data = json.loads(text or "{}")
    except Exception:
        return []
    items = data.get("channels") or []
    out: list[ChannelConfig] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append(ChannelConfig(
            id=it.get("id"),
            category=str(it.get("category") or "macro"),
            tags=list(it.get("tags") or []),
            weight=float(it.get("weight") or 1.0),
            title=it.get("title"),
        ))
    return out


def _filter_channels(channels: list[ChannelConfig], *, category: str | None, tags: Iterable[str] | None) -> list[ChannelConfig]:
    if not channels:
        return []
    out = []
    tag_set = {t.upper() for t in (tags or [])}
    for ch in channels:
        if category and ch.category != category:
            continue
        if tag_set:
            ch_tags = {t.upper() for t in (ch.tags or [])}
            if not (ch_tags & tag_set):
                continue
        out.append(ch)
    return out


async def _fetch_messages(client: TelegramClient, channel: ChannelConfig, *, limit: int, since: datetime) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        entity = await client.get_entity(channel.id)
        async for msg in client.iter_messages(entity, limit=limit):
            if msg.date is None or msg.date < since:
                break
            text = (msg.message or "").strip()
            if not text:
                continue
            out.append({
                "id": msg.id,
                "channel": getattr(entity, "username", None) or channel.id,
                "channel_title": getattr(entity, "title", channel.title or str(channel.id)),
                "category": channel.category,
                "tags": channel.tags or [],
                "date": msg.date.astimezone(timezone.utc).isoformat(),
                "title": text.splitlines()[0][:140] if text else "",
                "summary": text[:600],
                "body": text,
                "weight": channel.weight,
                "url": f"https://t.me/{getattr(entity, 'username', '')}/{msg.id}" if getattr(entity, "username", None) else None,
            })
    except RPCError as e:
        out.append({"_error": f"channel {channel.id}: {type(e).__name__}: {e}"})
    except Exception as e:
        out.append({"_error": f"channel {channel.id}: {type(e).__name__}: {e}"})
    return out


def fetch(
    *,
    category: str | None = None,
    tags: Iterable[str] | None = None,
    limit_per_channel: int = 20,
    window_hours: int = 48,
    channels_file: str | None = None,
) -> dict[str, Any]:
    """Return recent Telegram messages from configured channels.

    Filters: ``category`` (e.g. 'crypto') and ``tags`` (matches any tag on the
    channel config — case-insensitive). Returns
    ``{"ok": bool, "items": [...], "errors": [...], "channel_count": N}``.
    """
    if TelegramClient is None:
        return {"ok": False, "error": "telethon not installed", "items": [], "errors": []}
    api_id, api_hash, session = _credentials()
    if not api_id or not api_hash:
        return {"ok": False, "error": "TELEGRAM_API_ID / TELEGRAM_API_HASH not set", "items": [], "errors": []}
    channels = load_channels(channels_file)
    if not channels:
        return {"ok": True, "items": [], "errors": [], "channel_count": 0, "note": "no channels configured"}
    channels = _filter_channels(channels, category=category, tags=tags)
    if not channels:
        return {"ok": True, "items": [], "errors": [], "channel_count": 0, "note": "no channel matched filter"}

    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    items: list[dict[str, Any]] = []
    errors: list[str] = []

    async def runner() -> None:
        client = TelegramClient(session, api_id, api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            errors.append("session not authorized — run scripts/telegram_login.py first")
            await client.disconnect()
            return
        try:
            for ch in channels:
                got = await _fetch_messages(client, ch, limit=limit_per_channel, since=since)
                for g in got:
                    if "_error" in g:
                        errors.append(str(g["_error"]))
                    else:
                        items.append(g)
        finally:
            await client.disconnect()

    try:
        asyncio.run(runner())
    except Exception as e:
        errors.append(f"runtime: {type(e).__name__}: {e}")

    # Sort newest first.
    items.sort(key=lambda x: x.get("date") or "", reverse=True)
    return {
        "ok": not items == [] or not errors,
        "items": items,
        "errors": errors,
        "channel_count": len(channels),
    }
