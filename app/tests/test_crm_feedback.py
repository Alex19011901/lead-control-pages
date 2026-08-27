from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.crm_feedback import (
    FEEDBACK_RULE_VERSION,
    _first_manager_comment_after_creation,
    apply_crm_feedback_tracking,
)


MOSCOW_TZ = ZoneInfo("Europe/Moscow")
MANAGER_ID = 12982830
OTHER_USER_ID = 999999


def moscow_ts(year, month, day, hour=0, minute=0, second=0):
    return int(datetime(year, month, day, hour, minute, second, tzinfo=MOSCOW_TZ).timestamp())


class FakeClient:
    def __init__(self, lead_card, note_pages=None, event_pages=None, status_name="Первичный контакт"):
        self.lead_card = dict(lead_card)
        self.note_pages = note_pages or []
        self.event_pages = event_pages or []
        self.status_name = status_name
        self.note_calls = 0
        self.event_calls = 0
        self.lead_reads = 0

    def _get_entity(self, entity_type, entity_id, params=None):
        if entity_type == "leads" and int(entity_id) == int(self.lead_card["id"]):
            self.lead_reads += 1
            return dict(self.lead_card)
        return None

    def _request_json(self, path, params):
        if path == "/api/v4/leads/notes":
            self.note_calls += 1
            self.assert_notes_query(params)
            page = int(params.get("page") or 1)
            notes = self.note_pages[page - 1] if page <= len(self.note_pages) else []
            links = {"next": {"href": "next"}} if page < len(self.note_pages) else {}
            return {"_embedded": {"notes": notes}, "_links": links}
        if path == "/api/v4/events":
            self.event_calls += 1
            page = int(params.get("page") or 1)
            events = self.event_pages[page - 1] if page <= len(self.event_pages) else []
            links = {"next": {"href": "next"}} if page < len(self.event_pages) else {}
            return {"_embedded": {"events": events}, "_links": links}
        if "/statuses/" in path:
            return {"name": self.status_name}
        raise AssertionError(path)

    @staticmethod
    def assert_notes_query(params):
        assert params.get("filter[note_type]") == "common"
        assert int(params.get("filter[entity_id][0]") or 0) > 0


def make_lead(created, responsible_user_id=MANAGER_ID):
    return {
        "id": "a",
        "crm": {
            "found": True,
            "entity_type": "lead",
            "entity_id": 111,
            "created_at": created,
            "responsible_user_id": responsible_user_id,
        },
    }


def make_card(created, status_id=2, responsible_user_id=MANAGER_ID):
    return {
        "id": 111,
        "created_at": created,
        "pipeline_id": 1,
        "status_id": status_id,
        "responsible_user_id": responsible_user_id,
    }


def common_note(ts, created_by, entity_id=111):
    return {
        "entity_id": entity_id,
        "created_at": ts,
        "created_by": created_by,
        "note_type": "common",
    }


def direct_message(ts, created_by, entity_id=111):
    return {
        "entity_id": entity_id,
        "created_at": ts,
        "created_by": created_by,
        "type": "entity_direct_message",
    }


class CRMFeedbackTests(unittest.TestCase):
    def test_only_later_comment_from_responsible_manager_counts(self):
        created = moscow_ts(2026, 8, 14, 14, 16, 26)
        same_day_manager = moscow_ts(2026, 8, 14, 18, 0, 0)
        later_other_user = moscow_ts(2026, 8, 15, 10, 0, 0)
        later_manager = moscow_ts(2026, 8, 17, 12, 30, 14)
        client = FakeClient(
            make_card(created),
            note_pages=[[
                common_note(same_day_manager, MANAGER_ID),
                common_note(later_other_user, OTHER_USER_ID),
                common_note(later_manager, MANAGER_ID),
            ]],
        )

        found = _first_manager_comment_after_creation(
            client,
            111,
            created,
            MANAGER_ID,
        )

        self.assertEqual(found, later_manager)
        self.assertEqual(client.note_calls, 1)

    def test_responsible_manager_direct_message_clears_feedback(self):
        created = moscow_ts(2026, 8, 14, 14, 16, 26)
        manager_comment = moscow_ts(2026, 8, 17, 12, 30, 14)
        client = FakeClient(
            make_card(created),
            note_pages=[[]],
            event_pages=[[direct_message(manager_comment, MANAGER_ID)]],
        )
        lead = make_lead(created)

        apply_crm_feedback_tracking(
            [lead],
            client,
            now_ts=moscow_ts(2026, 8, 20, 12, 0, 0),
        )

        self.assertEqual(lead["crm_feedback"]["state"], "CLEAR")
        self.assertEqual(lead["crm_feedback"]["first_activity_at"], manager_comment)
        self.assertGreater(client.event_calls, 0)

    def test_other_users_direct_message_does_not_clear_feedback(self):
        created = moscow_ts(2026, 8, 14, 14, 16, 26)
        other_comment = moscow_ts(2026, 8, 17, 12, 30, 14)
        client = FakeClient(
            make_card(created),
            note_pages=[[]],
            event_pages=[[direct_message(other_comment, OTHER_USER_ID)]],
        )
        lead = make_lead(created)

        apply_crm_feedback_tracking(
            [lead],
            client,
            now_ts=moscow_ts(2026, 8, 20, 12, 0, 0),
        )

        self.assertEqual(lead["crm_feedback"]["state"], "NO_FEEDBACK")
        self.assertIsNone(lead["crm_feedback"]["first_activity_at"])

    def test_comment_from_other_user_does_not_clear_feedback(self):
        created = moscow_ts(2026, 8, 14, 14, 16, 26)
        other_comment = moscow_ts(2026, 8, 17, 12, 30, 14)
        client = FakeClient(
            make_card(created),
            note_pages=[[common_note(other_comment, OTHER_USER_ID)]],
        )
        lead = make_lead(created)

        apply_crm_feedback_tracking(
            [lead],
            client,
            now_ts=moscow_ts(2026, 8, 20, 12, 0, 0),
        )

        self.assertEqual(lead["crm_feedback"]["state"], "NO_FEEDBACK")
        self.assertIsNone(lead["crm_feedback"]["first_activity_at"])

    def test_responsible_manager_comment_clears_feedback(self):
        created = moscow_ts(2026, 8, 14, 14, 16, 26)
        manager_comment = moscow_ts(2026, 8, 17, 12, 30, 14)
        client = FakeClient(
            make_card(created),
            note_pages=[[common_note(manager_comment, MANAGER_ID)]],
        )
        lead = make_lead(created)

        apply_crm_feedback_tracking(
            [lead],
            client,
            now_ts=moscow_ts(2026, 8, 20, 12, 0, 0),
        )

        self.assertEqual(lead["crm_feedback"]["state"], "CLEAR")
        self.assertEqual(lead["crm_feedback"]["first_activity_at"], manager_comment)

    def test_no_feedback_starts_on_fifth_moscow_calendar_day(self):
        created = moscow_ts(2026, 8, 22, 23, 50, 0)
        client = FakeClient(make_card(created), note_pages=[[]])
        lead = make_lead(created)

        apply_crm_feedback_tracking(
            [lead],
            client,
            now_ts=moscow_ts(2026, 8, 25, 23, 59, 59),
        )
        self.assertEqual(lead["crm_feedback"]["state"], "WAITING")
        self.assertEqual(
            lead["crm_feedback"]["deadline_at"],
            moscow_ts(2026, 8, 26, 0, 0, 0),
        )

        apply_crm_feedback_tracking(
            [lead],
            client,
            now_ts=moscow_ts(2026, 8, 26, 0, 0, 0),
        )
        self.assertEqual(lead["crm_feedback"]["state"], "NO_FEEDBACK")

    def test_all_four_excluded_statuses_are_excluded(self):
        created = moscow_ts(2026, 8, 14, 14, 16, 26)
        cases = [
            (143, "Закрыто и не реализовано"),
            (142, "Успешно реализовано"),
            (10, "Согласование договора"),
            (11, "Внесена п/о идет текущая работа"),
        ]
        for status_id, status_name in cases:
            with self.subTest(status_name=status_name):
                client = FakeClient(
                    make_card(created, status_id=status_id),
                    status_name=status_name,
                )
                lead = make_lead(created)

                apply_crm_feedback_tracking(
                    [lead],
                    client,
                    now_ts=moscow_ts(2026, 8, 24, 12, 0, 0),
                )

                self.assertEqual(lead["crm_feedback"]["state"], "EXCLUDED")
                self.assertTrue(lead["crm_feedback"]["excluded"])
                self.assertEqual(client.note_calls, 0)

    def test_fast_refresh_rechecks_current_status_before_reusing_clear(self):
        created = moscow_ts(2026, 8, 14, 14, 16, 26)
        old_comment = moscow_ts(2026, 8, 17, 12, 30, 14)
        client = FakeClient(
            make_card(created, status_id=10),
            status_name="Согласование договора",
        )
        lead = make_lead(created)
        previous = [{
            "id": "a",
            "crm": {
                "entity_id": 111,
                "responsible_user_id": MANAGER_ID,
            },
            "crm_feedback": {
                "state": "CLEAR",
                "first_activity_at": old_comment,
                "responsible_user_id": MANAGER_ID,
                "rule_version": FEEDBACK_RULE_VERSION,
            },
        }]

        apply_crm_feedback_tracking(
            [lead],
            client,
            previous_leads=previous,
            now_ts=moscow_ts(2026, 8, 24, 12, 0, 0),
            reuse_stable=True,
        )

        self.assertGreater(client.lead_reads, 0)
        self.assertEqual(lead["crm_feedback"]["state"], "EXCLUDED")
        self.assertEqual(client.note_calls, 0)

    def test_cached_comment_is_not_reused_after_manager_change(self):
        created = moscow_ts(2026, 8, 14, 14, 16, 26)
        old_comment = moscow_ts(2026, 8, 17, 12, 30, 14)
        new_manager = 777777
        client = FakeClient(
            make_card(created, responsible_user_id=new_manager),
            note_pages=[[]],
        )
        lead = make_lead(created, responsible_user_id=MANAGER_ID)
        previous = [{
            "id": "a",
            "crm": {
                "entity_id": 111,
                "responsible_user_id": MANAGER_ID,
            },
            "crm_feedback": {
                "state": "CLEAR",
                "first_activity_at": old_comment,
                "responsible_user_id": MANAGER_ID,
                "rule_version": FEEDBACK_RULE_VERSION,
            },
        }]

        apply_crm_feedback_tracking(
            [lead],
            client,
            previous_leads=previous,
            now_ts=moscow_ts(2026, 8, 24, 12, 0, 0),
            reuse_stable=True,
        )

        self.assertEqual(lead["crm_feedback"]["responsible_user_id"], new_manager)
        self.assertEqual(lead["crm_feedback"]["state"], "NO_FEEDBACK")
        self.assertGreater(client.note_calls, 0)


if __name__ == "__main__":
    unittest.main()
