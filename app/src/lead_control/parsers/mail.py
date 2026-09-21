from __future__ import annotations

import re
from typing import Any

from ..normalize import normalize_phone, parse_event_date


SOURCE = "Заявка почта"


def parse_mail_message(message: dict[str, Any]) -> dict[str, Any] | None:
    text = str(message.get("caption") or message.get("text") or "").strip()
    if not _is_mail_label(text):
        return None

    phone_raw = _label_value(text, ("телефон", "тел", "phone")) or _extract_phone(text)
    name = _label_value(text, ("имя клиента", "имя", "name"))
    event_date_raw = _label_value(text, ("дата", "date"))
    guests_raw = _label_value(text, ("количество гостей", "гостей", "guests"))
    event_type = _label_value(text, ("мероприятие", "тип мероприятия", "event type"))

    return {
        "source": SOURCE,
        "name": name,
        "phone_raw": phone_raw,
        "phone_digits": normalize_phone(phone_raw),
        "telegram_username": "",
        "event_date_raw": event_date_raw,
        "event_date": parse_event_date(event_date_raw),
        "guests_count": _parse_int(guests_raw),
        "event_type": event_type,
        "description": text,
        "has_photo": bool(message.get("photo")),
    }


def _is_mail_label(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text.casefold()).strip(" .:-")
    return normalized == "заявка почта" or normalized.startswith("заявка почта ")


def _label_value(text: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        match = re.search(rf"(?mi)^\s*{re.escape(label)}\s*[:=]\s*(.+?)\s*$", text)
        if match:
            return match.group(1).strip()
    return ""


def _extract_phone(text: str) -> str:
    match = re.search(r"(\+?\d[\d\s().-]{8,}\d)", text)
    return match.group(1).strip() if match else ""


def _parse_int(value: str) -> int | None:
    if not value:
        return None
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None
