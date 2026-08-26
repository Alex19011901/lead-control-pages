from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_dashboard_snapshot import exact_guest_display
from build_dashboard_view import guest_bucket_label


def effective_guest_value(lead: dict) -> str:
    crm = lead.get("crm") or {}
    crm_value = str(crm.get("guests") or "").strip()
    if crm.get("found") and crm_value:
        return crm_value
    return exact_guest_display(lead)


def apply_priority(leads_path: Path, view_path: Path) -> None:
    raw = json.loads(leads_path.read_text(encoding="utf-8"))
    leads = raw.get("leads", raw if isinstance(raw, list) else [])
    view = json.loads(view_path.read_text(encoding="utf-8"))

    dated: list[tuple[str, dict]] = []
    for lead in leads:
        ts = str(lead.get("received_at") or lead.get("first_seen_at") or "")
        day = ts[:10]
        if day:
            dated.append((day, lead))

    for range_data in (view.get("ranges") or {}).values():
        start = str(range_data.get("start") or "")
        end = str(range_data.get("end") or "")
        if not start or not end:
            continue
        guest_counts: Counter[str] = Counter()
        for day, lead in dated:
            if start <= day <= end:
                guest_counts[guest_bucket_label(effective_guest_value(lead) or "unknown")] += 1
        range_data["guest"] = dict(guest_counts)

    view_path.write_text(json.dumps(view, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--leads", required=True)
    parser.add_argument("--view", required=True)
    args = parser.parse_args()
    apply_priority(Path(args.leads), Path(args.view))


if __name__ == "__main__":
    main()
