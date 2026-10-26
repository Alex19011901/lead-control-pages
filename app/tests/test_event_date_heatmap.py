from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_event_date_heatmap import build, parse_dates


class EventDateHeatmapTests(unittest.TestCase):
    def test_several_dates_and_same_day_repeated(self):
        self.assertEqual(
            parse_dates("ЗАЯВКА 18,25,18.12. 150п.", "2026-10-06T12:00:00+03:00"),
            {"2026-12-18", "2026-12-25"},
        )
        self.assertEqual(
            parse_dates("11,17,18,24,25.12", "2026-10-19T12:00:00+03:00"),
            {"2026-12-11", "2026-12-17", "2026-12-18", "2026-12-24", "2026-12-25"},
        )
        self.assertEqual(
            parse_dates("9.10,16,17.12", "2026-08-19T12:00:00+03:00"),
            {"2026-10-09", "2026-12-16", "2026-12-17"},
        )

    def test_ranges_include_all_explicit_days_across_new_year(self):
        self.assertEqual(len(parse_dates("1-10.12", "2026-09-18")), 10)
        self.assertEqual(
            parse_dates("28.12-01.01", "2026-10-22"),
            {"2026-12-28", "2026-12-29", "2026-12-30",
             "2026-12-31", "2027-01-01"},
        )
        self.assertEqual(
            parse_dates("5-6.08", "2026-07-08"),
            {"2026-08-05", "2026-08-06"},
        )

    def test_vague_text_and_phone_numbers_are_not_dates(self):
        for description in (
            "лето 2027", "сентябрь", "дата открыта",
            "конец августа начало сентября",
            "ЗАЯВКА. 80-100п., телефон 89161234567",
        ):
            self.assertEqual(parse_dates(description, "2026-10-20"), set())

    def test_full_dates_and_textual_dates(self):
        self.assertEqual(
            parse_dates("Дата: 25-12-2026", "2026-08-20"),
            {"2026-12-25"},
        )
        self.assertEqual(
            parse_dates("18 и 25 декабря", "2026-10-20"),
            {"2026-12-18", "2026-12-25"},
        )
        self.assertEqual(
            parse_dates("31.02.2027", "2026-10-20"),
            set(),
        )

    def test_count_all_dates_once_and_exclude_duplicate_without_touching_other_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            leads_path, events_path, view_path = [
                path / name for name in ("leads.json", "events.ndjson", "dashboard_view.json")
            ]
            leads = [
                {"id": "a", "status": "OK", "message_id": "mid1",
                 "received_at": "2026-10-20T12:00:00+03:00",
                 "fields": {"event_date": "2026-12-25", "event_date_raw": "25.12"}},
                {"id": "b", "status": "ALARM_NO_CRM",
                 "received_at": "2026-10-20T12:00:00+03:00",
                 "fields": {"event_date": "2026-12-18", "event_date_raw": "18.12"}},
                {"id": "duplicate", "status": "DUPLICATE", "is_duplicate": True,
                 "message_id": "mid3",
                 "received_at": "2026-10-20T12:00:00+03:00",
                 "fields": {"event_date": "2026-12-18"}},
                {"id": "undated", "status": "-",
                 "received_at": "2026-10-20T12:00:00+03:00",
                 "fields": {"event_date_raw": "сентябрь"}},
            ]
            leads_path.write_text(
                json.dumps({"leads": leads}, ensure_ascii=False), encoding="utf-8"
            )
            events_path.write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in [
                    {"type": "max_message_created", "message_id": "mid1",
                     "text": "ЗАЯВКА. 18,25,18.12. 150п."},
                    {"type": "max_message_created", "message_id": "mid3",
                     "text": "ЗАЯВКА. 18.12. 150п."},
                ]), encoding="utf-8"
            )
            view_path.write_text(json.dumps({"ranges": {"all": {"total": 3}}}), encoding="utf-8")
            result = build(leads_path, events_path, view_path)
            self.assertEqual(result["counts"], {"2026-12-18": 2, "2026-12-25": 1})
            self.assertEqual(result["unique_leads"], 3)
            self.assertEqual(result["dated_leads"], 2)
            self.assertEqual(result["multiple_date_leads"], 1)
            self.assertEqual(result["undated_leads"], 1)
            self.assertEqual(json.loads(view_path.read_text())["ranges"]["all"]["total"], 3)


if __name__ == "__main__":
    unittest.main()
