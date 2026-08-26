from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.amocrm_client import AmoCRMSearchResult
from lead_control.processor import apply_crm, normalize_updates, rebuild_leads
from lead_control.state import append_events, ensure_data_files, load_events, load_json


CHAT_ID = -1001645768111


class StateTests(unittest.TestCase):
    def test_fixture_test_lead_is_not_in_rebuilt_leads(self) -> None:
        updates = json.loads((ROOT / "tests/fixtures/telegram_tilda_reaction.json").read_text(encoding="utf-8"))
        events = normalize_updates(updates, CHAT_ID, set())

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["type"], "telegram_lead")
        self.assertTrue(events[0]["ignored"])
        self.assertEqual(events[0]["ignored_reason"], "test_phone")
        self.assertEqual(events[1]["type"], "telegram_reaction")
        self.assertEqual(events[1]["manager"]["name"], "Максим")
        self.assertEqual(events[1]["manager"]["username"], "empairbey")
        self.assertEqual(events[1]["manager"]["user_id"], 123456789)

        leads = rebuild_leads(events)
        self.assertEqual(leads, [])

    def test_data_files_bootstrap_and_ndjson_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            self.assertTrue(ensure_data_files(data_dir))
            self.assertFalse(ensure_data_files(data_dir))

            state = load_json(data_dir / "state.json", {})
            self.assertIn("telegram", state)
            self.assertIsNone(state["telegram"]["next_offset"])

            append_events(data_dir / "events.ndjson", [{"type": "x", "update_id": 1}])
            self.assertEqual(load_events(data_dir / "events.ndjson"), [{"type": "x", "update_id": 1}])

    def test_duplicate_window_and_ok_status(self) -> None:
        base_ts = 1787128800
        events = [
            _lead_event(1, 100, base_ts, "+71111111111"),
            _lead_event(2, 101, base_ts + 2 * 24 * 60 * 60, "+7 111 111-11-11"),
            _lead_event(3, 102, base_ts + 4 * 24 * 60 * 60, "+71111111111"),
            _reaction_event(4, 100, base_ts + 60),
        ]

        leads = rebuild_leads(events)
        self.assertEqual(len(leads), 2)
        self.assertEqual(leads[0]["telegram"]["message_ids"], [100, 101])
        self.assertEqual(leads[0]["manager_reaction"]["name"], "Максим")

        apply_crm(leads[:1], _FakeCRM(created_at=base_ts + 120))
        self.assertEqual(leads[0]["status"], "OK")
        self.assertEqual(leads[0]["violations"], [])


def _lead_event(update_id: int, message_id: int, timestamp: int, phone: str) -> dict[str, object]:
    return {
        "type": "telegram_lead",
        "update_id": update_id,
        "chat_id": CHAT_ID,
        "message_id": message_id,
        "telegram_date": timestamp,
        "telegram_date_msk": "2026-08-19T12:00:00+03:00",
        "source": "TildaForms",
        "ignored": False,
        "ignored_reason": "",
        "lead": {
            "source": "TildaForms",
            "name": "Real Lead",
            "phone_raw": phone,
            "phone_digits": "71111111111",
            "telegram_username": "",
            "event_date_raw": "30/08/2026",
            "event_date": "2026-08-30",
            "guests_count": 14,
            "event_type": "",
        },
    }


def _reaction_event(update_id: int, message_id: int, timestamp: int) -> dict[str, object]:
    return {
        "type": "telegram_reaction",
        "update_id": update_id,
        "chat_id": CHAT_ID,
        "message_id": message_id,
        "telegram_date": timestamp,
        "telegram_date_msk": "2026-08-19T12:01:00+03:00",
        "action": "reaction_set",
        "is_manager": True,
        "manager": {"name": "Максим", "username": "empairbey", "user_id": 123456789},
        "new_reaction": [{"type": "emoji", "emoji": "👍"}],
    }


class _FakeCRM:
    def __init__(self, created_at: int) -> None:
        self.created_at = created_at

    def search(self, query: str, lead_id: str, identifier_type: str) -> AmoCRMSearchResult:
        return AmoCRMSearchResult(
            found=True,
            entity_type="lead",
            entity_id=42,
            created_at=self.created_at,
            updated_at=self.created_at,
            responsible_user_id=1,
        )


if __name__ == "__main__":
    unittest.main()
