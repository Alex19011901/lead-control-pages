from __future__ import annotations

from typing import Any

from .max_mail_lead import MAIL_LEAD, classify_max_mail_event
from .normalize import parse_event_date


def apply_max_mail_leads(leads: list[dict[str, Any]], events: list[dict[str, Any]]) -> None:
    by_message_id = {
        str(event.get("message_id") or ""): event
        for event in events
        if event.get("type") == "max_message_created" and event.get("source") == "MAX"
    }
    for lead in leads:
        if str(lead.get("channel") or "").upper() != "MAX":
            continue
        message_ids = list((lead.get("max") or {}).get("message_ids") or [])
        if lead.get("message_id"):
            message_ids.append(lead.get("message_id"))
        event = None
        classification = None
        for message_id in message_ids:
            candidate = by_message_id.get(str(message_id))
            if not candidate:
                continue
            result = classify_max_mail_event(candidate)
            if result is not None:
                event = candidate
                classification = result
                break
        if classification is None or event is None:
            continue

        parsed = dict(classification.get("fields") or {})
        fields = lead.setdefault("fields", {})
        fields.update({key: value for key, value in parsed.items() if value not in (None, "")})
        fields["source"] = MAIL_LEAD
        fields["category"] = MAIL_LEAD
        fields["event_date"] = parse_event_date(str(fields.get("event_date_raw") or ""))

        lead["source"] = MAIL_LEAD
        lead["category"] = MAIL_LEAD
        lead["event_date"] = fields.get("event_date", "")
        lead["name"] = fields.get("name", "") or lead.get("name", "")
        lead["phone"] = fields.get("phone_raw", "")
        lead["username"] = fields.get("telegram_username", "")
        lead["guests"] = fields.get("guests_count")
        lead["guests_raw"] = fields.get("guests_raw", "")
        lead["guests_min"] = fields.get("guests_min")
        lead["guests_max"] = fields.get("guests_max")

        phone = str(fields.get("phone_digits") or "").strip()
        username = str(fields.get("telegram_username") or "").strip()
        if phone:
            lead["identifier"] = {"type": "phone", "value": phone}
            lead["crm_required"] = True
            lead["crm"] = {"found": False, "required": True}
            lead.pop("crm_check_status", None)
        elif username:
            lead["identifier"] = {"type": "telegram_username", "value": username}
            lead["crm_required"] = True
            lead["crm"] = {"found": False, "required": True}
            lead.pop("crm_check_status", None)
        else:
            # Source is still authoritative even when OCR cannot recover an
            # identifier; keep the lead instead of sending it to review.
            lead["crm_required"] = False
            lead["crm"] = {"found": False, "required": False}

        max_info = lead.setdefault("max", {})
        max_info["attachment_message_id"] = event.get("attachment_message_id") or event.get("message_id")
