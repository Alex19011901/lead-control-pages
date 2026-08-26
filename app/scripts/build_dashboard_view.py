from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def moscow_today() -> date:
    return datetime.now(MOSCOW_TZ).date()


def norm_event(value: object) -> str:
    text = str(value or "").strip()
    key = text.casefold().replace("ё", "е")
    if not key or key == "unknown":
        return ""
    mapping = {
        "свадьба": "Свадьба",
        "корпоратив": "Корпоратив",
        "нг корпоратив": "Корпоратив",
        "др": "Юбилей",
        "день рождения": "Юбилей",
        "birthday": "Юбилей",
        "юбилей": "Юбилей",
        "-летие": "Юбилей",
        "летие": "Юбилей",
        "бизнес-завтрак": "Бизнес-завтрак",
        "бизнес завтрак": "Бизнес-завтрак",
        "гала-ужин": "Гала-ужин",
        "гала ужин": "Гала-ужин",
        "клиентский вечер": "Клиентский вечер",
        "тимбилдинг": "Тимбилдинг",
        "конференция": "Конференция",
        "семинар": "Семинар",
        "презентация": "Презентация",
        "выпускной": "Выпускной",
        "съемки": "Съёмки",
        "съёмки": "Съёмки",
        "съемка": "Съёмки",
        "съёмка": "Съёмки",
        "поминки": "Поминки",
        "банкет": "Банкет",
        "фуршет": "Фуршет",
        "вечеринка": "Вечеринка",
        "семейный ужин": "Семейный ужин",
        "детский праздник": "Детский праздник",
        "новый год": "Новый год",
    }
    if key in mapping:
        return mapping[key]
    if re.search(r"(?:\b\d{1,3}\s*[-–—]?\s*)?лети(?:е|я|ю)\b", key):
        return "Юбилей"
    return text


def guest_bucket_label(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.casefold() == "unknown":
        return "Не указано"
    match = re.search(r"\d{1,4}", text)
    if not match:
        return "Не указано"
    guests = int(match.group(0))
    if guests <= 20:
        return "1-20"
    if guests <= 50:
        return "21-50"
    if guests <= 100:
        return "51-100"
    if guests <= 150:
        return "101-150"
    return "151+"


def merge_range(daily: dict[str, dict], start: date, end: date) -> dict:
    status: Counter[str] = Counter()
    source: Counter[str] = Counter()
    channel: Counter[str] = Counter()
    guest: Counter[str] = Counter()
    event: Counter[str] = Counter()
    days: list[list[object]] = []
    total = 0

    cur = start
    while cur <= end:
        key = cur.isoformat()
        item = daily.get(key) or {}
        n = int(item.get("total") or 0)
        if n:
            days.append([key, n])
        total += n
        status.update(item.get("status") or {})
        source.update(item.get("source") or {})
        channel.update(item.get("channel") or {})
        for k, v in (item.get("guest_ranges") or {}).items():
            guest[guest_bucket_label(k)] += int(v)

        defined_event_count = 0
        for k, v in (item.get("event_types") or {}).items():
            count = int(v)
            nk = norm_event(k)
            if nk:
                event[nk] += count
                defined_event_count += count
        undefined_event_count = max(0, n - defined_event_count)
        if undefined_event_count:
            event["Не определено"] += undefined_event_count

        cur += timedelta(days=1)

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "total": total,
        "status": dict(status),
        "source": dict(source),
        "channel": dict(channel),
        "guest": dict(guest),
        "event": dict(event),
        "days": days,
    }


def compact_lead(lead: dict) -> dict:
    return {
        "date": lead.get("date") or "",
        "ts": lead.get("ts") or "",
        "source": lead.get("source") or "unknown",
        "status": lead.get("status") or "UNKNOWN",
        "channel": lead.get("channel") or "unknown",
        "guest_range": lead.get("guest_range") or "unknown",
        "guests": lead.get("guests") or "",
        "event_type": norm_event(lead.get("event_type")) or "unknown",
        "name": lead.get("name") or "",
        "identifier": lead.get("identifier") or "",
        "manager": lead.get("manager") or "",
    }


def build(input_path: Path, output_path: Path) -> None:
    snap = json.loads(input_path.read_text(encoding="utf-8"))
    daily = snap.get("daily") or {}
    if not daily:
        out = {"ranges": {}, "latest": [], "not_entered": [], "snapshot_at": ""}
        output_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    min_day = date.fromisoformat(str(snap["min_date"]))
    max_day = date.fromisoformat(str(snap["max_date"]))
    today = moscow_today()
    yesterday = today - timedelta(days=1)
    ranges = {
        "today": merge_range(daily, today, today),
        "yesterday": merge_range(daily, yesterday, yesterday),
        "7": merge_range(daily, max(min_day, today - timedelta(days=6)), today),
        "30": merge_range(daily, max(min_day, today - timedelta(days=29)), today),
        "all": merge_range(daily, min_day, max_day),
    }

    all_leads = snap.get("leads") or []
    latest = [compact_lead(lead) for lead in all_leads[:60]]
    not_entered = [compact_lead(lead) for lead in all_leads if (lead.get("status") or "") == "ALARM_NO_CRM"]

    out = {
        "ranges": ranges,
        "latest": latest,
        "not_entered": not_entered,
        "snapshot_generated_at": snap.get("snapshot_generated_at") or "",
        "snapshot_at": snap.get("generated_at") or "",
        "min_date": snap.get("min_date"),
        "max_date": snap.get("max_date"),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    build(Path(args.input), Path(args.output))


if __name__ == "__main__":
    main()
