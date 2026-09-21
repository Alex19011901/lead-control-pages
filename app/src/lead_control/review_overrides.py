from __future__ import annotations

from typing import Any

from .parsers.max_leads import HOST, IGNORE, STREET, TG_LEAD, TILDA_VERANDA, WEDWED


VALID_DECISIONS = {HOST, STREET, TG_LEAD, TILDA_VERANDA, WEDWED, IGNORE}
CRM_FREE_DECISIONS = {TILDA_VERANDA, WEDWED}


def normalize_channel(value: str) -> str:
    normalized = value.strip()
    if normalized.upper() == "MAX":
        return "MAX"
    if normalized.lower() in {"telegram", "tg"}:
        return "Telegram"
    raise ValueError(f"Unsupported review channel: {value}")


def normalize_decision(value: str) -> str:
    decision = value.strip().upper()
    if decision not in VALID_DECISIONS:
        allowed = ", ".join(sorted(VALID_DECISIONS))
        raise ValueError(f"Unsupported review decision: {value}. Allowed: {allowed}")
    return decision


def review_key(channel: str, chat_id: int | str, message_id: int | str) -> str:
    return f"{normalize_channel(str(channel))}:{int(chat_id)}:{message_id}"


def review_key_from_item(item: dict[str, Any]) -> str:
    return review_key(
        str(item.get("channel") or ""),
        item.get("chat_id"),
        item.get("message_id"),
    )


def overrides_by_key(items: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items or []:
        key = review_key_from_item(item)
        result[key] = item
    return result


def find_needs_review_item(
    items: list[dict[str, Any]],
    *,
    channel: str,
    chat_id: int,
    message_id: str,
) -> dict[str, Any] | None:
    key = review_key(channel, chat_id, message_id)
    for item in items:
        if review_key_from_item(item) == key:
            return item
    return None


def build_override(item: dict[str, Any], decision: str, decided_at: str) -> dict[str, Any]:
    return {
        "channel": normalize_channel(str(item.get("channel") or "")),
        "chat_id": int(item["chat_id"]),
        "message_id": item["message_id"],
        "decision": normalize_decision(decision),
        "decided_at": decided_at,
        "original_text": item.get("text") or "",
    }


def upsert_override(
    items: list[dict[str, Any]],
    override: dict[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    key = review_key_from_item(override)
    result: list[dict[str, Any]] = []
    changed = True
    inserted = False

    for item in items:
        if review_key_from_item(item) != key:
            result.append(item)
            continue

        existing_decision = normalize_decision(str(item.get("decision") or ""))
        incoming_decision = normalize_decision(str(override.get("decision") or ""))
        if existing_decision != incoming_decision:
            raise ValueError(
                f"Review override already exists for {key} with decision {existing_decision}"
            )
        result.append(item)
        changed = False
        inserted = True

    if not inserted:
        result.append(override)

    return result, changed
