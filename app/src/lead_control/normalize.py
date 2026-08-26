from __future__ import annotations

import hashlib
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


MOSCOW_TZ = ZoneInfo("Europe/Moscow")
THREE_DAYS_SECONDS = 3 * 24 * 60 * 60


def normalize_phone(value: str | None) -> str:
    if not value:
        return ""
    digits = re.sub(r"\D+", "", value)
    # A MAX free-form parser may inspect a broad numeric span. Never allow a
    # calendar date plus adjacent numeric metadata (for example guests) to be
    # normalized into a plausible 10/11-digit phone number.
    if len(digits) >= 10 and re.search(r"(?<!\d)\d{1,2}[./-]\d{1,2}[./-]\d{2,4}(?!\d)", value):
        return ""
    if len(digits) == 11 and digits.startswith("8"):
        return f"7{digits[1:]}"
    return digits


def normalize_username(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lstrip("@").lower()


def parse_event_date(value: str | None) -> str:
    if not value:
        return ""
    text = value.strip()
    for fmt in ("%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def unix_to_moscow_iso(timestamp: int | None) -> str:
    if timestamp is None:
        return ""
    return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).astimezone(MOSCOW_TZ).isoformat()


def now_moscow_iso() -> str:
    return datetime.now(MOSCOW_TZ).replace(microsecond=0).isoformat()


def moscow_day_deadline_ts(source_timestamp: int) -> int:
    lead_dt = datetime.fromtimestamp(int(source_timestamp), tz=timezone.utc).astimezone(MOSCOW_TZ)
    if lead_dt.time() >= time(20, 0, 0):
        deadline_day = lead_dt.date() + timedelta(days=1)
        deadline_time = time(16, 0, 0)
    else:
        deadline_day = lead_dt.date()
        deadline_time = time(23, 59, 59)
    deadline_dt = datetime.combine(deadline_day, deadline_time, tzinfo=MOSCOW_TZ)
    return int(deadline_dt.timestamp())


def make_lead_id(identifier_type: str, identifier_value: str, message_id: int, created_at: int) -> str:
    source = f"{identifier_type}:{identifier_value}:{message_id}:{created_at}"
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]


def mask_identifier(identifier_type: str, value: str) -> str:
    if not value:
        return ""
    if identifier_type == "phone":
        if len(value) <= 4:
            return "*" * len(value)
        return f"{value[:1]}{'*' * max(0, len(value) - 3)}{value[-2:]}"
    if identifier_type == "telegram_username":
        return f"@{value}"
    return value


def guest_bucket(guests_count: int | None) -> str:
    if guests_count is None:
        return "unknown"
    if guests_count <= 20:
        return "1-20"
    if guests_count <= 50:
        return "21-50"
    if guests_count <= 100:
        return "51-100"
    if guests_count <= 150:
        return "101-150"
    return "151+"
