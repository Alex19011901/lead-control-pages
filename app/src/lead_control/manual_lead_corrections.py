from __future__ import annotations

"""Manual, message-scoped display corrections applied only after CRM checks.

The original MAX messages are immutable. Corrections never change normalized
phone identifiers, CRM matches, lead classification, or CRM/status policy.
"""

from typing import Any


def _lead_keys(lead: dict[str, Any]) -> set[tuple[str, str, str]]:
    if str(lead.get("channel") or "").upper() != "MAX":
        return set()
    max_payload = lead.get("max") or {}
    chat = str(max_payload.get("chat_id") or "")
    ids = list(max_payload.get("message_ids") or [])
    if lead.get("message_id"):
        ids.append(lead["message_id"])
    return {("MAX", chat, str(message_id)) for message_id in ids if message_id}


def apply_manual_lead_corrections(
    leads: list[dict[str, Any]], items: list[dict[str, Any]]
) -> int:
    """Apply user-verified names and *display-only* phones for exact MAX messages.

    A display_phone override can be shorter than a valid national phone number.
    Such an override is deliberately NOT promoted into identifier/phone_digits
    or used for amoCRM matching. The exact original remains in events.ndjson.
    """
    corrections: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in items:
        if str(item.get("channel") or "").upper() != "MAX":
            continue
        key = ("MAX", str(item.get("chat_id") or ""), str(item.get("message_id") or ""))
        if not key[1] or not key[2]:
            continue
        if key in corrections:
            raise ValueError(f"Duplicate manual field correction for MAX message {key[2]}")
        corrections[key] = item

    changes = 0
    for lead in leads:
        correction = next(
            (corrections[key] for key in _lead_keys(lead) if key in corrections),
            None,
        )
        if not correction:
            continue
        fields = lead.setdefault("fields", {})
        updated = False

        name = str(correction.get("name") or "").strip()
        if name and (lead.get("name") != name or fields.get("name") != name):
            lead["name"] = name
            fields["name"] = name
            lead["name_source"] = "USER_VERIFIED_MAX_MESSAGE"
            updated = True

        display_phone = str(correction.get("display_phone") or "").strip()
        if display_phone and (
            lead.get("phone") != display_phone or fields.get("phone_raw") != display_phone
        ):
            lead["phone"] = display_phone
            fields["phone_raw"] = display_phone
            updated = True

        if updated:
            changes += 1
    return changes
