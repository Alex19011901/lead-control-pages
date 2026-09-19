#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote_plus

MOSCOW = timezone(timedelta(hours=3))
HOSTESS_CALL_MATCH_BEFORE_MINUTES = 12 * 60
HOSTESS_CALL_MATCH_AFTER_MINUTES = 30


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--start-date", default="2026-09-05")
    parser.add_argument("--callibri-calls", default="")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def date_part(value: Any) -> str:
    text = str(value or "")
    return text[:10] if len(text) >= 10 else ""


def parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(MOSCOW) if parsed.tzinfo else parsed.replace(tzinfo=MOSCOW)


def crm_status_name(lead: dict[str, Any]) -> str:
    crm = lead.get("crm") or {}
    for key in ("status_name", "pipeline_status_name", "lead_status_name"):
        value = crm.get(key)
        if value:
            return str(value)
    for key in ("crm_status", "crm_status_name"):
        value = lead.get(key)
        if value:
            return str(value)
    return ""


def text_value(text: str, label: str) -> str:
    pattern = rf"(?im)^\s*{re.escape(label)}\s*:\s*(.*?)\s*$"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def first_text_value(text: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        value = text_value(text, label)
        if value:
            return value
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


def callibri_value(fields: dict[str, Any], description: str) -> str:
    direct = str(fields.get("callibri") or fields.get("callibri_id") or fields.get("callibri_uid") or "").strip()
    if direct:
        return unquote_plus(direct)
    return query_values_from_text(description).get("callibri", "")


def callibri_ids(value: str) -> dict[str, str]:
    decoded = unquote_plus(str(value or ""))
    result: dict[str, str] = {}
    for marker, key in (("yd_c", "campaign_id"), ("gb", "group_id"), ("ad", "ad_id")):
        match = re.search(rf"(?:^|_){re.escape(marker)}:([0-9]+)(?:_|$)", decoded, flags=re.I)
        if match:
            result[key] = match.group(1)
    return result


def normalize_phone(value: Any) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if len(digits) == 11 and digits.startswith("8"):
        return f"7{digits[1:]}"
    return digits


def attribution_fields(fields: dict[str, Any]) -> dict[str, Any]:
    description = str(fields.get("description") or "")
    query_values = query_values_from_text(description)
    utm_source = str(fields.get("utm_source") or text_value(description, "UTM source") or query_values.get("utm_source") or "")
    utm_medium = str(fields.get("utm_medium") or text_value(description, "UTM medium") or query_values.get("utm_medium") or "")
    utm_campaign = str(fields.get("utm_campaign") or text_value(description, "UTM campaign") or query_values.get("utm_campaign") or "")
    utm_content = str(fields.get("utm_content") or text_value(description, "UTM content") or query_values.get("utm_content") or "")
    result = {
        "utm_source": utm_source,
        "utm_medium": utm_medium,
        "utm_campaign": utm_campaign,
        "campaign_id": "",
        "group_id": "",
        "ad_id": "",
        "has_callibri": False,
        "advertising_id_source": "",
    }
    for marker, key in (("cid", "campaign_id"), ("gid", "group_id"), ("aid", "ad_id")):
        match = re.search(rf"(?:^|\|){marker}\|([0-9]+)(?:\||$)", utm_content, flags=re.I)
        if not match:
            match = re.search(rf"(?:^|[;,_-]){marker}(?:[:=_-])([0-9]+)(?:$|[;,_-])", utm_content, flags=re.I)
        if match:
            result[key] = match.group(1)
            result["advertising_id_source"] = "utm_content"

    callibri_raw = callibri_value(fields, description)
    ids_from_callibri = callibri_ids(callibri_raw)
    if callibri_raw:
        result["has_callibri"] = True
    for key, value in ids_from_callibri.items():
        if not result.get(key):
            result[key] = value
            result["advertising_id_source"] = "callibri"
    return result


def hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def is_hostess_lead(lead: dict[str, Any]) -> bool:
    return "заявки хост" in str(lead.get("source") or "").casefold()


def lead_phone_hash(lead: dict[str, Any]) -> str:
    identifier = lead.get("identifier") or {}
    fields = lead.get("fields") or {}
    if identifier.get("type") == "phone":
        phone = normalize_phone(identifier.get("value"))
    else:
        phone = normalize_phone(fields.get("phone_digits") or fields.get("phone_raw") or lead.get("phone"))
    return hash_value(phone)


def load_callibri_calls(path_text: str) -> dict[str, list[dict[str, Any]]]:
    if not path_text:
        return {}
    path = Path(path_text)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    calls = payload.get("calls") if isinstance(payload, dict) else []
    if not isinstance(calls, list):
        return {}
    by_phone: dict[str, list[dict[str, Any]]] = {}
    for call in calls:
        if not isinstance(call, dict):
            continue
        phone_hash = str(call.get("phone_sha256") or "").strip()
        if not phone_hash:
            continue
        by_phone.setdefault(phone_hash, []).append(call)
    for items in by_phone.values():
        items.sort(key=lambda item: parse_datetime(item.get("started_at")) or datetime.min.replace(tzinfo=MOSCOW))
    return by_phone


def call_has_ad_ids(call: dict[str, Any]) -> bool:
    return bool(str(call.get("ad_id") or call.get("group_id") or call.get("campaign_id") or "").strip())


def call_tracking_is_confirmed(call: dict[str, Any]) -> bool:
    return call.get("tracking_accurate") is not False


def apply_callibri_phone_match(item: dict[str, Any], lead: dict[str, Any], calls_by_phone: dict[str, list[dict[str, Any]]]) -> None:
    if not is_hostess_lead(lead):
        return
    lead_time = parse_datetime(lead.get("first_seen_at") or lead.get("received_at"))
    phone_hash = lead_phone_hash(lead)
    if not lead_time or not phone_hash:
        item["callibri_match_status"] = "no_phone_or_time"
        return
    phone_calls = calls_by_phone.get(phone_hash, [])
    if not phone_calls:
        item["callibri_match_status"] = "no_callibri_phone_match"
        return
    start = lead_time - timedelta(minutes=HOSTESS_CALL_MATCH_BEFORE_MINUTES)
    end = lead_time + timedelta(minutes=HOSTESS_CALL_MATCH_AFTER_MINUTES)
    candidates = []
    nearest_delta_seconds: int | None = None
    for call in phone_calls:
        call_time = parse_datetime(call.get("started_at"))
        if call_time and start <= call_time <= end:
            candidates.append((call_time, call))
        if call_time:
            delta = int((lead_time - call_time).total_seconds())
            if nearest_delta_seconds is None or abs(delta) < abs(nearest_delta_seconds):
                nearest_delta_seconds = delta
    if not candidates:
        item["callibri_match_status"] = "nearest_call_outside_window"
        if nearest_delta_seconds is not None:
            item["callibri_nearest_delta_seconds"] = nearest_delta_seconds
        return
    if len(candidates) > 1:
        item["callibri_match_status"] = "ambiguous_callibri_calls"
        item["callibri_candidate_count"] = len(candidates)
        return
    call_time, call = candidates[0]
    item["has_callibri"] = True
    item["callibri_match_status"] = "matched" if call_has_ad_ids(call) else "matched_without_ad_ids"
    item["callibri_call_id_sha256"] = str(call.get("call_id_sha256") or "")
    item["callibri_call_started_at"] = call_time.isoformat()
    item["callibri_match_delta_seconds"] = int((lead_time - call_time).total_seconds())
    if "tracking_accurate" in call:
        item["callibri_tracking_accurate"] = call.get("tracking_accurate")
    if not call_tracking_is_confirmed(call):
        item["callibri_match_status"] = "matched_unconfirmed_tracking"
        return
    for key in ("utm_source", "utm_medium", "utm_campaign"):
        if not item.get(key) and call.get(key):
            item[key] = str(call.get(key) or "")
    if call.get("utm_term"):
        item["utm_term"] = str(call.get("utm_term") or "")
    for key in ("campaign_id", "group_id", "ad_id"):
        if not item.get(key) and call.get(key):
            item[key] = str(call.get(key) or "")
            item["advertising_id_source"] = "callibri_phone_time_match"


def metrika_client_id(fields: dict[str, Any]) -> str:
    direct = str(
        fields.get("metrika_client_id")
        or fields.get("client_id")
        or fields.get("clientid")
        or fields.get("ym_client_id")
        or fields.get("ym_clientid")
        or fields.get("ym_uid")
        or fields.get("_ym_uid")
        or fields.get("yandex_client_id")
        or fields.get("ya_client_id")
        or ""
    ).strip()
    if direct:
        return direct
    description = str(fields.get("description") or "")
    return first_text_value(
        description,
        (
            "metrika_client_id",
            "Metrika ClientID",
            "Metrika Client ID",
            "clientID",
            "ClientID",
            "client_id",
            "ym_client_id",
            "ym_clientid",
            "ym_uid",
            "_ym_uid",
            "Yandex ClientID",
            "Yandex Client ID",
            "yandex_client_id",
            "Ya ClientID",
            "ya_client_id",
            "Метрика ClientID",
            "Метрика Client ID",
            "Яндекс Метрика ClientID",
        ),
    )


def form_submit_timestamp(fields: dict[str, Any]) -> int | None:
    value = fields.get("form_submit_timestamp")
    if value is None:
        description = str(fields.get("description") or "")
        value = first_text_value(description, ("form_submit_timestamp",))
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def safe_lead(lead: dict[str, Any], calls_by_phone: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    fields = lead.get("fields") or {}
    yclid = str(fields.get("yclid") or lead.get("yclid") or "").strip()
    client_id = metrika_client_id(fields)
    item = {
        "lead_id": str(lead.get("id") or ""),
        "created_at": str(lead.get("first_seen_at") or lead.get("received_at") or ""),
        "created_ts": lead.get("first_seen_ts"),
        "source": str(lead.get("source") or ""),
        "channel": str(lead.get("channel") or ""),
        "has_yclid": bool(yclid),
        "yclid_sha256": hash_value(yclid),
        "has_metrika_client_id": bool(client_id),
        "metrika_client_id_sha256": hash_value(client_id),
        "form_submit_timestamp": form_submit_timestamp(fields),
        "event_type": str(fields.get("event_type") or lead.get("event_type") or ""),
        "status": str(lead.get("status") or ""),
        "crm_found": bool(lead.get("crm_found") or (lead.get("crm") or {}).get("found")),
        "crm_status": crm_status_name(lead),
    }
    item.update(attribution_fields(fields))
    apply_callibri_phone_match(item, lead, calls_by_phone or {})
    return item


def main() -> int:
    args = parse_args()
    start = date.fromisoformat(args.start_date)
    payload = load_json(Path(args.input))
    calls_by_phone = load_callibri_calls(args.callibri_calls)
    exported = []
    for lead in payload.get("leads", []):
        if lead.get("is_duplicate") or lead.get("status") == "DUPLICATE":
            continue
        created = date_part(lead.get("first_seen_at") or lead.get("received_at"))
        if not created:
            continue
        try:
            created_date = date.fromisoformat(created)
        except ValueError:
            continue
        if created_date < start:
            continue
        exported.append(safe_lead(lead, calls_by_phone))

    exported.sort(key=lambda item: (item.get("created_ts") or 0, item.get("lead_id") or ""))
    output = {
        "schema_version": 7,
        "start_date": args.start_date,
        "lead_count": len(exported),
        "callibri_calls_loaded": sum(len(items) for items in calls_by_phone.values()),
        "leads": exported,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
