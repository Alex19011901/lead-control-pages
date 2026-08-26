from __future__ import annotations

import re
from typing import Any

from .event_type import infer_event_type
from .normalize import normalize_phone, normalize_username

MAIL_LEAD = "ЗАЯВКА ПОЧТА"
HEADER_RE = re.compile(r"^\s*заявка\s+сайт\s*:\s*$", re.IGNORECASE)

_RUSSIAN_MONTHS = (
    "январ(?:ь|я|е)",
    "феврал(?:ь|я|е)",
    "март(?:а|е)?",
    "апрел(?:ь|я|е)",
    "ма[йяе]",
    "июн(?:ь|я|е)",
    "июл(?:ь|я|е)",
    "август(?:а|е)?",
    "сентябр(?:ь|я|е)",
    "октябр(?:ь|я|е)",
    "ноябр(?:ь|я|е)",
    "декабр(?:ь|я|е)",
)


def classify_max_mail_event(event: dict[str, Any]) -> dict[str, Any] | None:
    text = str(event.get("text") or "")
    if not HEADER_RE.match(text):
        return None
    if not _has_image(event):
        return None

    attachment_text = str(
        event.get("attachment_ocr_text")
        or event.get("attachment_text")
        or ""
    ).strip()
    fields = parse_attachment_fields(attachment_text)
    has_identifier = bool(fields.get("phone_digits") or fields.get("telegram_username"))
    return {
        "classification": MAIL_LEAD,
        "display_name": MAIL_LEAD,
        "business_source": MAIL_LEAD,
        "is_lead": True,
        "crm_check_required": has_identifier,
        "review_reason": "",
        "source": "MAX",
        "chat_id": event.get("chat_id"),
        "message_id": event.get("message_id"),
        "sender_user_id": event.get("sender_user_id"),
        "sender_username": event.get("sender_username"),
        "sender_name": event.get("sender_name"),
        "timestamp": event.get("timestamp"),
        "text": text,
        "fields": {
            **fields,
            "description": attachment_text,
            "attachment_ocr_text": attachment_text,
            "attachment_message_id": event.get("attachment_message_id") or event.get("message_id"),
        },
    }


def parse_attachment_fields(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    phone_raw = _extract_phone(raw)
    username = _extract_username(raw)
    event_date_raw = (
        _extract_labeled_value(raw, ("дата мероприятия", "дата события", "дата", "event date"))
        or _extract_named_event_date(raw)
        or _extract_date(raw)
        or _extract_month_period(raw)
    )
    guests_raw = (
        _extract_labeled_value(
            raw,
            ("количество гостей", "количество персон", "кол-во гостей", "гостей", "персон", "guests"),
        )
        or _extract_guest_phrase(raw)
    )
    guests_count, guests_min, guests_max = _parse_guests(guests_raw)
    name = (
        _extract_labeled_value(raw, ("имя", "фио", "name", "клиент"))
        or _extract_signature_name(raw)
    )
    email = _extract_email(raw)
    event_type = infer_event_type(raw)

    result: dict[str, Any] = {
        "name": name,
        "phone_raw": phone_raw,
        "phone_digits": normalize_phone(phone_raw),
        "telegram_username": normalize_username(username),
        "event_date_raw": event_date_raw,
        "guests_count": guests_count,
        "guests_raw": guests_raw,
        "guests_min": guests_min,
        "guests_max": guests_max,
        "event_type": event_type,
    }
    if email:
        result["email"] = email
    return result


def _has_image(event: dict[str, Any]) -> bool:
    types = {str(item).strip().lower() for item in (event.get("attachment_types") or [])}
    if types & {"image", "photo"}:
        return True
    for attachment in event.get("attachments") or []:
        if str((attachment or {}).get("type") or "").strip().lower() in {"image", "photo"}:
            return True
    return bool(event.get("attachment_message_id"))


def _extract_labeled_value(text: str, labels: tuple[str, ...]) -> str:
    for line in text.splitlines():
        for label in labels:
            match = re.match(
                rf"^\s*{re.escape(label)}\s*[:=\-]\s*(.+?)\s*$",
                line,
                flags=re.IGNORECASE,
            )
            if match:
                return match.group(1).strip()
    return ""


def _extract_phone(text: str) -> str:
    match = re.search(
        r"(?:\+?7|8)[\s()\-]*\d{3}[\s()\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}",
        text,
    )
    return match.group(0) if match else ""


def _extract_username(text: str) -> str:
    match = re.search(r"(?<![\w.])@([A-Za-z0-9_]{4,})", text)
    return match.group(1) if match else ""


def _extract_email(text: str) -> str:
    match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, flags=re.IGNORECASE)
    return match.group(0) if match else ""


def _extract_named_event_date(text: str) -> str:
    month_pattern = "|".join(_RUSSIAN_MONTHS)
    match = re.search(
        rf"\bдата\s*[:=\-]?\s*(\d{{1,2}})\s+({month_pattern})\b",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    return f"{match.group(1)} {match.group(2)}"


def _extract_date(text: str) -> str:
    for match in re.finditer(r"\b(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\b", text):
        day = int(match.group(1))
        month = int(match.group(2))
        if 1 <= day <= 31 and 1 <= month <= 12:
            return match.group(0)
    return ""


def _extract_month_period(text: str) -> str:
    pattern = rf"\b(?:в|на)\s+(?:{'|'.join(_RUSSIAN_MONTHS)})\b"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return match.group(0) if match else ""


def _extract_guest_phrase(text: str) -> str:
    patterns = (
        r"\bдо\s+\d{1,4}\s*(?:чел\.?|человек|гост(?:ей|я|и)?|персон(?:ы)?)\b",
        r"\b\d{1,4}\s*[-–—]\s*\d{1,4}\s*(?:чел\.?|человек|гост(?:ей|я|и)?|персон(?:ы)?)\b",
        r"\b\d{1,4}\s*(?:чел\.?|человек|гост(?:ей|я|и)?|персон(?:ы)?)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return ""


def _extract_signature_name(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    role_pattern = re.compile(
        r"\b(?:руководител|директор|менеджер|координатор|начальник|продюсер|организатор)\w*\b",
        flags=re.IGNORECASE,
    )
    for index, line in enumerate(lines):
        if not role_pattern.search(line):
            continue
        for offset in (1, 2):
            candidate_index = index - offset
            if candidate_index < 0:
                continue
            candidate = _clean_person_name(lines[candidate_index])
            if candidate:
                return candidate

    for line in reversed(lines):
        candidate = _clean_person_name(line)
        if candidate:
            return candidate
    return ""


def _clean_person_name(value: str) -> str:
    text = re.sub(r"[^А-Яа-яЁё\-\s]", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if not re.fullmatch(r"[А-ЯЁ][а-яё-]{1,30}\s+[А-ЯЁ][а-яё-]{1,30}", text):
        return ""
    lowered = text.casefold()
    blocked = (
        "проведение мероприятия",
        "издательский дом",
        "добрый день",
        "малый зал",
        "большой зал",
    )
    if any(fragment in lowered for fragment in blocked):
        return ""
    return text


def _parse_guests(text: str) -> tuple[int | None, int | None, int | None]:
    raw = str(text or "").strip()
    if not raw:
        return None, None, None

    match = re.search(r"\b(\d{1,4})\s*[-–—]\s*(\d{1,4})\b", raw)
    if match:
        low, high = int(match.group(1)), int(match.group(2))
        return low, low, high

    match = re.search(r"\bдо\s*(\d{1,4})\b", raw, flags=re.IGNORECASE)
    if match:
        value = int(match.group(1))
        return value, None, value

    match = re.search(r"\b(\d{1,4})\b", raw)
    if match:
        value = int(match.group(1))
        return value, None, None
    return None, None, None
