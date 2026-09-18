#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import ssl
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, unquote_plus, urlsplit, urlunsplit
from urllib.request import Request, urlopen

MOSCOW = timezone(timedelta(hours=3))
API_SLEEP_SECONDS = 1.05

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
CALL_ID_KEYS = ("id", "call_id", "uuid", "external_id", "request_id", "conversations_number", "lid_id", "звонок id")
ACCURACY_KEYS = ("accurately", "tracking_accurate", "accuracy", "точность")
TEXT_KEYS = (
    "url",
    "landing",
    "landing_page",
    "lid_landing",
    "page",
    "referrer",
    "referer",
    "utm_content",
    "utm_term",
    "query",
    "callibri",
    "source",
    "Источник",
    "источник",
)


def env_value(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=env_value("CALLIBRI_CALLS_FILE", "CALIBRI_CALLS_FILE"))
    parser.add_argument("--url", default=env_value("CALLIBRI_CALLS_URL", "CALIBRI_CALLS_URL"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--date-from", default=env_value("CALLIBRI_DATE_FROM", "CALIBRI_DATE_FROM", default="2026-09-05"))
    parser.add_argument("--date-to", default=env_value("CALLIBRI_DATE_TO", "CALIBRI_DATE_TO"))
    parser.add_argument("--api-base-url", default=env_value("CALLIBRI_API_BASE_URL", "CALIBRI_API_BASE_URL"))
    parser.add_argument("--site-id", default=env_value("CALLIBRI_SITE_ID", "CALIBRI_SITE_ID"))
    parser.add_argument("--site-domain", default=env_value("CALLIBRI_SITE_DOMAIN", "CALIBRI_SITE_DOMAIN"))
    parser.add_argument("--site-name", default=env_value("CALLIBRI_SITE_NAME", "CALIBRI_SITE_NAME"))
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


def yandex_direct_ids_from_text(value: Any) -> dict[str, str]:
    decoded = unquote_plus(str(value or ""))
    result: dict[str, str] = {}
    for marker, key in (("cid", "campaign_id"), ("gid", "group_id"), ("aid", "ad_id")):
        patterns = (
            rf"(?:^|\|){marker}\|([0-9]+)(?:\||$)",
            rf"(?:^|[;,_\-\s]){marker}(?:[:=_-])([0-9]+)(?:$|[;,_\-\s])",
            rf"(?:^|[?&]){marker}=([0-9]+)(?:&|$)",
        )
        for pattern in patterns:
            match = re.search(pattern, decoded, flags=re.I)
            if match:
                result[key] = match.group(1)
                break
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


def parse_tracking_accurate(row: dict[str, Any]) -> bool | None:
    value = first_value(row, ACCURACY_KEYS).casefold()
    if not value:
        return None
    if value in {"нет", "no", "false", "0", "n"}:
        return False
    if value in {"да", "yes", "true", "1", "y"}:
        return True
    return None


def request_text(url: str) -> str:
    headers = {"User-Agent": "lead-control-callibri-import"}
    token = env_value("CALLIBRI_TOKEN", "CALIBRI_TOKEN")
    if token:
        header_name = env_value("CALLIBRI_AUTH_HEADER", "CALIBRI_AUTH_HEADER", default="Authorization")
        header_value = env_value("CALLIBRI_AUTH_VALUE", "CALIBRI_AUTH_VALUE") or f"Bearer {token}"
        headers[header_name] = header_value
    request = Request(url, headers=headers)
    with urlopen(request, timeout=45, context=ssl.create_default_context()) as response:
        return response.read().decode("utf-8-sig")


def redact_url(url: str) -> str:
    split = urlsplit(url)
    if not split.query:
        return url
    sensitive_markers = ("token", "key", "secret", "password", "pass", "auth", "email", "login")
    safe_query = []
    for key, value in parse_qsl(split.query, keep_blank_values=True):
        masked = "***" if any(marker in key.casefold() for marker in sensitive_markers) else value
        safe_query.append((key, masked))
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(safe_query), split.fragment))


def api_auth_params() -> list[tuple[str, str]]:
    result = parse_qsl(env_value("CALLIBRI_API_AUTH_QUERY", "CALIBRI_API_AUTH_QUERY").lstrip("?"), keep_blank_values=False)
    existing_keys = {key for key, _ in result}
    email = env_value("CALLIBRI_API_EMAIL", "CALIBRI_API_EMAIL", "CALLIBRI_EMAIL", "CALIBRI_EMAIL")
    token = env_value("CALLIBRI_API_TOKEN", "CALIBRI_API_TOKEN", "CALLIBRI_TOKEN", "CALIBRI_TOKEN")
    email_key = env_value("CALLIBRI_EMAIL_PARAM", "CALIBRI_EMAIL_PARAM", default="email")
    token_key = env_value("CALLIBRI_TOKEN_PARAM", "CALIBRI_TOKEN_PARAM", default="token")
    if email and email_key not in existing_keys:
        result.append((email_key, email))
    if token and token_key not in existing_keys:
        result.append((token_key, token))
    return result


def append_query(url: str, params: list[tuple[str, Any]]) -> str:
    split = urlsplit(url)
    query = parse_qsl(split.query, keep_blank_values=True)
    query.extend((key, str(value)) for key, value in params if str(value or ""))
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), split.fragment))


def api_endpoint_url(base_url: str, endpoint: str, params: list[tuple[str, Any]]) -> str:
    split = urlsplit(base_url)
    if not split.scheme or not split.netloc:
        raise RuntimeError("CALLIBRI_API_BASE_URL must be a full https:// URL from Callibri API settings.")
    base_path = split.path.rstrip("/")
    endpoint_path = endpoint.strip("/")
    path = f"{base_path}/{endpoint_path}" if base_path else f"/{endpoint_path}"
    url = urlunsplit((split.scheme, split.netloc, path, split.query, ""))
    return append_query(url, [*api_auth_params(), *params])


def fetch_api_json(base_url: str, endpoint: str, params: list[tuple[str, Any]]) -> dict[str, Any] | list[Any]:
    try:
        payload = json.loads(request_text(api_endpoint_url(base_url, endpoint, params)))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Callibri API returned non-JSON response for /{endpoint.strip('/')}") from exc
    if isinstance(payload, dict):
        error = payload.get("error") or payload.get("errors") or payload.get("message")
        if error and "callibri_too_many_requests" in str(error):
            raise RuntimeError("Callibri API rate limit: callibri_too_many_requests.")
    return payload


def site_rows(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    for key in ("sites", "items", "data", "results", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def normalize_domain(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = re.sub(r"^https?://", "", text)
    text = text.split("/", 1)[0].split(":", 1)[0]
    return text.removeprefix("www.")


def site_domains(site: dict[str, Any]) -> list[str]:
    domains = site.get("domains") or site.get("domain") or site.get("url") or ""
    values = domains if isinstance(domains, list) else re.split(r"[\s,;]+", str(domains))
    return [domain for value in values if (domain := normalize_domain(value))]


def choose_site_id(sites: list[dict[str, Any]], domain: str = "", name: str = "") -> str:
    if not sites:
        raise RuntimeError("Callibri API returned no sites; check account permissions.")
    normalized_domain = normalize_domain(domain)
    if normalized_domain:
        matches = [site for site in sites if normalized_domain in site_domains(site)]
        if len(matches) == 1:
            return str(matches[0].get("site_id") or matches[0].get("id") or "").strip()
        if len(matches) > 1:
            raise RuntimeError("CALLIBRI_SITE_DOMAIN matches multiple Callibri sites; set CALLIBRI_SITE_ID.")
    normalized_name = name.strip().casefold()
    if normalized_name:
        matches = [site for site in sites if normalized_name in str(site.get("sitename") or site.get("name") or "").casefold()]
        if len(matches) == 1:
            return str(matches[0].get("site_id") or matches[0].get("id") or "").strip()
        if len(matches) > 1:
            raise RuntimeError("CALLIBRI_SITE_NAME matches multiple Callibri sites; set CALLIBRI_SITE_ID.")
    if len(sites) == 1:
        return str(sites[0].get("site_id") or sites[0].get("id") or "").strip()
    raise RuntimeError("CALLIBRI_SITE_ID is required when Callibri account has multiple sites.")


def date_ranges(date_from: date, date_to: date) -> list[tuple[date, date]]:
    ranges = []
    current = date_from
    while current <= date_to:
        end = min(current + timedelta(days=6), date_to)
        ranges.append((current, end))
        current = end + timedelta(days=1)
    return ranges


def fetch_callibri_api(args: argparse.Namespace, date_from: date, date_to: date | None) -> tuple[str, str]:
    base_url = args.api_base_url.strip()
    if not base_url:
        return "not_configured", ""
    effective_date_to = date_to or datetime.now(MOSCOW).date()
    if effective_date_to < date_from:
        return "callibri_api:empty_period", json.dumps({"payloads": []}, ensure_ascii=False)
    site_id = str(args.site_id or "").strip()
    if not site_id:
        sites_payload = fetch_api_json(base_url, "get_sites", [])
        site_id = choose_site_id(site_rows(sites_payload), domain=args.site_domain, name=args.site_name)
        time.sleep(API_SLEEP_SECONDS)
    payloads = []
    for index, (start, end) in enumerate(date_ranges(date_from, effective_date_to)):
        if index:
            time.sleep(API_SLEEP_SECONDS)
        payloads.append(fetch_api_json(base_url, "site_get_statistics", [
            ("site_id", site_id),
            ("date1", start.strftime("%d.%m.%Y")),
            ("date2", end.strftime("%d.%m.%Y")),
        ]))
    source = f"callibri_api:site:{site_id}:dates:{date_from.isoformat()}:{effective_date_to.isoformat()}"
    return source, json.dumps({"payloads": payloads}, ensure_ascii=False)


def load_source(args: argparse.Namespace, date_from: date, date_to: date | None) -> tuple[str, str]:
    if args.input:
        path = Path(args.input)
        for encoding in ("utf-8-sig", "utf-8", "cp1251"):
            try:
                return f"file:{path}", path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                pass
        return f"file:{path}", path.read_text(encoding="utf-8", errors="replace")
    if args.url:
        return redact_url(args.url), request_text(args.url)
    return fetch_callibri_api(args, date_from, date_to)


def looks_like_call(row: dict[str, Any]) -> bool:
    return bool(first_value(row, PHONE_KEYS) and first_value(row, STARTED_AT_KEYS))


def collect_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        rows: list[dict[str, Any]] = []
        for item in value:
            rows.extend(collect_rows(item))
        return rows
    if not isinstance(value, dict):
        return []

    rows = []
    calls = value.get("calls")
    if isinstance(calls, list):
        rows.extend(call for call in calls if isinstance(call, dict))

    for key in ("payloads", "channels_statistics", "items", "data", "results", "records"):
        nested = value.get(key)
        if isinstance(nested, (dict, list)):
            rows.extend(collect_rows(nested))

    if not rows and looks_like_call(value):
        rows.append(value)
    return rows


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
    return collect_rows(payload)


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
    ids_from_content = yandex_direct_ids_from_text(row.get("utm_content") or query.get("utm_content") or text)
    campaign_id = (
        direct_id(row, "campaign_id", "campaignId", "ya_campaign_id", "yandex_campaign_id", "yd_c", "cid")
        or ids_from_content.get("campaign_id", "")
        or ids.get("campaign_id", "")
    )
    group_id = (
        direct_id(row, "group_id", "groupId", "ad_group_id", "adGroupId", "gb", "gid")
        or ids_from_content.get("group_id", "")
        or ids.get("group_id", "")
    )
    ad_id = (
        direct_id(row, "ad_id", "adId", "banner_id", "bannerId", "ad", "aid")
        or ids_from_content.get("ad_id", "")
        or ids.get("ad_id", "")
    )
    call_id = first_value(row, CALL_ID_KEYS)
    stable_id = call_id or f"{phone}:{started_at.isoformat()}:{campaign_id}:{group_id}:{ad_id}"
    metrika_client_id = str(row.get("metrika_client_id") or row.get("ym_client_id") or row.get("ym_uid") or "").strip()
    return {
        "call_id_sha256": hash_value(stable_id),
        "started_at": started_at.isoformat(),
        "phone_sha256": hash_value(phone),
        "metrika_client_id_sha256": hash_value(metrika_client_id),
        "tracking_accurate": parse_tracking_accurate(row),
        "duration_seconds": parse_duration(row.get("duration") or row.get("duration_seconds") or row.get("длительность")),
        "status": str(row.get("status") or row.get("call_status") or row.get("статус") or ""),
        "direction": str(row.get("direction") or row.get("type") or row.get("тип") or ""),
        "utm_source": str(row.get("utm_source") or query.get("utm_source") or row.get("source") or ""),
        "utm_medium": str(row.get("utm_medium") or query.get("utm_medium") or ""),
        "utm_campaign": str(row.get("utm_campaign") or query.get("utm_campaign") or ""),
        "utm_term": str(row.get("utm_term") or query.get("utm_term") or row.get("query") or ""),
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
    if not args.input and not args.url and not args.api_base_url:
        write_payload(output, {
            "schema_version": 1,
            "status": "missing_source",
            "message": "Set CALLIBRI_API_BASE_URL or CALLIBRI_CALLS_URL or CALLIBRI_CALLS_FILE to import calls.",
            "date_from": args.date_from,
            "date_to": args.date_to or None,
            "call_count": 0,
            "calls": [],
        })
        return 0
    try:
        source, text = load_source(args, date_from, date_to)
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
