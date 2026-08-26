from __future__ import annotations

import json
import ssl
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.max_client import MAX_CHAT_ID, MaxClient, filter_new_max_events, normalize_max_update
from lead_control.state import DEFAULT_STATE


class RecordingMaxClient(MaxClient):
    def __init__(self) -> None:
        super().__init__("token")
        self.last_path = ""
        self.last_params: dict[str, str | int] = {}

    def _request_json(self, path: str, params: dict[str, str | int] | None = None):
        self.last_path = path
        self.last_params = dict(params or {})
        return {"updates": [], "marker": 123}


class MaxClientTests(unittest.TestCase):
    def test_message_created_uses_body_mid_as_message_id(self) -> None:
        update = json.loads((ROOT / "tests/fixtures/max_message_created.json").read_text(encoding="utf-8"))

        event = normalize_max_update(update)

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event["source"], "MAX")
        self.assertEqual(event["update_type"], "message_created")
        self.assertEqual(event["chat_id"], MAX_CHAT_ID)
        self.assertEqual(event["message_id"], "mid.ffffbec8f345ffab01a01adebd363f53")
        self.assertEqual(event["body_mid"], "mid.ffffbec8f345ffab01a01adebd363f53")
        self.assertEqual(event["text"], "ТЕСТ MAX LEAD CONTROL")
        self.assertEqual(event["sender_user_id"], 74336871)
        self.assertIsNone(event["sender_username"])
        self.assertEqual(event["sender_name"], "Test Sender")
        self.assertEqual(event["timestamp"], 1787157200182)

    def test_message_created_ignores_other_chats(self) -> None:
        update = json.loads((ROOT / "tests/fixtures/max_message_created.json").read_text(encoding="utf-8"))
        update["message"]["recipient"]["chat_id"] = -1

        self.assertIsNone(normalize_max_update(update))

    def test_state_has_separate_max_marker(self) -> None:
        self.assertEqual(DEFAULT_STATE["telegram"]["next_offset"], None)
        self.assertEqual(DEFAULT_STATE["max"]["marker"], None)

    def test_message_created_duplicate_is_filtered_by_body_mid(self) -> None:
        update = json.loads((ROOT / "tests/fixtures/max_message_created.json").read_text(encoding="utf-8"))
        event = normalize_max_update(update)

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(
            filter_new_max_events([event], {"mid.ffffbec8f345ffab01a01adebd363f53"}),
            [],
        )
        self.assertEqual(filter_new_max_events([event], set()), [event])

    def test_get_updates_requests_maximum_supported_batch(self) -> None:
        client = RecordingMaxClient()

        result = client.get_updates(marker=705984)

        self.assertEqual(result.marker, 123)
        self.assertEqual(client.last_path, "/updates")
        self.assertEqual(client.last_params["marker"], 705984)
        self.assertEqual(client.last_params["limit"], 1000)
        self.assertEqual(client.last_params["timeout"], 0)
        self.assertEqual(client.last_params["types"], "bot_added,message_created")

    def test_ca_file_keeps_ssl_verification_enabled(self) -> None:
        client = MaxClient("token", ca_file=str(ROOT / "certs/max_ca_bundle.pem"))
        context = client._ssl_context

        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)


if __name__ == "__main__":
    unittest.main()
