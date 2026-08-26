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
from zoneinfo import ZoneInfo


MAX_API_BASE_URL = "https://platform-api2.max.ru"
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
DEFAULT_START = datetime(2026, 6, 1, 0, 0, 0, tzinfo=MOSCOW_TZ)


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run MAX message history export.")
    parser.add_argument("--chat-id", required=True, type=int)
    parser.add_argument("--output", default="max-history-dry-run.json")
    parser.add_argument("--ca-file", default="certs/max_ca_bundle.pem")
    parser.add_argument("--count", default=100, type=int)
    args = parser.parse_args()

    token = os.environ.get("MAX_BOT_TOKEN")
    if not token:
        stats = _empty_stats(args.chat_id)
        stats["api_ok"] = False
        stats["errors"].append("MAX_BOT_TOKEN is missing")
        _write_output(Path(args.output), stats, [])
        _write_summary(stats)
        return 1

    start_ms = int(DEFAULT_START.timestamp() * 1000)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    stats = _empty_stats(args.chat_id, start_ms=start_ms, end_ms=now_ms)
    messages: list[dict[str, Any]] = []
    seen_mids: set[str] = set()
    current_from = now_ms
    ssl_context = _ssl_context(args.ca_file)

    try:
        while current_from >= start_ms:
            stats["api_requests"] += 1
            batch = _fetch_messages(
                token=token,
                chat_id=args.chat_id,
                from_ms=current_from,
                to_ms=start_ms,
                count=args.count,
                ssl_context=ssl_context,
            )
            if not batch:
                break

            oldest_timestamp = None
            new_unique_in_batch = 0
            for raw_message in batch:
                normalized = _normalize_message(raw_message, fallback_chat_id=args.chat_id)
                mid = normalized.get("body_mid")
                timestamp = normalized.get("timestamp")
                if timestamp is not None:
                    oldest_timestamp = min(int(timestamp), oldest_timestamp) if oldest_timestamp is not None else int(timestamp)
                if not mid or mid in seen_mids:
                    continue
                seen_mids.add(str(mid))
                messages.append(normalized)
                new_unique_in_batch += 1

            if oldest_timestamp is None:
                break
            if len(batch) < args.count:
                break
            next_from = oldest_timestamp - 1
            if next_from >= current_from or new_unique_in_batch == 0:
                break
            current_from = next_from
    except Exception as exc:
        stats["api_ok"] = False
        stats["errors"].append(str(exc))

    messages.sort(key=lambda item: int(item.get("timestamp") or 0), reverse=True)
    _finalize_stats(stats, messages, start_ms)
    _write_output(Path(args.output), stats, messages)
    _write_summary(stats)
    return 0 if stats["api_ok"] else 1


def _fetch_messages(
    *,
    token: str,
    chat_id: int,
    from_ms: int,
    to_ms: int,
    count: int,
    ssl_context: ssl.SSLContext,
) -> list[dict[str, Any]]:
    params = {
        "chat_id": chat_id,
        "from": from_ms,
        "to": to_ms,
        "count": count,
    }
    url = f"{MAX_API_BASE_URL}/messages?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": token,
        },
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


def _normalize_message(message: dict[str, Any], fallback_chat_id: int) -> dict[str, Any]:
    body = _dict(message.get("body"))
    sender = _dict(message.get("sender"))
    recipient = _dict(message.get("recipient"))
    attachments = message.get("attachments") or body.get("attachments") or []
    linked = (
        message.get("linked_message")
        or message.get("forwarded_message")
        or message.get("link")
        or body.get("linked_message")
        or body.get("forwarded_message")
    )
    chat_id = recipient.get("chat_id") or message.get("chat_id") or fallback_chat_id
    return {
        "body_mid": body.get("mid"),
        "timestamp": message.get("timestamp") or body.get("timestamp"),
        "text": body.get("text") or message.get("text") or "",
        "sender": {
            "user_id": sender.get("user_id") or sender.get("id"),
            "first_name": sender.get("first_name"),
            "last_name": sender.get("last_name"),
            "username": sender.get("username"),
        },
        "chat_id": chat_id,
        "has_attachments": bool(attachments),
        "has_linked_or_forwarded_message": bool(linked),
    }


def _finalize_stats(stats: dict[str, Any], messages: list[dict[str, Any]], start_ms: int) -> None:
    timestamps = [int(item["timestamp"]) for item in messages if item.get("timestamp") is not None]
    sender_ids = {
        (item.get("sender") or {}).get("user_id")
        for item in messages
        if (item.get("sender") or {}).get("user_id") is not None
    }
    text_count = sum(1 for item in messages if str(item.get("text") or "").strip())
    day_counts: dict[str, int] = {}
    for timestamp in timestamps:
        day = _format_ms(timestamp).split("T", maxsplit=1)[0]
        day_counts[day] = day_counts.get(day, 0) + 1

    newest = max(timestamps) if timestamps else None
    oldest = min(timestamps) if timestamps else None
    stats.update(
        {
            "unique_messages": len(messages),
            "newest_message_at": _format_ms(newest),
            "oldest_message_at": _format_ms(oldest),
            "reached_start": bool(oldest is not None and oldest <= start_ms),
            "earliest_available_date": _format_ms(oldest).split("T", maxsplit=1)[0] if oldest is not None else "",
            "messages_with_text": text_count,
            "messages_without_text": len(messages) - text_count,
            "unique_senders": len(sender_ids),
            "by_day": dict(sorted(day_counts.items())),
        }
    )


def _empty_stats(chat_id: int, start_ms: int | None = None, end_ms: int | None = None) -> dict[str, Any]:
    start_ms = start_ms if start_ms is not None else int(DEFAULT_START.timestamp() * 1000)
    end_ms = end_ms if end_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    return {
        "api_ok": True,
        "chat_id": chat_id,
        "period_requested": {
            "from": _format_ms(start_ms),
            "to": _format_ms(end_ms),
            "from_ms": start_ms,
            "to_ms": end_ms,
        },
        "unique_messages": 0,
        "newest_message_at": "",
        "oldest_message_at": "",
        "reached_start": False,
        "earliest_available_date": "",
        "messages_with_text": 0,
        "messages_without_text": 0,
        "unique_senders": 0,
        "api_requests": 0,
        "errors": [],
        "production_data_changed": False,
        "by_day": {},
    }


def _write_output(path: Path, stats: dict[str, Any], messages: list[dict[str, Any]]) -> None:
    payload = {
        "stats": stats,
        "messages": messages,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_summary(stats: dict[str, Any]) -> None:
    lines = [
        "# MAX History Dry Run",
        "",
        f"MAX history API: {'OK' if stats['api_ok'] else 'ошибка'}",
        f"период запроса: {stats['period_requested']['from']} -> {stats['period_requested']['to']}",
        f"всего уникальных сообщений: {stats['unique_messages']}",
        f"самое новое: {stats['newest_message_at']}",
        f"самое старое: {stats['oldest_message_at']}",
        f"дошли до 01.06.2026: {'да' if stats['reached_start'] else 'нет'}",
        f"самая ранняя доступная дата: {stats['earliest_available_date']}",
        f"с текстом: {stats['messages_with_text']}",
        f"без текста: {stats['messages_without_text']}",
        f"уникальных отправителей: {stats['unique_senders']}",
        f"API requests: {stats['api_requests']}",
        f"ошибки: {'; '.join(stats['errors']) if stats['errors'] else 'нет'}",
        "production data изменены: нет",
    ]
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def _format_ms(timestamp_ms: int | None) -> str:
    if timestamp_ms is None:
        return ""
    return datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=timezone.utc).astimezone(MOSCOW_TZ).isoformat()


def _ssl_context(ca_file: str) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=ca_file)
    if hasattr(ssl, "VERIFY_X509_PARTIAL_CHAIN"):
        context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    return context


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


if __name__ == "__main__":
    sys.exit(main())
