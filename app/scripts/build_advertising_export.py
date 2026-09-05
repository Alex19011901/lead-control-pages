#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--start-date", default="2026-09-05")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def date_part(value: Any) -> str:
    text = str(value or "")
    return text[:10] if len(text) >= 10 else ""


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


def attribution_fields(fields: dict[str, Any]) -> dict[str, str]:
    description = str(fields.get("description") or "")
    result = {
        "utm_source": str(fields.get("utm_source") or text_value(description, "UTM source")),
        "utm_medium": str(fields.get("utm_medium") or text_value(description, "UTM medium")),
        "utm_campaign": str(fields.get("utm_campaign") or text_value(description, "UTM campaign")),
        "utm_content": str(fields.get("utm_content") or text_value(description, "UTM content")),
        "utm_term": str(fields.get("utm_term") or text_value(description, "UTM term")),
    }
    content = result["utm_content"]
    for marker, key in (("cid", "campaign_id"), ("gid", "group_id"), ("aid", "ad_id")):
        match = re.search(rf"(?:^|[|;,_-]){marker}(?:[|:=_-])([0-9]+)(?:$|[|;,_-])", content, flags=re.I)
        if not match:
            match = re.search(rf"(?:^|\|){marker}\|([0-9]+)(?:\||$)", content, flags=re.I)
        result[key] = match.group(1) if match else ""
    return result


def safe_lead(lead: dict[str, Any]) -> dict[str, Any]:
    fields = lead.get("fields") or {}
    yclid = str(fields.get("yclid") or lead.get("yclid") or "").strip()
    item = {
        "lead_id": str(lead.get("id") or ""),
        "created_at": str(lead.get("first_seen_at") or lead.get("received_at") or ""),
        "created_ts": lead.get("first_seen_ts"),
        "source": str(lead.get("source") or ""),
        "channel": str(lead.get("channel") or ""),
        "yclid": yclid,
        "event_type": str(fields.get("event_type") or lead.get("event_type") or ""),
        "status": str(lead.get("status") or ""),
        "crm_found": bool(lead.get("crm_found") or (lead.get("crm") or {}).get("found")),
        "crm_status": crm_status_name(lead),
    }
    item.update(attribution_fields(fields))
    return item


def main() -> int:
    args = parse_args()
    start = date.fromisoformat(args.start_date)
    payload = load_json(Path(args.input))
    exported = []
    for lead in payload.get("leads", []):
        created = date_part(lead.get("first_seen_at") or lead.get("received_at"))
        if not created:
            continue
        try:
            created_date = date.fromisoformat(created)
        except ValueError:
            continue
        if created_date < start:
            continue
        exported.append(safe_lead(lead))

    exported.sort(key=lambda item: (item.get("created_ts") or 0, item.get("lead_id") or ""))
    output = {
        "schema_version": 2,
        "start_date": args.start_date,
        "lead_count": len(exported),
        "leads": exported,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
