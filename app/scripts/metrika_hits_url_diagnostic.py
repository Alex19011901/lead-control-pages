from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.parse

from scripts.metrika_logs_readonly import (
    DEFAULT_ATTRIBUTION,
    DEFAULT_COUNTER_ID,
    DEFAULT_YCLID,
    LogsApiError,
    MetrikaLogsReadOnlyClient,
    access_diagnostic,
    extract_yclid,
    parse_tsv,
)

IDENTITY_FIELDS = (
    "ym:pv:watchID",
    "ym:pv:pageViewID",
    "ym:pv:visitID",
    "ym:pv:dateTime",
    "ym:pv:clientID",
)

URL_FIELDS = (
    "ym:pv:URL",
    "ym:pv:referer",
)

UTM_FIELDS = (
    "ym:pv:UTMSource",
    "ym:pv:UTMMedium",
    "ym:pv:UTMCampaign",
    "ym:pv:UTMContent",
    "ym:pv:UTMTerm",
)

SOURCE_FIELDS = (
    "ym:pv:lastTrafficSource",
    "ym:pv:lastAdvEngine",
    "ym:pv:from",
)

PARAM_FIELDS = (
    "ym:pv:params",
    "ym:pv:parsedParamsKey1",
    "ym:pv:parsedParamsKey2",
    "ym:pv:parsedParamsKey3",
    "ym:pv:parsedParamsKey4",
    "ym:pv:parsedParamsKey5",
    "ym:pv:parsedParamsKey6",
    "ym:pv:parsedParamsKey7",
    "ym:pv:parsedParamsKey8",
    "ym:pv:parsedParamsKey9",
    "ym:pv:parsedParamsKey10",
)

FIELDS = (
    *IDENTITY_FIELDS,
    *URL_FIELDS,
    *UTM_FIELDS,
    *SOURCE_FIELDS,
    *PARAM_FIELDS,
)


def _sanitize_url(value: str) -> dict[str, object]:
    try:
        parsed = urllib.parse.urlsplit(str(value))
        pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        keys: list[str] = []
        yclid_length = 0
        for key, val in pairs:
            key = str(key)
            if key not in keys:
                keys.append(key)
            if key.lower() == "yclid" and not yclid_length:
                yclid_length = len(str(val))
        return {
            "host": parsed.hostname or "",
            "path": parsed.path or "/",
            "query_keys": keys,
            "has_yclid": yclid_length > 0,
            "yclid_length": yclid_length,
        }
    except Exception:
        return {"host": "", "path": "", "query_keys": [], "has_yclid": False, "yclid_length": 0}


def _nonempty_counts(rows: list[dict[str, str]], fields: tuple[str, ...]) -> dict[str, int]:
    return {field: sum(1 for row in rows if str(row.get(field, "")).strip()) for field in fields}


def _contains_target(value: str, target: str) -> bool:
    return bool(target) and str(target) in str(value)


def _row_yclid_sources(row: dict[str, str], yclid: str) -> list[str]:
    target = str(yclid)
    sources: list[str] = []
    if extract_yclid(row.get("ym:pv:URL", "")) == target:
        sources.append("ym:pv:URL")
    if extract_yclid(row.get("ym:pv:referer", "")) == target:
        sources.append("ym:pv:referer")
    for field in PARAM_FIELDS:
        if _contains_target(row.get(field, ""), target):
            sources.append(field)
    return sources


def _safe_match(row: dict[str, str], yclid: str) -> dict[str, object]:
    result: dict[str, object] = {field: row.get(field, "") for field in IDENTITY_FIELDS}
    result["yclid_sources"] = _row_yclid_sources(row, yclid)
    result["url_sanitized"] = _sanitize_url(row.get("ym:pv:URL", ""))
    result["referer_sanitized"] = _sanitize_url(row.get("ym:pv:referer", ""))
    result["utm"] = {field: row.get(field, "") for field in UTM_FIELDS}
    result["source"] = {field: row.get(field, "") for field in SOURCE_FIELDS}
    result["params_fields_with_yclid"] = [
        field for field in PARAM_FIELDS if _contains_target(row.get(field, ""), str(yclid))
    ]
    return result


def collect_hits_url_diagnostic(
    client: MetrikaLogsReadOnlyClient,
    *,
    yclid: str,
    date1: str,
    date2: str,
    sample_limit: int = 12,
    poll_seconds: float = 2.0,
    max_polls: int = 60,
) -> dict[str, object]:
    access = access_diagnostic(client)
    if access.get("token_access_status") != "ok" or access.get("counter_access_status") != "ok":
        return {"status": "blocked", "access": access, "source": "hits", "yclid": str(yclid)}

    client.evaluate(date1=date1, date2=date2, fields=FIELDS, attribution=DEFAULT_ATTRIBUTION, source="hits")
    request = client.create_export(date1=date1, date2=date2, fields=FIELDS, attribution=DEFAULT_ATTRIBUTION, source="hits")
    current = request
    for _ in range(max_polls + 1):
        if current.status == "processed":
            break
        if current.status in {"canceled", "cleaned_by_user", "cleaned_automatically_as_too_old", "processing_failed"}:
            raise LogsApiError(f"log_request_{current.status}")
        if poll_seconds > 0:
            time.sleep(poll_seconds)
        current = client.status(request.request_id)
    if current.status != "processed":
        raise LogsApiError("log_request_timeout")

    rows: list[dict[str, str]] = []
    for part_number in current.parts:
        rows.extend(parse_tsv(client.download_part(current.request_id, part_number)))

    matches = [row for row in rows if _row_yclid_sources(row, yclid)]
    urls = [row.get("ym:pv:URL", "") for row in rows if str(row.get("ym:pv:URL", "")).strip()]
    sanitized_urls = [_sanitize_url(url) for url in urls]
    query_keys: list[str] = []
    for item in sanitized_urls:
        for key in item.get("query_keys", []):
            key = str(key)
            if key not in query_keys:
                query_keys.append(key)

    return {
        "status": "found" if matches else "not_found",
        "source": "hits",
        "yclid": str(yclid),
        "request_id": current.request_id,
        "rows_total": len(rows),
        "rows_with_url": len(urls),
        "rows_with_url_yclid_param": sum(1 for row in rows if extract_yclid(row.get("ym:pv:URL", ""))),
        "rows_with_referer_yclid_param": sum(1 for row in rows if extract_yclid(row.get("ym:pv:referer", ""))),
        "rows_with_params_yclid_text": sum(
            1 for row in rows if any(_contains_target(row.get(field, ""), str(yclid)) for field in PARAM_FIELDS)
        ),
        "matches_count": len(matches),
        "matches": [_safe_match(row, yclid) for row in matches[:sample_limit]],
        "sample_urls_sanitized": sanitized_urls[:sample_limit],
        "sample_query_keys": query_keys[:100],
        "url_fields_nonempty_counts": _nonempty_counts(rows, URL_FIELDS),
        "utm_fields_nonempty_counts": _nonempty_counts(rows, UTM_FIELDS),
        "source_fields_nonempty_counts": _nonempty_counts(rows, SOURCE_FIELDS),
        "param_fields_nonempty_counts": _nonempty_counts(rows, PARAM_FIELDS),
    }


def _safe_reason(value: object) -> str:
    text = str(value).replace("\n", " ").replace("\r", " ")
    text = re.sub(r"(OAuth|Bearer)\s+[A-Za-z0-9._~+/=-]+", r"\1 [redacted]", text)
    return text[:200]


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe read-only diagnostic of Metrika pageview URL fields")
    parser.add_argument("--counter-id", type=int, default=DEFAULT_COUNTER_ID)
    parser.add_argument("--yclid", default=DEFAULT_YCLID)
    parser.add_argument("--date1", default="2026-09-01")
    parser.add_argument("--date2", default="2026-09-03")
    parser.add_argument("--sample-limit", type=int, default=12)
    args = parser.parse_args()

    token = os.environ.get("YANDEX_METRIKA_READ_TOKEN", "").strip()
    if not token:
        print(json.dumps({"status": "blocked", "reason": "missing_read_token"}, ensure_ascii=False))
        return 2

    try:
        result = collect_hits_url_diagnostic(
            MetrikaLogsReadOnlyClient(token, counter_id=args.counter_id),
            yclid=args.yclid,
            date1=args.date1,
            date2=args.date2,
            sample_limit=args.sample_limit,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("status") in {"found", "not_found"} else 1
    except Exception as exc:
        print(json.dumps({"status": "error", "reason": _safe_reason(exc)}, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
