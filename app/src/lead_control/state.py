from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_STATE = {
    "schema_version": 1,
    "telegram": {"next_offset": None},
    "max": {"marker": None},
    "last_data_update_at": None,
}

DEFAULT_LEADS = {
    "schema_version": 1,
    "leads": [],
}

DEFAULT_NEEDS_REVIEW = {
    "schema_version": 1,
    "items": [],
}

DEFAULT_REVIEW_OVERRIDES = {
    "schema_version": 1,
    "items": [],
}

DEFAULT_REPORT = {
    "updated_at": None,
    "total_leads": 0,
    "needs_review": 0,
    "ok": 0,
    "late_crm": 0,
    "alarm_no_crm": 0,
    "no_reaction": 0,
    "by_source": {},
    "by_manager": {},
    "event_types": {},
    "guest_ranges": {
        "1-20": 0,
        "21-50": 0,
        "51-100": 0,
        "101-150": 0,
        "151+": 0,
        "unknown": 0,
    },
    "latest_leads": [],
}


def ensure_data_files(data_dir: Path) -> bool:
    data_dir.mkdir(parents=True, exist_ok=True)
    changed = False
    changed |= _write_default(data_dir / "state.json", DEFAULT_STATE)
    changed |= _write_default(data_dir / "leads.json", DEFAULT_LEADS)
    changed |= _write_default(data_dir / "needs_review.json", DEFAULT_NEEDS_REVIEW)
    changed |= _write_default(data_dir / "review_overrides.json", DEFAULT_REVIEW_OVERRIDES)
    changed |= _write_default(data_dir / "latest_report.json", DEFAULT_REPORT)
    events_path = data_dir / "events.ndjson"
    if not events_path.exists():
        events_path.write_text("", encoding="utf-8")
        changed = True
    return changed


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, value: Any) -> None:
    text = stable_json(value) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.write_text(text, encoding="utf-8")


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            events.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON in events.ndjson at line {line_number}") from exc
    return events


def append_events(path: Path, events: list[dict[str, Any]]) -> None:
    if not events:
        return
    with path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def save_events(path: Path, events: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.write_text(text, encoding="utf-8")


def _write_default(path: Path, value: Any) -> bool:
    if path.exists():
        return False
    save_json(path, value)
    return True
