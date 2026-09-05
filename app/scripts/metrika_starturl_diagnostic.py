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

FIELDS = (
    "ym:s:visitID",
    "ym:s:dateTime",
    "ym:s:dateTimeUTC",
    "ym:s:startURL",
    "ym:s:lastDirectClickOrder",
    "ym:s:lastDirectBannerGroup",
    "ym:s:lastDirectClickBanner",
    "ym:s:lastUTMSource",
    "ym:s:lastUTMMedium",
    "ym:s:lastUTMCampaign",
    "ym:s:lastUTMContent",
    "ym:s:lastUTMTerm",
)


def _sanitize_start_url(value: str) -> dict[str, object]:
    try:
        parsed = urllib.parse.urlsplit(str(value))
        pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        keys: list[str] = []
        yclids: list[str] = []
        for key, val in pairs:
            key = str(key)
            if key not in keys:
                keys.append(key)
            if key == "yclid":
                yclids.append(str(val))
        return {
            "host": parsed.hostname or "",
            "path": parsed.path or "/",
            "query_keys": keys,
            "has_yclid": bool(yclids),
            "yclid_values": yclids,
        }
    except Exception:
        return {"host": "", "path": "", "query_keys": [], "has_yclid": False, "yclid_values": []}


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

    start_urls = [row.get("ym:s:startURL", "") for row in rows if row.get("ym:s:startURL", "")]
    sanitized = [_sanitize_start_url(url) for url in start_urls]
    with_yclid = [item for item in sanitized if item["has_yclid"]]

    return {
        "status": "ok",
        "access": access,
        "request_id": current.request_id,
        "rows_total": len(rows),
        "start_urls_total": len(start_urls),
        "start_urls_with_yclid": len(with_yclid),
        "yclid_share": (len(with_yclid) / len(start_urls)) if start_urls else 0.0,
        "sample_start_urls": sanitized[:sample_limit],
        "sample_with_yclid": with_yclid[:sample_limit],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe read-only diagnostic of yclid presence in Metrika visit startURL")
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
