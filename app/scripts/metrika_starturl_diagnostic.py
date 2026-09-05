from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse

from scripts.metrika_logs_readonly import (
    DEFAULT_ATTRIBUTION,
    DEFAULT_COUNTER_ID,
    LogsApiError,
    MetrikaLogsReadOnlyClient,
    access_diagnostic,
    parse_tsv,
)

DIRECT_FIELDS = (
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
)

UTM_FIELDS = (
    "ym:s:lastUTMSource",
    "ym:s:lastUTMMedium",
    "ym:s:lastUTMCampaign",
    "ym:s:lastUTMContent",
    "ym:s:lastUTMTerm",
)

SOURCE_FIELDS = (
    "ym:s:lastTrafficSource",
    "ym:s:lastAdvEngine",
    "ym:s:lastSearchEngineRoot",
    "ym:s:lastSearchEngine",
    "ym:s:from",
)

URL_FIELDS = (
    "ym:s:startURL",
    "ym:s:endURL",
    "ym:s:referer",
)

FIELDS = (
    "ym:s:visitID",
    "ym:s:dateTime",
    "ym:s:dateTimeUTC",
    "ym:s:clientID",
    *URL_FIELDS,
    *DIRECT_FIELDS,
    *UTM_FIELDS,
    *SOURCE_FIELDS,
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


def collect_starturl_diagnostic(
    client: MetrikaLogsReadOnlyClient,
    *,
    date1: str,
    date2: str,
    sample_limit: int = 12,
    poll_seconds: float = 2.0,
    max_polls: int = 60,
) -> dict[str, object]:
    access = access_diagnostic(client)
    if access.get("token_access_status") != "ok" or access.get("counter_access_status") != "ok":
        return {"status": "blocked", "access": access}

    client.evaluate(date1=date1, date2=date2, fields=FIELDS, attribution=DEFAULT_ATTRIBUTION)
    request = client.create_export(date1=date1, date2=date2, fields=FIELDS, attribution=DEFAULT_ATTRIBUTION)
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

    start_urls = [row.get("ym:s:startURL", "") for row in rows if str(row.get("ym:s:startURL", "")).strip()]
    sanitized = [_sanitize_url(url) for url in start_urls]
    with_yclid = [item for item in sanitized if item["has_yclid"]]

    query_keys: list[str] = []
    for item in sanitized:
        for key in item.get("query_keys", []):
            key = str(key)
            if key not in query_keys:
                query_keys.append(key)

    return {
        "status": "ok",
        "access": access,
        "request_id": current.request_id,
        "rows_total": len(rows),
        "rows_with_startURL": len(start_urls),
        "rows_with_yclid_param": len(with_yclid),
        "sample_start_urls_sanitized": sanitized[:sample_limit],
        "sample_query_keys": query_keys[:100],
        "url_fields_nonempty_counts": _nonempty_counts(rows, URL_FIELDS),
        "direct_fields_nonempty_counts": _nonempty_counts(rows, DIRECT_FIELDS),
        "utm_fields_nonempty_counts": _nonempty_counts(rows, UTM_FIELDS),
        "source_fields_nonempty_counts": _nonempty_counts(rows, SOURCE_FIELDS),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe read-only diagnostic of Metrika visit attribution fields")
    parser.add_argument("--counter-id", type=int, default=DEFAULT_COUNTER_ID)
    parser.add_argument("--date1", default="2026-09-01")
    parser.add_argument("--date2", default="2026-09-03")
    parser.add_argument("--sample-limit", type=int, default=12)
    args = parser.parse_args()

    token = os.environ.get("YANDEX_METRIKA_READ_TOKEN", "").strip()
    if not token:
        print(json.dumps({"status": "blocked", "reason": "missing_read_token"}, ensure_ascii=False))
        return 2

    try:
        result = collect_starturl_diagnostic(
            MetrikaLogsReadOnlyClient(token, counter_id=args.counter_id),
            date1=args.date1,
            date2=args.date2,
            sample_limit=args.sample_limit,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("status") == "ok" else 1
    except Exception as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
