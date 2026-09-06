#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from metrika_logs_readonly import (
    DEFAULT_ATTRIBUTION,
    DEFAULT_COUNTER_ID,
    LogsApiError,
    MetrikaLogsReadOnlyClient,
    parse_tsv,
)

FIELDS = (
    "ym:s:visitID",
    "ym:s:dateTime",
    "ym:s:dateTimeUTC",
    "ym:s:visitDuration",
    "ym:s:clientID",
    "ym:s:lastDirectClickOrder",
    "ym:s:lastDirectBannerGroup",
    "ym:s:lastDirectClickBanner",
    "ym:s:lastDirectClickOrderName",
    "ym:s:lastClickBannerGroupName",
    "ym:s:lastDirectClickBannerName",
    "ym:s:lastDirectPhraseOrCond",
    "ym:s:lastDirectPlatformType",
    "ym:s:lastDirectPlatform",
)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def normalize_id(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text in {"", "0", "0.0"} else text


def safe_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    exported: list[dict[str, Any]] = []
    for row in rows:
        client_id = str(row.get("ym:s:clientID") or "").strip()
        if not client_id:
            continue
        campaign_id = normalize_id(row.get("ym:s:lastDirectClickOrder"))
        group_id = normalize_id(row.get("ym:s:lastDirectBannerGroup"))
        ad_id = normalize_id(row.get("ym:s:lastDirectClickBanner"))
        if not (campaign_id or group_id or ad_id):
            continue
        duration_raw = str(row.get("ym:s:visitDuration") or "0").strip()
        try:
            duration = max(0, int(float(duration_raw)))
        except ValueError:
            duration = 0
        exported.append(
            {
                "client_id_sha256": sha256_text(client_id),
                "visit_datetime": str(row.get("ym:s:dateTime") or ""),
                "visit_datetime_utc": str(row.get("ym:s:dateTimeUTC") or ""),
                "visit_duration_seconds": duration,
                "campaign_id": campaign_id,
                "group_id": group_id,
                "ad_id": ad_id,
                "campaign_name": str(row.get("ym:s:lastDirectClickOrderName") or ""),
                "group_name": str(row.get("ym:s:lastClickBannerGroupName") or ""),
                "ad_name": str(row.get("ym:s:lastDirectClickBannerName") or ""),
                "criterion": str(row.get("ym:s:lastDirectPhraseOrCond") or ""),
                "platform_type": str(row.get("ym:s:lastDirectPlatformType") or ""),
                "platform": str(row.get("ym:s:lastDirectPlatform") or ""),
            }
        )
    exported.sort(key=lambda item: (item["client_id_sha256"], item["visit_datetime"]))
    return exported


def collect(client: MetrikaLogsReadOnlyClient, *, date1: str, date2: str, poll_seconds: float, max_polls: int) -> dict[str, Any]:
    client.evaluate(date1=date1, date2=date2, fields=FIELDS, attribution=DEFAULT_ATTRIBUTION, source="visits")
    request = client.create_export(date1=date1, date2=date2, fields=FIELDS, attribution=DEFAULT_ATTRIBUTION, source="visits")
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
    mapped = safe_rows(rows)
    return {
        "schema_version": 1,
        "counter_id": client.counter_id,
        "date1": date1,
        "date2": date2,
        "attribution": DEFAULT_ATTRIBUTION,
        "request_id": current.request_id,
        "rows_total": len(rows),
        "mapped_rows": len(mapped),
        "rows": mapped,
    }


def default_date() -> str:
    moscow = timezone(timedelta(hours=3))
    return (datetime.now(moscow).date() - timedelta(days=1)).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a privacy-safe ClientID->Direct attribution map from Metrika Logs API")
    parser.add_argument("--counter-id", type=int, default=DEFAULT_COUNTER_ID)
    parser.add_argument("--date1", default=default_date())
    parser.add_argument("--date2", default="")
    parser.add_argument("--output", default="runtime-data/metrika_attribution_map.json")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--max-polls", type=int, default=60)
    args = parser.parse_args()
    date2 = args.date2 or args.date1

    token = os.environ.get("YANDEX_METRIKA_READ_TOKEN", "").strip()
    if not token:
        raise SystemExit("YANDEX_METRIKA_READ_TOKEN is required")
    client = MetrikaLogsReadOnlyClient(token, counter_id=args.counter_id)
    payload = collect(client, date1=args.date1, date2=date2, poll_seconds=args.poll_seconds, max_polls=args.max_polls)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Metrika attribution map written: {output}")
    print(f"Rows: {payload['mapped_rows']}/{payload['rows_total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
