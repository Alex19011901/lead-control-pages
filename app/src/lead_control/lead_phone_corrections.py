"""Apply verified, message-specific phone corrections without editing source events.

The raw event log remains an audit trail.  Correct only working copies that
are passed into the existing lead reconstruction and duplicate detection.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .normalize import normalize_phone


def _message_key(event: dict[str, Any]) -> tuple[str, str, str] | None:
    kind = str(event.get("type") or "")
    if kind == "max_message_created" and event.get("source") == "MAX":
        channel = "MAX"
    elif kind == "telegram_lead":
        channel = "TELEGRAM"
    else:
        return None
    return (channel, str(event.get("chat_id") or ""), str(event.get("message_id") or ""))


def _replace_exact_phone(value: str, old: str, new: str) -> str:
    # Match entire digit runs, not a fragment of a longer number.
    pat = re.compile(r"(?<!\d)" + re.escape(old) + r"(?!\d)")
    return pat.sub(new, value)


def apply_lead_phone_corrections(
    events: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return corrected working events; fail closed on any unexpected source.

    Does not mutate the original events list or the raw events.ndjson file.
    """
    if int(config.get("schema_version") or 0) != 1:
        raise ValueError("Unsupported phone correction schema")
    raw_rules = config.get("phone_corrections") or []
    if not isinstance(raw_rules, list):
        raise ValueError("Phone correction entries must be a list")

    rules: dict[tuple[str, str, str], tuple[str, str]] = {}
    for item in raw_rules:
        if not isinstance(item, dict):
            raise ValueError("Invalid phone correction entry")
        key = (
            str(item.get("channel") or "").strip().upper(),
            str(item.get("chat_id") or ""),
            str(item.get("message_id") or ""),
        )
        old = normalize_phone(str(item.get("original_phone") or ""))
        new = normalize_phone(str(item.get("correct_phone") or ""))
        if key[0] not in {"MAX", "TELEGRAM"} or not all(key) or len(old) != 11 or len(new) != 11 or old == new:
            raise ValueError("Invalid correction identifier or phone")
        if key in rules:
            raise ValueError(f"Duplicate phone correction for {key}")
        rules[key] = (old, new)

    if not rules:
        return events

    seen: set[tuple[str, str, str]] = set()
    working: list[dict[str, Any]] = []

    for event in events:
        key = _message_key(event)
        if key not in rules:
            working.append(event)
            continue
        if key in seen:
            raise ValueError(f"Duplicate source event for correction {key}")
        seen.add(key)
        old, new = rules[key]
        updated = deepcopy(event)

        if key[0] == "MAX":
            original = str(updated.get("text") or "")
            changed = _replace_exact_phone(original, old, new)
            if changed == original and not re.search(r"(?<!\d)" + new + r"(?!\d)", original):
                raise ValueError(f"Expected phone not found in MAX event {key}")
            updated["text"] = changed
        else:
            lead = updated.get("lead")
            if not isinstance(lead, dict):
                raise ValueError(f"Missing Telegram lead data for {key}")
            existing = normalize_phone(str(lead.get("phone_raw") or lead.get("phone_digits") or ""))
            if existing not in {old, new}:
                raise ValueError(f"Unexpected Telegram lead phone for {key}")
            lead["phone_raw"] = "+" + new
            lead["phone_digits"] = new
            for field in ("description",):
                if isinstance(lead.get(field), str):
                    lead[field] = _replace_exact_phone(lead[field], old, new)
            if isinstance(updated.get("text"), str):
                updated["text"] = _replace_exact_phone(updated["text"], old, new)

        working.append(updated)

    missing = set(rules) - seen
    if missing:
        raise ValueError(f"Source messages not found for phone corrections: {sorted(missing)}")
    return working
