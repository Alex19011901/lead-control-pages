from __future__ import annotations

import logging
import time
from datetime import datetime, time as datetime_time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .amocrm_client import AmoCRMClient


LOG = logging.getLogger(__name__)

FEEDBACK_RED_DAY = 5
FEEDBACK_RULE_VERSION = 4
CLOSED_NOT_REALIZED_STATUS_ID = 143
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def _status_key(value: object) -> str:
    return str(value or "").strip().casefold().replace("ё", "е")


def _moscow_date(ts: int):
    return datetime.fromtimestamp(int(ts), MOSCOW_TZ).date()


def _calendar_day_number(now_ts: int, created_at: int) -> int:
    """Return the Moscow calendar day number, with creation date as day 1."""
    return max(1, (_moscow_date(now_ts) - _moscow_date(created_at)).days + 1)


def _feedback_deadline_ts(created_at: int) -> int:
    """Start of day 5 in Moscow time."""
    deadline_date = _moscow_date(created_at) + timedelta(days=FEEDBACK_RED_DAY - 1)
    deadline_dt = datetime.combine(deadline_date, datetime_time.min, tzinfo=MOSCOW_TZ)
    return int(deadline_dt.timestamp())


def _is_later_calendar_date(event_ts: int, created_at: int) -> bool:
    """True only when the history event is on a later Moscow calendar date."""
    return _moscow_date(event_ts) > _moscow_date(created_at)


def _is_feedback_excluded_status(status_id: object, status_name: object) -> bool:
    try:
        if int(status_id or 0) in {142, CLOSED_NOT_REALIZED_STATUS_ID}:
            return True
    except (TypeError, ValueError):
        pass
    return _status_key(status_name) in {
        "закрыто и не реализовано",
        "закрыто и не реализованно",
        "согласование договора",
        "внесена п/о идет текущая работа",
        "успешно реализовано",
    }


def _status_name(
    client: AmoCRMClient,
    pipeline_id: object,
    status_id: object,
    cache: dict[tuple[int, int], str],
) -> str:
    try:
        pipeline = int(pipeline_id or 0)
        status = int(status_id or 0)
    except (TypeError, ValueError):
        return ""
    if not pipeline or not status:
        return ""
    if status == 142:
        return "Успешно реализовано"
    if status == 143:
        return "Закрыто и не реализовано"
    key = (pipeline, status)
    if key in cache:
        return cache[key]
    try:
        payload = client._request_json(
            f"/api/v4/leads/pipelines/{pipeline}/statuses/{status}",
            {},
        )
        name = str(payload.get("name") or "").strip()
    except RuntimeError as exc:
        LOG.warning(
            "CRM status lookup failed pipeline_id=%s status_id=%s error=%s",
            pipeline,
            status,
            exc,
        )
        name = ""
    cache[key] = name
    return name


def _first_manager_comment_after_creation(
    client: AmoCRMClient,
    crm_lead_id: int,
    created_at: int,
    responsible_user_id: int,
) -> int | None:
    """Return the first manager-authored text note on a later calendar date.

    Feedback counts only from a real amoCRM lead note with note_type "common"
    whose created_by equals the lead's current responsible manager. Comments
    from other users and all field/status/system timeline events are ignored.
    Same-day comments remain part of the creation-day block.
    """
    if crm_lead_id == 47523505:
        diagnostic_notes = client._request_json(
            "/api/v4/leads/notes",
            {
                "filter[entity_id][0]": crm_lead_id,
                "limit": 250,
                "page": 1,
            },
        )
        note_rows = list(((diagnostic_notes.get("_embedded") or {}).get("notes")) or [])
        LOG.info(
            "CRM feedback diagnostic notes lead_id=%s responsible_user_id=%s rows=%s",
            crm_lead_id,
            responsible_user_id,
            [
                {
                    "id": row.get("id"),
                    "entity_id": row.get("entity_id"),
                    "created_by": row.get("created_by"),
                    "created_at": row.get("created_at"),
                    "note_type": row.get("note_type"),
                    "responsible_user_id": row.get("responsible_user_id"),
                }
                for row in note_rows
            ],
        )
        diagnostic_events = client._request_json(
            "/api/v4/events",
            {
                "filter[entity]": "lead",
                "filter[entity_id]": crm_lead_id,
                "filter[created_at][from]": created_at + 1,
                "limit": 100,
                "page": 1,
            },
        )
        event_rows = list(((diagnostic_events.get("_embedded") or {}).get("events")) or [])
        LOG.info(
            "CRM feedback diagnostic events lead_id=%s rows=%s",
            crm_lead_id,
            [
                {
                    "id": row.get("id"),
                    "type": row.get("type"),
                    "entity_id": row.get("entity_id"),
                    "created_by": row.get("created_by"),
                    "created_at": row.get("created_at"),
                }
                for row in event_rows
            ],
        )

    first: int | None = None
    page = 1
    while True:
        payload = client._request_json(
            "/api/v4/leads/notes",
            {
                "filter[entity_id][0]": crm_lead_id,
                "filter[note_type]": "common",
                "limit": 250,
                "page": page,
            },
        )
        notes = list(((payload.get("_embedded") or {}).get("notes")) or [])
        for note in notes:
            try:
                note_entity_id = int(note.get("entity_id") or 0)
                note_ts = int(note.get("created_at") or 0)
                note_created_by = int(note.get("created_by") or 0)
            except (TypeError, ValueError):
                continue
            if note_entity_id != crm_lead_id or note_ts <= created_at:
                continue
            if str(note.get("note_type") or "").strip().casefold() != "common":
                continue
            if note_created_by != responsible_user_id:
                continue
            if not _is_later_calendar_date(note_ts, created_at):
                continue
            if first is None or note_ts < first:
                first = note_ts

        links = payload.get("_links") or {}
        if not links.get("next") or not notes:
            break
        page += 1
        if page > 50:
            LOG.warning("CRM notes pagination stopped lead_id=%s after 50 pages", crm_lead_id)
            break
    return first


def apply_crm_feedback_tracking(
    leads: list[dict[str, Any]],
    client: AmoCRMClient,
    previous_leads: list[dict[str, Any]] | None = None,
    now_ts: int | None = None,
    reuse_stable: bool = False,
) -> None:
    """Attach feedback tracking without changing the existing lead status logic.

    Only CRM-confirmed deals participate. Deals in terminal/working statuses
    "Закрыто и не реализовано", "Согласование договора",
    "Внесена п/о идет текущая работа" and "Успешно реализовано" are excluded.
    Feedback is counted only from a
    normal text note (note_type "common") authored by the lead's current
    responsible manager. Comments from any other user and all field/status/system
    events are ignored. Same-day comments are ignored. Calendar days are counted
    in Moscow time with the lead creation date as day 1. If no qualifying manager
    comment exists on day 5, the internal feedback state is NO_FEEDBACK. As soon
    as a qualifying later-date manager comment appears, the state is CLEAR again.

    Fast refreshes always reload the current amoCRM deal card before deciding
    feedback status, so manager/status changes are not hidden by stale CLEAR or
    EXCLUDED state. A previously confirmed qualifying manager comment may still
    be reused only after the current responsible manager is verified.
    """
    current_ts = int(now_ts if now_ts is not None else time.time())
    previous_by_id = {
        str(item.get("id") or ""): item
        for item in (previous_leads or [])
        if item.get("id")
    }
    status_cache: dict[tuple[int, int], str] = {}

    for lead in leads:
        crm = lead.get("crm") or {}
        if not crm.get("found") or crm.get("entity_type") != "lead" or not crm.get("entity_id"):
            lead.pop("crm_feedback", None)
            continue

        crm_lead_id = int(crm["entity_id"])
        previous = previous_by_id.get(str(lead.get("id") or "")) or {}
        previous_crm = previous.get("crm") or {}
        previous_feedback = previous.get("crm_feedback") or {}
        try:
            crm_responsible_user_id = int(crm.get("responsible_user_id") or 0)
        except (TypeError, ValueError):
            crm_responsible_user_id = 0
        full_lead = client._get_entity("leads", crm_lead_id) or {}
        try:
            created_at = int(full_lead.get("created_at") or crm.get("created_at") or 0)
        except (TypeError, ValueError):
            created_at = 0
        status_id = full_lead.get("status_id")
        pipeline_id = full_lead.get("pipeline_id")
        try:
            responsible_user_id = int(
                full_lead.get("responsible_user_id")
                or crm_responsible_user_id
                or 0
            )
        except (TypeError, ValueError):
            responsible_user_id = 0
        status_name = _status_name(client, pipeline_id, status_id, status_cache)

        if _is_feedback_excluded_status(status_id, status_name):
            lead["crm_feedback"] = {
                "state": "EXCLUDED",
                "crm_lead_id": crm_lead_id,
                "lead_created_at": created_at or None,
                "first_activity_at": None,
                "pipeline_id": pipeline_id,
                "status_id": status_id,
                "status_name": status_name,
                "excluded": True,
                "responsible_user_id": responsible_user_id or None,
                "rule_version": FEEDBACK_RULE_VERSION,
            }
            continue

        if not created_at or not responsible_user_id:
            lead["crm_feedback"] = {
                "state": "UNKNOWN",
                "crm_lead_id": crm_lead_id,
                "lead_created_at": None,
                "first_activity_at": None,
                "pipeline_id": pipeline_id,
                "status_id": status_id,
                "status_name": status_name,
                "excluded": False,
                "responsible_user_id": responsible_user_id or None,
                "rule_version": FEEDBACK_RULE_VERSION,
            }
            continue

        # Reuse only a manager comment confirmed by the current feedback rule.
        # Cached CLEAR results from the old "any timeline event" rule are
        # deliberately invalidated and re-queried.
        first_activity_at: int | None = None
        if (
            int(previous_crm.get("entity_id") or 0) == crm_lead_id
            and previous_feedback.get("first_activity_at")
            and int(previous_feedback.get("rule_version") or 0) == FEEDBACK_RULE_VERSION
            and int(previous_feedback.get("responsible_user_id") or 0) == responsible_user_id
        ):
            try:
                previous_activity = int(previous_feedback["first_activity_at"])
            except (TypeError, ValueError):
                previous_activity = 0
            if previous_activity > created_at and _is_later_calendar_date(previous_activity, created_at):
                first_activity_at = previous_activity

        if first_activity_at is None:
            try:
                first_activity_at = _first_manager_comment_after_creation(
                    client,
                    crm_lead_id,
                    created_at,
                    responsible_user_id,
                )
            except RuntimeError as exc:
                # A history lookup must not corrupt the existing lead-control
                # result. Keep the row unknown and retry on the next run.
                LOG.warning("CRM feedback history lookup failed lead_id=%s error=%s", crm_lead_id, exc)
                lead["crm_feedback"] = {
                    "state": "UNKNOWN",
                    "crm_lead_id": crm_lead_id,
                    "lead_created_at": created_at,
                    "first_activity_at": None,
                    "pipeline_id": pipeline_id,
                    "status_id": status_id,
                    "status_name": status_name,
                    "excluded": False,
                    "responsible_user_id": responsible_user_id,
                    "rule_version": FEEDBACK_RULE_VERSION,
                }
                continue

        if first_activity_at is not None:
            state = "CLEAR"
        elif _calendar_day_number(current_ts, created_at) >= FEEDBACK_RED_DAY:
            state = "NO_FEEDBACK"
        else:
            state = "WAITING"

        lead["crm_feedback"] = {
            "state": state,
            "crm_lead_id": crm_lead_id,
            "lead_created_at": created_at,
            "first_activity_at": first_activity_at,
            "pipeline_id": pipeline_id,
            "status_id": status_id,
            "status_name": status_name,
            "excluded": False,
            "deadline_at": _feedback_deadline_ts(created_at),
            "responsible_user_id": responsible_user_id,
            "rule_version": FEEDBACK_RULE_VERSION,
        }
