from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_dashboard_snapshot import exact_guest_display, event_type_for_lead, source_for_lead


def _decrement(mapping: dict, key: str) -> None:
    value = int(mapping.get(key) or 0) - 1
    if value > 0:
        mapping[key] = value
    else:
        mapping.pop(key, None)


def apply(leads_path: Path, snapshot_path: Path) -> None:
    leads_payload = json.loads(leads_path.read_text(encoding="utf-8"))
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    daily = snapshot.get("daily") or {}

    for lead in leads_payload.get("leads", []):
        if not (lead.get("is_duplicate") or lead.get("status") == "DUPLICATE"):
            continue
        ts = str(lead.get("received_at") or lead.get("first_seen_at") or "")
        day = ts[:10]
        item = daily.get(day)
        if not day or not item:
            continue

        item["total"] = max(0, int(item.get("total") or 0) - 1)
        _decrement(item.setdefault("status", {}), "DUPLICATE")

        source = source_for_lead(lead)
        _decrement(item.setdefault("source", {}), source)

        guest_key = exact_guest_display(lead) or "unknown"
        _decrement(item.setdefault("guest_ranges", {}), guest_key)

        channel = str(lead.get("channel") or "unknown")
        _decrement(item.setdefault("channel", {}), channel)

        event_type = event_type_for_lead(lead)
        if source == "Тильда Веранда" and event_type == "unknown":
            item["event_type_excluded"] = max(0, int(item.get("event_type_excluded") or 0) - 1)
        else:
            _decrement(item.setdefault("event_types", {}), event_type)

    snapshot["duplicates_excluded_from_totals"] = True
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--leads", required=True)
    parser.add_argument("--snapshot", required=True)
    args = parser.parse_args()
    apply(Path(args.leads), Path(args.snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
