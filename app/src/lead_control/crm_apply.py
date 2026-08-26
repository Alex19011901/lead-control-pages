from __future__ import annotations

from typing import Any

from .amocrm_client import AmoCRMClient
from .crm_guests import extract_crm_guest_value
from .processor import _update_status


def apply_crm(
    leads: list[dict[str, Any]],
    client: AmoCRMClient,
    previous_leads: list[dict[str, Any]] | None = None,
    reuse_confirmed: bool = False,
) -> None:
    """Apply CRM lookup using source lead time to select the correct deal.

    In fast-refresh mode, an already confirmed CRM deal can be reused from the
    previous snapshot. Unresolved leads are always queried again so newly added
    amoCRM deals are still discovered promptly.
    """
    previous_by_id = {
        str(item.get("id") or ""): item
        for item in (previous_leads or [])
        if item.get("id")
    }

    for lead in leads:
        if lead.get("crm_required") is False:
            lead["crm"] = {"found": False, "required": False}
            lead["crm_check_status"] = "NOT_REQUIRED"
            _update_status(lead)
            continue

        if lead.get("crm_check_status") == "NO_IDENTIFIER":
            lead["crm"] = {"found": False, "required": True, "check_status": "NO_IDENTIFIER"}
            lead["crm_found"] = False
            lead["crm_created_at"] = None
            lead["crm_responsible"] = None
            lead["violations"] = []
            lead["status"] = lead.get("status") or "PENDING"
            continue

        if reuse_confirmed:
            previous = previous_by_id.get(str(lead.get("id") or "")) or {}
            previous_identifier = previous.get("identifier") or {}
            previous_crm = previous.get("crm") or {}
            if (
                previous_identifier == (lead.get("identifier") or {})
                and previous_crm.get("found")
                and previous_crm.get("entity_type") == "lead"
                and previous_crm.get("entity_id")
            ):
                lead["crm"] = dict(previous_crm)
                _update_status(lead)
                continue

        identifier = lead.get("identifier") or {}
        source_ts = lead.get("first_seen_ts")
        try:
            target_created_at = int(source_ts) if source_ts is not None else None
        except (TypeError, ValueError):
            target_created_at = None

        result = client.search(
            query=identifier.get("value", ""),
            lead_id=lead["id"],
            identifier_type=identifier.get("type", ""),
            target_created_at=target_created_at,
        )
        crm_payload = result.as_dict()
        if result.found and result.entity_type == "lead" and result.entity_id:
            full_lead = client._get_entity("leads", int(result.entity_id)) or {}
            crm_guest_value = extract_crm_guest_value(full_lead)
            if crm_guest_value:
                crm_payload["guests"] = crm_guest_value
                crm_payload["guests_source"] = "CRM"
        lead["crm"] = crm_payload
        _update_status(lead)
