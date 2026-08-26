from __future__ import annotations

import unittest

from lead_control.crm_apply import apply_crm
from lead_control.crm_feedback import apply_crm_feedback_tracking


class _SearchResult:
    found = False
    entity_type = None
    entity_id = None

    def as_dict(self):
        return {"found": False}


class _RecordingClient:
    def __init__(self) -> None:
        self.search_calls = 0
        self.entity_calls = 0

    def search(self, **kwargs):
        self.search_calls += 1
        return _SearchResult()

    def _get_entity(self, *args, **kwargs):
        self.entity_calls += 1
        raise AssertionError("stable fast-refresh data should not reload CRM entity")


class FastRefreshTests(unittest.TestCase):
    def _lead(self):
        return {
            "id": "lead-fast-1",
            "identifier": {"type": "phone", "value": "79990000000"},
            "crm_required": True,
            "channel": "MAX",
            "manager_reaction": None,
            "deadline_msk_ts": 200,
            "first_seen_ts": 100,
            "crm": {"found": False},
            "status": "PENDING",
            "violations": [],
        }

    def test_fast_refresh_reuses_confirmed_crm_match(self) -> None:
        lead = self._lead()
        previous = self._lead()
        previous["crm"] = {
            "found": True,
            "entity_type": "lead",
            "entity_id": 123,
            "created_at": 100,
            "responsible_user_id": 7,
        }
        client = _RecordingClient()

        apply_crm([lead], client, previous_leads=[previous], reuse_confirmed=True)

        self.assertEqual(client.search_calls, 0)
        self.assertTrue(lead["crm"]["found"])
        self.assertEqual(lead["crm"]["entity_id"], 123)
        self.assertEqual(lead["status"], "OK")

    def test_fast_refresh_still_rechecks_unresolved_crm_lead(self) -> None:
        lead = self._lead()
        previous = self._lead()
        client = _RecordingClient()

        apply_crm([lead], client, previous_leads=[previous], reuse_confirmed=True)

        self.assertEqual(client.search_calls, 1)
        self.assertFalse(lead["crm"]["found"])

    def test_fast_refresh_reuses_only_stable_feedback(self) -> None:
        lead = self._lead()
        lead["crm"] = {
            "found": True,
            "entity_type": "lead",
            "entity_id": 123,
            "created_at": 100,
        }
        previous = self._lead()
        previous["crm"] = dict(lead["crm"])
        previous["crm_feedback"] = {
            "state": "CLEAR",
            "crm_lead_id": 123,
            "lead_created_at": 100,
            "first_activity_at": 200,
            "excluded": False,
        }
        client = _RecordingClient()

        apply_crm_feedback_tracking(
            [lead],
            client,
            previous_leads=[previous],
            reuse_stable=True,
        )

        self.assertEqual(client.entity_calls, 0)
        self.assertEqual(lead["crm_feedback"], previous["crm_feedback"])


if __name__ == "__main__":
    unittest.main()
