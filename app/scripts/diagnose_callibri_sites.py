#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MOSCOW = timezone(timedelta(hours=3))


def load_callibri_module() -> Any:
    path = Path(__file__).with_name("import_callibri_calls.py")
    spec = importlib.util.spec_from_file_location("import_callibri_calls", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load import_callibri_calls.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


callibri = load_callibri_module()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--leads", default="../runtime-data/leads.json")
    parser.add_argument("--advertising-leads", default="../runtime-data/advertising_leads.json")
    parser.add_argument("--current-callibri", default="../runtime-data/callibri_calls.json")
    parser.add_argument("--output", default="../runtime-data/callibri_sites_diagnostic.json")
    parser.add_argument("--date-from", default="2026-09-17")
    parser.add_argument("--date-to", default="")
    parser.add_argument("--target", choices=("late", "all-unmatched"), default="late")
    parser.add_argument("--sleep-seconds", type=float, default=1.05)
    return parser.parse_args()


def load_json(path_text: str) -> dict[str, Any]:
    return json.loads(Path(path_text).read_text(encoding="utf-8"))


def normalize_phone(value: Any) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if len(digits) == 11 and digits.startswith("8"):
        return f"7{digits[1:]}"
    if len(digits) == 10:
        return f"7{digits}"
    return digits


def parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(MOSCOW) if parsed.tzinfo else parsed.replace(tzinfo=MOSCOW)


def current_last_call(path_text: str) -> datetime | None:
    payload = load_json(path_text)
    dates = [parse_datetime(call.get("started_at")) for call in payload.get("calls", []) if isinstance(call, dict)]
    dates = [value for value in dates if value]
    return max(dates) if dates else None


def lead_phone(fields: dict[str, Any], lead: dict[str, Any]) -> str:
    return normalize_phone(fields.get("phone_digits") or fields.get("phone_raw") or lead.get("phone"))


def target_leads(args: argparse.Namespace) -> list[dict[str, Any]]:
    raw = load_json(args.leads).get("leads", [])
    advertising = load_json(args.advertising_leads).get("leads", [])
    raw_by_id = {str(lead.get("id") or ""): lead for lead in raw if isinstance(lead, dict)}
    after = current_last_call(args.current_callibri) if args.target == "late" else None
    result = []
    for item in advertising:
        if not isinstance(item, dict):
            continue
        if item.get("source") != "Заявки хост":
            continue
        if item.get("callibri_match_status") != "no_callibri_phone_match":
            continue
        created_at = parse_datetime(item.get("created_at"))
        if after and (not created_at or created_at <= after):
            continue
        raw_lead = raw_by_id.get(str(item.get("lead_id") or ""), {})
        fields = raw_lead.get("fields") or {}
        phone = lead_phone(fields, raw_lead)
        if not phone:
            continue
        result.append({
            "lead_id": str(item.get("lead_id") or ""),
            "created_at": str(item.get("created_at") or ""),
            "sender": str(raw_lead.get("sender_name") or ""),
            "name": str(fields.get("name") or ""),
            "event_type": str(item.get("event_type") or fields.get("event_type") or ""),
            "phone_last4": phone[-4:],
            "phone_sha256": callibri.hash_value(phone),
        })
    result.sort(key=lambda item: (item["created_at"], item["lead_id"]))
    return result


def site_id(site: dict[str, Any]) -> str:
    return str(site.get("site_id") or site.get("id") or "").strip()


def site_name(site: dict[str, Any]) -> str:
    return str(site.get("sitename") or site.get("name") or "").strip()


def safe_site(site: dict[str, Any]) -> dict[str, Any]:
    return {
        "site_id": site_id(site),
        "name": site_name(site),
        "domains": callibri.site_domains(site),
    }


def fetch_site_calls(base_url: str, site: dict[str, Any], date_from: date, date_to: date) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(callibri.date_ranges(date_from, date_to)):
        if index:
            time.sleep(callibri.API_SLEEP_SECONDS)
        payload = callibri.fetch_api_json(base_url, "site_get_statistics", [
            ("site_id", site_id(site)),
            ("date1", start.strftime("%d.%m.%Y")),
            ("date2", end.strftime("%d.%m.%Y")),
        ])
        rows.extend(callibri.collect_rows(payload))
    return [safe for row in rows if (safe := callibri.safe_call(row))]


def main() -> int:
    args = parse_args()
    base_url = callibri.env_value("CALLIBRI_API_BASE_URL", "CALIBRI_API_BASE_URL")
    if not base_url:
        raise SystemExit("CALLIBRI_API_BASE_URL/CALIBRI_API_BASE_URL is not configured.")
    date_from = date.fromisoformat(args.date_from)
    date_to = date.fromisoformat(args.date_to) if args.date_to else datetime.now(MOSCOW).date()
    targets = target_leads(args)
    target_by_hash = {item["phone_sha256"]: item for item in targets}

    sites_payload = callibri.fetch_api_json(base_url, "get_sites", [])
    sites = [site for site in callibri.site_rows(sites_payload) if site_id(site)]
    matches: list[dict[str, Any]] = []
    site_summaries: list[dict[str, Any]] = []
    for index, site in enumerate(sites):
        if index:
            time.sleep(args.sleep_seconds)
        safe = safe_site(site)
        try:
            calls = fetch_site_calls(base_url, site, date_from, date_to)
            error = ""
        except Exception as exc:  # noqa: BLE001 - diagnostic should inspect all sites.
            calls = []
            error = str(exc)
        matched_calls = []
        for call in calls:
            target = target_by_hash.get(str(call.get("phone_sha256") or ""))
            if not target:
                continue
            matched_calls.append({
                "lead_id": target["lead_id"],
                "lead_created_at": target["created_at"],
                "phone_last4": target["phone_last4"],
                "lead_sender": target["sender"],
                "lead_name": target["name"],
                "lead_event_type": target["event_type"],
                "call_started_at": call.get("started_at"),
                "call_duration_seconds": call.get("duration_seconds"),
                "call_status": call.get("status"),
                "tracking_accurate": call.get("tracking_accurate"),
                "campaign_id": call.get("campaign_id"),
                "group_id": call.get("group_id"),
                "ad_id": call.get("ad_id"),
                "utm_source": call.get("utm_source"),
                "utm_campaign": call.get("utm_campaign"),
            })
        if matched_calls:
            matches.extend({**safe, **match} for match in matched_calls)
        site_summaries.append({
            **safe,
            "status": "error" if error else "ok",
            "error": error,
            "calls_found": len(calls),
            "target_matches": len(matched_calls),
            "first_call_started_at": min((str(call.get("started_at") or "") for call in calls), default=""),
            "last_call_started_at": max((str(call.get("started_at") or "") for call in calls), default=""),
        })

    output = {
        "schema_version": 1,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "target": args.target,
        "target_count": len(targets),
        "site_count": len(sites),
        "matches_count": len(matches),
        "matches_by_last4": dict(Counter(match["phone_last4"] for match in matches)),
        "targets": [{key: value for key, value in item.items() if key != "phone_sha256"} for item in targets],
        "sites": site_summaries,
        "matches": matches,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Callibri sites checked: {len(sites)}")
    print(f"Target hostess leads: {len(targets)}")
    print(f"Target matches found: {len(matches)}")
    for match in matches:
        print(
            "MATCH",
            f"site_id={match.get('site_id')}",
            f"site_name={match.get('name')}",
            f"last4={match.get('phone_last4')}",
            f"lead_id={match.get('lead_id')}",
            f"call_started_at={match.get('call_started_at')}",
            f"campaign_id={match.get('campaign_id') or ''}",
            f"group_id={match.get('group_id') or ''}",
            f"ad_id={match.get('ad_id') or ''}",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
