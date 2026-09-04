from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, TextIO


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "app" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lead_control import metrika_offline


DEFAULT_AMOCRM_DOMAIN = "https://alex1901yaru.amocrm.ru"
DEFAULT_DATA_DIR = Path("runtime-data")
METRIKA_OFFLINE_ENABLED_ENV = "METRIKA_OFFLINE_ENABLED"
METRIKA_OFFLINE_DRY_RUN_ENV = "METRIKA_OFFLINE_DRY_RUN"
YANDEX_METRIKA_OFFLINE_TOKEN_ENV = "YANDEX_METRIKA_OFFLINE_TOKEN"

EventsClientFactory = Callable[[str, str, int], Any]
MetrikaClientFactory = Callable[[str, int], Any]


def main() -> int:
    return run()


def run(
    *,
    env: Mapping[str, str] | None = None,
    data_dir: Path | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    events_client_factory: EventsClientFactory | None = None,
    metrika_client_factory: MetrikaClientFactory | None = None,
) -> int:
    env_map = os.environ if env is None else env
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    sensitive_values = _sensitive_env_values(env_map)
    state: dict[str, Any] | None = None
    state_path: Path | None = None

    try:
        data_root = Path(data_dir or env_map.get("LEAD_CONTROL_DATA_DIR") or DEFAULT_DATA_DIR)
        leads_path = data_root / "leads.json"
        state_path = data_root / "metrika_offline_state.json"
        state = metrika_offline.load_metrika_offline_state(state_path)
        leads = _load_leads(leads_path)

        enabled = env_map.get(METRIKA_OFFLINE_ENABLED_ENV) == "1"
        dry_run = env_map.get(METRIKA_OFFLINE_DRY_RUN_ENV, "1") != "0"
        if not enabled:
            summary = _summary(status="disabled", enabled=False, dry_run=True, total_leads=len(leads))
            _save_summary(state, state_path, summary)
            _write_summary(stdout, summary)
            return 0

        candidates = _candidate_leads(leads, state)
        if not candidates:
            summary = _summary(status="no_candidates", enabled=True, dry_run=dry_run, total_leads=len(leads), candidates=0)
            _save_summary(state, state_path, summary)
            _write_summary(stdout, summary)
            return 0

        amocrm_token = str(env_map.get("AMOCRM_TOKEN") or "").strip()
        timeout = _positive_int(env_map.get("METRIKA_OFFLINE_HTTP_TIMEOUT"), default=30)
        amocrm_domain = str(env_map.get("AMOCRM_DOMAIN") or DEFAULT_AMOCRM_DOMAIN).strip()

        if dry_run:
            summary = _summary(status="dry_run", enabled=True, dry_run=True, total_leads=len(leads), candidates=len(candidates))
            if not amocrm_token:
                summary["qualification_check"] = "missing_amocrm_token"
                summary["candidate_details"] = [_safe_candidate_details(lead) for lead in candidates]
            else:
                events_client = events_client_factory(amocrm_domain, amocrm_token, timeout) if events_client_factory is not None else metrika_offline.AmoCRMEventsReadOnlyClient(amocrm_domain, amocrm_token, timeout=timeout)
                summary["qualification_check"] = "read_only_amocrm_events"
                summary["candidate_details"] = [_dry_run_candidate_details(lead, events_client) for lead in candidates]
            _save_summary(state, state_path, summary)
            _write_summary(stdout, summary)
            return 0

        if not amocrm_token:
            summary = _summary(status="missing_amocrm_token", enabled=True, dry_run=False, total_leads=len(leads), candidates=len(candidates))
            _save_summary(state, state_path, summary)
            _write_summary(stdout, summary)
            return 0

        metrika_token = str(env_map.get(YANDEX_METRIKA_OFFLINE_TOKEN_ENV) or "").strip()
        if not metrika_token:
            summary = _summary(status="missing_metrika_token", enabled=True, dry_run=False, total_leads=len(leads), candidates=len(candidates))
            _save_summary(state, state_path, summary)
            _write_summary(stdout, summary)
            return 0

        events_client = events_client_factory(amocrm_domain, amocrm_token, timeout) if events_client_factory is not None else metrika_offline.AmoCRMEventsReadOnlyClient(amocrm_domain, amocrm_token, timeout=timeout)
        metrika_client = metrika_client_factory(metrika_token, timeout) if metrika_client_factory is not None else metrika_offline.YandexMetrikaOfflineClient(metrika_token, timeout=timeout)

        processed = 0
        uploaded = 0
        errors: list[str] = []
        detected_at = _now_utc_iso()
        for lead in candidates:
            try:
                record, _duplicate = metrika_offline.record_qualified_lead_detection_with_datetime(state, lead, events_client, detected_at=detected_at)
                if record is None:
                    continue
                processed += 1
                result = metrika_offline.submit_metrika_offline_record(state, record, metrika_client, submitted_at=_now_utc_iso())
                if result.attempted:
                    uploaded += 1
            except Exception as exc:
                errors.append(_redact(str(exc), sensitive_values))

        status = "completed" if not errors else "completed_with_errors"
        summary = _summary(status=status, enabled=True, dry_run=False, total_leads=len(leads), candidates=len(candidates), processed=processed, uploads_attempted=uploaded, errors=errors)
        _save_summary(state, state_path, summary)
        _write_summary(stdout, summary)
        return 0
    except Exception as exc:
        message = _redact(str(exc), sensitive_values)
        summary = _summary(status="failed", enabled=False, dry_run=True, errors=[message])
        if state_path is not None:
            if state is None:
                state = metrika_offline.default_metrika_offline_state()
            _safe_save_summary(state, state_path, summary, stdout)
        _write_summary(stdout, summary)
        stderr.write("")
        return 0


def _load_leads(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    leads = payload.get("leads") if isinstance(payload, dict) else None
    if not isinstance(leads, list):
        return []
    return [lead for lead in leads if isinstance(lead, dict)]


def _candidate_leads(leads: list[dict[str, Any]], state: dict[str, Any]) -> list[dict[str, Any]]:
    conversions = state.setdefault("conversions", {})
    result: list[dict[str, Any]] = []
    for lead in leads:
        record = metrika_offline.build_qualified_lead_detection(lead)
        if record is None or not record.get("crm_lead_id"):
            continue
        existing = conversions.get(record["idempotency_key"])
        if isinstance(existing, dict) and str(existing.get("state") or "").strip() in metrika_offline.SUBMISSION_BLOCKING_STATES:
            continue
        result.append(lead)
    return result


def _safe_candidate_details(lead: dict[str, Any]) -> dict[str, Any]:
    record = metrika_offline.build_qualified_lead_detection(lead) or {}
    feedback = lead.get("crm_feedback") if isinstance(lead.get("crm_feedback"), dict) else {}
    fields = lead.get("fields") if isinstance(lead.get("fields"), dict) else {}
    return {
        "lead_id": str(lead.get("id") or ""),
        "crm_lead_id": str(record.get("crm_lead_id") or ""),
        "status_name": str(feedback.get("status_name") or ""),
        "yclid": str(fields.get("yclid") or ""),
        "name": _first_text(lead.get("name"), fields.get("name")),
        "phone": _first_text(lead.get("phone"), fields.get("phone"), lead.get("identifier")),
        "source": _first_text(lead.get("source"), fields.get("source")),
        "lead_time": _first_text(lead.get("ts"), lead.get("created_at"), lead.get("first_seen_at"), fields.get("ts")),
    }


def _dry_run_candidate_details(lead: dict[str, Any], events_client: Any) -> dict[str, Any]:
    details = _safe_candidate_details(lead)
    crm_lead_id = _positive_int(details.get("crm_lead_id"), default=0)
    if crm_lead_id <= 0:
        details["qualification_datetime_state"] = "missing_crm_lead_id"
        details["qualification_datetime"] = None
        details["qualification_datetime_iso"] = ""
        return details

    result = metrika_offline.lookup_first_qualification_datetime(events_client, crm_lead_id)
    details["qualification_datetime_state"] = result.datetime_state
    details["qualification_datetime_source"] = result.datetime_source
    details["qualification_datetime"] = result.qualification_datetime
    details["qualification_datetime_iso"] = _unix_to_utc_iso(result.qualification_datetime)
    if result.error_kind:
        details["qualification_error_kind"] = result.error_kind
    if result.error_status is not None:
        details["qualification_error_status"] = result.error_status
    if result.error_detail:
        details["qualification_error_detail"] = str(result.error_detail)[:200]
    if result.datetime_state == metrika_offline.DATETIME_STATE_MISSING_TRANSITION_TIMESTAMP:
        details.update(_all_status_transition_diagnostics(events_client, crm_lead_id))
    return details


def _all_status_transition_diagnostics(events_client: Any, crm_lead_id: int) -> dict[str, Any]:
    params = {
        "filter[entity]": "lead",
        "filter[entity_id][0]": int(crm_lead_id),
        "filter[type]": "lead_status_changed",
        "limit": 100,
        "page": 1,
    }
    try:
        payload = events_client.get_events(params)
    except metrika_offline.AmoCRMEventsLookupError as exc:
        result: dict[str, Any] = {
            "all_status_events_check": "lookup_failed",
            "all_status_events_error_kind": exc.kind,
        }
        if exc.http_status is not None:
            result["all_status_events_error_status"] = exc.http_status
        if exc.detail:
            result["all_status_events_error_detail"] = str(exc.detail)[:200]
        return result

    events = list(((payload.get("_embedded") or {}).get("events")) or [])
    transitions: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        item: dict[str, Any] = {
            "created_at": event.get("created_at"),
            "created_at_iso": _unix_to_utc_iso(event.get("created_at")),
            "entity_id": event.get("entity_id"),
        }
        before_statuses = _event_lead_statuses(event.get("value_before"))
        after_statuses = _event_lead_statuses(event.get("value_after"))
        if before_statuses:
            item["value_before"] = before_statuses
        if after_statuses:
            item["value_after"] = after_statuses
        transitions.append(item)

    return {
        "all_status_events_check": "read_only_unfiltered_lead_status_changed",
        "all_status_events_count": len(events),
        "all_status_events_has_next": bool((payload.get("_links") or {}).get("next")),
        "all_status_events": transitions,
    }


def _event_lead_statuses(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    statuses: list[dict[str, Any]] = []
    for change in value:
        if not isinstance(change, dict):
            continue
        lead_status = change.get("lead_status")
        if not isinstance(lead_status, dict):
            continue
        statuses.append(
            {
                "pipeline_id": lead_status.get("pipeline_id"),
                "status_id": lead_status.get("id") or lead_status.get("status_id"),
            }
        )
    return statuses


def _first_text(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _unix_to_utc_iso(value: object) -> str:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return ""
    if timestamp <= 0:
        return ""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _summary(*, status: str, enabled: bool, dry_run: bool, total_leads: int = 0, candidates: int = 0, processed: int = 0, uploads_attempted: int = 0, errors: list[str] | None = None) -> dict[str, Any]:
    return {"updated_at": _now_utc_iso(), "status": status, "enabled": enabled, "dry_run": dry_run, "total_leads": total_leads, "candidates": candidates, "processed": processed, "uploads_attempted": uploads_attempted, "errors": errors or []}


def _save_summary(state: dict[str, Any], state_path: Path, summary: dict[str, Any]) -> None:
    state["runner"] = summary
    metrika_offline.save_metrika_offline_state(state, state_path)


def _safe_save_summary(state: dict[str, Any], state_path: Path, summary: dict[str, Any], stdout: TextIO) -> None:
    try:
        _save_summary(state, state_path, summary)
    except Exception as exc:
        fallback = dict(summary)
        fallback["state_save_error"] = _redact(str(exc), [])
        _write_summary(stdout, fallback)


def _write_summary(stream: TextIO, summary: dict[str, Any]) -> None:
    stream.write(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    stream.write("\n")


def _positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _sensitive_env_values(env: Mapping[str, str]) -> list[str]:
    values: list[str] = []
    for key, value in env.items():
        upper_key = key.upper()
        if not any(marker in upper_key for marker in ("TOKEN", "SECRET", "AUTHORIZATION")):
            continue
        text = str(value or "")
        if len(text) >= 4:
            values.append(text)
    return values


def _redact(value: object, sensitive_values: list[str]) -> str:
    text = str(value or "")
    for sensitive in sensitive_values:
        text = text.replace(sensitive, "[redacted]")
    text = re.sub(r"(OAuth|Bearer)\s+[A-Za-z0-9._~+/=-]+", r"\1 [redacted]", text)
    return text[:500]


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
