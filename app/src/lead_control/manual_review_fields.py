from __future__ import annotations

from typing import Any

from .normalize import normalize_phone, normalize_username


def enrich_manual_review_fields(
    leads: list[dict[str, Any]],
    overrides: list[dict[str, Any]],
) -> None:
    """Apply explicitly confirmed lead fields stored with review decisions.

    This is intentionally message-specific: it never creates a rule for other
    messages or senders. It is used when the original forwarded request carries
    useful metadata (for example, the original author's name or contact) that is
    not part of the plain message text used by the manual-review parser.

    If a confirmed phone or Telegram username is supplied for a CRM-required
    lead, it becomes the reliable CRM identifier and the lead is eligible for a
    real amoCRM lookup instead of staying in NO_IDENTIFIER.
    """
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in overrides:
        lead_fields = item.get("lead_fields") or {}
        if not isinstance(lead_fields, dict) or not lead_fields:
            continue
        channel = "MAX" if str(item.get("channel") or "").upper() == "MAX" else "TELEGRAM"
        by_key[(channel, str(item.get("chat_id") or ""), str(item.get("message_id") or ""))] = lead_fields

    if not by_key:
        return

    for lead in leads:
        channel = str(lead.get("channel") or "").upper()
        if channel == "MAX":
            chat_id = str((lead.get("max") or {}).get("chat_id") or "")
            message_ids = list((lead.get("max") or {}).get("message_ids") or [])
            if lead.get("message_id") is not None:
                message_ids.append(lead.get("message_id"))
        else:
            chat_id = str((lead.get("telegram") or {}).get("chat_id") or "")
            message_ids = list((lead.get("telegram") or {}).get("message_ids") or [])
            if lead.get("message_id") is not None:
                message_ids.append(lead.get("message_id"))

        confirmed: dict[str, Any] | None = None
        for message_id in message_ids:
            confirmed = by_key.get((channel, chat_id, str(message_id)))
            if confirmed:
                break
        if not confirmed:
            continue

        fields = lead.setdefault("fields", {})
        for key, value in confirmed.items():
            if value in (None, ""):
                continue
            fields[key] = value
            if key == "name":
                lead["name"] = value
            elif key == "phone_raw":
                lead["phone"] = value
            elif key == "telegram_username":
                lead["username"] = value
            elif key == "email":
                lead["email"] = str(value).strip().lower()
                fields["email"] = lead["email"]
            elif key == "event_date":
                lead["event_date"] = value
            elif key == "guests_count":
                lead["guests"] = value

        phone_digits = normalize_phone(str(fields.get("phone_raw") or ""))
        username = normalize_username(str(fields.get("telegram_username") or ""))
        email = str(fields.get("email") or "").strip().lower()

        if phone_digits:
            fields["phone_digits"] = phone_digits
            lead["identifier"] = {"type": "phone", "value": phone_digits}
            if lead.get("crm_required") is not False:
                lead["crm_check_status"] = "PENDING"
        elif username:
            fields["telegram_username"] = username
            lead["username"] = username
            lead["identifier"] = {"type": "telegram_username", "value": username}
            if lead.get("crm_required") is not False:
                lead["crm_check_status"] = "PENDING"
        elif email:
            fields["email"] = email
            lead["email"] = email
            lead["identifier"] = {"type": "email", "value": email}
            lead["crm_required"] = True
            lead["crm_check_status"] = "PENDING"
