from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .amocrm_client import AmoCRMClient


CLOSED_NOT_REALIZED_STATUS_ID = 143
HISTORY_DAYS = 5
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def _moscow_date(ts: int):
    return datetime.fromtimestamp(int(ts), MOSCOW_TZ).date()


def _status_key(value: object) -> str:
    return str(value or "").strip().casefold().replace("ё", "е")


def _loss_reason(payload: dict[str, Any]) -> tuple[int | None, str]:
    raw = ((payload.get("_embedded") or {}).get("loss_reason"))
    item: dict[str, Any] = {}
    if isinstance(raw, list) and raw:
        item = raw[0] if isinstance(raw[0], dict) else {}
    elif isinstance(raw, dict):
        item = raw

    reason_id = item.get("id") or payload.get("loss_reason_id")
    try:
        reason_id = int(reason_id) if reason_id else None
    except (TypeError, ValueError):
        reason_id = None
    return reason_id, str(item.get("name") or "").strip()


def apply_closed_not_realized_history(
    leads: list[dict[str, Any]],
    client: AmoCRMClient,
    now_ts: int | None = None,
) -> None:
    """Attach exact recent amoCRM closed/lost metadata to tracked leads.

    The current lead card has already been loaded by CRM feedback tracking in
    the same process, so the first entity lookup normally hits the shared
    AmoCRMClient cache. A second request with `with=loss_reason` is made only
    for deals that are currently "Закрыто и не реализовано" and whose
    `closed_at` falls within the last five Moscow calendar dates.
    """
    current_ts = int(now_ts if now_ts is not None else time.time())
    today = _moscow_date(current_ts)
    first_day = today - timedelta(days=HISTORY_DAYS - 1)

    for lead in leads:
        lead.pop("closed_not_realized", None)
        crm = lead.get("crm") or {}
        if not crm.get("found") or crm.get("entity_type") != "lead" or not crm.get("entity_id"):
            continue

        feedback = lead.get("crm_feedback") or {}
        try:
            status_id = int(feedback.get("status_id") or 0)
        except (TypeError, ValueError):
            status_id = 0
        status_name = _status_key(feedback.get("status_name"))
        if status_id != CLOSED_NOT_REALIZED_STATUS_ID and status_name not in {
            "закрыто и не реализовано",
            "закрыто и не реализованно",
        }:
            continue

        crm_lead_id = int(crm["entity_id"])
        full_lead = client._get_entity("leads", crm_lead_id) or {}
        try:
            closed_at = int(full_lead.get("closed_at") or 0)
        except (TypeError, ValueError):
            closed_at = 0
        if not closed_at:
            continue

        closed_date = _moscow_date(closed_at)
        if closed_date < first_day or closed_date > today:
            continue

        detailed = client._get_entity(
            "leads",
            crm_lead_id,
            params={"with": "loss_reason"},
        ) or full_lead
        reason_id, reason_name = _loss_reason(detailed)

        lead["closed_not_realized"] = {
            "crm_lead_id": crm_lead_id,
            "closed_at": closed_at,
            "loss_reason_id": reason_id,
            "loss_reason_name": reason_name,
        }
