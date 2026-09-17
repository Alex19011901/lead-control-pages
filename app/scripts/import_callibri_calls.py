#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import ssl
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote_plus
from urllib.request import Request, urlopen

MOSCOW = timezone(timedelta(hours=3))

PHONE_KEYS = (
    "phone",
    "client_phone",
    "caller_phone",
    "caller",
    "visitor_phone",
    "from",
    "src_phone",
    "client",
    "telephone",
    "tel",
    "номер",
    "телефон",
    "номер клиента",
)
STARTED_AT_KEYS = (
    "started_at",
    "start_time",
    "call_start",
    "call_started_at",
    "created_at",
    "date",
    "datetime",
    "time",
    "дата",
    "время",
    "дата звонка",
)
CALL_ID_KEYS = ("id", "call_id", "uuid", "external_id", "request_id", "звонок id")
TEXT_KEYS = (
    "url",
    "landing",
    "page",
    "referrer",
    "referer",
    "utm_content",
    "callibri",
    "source",
    "Источник",
    "источник",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=os.getenv("CALLIBRI_CALLS_FILE", ""))
    parser.add_argument("--url", default=os.getenv("CALLIBRI_CALLS_URL", ""))
    parser.add_argument("--output", required=True)
    parser.add_argument("--date-from", default=os.getenv("CALLIBRI_DATE_FROM", "2026-09-05"))
    parser.add_argument("--date-to", default=os.getenv("CALLIBRI_DATE_TO", ""))
    return parser.parse_args()


def normalize_phone(value: Any) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if len(digits) == 11 and digits.startswith("8"):
        return f"7{digits[1:]}"
    return digits


def hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def first_value(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    lowered = {str(key).strip().casefold(): value for key, value in row.items()}
    for key in keys:
        value = row.get(key)
        if value:
            return str(value).strip()
        value = lowered.get(key.casefold())
        if value:
            return str(value).strip()
    return ""


def query_values_from_text(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for candidate in (text, unquote_plus(text)):
        for match in re.finditer(r"(?:^|[?&\s])([a-zA-Z][a-zA-Z0-9_]*?)=([^&\s]+)", candidate):
            key = match.group(1).strip()
            value = unquote_plus(match.group(2).strip())
            if key and value and key not in result:
                result[key] = value
    return result


def callibri_ids(value: Any) -> dict[str, str]:
    decoded = unquote_plus(str(value or ""))
    result: dict[str, str] = {}
    for marker, key in (("yd_c", "campaign_id"), ("gb", "group_id"), ("ad", "ad_id")):
        match = re.search(rf"(?:^|_){re.escape(marker)}:([0-9]+)(?:_|$)", decoded, flags=re.I)
        if match:
            result[key] = match.group(1)
    return result


def direct_id(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value and re.fullmatch(r"\d+", value):
            return value
    return ""


def parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d{10}", text):
        return datetime.fromtimestamp(int(text), tz=timezone.utc).astimezone(MOSCOW)
    if re.fullmatch(r"\d{13}", text):
        return datetime.fromtimestamp(int(text) / 1000, tz=timezone.utc).astimezone(MOSCOW)
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        return parsed.astimezone(MOSCOW) if parsed.tzinfo else parsed.replace(tzinfo=MOSCOW)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=MOSCOW)
        except ValueError:
            pass
    return None


def parse_duration(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d+", text):
        return int(text)
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", text)
    if not match:
        return None
    first = int(match.group(1))
    second = int(match.group(2))
    third = int(match.group(3) or 0)
    return first * 3600 + second * 60 + third if match.group(3) else first * 60 + second


def load_source(args: argparse.Namespace) -> tuple[str, str]:
    if args.input:
        path = Path(args.input)
        for encoding in ("utf-8-sig", "utf-8", "cp1251"):
            try:
                return f"file:{path}", path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                pass
        return f"file:{path}", path.read_text(encoding="utf-8", errors="replace")
    if not args.url:
        return "not_configured", ""
    headers = {"User-Agent": "lead-control-callibri-import"}
    token = os.getenv("CALLIBRI_TOKEN", "").strip()
    if token:
        header_name = os.getenv("CALLIBRI_AUTH_HEADER", "Authorization").strip() or "Authorization"
        header_value = os.getenv("CALLIBRI_AUTH_VALUE", "").strip() or f"Bearer {token}"
        headers[header_name] = header_value
    request = Request(args.url, headers=headers)
    with urlopen(request, timeout=45, context=ssl.create_default_context()) as response:
        return args.url, response.read().decode("utf-8-sig")


def raw_rows(text: str) -> list[dict[str, Any]]:
    if not text.strip():
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(text.splitlines(), dialect=dialect)
        return [dict(row) for row in reader]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("calls", "items", "data", "results", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return [payload]


def all_text(row: dict[str, Any]) -> str:
    chunks = []
    for key in TEXT_KEYS:
        value = first_value(row, (key,))
        if value:
            chunks.append(value)
    chunks.extend(str(value) for value in row.values() if isinstance(value, str) and ("callibri" in value.lower() or "utm_" in value.lower()))
    return "\n".join(chunks)


def safe_call(row: dict[str, Any]) -> dict[str, Any] | None:
    phone = normalize_phone(first_value(row, PHONE_KEYS))
    started_at = parse_datetime(first_value(row, STARTED_AT_KEYS))
    if not phone or not started_at:
        return None
    text = all_text(row)
    query = query_values_from_text(text)
    callibri = str(row.get("callibri") or query.get("callibri") or "").strip()
    ids = callibri_ids(callibri)
    campaign_id = direct_id(row, "campaign_id", "campaignId", "ya_campaign_id", "yandex_campaign_id", "yd_c") or ids.get("campaign_id", "")
    group_id = direct_id(row, "group_id", "groupId", "ad_group_id", "adGroupId", "gb") or ids.get("group_id", "")
    ad_id = direct_id(row, "ad_id", "adId", "banner_id", "bannerId", "ad") or ids.get("ad_id", "")
    call_id = first_value(row, CALL_ID_KEYS)
    stable_id = call_id or f"{phone}:{started_at.isoformat()}:{campaign_id}:{group_id}:{ad_id}"
    return {
        "call_id_sha256": hash_value(stable_id),
        "started_at": started_at.isoformat(),
        "phone_sha256": hash_value(phone),
        "duration_seconds": parse_duration(row.get("duration") or row.get("duration_seconds") or row.get("длительность")),
        "status": str(row.get("status") or row.get("call_status") or row.get("статус") or ""),
        "direction": str(row.get("direction") or row.get("type") or row.get("тип") or ""),
        "utm_source": str(row.get("utm_source") or query.get("utm_source") or ""),
        "utm_medium": str(row.get("utm_medium") or query.get("utm_medium") or ""),
        "utm_campaign": str(row.get("utm_campaign") or query.get("utm_campaign") or ""),
        "utm_term": str(row.get("utm_term") or query.get("utm_term") or ""),
        "campaign_id": campaign_id,
        "group_id": group_id,
        "ad_id": ad_id,
        "has_callibri": bool(callibri or campaign_id or group_id or ad_id),
    }


def in_period(item: dict[str, Any], date_from: date, date_to: date | None) -> bool:
    started_at = parse_datetime(item.get("started_at"))
    if not started_at:
        return False
    item_date = started_at.date()
    if item_date < date_from:
        return False
    return date_to is None or item_date <= date_to


def write_payload(output: Path, payload: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    output = Path(args.output)
    date_from = date.fromisoformat(args.date_from)
    date_to = date.fromisoformat(args.date_to) if args.date_to else None
    if not args.input and not args.url:
        write_payload(output, {
            "schema_version": 1,
            "status": "missing_source",
            "message": "Set CALLIBRI_CALLS_URL or CALLIBRI_CALLS_FILE to import calls.",
            "date_from": args.date_from,
            "date_to": args.date_to or None,
            "call_count": 0,
            "calls": [],
        })
        return 0
    try:
        source, text = load_source(args)
        calls = [item for row in raw_rows(text) if (item := safe_call(row))]
    except Exception as exc:  # noqa: BLE001 - keep public refresh resilient.
        write_payload(output, {
            "schema_version": 1,
            "status": "error",
            "message": str(exc),
            "date_from": args.date_from,
            "date_to": args.date_to or None,
            "call_count": 0,
            "calls": [],
        })
        return 0
    calls = [item for item in calls if in_period(item, date_from, date_to)]
    calls.sort(key=lambda item: (item.get("started_at") or "", item.get("call_id_sha256") or ""))
    write_payload(output, {
        "schema_version": 1,
        "status": "ok",
        "source": source,
        "date_from": args.date_from,
        "date_to": args.date_to or None,
        "call_count": len(calls),
        "calls": calls,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
