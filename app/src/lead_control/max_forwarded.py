from __future__ import annotations

import logging
from typing import Any

from .max_client import MaxClient


LOG = logging.getLogger(__name__)


def enrich_incomplete_forwarded_messages(
    events: list[dict[str, Any]],
    client: MaxClient,
) -> bool:
    """Recover content for MAX forwarded messages that were stored with empty text."""
    changed = False

    for event in events:
        if event.get("type") != "max_message_created" or event.get("source") != "MAX":
            continue
        if not event.get("has_linked_or_forwarded_message"):
            continue
        if str(event.get("text") or "").strip():
            continue
        if str(event.get("linked_or_forwarded_text") or "").strip():
            continue

        message_id = str(event.get("message_id") or "").strip()
        if not message_id:
            continue

        try:
            messages = client.get_messages([message_id])
        except RuntimeError as exc:
            LOG.warning(
                "MAX forwarded message fetch failed message_id=%s error=%s",
                message_id,
                exc,
            )
            continue

        if not messages:
            continue

        content = _forwarded_content(messages[0])
        if not content:
            continue

        event["linked_or_forwarded_text"] = content
        changed = True

    return changed


def _forwarded_content(message: dict[str, Any]) -> str:
    body = _dict(message.get("body"))
    linked = _linked_or_forwarded(message, body)
    if not linked:
        return ""

    parts: list[str] = []
    _collect_content(linked, parts)

    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        normalized = part.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return "\n".join(result)


def _collect_content(value: Any, parts: list[str]) -> None:
    if isinstance(value, list):
        for item in value:
            _collect_content(item, parts)
        return
    if not isinstance(value, dict):
        return

    for key in ("text", "caption", "description", "title", "url"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            parts.append(item.strip())

    for key in (
        "body",
        "attachments",
        "attachment",
        "payload",
        "message",
        "linked_message",
        "forwarded_message",
        "link",
    ):
        child = value.get(key)
        if isinstance(child, (dict, list)):
            _collect_content(child, parts)


def _linked_or_forwarded(message: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    value = (
        message.get("linked_message")
        or message.get("forwarded_message")
        or message.get("link")
        or body.get("linked_message")
        or body.get("forwarded_message")
    )
    return _dict(value)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
