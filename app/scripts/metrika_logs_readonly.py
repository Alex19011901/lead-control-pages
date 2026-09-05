from __future__ import annotations

import argparse
import csv
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable

API_BASE = "https://api-metrika.yandex.net/management/v1"
DEFAULT_COUNTER_ID = 112267492
DEFAULT_YCLID = "5288069203188252671"
DEFAULT_DATE1 = "2026-09-03"
DEFAULT_DATE2 = "2026-09-03"
DEFAULT_ATTRIBUTION = "LAST_YANDEX_DIRECT_CLICK"

# Isolated diagnostic field set only. Nothing here changes Metrika or Direct entities.
DEFAULT_FIELDS = (
    "ym:s:visitID",
    "ym:s:dateTime",
    "ym:s:dateTimeUTC",
    "ym:s:clientID",
    "ym:s:startURL",
    "ym:s:lastDirectClickOrder",
    "ym:s:lastDirectBannerGroup",
    "ym:s:lastDirectClickBanner",
    "ym:s:lastDirectClickOrderName",
    "ym:s:lastClickBannerGroupName",
    "ym:s:lastDirectClickBannerName",
    "ym:s:lastDirectPhraseOrCond",
    "ym:s:lastDirectPlatformType",
    "ym:s:lastDirectPlatform",
    "ym:s:lastDirectConditionType",
    "ym:s:lastUTMCampaign",
    "ym:s:lastUTMContent",
    "ym:s:lastUTMMedium",
    "ym:s:lastUTMSource",
    "ym:s:lastUTMTerm",
)


class LogsApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class LogRequest:
    request_id: int
    status: str
    parts: tuple[int, ...]


class MetrikaLogsReadOnlyClient:
    """Allow-listed Logs API client.

    The only POST operation is creation of a Logs API export request.
    No offline-conversion, goal, counter, campaign, ad, bid, budget, PUT,
    PATCH or DELETE operation exists in this client.
    """

    def __init__(self, token: str, counter_id: int = DEFAULT_COUNTER_ID, timeout: int = 30) -> None:
        token = token.strip()
        if not token:
            raise ValueError("YANDEX_METRIKA_READ_TOKEN is required")
        self._token = token
        self.counter_id = int(counter_id)
        self.timeout = int(timeout)

    def evaluate(self, *, date1: str, date2: str, fields: Iterable[str], attribution: str = DEFAULT_ATTRIBUTION) -> dict[str, Any]:
        query = self._export_query(date1=date1, date2=date2, fields=fields, attribution=attribution)
        return self._json("GET", f"/counter/{self.counter_id}/logrequests/evaluate", query)

    def create_export(self, *, date1: str, date2: str, fields: Iterable[str], attribution: str = DEFAULT_ATTRIBUTION) -> LogRequest:
        query = self._export_query(date1=date1, date2=date2, fields=fields, attribution=attribution)
        payload = self._json("POST", f"/counter/{self.counter_id}/logrequests", query)
        return _parse_log_request(payload)

    def status(self, request_id: int) -> LogRequest:
        payload = self._json("GET", f"/counter/{self.counter_id}/logrequest/{int(request_id)}", None)
        return _parse_log_request(payload)

    def download_part(self, request_id: int, part_number: int) -> str:
        return self._text(
            "GET",
            f"/counter/{self.counter_id}/logrequest/{int(request_id)}/part/{int(part_number)}/download",
            None,
        )

    def _export_query(self, *, date1: str, date2: str, fields: Iterable[str], attribution: str) -> dict[str, str]:
        field_list = [str(field).strip() for field in fields if str(field).strip()]
        if not field_list:
            raise ValueError("fields are required")
        return {
            "date1": str(date1),
            "date2": str(date2),
            "fields": ",".join(field_list),
            "source": "visits",
            "attribution": str(attribution),
        }

    def _json(self, method: str, path: str, query: dict[str, str] | None) -> dict[str, Any]:
        text = self._text(method, path, query)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LogsApiError("invalid_json") from exc
        if not isinstance(payload, dict):
            raise LogsApiError("invalid_payload")
        return payload

    def _text(self, method: str, path: str, query: dict[str, str] | None) -> str:
        method = method.upper()
        if method not in {"GET", "POST"}:
            raise LogsApiError("method_not_allowed")
        if not _allowed_path(method, path):
            raise LogsApiError("endpoint_not_allowed")
        url = API_BASE + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(
            url,
            method=method,
            headers={"Authorization": f"OAuth {self._token}", "Accept": "application/json"},
            data=b"" if method == "POST" else None,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            # Safe diagnostic only: HTTP code and standard reason phrase.
            # Never include URL, headers, response body, or token.
            reason = str(exc.reason or "HTTPError").replace("\n", " ").replace("\r", " ")[:120]
            raise LogsApiError(f"http_{int(exc.code)}:{reason}") from None
        except Exception as exc:
            # Never include headers/token in diagnostics.
            raise LogsApiError(type(exc).__name__) from None


def _allowed_path(method: str, path: str) -> bool:
    segments = [part for part in path.split("/") if part]
    # /counter/{id}/logrequests/evaluate
    if method == "GET" and len(segments) == 4 and segments[0] == "counter" and segments[2] == "logrequests" and segments[3] == "evaluate":
        return segments[1].isdigit()
    # POST /counter/{id}/logrequests -- technical export creation only.
    if method == "POST" and len(segments) == 3 and segments[0] == "counter" and segments[2] == "logrequests":
        return segments[1].isdigit()
    # GET /counter/{id}/logrequest/{requestId}
    if method == "GET" and len(segments) == 4 and segments[0] == "counter" and segments[2] == "logrequest":
        return segments[1].isdigit() and segments[3].isdigit()
    # GET /counter/{id}/logrequest/{requestId}/part/{partNumber}/download
    if method == "GET" and len(segments) == 7 and segments[0] == "counter" and segments[2] == "logrequest" and segments[4] == "part" and segments[6] == "download":
        return segments[1].isdigit() and segments[3].isdigit() and segments[5].isdigit()
    return False


def _parse_log_request(payload: dict[str, Any]) -> LogRequest:
    item = payload.get("log_request")
    if not isinstance(item, dict):
        raise LogsApiError("missing_log_request")
    request_id = int(item.get("request_id"))
    status = str(item.get("status") or "")
    parts_raw = item.get("parts") or []
    parts: list[int] = []
    if isinstance(parts_raw, list):
        for part in parts_raw:
            if isinstance(part, dict) and part.get("part_number") is not None:
                parts.append(int(part["part_number"]))
    return LogRequest(request_id=request_id, status=status, parts=tuple(parts))


def extract_yclid(url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(str(url))
        values = urllib.parse.parse_qs(parsed.query, keep_blank_values=True).get("yclid", [])
        return str(values[0]) if values else ""
    except Exception:
        return ""


def parse_tsv(text: str) -> list[dict[str, str]]:
    if not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    return [{str(k): str(v or "") for k, v in row.items()} for row in reader]


def find_by_yclid(rows: Iterable[dict[str, str]], yclid: str) -> list[dict[str, str]]:
    target = str(yclid)
    return [row for row in rows if extract_yclid(row.get("ym:s:startURL", "")) == target]


def safe_diagnostic(matches: list[dict[str, str]], *, yclid: str, request_id: int | None = None) -> dict[str, Any]:
    allowed = set(DEFAULT_FIELDS)
    safe_matches = [{key: row.get(key, "") for key in DEFAULT_FIELDS if key in allowed} for row in matches]
    return {
        "status": "found" if safe_matches else "not_found",
        "yclid": str(yclid),
        "request_id": request_id,
        "matches_count": len(safe_matches),
        "visits": safe_matches,
    }


def collect(
    client: MetrikaLogsReadOnlyClient,
    *,
    yclid: str,
    date1: str,
    date2: str,
    fields: Iterable[str] = DEFAULT_FIELDS,
    attribution: str = DEFAULT_ATTRIBUTION,
    poll_seconds: float = 2.0,
    max_polls: int = 30,
) -> dict[str, Any]:
    # Evaluate is read-only. Creation is the only stateful read-export operation.
    client.evaluate(date1=date1, date2=date2, fields=fields, attribution=attribution)
    request = client.create_export(date1=date1, date2=date2, fields=fields, attribution=attribution)
    current = request
    for _ in range(max_polls + 1):
        if current.status == "processed":
            break
        if current.status in {"canceled", "cleaned_by_user", "cleaned_automatically_as_too_old", "processing_failed"}:
            raise LogsApiError(f"log_request_{current.status}")
        if poll_seconds > 0:
            time.sleep(poll_seconds)
        current = client.status(request.request_id)
    else:
        raise LogsApiError("log_request_timeout")
    if current.status != "processed":
        raise LogsApiError("log_request_timeout")

    rows: list[dict[str, str]] = []
    for part_number in current.parts:
        rows.extend(parse_tsv(client.download_part(current.request_id, part_number)))
    matches = find_by_yclid(rows, yclid)
    return safe_diagnostic(matches, yclid=yclid, request_id=current.request_id)


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated Yandex Metrica Logs API read-export diagnostic")
    parser.add_argument("--counter-id", type=int, default=DEFAULT_COUNTER_ID)
    parser.add_argument("--yclid", default=DEFAULT_YCLID)
    parser.add_argument("--date1", default=DEFAULT_DATE1)
    parser.add_argument("--date2", default=DEFAULT_DATE2)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--max-polls", type=int, default=30)
    args = parser.parse_args()

    token = os.environ.get("YANDEX_METRIKA_READ_TOKEN", "").strip()
    if not token:
        print(json.dumps({"status": "blocked", "reason": "missing_read_token"}, ensure_ascii=False))
        return 2

    try:
        result = collect(
            MetrikaLogsReadOnlyClient(token, counter_id=args.counter_id),
            yclid=args.yclid,
            date1=args.date1,
            date2=args.date2,
            poll_seconds=args.poll_seconds,
            max_polls=args.max_polls,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
