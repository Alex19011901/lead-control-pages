from __future__ import annotations

import re
from typing import Any

from ..normalize import normalize_phone, parse_event_date


SOURCE = "MARQUIZ"


def parse_marquiz_message(message: dict[str, Any]) -> dict[str, Any] | None:
    if not _is_marquiz_sender(message):
        return None

    text = str(message.get("text") or message.get("caption") or "")
    if not text.strip():
        return None

    phone_raw = _label_value(text, "Телефон") or _extract_phone(text)
    phone_digits = normalize_phone(phone_raw)
    name = _label_value(text, "Имя")
    event_type = _answer_after_question(text, "Какое мероприятие вы планируете?")
    guests_raw = _answer_after_question(text, "Сколько гостей ожидается?")
    event_date_raw = _answer_after_question(text, "Уточните дату Вашего мероприятия?")
    event_format = _answer_after_question(text, "Какой формат мероприятия интересует?")

    return {
        "source": SOURCE,
        "name": name,
        "phone_raw": phone_raw,
        "phone_digits": phone_digits,
        "telegram_username": "",
        "event_date_raw": event_date_raw,
        "event_date": parse_event_date(event_date_raw),
        "guests_count": _guest_count(guests_raw),
        "guests_raw": guests_raw,
        "event_type": event_type,
        "event_format": event_format,
        "description": text.strip(),
    }


def _is_marquiz_sender(message: dict[str, Any]) -> bool:
    sender = message.get("from") or {}
    candidates = {
        str(sender.get("username") or "").strip().lower(),
        str(sender.get("first_name") or "").strip().lower(),
        str(sender.get("last_name") or "").strip().lower(),
    }
    return "marquizbot" in candidates


def _label_value(text: str, label: str) -> str:
    match = re.search(rf"(?mi)^\s*{re.escape(label)}\s*:\s*(.+?)\s*$", text)
    return match.group(1).strip() if match else ""


def _answer_after_question(text: str, question: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    for idx, line in enumerate(lines):
        if line.casefold() != question.casefold():
            continue
        for answer in lines[idx + 1 :]:
            if answer:
                return answer
    return ""


def _extract_phone(text: str) -> str:
    match = re.search(r"(\+?\d[\d\s().-]{8,}\d)", text)
    return match.group(1).strip() if match else ""


def _guest_count(value: str) -> int | None:
    if not value:
        return None
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None
