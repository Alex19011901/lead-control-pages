from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lead_control.source_categories import normalize_lead_sources
from scripts.build_dashboard_snapshot import build
from scripts.build_dashboard_view import build as build_view


class DashboardSnapshotTests(unittest.TestCase):
    def test_build_writes_daily_and_view_payloads_with_refresh_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "leads.json"
            daily_path = root / "dashboard_daily.json"
            view_path = root / "dashboard_view.json"
            input_path.write_text(
                json.dumps(
                    {
                        "leads": [
                            {
                                "received_at": "2026-08-20T12:59:15+03:00",
                                "source": "Заявки хост",
                                "status": "OK",
                                "channel": "MAX",
                                "guests": 14,
                                "name": "Наталья",
                                "identifier": {"type": "phone", "value": "79606254413"},
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            build(input_path, daily_path, view_path)

            daily = json.loads(daily_path.read_text(encoding="utf-8"))
            view = json.loads(view_path.read_text(encoding="utf-8"))
            self.assertEqual(daily, view)
            self.assertIn("snapshot_generated_at", daily)
            self.assertTrue(daily["snapshot_generated_at"].endswith("Z"))
            self.assertEqual(daily["generated_at"], "2026-08-20T12:59:15+03:00")
            self.assertEqual(daily["daily"]["2026-08-20"]["source"]["Заявки хост"], 1)
            self.assertEqual(daily["latest"][0]["identifier"], "79606254413")
            self.assertEqual(daily["latest"][0]["guests"], "14")

    def test_dashboard_rows_use_exact_guest_value_from_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "leads.json"
            daily_path = root / "dashboard_daily.json"
            view_path = root / "dashboard_view.json"
            input_path.write_text(
                json.dumps(
                    {
                        "leads": [
                            {
                                "received_at": "2026-08-21T10:00:00+03:00",
                                "source": "Заявки хост",
                                "status": "OK",
                                "channel": "MAX",
                                "fields": {"description": "ЗАЯВКА\n12.09\n15п.\nАнна\n89990001122", "guests_count": 15},
                            },
                            {
                                "received_at": "2026-08-21T09:00:00+03:00",
                                "source": "Заявки хост",
                                "status": "ALARM_NO_CRM",
                                "channel": "MAX",
                                "fields": {"description": "ЗАЯВКА 13.09 40-50п. Ирина 89990002233", "guests_min": 40, "guests_max": 50},
                            },
                            {
                                "received_at": "2026-08-21T08:00:00+03:00",
                                "source": "САЙТ ТИЛЬДА",
                                "status": "OK",
                                "channel": "TELEGRAM",
                                "fields": {"description": "Input: 100", "guests_count": 100},
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            build(input_path, daily_path)
            build_view(daily_path, view_path)

            view = json.loads(view_path.read_text(encoding="utf-8"))
            self.assertEqual([row["guests"] for row in view["latest"]], ["15", "40-50", "100"])
            self.assertEqual(view["not_entered"][0]["guests"], "40-50")

    def test_dashboard_view_preserves_refresh_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "dashboard_daily.json"
            view_path = root / "dashboard_view.json"
            input_path.write_text(
                json.dumps(
                    {
                        "snapshot_generated_at": "2026-08-20T10:00:00Z",
                        "generated_at": "2026-08-20T12:59:15+03:00",
                        "min_date": "2026-08-20",
                        "max_date": "2026-08-20",
                        "daily": {
                            "2026-08-20": {
                                "total": 1,
                                "status": {"OK": 1},
                                "source": {"Заявки хост": 1},
                                "guest_ranges": {"1-20": 1},
                                "event_types": {"unknown": 1},
                                "channel": {"MAX": 1},
                            }
                        },
                        "leads": [
                            {
                                "date": "2026-08-20",
                                "ts": "2026-08-20T12:59:15+03:00",
                                "source": "Заявки хост",
                                "status": "OK",
                                "channel": "MAX",
                                "guest_range": "1-20",
                                "guests": "14",
                                "event_type": "unknown",
                                "name": "Наталья",
                                "identifier": "79606254413",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            build_view(input_path, view_path)

            view = json.loads(view_path.read_text(encoding="utf-8"))
            self.assertEqual(view["snapshot_generated_at"], "2026-08-20T10:00:00Z")
            self.assertEqual(view["snapshot_at"], "2026-08-20T12:59:15+03:00")
            self.assertEqual(view["ranges"]["all"]["source"]["Заявки хост"], 1)
            self.assertEqual(view["latest"][0]["guests"], "14")

    def test_dashboard_view_exposes_all_not_entered_leads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "dashboard_daily.json"
            view_path = root / "dashboard_view.json"
            input_path.write_text(
                json.dumps(
                    {
                        "snapshot_generated_at": "2026-08-21T18:00:00Z",
                        "generated_at": "2026-08-21T20:30:00+03:00",
                        "min_date": "2026-08-20",
                        "max_date": "2026-08-21",
                        "daily": {
                            "2026-08-20": {
                                "total": 1,
                                "status": {"ALARM_NO_CRM": 1},
                                "source": {"Заявки хост": 1},
                                "guest_ranges": {"21-50": 1},
                                "event_types": {"unknown": 1},
                                "channel": {"MAX": 1},
                            },
                            "2026-08-21": {
                                "total": 1,
                                "status": {"OK": 1},
                                "source": {"САЙТ ТИЛЬДА": 1},
                                "guest_ranges": {"1-20": 1},
                                "event_types": {"unknown": 1},
                                "channel": {"TELEGRAM": 1},
                            },
                        },
                        "leads": [
                            {
                                "date": "2026-08-21",
                                "ts": "2026-08-21T20:30:00+03:00",
                                "source": "САЙТ ТИЛЬДА",
                                "status": "OK",
                                "channel": "TELEGRAM",
                                "guest_range": "1-20",
                                "guests": "15",
                                "event_type": "unknown",
                                "name": "Анна",
                                "identifier": "79990001122",
                            },
                            {
                                "date": "2026-08-20",
                                "ts": "2026-08-20T10:00:00+03:00",
                                "source": "Заявки хост",
                                "status": "ALARM_NO_CRM",
                                "channel": "MAX",
                                "guest_range": "21-50",
                                "guests": "35",
                                "event_type": "unknown",
                                "name": "Ирина",
                                "identifier": "79850000000",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            build_view(input_path, view_path)

            view = json.loads(view_path.read_text(encoding="utf-8"))
            self.assertEqual(len(view["not_entered"]), 1)
            self.assertEqual(view["not_entered"][0]["name"], "Ирина")
            self.assertEqual(view["not_entered"][0]["status"], "ALARM_NO_CRM")
            self.assertEqual(view["not_entered"][0]["identifier"], "79850000000")
            self.assertEqual(view["not_entered"][0]["guests"], "35")

    def test_tatiana_leads_are_removed_before_dashboard_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "leads.json"
            daily_path = root / "dashboard_daily.json"
            view_path = root / "dashboard_view.json"

            leads = [
                {
                    "received_at": "2026-08-20T12:59:15+03:00",
                    "source": "ОТ ТАТЬЯНЫ ТГ",
                    "category": "ОТ ТАТЬЯНЫ ТГ",
                    "channel": "TELEGRAM",
                    "status": "OK",
                    "sender_name": "Tatiana Ts",
                    "sender_username": "Tati_Ts_A",
                    "fields": {
                        "source": "ОТ ТАТЬЯНЫ ТГ",
                        "category": "ОТ ТАТЬЯНЫ ТГ",
                    },
                    "identifier": {"type": "telegram_message", "value": "5653"},
                },
                {
                    "received_at": "2026-08-20T13:00:00+03:00",
                    "source": "Заявка с ТГ",
                    "category": "TG_LEAD",
                    "channel": "TELEGRAM",
                    "status": "OK",
                    "sender_name": "Someone",
                    "sender_username": "someone",
                    "fields": {"source": "Заявка с ТГ", "category": "TG_LEAD"},
                    "identifier": {"type": "phone", "value": "79990001122"},
                },
            ]

            normalize_lead_sources(leads)
            input_path.write_text(
                json.dumps({"leads": leads}, ensure_ascii=False),
                encoding="utf-8",
            )

            build(input_path, daily_path)
            build_view(daily_path, view_path)

            view = json.loads(view_path.read_text(encoding="utf-8"))
            self.assertNotIn("ОТ ТАТЬЯНЫ ТГ", view["ranges"]["all"]["source"])
            self.assertEqual(view["ranges"]["all"]["source"]["Заявка с ТГ"], 1)
            self.assertEqual(view["ranges"]["all"]["total"], 1)
            self.assertTrue(all(row.get("source") != "ОТ ТАТЬЯНЫ ТГ" for row in view["latest"]))


if __name__ == "__main__":
    unittest.main()
