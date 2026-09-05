from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import time
import urllib.parse
from typing import Any

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

UTC = dt.timezone.utc
COUNTER_TZ = dt.timezone(dt.timedelta(hours=3))


def collect_visit_time_diagnostic(
    client: MetrikaLogsReadOnlyClient,
    *,
    lead_timestamp_utc: int,
    date1: str,
    date2: str,
    window_minutes: int = 120,
    sample_limit: int = 20,
    utm_source: str = "",
    utm_medium: str = "",
    utm_campaign: str = "",
    utm_term: str = "",
    poll_seconds: float = 2.0,
    max_polls: int = 60,
) -> dict[str, Any]:
    access = access_diagnostic(client)
    if access.get("token_access_status") != "ok" or access.get("counter_access_status") != "ok":
        return {"status": "blocked", "access": access, "source": "visits"}

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

    lead_dt = dt.datetime.fromtimestamp(int(lead_timestamp_utc), UTC)
    candidates: list[dict[str, Any]] = []
    for row in rows:
        candidate = _candidate(row, lead_dt, window_minutes)
        if candidate is not None:
            candidates.append(candidate)
    candidates.sort(key=lambda item: abs(int(item["delta_seconds_from_lead_utc"])))

    return {
        "status": "ok",
        "source": "visits",
        "matching_mode": "time_utm_heuristic",
        "exact_yclid_match_available": False,
        "request_id": current.request_id,
        "lead_timestamp_utc": int(lead_timestamp_utc),
        "lead_timestamp_utc_iso": lead_dt.isoformat().replace("+00:00", "Z"),
        "date1": date1,
        "date2": date2,
        "window_minutes": int(window_minutes),
        "rows_total": len(rows),
        "candidates_total": len(candidates),
        "window_counts": _window_counts(rows, lead_dt),
        "utm_filter": {
            "ym:s:lastUTMSource": str(utm_source),
            "ym:s:lastUTMMedium": str(utm_medium),
            "ym:s:lastUTMCampaign": str(utm_campaign),
            "ym:s:lastUTMTerm": str(utm_term),
        },
        "utm_filter_matches": sum(
            1
            for item in candidates
            if _utm_matches(item["utm"], source=utm_source, medium=utm_medium, campaign=utm_campaign, term=utm_term)
        ),
        "nearest_candidates": candidates[:sample_limit],
    }


def _candidate(row: dict[str, str], lead_dt: dt.datetime, window_minutes: int) -> dict[str, Any] | None:
    visit_dt = _parse_utc(row.get("ym:s:dateTimeUTC", ""))
    if visit_dt is None:
        visit_dt = _parse_counter_tz(row.get("ym:s:dateTime", ""))
    if visit_dt is None:
        return None
    delta = int((visit_dt - lead_dt).total_seconds())
    if abs(delta) > int(window_minutes) * 60:
        return None
    return {
        "ym:s:visitID": row.get("ym:s:visitID", ""),
        "ym:s:dateTime": row.get("ym:s:dateTime", ""),
        "ym:s:dateTimeUTC": row.get("ym:s:dateTimeUTC", ""),
        "ym:s:clientID": row.get("ym:s:clientID", ""),
        "delta_seconds_from_lead_utc": delta,
        "start_url_sanitized": _sanitize_url(row.get("ym:s:startURL", "")),
        "end_url_sanitized": _sanitize_url(row.get("ym:s:endURL", "")),
        "referer_sanitized": _sanitize_url(row.get("ym:s:referer", "")),
        "direct": {field: row.get(field, "") for field in DIRECT_FIELDS},
        "utm": {field: row.get(field, "") for field in UTM_FIELDS},
        "source": {field: row.get(field, "") for field in SOURCE_FIELDS},
    }


def _window_counts(rows: list[dict[str, str]], lead_dt: dt.datetime) -> dict[str, int]:
    counts = {"5m": 0, "15m": 0, "30m": 0, "60m": 0, "120m": 0}
    for row in rows:
        visit_dt = _parse_utc(row.get("ym:s:dateTimeUTC", "")) or _parse_counter_tz(row.get("ym:s:dateTime", ""))
        if visit_dt is None:
            continue
        delta = abs(int((visit_dt - lead_dt).total_seconds()))
        if delta <= 5 * 60:
            counts["5m"] += 1
        if delta <= 15 * 60:
            counts["15m"] += 1
        if delta <= 30 * 60:
            counts["30m"] += 1
        if delta <= 60 * 60:
            counts["60m"] += 1
        if delta <= 120 * 60:
            counts["120m"] += 1
    return counts


def _parse_utc(value: str) -> dt.datetime | None:
    parsed = _parse_naive_datetime(value)
    if parsed is None:
        return None
    return parsed.replace(tzinfo=UTC)


def _parse_counter_tz(value: str) -> dt.datetime | None:
    parsed = _parse_naive_datetime(value)
    if parsed is None:
        return None
    return parsed.replace(tzinfo=COUNTER_TZ).astimezone(UTC)


def _parse_naive_datetime(value: str) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _sanitize_url(value: str) -> dict[str, object]:
    try:
        parsed = urllib.parse.urlsplit(str(value))
        keys: list[str] = []
        for key, _val in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
            key = str(key)
            if key not in keys:
                keys.append(key)
        return {
            "host": parsed.hostname or "",
            "path": parsed.path or "/",
            "query_keys": keys,
            "has_query": bool(keys),
        }
    except Exception:
        return {"host": "", "path": "", "query_keys": [], "has_query": False}


def _utm_matches(utm: dict[str, str], *, source: str, medium: str, campaign: str, term: str) -> bool:
    expected = {
        "ym:s:lastUTMSource": source,
        "ym:s:lastUTMMedium": medium,
        "ym:s:lastUTMCampaign": campaign,
        "ym:s:lastUTMTerm": term,
    }
    for key, value in expected.items():
        value = str(value or "").strip()
        if value and str(utm.get(key, "")).strip() != value:
            return False
    return True


def _safe_reason(value: object) -> str:
    text = str(value).replace("\n", " ").replace("\r", " ")
    text = re.sub(r"(OAuth|Bearer)\s+[A-Za-z0-9._~+/=-]+", r"\1 [redacted]", text)
    return text[:200]


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe read-only diagnostic of nearest Metrika visits by lead timestamp")
    parser.add_argument("--counter-id", type=int, default=DEFAULT_COUNTER_ID)
    parser.add_argument("--lead-timestamp-utc", type=int, required=True)
    parser.add_argument("--date1", default="2026-09-01")
    parser.add_argument("--date2", default="2026-09-03")
    parser.add_argument("--window-minutes", type=int, default=120)
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--utm-source", default="")
    parser.add_argument("--utm-medium", default="")
    parser.add_argument("--utm-campaign", default="")
    parser.add_argument("--utm-term", default="")
    args = parser.parse_args()

    token = os.environ.get("YANDEX_METRIKA_READ_TOKEN", "").strip()
    if not token:
        print(json.dumps({"status": "blocked", "reason": "missing_read_token"}, ensure_ascii=False))
        return 2

    try:
        result = collect_visit_time_diagnostic(
            MetrikaLogsReadOnlyClient(token, counter_id=args.counter_id),
            lead_timestamp_utc=args.lead_timestamp_utc,
            date1=args.date1,
            date2=args.date2,
            window_minutes=args.window_minutes,
            sample_limit=args.sample_limit,
            utm_source=args.utm_source,
            utm_medium=args.utm_medium,
            utm_campaign=args.utm_campaign,
            utm_term=args.utm_term,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("status") == "ok" else 1
    except Exception as exc:
        print(json.dumps({"status": "error", "reason": _safe_reason(exc)}, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
