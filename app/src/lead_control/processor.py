from __future__ import annotations

import re
from typing import Any

from .amocrm_client import AmoCRMClient
from .normalize import (
    THREE_DAYS_SECONDS,
    make_lead_id,
    moscow_day_deadline_ts,
    normalize_phone,
    normalize_username,
    parse_event_date,
    unix_to_moscow_iso,
)
from .parsers import parse_message
from .parsers.max_leads import (
    BUSINESS_SOURCES,
    IGNORE,
    NEEDS_REVIEW,
    classify_max_event,
    classify_max_text,
)
from .review_overrides import CRM_FREE_DECISIONS, normalize_decision, overrides_by_key, review_key


MANAGERS_BY_USERNAME = {
    "empairbey": {"name": "Максим", "username": "empairbey"},
    "olesyagozhina": {"name": "Олеся", "username": "Olesyagozhina"},
}

TELEGRAM_TEST_PHRASES = {"TEST LEAD CONTROL", "ТЕСТ РЕАКЦИИ"}
TELEGRAM_TEST_PHONES = {"79999999999"}


def collect_known_manager_ids(events: list[dict[str, Any]]) -> dict[int, dict[str, str]]:
    result: dict[int, dict[str, str]] = {}
    for event in events:
        manager = event.get("manager") or {}
        user_id = manager.get("user_id")
        if user_id:
            result[int(user_id)] = {
                "name": manager.get("name", ""),
                "username": manager.get("username", ""),
            }
    return result


def normalize_updates(
    updates: list[dict[str, Any]],
    chat_id: int,
    existing_update_ids: set[int],
    known_manager_ids: dict[int, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    known_manager_ids = known_manager_ids or {}

    for update in updates:
        update_id = int(update["update_id"])
        if update_id in existing_update_ids:
            continue

        if "message" in update:
            event = _normalize_message_update(update_id, update["message"], chat_id)
        elif "message_reaction" in update:
            event = _normalize_reaction_update(
                update_id,
                update["message_reaction"],
                chat_id,
                known_manager_ids,
            )
        else:
            event = None

        if event:
            events.append(event)

    return events


def rebuild_leads(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    leads, _ = rebuild_leads_and_needs_review(events)
    return leads


def rebuild_leads_and_needs_review(
    events: list[dict[str, Any]],
    existing_needs_review: list[dict[str, Any]] | None = None,
    review_overrides: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    leads: list[dict[str, Any]] = []
    needs_review_by_key = {
        _needs_review_key(item): item
        for item in (existing_needs_review or [])
        if _needs_review_key(item)
    }
    review_overrides_by_key = overrides_by_key(review_overrides)
    applied_override_keys: set[str] = set()
    seen_max_message_ids: set[str] = set()

    for event in sorted(events, key=_event_sort_key):
        if event.get("type") != "telegram_lead" or event.get("ignored"):
            continue

        lead_data = event["lead"]
        created_at = int(event["telegram_date"])
        message_id = int(event["message_id"])
        identifier_type, identifier_value = _lead_identifier(lead_data, message_id)
        lead = _find_duplicate(leads, identifier_type, identifier_value, created_at)

        if lead is None:
            lead = {
                "id": make_lead_id(identifier_type, identifier_value, message_id, created_at),
                "source": lead_data["source"],
                "channel": "TELEGRAM",
                "first_seen_at": event["telegram_date_msk"],
                "first_seen_ts": created_at,
                "received_at": event["telegram_date_msk"],
                "last_seen_at": event["telegram_date_msk"],
                "last_seen_ts": created_at,
                "identifier": {
                    "type": identifier_type,
                    "value": identifier_value,
                },
                "sender_user_id": event.get("sender_user_id"),
                "sender_name": event.get("sender_name", ""),
                "sender_username": event.get("sender_username", ""),
                "telegram": {
                    "chat_id": event["chat_id"],
                    "message_ids": [],
                    "update_ids": [],
                },
                "fields": dict(lead_data),
                "manager_reaction": None,
                "crm_required": True,
                "crm": {"found": False},
                "crm_found": False,
                "crm_created_at": None,
                "crm_responsible": None,
                "deadline_msk_ts": moscow_day_deadline_ts(created_at),
                "status": "PENDING",
                "violations": [],
            }
            leads.append(lead)
        else:
            _merge_fields(lead["fields"], lead_data)
            if created_at > int(lead["last_seen_ts"]):
                lead["last_seen_ts"] = created_at
                lead["last_seen_at"] = event["telegram_date_msk"]

        if message_id not in lead["telegram"]["message_ids"]:
            lead["telegram"]["message_ids"].append(message_id)
        if event["update_id"] not in lead["telegram"]["update_ids"]:
            lead["telegram"]["update_ids"].append(event["update_id"])

    for event in sorted(events, key=_event_sort_key):
        if event.get("type") != "telegram_needs_review":
            continue
        key = _event_review_key("Telegram", event)
        override = review_overrides_by_key.get(key)
        if override:
            _apply_review_override(leads, needs_review_by_key, event, override, key)
            applied_override_keys.add(key)
            continue
        _add_telegram_needs_review(needs_review_by_key, event)

    for event in sorted(events, key=_event_sort_key):
        if event.get("type") != "max_message_created" or event.get("source") != "MAX":
            continue
        message_id = str(event.get("message_id") or "")
        if message_id in seen_max_message_ids:
            continue
        if message_id:
            seen_max_message_ids.add(message_id)

        key = _event_review_key("MAX", event)
        override = review_overrides_by_key.get(key)
        if override:
            _apply_review_override(leads, needs_review_by_key, event, override, key)
            applied_override_keys.add(key)
            continue

        classification = classify_max_event(event)
        category = classification["classification"]
        if category == IGNORE:
            continue
        if category == NEEDS_REVIEW:
            _add_needs_review(needs_review_by_key, classification)
            continue

        fields = _max_fields(classification)
        crm_required = bool(classification.get("crm_check_required"))
        identifier_type, identifier_value = _max_identifier(fields, message_id, crm_required)
        if crm_required and not identifier_value:
            _add_needs_review(
                needs_review_by_key,
                classification,
                review_reason="Нет надёжного идентификатора для CRM-проверки",
            )
            continue

        _remove_needs_review(needs_review_by_key, classification)
        created_at = _max_timestamp_seconds(event)
        lead = _find_duplicate(leads, identifier_type, identifier_value, created_at, channel="MAX")
        source = classification.get("business_source") or classification.get("display_name") or category
        received_at = unix_to_moscow_iso(created_at)

        if lead is None:
            lead = {
                "id": make_lead_id(identifier_type, identifier_value, message_id, created_at),
                "source": source,
                "category": category,
                "channel": "MAX",
                "message_id": message_id,
                "first_seen_at": received_at,
                "first_seen_ts": created_at,
                "received_at": received_at,
                "last_seen_at": received_at,
                "last_seen_ts": created_at,
                "event_date": fields.get("event_date", ""),
                "guests": fields.get("guests_count"),
                "guests_raw": fields.get("guests_raw", ""),
                "guests_min": fields.get("guests_min"),
                "guests_max": fields.get("guests_max"),
                "name": fields.get("name", ""),
                "phone": fields.get("phone_raw", ""),
                "username": fields.get("telegram_username", ""),
                "sender_user_id": event.get("sender_user_id"),
                "sender_name": event.get("sender_name", ""),
                "identifier": {
                    "type": identifier_type,
                    "value": identifier_value,
                },
                "max": {
                    "chat_id": event.get("chat_id"),
                    "message_ids": [],
                    "sender_user_id": event.get("sender_user_id"),
                    "sender_username": event.get("sender_username"),
                    "sender_name": event.get("sender_name"),
                },
                "fields": fields,
                "manager_reaction": None,
                "crm_required": crm_required,
                "crm": {"found": False, "required": crm_required},
                "crm_found": False,
                "crm_created_at": None,
                "crm_responsible": None,
                "deadline_msk_ts": moscow_day_deadline_ts(created_at),
                "status": "PENDING" if crm_required else "OK",
                "violations": [],
            }
            leads.append(lead)
        else:
            _merge_fields(lead["fields"], fields)
            if crm_required:
                lead["crm_required"] = True
            if created_at > int(lead["last_seen_ts"]):
                lead["last_seen_ts"] = created_at
                lead["last_seen_at"] = received_at
            lead.setdefault("max", {"message_ids": []})

        max_payload = lead.setdefault("max", {"message_ids": []})
        max_payload.setdefault("message_ids", [])
        if message_id and message_id not in max_payload["message_ids"]:
            max_payload["message_ids"].append(message_id)

    for key, override in review_overrides_by_key.items():
        if key in applied_override_keys:
            continue
        review_item = needs_review_by_key.get(key)
        if not review_item:
            continue
        event = _event_from_review_item(review_item)
        _apply_review_override(leads, needs_review_by_key, event, override, key)
        applied_override_keys.add(key)

    leads_by_message_id = {
        message_id: lead
        for lead in leads
        for message_id in (lead.get("telegram") or {}).get("message_ids", [])
    }

    for event in sorted(events, key=lambda item: int(item.get("update_id", 0))):
        if event.get("type") != "telegram_reaction" or not event.get("is_manager"):
            continue
        lead = leads_by_message_id.get(event.get("message_id"))
        if not lead:
            continue
        if event.get("action") == "reaction_removed":
            current = lead.get("manager_reaction") or {}
            if current.get("user_id") == event["manager"].get("user_id"):
                lead["manager_reaction"] = None
            continue

        lead["manager_reaction"] = {
            "name": event["manager"]["name"],
            "username": event["manager"]["username"],
            "user_id": event["manager"].get("user_id"),
            "reacted_at": event["telegram_date_msk"],
            "reacted_ts": event["telegram_date"],
            "update_id": event["update_id"],
            "reaction": event.get("new_reaction", []),
        }

    return leads, list(needs_review_by_key.values())


def apply_crm(leads: list[dict[str, Any]], client: AmoCRMClient) -> None:
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

        identifier = lead.get("identifier") or {}
        result = client.search(
            query=identifier.get("value", ""),
            lead_id=lead["id"],
            identifier_type=identifier.get("type", ""),
        )
        lead["crm"] = result.as_dict()
        _update_status(lead)


def _normalize_message_update(update_id: int, message: dict[str, Any], chat_id: int) -> dict[str, Any] | None:
    chat = message.get("chat") or {}
    if int(chat.get("id", 0)) != chat_id:
        return None

    sender = message.get("from") or {}
    lead = parse_message(message)
    if lead is None:
        text = str(message.get("text") or "").strip()
        if not text or _telegram_ignored_text_reason(text):
            return None

        return {
            "type": "telegram_needs_review",
            "update_id": update_id,
            "chat_id": int(chat["id"]),
            "message_id": int(message["message_id"]),
            "telegram_date": int(message["date"]),
            "telegram_date_msk": unix_to_moscow_iso(int(message["date"])),
            "sender_user_id": sender.get("id"),
            "sender_username": sender.get("username") or "",
            "sender_name": _telegram_sender_name(sender),
            "text": text,
            "review_reason": _telegram_review_reason(text),
        }

    ignored_reason = lead.pop("ignored_reason", "")
    return {
        "type": "telegram_lead",
        "update_id": update_id,
        "chat_id": int(chat["id"]),
        "message_id": int(message["message_id"]),
        "telegram_date": int(message["date"]),
        "telegram_date_msk": unix_to_moscow_iso(int(message["date"])),
        "sender_user_id": sender.get("id"),
        "sender_username": sender.get("username") or "",
        "sender_name": _telegram_sender_name(sender),
        "source": lead["source"],
        "ignored": bool(ignored_reason),
        "ignored_reason": ignored_reason,
        "lead": lead,
    }


def _normalize_reaction_update(
    update_id: int,
    reaction: dict[str, Any],
    chat_id: int,
    known_manager_ids: dict[int, dict[str, str]],
) -> dict[str, Any] | None:
    chat = reaction.get("chat") or {}
    if int(chat.get("id", 0)) != chat_id:
        return None

    user = reaction.get("user") or {}
    manager = _identify_manager(user, known_manager_ids)
    if manager is None:
        return None

    new_reaction = reaction.get("new_reaction") or []
    return {
        "type": "telegram_reaction",
        "update_id": update_id,
        "chat_id": int(chat["id"]),
        "message_id": int(reaction["message_id"]),
        "telegram_date": int(reaction["date"]),
        "telegram_date_msk": unix_to_moscow_iso(int(reaction["date"])),
        "action": "reaction_set" if new_reaction else "reaction_removed",
        "is_manager": True,
        "manager": manager,
        "new_reaction": _compact_reactions(new_reaction),
    }


def _identify_manager(user: dict[str, Any], known_manager_ids: dict[int, dict[str, str]]) -> dict[str, Any] | None:
    user_id = user.get("id")
    username = str(user.get("username") or "").lower()

    manager = MANAGERS_BY_USERNAME.get(username)
    if manager:
        return {**manager, "user_id": user_id}

    if user_id is not None and int(user_id) in known_manager_ids:
        known = known_manager_ids[int(user_id)]
        return {**known, "user_id": int(user_id)}

    return None


def _compact_reactions(reactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for reaction in reactions:
        item = {"type": reaction.get("type")}
        if "emoji" in reaction:
            item["emoji"] = reaction["emoji"]
        if "custom_emoji_id" in reaction:
            item["custom_emoji_id"] = reaction["custom_emoji_id"]
        compacted.append(item)
    return compacted


def _lead_identifier(lead_data: dict[str, Any], message_id: int) -> tuple[str, str]:
    if lead_data.get("phone_digits"):
        return "phone", lead_data["phone_digits"]
    if lead_data.get("telegram_username"):
        return "telegram_username", lead_data["telegram_username"]
    return "telegram_message", str(message_id)


def _max_identifier(fields: dict[str, Any], message_id: str, crm_required: bool) -> tuple[str, str]:
    if fields.get("phone_digits"):
        return "phone", fields["phone_digits"]
    if fields.get("telegram_username"):
        return "telegram_username", fields["telegram_username"]
    if not crm_required and message_id:
        return "max_message", message_id
    return "", ""


def _max_fields(classification: dict[str, Any]) -> dict[str, Any]:
    fields = dict(classification.get("fields") or {})
    event_date_raw = fields.get("event_date_raw", "")
    return {
        "source": classification.get("business_source") or classification.get("display_name", ""),
        "category": classification["classification"],
        "name": fields.get("name", ""),
        "phone_raw": fields.get("phone_raw", ""),
        "phone_digits": fields.get("phone_digits", ""),
        "telegram_username": normalize_username(fields.get("telegram_username", "")),
        "event_date_raw": event_date_raw,
        "event_date": parse_event_date(event_date_raw),
        "guests_count": fields.get("guests_count"),
        "guests_raw": fields.get("guests_raw", ""),
        "guests_min": fields.get("guests_min"),
        "guests_max": fields.get("guests_max"),
        "event_type": fields.get("event_type", ""),
    }


def _apply_review_override(
    leads: list[dict[str, Any]],
    needs_review_by_key: dict[str, dict[str, Any]],
    event: dict[str, Any],
    override: dict[str, Any],
    key: str,
) -> None:
    decision = normalize_decision(str(override.get("decision") or ""))
    needs_review_by_key.pop(key, None)
    legacy_key = f"{override.get('channel')}:{override.get('message_id')}"
    needs_review_by_key.pop(legacy_key, None)

    if decision == IGNORE:
        return

    text = str(event.get("text") or override.get("original_text") or "")
    fields = _manual_fields(text, decision)
    crm_required = decision not in CRM_FREE_DECISIONS
    channel = _event_channel(event, override)
    chat_id = int(event.get("chat_id") or override.get("chat_id"))
    message_id = event.get("message_id") or override.get("message_id")
    created_at = _review_event_timestamp_seconds(event)
    identifier_type, identifier_value, crm_check_status = _manual_identifier(
        fields,
        channel,
        chat_id,
        str(message_id),
        crm_required,
    )
    source = _manual_source(decision)
    received_at = unix_to_moscow_iso(created_at)
    lead_channel = "MAX" if channel == "MAX" else "TELEGRAM"
    lead = _find_duplicate(leads, identifier_type, identifier_value, created_at, channel=lead_channel)

    if lead is None:
        lead = {
            "id": make_lead_id(identifier_type, identifier_value, message_id, created_at),
            "source": source,
            "category": decision,
            "channel": lead_channel,
            "message_id": message_id,
            "first_seen_at": received_at,
            "first_seen_ts": created_at,
            "received_at": received_at,
            "last_seen_at": received_at,
            "last_seen_ts": created_at,
            "event_date": fields.get("event_date", ""),
            "guests": fields.get("guests_count"),
            "guests_raw": fields.get("guests_raw", ""),
            "guests_min": fields.get("guests_min"),
            "guests_max": fields.get("guests_max"),
            "name": fields.get("name", ""),
            "phone": fields.get("phone_raw", ""),
            "username": fields.get("telegram_username", ""),
            "sender_user_id": event.get("sender_user_id"),
            "sender_name": event.get("sender_name", ""),
            "sender_username": event.get("sender_username", ""),
            "identifier": {
                "type": identifier_type,
                "value": identifier_value,
            },
            "fields": fields,
            "manager_reaction": None,
            "crm_required": crm_required,
            "crm_check_status": crm_check_status,
            "crm": {"found": False, "required": crm_required, "check_status": crm_check_status},
            "crm_found": False,
            "crm_created_at": None,
            "crm_responsible": None,
            "deadline_msk_ts": moscow_day_deadline_ts(created_at),
            "status": "OK" if crm_required is False else "PENDING",
            "violations": [],
            "manual_review": {
                "decision": decision,
                "decided_at": override.get("decided_at"),
                "key": key,
            },
        }
        if channel == "MAX":
            lead["max"] = {
                "chat_id": chat_id,
                "message_ids": [],
                "sender_user_id": event.get("sender_user_id"),
                "sender_username": event.get("sender_username"),
                "sender_name": event.get("sender_name"),
            }
        else:
            lead["telegram"] = {
                "chat_id": chat_id,
                "message_ids": [],
                "update_ids": [],
            }
        leads.append(lead)
    else:
        _merge_fields(lead["fields"], fields)
        lead.setdefault("manual_review", {
            "decision": decision,
            "decided_at": override.get("decided_at"),
            "key": key,
        })
        if crm_required:
            lead["crm_required"] = True
        if lead.get("crm_check_status") in ("", None):
            lead["crm_check_status"] = crm_check_status
        if created_at > int(lead["last_seen_ts"]):
            lead["last_seen_ts"] = created_at
            lead["last_seen_at"] = received_at

    if channel == "MAX":
        max_payload = lead.setdefault("max", {"chat_id": chat_id, "message_ids": []})
        max_payload.setdefault("message_ids", [])
        if message_id and message_id not in max_payload["message_ids"]:
            max_payload["message_ids"].append(message_id)
    else:
        telegram_payload = lead.setdefault("telegram", {"chat_id": chat_id, "message_ids": [], "update_ids": []})
        telegram_payload.setdefault("message_ids", [])
        telegram_payload.setdefault("update_ids", [])
        if message_id not in telegram_payload["message_ids"]:
            telegram_payload["message_ids"].append(message_id)
        if event.get("update_id") is not None and event["update_id"] not in telegram_payload["update_ids"]:
            telegram_payload["update_ids"].append(event["update_id"])


def _manual_fields(text: str, decision: str) -> dict[str, Any]:
    classification = classify_max_text(text)
    if classification.get("classification") == decision:
        return _max_fields(classification)

    parsed = _parse_manual_key_value_fields(text)
    phone_raw = parsed.get("phone") or _extract_manual_phone_raw(text)
    event_date_raw = parsed.get("event_date") or _extract_manual_date_raw(text)
    guests = _extract_manual_guest_fields(parsed.get("guests_count") or text)
    username = parsed.get("telegram_username") or _extract_manual_username(text)

    return {
        "source": _manual_source(decision),
        "category": decision,
        "name": parsed.get("name") or _extract_manual_name(text, phone_raw, username),
        "phone_raw": phone_raw,
        "phone_digits": normalize_phone(phone_raw),
        "telegram_username": normalize_username(username),
        "event_date_raw": event_date_raw,
        "event_date": parse_event_date(event_date_raw),
        "guests_count": guests.get("guests_count"),
        "guests_raw": guests.get("guests_raw", ""),
        "guests_min": guests.get("guests_min"),
        "guests_max": guests.get("guests_max"),
        "event_type": parsed.get("event_type", ""),
    }


def _manual_identifier(
    fields: dict[str, Any],
    channel: str,
    chat_id: int,
    message_id: str,
    crm_required: bool,
) -> tuple[str, str, str]:
    if fields.get("phone_digits"):
        return "phone", fields["phone_digits"], "PENDING" if crm_required else "NOT_REQUIRED"
    if fields.get("telegram_username"):
        return "telegram_username", fields["telegram_username"], "PENDING" if crm_required else "NOT_REQUIRED"
    if crm_required:
        return "review_message", f"{channel}:{chat_id}:{message_id}", "NO_IDENTIFIER"
    return f"{channel.lower()}_message", f"{channel}:{chat_id}:{message_id}", "NOT_REQUIRED"


def _manual_source(decision: str) -> str:
    return BUSINESS_SOURCES.get(decision, decision)


def _event_review_key(channel: str, event: dict[str, Any]) -> str:
    return review_key(channel, event.get("chat_id"), event.get("message_id"))


def _event_channel(event: dict[str, Any], override: dict[str, Any]) -> str:
    channel = str(override.get("channel") or "")
    if channel:
        return "MAX" if channel.upper() == "MAX" else "Telegram"
    if event.get("source") == "MAX" or event.get("type", "").startswith("max_"):
        return "MAX"
    return "Telegram"


def _event_from_review_item(item: dict[str, Any]) -> dict[str, Any]:
    sender = item.get("sender") or {}
    channel = str(item.get("channel") or "")
    event_type = "max_message_created" if channel.upper() == "MAX" else "telegram_needs_review"
    event: dict[str, Any] = {
        "type": event_type,
        "chat_id": item.get("chat_id"),
        "message_id": item.get("message_id"),
        "text": item.get("text") or "",
        "timestamp": item.get("timestamp"),
        "sender_user_id": sender.get("user_id"),
        "sender_username": sender.get("username"),
        "sender_name": sender.get("name"),
    }
    if channel.upper() == "MAX":
        event["source"] = "MAX"
    else:
        event["telegram_date"] = item.get("timestamp")
    return event


def _review_event_timestamp_seconds(event: dict[str, Any]) -> int:
    if event.get("telegram_date") is not None:
        return int(event.get("telegram_date") or 0)
    return _max_timestamp_seconds(event)


def _parse_manual_key_value_fields(text: str) -> dict[str, str]:
    aliases = {
        "name": {"name", "имя", "ваше имя"},
        "phone": {"phone", "телефон", "номер телефона", "tel"},
        "event_date": {"дата мероприятия", "дата", "event date"},
        "guests_count": {"количество персон", "количество гостей", "кол-во гостей", "гостей", "guests"},
        "event_type": {"тип мероприятия", "формат мероприятия", "event type"},
        "telegram_username": {"telegram", "telegram username", "username", "ник", "nickname"},
    }
    result: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*([^:=]{2,80})\s*[:=]\s*(.+?)\s*$", line)
        if not match:
            continue
        label = re.sub(r"\s+", " ", match.group(1).strip().lower())
        value = match.group(2).strip()
        for field_name, labels in aliases.items():
            if label in labels:
                result[field_name] = value
                break
    return result


def _extract_manual_phone_raw(text: str) -> str:
    for match in re.finditer(r"(\+?\d[\d\s().-]{3,}\d)", text):
        candidate = match.group(1).strip()
        if len(normalize_phone(candidate)) >= 10:
            return candidate
    return ""


def _extract_manual_username(text: str) -> str:
    match = re.search(r"@([A-Za-z0-9_]{3,})", text)
    return match.group(1) if match else ""


def _extract_manual_date_raw(text: str) -> str:
    match = re.search(r"\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b", text)
    return match.group(0) if match else ""


def _extract_manual_guest_fields(text: str | None) -> dict[str, Any]:
    if not text:
        return {"guests_count": None, "guests_raw": "", "guests_min": None, "guests_max": None}

    up_to = re.search(r"\bдо\s*(?P<max>\d{1,4})\s*п\.?", text, flags=re.IGNORECASE)
    if up_to:
        raw = _normalize_manual_guest_raw(up_to.group(0))
        return {"guests_count": None, "guests_raw": raw, "guests_min": None, "guests_max": int(up_to.group("max"))}

    range_match = re.search(r"\b(?P<min>\d{1,4})\s*[-–]\s*(?P<max>\d{1,4})\s*п\.?", text, flags=re.IGNORECASE)
    if range_match:
        guests_min = int(range_match.group("min"))
        guests_max = int(range_match.group("max"))
        if guests_min <= guests_max:
            raw = _normalize_manual_guest_raw(range_match.group(0))
            return {"guests_count": None, "guests_raw": raw, "guests_min": guests_min, "guests_max": guests_max}

    count_match = re.search(
        r"\b(?P<count>\d{1,4})\s*(?:п\.?|чел\.?|человек|гост(?:ей|я|ь)?|персон)\b",
        text,
        flags=re.IGNORECASE,
    )
    if count_match:
        return {
            "guests_count": int(count_match.group("count")),
            "guests_raw": _normalize_manual_guest_raw(count_match.group(0)),
            "guests_min": None,
            "guests_max": None,
        }

    direct = re.fullmatch(r"\s*(?P<count>\d{1,4})\s*", text)
    if direct:
        return {
            "guests_count": int(direct.group("count")),
            "guests_raw": direct.group("count"),
            "guests_min": None,
            "guests_max": None,
        }

    return {"guests_count": None, "guests_raw": "", "guests_min": None, "guests_max": None}


def _normalize_manual_guest_raw(value: str) -> str:
    raw = re.sub(r"\s+", " ", value.strip())
    raw = re.sub(r"\s*([-–])\s*", r"\1", raw)
    raw = re.sub(r"\s*п\.?$", "п.", raw, flags=re.IGNORECASE)
    return raw


def _extract_manual_name(text: str, phone_raw: str, username: str = "") -> str:
    contacts: list[str] = []
    if phone_raw:
        contacts.append(phone_raw)
    if username:
        clean_username = username.strip().lstrip("@")
        if clean_username:
            contacts.extend([f"@{clean_username}", clean_username])

    stop_words = {
        "заявка",
        "свадьба",
        "корпоратив",
        "юбилей",
        "банкет",
        "фуршет",
        "мероприятие",
        "дата",
        "зал",
        "вип",
        "просмотр",
        "бронь",
        "предбронь",
        "телефон",
        "telegram",
        "username",
    }

    for contact in contacts:
        if contact not in text:
            continue

        before, _, after = text.partition(contact)
        sides = (
            (after[:120], False),
            (before[-120:], True),
        )
        for side, reverse in sides:
            words = re.findall(r"[А-ЯЁ][а-яё]+|[A-Z][a-z]+", side)
            if reverse:
                words = list(reversed(words))
            for word in words:
                if word.casefold() not in stop_words:
                    return word

    return ""


def _add_needs_review(
    needs_review_by_key: dict[str, dict[str, Any]],
    classification: dict[str, Any],
    review_reason: str | None = None,
) -> None:
    item = {
        "channel": "MAX",
        "source": "MAX",
        "message_id": classification.get("message_id"),
        "chat_id": classification.get("chat_id"),
        "sender": {
            "user_id": classification.get("sender_user_id"),
            "username": classification.get("sender_username"),
            "name": classification.get("sender_name"),
        },
        "timestamp": classification.get("timestamp"),
        "text": classification.get("text") or "",
        "review_reason": review_reason or classification.get("review_reason") or "ambiguous_max_message",
        "status": "NEEDS_REVIEW",
    }
    key = _needs_review_key(item)
    if key in needs_review_by_key:
        return

    needs_review_by_key[key] = item


def _add_telegram_needs_review(
    needs_review_by_key: dict[str, dict[str, Any]],
    event: dict[str, Any],
) -> None:
    item = {
        "channel": "Telegram",
        "source": "Telegram",
        "message_id": event.get("message_id"),
        "chat_id": event.get("chat_id"),
        "sender": {
            "user_id": event.get("sender_user_id"),
            "username": event.get("sender_username") or "",
            "name": event.get("sender_name") or "",
        },
        "timestamp": event.get("telegram_date"),
        "text": event.get("text") or "",
        "review_reason": event.get("review_reason") or "unmatched_telegram_message",
        "status": "NEEDS_REVIEW",
    }
    key = _needs_review_key(item)
    if key in needs_review_by_key:
        return

    needs_review_by_key[key] = item


def _remove_needs_review(
    needs_review_by_key: dict[str, dict[str, Any]],
    classification: dict[str, Any],
) -> None:
    message_id = classification.get("message_id")
    if message_id:
        needs_review_by_key.pop(f"MAX:{message_id}", None)
        chat_id = classification.get("chat_id")
        if chat_id is not None:
            needs_review_by_key.pop(f"MAX:{chat_id}:{message_id}", None)


def _needs_review_key(item: dict[str, Any]) -> str:
    channel = item.get("channel", "MAX")
    message_id = item.get("message_id")
    if message_id:
        chat_id = item.get("chat_id")
        if chat_id is not None:
            return review_key(str(channel), chat_id, message_id)
        return f"{channel}:{message_id}"
    return f"{channel}:{item.get('timestamp')}:{item.get('text')}"


def _telegram_ignored_text_reason(text: str) -> str:
    upper_lines = {line.strip().upper() for line in text.splitlines() if line.strip()}
    if "TEST" in upper_lines or "ТЕСТ" in upper_lines:
        return "test_marker"

    upper_text = text.upper()
    for phrase in TELEGRAM_TEST_PHRASES:
        if phrase in upper_text:
            return "test_phrase"

    for match in re.finditer(r"(\+?\d[\d\s().-]{8,}\d)", text):
        if re.sub(r"\D+", "", match.group(1)) in TELEGRAM_TEST_PHONES:
            return "test_phone"

    return ""


def _telegram_review_reason(text: str) -> str:
    if re.search(r"@([A-Za-z0-9_]{3,})", text):
        return "ambiguous_contact_or_event_details"
    if re.search(r"\+?\d[\d\s().-]{8,}\d", text):
        return "ambiguous_contact_or_event_details"
    if re.search(r"\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b", text):
        return "ambiguous_contact_or_event_details"
    return "unmatched_telegram_message"


def _telegram_sender_name(sender: dict[str, Any]) -> str:
    parts = [
        str(sender.get("first_name") or "").strip(),
        str(sender.get("last_name") or "").strip(),
    ]
    return " ".join(part for part in parts if part)


def _max_timestamp_seconds(event: dict[str, Any]) -> int:
    timestamp = int(event.get("timestamp") or 0)
    if timestamp > 10_000_000_000:
        return timestamp // 1000
    return timestamp


def _event_sort_key(event: dict[str, Any]) -> tuple[int, int, str]:
    if "update_id" in event:
        return (0, int(event.get("update_id") or 0), str(event.get("message_id", "")))
    timestamp = event.get("timestamp") or event.get("telegram_date") or 0
    try:
        numeric_timestamp = int(timestamp)
    except (TypeError, ValueError):
        numeric_timestamp = 0
    return (1, numeric_timestamp, str(event.get("message_id", "")))


def _find_duplicate(
    leads: list[dict[str, Any]],
    identifier_type: str,
    identifier_value: str,
    created_at: int,
    channel: str | None = None,
) -> dict[str, Any] | None:
    for lead in leads:
        if channel is not None and lead.get("channel") != channel:
            continue
        identifier = lead.get("identifier") or {}
        if identifier.get("type") != identifier_type or identifier.get("value") != identifier_value:
            continue
        if abs(created_at - int(lead["first_seen_ts"])) <= THREE_DAYS_SECONDS:
            return lead
    return None


def _merge_fields(current: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key, value in incoming.items():
        if current.get(key) in ("", None) and value not in ("", None):
            current[key] = value


def _update_status(lead: dict[str, Any]) -> None:
    crm = lead.get("crm") or {}
    crm_required = lead.get("crm_required", True)
    has_reaction = bool(lead.get("manager_reaction"))
    crm_found = bool(crm.get("found"))
    violations: list[str] = []

    lead["crm_found"] = crm_found
    lead["crm_created_at"] = crm.get("created_at")
    lead["crm_responsible"] = crm.get("responsible_user_id")

    if crm_required is False:
        lead["status"] = "OK"
        lead["violations"] = []
        lead["crm_required"] = False
        return

    late = False
    if crm_found and crm.get("created_at"):
        late = int(crm["created_at"]) > int(lead["deadline_msk_ts"])
        if late:
            violations.append("LATE_CRM")

    if lead.get("channel") == "MAX":
        if not crm_found:
            violations.append("ALARM_NO_CRM")
    else:
        if crm_found and not has_reaction:
            violations.append("NO_REACTION")
        if has_reaction and not crm_found:
            violations.append("ALARM_NO_CRM")

    if not violations and crm_found and (has_reaction or lead.get("channel") == "MAX"):
        status = "OK"
    elif "LATE_CRM" in violations:
        status = "LATE_CRM"
    elif "ALARM_NO_CRM" in violations:
        status = "ALARM_NO_CRM"
    elif "NO_REACTION" in violations:
        status = "NO_REACTION"
    else:
        status = "PENDING"

    lead["status"] = status
    lead["violations"] = violations
