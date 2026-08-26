from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


MAX_API_BASE_URL = "https://platform-api2.max.ru"
MAX_CHAT_ID = -71704692523093
MAX_ALLOWED_UPDATE_TYPES = ("bot_added", "message_created")


@dataclass(frozen=True)
class MaxUpdatesResult:
    updates: list[dict[str, Any]]
    marker: int | str | None


class MaxClient:
    def __init__(self, token: str, base_url: str = MAX_API_BASE_URL, ca_file: str | None = None) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._ssl_context = _ssl_context(ca_file)

    def get_me(self) -> dict[str, Any]:
        body = self._request_json("/me")
        if not isinstance(body, dict):
            raise RuntimeError("MAX /me failed: response is not an object")
        return body

    def get_updates(
        self,
        marker: int | str | None,
        timeout: int = 0,
        update_types: tuple[str, ...] = MAX_ALLOWED_UPDATE_TYPES,
        limit: int = 1000,
    ) -> MaxUpdatesResult:
        params: dict[str, str | int] = {
            "timeout": int(timeout),
            "limit": max(1, min(int(limit), 1000)),
        }
        if marker is not None:
            params["marker"] = marker
        if update_types:
            params["types"] = ",".join(update_types)

        body = self._request_json("/updates", params)
        if not isinstance(body, dict):
            raise RuntimeError("MAX /updates failed: response is not an object")

        updates = body.get("updates")
        if not isinstance(updates, list):
            raise RuntimeError("MAX /updates failed: updates is not a list")

        return MaxUpdatesResult(updates=updates, marker=body.get("marker"))

    def get_messages(self, message_ids: list[str]) -> list[dict[str, Any]]:
        ids = [str(value).strip() for value in message_ids if str(value).strip()]
        if not ids:
            return []
        body = self._request_json("/messages", {"message_ids": ",".join(ids)})
        if not isinstance(body, dict):
            raise RuntimeError("MAX /messages failed: response is not an object")
        messages = body.get("messages")
        if not isinstance(messages, list):
            raise RuntimeError("MAX /messages failed: messages is not a list")
        return [item for item in messages if isinstance(item, dict)]

    def _request_json(self, path: str, params: dict[str, str | int] | None = None) -> Any:
        query = ""
        if params:
            query = "?" + urllib.parse.urlencode(params)

        request = urllib.request.Request(
            self._base_url + path + query,
            headers={
                "Accept": "application/json",
                "Authorization": self._token,
            },
            method="GET",
        )

        try:
            with urllib.request.urlopen(request, timeout=30, context=self._ssl_context) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"MAX {path} failed: HTTP {exc.code}") from None
        except urllib.error.URLError as exc:
            raise RuntimeError(f"MAX {path} failed: {exc.reason}") from None
        except json.JSONDecodeError:
            raise RuntimeError(f"MAX {path} failed: invalid JSON response") from None


def normalize_max_update(update: dict[str, Any], chat_id: int = MAX_CHAT_ID) -> dict[str, Any] | None:
    update_type = update.get("update_type")
    if update_type not in MAX_ALLOWED_UPDATE_TYPES:
        return None

    if update_type == "bot_added":
        event_chat_id = _bot_added_chat_id(update)
        if event_chat_id != chat_id:
            return None
        return {
            "type": "max_bot_added",
            "source": "MAX",
            "update_type": "bot_added",
            "chat_id": event_chat_id,
            "timestamp": update.get("timestamp"),
            "is_channel": update.get("is_channel"),
        }

    message = _dict(update.get("message"))
    recipient = _dict(message.get("recipient"))
    body = _dict(message.get("body"))
    sender = _dict(message.get("sender"))

    event_chat_id = recipient.get("chat_id") or update.get("chat_id")
    if event_chat_id != chat_id:
        return None

    body_mid = body.get("mid")
    attachments = _attachments(message, body)
    linked = _linked_or_forwarded(message, body)
    event = {
        "type": "max_message_created",
        "source": "MAX",
        "update_type": "message_created",
        "chat_id": event_chat_id,
        "message_id": body_mid,
        "body_mid": body_mid,
        "text": body.get("text") or "",
        "has_attachments": bool(attachments),
        "has_linked_or_forwarded_message": bool(linked),
        "sender_user_id": sender.get("user_id"),
        "sender_username": sender.get("username"),
        "sender_name": sender.get("name"),
        "timestamp": update.get("timestamp") or message.get("timestamp"),
    }
    if attachments:
        # Preserve the MAX attachment payload so downstream enrichment can
        # resolve/download image content instead of losing it at normalization.
        event["attachments"] = attachments
    attachment_text = _attachment_text(attachments)
    if attachment_text:
        event["attachment_text"] = attachment_text
    attachment_types = _attachment_types(attachments)
    if attachment_types:
        event["attachment_types"] = attachment_types
    linked_text = _linked_text(linked)
    if linked_text:
        event["linked_or_forwarded_text"] = linked_text
    return event


def normalize_max_updates(updates: list[dict[str, Any]], chat_id: int = MAX_CHAT_ID) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for update in updates:
        event = normalize_max_update(update, chat_id=chat_id)
        if event is not None:
            events.append(event)
    return events


def filter_new_max_events(
    events: list[dict[str, Any]],
    existing_message_ids: set[str],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen_message_ids = set(existing_message_ids)
    for event in events:
        if event.get("update_type") != "message_created":
            result.append(event)
            continue

        message_id = event.get("message_id")
        if message_id and str(message_id) in seen_message_ids:
            continue
        if message_id:
            seen_message_ids.add(str(message_id))
        result.append(event)
    return result


def message_attachments(message: dict[str, Any]) -> list[dict[str, Any]]:
    body = _dict(message.get("body"))
    return _attachments(message, body)


def _bot_added_chat_id(update: dict[str, Any]) -> Any:
    chat = _dict(update.get("chat"))
    recipient = _dict(update.get("recipient"))
    return update.get("chat_id") or chat.get("chat_id") or chat.get("id") or recipient.get("chat_id")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _attachments(message: dict[str, Any], body: dict[str, Any]) -> list[dict[str, Any]]:
    attachments = message.get("attachments") or body.get("attachments") or []
    if not isinstance(attachments, list):
        return []
    return [item for item in attachments if isinstance(item, dict)]


def _attachment_text(attachments: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for attachment in attachments:
        parts.extend(_text_values(attachment))
        payload = attachment.get("payload")
        if isinstance(payload, dict):
            parts.extend(_text_values(payload))
    return "\n".join(parts)


def _text_values(value: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    for key in ("caption", "text", "description"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            parts.append(item.strip())
    return parts


def _attachment_types(attachments: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for attachment in attachments:
        payload = _dict(attachment.get("payload"))
        attachment_type = attachment.get("type") or attachment.get("attachment_type") or payload.get("type")
        if isinstance(attachment_type, str) and attachment_type not in result:
            result.append(attachment_type)
    return result


def _linked_or_forwarded(message: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    return _dict(
        message.get("linked_message")
        or message.get("forwarded_message")
        or message.get("link")
        or body.get("linked_message")
        or body.get("forwarded_message")
    )


def _linked_text(value: dict[str, Any]) -> str:
    if not value:
        return ""
    body = _dict(value.get("body"))
    text = body.get("text") or value.get("text")
    return text.strip() if isinstance(text, str) else ""


def _ssl_context(ca_file: str | None) -> ssl.SSLContext | None:
    if ca_file is None:
        return None
    context = ssl.create_default_context(cafile=ca_file)
    if hasattr(ssl, "VERIFY_X509_PARTIAL_CHAIN"):
        context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    return context
