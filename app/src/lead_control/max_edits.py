from __future__ import annotations

from typing import Any

from .max_client import message_attachments


def apply_max_message_edits(
    events: list[dict[str, Any]],
    updates: list[dict[str, Any]],
    chat_id: int,
) -> bool:
    """Apply MAX ``message_edited`` updates to the stored source event.

    Lead Control rebuilds leads from the event history, so the edited text must
    replace the previously stored version of that exact MAX message. The
    original creation timestamp is preserved; ``edited_at`` records when the
    edit was observed.
    """
    by_message_id = {
        str(event.get("message_id")): event
        for event in events
        if event.get("source") == "MAX"
        and event.get("type") == "max_message_created"
        and event.get("message_id")
    }
    changed = False

    for update in updates:
        if str(update.get("update_type") or "") != "message_edited":
            continue

        message = update.get("message") if isinstance(update.get("message"), dict) else {}
        recipient = message.get("recipient") if isinstance(message.get("recipient"), dict) else {}
        body = message.get("body") if isinstance(message.get("body"), dict) else {}
        sender = message.get("sender") if isinstance(message.get("sender"), dict) else {}
        event_chat_id = recipient.get("chat_id") or update.get("chat_id")
        if event_chat_id != chat_id:
            continue

        message_id = str(body.get("mid") or "").strip()
        if not message_id:
            continue

        attachments = message_attachments(message)
        text = str(body.get("text") or "")
        target = by_message_id.get(message_id)

        if target is None:
            target = {
                "type": "max_message_created",
                "source": "MAX",
                "update_type": "message_created",
                "chat_id": event_chat_id,
                "message_id": message_id,
                "body_mid": message_id,
                "text": text,
                "has_attachments": bool(attachments),
                "has_linked_or_forwarded_message": bool(_linked_message(message, body)),
                "sender_user_id": sender.get("user_id"),
                "sender_username": sender.get("username"),
                "sender_name": sender.get("name"),
                "timestamp": message.get("timestamp") or update.get("timestamp"),
                "edited_at": update.get("timestamp"),
            }
            if attachments:
                target["attachments"] = attachments
            linked_text = _linked_text(_linked_message(message, body))
            if linked_text:
                target["linked_or_forwarded_text"] = linked_text
            events.append(target)
            by_message_id[message_id] = target
            changed = True
            continue

        if target.get("text") != text:
            target["text"] = text
            changed = True

        if bool(target.get("has_attachments")) != bool(attachments):
            target["has_attachments"] = bool(attachments)
            changed = True
        if attachments:
            if target.get("attachments") != attachments:
                target["attachments"] = attachments
                changed = True
        elif "attachments" in target:
            target.pop("attachments", None)
            changed = True

        linked = _linked_message(message, body)
        linked_text = _linked_text(linked)
        if bool(target.get("has_linked_or_forwarded_message")) != bool(linked):
            target["has_linked_or_forwarded_message"] = bool(linked)
            changed = True
        if linked_text:
            if target.get("linked_or_forwarded_text") != linked_text:
                target["linked_or_forwarded_text"] = linked_text
                changed = True
        elif "linked_or_forwarded_text" in target:
            target.pop("linked_or_forwarded_text", None)
            changed = True

        edited_at = update.get("timestamp")
        if edited_at is not None and target.get("edited_at") != edited_at:
            target["edited_at"] = edited_at
            changed = True

    return changed


def _linked_message(message: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    value = (
        message.get("linked_message")
        or message.get("forwarded_message")
        or message.get("link")
        or body.get("linked_message")
        or body.get("forwarded_message")
    )
    return value if isinstance(value, dict) else {}


def _linked_text(value: dict[str, Any]) -> str:
    if not value:
        return ""
    body = value.get("body") if isinstance(value.get("body"), dict) else {}
    text = body.get("text") or value.get("text")
    return text.strip() if isinstance(text, str) else ""
