from __future__ import annotations

from datetime import datetime
import unittest
from zoneinfo import ZoneInfo

from lead_control.closed_not_realized import apply_closed_not_realized_history


MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def _ts(day: int, hour: int = 12) -> int:
    return int(datetime(2026, 9, day, hour, tzinfo=MOSCOW_TZ).timestamp())


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[int, tuple[tuple[str, str], ...]]] = []
        self.request_calls: list[tuple[str, dict]] = []
        self.cards = {
            101: {"id": 101, "closed_at": _ts(16), "loss_reason_id": 501},
            102: {"id": 102, "closed_at": _ts(11), "loss_reason_id": 502},
        }

    def _get_entity(self, entity_type, entity_id, params=None):
        key = tuple(sorted((str(k), str(v)) for k, v in (params or {}).items()))
        self.calls.append((int(entity_id), key))
        card = dict(self.cards[int(entity_id)])
        if params and params.get("with") == "loss_reason":
            card["_embedded"] = {
                "loss_reason": [{"id": card["loss_reason_id"], "name": "Не устроила цена"}]
            }
        return card

    def _request_json(self, path, params):
        self.request_calls.append((path, dict(params)))
        if path != "/api/v4/leads/notes":
            return {}
        return {
            "_embedded": {
                "notes": [
                    {
                        "entity_id": 101,
                        "note_type": "common",
                        "created_at": _ts(15, 10),
                        "params": {"text": "Первый комментарий"},
                    },
                    {
                        "entity_id": 101,
                        "note_type": "common",
                        "created_at": _ts(16, 9),
                        "params": {"text": "Клиент выбрал другую площадку"},
                    },
                ]
            },
            "_links": {},
        }


class ClosedNotRealizedTests(unittest.TestCase):
    def test_only_last_five_moscow_dates_are_attached_with_reason_and_latest_comment(self):
        leads = [
            {
                "crm": {"found": True, "entity_type": "lead", "entity_id": 101},
                "crm_feedback": {"status_id": 143, "status_name": "Закрыто и не реализовано"},
            },
            {
                "crm": {"found": True, "entity_type": "lead", "entity_id": 102},
                "crm_feedback": {"status_id": 143, "status_name": "Закрыто и не реализовано"},
            },
        ]
        client = FakeClient()

        apply_closed_not_realized_history(leads, client, now_ts=_ts(16, 18))

        self.assertEqual(leads[0]["closed_not_realized"]["closed_at"], _ts(16))
        self.assertEqual(leads[0]["closed_not_realized"]["loss_reason_name"], "Не устроила цена")
        self.assertEqual(
            leads[0]["closed_not_realized"]["last_comment"],
            "Клиент выбрал другую площадку",
        )
        self.assertEqual(leads[0]["closed_not_realized"]["last_comment_at"], _ts(16, 9))
        self.assertNotIn("closed_not_realized", leads[1])
        reason_calls = [call for call in client.calls if call[1] == (("with", "loss_reason"),)]
        self.assertEqual(reason_calls, [(101, (("with", "loss_reason"),))])
        self.assertEqual(len(client.request_calls), 1)

    def test_non_closed_status_is_ignored(self):
        leads = [{
            "crm": {"found": True, "entity_type": "lead", "entity_id": 101},
            "crm_feedback": {"status_id": 142, "status_name": "Успешно реализовано"},
            "closed_not_realized": {"stale": True},
        }]
        client = FakeClient()

        apply_closed_not_realized_history(leads, client, now_ts=_ts(16, 18))

        self.assertNotIn("closed_not_realized", leads[0])
        self.assertEqual(client.calls, [])
        self.assertEqual(client.request_calls, [])


if __name__ == "__main__":
    unittest.main()
