"""Reliable MAX group ingestion from paginated chat history.

MAX documents /updates long polling as unsuitable for production and may
return zero updates despite new messages. Reconcile messages from /messages
by immutable message ID, preserving the existing event format and CRM logic.

This module never sends a MAX message, changes an /updates cursor, or writes
data by itself. The caller persists newly found events before advancing the
history watermark alongside the ordinary Lead Control state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .max_client import MaxClient, filter_new_max_events, normalize_max_update

MAX_HISTORY_PAGE_SIZE = 100
MAX_HISTORY_MAX_PAGES = 40
MAX_HISTORY_OVERLAP_MS = 3 * 24 * 60 * 60 * 1000
MAX_HISTORY_FIRST_RUN_DAYS = 7


@dataclass(frozen=True)
class MaxHistoryRecovery:
    events: list[dict[str, Any]]
    watermark_ms: int
    pages: int
    scanned: int
    bot_messages_skipped: int


def _timestamp_ms(value: Any) -> int:
    try:
        timestamp = int(value or 0)
    except (ValueError, TypeError):
        return 0
    if timestamp <= 0:
        return 0
    return timestamp * 1000 if timestamp < 100_000_000_000 else timestamp


def reconcile_max_history(
    client: MaxClient,
    *,
    chat_id: int,
    events: list[dict[str, Any]],
    state: dict[str, Any],
    now_ms: int | None = None,
    max_pages: int = MAX_HISTORY_MAX_PAGES,
) -> MaxHistoryRecovery:
    """Read every group message newer than the last saved checkpoint, with overlap.

    Keep a three-day overlap to recover out-of-order gaps, including messages
    published shortly before a later /updates message was saved. If /updates
    stops delivering, the history watermark continues independently.
    """
    if max_pages < 1:
        raise ValueError("MAX history max_pages must be positive")
    if now_ms is None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    prior_state_ms = _timestamp_ms(state.get("history_last_seen_ms"))
    last_persisted_ms = max(
        (
            _timestamp_ms(event.get("timestamp"))
            for event in events
            if event.get("type") == "max_message_created"
            and str(event.get("source") or "") == "MAX"
            and str(event.get("chat_id") or "") == str(chat_id)
        ),
        default=0,
    )
    anchor = max(prior_state_ms, last_persisted_ms)
    if anchor:
        since_ms = max(0, anchor - MAX_HISTORY_OVERLAP_MS)
    else:
        since_ms = max(0, now_ms - MAX_HISTORY_FIRST_RUN_DAYS * 24 * 60 * 60 * 1000)

    me = client.get_me()
    try:
        bot_user_id = int(me.get("user_id") or 0)
    except (ValueError, TypeError):
        bot_user_id = 0
    if bot_user_id <= 0:
        raise RuntimeError("MAX /me did not return a valid bot user ID; aborting history sync")

    known_ids = {
        str(event.get("message_id"))
        for event in events
        if event.get("source") == "MAX"
        and str(event.get("chat_id")) == str(chat_id)
        and event.get("message_id")
    }
    discovered: list[dict[str, Any]] = []
    seen_ids = set(known_ids)
    highwater_ms = anchor
    scanned = 0
    bot_skipped = 0
    before_ms: int | None = None
    previous_oldest_ms: int | None = None

    for page in range(1, max_pages + 1):
        rows = client.get_chat_messages(
            chat_id, before_ms=before_ms, since_ms=since_ms,
            count=MAX_HISTORY_PAGE_SIZE,
        )
        if not rows:
            return MaxHistoryRecovery(discovered, highwater_ms, page, scanned, bot_skipped)

        timestamps: list[int] = []
        for row in rows:
            body = row.get("body") or {}
            sender = row.get("sender") or {}
            if not isinstance(body, dict) or not isinstance(sender, dict):
                raise RuntimeError("MAX chat message body or sender is invalid")
            mid = str(body.get("mid") or "").strip()
            ts = _timestamp_ms(row.get("timestamp"))
            if not mid or not ts:
                raise RuntimeError("MAX chat history message missing ID or timestamp")
            timestamps.append(ts)
            scanned += 1
            highwater_ms = max(highwater_ms, ts)
            if ts < since_ms:
                continue
            if str(sender.get("user_id") or "") == str(bot_user_id):
                bot_skipped += 1
                continue
            if mid in seen_ids:
                continue

            recipient = row.get("recipient") or {}
            if not isinstance(recipient, dict):
                raise RuntimeError("MAX chat history recipient is invalid")
            if recipient.get("chat_id") is not None and str(recipient["chat_id"]) != str(chat_id):
                raise RuntimeError("MAX chat history returned a different group")
            rebuilt_message = dict(row)
            rebuilt_message["recipient"] = {**recipient, "chat_id": int(chat_id)}
            update = {
                "update_type": "message_created",
                "chat_id": int(chat_id),
                "timestamp": row["timestamp"],
                "message": rebuilt_message,
            }
            normalized = normalize_max_update(update, chat_id=int(chat_id))
            if not normalized or not normalized.get("message_id"):
                raise RuntimeError("MAX chat message normalization failed")
            seen_ids.add(mid)
            discovered.append(normalized)

        oldest_ms = min(timestamps)
        if previous_oldest_ms is not None and oldest_ms >= previous_oldest_ms:
            raise RuntimeError("MAX chat history pagination did not advance")
        if before_ms is not None and oldest_ms > before_ms:
            raise RuntimeError("MAX chat history ignored the pagination boundary")
        if oldest_ms <= since_ms or len(rows) < MAX_HISTORY_PAGE_SIZE:
            # Reaching the overlap boundary (or exhausting history) means no gap.
            return MaxHistoryRecovery(discovered, highwater_ms, page, scanned, bot_skipped)
        previous_oldest_ms = oldest_ms
        before_ms = oldest_ms - 1

    # A partial backfill must not silently move the cursor and lose older leads.
    raise RuntimeError(
        f"MAX chat history exceeded {max_pages} pages before reaching overlap boundary"
    )
