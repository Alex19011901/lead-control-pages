from __future__ import annotations

import re
from typing import Any

from .event_type import infer_event_type
from .normalize import THREE_DAYS_SECONDS, normalize_phone


_SERVICE_NAME_FRAGMENTS = (
    "ждут инф",
    "ждет инф",
    "ждёт инф",
    "ждем инф",
    "ждём инф",
    "ожидает инф",
    "ожидают инф",
    "ждут информацию",
    "ждет информацию",
    "ждёт информацию",
)


def enrich_leads_from_events(leads: list[dict[str, Any]], events: list[dict[str, Any]]) -> None:
    """Repair semantic lead fields from the original MAX message when needed.

    The original event text is the source of truth for semantic fields that a
    source-specific parser may have missed. In particular, event type must be
    inferred from phrases such as "Планируем свадьбу", not only from a
    dedicated event-type field.
    """
    max_events_by_message_id = {
        str(event.get("message_id")): event
        for event in events
        if event.get("type") == "max_message_created" and event.get("message_id")
    }

    for lead in leads:
        if str(lead.get("channel") or "").upper() != "MAX":
            continue

        fields = lead.setdefault("fields", {})
        message_ids = list((lead.get("max") or {}).get("message_ids") or [])
        if lead.get("message_id"):
            message_ids.append(lead.get("message_id"))

        current_event_type = str(lead.get("event_type") or fields.get("event_type") or "").strip()
        if not current_event_type:
            for message_id in message_ids:
                event = max_events_by_message_id.get(str(message_id))
                if not event:
                    continue
                inferred_event_type = infer_event_type(str(event.get("text") or ""))
                if not inferred_event_type:
                    continue
                fields["event_type"] = inferred_event_type
                lead["event_type"] = inferred_event_type
                lead["event_type_source"] = "MESSAGE"
                break

        if str(lead.get("source") or "") != "С улицы":
            continue

        current_name = str(lead.get("name") or fields.get("name") or "").strip()
        if current_name and not _looks_like_service_note(current_name):
            continue

        identifier = lead.get("identifier") or {}
        phone_digits = normalize_phone(
            identifier.get("value")
            or lead.get("phone")
            or fields.get("phone_digits")
            or fields.get("phone_raw")
        )
        if not phone_digits:
            continue

        for message_id in message_ids:
            event = max_events_by_message_id.get(str(message_id))
            if not event:
                continue
            name = _extract_name_from_original_text(str(event.get("text") or ""), phone_digits)
            if not name:
                continue
            fields["name"] = name
            lead["name"] = name
            lead["name_source"] = "MESSAGE"
            break

    _dedupe_same_phone_leads(leads)


def _dedupe_same_phone_leads(leads: list[dict[str, Any]]) -> None:
    """Collapse repeated leads with the same normalized phone within the duplicate window.

    Source and channel do not create a second lead when the phone is the same.
    The earliest lead remains canonical and later message references/fields are
    merged into it.
    """
    canonical_by_phone: dict[str, list[dict[str, Any]]] = {}
    duplicate_object_ids: set[int] = set()

    ordered = sorted(leads, key=_first_seen_ts)
    for lead in ordered:
        phone_digits = _lead_phone_digits(lead)
        created_at = _first_seen_ts(lead)
        if not phone_digits or created_at <= 0:
            continue

        canonical = None
        for candidate in reversed(canonical_by_phone.get(phone_digits, [])):
            candidate_created_at = _first_seen_ts(candidate)
            if candidate_created_at <= 0:
                continue
            if created_at - candidate_created_at <= THREE_DAYS_SECONDS:
                canonical = candidate
                break

        if canonical is None:
            canonical_by_phone.setdefault(phone_digits, []).append(lead)
            continue

        _merge_duplicate_lead(canonical, lead)
        duplicate_object_ids.add(id(lead))

    if duplicate_object_ids:
        leads[:] = [lead for lead in leads if id(lead) not in duplicate_object_ids]


def _lead_phone_digits(lead: dict[str, Any]) -> str:
    identifier = lead.get("identifier") or {}
    fields = lead.get("fields") or {}
    return normalize_phone(
        identifier.get("value") if identifier.get("type") == "phone" else None
        or lead.get("phone")
        or fields.get("phone_digits")
        or fields.get("phone_raw")
    )


def _first_seen_ts(lead: dict[str, Any]) -> int:
    try:
        return int(lead.get("first_seen_ts") or 0)
    except (TypeError, ValueError):
        return 0


def _merge_duplicate_lead(primary: dict[str, Any], duplicate: dict[str, Any]) -> None:
    primary_fields = primary.setdefault("fields", {})
    duplicate_fields = duplicate.get("fields") or {}
    _merge_missing_values(primary_fields, duplicate_fields)

    for key in (
        "event_date",
        "guests",
        "guests_raw",
        "guests_min",
        "guests_max",
        "name",
        "phone",
        "username",
        "event_type",
        "event_type_source",
        "name_source",
    ):
        if primary.get(key) in ("", None) and duplicate.get(key) not in ("", None):
            primary[key] = duplicate.get(key)

    duplicate_last_seen_ts = _safe_int(duplicate.get("last_seen_ts"))
    primary_last_seen_ts = _safe_int(primary.get("last_seen_ts"))
    if duplicate_last_seen_ts > primary_last_seen_ts:
        primary["last_seen_ts"] = duplicate_last_seen_ts
        if duplicate.get("last_seen_at"):
            primary["last_seen_at"] = duplicate.get("last_seen_at")

    if duplicate.get("crm_required") is True:
        primary["crm_required"] = True

    primary_reaction = primary.get("manager_reaction") or {}
    duplicate_reaction = duplicate.get("manager_reaction") or {}
    if duplicate_reaction and _safe_int(duplicate_reaction.get("reacted_ts")) > _safe_int(primary_reaction.get("reacted_ts")):
        primary["manager_reaction"] = duplicate.get("manager_reaction")

    if not primary.get("manual_review") and duplicate.get("manual_review"):
        primary["manual_review"] = duplicate.get("manual_review")

    _merge_channel_payload(primary, duplicate, "max", ("message_ids",))
    _merge_channel_payload(primary, duplicate, "telegram", ("message_ids", "update_ids"))


def _merge_channel_payload(
    primary: dict[str, Any],
    duplicate: dict[str, Any],
    key: str,
    list_keys: tuple[str, ...],
) -> None:
    duplicate_payload = duplicate.get(key) or {}
    if not duplicate_payload:
        return

    primary_payload = primary.setdefault(key, {})
    _merge_missing_values(primary_payload, duplicate_payload, skip_keys=set(list_keys))
    for list_key in list_keys:
        current = primary_payload.setdefault(list_key, [])
        for value in duplicate_payload.get(list_key) or []:
            if value not in current:
                current.append(value)


def _merge_missing_values(
    current: dict[str, Any],
    incoming: dict[str, Any],
    skip_keys: set[str] | None = None,
) -> None:
    skip_keys = skip_keys or set()
    for key, value in incoming.items():
        if key in skip_keys:
            continue
        if current.get(key) in ("", None) and value not in ("", None):
            current[key] = value


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _extract_name_from_original_text(text: str, phone_digits: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        for match in re.finditer(r"\+?\d[\d\s().-]{8,}\d", line):
            if normalize_phone(match.group(0)) != phone_digits:
                continue

            same_line = _clean_name_candidate(line[match.end() :])
            if same_line:
                return same_line

            for candidate in lines[index + 1 : index + 3]:
                cleaned = _clean_name_candidate(candidate)
                if cleaned:
                    return cleaned
    return ""


def _clean_name_candidate(value: str) -> str:
    text = value.strip(" .,:;-—")
    if not text:
        return ""

    text = re.split(
        r"\b(?:ждут|ждет|ждёт|ждем|ждём|ожидает|ожидают)\b",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" .,:;-—")
    if not text or _looks_like_service_note(text) or re.search(r"\d", text):
        return ""

    match = re.match(r"^[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё-]*(?:\s+[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё-]*)?", text)
    return match.group(0).strip() if match else ""


def _looks_like_service_note(value: str) -> bool:
    lowered = str(value or "").strip().casefold().replace("ё", "е")
    return any(fragment.replace("ё", "е") in lowered for fragment in _SERVICE_NAME_FRAGMENTS)
