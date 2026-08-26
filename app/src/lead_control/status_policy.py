from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any

from .normalize import MOSCOW_TZ


NO_CRM_STATUS = "-"
EVENING_CUTOFF = time(20, 0, 0)
EVENING_NEXT_DAY_DEADLINE = time(16, 0, 0)
SAME_DAY_DEADLINE = time(23, 59, 59)


def apply_crm_day_status_policy(
    leads: list[dict[str, Any]],
    now_ts: int | None = None,
) -> None:
    """Apply one CRM-only status policy to Telegram and MAX leads.

    Reactions are intentionally ignored. Leads received before 20:00 Moscow
    have until 23:59:59 of the same Moscow calendar day to be entered into CRM.
    Leads received at or after 20:00 Moscow have until 16:00:00 of the next
    Moscow calendar day.

    If amoCRM contains an event type, that value has priority over the event
    type inferred from the original request. Other request fields, including
    the exact guest count, are not overwritten here.

    Leads for which CRM verification is intentionally disabled, or impossible
    because there is no reliable CRM identifier, must never be shown as
    successfully entered or waiting for CRM. Their dashboard status is a
    neutral dash.
    """
    now_dt = (
        datetime.now(MOSCOW_TZ)
        if now_ts is None
        else datetime.fromtimestamp(int(now_ts), tz=timezone.utc).astimezone(MOSCOW_TZ)
    )

    for lead in leads:
        _apply_crm_event_priority(lead)

        if lead.get("crm_required") is False:
            _set_status(lead, NO_CRM_STATUS)
            continue

        if lead.get("crm_check_status") == "NO_IDENTIFIER":
            _set_status(lead, NO_CRM_STATUS)
            continue

        deadline = _crm_entry_deadline(lead)
        crm = lead.get("crm") or {}
        crm_found = bool(crm.get("found"))

        if crm_found:
            created_at = crm.get("created_at")
            if not created_at or deadline is None:
                _set_status(lead, "OK")
                continue

            crm_created_dt = datetime.fromtimestamp(
                int(created_at), tz=timezone.utc
            ).astimezone(MOSCOW_TZ)
            if crm_created_dt <= deadline:
                _set_status(lead, "OK")
            else:
                _set_status(lead, "LATE_CRM")
            continue

        if deadline is not None and now_dt > deadline:
            _set_status(lead, "ALARM_NO_CRM")
        else:
            _set_status(lead, "PENDING")


def _apply_crm_event_priority(lead: dict[str, Any]) -> None:
    crm = lead.get("crm") or {}
    if not crm.get("found"):
        return

    crm_event_type = str(crm.get("event_type") or "").strip()
    if not crm_event_type:
        return

    fields = lead.setdefault("fields", {})
    fields["event_type"] = crm_event_type
    lead["event_type"] = crm_event_type
    lead["event_type_source"] = "CRM"


def _lead_received_at(lead: dict[str, Any]) -> datetime | None:
    first_seen_ts = lead.get("first_seen_ts")
    if first_seen_ts is not None:
        return datetime.fromtimestamp(
            int(first_seen_ts), tz=timezone.utc
        ).astimezone(MOSCOW_TZ)

    received_at = str(lead.get("received_at") or lead.get("first_seen_at") or "")
    if not received_at:
        return None
    try:
        parsed = datetime.fromisoformat(received_at)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MOSCOW_TZ)
    return parsed.astimezone(MOSCOW_TZ)


def _crm_entry_deadline(lead: dict[str, Any]) -> datetime | None:
    received_at = _lead_received_at(lead)
    if received_at is None:
        return None

    received_time = received_at.timetz().replace(tzinfo=None)
    if received_time >= EVENING_CUTOFF:
        deadline_day = received_at.date() + timedelta(days=1)
        deadline_time = EVENING_NEXT_DAY_DEADLINE
    else:
        deadline_day = received_at.date()
        deadline_time = SAME_DAY_DEADLINE

    return datetime.combine(deadline_day, deadline_time, tzinfo=MOSCOW_TZ)


def _lead_day(lead: dict[str, Any]):
    received_at = _lead_received_at(lead)
    return received_at.date() if received_at is not None else None


def _moscow_day(timestamp: int):
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(MOSCOW_TZ).date()


def _set_status(lead: dict[str, Any], status: str) -> None:
    lead["status"] = status
    if status == "LATE_CRM":
        lead["violations"] = ["LATE_CRM"]
    elif status == "ALARM_NO_CRM":
        lead["violations"] = ["ALARM_NO_CRM"]
    else:
        lead["violations"] = []
