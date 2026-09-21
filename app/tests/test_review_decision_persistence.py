from __future__ import annotations

import unittest

from lead_control.manual_history import REVIEWED_TG_MESSAGE_ID, missing_manual_history_events
from lead_control.processor import _manual_fields
from lead_control.review_overrides import build_override, upsert_override


class ReviewDecisionPersistenceTests(unittest.TestCase):
    def test_reviewed_5666_is_restored_as_raw_review_event(self) -> None:
        events = missing_manual_history_events([])
        event = next(item for item in events if item.get("message_id") == REVIEWED_TG_MESSAGE_ID)
        self.assertEqual(event["type"], "telegram_needs_review")
        self.assertEqual(event["message_id"], 5666)
        self.assertIn("150 человек", event["text"])

    def test_manual_max_name_after_phone_is_extracted(self) -> None:
        fields = _manual_fields(
            "Заявка 6.10 15-20 перс свадьба мз +79271764323 Александр, ждут меню",
            "HOST",
        )

        self.assertEqual(fields["phone_digits"], "79271764323")
        self.assertEqual(fields["name"], "Александр")

    def test_manual_telegram_name_near_username_is_extracted(self) -> None:
        fields = _manual_fields(
            "Марина @marina_chudaeva",
            "TG_LEAD",
        )

        self.assertEqual(fields["telegram_username"], "marina_chudaeva")
        self.assertEqual(fields["name"], "Марина")

    def test_first_decision_cannot_be_silently_replaced(self) -> None:
        item = {
            "channel": "Telegram",
            "chat_id": -1001645768111,
            "message_id": 5666,
            "text": "Добрый день! У меня запрос на 25 декабря, 150 человек",
        }
        first = build_override(item, "TG_LEAD", "2026-08-21T17:26:00+03:00")
        stored, changed = upsert_override([], first)
        self.assertTrue(changed)
        self.assertEqual(stored[0]["decision"], "TG_LEAD")

        conflicting = build_override(item, "IGNORE", "2026-08-22T13:00:00+03:00")
        with self.assertRaises(ValueError):
            upsert_override(stored, conflicting)


if __name__ == "__main__":
    unittest.main()
