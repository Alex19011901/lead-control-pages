from __future__ import annotations

import re
from datetime import datetime, timezone
from itertools import chain
from pathlib import Path
from zoneinfo import ZoneInfo

from .event_type import infer_event_type
from .normalize import normalize_phone, normalize_username, parse_event_date, unix_to_moscow_iso
from .parsers import parse_message
from .state import append_events, load_events
from .telegram_history_202607 import load_history as load_initial_history
from .telegram_history_202607_202608 import load_history as load_full_history


CHAT_ID = -1001645768111
MOSCOW = ZoneInfo("Europe/Moscow")

_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


def import_telegram_history(data_dir: Path) -> int:
    events_path = data_dir / "events.ndjson"
    existing = load_events(events_path)

    # A current live message may already be stored as telegram_needs_review.
    # Treat it as present too: source normalization will promote known
    # TildaForms/Marquiz messages, and we must not duplicate the same message.
    existing_messages = {
        int(event["message_id"])
        for event in existing
        if event.get("type") in {"telegram_lead", "telegram_needs_review"}
        and str(event.get("message_id", "")).lstrip("-").isdigit()
    }
    existing_reactions = {
        (int(event["message_id"]), int((event.get("manager") or {}).get("user_id") or 0))
        for event in existing
        if event.get("type") == "telegram_reaction"
        and str(event.get("message_id", "")).lstrip("-").isdigit()
    }

    new_events: list[dict] = []
    for item in chain(load_initial_history(), load_full_history()):
        message_id = int(item["id"])
        if message_id not in existing_messages:
            lead = _lead_for_item(item)
            if lead is not None:
                created_at = int(item["date_unixtime"])
                ignored_reason = str(lead.pop("ignored_reason", "") or "")
                new_events.append(
                    {
                        "type": "telegram_lead",
                        "update_id": _history_update_id(message_id, 1),
                        "chat_id": CHAT_ID,
                        "message_id": message_id,
                        "telegram_date": created_at,
                        "telegram_date_msk": unix_to_moscow_iso(created_at),
                        "sender_user_id": item.get("sender_user_id"),
                        "sender_username": str(item.get("sender_username") or ""),
                        "sender_name": str(item.get("sender_name") or ""),
                        "source": lead["source"],
                        "ignored": bool(ignored_reason),
                        "ignored_reason": ignored_reason,
                        "lead": lead,
                    }
                )
                existing_messages.add(message_id)

        for reaction in item.get("reaction") or []:
            key = (message_id, int(reaction["user_id"]))
            if key in existing_reactions:
                continue
            reacted_at = _parse_export_datetime(reaction.get("date"))
            if reacted_at is None:
                continue
            new_events.append(
                {
                    "type": "telegram_reaction",
                    "update_id": _history_update_id(message_id, 2),
                    "chat_id": CHAT_ID,
                    "message_id": message_id,
                    "telegram_date": reacted_at,
                    "telegram_date_msk": unix_to_moscow_iso(reacted_at),
                    "action": "reaction_set",
                    "is_manager": True,
                    "manager": {
                        "name": reaction["name"],
                        "username": reaction["username"],
                        "user_id": int(reaction["user_id"]),
                    },
                    "new_reaction": [{"type": "emoji", "emoji": reaction.get("emoji") or "👍"}],
                }
            )
            existing_reactions.add(key)

    if new_events:
        append_events(events_path, new_events)
    return len(new_events)


def _lead_for_item(item: dict) -> dict | None:
    kind = item.get("kind")

    if kind == "parsed":
        lead = dict(item.get("lead") or {})
        return lead if lead.get("source") else None

    if kind == "tilda":
        lead = parse_message(
            {
                "from": {"first_name": "TildaForms", "username": "TildaFormsBot"},
                "text": item.get("text") or "",
            }
        )
        if lead is None:
            return None
        lead["source"] = "САЙТ ТИЛЬДА"
        return lead

    if kind == "marquiz":
        lead = parse_message(
            {
                "from": {"first_name": "MarquizBot", "username": "MarquizBot"},
                "text": item.get("text") or "",
            }
        )
        if lead is None:
            return None
        lead["source"] = "MARQUIZ"
        return lead

    if kind == "tg":
        return _telegram_forwarded_lead(item)

    if kind == "mail":
        return {
            "source": "Заявка почта",
            "category": "Заявка почта",
            "name": "Ирина",
            "phone_raw": "+7 (909) 917 10 59",
            "phone_digits": "79099171059",
            "telegram_username": "",
            "event_date_raw": "6.07.26",
            "event_date": "2026-07-06",
            "guests_count": 60,
            "event_type": "Корпоратив",
            "has_photo": True,
            "description": (
                "Заявка почта. Дата: 6.07.26; время: 16:00; количество гостей: 60; "
                "имя клиента: Ирина; телефон: +7 (909) 917 10 59; "
                "дополнительный номер: 9099857506; корпоратив."
            ),
        }

    return None


def _telegram_forwarded_lead(item: dict) -> dict:
    text = str(item.get("text") or "")
    contact = str(item.get("contact") or "").strip()
    phone_raw = contact if re.search(r"\d", contact) else ""
    username = normalize_username(contact) if contact.startswith("@") else ""
    event_date_raw, event_date = _extract_event_date(text, int(item["date_unixtime"]))
    guests = _extract_guests(text)

    return {
        "source": "Заявка с ТГ",
        "category": "TG_LEAD",
        "name": str(item.get("name") or "").strip(),
        "phone_raw": phone_raw,
        "phone_digits": normalize_phone(phone_raw),
        "telegram_username": username,
        "event_date_raw": event_date_raw,
        "event_date": event_date,
        "guests_count": guests,
        "event_type": infer_event_type(text),
        "description": text.strip(),
    }


def _extract_guests(text: str) -> int | None:
    patterns = (
        r"(?:до\s*)?(\d{1,3})(?:\s*[-–—]\s*(\d{1,3}))?\s*(?:человек|чел\.?|гост(?:ей|я|и)?|персон(?:ы)?|участник(?:ов|а)?)",
        r"(?:на|около)\s+(\d{1,3})(?:\s*[-–—]\s*(\d{1,3}))?\s*(?:человек|чел\.?|гост(?:ей|я|и)?|персон(?:ы)?)?",
    )
    lowered = text.casefold()
    for pattern in patterns:
        match = re.search(pattern, lowered, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _extract_event_date(text: str, received_ts: int) -> tuple[str, str]:
    full = re.search(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b", text)
    if full:
        raw = full.group(0)
        normalized = parse_event_date(raw.replace("/", ".").replace("-", "."))
        return raw, normalized

    received_year = datetime.fromtimestamp(received_ts, tz=timezone.utc).astimezone(MOSCOW).year
    short = re.search(r"\b(\d{1,2})[./-](\d{1,2})(?![./-]\d)\b", text)
    if short:
        day = int(short.group(1))
        month = int(short.group(2))
        try:
            value = datetime(received_year, month, day).date().isoformat()
            return short.group(0), value
        except ValueError:
            pass

    month_names = "|".join(_MONTHS)
    named = re.search(rf"\b(\d{{1,2}})\s+({month_names})\b", text.casefold())
    if named:
        day = int(named.group(1))
        month = _MONTHS[named.group(2)]
        try:
            value = datetime(received_year, month, day).date().isoformat()
            return named.group(0), value
        except ValueError:
            pass

    return "", ""


def _parse_export_datetime(value: str | None) -> int | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MOSCOW)
    return int(dt.timestamp())


def _history_update_id(message_id: int, suffix: int) -> int:
    return -(10_000_000 + message_id * 10 + suffix)
