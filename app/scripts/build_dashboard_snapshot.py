from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.event_type import infer_event_type, normalize_event_type


# Raw text was discarded by the old Telegram/Tilda parser for a small number
# of already-collected leads. Keep only event types explicitly verified from
# the original message until the full Telegram export is imported.
VERIFIED_EVENT_TYPE_BY_IDENTIFIER = {
    "79161553602": "Свадьба",
}


def guest_bucket(lead: dict) -> str:
    g = lead.get("guests")
    if g is None:
        g = (lead.get("fields") or {}).get("guests_count")
    if g is None:
        g = lead.get("guests_max")
    if g is None:
        g = lead.get("guests_min")
    if g is None:
        return "unknown"
    try:
        g = int(g)
    except (TypeError, ValueError):
        return "unknown"
    if g <= 20:
        return "1-20"
    if g <= 50:
        return "21-50"
    if g <= 100:
        return "51-100"
    if g <= 150:
        return "101-150"
    return "151+"


def _normalize_guest_display(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*[-–—]\s*", "-", text)
    text = re.sub(
        r"\s*(?:п\.?|персон(?:ы)?|перс|чел\.?|человек|гост(?:ей|я|и|ь)?)\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()


def _guest_from_text(text: object) -> str:
    raw = str(text or "")
    if not raw:
        return ""

    labeled_patterns = [
        r"(?:количество[_ ]персон|количество[_ ]гостей|кол-во[_ ]гостей|гостей|guests|input)\s*[:=]\s*(?P<v>(?:до\s*)?\d{1,4}(?:\s*[-–—]\s*\d{1,4})?\+?)",
        r"сколько\s+гостей[^\d]{0,80}(?P<v>(?:до\s*)?\d{1,4}(?:\s*[-–—]\s*\d{1,4})?\+?)",
    ]
    for pattern in labeled_patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            return _normalize_guest_display(match.group("v"))

    natural = re.search(
        r"\b(?P<v>(?:до\s*)?\d{1,4}(?:\s*[-–—]\s*\d{1,4})?\+?)\s*"
        r"(?:п\.?|персон(?:ы)?|перс|чел\.?|человек|гост(?:ей|я|и|ь)?)\b",
        raw,
        flags=re.IGNORECASE,
    )
    if natural:
        return _normalize_guest_display(natural.group("v"))
    return ""


def exact_guest_display(lead: dict) -> str:
    crm = lead.get("crm") or {}
    crm_value = _normalize_guest_display(crm.get("guests"))
    if crm.get("found") and crm_value:
        return crm_value

    fields = lead.get("fields") or {}

    for text in (
        fields.get("description"),
        lead.get("description"),
        lead.get("text"),
    ):
        value = _guest_from_text(text)
        if value:
            return value

    raw = fields.get("guests_raw") or lead.get("guests_raw")
    if raw:
        value = _normalize_guest_display(raw)
        if value:
            return value

    count = fields.get("guests_count")
    if count is None:
        count = lead.get("guests_count")
    if count is None:
        count = lead.get("guests")
    if count is not None and str(count).strip() != "":
        try:
            return str(int(count))
        except (TypeError, ValueError):
            return _normalize_guest_display(count)

    gmin = fields.get("guests_min")
    if gmin is None:
        gmin = lead.get("guests_min")
    gmax = fields.get("guests_max")
    if gmax is None:
        gmax = lead.get("guests_max")

    if gmin is not None and gmax is not None:
        return f"{gmin}-{gmax}"
    if gmax is not None:
        return f"до {gmax}"
    if gmin is not None:
        return f"от {gmin}"
    return ""


def canonical_source(value: object) -> str:
    source = str(value or "unknown").strip()
    key = source.casefold()
    if key in {"marquiz", "marquizbot"}:
        return "MARQUIZ"
    if key in {"tildaforms", "tildaformsbot", "tildaforms_bot", "сайт тильда"}:
        return "САЙТ ТИЛЬДА"
    if key == "заявка почта":
        return "Заявка почта"
    return source or "unknown"


def source_for_lead(lead: dict) -> str:
    channel = str(lead.get("channel") or "").strip().upper()
    current = str(lead.get("source") or (lead.get("fields") or {}).get("source") or "unknown").strip()
    category = str(lead.get("category") or (lead.get("fields") or {}).get("category") or "").strip().casefold()
    max_info = lead.get("max") or {}
    sender_values = {
        str(lead.get("sender_name") or "").strip().casefold(),
        str(lead.get("sender_username") or "").strip().casefold(),
        str(max_info.get("sender_name") or "").strip().casefold(),
        str(max_info.get("sender_username") or "").strip().casefold(),
    }

    # TildaForms arriving through MAX is the existing "Тильда Веранда" source.
    # Direct Telegram TildaForms is the separate "САЙТ ТИЛЬДА" source.
    if channel == "MAX" and (
        current.casefold() in {"тильда веранда", "заявка тильда веранда", "сайт тильда"}
        or category in {"tilda_veranda", "сайт тильда"}
        or sender_values & {"tildaforms", "tildaformsbot", "tildaforms_bot"}
    ):
        return "Тильда Веранда"

    return canonical_source(current)


def identifier_value(lead: dict) -> str:
    ident = lead.get("identifier")
    if isinstance(ident, dict):
        ident = ident.get("value") or ""
    return str(ident or lead.get("phone") or lead.get("username") or "")


def event_type_for_lead(lead: dict) -> str:
    fields = lead.get("fields") or {}
    explicit = fields.get("event_type") or lead.get("event_type")
    if explicit:
        normalized = normalize_event_type(explicit)
        if normalized:
            return normalized

    for text in (
        fields.get("description"),
        lead.get("description"),
        lead.get("text"),
        fields.get("event_format"),
    ):
        inferred = infer_event_type(text)
        if inferred:
            return inferred

    verified = VERIFIED_EVENT_TYPE_BY_IDENTIFIER.get(identifier_value(lead))
    if verified:
        return verified

    return "unknown"


def crm_manager_name(lead: dict) -> str:
    crm = lead.get("crm") or {}
    return str(crm.get("responsible_user_name") or "").strip()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build(input_path: Path, output_path: Path, view_output_path: Path | None = None) -> None:
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    leads = raw.get("leads", raw if isinstance(raw, list) else [])

    daily = defaultdict(
        lambda: {
            "total": 0,
            "status": Counter(),
            "source": Counter(),
            "guest_ranges": Counter(),
            "event_types": Counter(),
            "channel": Counter(),
        }
    )
    compact = []

    for lead in leads:
        ts = lead.get("received_at") or lead.get("first_seen_at") or ""
        day = ts[:10]
        if not day:
            continue

        status = lead.get("status") or "UNKNOWN"
        source = source_for_lead(lead)
        channel = lead.get("channel") or "unknown"
        event_type = event_type_for_lead(lead)
        guest_value = exact_guest_display(lead)
        guest_key = guest_value or "unknown"

        d = daily[day]
        d["total"] += 1
        d["status"][status] += 1
        d["source"][source] += 1
        d["guest_ranges"][guest_key] += 1
        d["event_types"][event_type] += 1
        d["channel"][channel] += 1

        compact.append(
            {
                "date": day,
                "ts": ts,
                "source": source,
                "status": status,
                "channel": channel,
                "guest_range": guest_key,
                "guests": guest_value,
                "event_type": event_type,
                "name": lead.get("name") or (lead.get("fields") or {}).get("name") or "",
                "identifier": identifier_value(lead),
                "manager": crm_manager_name(lead),
            }
        )

    compact.sort(key=lambda x: x["ts"], reverse=True)
    out = {
        "snapshot_generated_at": utc_now(),
        "generated_at": compact[0]["ts"] if compact else "",
        "min_date": min(daily) if daily else None,
        "max_date": max(daily) if daily else None,
        "daily": {
            day: {
                "total": values["total"],
                "status": dict(values["status"]),
                "source": dict(values["source"]),
                "guest_ranges": dict(values["guest_ranges"]),
                "event_types": dict(values["event_types"]),
                "channel": dict(values["channel"]),
            }
            for day, values in sorted(daily.items())
        },
        "leads": compact,
        "latest": compact[:40],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    output_path.write_text(payload, encoding="utf-8")
    if view_output_path is not None:
        view_output_path.parent.mkdir(parents=True, exist_ok=True)
        view_output_path.write_text(payload, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--view-output")
    args = parser.parse_args()
    build(Path(args.input), Path(args.output), Path(args.view_output) if args.view_output else None)


if __name__ == "__main__":
    main()
