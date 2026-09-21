from __future__ import annotations

import re
from typing import Any


_GUEST_FIELD_LABELS = {
    "количество гостей",
    "кол-во гостей",
    "кол во гостей",
    "количество персон",
    "кол-во персон",
    "кол во персон",
}


def _field_values(field: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for item in field.get("values") or []:
        value = item.get("value") if isinstance(item, dict) else item
        if isinstance(value, dict):
            value = value.get("value") or value.get("name") or value.get("text")
        text = str(value or "").strip()
        if text:
            result.append(text)
    return result


def _normalize_guest_value(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"\s+", " ", text)
    match = re.search(r"(?P<v>(?:до\s*)?\d{1,4}(?:\s*[-–—]\s*\d{1,4})?\+?)", text, flags=re.IGNORECASE)
    if not match:
        return None
    value_text = match.group("v")
    value_text = re.sub(r"\s*[-–—]\s*", "-", value_text)
    value_text = re.sub(r"\s+", " ", value_text).strip()
    return value_text


def extract_crm_guest_value(entity: dict[str, Any]) -> str | None:
    """Read guest count from the matched amoCRM deal card.

    Source parsing remains the fallback. This function only returns a value
    when amoCRM has an explicit guest-count/person-count field.
    """
    for field in entity.get("custom_fields_values") or []:
        field_name = str(field.get("field_name") or "").strip().casefold().replace("ё", "е")
        normalized_name = re.sub(r"[._]+", " ", field_name)
        normalized_name = re.sub(r"\s+", " ", normalized_name).strip()
        is_guest_field = normalized_name in _GUEST_FIELD_LABELS or (
            ("гост" in normalized_name or "персон" in normalized_name)
            and ("кол" in normalized_name or normalized_name in {"гости", "гостей", "персоны"})
        )
        if not is_guest_field:
            continue
        for raw_value in _field_values(field):
            guest_value = _normalize_guest_value(raw_value)
            if guest_value:
                return guest_value
    return None
