from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.crm_feedback import (
    _first_event_after_creation,
    apply_crm_feedback_tracking,
)


MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def moscow_ts(year, month, day, hour=0, minute=0, second=0):
    return int(datetime(year, month, day, hour, minute, second, tzinfo=MOSCOW_TZ).timestamp())


class FakeClient:
    def __init__(self, lead_card, event_pages=None, status_name="Первичный контакт"):
        self.lead_card = lead_card
        self.event_pages = event_pages or []
        self.status_name = status_name
        self.event_calls = 0

    def _get_entity(self, entity_type, entity_id, params=None):
        if entity_type == "leads" and int(entity_id) == int(self.lead_card["id"]):
            return dict(self.lead_card)
        return None

    def _request_json(self, path, params):
        if path == "/api/v4/events":
            self.event_calls += 1
            page = int(params.get("page") or 1)
            events = self.event_pages[page - 1] if page <= len(self.event_pages) else []
            links = {"next": {"href": "next"}} if page < len(self.event_pages) else {}
            return {"_embedded": {"events": events}, "_links": links}
        if "/statuses/" in path:
            return {"name": self.status_name}
        raise AssertionError(path)


class CRMFeedbackTests(unittest.TestCase):
    def test_first_event_ignores_all_creation_day_rows_and_uses_next_date(self):
        created = moscow_ts(2026, 8, 14, 14, 16, 26)
        same_day_31s = moscow_ts(2026, 8, 14, 14, 16, 57)
        same_day_later = moscow_ts(2026, 8, 14, 22, 0, 0)
        next_date = moscow_ts(2026, 8, 17, 12, 30, 0)
        client = FakeClient(
            {"id": 111, "created_at": created, "pipeline_id": 1, "status_id": 2},
            event_pages=[[
                {"entity_id": 111, "created_at": created, "type": "lead_added"},
                {"entity_id": 111, "created_at": same_day_31s, "type": "custom_field_value_changed"},
                {"entity_id": 111, "created_at": same_day_later, "type": "note_added"},
                {"entity_id": 111, "created_at": next_date, "type": "lead_status_changed"},
            ]],
        )
        self.assertEqual(_first_event_after_creation(client, 111, created), next_date)

    def test_no_feedback_starts_at_beginning_of_fifth_moscow_calendar_day(self):
        created = moscow_ts(2026, 8, 22, 23, 50, 0)
        client = FakeClient(
            {"id": 111, "created_at": created, "pipeline_id": 1, "status_id": 2},
            event_pages=[[]],
        )
        lead = {
            "id": "a",
            "crm": {"found": True, "entity_type": "lead", "entity_id": 111, "created_at": created},
        }

        apply_crm_feedback_tracking(
            [lead],
            client,
            now_ts=moscow_ts(2026, 8, 25, 23, 59, 59),
        )
        self.assertEqual(lead["crm_feedback"]["state"], "WAITING")
        self.assertEqual(lead["crm_feedback"]["deadline_at"], moscow_ts(2026, 8, 26, 0, 0, 0))

        apply_crm_feedback_tracking(
            [lead],
            client,
            now_ts=moscow_ts(2026, 8, 26, 0, 0, 0),
        )
        self.assertEqual(lead["crm_feedback"]["state"], "NO_FEEDBACK")
        self.assertIsNone(lead["crm_feedback"]["first_activity_at"])

    def test_later_calendar_date_clears_status_even_if_it_appears_after_day_five(self):
        created = moscow_ts(2026, 8, 14, 14, 16, 26)
        later = moscow_ts(2026, 8, 20, 12, 0, 0)
        client = FakeClient(
            {"id": 111, "created_at": created, "pipeline_id": 1, "status_id": 2},
            event_pages=[[{"entity_id": 111, "created_at": later, "type": "lead_status_changed"}]],
        )
        lead = {
            "id": "a",
            "crm": {"found": True, "entity_type": "lead", "entity_id": 111, "created_at": created},
        }
        apply_crm_feedback_tracking([lead], client, now_ts=later + 100)
        self.assertEqual(lead["crm_feedback"]["state"], "CLEAR")
        self.assertEqual(lead["crm_feedback"]["first_activity_at"], later)

    def test_closed_not_realized_is_excluded_without_history_lookup(self):
        created = moscow_ts(2026, 8, 14, 14, 16, 26)
        client = FakeClient(
            {"id": 111, "created_at": created, "pipeline_id": 1, "status_id": 143},
        )
        lead = {
            "id": "a",
            "crm": {"found": True, "entity_type": "lead", "entity_id": 111, "created_at": created},
        }
        apply_crm_feedback_tracking([lead], client, now_ts=moscow_ts(2026, 8, 24, 12, 0, 0))
        self.assertEqual(lead["crm_feedback"]["state"], "EXCLUDED")
        self.assertTrue(lead["crm_feedback"]["excluded"])
        self.assertEqual(client.event_calls, 0)

    def test_existing_later_date_activity_is_reused_and_not_requeried(self):
        created = moscow_ts(2026, 8, 14, 14, 16, 26)
        first_activity = moscow_ts(2026, 8, 17, 12, 30, 0)
        client = FakeClient(
            {"id": 111, "created_at": created, "pipeline_id": 1, "status_id": 2},
        )
        lead = {
            "id": "a",
            "crm": {"found": True, "entity_type": "lead", "entity_id": 111, "created_at": created},
        }
        previous = [{
            "id": "a",
            "crm": {"entity_id": 111},
            "crm_feedback": {"first_activity_at": first_activity},
        }]
        apply_crm_feedback_tracking([lead], client, previous_leads=previous, now_ts=moscow_ts(2026, 8, 24, 12, 0, 0))
        self.assertEqual(lead["crm_feedback"]["state"], "CLEAR")
        self.assertEqual(lead["crm_feedback"]["first_activity_at"], first_activity)
        self.assertEqual(client.event_calls, 0)

    def test_old_same_day_cached_activity_is_invalidated_and_rechecked(self):
        created = moscow_ts(2026, 8, 14, 14, 16, 26)
        old_same_day = moscow_ts(2026, 8, 14, 14, 16, 57)
        next_date = moscow_ts(2026, 8, 17, 12, 30, 0)
        client = FakeClient(
            {"id": 111, "created_at": created, "pipeline_id": 1, "status_id": 2},
            event_pages=[[{"entity_id": 111, "created_at": next_date, "type": "lead_status_changed"}]],
        )
        lead = {
            "id": "a",
            "crm": {"found": True, "entity_type": "lead", "entity_id": 111, "created_at": created},
        }
        previous = [{
            "id": "a",
            "crm": {"entity_id": 111},
            "crm_feedback": {"first_activity_at": old_same_day},
        }]
        apply_crm_feedback_tracking([lead], client, previous_leads=previous, now_ts=moscow_ts(2026, 8, 24, 12, 0, 0))
        self.assertEqual(lead["crm_feedback"]["state"], "CLEAR")
        self.assertEqual(lead["crm_feedback"]["first_activity_at"], next_date)
        self.assertGreater(client.event_calls, 0)


if __name__ == "__main__":
    unittest.main()
