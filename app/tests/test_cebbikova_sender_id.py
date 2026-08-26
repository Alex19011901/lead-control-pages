from __future__ import annotations

import unittest

from lead_control.source_categories import (
    is_tatiana_sender,
    normalize_known_source_events,
    normalize_lead_sources,
)


class CebikovaSenderIdTests(unittest.TestCase):
    def test_stable_telegram_user_id_matches_even_when_name_changes(self) -> None:
        self.assertTrue(is_tatiana_sender("Цебикова", "", 1366518980))
        self.assertTrue(is_tatiana_sender("Другое имя", "other", "user1366518980"))
        self.assertFalse(is_tatiana_sender("Цебикова", "", 999999999))

    def test_telegram_event_from_cebbikova_id_is_excluded(self) -> None:
        event = {
            "type": "telegram_lead",
            "update_id": 185608012,
            "chat_id": -1001645768111,
            "message_id": 5668,
            "telegram_date": 1787336363,
            "telegram_date_msk": "2026-08-21T21:19:23+03:00",
            "sender_user_id": 1366518980,
            "sender_username": "",
            "sender_name": "Цебикова",
            "source": "Заявка с ТГ",
            "ignored": False,
            "ignored_reason": "",
            "lead": {
                "source": "Заявка с ТГ",
                "category": "TG_LEAD",
                "name": "🎀ЮА🎀",
                "phone_digits": "79267067586",
            },
        }
        self.assertEqual(normalize_known_source_events([event]), [])

    def test_legacy_import_without_sender_metadata_is_also_excluded(self) -> None:
        event = {
            "type": "telegram_lead",
            "update_id": -10056681,
            "chat_id": -1001645768111,
            "message_id": 5668,
            "telegram_date": 1787336363,
            "telegram_date_msk": "2026-08-21T21:19:23+03:00",
            "source": "Заявка с ТГ",
            "ignored": False,
            "ignored_reason": "",
            "lead": {
                "source": "Заявка с ТГ",
                "category": "TG_LEAD",
                "name": "🎀ЮА🎀",
                "phone_digits": "79267067586",
            },
        }
        self.assertEqual(normalize_known_source_events([event]), [])

    def test_same_user_id_does_not_remove_max_lead(self) -> None:
        leads = [
            {
                "source": "Заявки хост",
                "category": "HOST",
                "channel": "MAX",
                "sender_user_id": 1366518980,
                "sender_name": "Цебикова",
                "fields": {"source": "Заявки хост", "category": "HOST"},
            }
        ]
        normalize_lead_sources(leads)
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["source"], "Заявки хост")


if __name__ == "__main__":
    unittest.main()
