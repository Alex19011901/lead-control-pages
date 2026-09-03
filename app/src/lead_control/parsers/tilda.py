from __future__ import annotations

import re
from typing import Any

from ..event_type import infer_event_type, normalize_event_type
from ..normalize import normalize_phone, normalize_username, parse_event_date


SOURCE = "САЙТ ТИЛЬДА"

FIELD_ALIASES = {
    "name": {"name", "имя", "ваше имя"},
    "phone": {"phone", "телефон", "номер телефона"},
    "event_date": {"дата мероприятия", "event date", "date", "дата"},
    "guests_count": {
        "количество гостей",
        "кол-во гостей",
        "кол-во_гостей",
        "количество_гостей",
        "количество персон",
        "количество_персон",
        "гостей",
        "guests",
        "input",
    },
    "event_type": {"тип мероприятия", "формат мероприятия", "event type"},
    "yclid": {"yclid"},
}

WORD_NUMBERS = {
    "один": 1,
    "два": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "семь": 7,
    "восемь": 8,
    "девять": 9,
    "десять": 10,
}

TEST_PHONES = {"79999999999"}
TEST_PHRASES = {"TEST LEAD CONTROL", "ТЕСТ РЕАКЦИИ"}


def parse_tilda_message(message: dict[str, Any]) -> dict[str, Any] | None:
    text = message.get("text") or message.get("caption") or ""
    if not _looks_like_tilda(message, text):
        return None

    fields = _parse_key_value_fields(text)
    phone_raw = fields.get("phone") or _extract_phone(text)
    phone_digits = normalize_phone(phone_raw)
    username = normalize_username(fields.get("telegram_username") or _extract_username(text))
    explicit_event_type = normalize_event_type(fields.get("event_type", ""))
    event_type = explicit_event_type or infer_event_type(text)

    lead = {
        "source": SOURCE,
        "name": fields.get("name", ""),
        "phone_raw": phone_raw,
        "phone_digits": phone_digits,
        "telegram_username": username,
        "event_date_raw": fields.get("event_date", ""),
        "event_date": parse_event_date(fields.get("event_date")),
        "guests_count": _parse_int(fields.get("guests_count")),
        "event_type": event_type,
        "yclid": fields.get("yclid", ""),
        "description": str(text).strip(),
    }
    reason = test_lead_reason(lead, text)
    if reason:
        lead["ignored_reason"] = reason
    return lead


def test_lead_reason(lead: dict[str, Any], text: str) -> str:
    if lead.get("phone_digits") in TEST_PHONES:
        return "test_phone"

    upper_lines = {line.strip().upper() for line in text.splitlines() if line.strip()}
    if "TEST" in upper_lines or "ТЕСТ" in upper_lines:
        return "test_marker"

    upper_text = text.upper()
    for phrase in TEST_PHRASES:
        if phrase in upper_text:
            return "test_phrase"

    return ""


def _looks_like_tilda(message: dict[str, Any], text: str) -> bool:
    sender = message.get("from") or {}
    sender_values = {
        str(sender.get("username") or "").strip().lower(),
        str(sender.get("first_name") or "").strip().lower(),
        str(sender.get("last_name") or "").strip().lower(),
    }
    if sender_values & {"tildaforms", "tildaformsbot", "tildaforms_bot"}:
        return True

    lowered = text.lower()
    return "tildaforms" in lowered or "tilda forms" in lowered


def _parse_key_value_fields(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*([^:=]{2,80})\s*[:=]\s*(.+?)\s*$", line)
        if not match:
            continue
        label = _normalize_label(match.group(1))
        value = match.group(2).strip()
        for field_name, aliases in FIELD_ALIASES.items():
            if label not in aliases:
                continue

            if field_name == "name" and "name" in result:
                word_number = WORD_NUMBERS.get(value.casefold())
                if word_number is not None and "guests_count" not in result:
                    result["guests_count"] = str(word_number)
                break

            if field_name not in result:
                result[field_name] = value
            break
    return result


def _normalize_label(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _extract_phone(text: str) -> str:
    match = re.search(r"(\+?\d[\d\s().-]{8,}\d)", text)
    return match.group(1).strip() if match else ""


def _extract_username(text: str) -> str:
    match = re.search(r"@([A-Za-z0-9_]{3,})", text)
    return match.group(1) if match else ""


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d+", value)
    if not match:
        return None
    return int(match.group(0))
