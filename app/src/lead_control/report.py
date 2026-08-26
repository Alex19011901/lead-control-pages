from __future__ import annotations

from collections import Counter
from typing import Any

from .normalize import guest_bucket, mask_identifier


GUEST_BUCKETS = ("1-20", "21-50", "51-100", "101-150", "151+", "unknown")


def build_report(leads: list[dict[str, Any]], updated_at: str | None, needs_review_count: int = 0) -> dict[str, Any]:
    status_counts = Counter(lead.get("status", "PENDING") for lead in leads)
    violation_counts = Counter(
        violation
        for lead in leads
        for violation in lead.get("violations", [])
    )

    by_source = Counter(lead.get("source") or "unknown" for lead in leads)
    by_manager = Counter(_manager_key(lead) for lead in leads)
    event_types = Counter((lead.get("fields") or {}).get("event_type") or "unknown" for lead in leads)
    guest_ranges = Counter(guest_bucket((lead.get("fields") or {}).get("guests_count")) for lead in leads)

    return {
        "updated_at": updated_at,
        "total_leads": len(leads),
        "needs_review": needs_review_count,
        "ok": status_counts["OK"],
        "late_crm": violation_counts["LATE_CRM"],
        "alarm_no_crm": violation_counts["ALARM_NO_CRM"],
        "no_reaction": violation_counts["NO_REACTION"],
        "by_source": dict(sorted(by_source.items())),
        "by_manager": dict(sorted(by_manager.items())),
        "event_types": dict(sorted(event_types.items())),
        "guest_ranges": {bucket: guest_ranges[bucket] for bucket in GUEST_BUCKETS},
        "latest_leads": [_report_lead(lead) for lead in _latest(leads)],
    }


def _manager_key(lead: dict[str, Any]) -> str:
    reaction = lead.get("manager_reaction") or {}
    return reaction.get("name") or "no_manager_reaction"


def _latest(leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(leads, key=lambda lead: int(lead.get("first_seen_ts", 0)), reverse=True)[:20]


def _report_lead(lead: dict[str, Any]) -> dict[str, Any]:
    fields = lead.get("fields") or {}
    identifier = lead.get("identifier") or {}
    reaction = lead.get("manager_reaction") or {}
    crm = lead.get("crm") or {}
    return {
        "lead_id": lead.get("id"),
        "source": lead.get("source"),
        "created_at": lead.get("first_seen_at"),
        "status": lead.get("status"),
        "violations": lead.get("violations", []),
        "identifier_type": identifier.get("type"),
        "identifier": mask_identifier(identifier.get("type", ""), identifier.get("value", "")),
        "name": fields.get("name", ""),
        "event_date": fields.get("event_date", ""),
        "guests_count": fields.get("guests_count"),
        "event_type": fields.get("event_type", ""),
        "manager": reaction.get("name", ""),
        "manager_username": reaction.get("username", ""),
        "crm_found": bool(crm.get("found")),
        "crm_entity_type": crm.get("entity_type"),
        "crm_entity_id": crm.get("entity_id"),
    }
