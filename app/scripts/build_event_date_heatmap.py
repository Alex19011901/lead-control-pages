from __future__ import annotations

"""Independent event-date demand counter: never changes lead or CRM states."""

import argparse
import json
import re
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

MONTH_NAMES = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
MONTH_WORDS = "|".join(MONTH_NAMES)
DATE_RANGE = re.compile(
    r"(?<![\d./])(\d{1,2})[./](\d{1,2})(?:[./](20\d{2}|\d{2}))?"
    r"\s*[-–—]\s*(\d{1,2})[./](\d{1,2})(?:[./](20\d{2}|\d{2}))?(?!\d)"
)
DAY_RANGE = re.compile(
    r"(?<![\d./])(\d{1,2})\s*[-–—]\s*(\d{1,2})\s*[./]\s*(\d{1,2})(?![.\d])"
)
DAY_LIST = re.compile(
    r"(?<![\d./])((?:\d{1,2}\s*(?:[,;]|\bи\b)\s*)+)"
    r"(\d{1,2})\s*[./]\s*(\d{1,2})(?![.\d])", re.IGNORECASE
)
ISO_DATE = re.compile(r"(?<!\d)(20\d{2})-(\d{1,2})-(\d{1,2})(?!\d)")
FULL_DATE = re.compile(
    r"(?<![\d./])(\d{1,2})([./-])(\d{1,2})\2(20\d{2}|\d{2})(?!\d)"
)
SHORT_DATE = re.compile(r"(?<![\d./])(\d{1,2})[./](\d{1,2})(?![.\d])")
WORD_RANGE = re.compile(
    rf"(?<!\d)(?:с\s+)?(\d{{1,2}})\s*(?:[-–—]|\bпо\b)\s*(\d{{1,2}})"
    rf"\s+({MONTH_WORDS})\b", re.IGNORECASE
)
WORD_DATES = re.compile(
    rf"(?<![\d./])((?:\d{{1,2}}\s*(?:[,;]|\bи\b)\s*)*\d{{1,2}})"
    rf"\s+({MONTH_WORDS})(?:\s+(20\d{{2}}))?\b", re.IGNORECASE
)


def valid_date(year: int, month: int, day: int) -> date | None:
    try:
        if not (2020 <= year <= 2100):
            return None
        return date(year, month, day)
    except ValueError:
        return None


def iso_date(value: object) -> date | None:
    text = str(value or "")
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def infer_date(day: int, month: int, year: str | None, received: date,
               primary: date | None) -> date | None:
    if year:
        numeric_year = int(year)
        numeric_year += 2000 if numeric_year < 100 else 0
    elif primary and primary.month == month:
        numeric_year = primary.year
    else:
        numeric_year = received.year + (1 if month < received.month else 0)
    return valid_date(numeric_year, month, day)


def add_range(target: set[str], start: date | None, end: date | None) -> None:
    if not start or not end:
        return
    days = (end - start).days
    # Avoid fabricating months of demand from malformed or vague date ranges.
    if not 0 <= days <= 31:
        return
    for i in range(days + 1):
        target.add((start + timedelta(days=i)).isoformat())


def parse_dates(text: object, received_at: str, primary: date | None = None) -> set[str]:
    raw = str(text or "")
    if not raw:
        return set()
    raw = raw[:1200].replace("\u00a0", " ")
    received = iso_date(received_at[:10]) or date(2026, 1, 1)
    found: set[str] = set()

    for m in DATE_RANGE.finditer(raw):
        start = infer_date(int(m[1]), int(m[2]), m[3], received, primary)
        end = infer_date(int(m[4]), int(m[5]), m[6], received, primary)
        if start and end and end < start and not m[6]:
            end = valid_date(start.year + 1, end.month, end.day)
        add_range(found, start, end)

    for m in DAY_RANGE.finditer(raw):
        low, high, month = map(int, m.groups())
        if 1 <= low <= high <= 31:
            start = infer_date(low, month, None, received, primary)
            end = infer_date(high, month, None, received, primary)
            add_range(found, start, end)

    for m in DAY_LIST.finditer(raw):
        month = int(m[3])
        days = [int(d) for d in re.findall(r"\d{1,2}", m[1])]
        days.append(int(m[2]))
        for day in days:
            parsed = infer_date(day, month, None, received, primary)
            if parsed:
                found.add(parsed.isoformat())

    for m in ISO_DATE.finditer(raw):
        parsed = valid_date(int(m[1]), int(m[2]), int(m[3]))
        if parsed:
            found.add(parsed.isoformat())

    for m in FULL_DATE.finditer(raw):
        parsed = infer_date(int(m[1]), int(m[3]), m[4], received, primary)
        if parsed:
            found.add(parsed.isoformat())

    for m in SHORT_DATE.finditer(raw):
        parsed = infer_date(int(m[1]), int(m[2]), None, received, primary)
        if parsed:
            found.add(parsed.isoformat())

    for m in WORD_RANGE.finditer(raw):
        month = MONTH_NAMES[m[3].lower()]
        low, high = int(m[1]), int(m[2])
        if 1 <= low <= high <= 31:
            add_range(
                found,
                infer_date(low, month, None, received, primary),
                infer_date(high, month, None, received, primary),
            )

    for m in WORD_DATES.finditer(raw):
        month = MONTH_NAMES[m[2].lower()]
        days = [int(d) for d in re.findall(r"\d{1,2}", m[1])]
        for day in days:
            parsed = infer_date(day, month, m[3], received, primary)
            if parsed:
                found.add(parsed.isoformat())

    return found


def event_texts(events_path: Path) -> dict[str, str]:
    messages: dict[str, str] = {}
    if not events_path.exists():
        return messages
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        kind = event.get("type")
        if kind not in {"max_message_created", "telegram_lead", "telegram_needs_review"}:
            continue
        message_id = str(event.get("message_id") or "")
        if not message_id:
            continue
        raw = str(event.get("text") or (event.get("lead") or {}).get("description") or "")
        if raw:
            messages[message_id] = raw
    return messages


def requested_dates(lead: dict, messages: dict[str, str]) -> set[str]:
    fields = lead.get("fields") or {}
    received = str(lead.get("received_at") or lead.get("first_seen_at") or "")
    primary = iso_date(fields.get("event_date")) or iso_date(lead.get("event_date"))
    dates = parse_dates(fields.get("event_date_raw"), received, primary)

    ids = {
        str(item)
        for item in (
            lead.get("message_id"),
            *((lead.get("max") or {}).get("message_ids") or []),
            *((lead.get("telegram") or {}).get("message_ids") or []),
        )
        if item is not None and str(item)
    }
    for mid in ids:
        if mid in messages:
            source = messages[mid].split("Дополнительная информация:", 1)[0]
            source = source.split("Страница:", 1)[0]
            dates.update(parse_dates(source, received, primary))

    description = str(fields.get("description") or "")
    if description:
        description = description.split("Дополнительная информация:", 1)[0]
        description = description.split("Страница:", 1)[0]
        dates.update(parse_dates(description, received, primary))

    if primary:
        dates.add(primary.isoformat())
    return dates


def build(leads_path: Path, events_path: Path, view_path: Path) -> dict:
    leads_payload = json.loads(leads_path.read_text(encoding="utf-8"))
    view = json.loads(view_path.read_text(encoding="utf-8"))
    messages = event_texts(events_path)
    counter: Counter[str] = Counter()
    identifiers: set[str] = set()
    unique = dated = multiple = 0

    for lead in leads_payload.get("leads") or []:
        if lead.get("is_duplicate") or lead.get("status") == "DUPLICATE":
            continue
        identity = str(lead.get("id") or "")
        if identity:
            if identity in identifiers:
                continue
            identifiers.add(identity)
        unique += 1
        dates = requested_dates(lead, messages)
        if dates:
            dated += 1
        if len(dates) > 1:
            multiple += 1
        counter.update(dates)

    heatmap = {
        "counts": dict(sorted(counter.items())),
        "unique_leads": unique,
        "dated_leads": dated,
        "undated_leads": unique - dated,
        "multiple_date_leads": multiple,
        "total_date_requests": sum(counter.values()),
    }
    view["event_date_heatmap"] = heatmap
    view_path.write_text(
        json.dumps(view, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return heatmap


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--leads", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--view", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.leads, args.events, args.view)
    print(
        "HEATMAP "
        + json.dumps(
            {key: result[key] for key in (
                "unique_leads", "dated_leads", "undated_leads",
                "multiple_date_leads", "total_date_requests"
            )},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
