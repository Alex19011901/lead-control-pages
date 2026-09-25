from __future__ import annotations

from datetime import datetime
import unittest
from zoneinfo import ZoneInfo

from lead_control.crm_pipeline_activity import collect_pipeline_activity


MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def _ts(year: int, month: int, day: int, hour: int = 12) -> int:
    return int(datetime(year, month, day, hour, tzinfo=MOSCOW_TZ).timestamp())


def _event(event_id: str, entity_id: int, created_at: int, before_id: int, after_id: int, pipeline_id: int = 77):
    return {
        "id": event_id,
        "type": "lead_status_changed",
        "entity_id": entity_id,
        "entity_type": "lead",
        "created_at": created_at,
        "value_before": [{"lead_status": {"id": before_id, "pipeline_id": pipeline_id}}],
        "value_after": [{"lead_status": {"id": after_id, "pipeline_id": pipeline_id}}],
    }


class FakeClient:
    def _request_json(self, path, params):
        if path == "/api/v4/leads/pipelines/77":
            return {
                "id": 77,
                "name": "Основная воронка",
                "_embedded": {
                    "statuses": [
                        {"id": 10, "name": "Новый лид", "sort": 10},
                        {"id": 20, "name": "Ждём на дегустацию", "sort": 20},
                        {"id": 30, "name": "Предбронь", "sort": 30},
                    ]
                },
            }
        if path == "/api/v4/events":
            return {
                "_embedded": {
                    "events": [
                        _event("a", 101, _ts(2026, 9, 25, 10), 10, 20),
                        _event("b", 101, _ts(2026, 9, 25, 12), 20, 30),
                        _event("c", 101, _ts(2026, 9, 25, 14), 30, 20),
                        _event("d", 999, _ts(2026, 9, 25, 15), 10, 20),
                        _event("e", 101, _ts(2026, 9, 25, 16), 20, 30, pipeline_id=88),
                    ]
                },
                "_links": {},
            }
        raise AssertionError(path)


class PipelineActivityTests(unittest.TestCase):
    def test_counts_every_real_transition_for_tracked_lead(self):
        leads = [
            {
                "crm": {"found": True, "entity_type": "lead", "entity_id": 101},
                "crm_feedback": {"pipeline_id": 77},
            },
            {
                "crm": {"found": True, "entity_type": "lead", "entity_id": 102},
                "crm_feedback": {"pipeline_id": 77},
            },
        ]

        result = collect_pipeline_activity(
            leads,
            FakeClient(),
            now_ts=_ts(2026, 9, 25, 18),
        )

        self.assertEqual(result["pipeline_id"], 77)
        self.assertEqual(result["pipeline_name"], "Основная воронка")
        self.assertEqual(len(result["weeks"]), 4)
        self.assertEqual(result["weeks"][0]["start"], "2026-09-21")
        self.assertEqual(result["weeks"][0]["end"], "2026-09-27")
        self.assertEqual(result["days"]["2026-09-25"]["20"], 2)
        self.assertEqual(result["days"]["2026-09-25"]["30"], 1)
        self.assertEqual(result["total_movements"], 3)

    def test_empty_when_no_tracked_crm_leads(self):
        result = collect_pipeline_activity([], FakeClient(), now_ts=_ts(2026, 9, 25))
        self.assertEqual(result["total_movements"], 0)
        self.assertEqual(result["stages"], [])
        self.assertEqual(len(result["weeks"]), 4)


if __name__ == "__main__":
    unittest.main()
