from __future__ import annotations

import logging
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .amocrm_client import AmoCRMClient


LOG = logging.getLogger(__name__)
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
WEEKS_TO_KEEP = 4
EVENT_PAGE_LIMIT = 100
MAX_EVENT_PAGES = 100


def _status_change(value: object) -> tuple[int, int]:
    items = value if isinstance(value, list) else []
    if not items or not isinstance(items[0], dict):
        return 0, 0
    status = items[0].get("lead_status") or {}
    if not isinstance(status, dict):
        return 0, 0
    try:
        return int(status.get("id") or 0), int(status.get("pipeline_id") or 0)
    except (TypeError, ValueError):
        return 0, 0


def _main_pipeline_id(leads: list[dict[str, Any]]) -> int:
    counts: Counter[int] = Counter()
    for lead in leads:
        crm = lead.get("crm") or {}
        feedback = lead.get("crm_feedback") or {}
        if not crm.get("found") or crm.get("entity_type") != "lead":
            continue
        try:
            pipeline_id = int(feedback.get("pipeline_id") or 0)
        except (TypeError, ValueError):
            pipeline_id = 0
        if pipeline_id:
            counts[pipeline_id] += 1
    return counts.most_common(1)[0][0] if counts else 0


def _pipeline_stages(client: AmoCRMClient, pipeline_id: int) -> tuple[str, list[dict[str, Any]]]:
    payload = client._request_json(f"/api/v4/leads/pipelines/{pipeline_id}", {})
    pipeline_name = str(payload.get("name") or "").strip()
    statuses = list(((payload.get("_embedded") or {}).get("statuses")) or [])
    result: list[dict[str, Any]] = []
    for status in statuses:
        try:
            status_id = int(status.get("id") or 0)
            sort = int(status.get("sort") or 0)
        except (TypeError, ValueError):
            continue
        name = str(status.get("name") or "").strip()
        if status_id and name:
            result.append({"id": status_id, "name": name, "sort": sort})
    result.sort(key=lambda item: (int(item.get("sort") or 0), int(item["id"])))
    return pipeline_name, result


def _week_payload(today) -> list[dict[str, Any]]:
    current_monday = today - timedelta(days=today.weekday())
    weeks: list[dict[str, Any]] = []
    for index in range(WEEKS_TO_KEEP):
        start = current_monday - timedelta(days=7 * index)
        dates = [(start + timedelta(days=offset)).isoformat() for offset in range(7)]
        end = start + timedelta(days=6)
        weeks.append(
            {
                "index": index,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "dates": dates,
                "label": (
                    f"{start.strftime('%d.%m')}–{end.strftime('%d.%m')} · Текущая"
                    if index == 0
                    else f"{start.strftime('%d.%m')}–{end.strftime('%d.%m')}"
                ),
            }
        )
    return weeks


def collect_pipeline_activity(
    leads: list[dict[str, Any]],
    client: AmoCRMClient,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Collect every real amoCRM lead status transition for the dashboard leads.

    A single lead can contribute several movements on the same day. Lead creation
    is not counted because only lead_status_changed events are requested.
    """
    current_ts = int(now_ts if now_ts is not None else time.time())
    now_dt = datetime.fromtimestamp(current_ts, MOSCOW_TZ)
    today = now_dt.date()
    weeks = _week_payload(today)
    first_day = datetime.fromisoformat(weeks[-1]["start"]).replace(tzinfo=MOSCOW_TZ)
    from_ts = int(first_day.timestamp())

    tracked_ids: set[int] = set()
    for lead in leads:
        crm = lead.get("crm") or {}
        if not crm.get("found") or crm.get("entity_type") != "lead":
            continue
        try:
            entity_id = int(crm.get("entity_id") or 0)
        except (TypeError, ValueError):
            entity_id = 0
        if entity_id:
            tracked_ids.add(entity_id)

    pipeline_id = _main_pipeline_id(leads)
    if not tracked_ids or not pipeline_id:
        return {
            "pipeline_id": pipeline_id or None,
            "pipeline_name": "",
            "today": today.isoformat(),
            "weeks": weeks,
            "stages": [],
            "days": {},
            "total_movements": 0,
        }

    pipeline_name, stages = _pipeline_stages(client, pipeline_id)
    valid_status_ids = {int(stage["id"]) for stage in stages}

    days: dict[str, dict[str, int]] = {}
    total_movements = 0
    seen_event_ids: set[str] = set()
    page = 1

    while True:
        payload = client._request_json(
            "/api/v4/events",
            {
                "filter[entity]": "lead",
                "filter[type]": "lead_status_changed",
                "filter[created_at][from]": from_ts,
                "filter[created_at][to]": current_ts,
                "limit": EVENT_PAGE_LIMIT,
                "page": page,
            },
        )
        events = list(((payload.get("_embedded") or {}).get("events")) or [])
        for event in events:
            event_id = str(event.get("id") or "")
            if event_id and event_id in seen_event_ids:
                continue
            if event_id:
                seen_event_ids.add(event_id)
            try:
                entity_id = int(event.get("entity_id") or 0)
                created_at = int(event.get("created_at") or 0)
            except (TypeError, ValueError):
                continue
            if entity_id not in tracked_ids or not created_at:
                continue

            after_status_id, after_pipeline_id = _status_change(event.get("value_after"))
            before_status_id, before_pipeline_id = _status_change(event.get("value_before"))
            if after_pipeline_id != pipeline_id or after_status_id not in valid_status_ids:
                continue
            if before_status_id == after_status_id and before_pipeline_id == after_pipeline_id:
                continue

            day = datetime.fromtimestamp(created_at, MOSCOW_TZ).date().isoformat()
            bucket = days.setdefault(day, {})
            key = str(after_status_id)
            bucket[key] = int(bucket.get(key) or 0) + 1
            total_movements += 1

        links = payload.get("_links") or {}
        if not events or not links.get("next"):
            break
        page += 1
        if page > MAX_EVENT_PAGES:
            LOG.warning("CRM pipeline activity pagination stopped after %s pages", MAX_EVENT_PAGES)
            break

    return {
        "pipeline_id": pipeline_id,
        "pipeline_name": pipeline_name,
        "today": today.isoformat(),
        "weeks": weeks,
        "stages": stages,
        "days": days,
        "total_movements": total_movements,
    }
