from __future__ import annotations

import re
from typing import Any


# Start the new name-correction policy prospectively. Historical lead names are
# left untouched unless they are rebuilt by older parser rules themselves.
EXPLICIT_NAME_POLICY_START_TS = 1789419600  # 2026-09-15 00:00:00 MSK

_GREETING_NAMES = {
    "добрый",
    "добрый день",
    "добрый вечер",
    "доброе утро",
    "здравствуйте",
    "привет",
    "приветствую",
}

_NAME = r"([А-ЯЁ][а-яё-]+(?:\s+[А-ЯЁ][а-яё-]+)?)"
_EXPLICIT_NAME_PATTERNS = (
    rf"(?i:\bменя\s+зовут\s*[:\-—]?\s*){_NAME}\b",
    rf"(?i:\b(?:мо[её]\s+имя)\s*[:\-—]?\s*){_NAME}\b",
    rf"(?i:(?:^|[.!?]\s*|\n\s*)это\s*[:\-—]?\s*){_NAME}\b",
    rf"(?i:(?:^|[.!?]\s*|\n\s*)с\s+вами\s*[:\-—]?\s*){_NAME}\b",
    rf"(?i:(?:^|[.!?]\s*|\n\s*)я\s*[:\-—]?\s*){_NAME}\b(?=\s*[,.;!?]|\s*$)",
)


def apply_explicit_client_names(leads: list[dict[str, Any]], events: list[dict[str, Any]]) -> None:
    """Prefer explicit client self-introductions over guessed MAX names.

    This is intentionally narrow: it only applies to MAX messages from the new
    policy date onward. If there is no explicit self-introduction, obvious
    greeting words are removed rather than kept as a client name.
    """
    max_events_by_message_id = {
        str(event.get("message_id")): event
        for event in events
        if event.get("type") == "max_message_created" and event.get("message_id")
    }

    for lead in leads:
        if str(lead.get("channel") or "").upper() != "MAX":
            continue

        message_ids = list((lead.get("max") or {}).get("message_ids") or [])
        if lead.get("message_id"):
            message_ids.append(lead.get("message_id"))

        source_events: list[dict[str, Any]] = []
        for message_id in message_ids:
            event = max_events_by_message_id.get(str(message_id))
            if not event:
                continue
            if _event_ts(event) < EXPLICIT_NAME_POLICY_START_TS:
                continue
            source_events.append(event)

        if not source_events:
            continue

        explicit_name = ""
        for event in source_events:
            explicit_name = extract_explicit_client_name(str(event.get("text") or ""))
            if explicit_name:
                break

        fields = lead.setdefault("fields", {})
        if explicit_name:
            fields["name"] = explicit_name
            lead["name"] = explicit_name
            lead["name_source"] = "MESSAGE_EXPLICIT"
            continue

        current_name = str(lead.get("name") or fields.get("name") or "").strip()
        if _looks_like_greeting_name(current_name):
            fields["name"] = ""
            lead["name"] = ""
            lead["name_source"] = "MESSAGE_REJECTED_GREETING"


def extract_explicit_client_name(text: str) -> str:
    for pattern in _EXPLICIT_NAME_PATTERNS:
        match = re.search(pattern, text, flags=re.MULTILINE)
        if not match:
            continue
        candidate = match.group(1).strip()
        if candidate and not _looks_like_greeting_name(candidate):
            return candidate
    return ""


def _event_ts(event: dict[str, Any]) -> int:
    try:
        raw = int(event.get("timestamp") or 0)
    except (TypeError, ValueError):
        return 0
    if raw > 10_000_000_000:
        raw //= 1000
    return raw


def _looks_like_greeting_name(value: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(value or "").strip().casefold().replace("ё", "е"))
    return normalized in _GREETING_NAMES
