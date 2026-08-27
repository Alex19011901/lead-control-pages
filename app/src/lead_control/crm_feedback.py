from __future__ import annotations

import logging
import time
from datetime import datetime, time as datetime_time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .amocrm_client import AmoCRMClient


LOG = logging.getLogger(__name__)

FEEDBACK_RED_DAY = 5
FEEDBACK_RULE_VERSION = 6
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
        "контакты на декабрь 26",
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
    """Return the first qualifying manager comment on a later calendar date.

    amoCRM may expose manager feedback as a normal lead note (note_type
    "common"), an events timeline row of type "entity_direct_message", or a
    completed task with a written result. Only feedback belonging to the lead's
    current responsible manager counts. Same-day feedback, feedback from other
    users, empty completed tasks, and field/status/system events do not count.
    """
    first: int | None = None

    # Normal text notes.
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

    # Internal amoCRM chat messages shown in the lead timeline as
    # "От: <manager> кому: всем" are entity_direct_message events.
    page = 1
    while True:
        payload = client._request_json(
            "/api/v4/events",
            {
                "filter[entity]": "lead",
                "filter[entity_id]": crm_lead_id,
                "filter[created_at][from]": created_at + 1,
                "limit": 100,
                "page": page,
            },
        )
        events = list(((payload.get("_embedded") or {}).get("events")) or [])
        for event in events:
            try:
                event_entity_id = int(event.get("entity_id") or 0)
                event_ts = int(event.get("created_at") or 0)
                event_created_by = int(event.get("created_by") or 0)
            except (TypeError, ValueError):
                continue
            if event_entity_id != crm_lead_id or event_ts <= created_at:
                continue
            if str(event.get("type") or "").strip() != "entity_direct_message":
                continue
            if event_created_by != responsible_user_id:
                continue
            if not _is_later_calendar_date(event_ts, created_at):
                continue
            if first is None or event_ts < first:
                first = event_ts

        links = payload.get("_links") or {}
        if not links.get("next") or not events:
            break
        page += 1
        if page > 50:
            LOG.warning("CRM events pagination stopped lead_id=%s after 50 pages", crm_lead_id)
            break

    # Completed tasks with a written result confirm feedback when the task
    # belongs to the lead's current responsible manager.
    page = 1
    while True:
        payload = client._request_json(
            "/api/v4/tasks",
            {
                "filter[entity_type]": "leads",
                "filter[entity_id]": crm_lead_id,
                "limit": 250,
                "page": page,
            },
        )
        tasks = list(((payload.get("_embedded") or {}).get("tasks")) or [])
        for task in tasks:
            try:
                task_entity_id = int(task.get("entity_id") or 0)
                task_responsible = int(task.get("responsible_user_id") or 0)
                task_updated_at = int(task.get("updated_at") or 0)
            except (TypeError, ValueError):
                continue
            if task_entity_id != crm_lead_id or not task.get("is_completed"):
                continue
            result = task.get("result") or {}
            result_text = str(result.get("text") or "").strip() if isinstance(result, dict) else ""
            if not result_text:
                continue
            if task_responsible != responsible_user_id:
                continue
            if task_updated_at <= created_at or not _is_later_calendar_date(task_updated_at, created_at):
                continue
            if first is None or task_updated_at < first:
                first = task_updated_at

        links = payload.get("_links") or {}
        if not links.get("next") or not tasks:
            break
        page += 1
        if page > 50:
            LOG.warning("CRM tasks pagination stopped lead_id=%s after 50 pages", crm_lead_id)
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
    "Внесена п/о идет текущая работа", "Успешно реализовано" and
    "Контакты на декабрь 26" are excluded.
    Feedback is counted only from a normal text note (note_type "common"), an
    amoCRM internal chat message (event type "entity_direct_message"), or a
    completed task with a non-empty result text. The feedback must belong to the
    lead's current responsible manager. Comments/tasks from any other manager,
    empty completed tasks, and all other field/status/system events are ignored. Same-day comments are ignored. Calendar days are counted
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
