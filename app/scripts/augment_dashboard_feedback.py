from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_dashboard_snapshot import (
    crm_manager_name,
    event_type_for_lead,
    exact_guest_display,
    identifier_value,
    source_for_lead,
)


MOSCOW_TZ = ZoneInfo("Europe/Moscow")
VISIBLE_STATES = {"NO_FEEDBACK", "WAITING"}
TRACKED_STATES = {"NO_FEEDBACK", "WAITING", "CLEAR"}
YELLOW_WAITING_DAY = 3
BLUE_WAITING_DAY = 4


def iso_moscow(value: object) -> str:
    try:
        ts = int(value or 0)
    except (TypeError, ValueError):
        return ""
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, MOSCOW_TZ).isoformat(timespec="seconds")


def calendar_day_number(now_ts: int, created_at: int) -> int:
    if not created_at:
        return 0
    now_date = datetime.fromtimestamp(int(now_ts), MOSCOW_TZ).date()
    created_date = datetime.fromtimestamp(int(created_at), MOSCOW_TZ).date()
    return max(1, (now_date - created_date).days + 1)


def compact_feedback_lead(lead: dict, now_ts: int) -> dict | None:
    crm = lead.get("crm") or {}
    feedback = lead.get("crm_feedback") or {}
    state = str(feedback.get("state") or "").strip().upper()
    if not crm.get("found") or crm.get("entity_type") != "lead" or state not in VISIBLE_STATES:
        return None

    try:
        created_at = int(feedback.get("lead_created_at") or crm.get("created_at") or 0)
    except (TypeError, ValueError):
        created_at = 0
    try:
        first_activity_at = int(feedback.get("first_activity_at") or 0)
    except (TypeError, ValueError):
        first_activity_at = 0

    fields = lead.get("fields") or {}
    age_seconds = max(0, now_ts - created_at) if created_at else 0
    day_number = calendar_day_number(now_ts, created_at)

    if state == "WAITING":
        # Moscow calendar dates define the control day. The CRM creation date is
        # day 1, the next date is day 2, day 3 is yellow, day 4 is blue, and day
        # 5+ is promoted to NO_FEEDBACK by crm_feedback.py.
        if day_number < YELLOW_WAITING_DAY:
            return None
        display_state = "WAITING_BLUE" if day_number >= BLUE_WAITING_DAY else "WAITING_YELLOW"
    else:
        display_state = state

    return {
        "crm_lead_id": int(crm.get("entity_id") or 0),
        "created_at": iso_moscow(created_at),
        "created_ts": created_at,
        "source": source_for_lead(lead),
        "name": lead.get("name") or fields.get("name") or "",
        "identifier": identifier_value(lead),
        "guests": exact_guest_display(lead),
        "event_type": event_type_for_lead(lead),
        "manager": crm_manager_name(lead),
        "crm_status": str(feedback.get("status_name") or "").strip(),
        "first_activity_at": iso_moscow(first_activity_at),
        "first_activity_ts": first_activity_at or None,
        "age_seconds": age_seconds,
        "feedback_state": display_state,
    }



def compact_waiting_stage_lead(lead: dict) -> dict | None:
    crm = lead.get("crm") or {}
    feedback = lead.get("crm_feedback") or {}
    status_name = str(feedback.get("status_name") or "").strip()
    status_key = status_name.casefold().replace("ё", "е")
    if not crm.get("found") or crm.get("entity_type") != "lead" or status_key != "ждуны":
        return None

    try:
        created_at = int(feedback.get("lead_created_at") or crm.get("created_at") or 0)
    except (TypeError, ValueError):
        created_at = 0

    fields = lead.get("fields") or {}
    return {
        "crm_lead_id": int(crm.get("entity_id") or 0),
        "created_at": iso_moscow(created_at),
        "created_ts": created_at,
        "source": source_for_lead(lead),
        "name": lead.get("name") or fields.get("name") or "",
        "identifier": identifier_value(lead),
        "guests": exact_guest_display(lead),
        "event_type": event_type_for_lead(lead),
        "manager": crm_manager_name(lead),
        "crm_status": status_name,
    }


def augment(leads_path: Path, view_path: Path, now_ts: int | None = None) -> None:
    leads_payload = json.loads(leads_path.read_text(encoding="utf-8"))
    view = json.loads(view_path.read_text(encoding="utf-8"))
    leads = leads_payload.get("leads", leads_payload if isinstance(leads_payload, list) else [])
    current_ts = int(now_ts if now_ts is not None else time.time())

    rows = []
    waiting_stage_rows = []
    tracked_counts = {state: 0 for state in TRACKED_STATES}
    display_counts = {"WAITING_YELLOW": 0, "WAITING_BLUE": 0}
    for lead in leads:
        crm = lead.get("crm") or {}
        feedback = lead.get("crm_feedback") or {}
        state = str(feedback.get("state") or "").strip().upper()
        if crm.get("found") and crm.get("entity_type") == "lead" and state in TRACKED_STATES:
            tracked_counts[state] += 1

        waiting_stage_row = compact_waiting_stage_lead(lead)
        if waiting_stage_row is not None:
            waiting_stage_rows.append(waiting_stage_row)

        row = compact_feedback_lead(lead, current_ts)
        if row is not None:
            rows.append(row)
            if row["feedback_state"] in display_counts:
                display_counts[row["feedback_state"]] += 1

    state_order = {"NO_FEEDBACK": 0, "WAITING_BLUE": 1, "WAITING_YELLOW": 2}
    rows.sort(
        key=lambda row: (
            state_order.get(row["feedback_state"], 9),
            -int(row.get("created_ts") or 0),
        )
    )

    view["feedback_summary"] = {
        "total": len(rows),
        "no_feedback": tracked_counts["NO_FEEDBACK"],
        "waiting": tracked_counts["WAITING"],
        "waiting_blue": display_counts["WAITING_BLUE"],
        "waiting_yellow": display_counts["WAITING_YELLOW"],
        "clear": tracked_counts["CLEAR"],
    }
    waiting_stage_rows.sort(key=lambda row: -int(row.get("created_ts") or 0))
    view["feedback"] = rows
    view["waiting_stage"] = waiting_stage_rows
    view_path.write_text(json.dumps(view, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--leads", required=True)
    parser.add_argument("--view", required=True)
    args = parser.parse_args()
    augment(Path(args.leads), Path(args.view))


if __name__ == "__main__":
    main()
