from __future__ import annotations

import re
from typing import Any

from .normalize import normalize_phone


# Apply this cleanup only prospectively so older dashboard history is not rewritten.
LINKED_CONTACT_FOLLOWUP_POLICY_START_TS = 1789506000  # 2026-09-16 00:00:00 MSK

_FOLLOWUP_PHRASES = (
    "позвонили ещё раз",
    "позвонили еще раз",
    "дали личный номер",
    "личный номер для связи",
    "номер для связи",
    "другой номер",
    "новый номер",
)


def remove_linked_contact_followup_leads(
    leads: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> int:
    """Remove false leads created from linked MAX contact-detail follow-ups.

    A linked/reply message that only supplies a replacement/additional phone number
    for an existing request is service context, not a new lead. Explicit messages
    beginning with "ЗАЯВКА" are never removed by this rule.
    """
    service_message_ids: set[str] = set()
    service_phones: set[str] = set()

    for event in events:
        if event.get("type") != "max_message_created":
            continue
        if not event.get("has_linked_or_forwarded_message"):
            continue
        if _event_ts(event) < LINKED_CONTACT_FOLLOWUP_POLICY_START_TS:
            continue

        text = str(event.get("text") or "").strip()
        if not text or re.match(r"^\s*заявка\b", text, flags=re.IGNORECASE):
            continue
        if not _looks_like_contact_followup(text):
            continue

        phone = _extract_phone(text)
        if not phone:
            continue

        message_id = str(event.get("message_id") or "").strip()
        if message_id:
            service_message_ids.add(message_id)
        service_phones.add(phone)

    if not service_message_ids and not service_phones:
        return 0

    kept: list[dict[str, Any]] = []
    removed = 0
    for lead in leads:
        lead_message_ids = _lead_message_ids(lead)
        direct_match = bool(lead_message_ids & service_message_ids)

        identifier = lead.get("identifier") or {}
        lead_phone = normalize_phone(str(identifier.get("value") or ""))
        phone_match = bool(lead_phone and lead_phone in service_phones)

        # Message-id matching is authoritative. The conservative phone fallback
        # only applies to empty/minimal MAX rows, which are the false-lead shape
        # produced by this service-message case.
        conservative_fallback = phone_match and _is_empty_max_lead(lead)

        if direct_match or conservative_fallback:
            removed += 1
            continue
        kept.append(lead)

    if removed:
        leads[:] = kept
    return removed


def _looks_like_contact_followup(text: str) -> bool:
    lowered = re.sub(r"\s+", " ", text.casefold().replace("ё", "е"))
    normalized_phrases = tuple(phrase.casefold().replace("ё", "е") for phrase in _FOLLOWUP_PHRASES)
    return any(phrase in lowered for phrase in normalized_phrases)


def _extract_phone(text: str) -> str:
    separator = r"[ \t\u00a0().-]*"
    patterns = (
        rf"(?<!\d)(?:\+7|7|8)(?:{separator}\d){{10}}(?!\d)",
        rf"(?<!\d)9(?:{separator}\d){{9}}(?!\d)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return normalize_phone(match.group(0))
    return ""


def _lead_message_ids(lead: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    if lead.get("message_id"):
        result.add(str(lead["message_id"]))
    max_payload = lead.get("max") or {}
    for message_id in max_payload.get("message_ids") or []:
        if message_id:
            result.add(str(message_id))
    return result


def _is_empty_max_lead(lead: dict[str, Any]) -> bool:
    if str(lead.get("channel") or "").upper() != "MAX":
        return False
    fields = lead.get("fields") or {}
    name = str(lead.get("name") or fields.get("name") or "").strip()
    guests = lead.get("guests") or fields.get("guests_count") or fields.get("guests_raw")
    event_type = str(lead.get("event_type") or fields.get("event_type") or "").strip().casefold()
    event_date = str(fields.get("event_date_raw") or lead.get("event_date") or "").strip()
    return not name and not guests and event_type in {"", "unknown", "не определено"} and not event_date


def _event_ts(event: dict[str, Any]) -> int:
    try:
        raw = int(event.get("timestamp") or 0)
    except (TypeError, ValueError):
        return 0
    if raw > 10_000_000_000:
        raw //= 1000
    return raw
