from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.manual_review_fields import enrich_manual_review_fields


class ManualReviewFieldsTests(unittest.TestCase):
    def test_confirmed_forwarded_author_name_is_applied_by_message_id(self) -> None:
        leads = [{
            "channel": "TELEGRAM",
            "message_id": 5666,
            "telegram": {"chat_id": -1001645768111, "message_ids": [5666]},
            "name": "",
            "fields": {"name": ""},
        }]
        overrides = [{
            "channel": "Telegram",
            "chat_id": -1001645768111,
            "message_id": 5666,
            "decision": "TG_LEAD",
            "lead_fields": {"name": "Marina Chudaeva"},
        }]

        enrich_manual_review_fields(leads, overrides)

        self.assertEqual(leads[0]["name"], "Marina Chudaeva")
        self.assertEqual(leads[0]["fields"]["name"], "Marina Chudaeva")

    def test_confirmed_username_becomes_crm_identifier(self) -> None:
        leads = [{
            "channel": "TELEGRAM",
            "message_id": 5666,
            "telegram": {"chat_id": -1001645768111, "message_ids": [5666]},
            "name": "Marina Chudaeva",
            "username": "",
            "fields": {"name": "Marina Chudaeva", "telegram_username": ""},
            "identifier": {
                "type": "review_message",
                "value": "Telegram:-1001645768111:5666",
            },
            "crm_required": True,
            "crm_check_status": "NO_IDENTIFIER",
        }]
        overrides = [{
            "channel": "Telegram",
            "chat_id": -1001645768111,
            "message_id": 5666,
            "decision": "TG_LEAD",
            "lead_fields": {
                "name": "Marina Chudaeva",
                "telegram_username": "@marina_chudaeva",
            },
        }]

        enrich_manual_review_fields(leads, overrides)

        self.assertEqual(leads[0]["username"], "marina_chudaeva")
        self.assertEqual(leads[0]["fields"]["telegram_username"], "marina_chudaeva")
        self.assertEqual(
            leads[0]["identifier"],
            {"type": "telegram_username", "value": "marina_chudaeva"},
        )
        self.assertEqual(leads[0]["crm_check_status"], "PENDING")

    def test_confirmed_email_becomes_crm_identifier(self) -> None:
        leads = [{
            "channel": "MAX",
            "message_id": "mid.mail",
            "max": {"chat_id": -71704692523093, "message_ids": ["mid.mail"]},
            "fields": {},
            "identifier": {"type": "review_message", "value": "mid.mail"},
            "crm_required": False,
            "crm_check_status": "NOT_REQUIRED",
        }]
        overrides = [{
            "channel": "MAX",
            "chat_id": -71704692523093,
            "message_id": "mid.mail",
            "lead_fields": {"email": "TroshinaCari@Yandex.ru"},
        }]

        enrich_manual_review_fields(leads, overrides)

        self.assertEqual(leads[0]["email"], "troshinacari@yandex.ru")
        self.assertEqual(leads[0]["fields"]["email"], "troshinacari@yandex.ru")
        self.assertEqual(
            leads[0]["identifier"],
            {"type": "email", "value": "troshinacari@yandex.ru"},
        )
        self.assertTrue(leads[0]["crm_required"])
        self.assertEqual(leads[0]["crm_check_status"], "PENDING")

    def test_other_messages_are_not_changed(self) -> None:
        leads = [{
            "channel": "TELEGRAM",
            "message_id": 9999,
            "telegram": {"chat_id": -1001645768111, "message_ids": [9999]},
            "name": "",
            "fields": {"name": ""},
        }]
        overrides = [{
            "channel": "Telegram",
            "chat_id": -1001645768111,
            "message_id": 5666,
            "lead_fields": {"name": "Marina Chudaeva"},
        }]

        enrich_manual_review_fields(leads, overrides)

        self.assertEqual(leads[0]["name"], "")


if __name__ == "__main__":
    unittest.main()
