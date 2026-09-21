from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.manual_history import MAIL_PHOTO_MESSAGE_ID, missing_manual_history_events
from lead_control.parsers.mail import parse_mail_message


class MailParserTests(unittest.TestCase):
    def test_mail_caption_is_separate_source(self) -> None:
        message = {
            "caption": "Заявка почта",
            "photo": [{"file_id": "photo"}],
        }

        lead = parse_mail_message(message)

        self.assertIsNotNone(lead)
        assert lead is not None
        self.assertEqual(lead["source"], "Заявка почта")
        self.assertTrue(lead["has_photo"])

    def test_confirmed_historical_photo_is_added_once(self) -> None:
        first = missing_manual_history_events([])
        photo_events = [item for item in first if item.get("message_id") == MAIL_PHOTO_MESSAGE_ID]
        self.assertEqual(len(photo_events), 2)
        self.assertEqual(photo_events[0]["message_id"], 5359)
        self.assertEqual(photo_events[0]["lead"]["source"], "Заявка почта")
        self.assertEqual(photo_events[0]["lead"]["phone_digits"], "79099171059")
        self.assertEqual(photo_events[0]["lead"]["guests_count"], 60)

        second = missing_manual_history_events(first)
        self.assertEqual(second, [])


if __name__ == "__main__":
    unittest.main()
