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
PRE_CLOSE_RECORD_VERSION = 2
MAX_HISTORY_PAGES = 50


def _moscow_date(ts: int):
    return datetime.fromtimestamp(int(ts), MOSCOW_TZ).date()


def _status_key(value: object) -> str:
    return str(value or "").strip().casefold().replace("ё", "е")


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _loss_reason(payload: dict[str, Any]) -> tuple[int | None, str]:
    raw = (payload.get("_embedded") or {}).get("loss_reason")
    item = raw[0] if isinstance(raw, list) and raw else raw
    item = item if isinstance(item, dict) else {}
    reason_id = _int(item.get("id") or payload.get("loss_reason_id")) or None
    return reason_id, str(item.get("name") or "").strip()


def _extract_text(value: object) -> str:
    """Only explicit text fields: never mistake a message ID for its text."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            text = _extract_text(item)
            if text:
                return text
    if isinstance(value, dict):
        for key in ("text", "message", "comment", "body", "result", "value"):
            if key in value:
                text = _extract_text(value[key])
                if text:
                    return text
    return ""


def _history_items(client: AmoCRMClient, path: str, params: dict, collection: str):
    """Complete pagination; an incomplete response must not be frozen as empty."""
    for page in range(1, MAX_HISTORY_PAGES + 1):
        payload = client._request_json(path, {**params, "page": page})
        items = (payload.get("_embedded") or {}).get(collection) or []
        if not isinstance(items, list):
            raise RuntimeError("Invalid CRM history collection")
        yield from (item for item in items if isinstance(item, dict))
        has_next = bool((payload.get("_links") or {}).get("next"))
        if not has_next:
            return
        if not items:
            raise RuntimeError("Incomplete CRM history pagination")
    raise RuntimeError("CRM history page limit reached")


def _read_preclose_record(client: AmoCRMClient, crm_lead_id: int,
                         closed_at: int) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    errors: list[str] = []

    def consider(text: str, ts: int, kind: str, record_id: object = "",
                 missing_text: bool = False) -> None:
        nonlocal latest
        if not 0 < ts < closed_at or (not text and not missing_text):
            return
        # An ID-only message later than a note must not silently become that note.
        if ts > _int(latest.get("at")) or (ts == _int(latest.get("at")) and missing_text):
            latest = {"text": text, "at": ts, "kind": kind,
                      "record_id": str(record_id or "")}

    sources = (
        ("notes", "/api/v4/leads/notes", {
            "filter[entity_id][0]": crm_lead_id, "limit": 250}),
        ("events", "/api/v4/events", {
            "filter[entity]": "lead", "filter[entity_id]": crm_lead_id,
            # amoCRM requires BOTH bounds when a date range is passed.
            "filter[created_at][from]": 1,
            "filter[created_at][to]": closed_at - 1, "limit": 100}),
        ("tasks", "/api/v4/tasks", {
            "filter[entity_type]": "leads", "filter[entity_id]": crm_lead_id,
            "limit": 250}),
    )
    for collection, path, params in sources:
        try:
            for item in _history_items(client, path, params, collection):
                if _int(item.get("entity_id")) != crm_lead_id:
                    continue
                if collection == "notes":
                    text = _extract_text(item.get("params")) or _extract_text(item.get("text"))
                    consider(text, _int(item.get("created_at")),
                             str(item.get("note_type") or "note"), item.get("id"))
                elif collection == "events":
                    if item.get("type") != "entity_direct_message":
                        continue
                    text = (_extract_text(item.get("value_after"))
                            or _extract_text(item.get("params")))
                    consider(text, _int(item.get("created_at")), "entity_direct_message",
                             item.get("id"), missing_text=not bool(text))
                elif item.get("is_completed"):
                    consider(_extract_text(item.get("result")), _int(item.get("updated_at")),
                             "task_result", item.get("id"))
        except RuntimeError as exc:
            errors.append(collection)
            LOG.warning("CRM pre-close source failed lead_id=%s source=%s error=%s",
                        crm_lead_id, collection, exc)
            # No retry here. Other successful source results are retained.

    if errors:
        state = "READ_ERROR"
    elif not latest:
        state = "EMPTY"
    elif not latest.get("text"):
        state = "TEXT_UNAVAILABLE"
    else:
        state = "VERIFIED"
    return {
        "crm_lead_id": crm_lead_id, "closed_at": closed_at,
        "last_comment": str(latest.get("text") or ""),
        "last_comment_at": latest.get("at") if latest.get("text") else None,
        "last_record_at": latest.get("at"),
        "last_record_type": str(latest.get("kind") or ""),
        "last_record_id": str(latest.get("record_id") or ""),
        "last_record_status": state,
        "last_record_rule_version": PRE_CLOSE_RECORD_VERSION,
        "last_record_errors": errors,
    }


def _latest_record_before_closed(client: AmoCRMClient, crm_lead_id: int,
                                 closed_at: int) -> tuple[str, int | None]:
    record = _read_preclose_record(client, crm_lead_id, closed_at)
    if record["last_record_status"] == "READ_ERROR":
        raise RuntimeError("Incomplete pre-close history read")
    return record["last_comment"], record["last_comment_at"]


def _snapshot_key(record: dict) -> tuple[int, int]:
    return _int(record.get("crm_lead_id")), _int(record.get("closed_at"))


def _frozen(record: dict) -> bool:
    if _int(record.get("last_record_rule_version")) != PRE_CLOSE_RECORD_VERSION:
        return False
    state = record.get("last_record_status")
    if state == "VERIFIED":
        return bool(str(record.get("last_comment") or "").strip()) and (
            0 < _int(record.get("last_comment_at")) < _int(record.get("closed_at")))
    return state in {"EMPTY", "TEXT_UNAVAILABLE"}


def apply_closed_not_realized_history(
    leads: list[dict[str, Any]], client: AmoCRMClient,
    now_ts: int | None = None,
    previous_leads: list[dict[str, Any]] | None = None,
) -> None:
    """Freeze successfully read pre-close records, preserving data on read errors."""
    current_ts = int(now_ts if now_ts is not None else time.time())
    today = _moscow_date(current_ts)
    first_day = today - timedelta(days=HISTORY_DAYS - 1)
    previous: dict[tuple[int, int], dict] = {}
    for old in list(previous_leads or []) + leads:
        old_crm_id = _int((old.get("crm") or {}).get("entity_id"))
        for field in ("closed_not_realized", "preclose_record_cache"):
            record = old.get(field) or {}
            key = _snapshot_key(record)
            if key[0] != old_crm_id or not all(key):
                continue
            existing = previous.get(key) or {}
            if not existing or _frozen(record) or not existing.get("last_comment"):
                previous[key] = dict(record)

    detail_cache: dict[int, dict] = {}
    record_cache: dict[tuple[int, int], dict] = {}
    for lead in leads:
        lead.pop("closed_not_realized", None)
        lead.pop("crm_outcome", None)
        crm = lead.get("crm") or {}
        if not crm.get("found") or crm.get("entity_type") != "lead" or not crm.get("entity_id"):
            continue
        crm_id = _int(crm["entity_id"])
        feedback = lead.get("crm_feedback") or {}
        status_id = _int(feedback.get("status_id"))
        status_name = str(feedback.get("status_name") or "").strip()
        key_name = _status_key(status_name)
        if status_id == SUCCESSFUL_STATUS_ID or key_name == "успешно реализовано":
            lead["crm_outcome"] = {"result": "SUCCESS", "status_id": status_id or 142,
                                   "status_name": status_name or "Успешно реализовано"}
            continue
        if status_id != 143 and key_name not in {"закрыто и не реализовано", "закрыто и не реализованно"}:
            continue

        if feedback.get("loss_reason_checked"):
            closed_at = _int(feedback.get("closed_at"))
            reason_id = _int(feedback.get("loss_reason_id")) or None
            reason = str(feedback.get("loss_reason_name") or "").strip() or "Не указана"
        else:
            if crm_id not in detail_cache:
                detail_cache[crm_id] = client._get_entity(
                    "leads", crm_id, params={"with": "loss_reason"}) or {}
            card = detail_cache[crm_id]
            closed_at = _int(card.get("closed_at"))
            reason_id, reason = _loss_reason(card)
            reason = reason or "Не указана"
        lead["crm_outcome"] = {
            "result": "LOST", "status_id": status_id or 143,
            "status_name": status_name or "Закрыто и не реализовано",
            "closed_at": closed_at or None, "loss_reason_id": reason_id,
            "loss_reason_name": reason,
        }
        if not closed_at:
            continue
        key = (crm_id, closed_at)
        saved = previous.get(key) or {}
        if saved:
            lead["preclose_record_cache"] = dict(saved)
        if not first_day <= _moscow_date(closed_at) <= today:
            continue
        if key in record_cache:
            record = dict(record_cache[key])
        elif _frozen(saved):
            record = dict(saved)
        else:
            record = _read_preclose_record(client, crm_id, closed_at)
            if record["last_record_status"] == "READ_ERROR":
                saved_at = _int(saved.get("last_comment_at"))
                if saved.get("last_comment") and 0 < saved_at < closed_at:
                    record["last_comment"] = saved["last_comment"]
                    record["last_comment_at"] = saved_at
                    record["last_record_preserved"] = True
            # Old unversioned empty values are never considered valid cache hits.
        record_cache[key] = dict(record)
        lead["preclose_record_cache"] = dict(record)
        lead["closed_not_realized"] = {
            **record, "crm_lead_id": crm_id, "closed_at": closed_at,
            "loss_reason_id": reason_id, "loss_reason_name": reason,
        }
