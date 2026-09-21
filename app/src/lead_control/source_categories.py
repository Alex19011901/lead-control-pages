from __future__ import annotations

from typing import Any

from .parsers import parse_message
from .tatiana_history import LEGACY_TATIANA_TELEGRAM_MESSAGE_IDS


MARQUIZ = "MARQUIZ"
SITE_TILDA = "САЙТ ТИЛЬДА"
MAIL_LEAD = "ЗАЯВКА ПОЧТА"
TATIANA_TG = "ОТ ТАТЬЯНЫ ТГ"

_TATIANA_NAMES = {"tatiana ts"}
_TATIANA_USERNAMES = {"tati_ts_a"}
_TATIANA_USER_IDS = {1366518980}
_TILDA_TEST_NAMES = {"test", "тест"}

# Explicit one-off decision for this Telegram history only.
# Do not generalize this exclusion by sender, wording, format, or source.
_ONE_OFF_SKIPPED_TELEGRAM_MESSAGE_IDS = {5670}


def normalize_known_source_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for original in events:
        event = dict(original)

        if _is_one_off_skipped_telegram_message(event):
            continue

        if _event_is_tatiana(event):
            continue

        if event.get("type") == "telegram_needs_review":
            promoted = _promote_known_telegram_review(event)
            if promoted is not None:
                normalized.append(promoted)
                continue

        if event.get("type") == "telegram_lead":
            lead = dict(event.get("lead") or {})
            source = canonical_source(
                lead.get("source"),
                event.get("sender_name"),
                event.get("sender_username"),
            )
            if source == SITE_TILDA and _norm(lead.get("name")) in _TILDA_TEST_NAMES:
                continue
            if source:
                lead["source"] = source
                event["source"] = source
                event["lead"] = lead

        normalized.append(event)
    return normalized


def normalize_lead_sources(leads: list[dict[str, Any]]) -> None:
    leads[:] = [lead for lead in leads if not _lead_is_tatiana(lead)]

    for lead in leads:
        max_info = lead.get("max") or {}
        current_source = lead.get("source") or lead.get("category")

        if _norm(current_source) in {"тильда веранда", "заявка тильда веранда"}:
            continue

        source = canonical_source(
            current_source,
            lead.get("sender_name") or max_info.get("sender_name"),
            lead.get("sender_username") or max_info.get("sender_username"),
        )
        if not source:
            continue

        lead["source"] = source
        lead["category"] = source

        fields = lead.get("fields")
        if isinstance(fields, dict):
            fields["source"] = source
            fields["category"] = source


def filter_known_source_reviews(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        if _is_one_off_skipped_telegram_message(item):
            continue

        if _review_item_is_tatiana(item):
            continue

        sender = item.get("sender") or {}
        source = canonical_source(
            item.get("source"),
            sender.get("name"),
            sender.get("username"),
        )
        if source in {MARQUIZ, SITE_TILDA, MAIL_LEAD}:
            continue
        result.append(item)
    return result


def canonical_source(
    current_source: Any = None,
    sender_name: Any = None,
    sender_username: Any = None,
) -> str:
    current = _norm(current_source)
    sender_values = {_norm(sender_name), _norm(sender_username)}

    if current in {"marquiz", "marquizbot"} or sender_values & {"marquiz", "marquizbot"}:
        return MARQUIZ

    if current == "сайт тильда":
        return SITE_TILDA

    if sender_values & {"tildaforms", "tildaformsbot", "tildaforms_bot"}:
        return SITE_TILDA

    if current == "заявка почта":
        return MAIL_LEAD

    return ""


def is_tatiana_sender(
    sender_name: Any = None,
    sender_username: Any = None,
    sender_user_id: Any = None,
) -> bool:
    return (
        _norm_user_id(sender_user_id) in _TATIANA_USER_IDS
        or _norm(sender_name) in _TATIANA_NAMES
        or _norm_username(sender_username) in _TATIANA_USERNAMES
    )


def _is_one_off_skipped_telegram_message(item: dict[str, Any]) -> bool:
    channel = _norm(item.get("channel"))
    if channel == "max":
        return False

    item_type = _norm(item.get("type"))
    if item_type and not item_type.startswith("telegram_"):
        return False

    try:
        message_id = int(item.get("message_id"))
    except (TypeError, ValueError):
        return False
    return message_id in _ONE_OFF_SKIPPED_TELEGRAM_MESSAGE_IDS


def _event_is_tatiana(event: dict[str, Any]) -> bool:
    lead = event.get("lead") or {}
    legacy_values = {
        _norm(event.get("source")),
        _norm(lead.get("source")),
        _norm(lead.get("category")),
    }
    if _norm(TATIANA_TG) in legacy_values:
        return True

    channel = _norm(event.get("channel"))
    event_type = _norm(event.get("type"))
    if channel == "max" or event_type.startswith("max_") or _norm(event.get("source")) == "max":
        return False

    if event_type.startswith("telegram_"):
        try:
            message_id = int(event.get("message_id"))
        except (TypeError, ValueError):
            message_id = None
        if message_id in LEGACY_TATIANA_TELEGRAM_MESSAGE_IDS:
            return True

    return is_tatiana_sender(
        event.get("sender_name") or lead.get("sender_name"),
        event.get("sender_username") or lead.get("sender_username"),
        event.get("sender_user_id") or lead.get("sender_user_id"),
    )


def _lead_is_tatiana(lead: dict[str, Any]) -> bool:
    fields = lead.get("fields") or {}
    legacy_values = {
        _norm(lead.get("source")),
        _norm(lead.get("category")),
        _norm(fields.get("source")),
        _norm(fields.get("category")),
    }
    if _norm(TATIANA_TG) in legacy_values:
        return True

    channel = _norm(lead.get("channel"))
    if channel == "max":
        return False

    telegram_message_ids = (lead.get("telegram") or {}).get("message_ids", [])
    for message_id in telegram_message_ids:
        try:
            normalized_message_id = int(message_id)
        except (TypeError, ValueError):
            continue
        if normalized_message_id in LEGACY_TATIANA_TELEGRAM_MESSAGE_IDS:
            return True

    return is_tatiana_sender(
        lead.get("sender_name") or fields.get("sender_name"),
        lead.get("sender_username") or fields.get("sender_username"),
        lead.get("sender_user_id") or fields.get("sender_user_id"),
    )


def _review_item_is_tatiana(item: dict[str, Any]) -> bool:
    if _norm(item.get("source")) == _norm(TATIANA_TG):
        return True

    channel = _norm(item.get("channel"))
    if channel == "max":
        return False

    try:
        message_id = int(item.get("message_id"))
    except (TypeError, ValueError):
        message_id = None
    if message_id in LEGACY_TATIANA_TELEGRAM_MESSAGE_IDS:
        return True

    sender = item.get("sender") or {}
    return is_tatiana_sender(
        sender.get("name") or item.get("sender_name"),
        sender.get("username") or item.get("sender_username"),
        sender.get("user_id") or sender.get("id") or item.get("sender_user_id"),
    )


def _promote_known_telegram_review(event: dict[str, Any]) -> dict[str, Any] | None:
    sender_name = str(event.get("sender_name") or "")
    sender_username = str(event.get("sender_username") or "")

    message = {
        "text": str(event.get("text") or ""),
        "from": {
            "id": event.get("sender_user_id"),
            "username": sender_username,
            "first_name": sender_name,
        },
    }
    lead = parse_message(message)
    if lead is None:
        return None

    source = canonical_source(lead.get("source"), sender_name, sender_username) or str(lead.get("source") or "")
    if not source:
        return None

    lead["source"] = source
    ignored_reason = lead.pop("ignored_reason", "")
    return {
        "type": "telegram_lead",
        "update_id": event["update_id"],
        "chat_id": event["chat_id"],
        "message_id": event["message_id"],
        "telegram_date": event["telegram_date"],
        "telegram_date_msk": event["telegram_date_msk"],
        "sender_user_id": event.get("sender_user_id"),
        "sender_username": sender_username,
        "sender_name": sender_name,
        "source": source,
        "ignored": bool(ignored_reason),
        "ignored_reason": ignored_reason,
        "lead": lead,
    }


def _norm(value: Any) -> str:
    return str(value or "").strip().casefold()


def _norm_username(value: Any) -> str:
    return _norm(value).removeprefix("@")


def _norm_user_id(value: Any) -> int | None:
    text = str(value or "").strip().casefold()
    if text.startswith("user"):
        text = text[4:]
    try:
        return int(text)
    except (TypeError, ValueError):
        return None
