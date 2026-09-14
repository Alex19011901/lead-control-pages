from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from .event_type import infer_event_type
from .normalize import MOSCOW_TZ, make_lead_id, normalize_phone, unix_to_moscow_iso
from .parsers.max_leads import IGNORE, NEEDS_REVIEW, classify_max_event
from .processor import _max_fields, _max_timestamp_seconds
from .source_categories import normalize_lead_sources


DUPLICATE_STATUS = "DUPLICATE"


def apply_daily_phone_duplicate_policy(
    leads: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> None:
    """Keep every application visible while excluding same-day phone repeats from lead counts/CRM.

    The legacy rebuild step can merge repeated phone applications before later
    enrichment runs. Re-expand those merged message ids from the persisted raw
    events, then apply the business rule in Moscow calendar time:

    * first application for a phone on a day is a normal lead;
    * every later application for that phone on the same day is a duplicate;
    * the next Moscow calendar day starts a new lead again.

    Duplicates stay in ``leads`` so the dashboard can show them, but are marked
    CRM-free before amoCRM processing starts.
    """
    telegram_events = {
        int(event["message_id"]): event
        for event in events
        if event.get("type") == "telegram_lead" and event.get("message_id") is not None
    }
    max_events = {
        str(event["message_id"]): event
        for event in events
        if event.get("type") == "max_message_created" and event.get("message_id")
    }

    expanded: list[dict[str, Any]] = []
    for lead in leads:
        phone = _lead_phone(lead)
        occurrences = _occurrences(lead, telegram_events, max_events)
        if not phone or len(occurrences) <= 1:
            _clear_duplicate_marker(lead)
            expanded.append(lead)
            continue

        for channel, event in occurrences:
            expanded.append(_clone_for_occurrence(lead, phone, channel, event))

    leads[:] = expanded
    normalize_lead_sources(leads)
    _mark_duplicates(leads)


def _occurrences(
    lead: dict[str, Any],
    telegram_events: dict[int, dict[str, Any]],
    max_events: dict[str, dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    result: list[tuple[str, dict[str, Any]]] = []
    seen: set[tuple[str, str]] = set()

    for message_id in (lead.get("telegram") or {}).get("message_ids") or []:
        try:
            numeric_id = int(message_id)
        except (TypeError, ValueError):
            continue
        event = telegram_events.get(numeric_id)
        key = ("TELEGRAM", str(numeric_id))
        if event and key not in seen:
            seen.add(key)
            result.append(("TELEGRAM", event))

    max_ids = list((lead.get("max") or {}).get("message_ids") or [])
    if lead.get("channel") == "MAX" and lead.get("message_id"):
        max_ids.append(lead.get("message_id"))
    for message_id in max_ids:
        text_id = str(message_id)
        event = max_events.get(text_id)
        key = ("MAX", text_id)
        if event and key not in seen:
            seen.add(key)
            result.append(("MAX", event))

    result.sort(key=lambda item: (_event_ts(item[1], item[0]), str(item[1].get("message_id") or "")))
    return result


def _clone_for_occurrence(
    base: dict[str, Any],
    phone: str,
    channel: str,
    event: dict[str, Any],
) -> dict[str, Any]:
    lead = deepcopy(base)
    message_id = event.get("message_id")
    timestamp = _event_ts(event, channel)
    received_at = _event_iso(event, channel, timestamp)

    lead["id"] = make_lead_id("phone", phone, message_id, timestamp)
    lead["channel"] = channel
    lead["identifier"] = {"type": "phone", "value": phone}
    lead["first_seen_ts"] = timestamp
    lead["first_seen_at"] = received_at
    lead["received_at"] = received_at
    lead["last_seen_ts"] = timestamp
    lead["last_seen_at"] = received_at
    lead["manager_reaction"] = None
    lead.pop("crm_feedback", None)
    _clear_duplicate_marker(lead)

    if channel == "TELEGRAM":
        event_fields = dict(event.get("lead") or {})
        if event_fields:
            lead["fields"] = event_fields
            lead["source"] = event_fields.get("source") or event.get("source") or lead.get("source")
            lead["name"] = event_fields.get("name") or ""
            lead["phone"] = event_fields.get("phone_raw") or phone
            lead["event_date"] = event_fields.get("event_date") or ""
            lead["guests"] = event_fields.get("guests_count")
            lead["guests_raw"] = event_fields.get("guests_raw") or ""
            lead["event_type"] = event_fields.get("event_type") or infer_event_type(event_fields.get("description")) or ""
        lead["telegram"] = {
            "chat_id": event.get("chat_id"),
            "message_ids": [int(message_id)],
            "update_ids": [int(event["update_id"])] if event.get("update_id") is not None else [],
        }
        lead.pop("max", None)
        lead.pop("message_id", None)
        lead["crm_required"] = True
    else:
        classification = classify_max_event(event)
        if classification.get("classification") not in {IGNORE, NEEDS_REVIEW}:
            fields = _max_fields(classification, timestamp)
            lead["fields"] = fields
            lead["source"] = (
                classification.get("business_source")
                or classification.get("display_name")
                or classification.get("classification")
                or lead.get("source")
            )
            lead["category"] = classification.get("classification") or lead.get("category")
            lead["name"] = fields.get("name") or ""
            lead["phone"] = fields.get("phone_raw") or phone
            lead["event_date"] = fields.get("event_date") or ""
            lead["guests"] = fields.get("guests_count")
            lead["guests_raw"] = fields.get("guests_raw") or ""
            lead["guests_min"] = fields.get("guests_min")
            lead["guests_max"] = fields.get("guests_max")
            lead["event_type"] = fields.get("event_type") or infer_event_type(event.get("text")) or ""
            lead["crm_required"] = bool(classification.get("crm_check_required"))
        lead["message_id"] = str(message_id)
        lead["max"] = {
            "chat_id": event.get("chat_id"),
            "message_ids": [str(message_id)],
            "sender_user_id": event.get("sender_user_id"),
            "sender_username": event.get("sender_username"),
            "sender_name": event.get("sender_name"),
        }
        lead.pop("telegram", None)

    lead["crm"] = {"found": False, "required": bool(lead.get("crm_required", True))}
    lead["crm_found"] = False
    lead["crm_created_at"] = None
    lead["crm_responsible"] = None
    lead.pop("crm_check_status", None)
    lead["violations"] = []
    lead["status"] = "PENDING" if lead.get("crm_required", True) else "OK"
    return lead


def _mark_duplicates(leads: list[dict[str, Any]]) -> None:
    first_by_day_phone: dict[tuple[str, str], dict[str, Any]] = {}
    for lead in sorted(leads, key=lambda item: (_lead_ts(item), str(item.get("id") or ""))):
        _clear_duplicate_marker(lead)
        phone = _lead_phone(lead)
        day = _lead_day(lead)
        if not phone or not day:
            continue
        key = (day, phone)
        primary = first_by_day_phone.get(key)
        if primary is None:
            first_by_day_phone[key] = lead
            continue
        _set_duplicate(lead, primary)


def _set_duplicate(lead: dict[str, Any], primary: dict[str, Any]) -> None:
    lead["is_duplicate"] = True
    lead["duplicate_of"] = primary.get("id")
    lead["crm_required"] = False
    lead["crm_check_status"] = "NOT_REQUIRED"
    lead["crm"] = {"found": False, "required": False, "check_status": "NOT_REQUIRED"}
    lead["crm_found"] = False
    lead["crm_created_at"] = None
    lead["crm_responsible"] = None
    lead.pop("crm_feedback", None)
    lead["status"] = DUPLICATE_STATUS
    lead["violations"] = []


def _clear_duplicate_marker(lead: dict[str, Any]) -> None:
    if not lead.get("is_duplicate") and lead.get("status") != DUPLICATE_STATUS:
        return
    lead.pop("is_duplicate", None)
    lead.pop("duplicate_of", None)
    if lead.get("status") == DUPLICATE_STATUS:
        lead["status"] = "PENDING" if lead.get("crm_required", True) else "OK"


def _lead_phone(lead: dict[str, Any]) -> str:
    identifier = lead.get("identifier") or {}
    fields = lead.get("fields") or {}
    return normalize_phone(
        identifier.get("value") if identifier.get("type") == "phone" else None
        or lead.get("phone")
        or fields.get("phone_digits")
        or fields.get("phone_raw")
    )


def _lead_ts(lead: dict[str, Any]) -> int:
    try:
        return int(lead.get("first_seen_ts") or 0)
    except (TypeError, ValueError):
        return 0


def _lead_day(lead: dict[str, Any]) -> str:
    timestamp = _lead_ts(lead)
    if timestamp > 0:
        return datetime.fromtimestamp(timestamp, tz=MOSCOW_TZ).date().isoformat()
    for key in ("received_at", "first_seen_at"):
        value = str(lead.get(key) or "")
        if len(value) >= 10:
            return value[:10]
    return ""


def _event_ts(event: dict[str, Any], channel: str) -> int:
    if channel == "TELEGRAM":
        return int(event.get("telegram_date") or 0)
    return _max_timestamp_seconds(event)


def _event_iso(event: dict[str, Any], channel: str, timestamp: int) -> str:
    if channel == "TELEGRAM":
        value = str(event.get("telegram_date_msk") or "")
        if value:
            return value
    return unix_to_moscow_iso(timestamp)
