from __future__ import annotations

import csv
import io
import json
import os
import re
import socket
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .state import load_json, stable_json


TARGET_QUALIFIED_LEAD = "qualified_lead"
METRIKA_OFFLINE_STATE_SCHEMA_VERSION = 1
DEFAULT_METRIKA_OFFLINE_STATE_PATH = Path("runtime-data/metrika_offline_state.json")
QUALIFYING_CRM_PIPELINE_ID = 10081590
YANDEX_METRIKA_COUNTER_ID = 112267492
YANDEX_METRIKA_API_BASE_URL = "https://api-metrika.yandex.net"
YANDEX_METRIKA_OFFLINE_UPLOAD_PATH = (
    f"/management/v1/counter/{YANDEX_METRIKA_COUNTER_ID}/offline_conversions/upload"
)
YANDEX_METRIKA_UPLOAD_STATUS_PATH_TEMPLATE = (
    f"/management/v1/counter/{YANDEX_METRIKA_COUNTER_ID}/offline_conversions/uploading/{{upload_id}}"
)


def _status_key(status_name: object) -> str:
    return str(status_name or "").strip().casefold().replace("ё", "е")


QUALIFYING_CRM_STATUS_NAMES = frozenset(
    {
        "Выслано предложение",
        "Принимают решение",
        "Предбронь",
        "Приедут на просмотр",
        "ЖДЕМ НА ДЕГУСТАЦИЮ",
        "Согласование договора",
        "Внесена п/о идет текущая работа",
        "Успешно реализовано",
    }
)

QUALIFYING_CRM_STATUS_IDS_BY_NAME = {
    "Выслано предложение": 79927038,
    "Принимают решение": 79927042,
    "Предбронь": 80331318,
    "Приедут на просмотр": 79927914,
    "ЖДЕМ НА ДЕГУСТАЦИЮ": 80182874,
    "Согласование договора": 79927046,
    "Внесена п/о идет текущая работа": 84995274,
    "Успешно реализовано": 142,
}
QUALIFYING_CRM_STATUS_IDS = frozenset(QUALIFYING_CRM_STATUS_IDS_BY_NAME.values())
_QUALIFYING_CRM_STATUS_KEYS = frozenset(_status_key(status) for status in QUALIFYING_CRM_STATUS_NAMES)

IDEMPOTENCY_BLOCKING_STATES = frozenset({"detected", "submitted", "uncertain"})
ALLOWED_METRIKA_OFFLINE_STATES = frozenset({"detected", "submitted", "uncertain", "failed"})
SUBMISSION_BLOCKING_STATES = frozenset({"submitted", "uncertain", "failed"})
DATETIME_SOURCE_AMOCRM_LEAD_STATUS_CHANGED = "amocrm_lead_status_changed"
DATETIME_STATE_NOT_CHECKED = "not_checked"
DATETIME_STATE_CONFIRMED = "confirmed"
DATETIME_STATE_MISSING_TRANSITION_TIMESTAMP = "missing_transition_timestamp"
DATETIME_STATE_LOOKUP_FAILED = "lookup_failed"
DATETIME_LOOKUP_FINAL_STATES = frozenset(
    {
        DATETIME_STATE_CONFIRMED,
        DATETIME_STATE_MISSING_TRANSITION_TIMESTAMP,
        DATETIME_STATE_LOOKUP_FAILED,
    }
)
MAX_EVENTS_PAGES = 50
METRIKA_UPLOAD_STATUSES = frozenset(
    {
        "PREPARED",
        "UPLOADED",
        "EXPORTED",
        "MATCHED",
        "PROCESSED",
        "LINKAGE_FAILURE",
    }
)


class AmoCRMEventsLookupError(RuntimeError):
    def __init__(
        self,
        kind: str,
        *,
        http_status: int | None = None,
        detail: str = "",
    ) -> None:
        self.kind = kind
        self.http_status = http_status
        self.detail = detail
        message = kind
        if http_status is not None:
            message = f"{message}: HTTP {http_status}"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


class MetrikaOfflineUploadBlocked(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class MetrikaOfflineHTTPError(RuntimeError):
    def __init__(
        self,
        kind: str,
        *,
        http_status: int | None = None,
        detail: str = "",
    ) -> None:
        self.kind = kind
        self.http_status = http_status
        self.detail = detail
        message = kind
        if http_status is not None:
            message = f"{message}: HTTP {http_status}"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


@dataclass(frozen=True)
class QualificationDateTimeLookupResult:
    qualification_datetime: int | None
    datetime_state: str
    datetime_source: str = ""
    error_kind: str | None = None
    error_status: int | None = None
    error_detail: str = ""


@dataclass(frozen=True)
class MetrikaOfflineSubmissionResult:
    attempted: bool
    state: str
    blocked_reason: str = ""
    upload_id: int | None = None
    upload_status: str = ""
    http_status: int | None = None
    error_kind: str | None = None
    diagnostic: str = ""


@dataclass(frozen=True)
class MetrikaUploadInfo:
    upload_id: int | None
    status: str
    known_status: bool


@dataclass(frozen=True)
class MetrikaUploadStatusResult:
    upload_id: int | None
    status: str
    known_status: bool
    lookup_state: str
    http_status: int | None = None
    error_kind: str | None = None
    diagnostic: str = ""


class AmoCRMEventsReadOnlyClient:
    def __init__(self, domain: str, token: str, *, timeout: int = 30) -> None:
        self.domain = domain.rstrip("/")
        self._token = token
        self.timeout = timeout

    def get_events(self, params: dict[str, Any]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        url = f"{self.domain}/api/v4/events"
        if query:
            url = f"{url}?{query}"

        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._token}",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                if response.status == 204:
                    return {}
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise AmoCRMEventsLookupError("http_error", http_status=exc.code) from None
        except TimeoutError as exc:
            raise AmoCRMEventsLookupError("timeout", detail=str(exc)) from None
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, TimeoutError):
                raise AmoCRMEventsLookupError("timeout", detail=str(reason)) from None
            raise AmoCRMEventsLookupError("network_error", detail=str(reason)) from None
        except json.JSONDecodeError as exc:
            raise AmoCRMEventsLookupError("invalid_json", detail=str(exc)) from None


class YandexMetrikaOfflineClient:
    def __init__(
        self,
        token: str,
        *,
        counter_id: int = YANDEX_METRIKA_COUNTER_ID,
        base_url: str = YANDEX_METRIKA_API_BASE_URL,
        timeout: int = 30,
        urlopen: Any = urllib.request.urlopen,
    ) -> None:
        self._token = token
        self.counter_id = counter_id
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._urlopen = urlopen

    def upload_offline_conversion_csv(self, csv_bytes: bytes) -> dict[str, Any]:
        body, content_type = build_multipart_file_body(
            csv_bytes,
            field_name="file",
            filename="offline-conversions.csv",
            content_type="text/csv; charset=utf-8",
        )
        return self._request_json(
            self._offline_upload_url(),
            method="POST",
            headers={
                "Accept": "application/json",
                "Authorization": f"OAuth {self._token}",
                "Content-Type": content_type,
            },
            data=body,
        )

    def get_upload_status(self, upload_id: int) -> dict[str, Any]:
        return self._request_json(
            self._upload_status_url(upload_id),
            method="GET",
            headers={
                "Accept": "application/json",
                "Authorization": f"OAuth {self._token}",
            },
            data=None,
        )

    def _offline_upload_url(self) -> str:
        path = f"/management/v1/counter/{self.counter_id}/offline_conversions/upload"
        return f"{self.base_url}{path}"

    def _upload_status_url(self, upload_id: int) -> str:
        path = f"/management/v1/counter/{self.counter_id}/offline_conversions/uploading/{int(upload_id)}"
        return f"{self.base_url}{path}"

    def _request_json(
        self,
        url: str,
        *,
        method: str,
        headers: dict[str, str],
        data: bytes | None,
    ) -> dict[str, Any]:
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._urlopen(request, timeout=self.timeout) as response:
                body = response.read()
                http_status = int(getattr(response, "status", 200) or 200)
        except urllib.error.HTTPError as exc:
            raise MetrikaOfflineHTTPError(
                "http_error",
                http_status=exc.code,
                detail=_safe_error_detail(_read_http_error_body(exc), self._token),
            ) from None
        except (TimeoutError, socket.timeout) as exc:
            raise MetrikaOfflineHTTPError("timeout", detail=_safe_error_detail(str(exc), self._token)) from None
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise MetrikaOfflineHTTPError(
                    "timeout",
                    detail=_safe_error_detail(str(reason), self._token),
                ) from None
            raise MetrikaOfflineHTTPError(
                "network_error",
                detail=_safe_error_detail(str(reason), self._token),
            ) from None

        if http_status < 200 or http_status >= 300:
            raise MetrikaOfflineHTTPError(
                "http_error",
                http_status=http_status,
                detail=_safe_error_detail(body, self._token),
            ) from None
        if not body:
            return {}
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            raise MetrikaOfflineHTTPError(
                "invalid_json",
                http_status=http_status,
                detail=_safe_error_detail(body, self._token),
            ) from None


def default_metrika_offline_state() -> dict[str, Any]:
    return {
        "schema_version": METRIKA_OFFLINE_STATE_SCHEMA_VERSION,
        "target": TARGET_QUALIFIED_LEAD,
        "conversions": {},
    }


def load_metrika_offline_state(path: Path = DEFAULT_METRIKA_OFFLINE_STATE_PATH) -> dict[str, Any]:
    state = load_json(path, default_metrika_offline_state())
    if not isinstance(state, dict):
        return default_metrika_offline_state()
    state.setdefault("schema_version", METRIKA_OFFLINE_STATE_SCHEMA_VERSION)
    state.setdefault("target", TARGET_QUALIFIED_LEAD)
    conversions = state.get("conversions")
    if not isinstance(conversions, dict):
        state["conversions"] = {}
    return state


def save_metrika_offline_state(
    state: dict[str, Any],
    path: Path = DEFAULT_METRIKA_OFFLINE_STATE_PATH,
) -> None:
    _atomic_save_json(path, state)


def _atomic_save_json(path: Path, value: Any) -> None:
    text = stable_json(value) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp_path, path)
        temp_path = None
        _fsync_directory(path.parent)
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


def _fsync_directory(directory: Path) -> None:
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return

    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def is_qualifying_crm_status(status_name: object) -> bool:
    return _status_key(status_name) in _QUALIFYING_CRM_STATUS_KEYS


def build_qualified_lead_detection(
    lead: dict[str, Any],
    *,
    detected_at: str | None = None,
) -> dict[str, Any] | None:
    yclid = _lead_yclid(lead)
    if not yclid:
        return None

    crm_feedback = lead.get("crm_feedback") or {}
    status_name = str(crm_feedback.get("status_name") or "").strip()
    if not is_qualifying_crm_status(status_name):
        return None

    stable_id = stable_lead_id(lead)
    if not stable_id:
        return None

    crm_lead_id = _crm_lead_id(lead)
    return {
        "idempotency_key": build_idempotency_key(stable_id, yclid),
        "lead_id": str(lead.get("id") or ""),
        "crm_lead_id": crm_lead_id,
        "yclid": yclid,
        "target": TARGET_QUALIFIED_LEAD,
        "current_crm_status": status_name,
        "detected_at": detected_at or _now_utc_iso(),
        "qualification_datetime": None,
        "datetime_source": "",
        "datetime_state": DATETIME_STATE_NOT_CHECKED,
        "state": "detected",
    }


def record_qualified_lead_detection(
    state: dict[str, Any],
    lead: dict[str, Any],
    *,
    detected_at: str | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    record = build_qualified_lead_detection(lead, detected_at=detected_at)
    if record is None:
        return None, False

    conversions = state.setdefault("conversions", {})
    existing = _find_existing_record(conversions, record)
    if existing is not None:
        _refresh_existing_record(existing, record)
        return existing, True

    conversions[record["idempotency_key"]] = record
    return record, False


def record_qualified_lead_detections(
    state: dict[str, Any],
    leads: list[dict[str, Any]],
    *,
    detected_at: str | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for lead in leads:
        record, duplicate = record_qualified_lead_detection(state, lead, detected_at=detected_at)
        if record is not None and not duplicate:
            records.append(record)
    return records


def record_qualified_lead_detection_with_datetime(
    state: dict[str, Any],
    lead: dict[str, Any],
    events_client: Any,
    *,
    detected_at: str | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    crm_lead_id = _crm_lead_id(lead)
    if crm_lead_id is None:
        return None, False

    record, duplicate = record_qualified_lead_detection(state, lead, detected_at=detected_at)
    if record is None:
        return None, False

    if _should_lookup_qualification_datetime(record):
        result = lookup_first_qualification_datetime(events_client, crm_lead_id)
        _apply_qualification_datetime_lookup(record, result)

    return record, duplicate


def prepare_metrika_offline_csv(record: dict[str, Any]) -> bytes:
    reason = metrika_csv_block_reason(record)
    if reason:
        raise MetrikaOfflineUploadBlocked(reason)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["Yclid", "Target", "DateTime"], lineterminator="\n")
    writer.writeheader()
    writer.writerow(
        {
            "Yclid": str(record.get("yclid") or "").strip(),
            "Target": TARGET_QUALIFIED_LEAD,
            "DateTime": str(int(record["qualification_datetime"])),
        }
    )
    return output.getvalue().encode("utf-8")


def metrika_csv_block_reason(record: dict[str, Any]) -> str:
    if not str(record.get("yclid") or "").strip():
        return "missing_yclid"
    if str(record.get("target") or "").strip() != TARGET_QUALIFIED_LEAD:
        return "invalid_target"
    if str(record.get("datetime_state") or "").strip() != DATETIME_STATE_CONFIRMED:
        return "datetime_not_confirmed"
    qualification_datetime = _int_or_none(record.get("qualification_datetime"))
    if not qualification_datetime or qualification_datetime <= 0:
        return "missing_qualification_datetime"
    return ""


def metrika_upload_block_reason(record: dict[str, Any]) -> str:
    record_state = str(record.get("state") or "").strip()
    if record_state in SUBMISSION_BLOCKING_STATES:
        return f"already_{record_state}"
    return metrika_csv_block_reason(record)


def submit_metrika_offline_record(
    state: dict[str, Any],
    record: dict[str, Any],
    metrika_client: Any,
    *,
    submitted_at: str | None = None,
) -> MetrikaOfflineSubmissionResult:
    record = _state_record_for_submission(state, record)
    blocked_reason = metrika_upload_block_reason(record)
    if blocked_reason:
        return MetrikaOfflineSubmissionResult(
            attempted=False,
            state=str(record.get("state") or ""),
            blocked_reason=blocked_reason,
        )

    try:
        response = metrika_client.upload_offline_conversion_csv(prepare_metrika_offline_csv(record))
        upload_info = parse_metrika_upload_response(response)
    except MetrikaOfflineHTTPError as exc:
        new_state = "uncertain" if exc.kind == "timeout" else "failed"
        _record_safe_upload_error(record, exc, state=new_state)
        return MetrikaOfflineSubmissionResult(
            attempted=True,
            state=new_state,
            http_status=exc.http_status,
            error_kind=exc.kind,
            diagnostic=exc.detail,
        )

    if upload_info.upload_id is None:
        error = MetrikaOfflineHTTPError(
            "malformed_response",
            http_status=200,
            detail="missing uploading.id",
        )
        _record_safe_upload_error(record, error, state="failed")
        return MetrikaOfflineSubmissionResult(
            attempted=True,
            state="failed",
            http_status=200,
            error_kind=error.kind,
            diagnostic=error.detail,
        )

    record["state"] = "submitted"
    record["upload_id"] = upload_info.upload_id
    record["upload_status"] = upload_info.status
    record["submitted_at"] = submitted_at or _now_utc_iso()
    record.pop("upload_error", None)
    return MetrikaOfflineSubmissionResult(
        attempted=True,
        state="submitted",
        upload_id=upload_info.upload_id,
        upload_status=upload_info.status,
        http_status=200,
    )


def fetch_metrika_upload_status(
    metrika_client: Any,
    upload_id: int,
) -> MetrikaUploadStatusResult:
    try:
        payload = metrika_client.get_upload_status(upload_id)
    except MetrikaOfflineHTTPError as exc:
        return MetrikaUploadStatusResult(
            upload_id=None,
            status="",
            known_status=False,
            lookup_state="failed",
            http_status=exc.http_status,
            error_kind=exc.kind,
            diagnostic=exc.detail,
        )
    return parse_metrika_upload_status_response(payload)


def parse_metrika_upload_response(payload: dict[str, Any]) -> MetrikaUploadInfo:
    uploading = payload.get("uploading") if isinstance(payload, dict) else None
    if not isinstance(uploading, dict):
        return MetrikaUploadInfo(upload_id=None, status="", known_status=False)
    status = str(uploading.get("status") or "").strip()
    return MetrikaUploadInfo(
        upload_id=_int_or_none(uploading.get("id")),
        status=status,
        known_status=status in METRIKA_UPLOAD_STATUSES,
    )


def parse_metrika_upload_status_response(payload: dict[str, Any]) -> MetrikaUploadStatusResult:
    upload_info = parse_metrika_upload_response(payload)
    lookup_state = "parsed" if upload_info.upload_id is not None and upload_info.status else "malformed_response"
    return MetrikaUploadStatusResult(
        upload_id=upload_info.upload_id,
        status=upload_info.status,
        known_status=upload_info.known_status,
        lookup_state=lookup_state,
        http_status=200,
    )


def build_multipart_file_body(
    file_bytes: bytes,
    *,
    field_name: str,
    filename: str,
    content_type: str,
    boundary: str | None = None,
) -> tuple[bytes, str]:
    actual_boundary = boundary or f"lead-control-{uuid.uuid4().hex}"
    body = b"".join(
        [
            f"--{actual_boundary}\r\n".encode("ascii"),
            (
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{filename}"\r\n'
            ).encode("ascii"),
            f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
            file_bytes,
            b"\r\n",
            f"--{actual_boundary}--\r\n".encode("ascii"),
        ]
    )
    return body, f"multipart/form-data; boundary={actual_boundary}"


def lookup_first_qualification_datetime(
    events_client: Any,
    crm_lead_id: int,
    *,
    max_pages: int = MAX_EVENTS_PAGES,
) -> QualificationDateTimeLookupResult:
    first: int | None = None
    page = 1

    while page <= max_pages:
        try:
            payload = events_client.get_events(qualification_events_params(crm_lead_id, page=page))
        except AmoCRMEventsLookupError as exc:
            return QualificationDateTimeLookupResult(
                qualification_datetime=None,
                datetime_state=DATETIME_STATE_LOOKUP_FAILED,
                error_kind=exc.kind,
                error_status=exc.http_status,
                error_detail=exc.detail,
            )

        events = list(((payload.get("_embedded") or {}).get("events")) or [])
        for event in events:
            event_ts = qualifying_transition_created_at(event, crm_lead_id=crm_lead_id)
            if event_ts is not None and (first is None or event_ts < first):
                first = event_ts

        links = payload.get("_links") or {}
        if not events or not links.get("next"):
            break
        page += 1

    if page > max_pages:
        return QualificationDateTimeLookupResult(
            qualification_datetime=None,
            datetime_state=DATETIME_STATE_LOOKUP_FAILED,
            error_kind="pagination_limit",
            error_detail=f"events pagination exceeded {max_pages} pages",
        )

    if first is None:
        return QualificationDateTimeLookupResult(
            qualification_datetime=None,
            datetime_state=DATETIME_STATE_MISSING_TRANSITION_TIMESTAMP,
        )

    return QualificationDateTimeLookupResult(
        qualification_datetime=first,
        datetime_state=DATETIME_STATE_CONFIRMED,
        datetime_source=DATETIME_SOURCE_AMOCRM_LEAD_STATUS_CHANGED,
    )


def qualification_events_params(crm_lead_id: int, *, page: int = 1) -> dict[str, Any]:
    params: dict[str, Any] = {
        "filter[entity]": "lead",
        "filter[entity_id][0]": int(crm_lead_id),
        "filter[type]": "lead_status_changed",
        "limit": 100,
        "page": page,
    }
    for index, status_id in enumerate(sorted(QUALIFYING_CRM_STATUS_IDS)):
        params[f"filter[value_after][leads_statuses][{index}][pipeline_id]"] = QUALIFYING_CRM_PIPELINE_ID
        params[f"filter[value_after][leads_statuses][{index}][status_id]"] = status_id
    return params


def qualifying_transition_created_at(event: dict[str, Any], *, crm_lead_id: int | None = None) -> int | None:
    if not isinstance(event, dict):
        return None
    if str(event.get("type") or "").strip() != "lead_status_changed":
        return None
    if str(event.get("entity_type") or "").strip() not in {"", "lead"}:
        return None
    if crm_lead_id is not None:
        event_entity_id = _int_or_none(event.get("entity_id"))
        if event_entity_id is not None and event_entity_id != int(crm_lead_id):
            return None

    created_at = _int_or_none(event.get("created_at"))
    if not created_at or created_at <= 0:
        return None

    for change in event.get("value_after") or []:
        if not isinstance(change, dict):
            continue
        lead_status = change.get("lead_status")
        if not isinstance(lead_status, dict):
            continue
        pipeline_id = _int_or_none(lead_status.get("pipeline_id"))
        status_id = _int_or_none(lead_status.get("id") or lead_status.get("status_id"))
        if pipeline_id == QUALIFYING_CRM_PIPELINE_ID and status_id in QUALIFYING_CRM_STATUS_IDS:
            return created_at
    return None


def stable_lead_id(lead: dict[str, Any]) -> str:
    crm_lead_id = _crm_lead_id(lead)
    if crm_lead_id is not None:
        return str(crm_lead_id)
    return str(lead.get("id") or "").strip()


def build_idempotency_key(stable_id: object, yclid: object) -> str:
    return f"{TARGET_QUALIFIED_LEAD} | {str(stable_id).strip()} | {str(yclid).strip()}"


def _lead_yclid(lead: dict[str, Any]) -> str:
    fields = lead.get("fields") or {}
    return str(fields.get("yclid") or "").strip()


def _crm_lead_id(lead: dict[str, Any]) -> int | None:
    crm_feedback = lead.get("crm_feedback") or {}
    crm = lead.get("crm") or {}
    raw = crm_feedback.get("crm_lead_id") or crm.get("entity_id")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _find_existing_record(
    conversions: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any] | None:
    direct = conversions.get(record["idempotency_key"])
    if isinstance(direct, dict):
        return direct

    for existing in conversions.values():
        if not isinstance(existing, dict):
            continue
        if existing.get("target") != record["target"]:
            continue
        if existing.get("yclid") != record["yclid"]:
            continue
        if existing.get("lead_id") and existing.get("lead_id") == record.get("lead_id"):
            return existing
        if existing.get("crm_lead_id") and existing.get("crm_lead_id") == record.get("crm_lead_id"):
            return existing
    return None


def _refresh_existing_record(existing: dict[str, Any], record: dict[str, Any]) -> None:
    existing["current_crm_status"] = record["current_crm_status"]
    if not existing.get("crm_lead_id") and record.get("crm_lead_id"):
        existing["crm_lead_id"] = record["crm_lead_id"]
    if not existing.get("lead_id") and record.get("lead_id"):
        existing["lead_id"] = record["lead_id"]


def _state_record_for_submission(state: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    conversions = state.setdefault("conversions", {})
    key = str(record.get("idempotency_key") or "").strip()
    if not key:
        return record
    existing = conversions.get(key)
    if isinstance(existing, dict):
        return existing
    conversions[key] = record
    return record


def _record_safe_upload_error(
    record: dict[str, Any],
    exc: MetrikaOfflineHTTPError,
    *,
    state: str,
) -> None:
    record["state"] = state
    record["upload_error"] = {
        "kind": exc.kind,
        "http_status": exc.http_status,
        "message": exc.detail,
    }


def _safe_error_detail(value: object, token: str) -> str:
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value or "")
    if token:
        text = text.replace(token, "[redacted]")
    text = re.sub(r"OAuth\s+[A-Za-z0-9._~+/=-]+", "OAuth [redacted]", text)
    return text[:500]


def _read_http_error_body(exc: urllib.error.HTTPError) -> bytes:
    try:
        return exc.read()
    except Exception:
        return b""


def _should_lookup_qualification_datetime(record: dict[str, Any]) -> bool:
    if str(record.get("state") or "") in {"submitted", "uncertain"}:
        return False
    return str(record.get("datetime_state") or "") not in DATETIME_LOOKUP_FINAL_STATES


def _apply_qualification_datetime_lookup(
    record: dict[str, Any],
    result: QualificationDateTimeLookupResult,
) -> None:
    record["qualification_datetime"] = result.qualification_datetime
    record["datetime_source"] = result.datetime_source
    record["datetime_state"] = result.datetime_state

    if result.datetime_state == DATETIME_STATE_LOOKUP_FAILED:
        record["state"] = "failed"
        record["datetime_error"] = {
            "kind": result.error_kind,
            "http_status": result.error_status,
            "detail": result.error_detail,
        }
    else:
        record.pop("datetime_error", None)


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
