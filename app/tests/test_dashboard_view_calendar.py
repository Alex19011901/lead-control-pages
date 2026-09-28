from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from scripts.build_dashboard_view import build


class DashboardViewCalendarTests(unittest.TestCase):
    def test_source_selector_exports_exact_last_30_moscow_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "dashboard_daily.json"
            output_path = root / "dashboard_view.json"
            input_path.write_text(
                json.dumps(
                    {
                        "snapshot_generated_at": "2026-09-28T10:00:00Z",
                        "generated_at": "2026-09-28T13:00:00+03:00",
                        "min_date": "2026-08-01",
                        "max_date": "2026-09-28",
                        "daily": {
                            "2026-09-28": {
                                "total": 3,
                                "status": {"OK": 3},
                                "source": {"Заявки хост": 2, "САЙТ ТИЛЬДА": 1},
                                "guest_ranges": {},
                                "event_types": {},
                                "channel": {"MAX": 2, "TELEGRAM": 1},
                            },
                            "2026-08-30": {
                                "total": 1,
                                "status": {"OK": 1},
                                "source": {"MARQUIZ": 1},
                                "guest_ranges": {},
                                "event_types": {},
                                "channel": {"TELEGRAM": 1},
                            },
                            "2026-08-29": {
                                "total": 9,
                                "status": {"OK": 9},
                                "source": {"Старый источник": 9},
                                "guest_ranges": {},
                                "event_types": {},
                                "channel": {"MAX": 9},
                            },
                        },
                        "leads": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch("scripts.build_dashboard_view.moscow_today", return_value=date(2026, 9, 28)):
                build(input_path, output_path)

            view = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(view["source_date_start"], "2026-08-30")
            self.assertEqual(view["source_date_end"], "2026-09-28")
            self.assertEqual(len(view["source_days"]), 30)
            self.assertEqual(
                view["source_days"]["2026-09-28"],
                {"Заявки хост": 2, "САЙТ ТИЛЬДА": 1},
            )
            self.assertEqual(view["source_days"]["2026-08-30"], {"MARQUIZ": 1})
            self.assertNotIn("2026-08-29", view["source_days"])

    def test_today_uses_moscow_calendar_even_when_latest_lead_is_yesterday(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "dashboard_daily.json"
            output_path = root / "dashboard_view.json"
            input_path.write_text(
                json.dumps(
                    {
                        "snapshot_generated_at": "2026-08-22T05:28:00Z",
                        "generated_at": "2026-08-21T22:54:48+03:00",
                        "min_date": "2026-08-21",
                        "max_date": "2026-08-21",
                        "daily": {
                            "2026-08-21": {
                                "total": 10,
                                "status": {"OK": 9, "ALARM_NO_CRM": 1},
                                "source": {"Заявки хост": 3},
                                "guest_ranges": {"50": 1},
                                "event_types": {"Свадьба": 1},
                                "channel": {"MAX": 6, "TELEGRAM": 4},
                            }
                        },
                        "leads": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch("scripts.build_dashboard_view.moscow_today", return_value=date(2026, 8, 22)):
                build(input_path, output_path)

            view = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(view["ranges"]["today"]["start"], "2026-08-22")
            self.assertEqual(view["ranges"]["today"]["end"], "2026-08-22")
            self.assertEqual(view["ranges"]["today"]["total"], 0)
            self.assertEqual(view["ranges"]["yesterday"]["start"], "2026-08-21")
            self.assertEqual(view["ranges"]["yesterday"]["total"], 10)


if __name__ == "__main__":
    unittest.main()
