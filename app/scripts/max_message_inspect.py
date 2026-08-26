from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_API_BASE_URL = "https://platform-api2.max.ru"


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect one MAX message attachment without exposing secrets.")
    parser.add_argument("--chat-id", required=True, type=int)
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--from-ms", required=True, type=int)
    parser.add_argument("--to-ms", required=True, type=int)
    parser.add_argument("--output", default="max-message-inspect.json")
    parser.add_argument("--ca-file", default="certs/max_ca_bundle.pem")
    parser.add_argument("--count", default=100, type=int)
    args = parser.parse_args()

    token = os.environ.get("MAX_BOT_TOKEN")
    result: dict[str, Any] = {
        "api_ok": True,
        "message_found": False,
        "chat_id": args.chat_id,
        "message_id": args.message_id,
        "attachments": [],
        "errors": [],
    }
    if not token:
        result["api_ok"] = False
        result["errors"].append("MAX_BOT_TOKEN is missing")
        _write_result(Path(args.output), result)
        return 1

    ssl_context = ssl.create_default_context(cafile=args.ca_file)
    current_from = args.from_ms
    seen_mids: set[str] = set()

    try:
        while current_from >= args.to_ms:
            batch = _fetch_messages(
                token=token,
                chat_id=args.chat_id,
                from_ms=current_from,
                to_ms=args.to_ms,
                count=args.count,
                ssl_context=ssl_context,
            )
            if not batch:
                break

            oldest_timestamp: int | None = None
            new_unique = 0
            for raw in batch:
                body = _dict(raw.get("body"))
                mid = body.get("mid")
                timestamp = raw.get("timestamp") or body.get("timestamp")
                if timestamp is not None:
                    oldest_timestamp = min(int(timestamp), oldest_timestamp) if oldest_timestamp is not None else int(timestamp)
                if not mid or mid in seen_mids:
                    continue
                seen_mids.add(str(mid))
                new_unique += 1
                if str(mid) == args.message_id:
                    result.update(_sanitize_message(raw, fallback_chat_id=args.chat_id))
                    result["message_found"] = True
                    _write_result(Path(args.output), result)
                    return 0

            if oldest_timestamp is None or len(batch) < args.count:
                break
            next_from = oldest_timestamp - 1
            if next_from >= current_from or new_unique == 0:
                break
            current_from = next_from
    except Exception as exc:
        result["api_ok"] = False
        result["errors"].append(str(exc))

    _write_result(Path(args.output), result)
    return 0 if result["api_ok"] else 1


def _fetch_messages(
    *,
    token: str,
    chat_id: int,
    from_ms: int,
    to_ms: int,
    count: int,
    ssl_context: ssl.SSLContext,
) -> list[dict[str, Any]]:
    params = {"chat_id": chat_id, "from": from_ms, "to": to_ms, "count": count}
    request = urllib.request.Request(
        f"{MAX_API_BASE_URL}/messages?{urllib.parse.urlencode(params)}",
        headers={"Accept": "application/json", "Authorization": token},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30, context=ssl_context) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"MAX /messages failed: HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"MAX /messages failed: {exc.reason}") from None
    except json.JSONDecodeError:
        raise RuntimeError("MAX /messages failed: invalid JSON response") from None

    messages = _extract_messages(body)
    if not isinstance(messages, list):
        raise RuntimeError("MAX /messages failed: response does not contain messages list")
    return [item for item in messages if isinstance(item, dict)]


def _extract_messages(body: Any) -> Any:
    if isinstance(body, list):
        return body
    if not isinstance(body, dict):
        return None
    for key in ("messages", "items", "result"):
        value = body.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _extract_messages(value)
            if isinstance(nested, list):
                return nested
    return None


def _sanitize_message(raw: dict[str, Any], fallback_chat_id: int) -> dict[str, Any]:
    body = _dict(raw.get("body"))
    sender = _dict(raw.get("sender"))
    recipient = _dict(raw.get("recipient"))
    attachments = raw.get("attachments") or body.get("attachments") or []
    linked = (
        raw.get("linked_message")
        or raw.get("forwarded_message")
        or raw.get("link")
        or body.get("linked_message")
        or body.get("forwarded_message")
    )
    return {
        "chat_id": recipient.get("chat_id") or raw.get("chat_id") or fallback_chat_id,
        "message_id": body.get("mid"),
        "timestamp": raw.get("timestamp") or body.get("timestamp"),
        "timestamp_msk": _format_msk(raw.get("timestamp") or body.get("timestamp")),
        "sender": {
            "user_id": sender.get("user_id") or sender.get("id"),
            "first_name": sender.get("first_name"),
            "last_name": sender.get("last_name"),
            "username": sender.get("username"),
        },
        "body_text": body.get("text") or raw.get("text") or "",
        "body_caption": _first_string(body, ("caption", "description")),
        "has_linked_or_forwarded_message": bool(linked),
        "linked_or_forwarded_text": _linked_text(linked),
        "attachments": [_sanitize_attachment(item) for item in attachments if isinstance(item, dict)],
    }


def _sanitize_attachment(attachment: dict[str, Any]) -> dict[str, Any]:
    payload = _dict(attachment.get("payload"))
    return {
        "type": attachment.get("type") or attachment.get("attachment_type") or payload.get("type"),
        "caption": _first_string(attachment, ("caption", "description")) or _first_string(payload, ("caption", "description")),
        "filename": _first_string(attachment, ("filename", "file_name", "name")) or _first_string(payload, ("filename", "file_name", "name")),
        "title": _first_string(attachment, ("title",)) or _first_string(payload, ("title",)),
        "text": _first_string(attachment, ("text",)) or _first_string(payload, ("text",)),
        "ids": _ids(attachment) | _ids(payload),
    }


def _ids(value: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("id", "file_id", "photo_id", "video_id", "sticker_id", "token", "url"):
        item = value.get(key)
        if item is None:
            continue
        if key in {"token", "url"}:
            continue
        result[key] = item
    return result


def _linked_text(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    body = _dict(value.get("body"))
    return body.get("text") or value.get("text")


def _first_string(value: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item
    return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _format_msk(timestamp_ms: Any) -> str | None:
    if timestamp_ms is None:
        return None
    return datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=timezone.utc).astimezone().isoformat()


def _write_result(path: Path, result: dict[str, Any]) -> None:
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
