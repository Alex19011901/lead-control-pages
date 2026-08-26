from __future__ import annotations

import re
from typing import Any

from .event_type import infer_event_type
from .normalize import normalize_phone


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
