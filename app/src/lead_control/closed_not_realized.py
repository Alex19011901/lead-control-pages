from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .amocrm_client import AmoCRMClient


LOG = logging.getLogger(__name__)
SUCCESSFUL_STATUS_ID = 142
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


def _latest_common_comment(client: AmoCRMClient, crm_lead_id: int) -> tuple[str, int | None]:
    latest_text = ""
    latest_at: int | None = None
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
                entity_id = int(note.get("entity_id") or 0)
                created_at = int(note.get("created_at") or 0)
            except (TypeError, ValueError):
                continue
            if entity_id != crm_lead_id or not created_at:
                continue
            if str(note.get("note_type") or "").strip().casefold() != "common":
                continue
            params = note.get("params") or {}
            text = str(params.get("text") or "").strip() if isinstance(params, dict) else ""
            if not text:
                continue
            if latest_at is None or created_at > latest_at:
                latest_at = created_at
                latest_text = text

        links = payload.get("_links") or {}
        if not links.get("next") or not notes:
            break
        page += 1
        if page > 50:
            LOG.warning("CRM closed-lead notes pagination stopped lead_id=%s after 50 pages", crm_lead_id)
            break

    return latest_text, latest_at


def apply_closed_not_realized_history(
    leads: list[dict[str, Any]],
    client: AmoCRMClient,
    now_ts: int | None = None,
) -> None:
    """Attach CRM outcome metadata and exact recent closed/lost details."""
    current_ts = int(now_ts if now_ts is not None else time.time())
    today = _moscow_date(current_ts)
    first_day = today - timedelta(days=HISTORY_DAYS - 1)

    for lead in leads:
        lead.pop("closed_not_realized", None)
        lead.pop("crm_outcome", None)

        crm = lead.get("crm") or {}
        if not crm.get("found") or crm.get("entity_type") != "lead" or not crm.get("entity_id"):
            continue

        feedback = lead.get("crm_feedback") or {}
        try:
            status_id = int(feedback.get("status_id") or 0)
        except (TypeError, ValueError):
            status_id = 0
        status_name_raw = str(feedback.get("status_name") or "").strip()
        status_name = _status_key(status_name_raw)

        is_success = status_id == SUCCESSFUL_STATUS_ID or status_name == "успешно реализовано"
        is_lost = status_id == CLOSED_NOT_REALIZED_STATUS_ID or status_name in {
            "закрыто и не реализовано",
            "закрыто и не реализованно",
        }

        if is_success:
            lead["crm_outcome"] = {
                "result": "SUCCESS",
                "status_id": status_id or SUCCESSFUL_STATUS_ID,
                "status_name": status_name_raw or "Успешно реализовано",
            }
            continue

        if not is_lost:
            continue

        crm_lead_id = int(crm["entity_id"])
        detailed = client._get_entity(
            "leads",
            crm_lead_id,
            params={"with": "loss_reason"},
        ) or {}

        try:
            closed_at = int(detailed.get("closed_at") or 0)
        except (TypeError, ValueError):
            closed_at = 0
        reason_id, reason_name = _loss_reason(detailed)
        reason_name = reason_name or "Не указана"

        lead["crm_outcome"] = {
            "result": "LOST",
            "status_id": status_id or CLOSED_NOT_REALIZED_STATUS_ID,
            "status_name": status_name_raw or "Закрыто и не реализовано",
            "closed_at": closed_at or None,
            "loss_reason_id": reason_id,
            "loss_reason_name": reason_name,
        }

        if not closed_at:
            continue

        closed_date = _moscow_date(closed_at)
        if closed_date < first_day or closed_date > today:
            continue

        last_comment = ""
        last_comment_at: int | None = None
        try:
            last_comment, last_comment_at = _latest_common_comment(client, crm_lead_id)
        except RuntimeError as exc:
            LOG.warning("CRM closed-lead comment lookup failed lead_id=%s error=%s", crm_lead_id, exc)

        lead["closed_not_realized"] = {
            "crm_lead_id": crm_lead_id,
            "closed_at": closed_at,
            "loss_reason_id": reason_id,
            "loss_reason_name": reason_name,
            "last_comment": last_comment,
            "last_comment_at": last_comment_at,
        }
