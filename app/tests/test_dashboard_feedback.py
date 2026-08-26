from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from augment_dashboard_feedback import augment


MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def moscow_ts(year, month, day, hour=0, minute=0, second=0):
    return int(datetime(year, month, day, hour, minute, second, tzinfo=MOSCOW_TZ).timestamp())


class DashboardFeedbackTests(unittest.TestCase):
    def test_feedback_is_added_without_changing_existing_view_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            leads_path = root / "leads.json"
            view_path = root / "dashboard_view.json"
            leads_path.write_text(
                json.dumps(
                    {
                        "leads": [
                            {
                                "id": "a",
                                "source": "MARQUIZ",
                                "channel": "TELEGRAM",
                                "name": "Александр",
                                "identifier": {"type": "phone", "value": "79000000000"},
                                "fields": {"name": "Александр", "guests_count": 150, "event_type": "Корпоратив"},
                                "crm": {
                                    "found": True,
                                    "entity_type": "lead",
                                    "entity_id": 123,
                                    "responsible_user_name": "Олеся",
                                    "created_at": 100,
                                },
                                "crm_feedback": {
                                    "state": "NO_FEEDBACK",
                                    "crm_lead_id": 123,
                                    "lead_created_at": 100,
                                    "first_activity_at": None,
                                    "status_name": "Первичный контакт",
                                },
                            },
                            {
                                "id": "b",
                                "source": "САЙТ ТИЛЬДА",
                                "crm": {"found": True, "entity_type": "lead", "entity_id": 124},
                                "crm_feedback": {"state": "EXCLUDED", "crm_lead_id": 124},
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            original = {"ranges": {"today": {"total": 7}}, "latest": [{"name": "старый"}], "not_entered": []}
            view_path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")

            augment(leads_path, view_path, now_ts=1000)
            result = json.loads(view_path.read_text(encoding="utf-8"))

            self.assertEqual(result["ranges"], original["ranges"])
            self.assertEqual(result["latest"], original["latest"])
            self.assertEqual(result["not_entered"], original["not_entered"])
            self.assertEqual(result["feedback_summary"]["no_feedback"], 1)
            self.assertEqual(result["feedback_summary"]["total"], 1)
            self.assertEqual(len(result["feedback"]), 1)
            row = result["feedback"][0]
            self.assertEqual(row["name"], "Александр")
            self.assertEqual(row["feedback_state"], "NO_FEEDBACK")
            self.assertEqual(row["crm_status"], "Первичный контакт")
            self.assertEqual(row["manager"], "Олеся")
            self.assertEqual(row["crm_lead_id"], 123)

    def test_clear_rows_are_counted_but_not_rendered(self):
        created = moscow_ts(2026, 8, 22, 23, 50, 0)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            leads_path = root / "leads.json"
            view_path = root / "dashboard_view.json"
            leads_path.write_text(
                json.dumps(
                    {
                        "leads": [
                            {
                                "id": "clear",
                                "source": "Заявки хост",
                                "name": "Ольга Андреевна",
                                "identifier": {"type": "phone", "value": "79035146965"},
                                "crm": {
                                    "found": True,
                                    "entity_type": "lead",
                                    "entity_id": 47523505,
                                    "created_at": created,
                                },
                                "crm_feedback": {
                                    "state": "CLEAR",
                                    "crm_lead_id": 47523505,
                                    "lead_created_at": created,
                                    "first_activity_at": moscow_ts(2026, 8, 23, 10, 0, 0),
                                    "status_name": "Предбронь",
                                },
                            },
                            {
                                "id": "waiting",
                                "source": "Заявки хост",
                                "name": "Новый лид",
                                "identifier": {"type": "phone", "value": "79000000001"},
                                "crm": {
                                    "found": True,
                                    "entity_type": "lead",
                                    "entity_id": 47523506,
                                    "created_at": created,
                                },
                                "crm_feedback": {
                                    "state": "WAITING",
                                    "crm_lead_id": 47523506,
                                    "lead_created_at": created,
                                    "first_activity_at": None,
                                    "status_name": "Первичный контакт",
                                },
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            view_path.write_text(json.dumps({"ranges": {}, "latest": [], "not_entered": []}), encoding="utf-8")

            augment(leads_path, view_path, now_ts=moscow_ts(2026, 8, 25, 0, 0, 0))
            result = json.loads(view_path.read_text(encoding="utf-8"))

            self.assertEqual(result["feedback_summary"]["clear"], 1)
            self.assertEqual(result["feedback_summary"]["waiting"], 1)
            self.assertEqual(result["feedback_summary"]["waiting_blue"], 1)
            self.assertEqual(result["feedback_summary"]["total"], 1)
            self.assertEqual([row["name"] for row in result["feedback"]], ["Новый лид"])
            self.assertEqual(result["feedback"][0]["feedback_state"], "WAITING_BLUE")

    def test_waiting_visibility_uses_moscow_calendar_days_not_elapsed_hours(self):
        created = moscow_ts(2026, 8, 22, 23, 50, 0)
        lead = {
            "id": "waiting",
            "source": "Заявки хост",
            "name": "Тест",
            "identifier": {"type": "phone", "value": "79000000002"},
            "crm": {
                "found": True,
                "entity_type": "lead",
                "entity_id": 500,
                "created_at": created,
            },
            "crm_feedback": {
                "state": "WAITING",
                "crm_lead_id": 500,
                "lead_created_at": created,
                "first_activity_at": None,
                "status_name": "Первичный контакт",
            },
        }

        def build(now_ts: int) -> dict:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                leads_path = root / "leads.json"
                view_path = root / "dashboard_view.json"
                leads_path.write_text(json.dumps({"leads": [lead]}, ensure_ascii=False), encoding="utf-8")
                view_path.write_text(json.dumps({"ranges": {}, "latest": [], "not_entered": []}), encoding="utf-8")
                augment(leads_path, view_path, now_ts=now_ts)
                return json.loads(view_path.read_text(encoding="utf-8"))

        day_two = build(moscow_ts(2026, 8, 23, 23, 59, 59))
        self.assertEqual(day_two["feedback"], [])

        day_three = build(moscow_ts(2026, 8, 24, 0, 0, 0))
        self.assertEqual(day_three["feedback"][0]["feedback_state"], "WAITING_YELLOW")
        self.assertEqual(day_three["feedback_summary"]["waiting_yellow"], 1)

        day_four = build(moscow_ts(2026, 8, 25, 0, 0, 0))
        self.assertEqual(day_four["feedback"][0]["feedback_state"], "WAITING_BLUE")
        self.assertEqual(day_four["feedback_summary"]["waiting_blue"], 1)


if __name__ == "__main__":
    unittest.main()
