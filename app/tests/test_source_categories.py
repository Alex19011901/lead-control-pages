from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.source_categories import (
    TATIANA_TG,
    filter_known_source_reviews,
    is_tatiana_sender,
    normalize_known_source_events,
    normalize_lead_sources,
)


class SourceCategoryTests(unittest.TestCase):
    def test_tatiana_sender_matches_name_username_and_stable_id(self) -> None:
        self.assertTrue(is_tatiana_sender("Tatiana Ts", "anything"))
        self.assertTrue(is_tatiana_sender("anything", "@Tati_Ts_A"))
        self.assertTrue(is_tatiana_sender("Цебикова", "", 1366518980))
        self.assertTrue(is_tatiana_sender("Другое имя", "other", "user1366518980"))
        self.assertFalse(is_tatiana_sender("Цебикова", "", 999999999))

    def test_cebbikova_telegram_event_is_excluded_by_stable_user_id(self) -> None:
        event = {
            "type": "telegram_lead",
            "update_id": 100,
            "chat_id": -1001645768111,
            "message_id": 7001,
            "telegram_date": 1787217110,
            "telegram_date_msk": "2026-08-20T12:11:50+03:00",
            "sender_user_id": 1366518980,
            "sender_username": "",
            "sender_name": "Цебикова",
            "source": "Заявка с ТГ",
            "ignored": False,
            "ignored_reason": "",
            "lead": {
                "source": "Заявка с ТГ",
                "category": "TG_LEAD",
                "name": "Клиент",
                "phone_raw": "+7 916 111-22-33",
                "phone_digits": "79161112233",
            },
        }
        self.assertEqual(normalize_known_source_events([event]), [])

    def test_only_message_5670_is_one_off_skipped(self) -> None:
        events = [
            {
                "type": "telegram_needs_review",
                "update_id": 1,
                "chat_id": -1001645768111,
                "message_id": 5666,
                "telegram_date": 1787317672,
                "telegram_date_msk": "2026-08-21T16:07:52+03:00",
                "sender_name": "Мишуткина",
                "sender_username": "Green1504",
                "text": "Запрос на 25 декабря, 150 человек. Банкет.",
            },
            {
                "type": "telegram_needs_review",
                "update_id": 2,
                "chat_id": -1001645768111,
                "message_id": 5670,
                "telegram_date": 1787336401,
                "telegram_date_msk": "2026-08-21T21:20:01+03:00",
                "sender_name": "Someone",
                "sender_username": "someone",
                "text": "Партнерский запрос",
            },
            {
                "type": "telegram_needs_review",
                "update_id": 3,
                "chat_id": -1001645768111,
                "message_id": 7002,
                "telegram_date": 1787336405,
                "telegram_date_msk": "2026-08-21T21:20:05+03:00",
                "sender_name": "Someone",
                "sender_username": "someone",
                "text": "Обычный неоднозначный текст",
            },
        ]

        normalized = normalize_known_source_events(events)
        self.assertEqual([event["message_id"] for event in normalized], [5666, 7002])

    def test_legacy_tatiana_event_is_excluded_without_sender_metadata(self) -> None:
        events = [
            {
                "type": "telegram_lead",
                "update_id": 200,
                "chat_id": -1001645768111,
                "message_id": 8001,
                "telegram_date": 1787217110,
                "telegram_date_msk": "2026-08-20T12:11:50+03:00",
                "source": TATIANA_TG,
                "ignored": False,
                "ignored_reason": "",
                "lead": {"source": TATIANA_TG, "category": TATIANA_TG},
            }
        ]
        self.assertEqual(normalize_known_source_events(events), [])

    def test_existing_tatiana_lead_removed_but_normal_lead_kept(self) -> None:
        leads = [
            {
                "source": "Заявка с ТГ",
                "category": "TG_LEAD",
                "channel": "TELEGRAM",
                "sender_user_id": 1366518980,
                "sender_name": "Цебикова",
                "fields": {"source": "Заявка с ТГ", "category": "TG_LEAD"},
            },
            {
                "source": "Заявка с ТГ",
                "category": "TG_LEAD",
                "channel": "TELEGRAM",
                "sender_user_id": 999,
                "sender_name": "Someone",
                "fields": {"source": "Заявка с ТГ", "category": "TG_LEAD"},
            },
        ]
        normalize_lead_sources(leads)
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["sender_name"], "Someone")

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

    def test_existing_marquiz_and_tilda_reviews_are_promoted(self) -> None:
        events = [
            {
                "type": "telegram_needs_review",
                "update_id": 10,
                "chat_id": -1001645768111,
                "message_id": 7100,
                "telegram_date": 1787217110,
                "telegram_date_msk": "2026-08-20T12:11:50+03:00",
                "sender_user_id": 446491725,
                "sender_username": "MarquizBot",
                "sender_name": "MarquizBot",
                "text": "Имя: Александр\nТелефон: +79036729289",
            },
            {
                "type": "telegram_needs_review",
                "update_id": 11,
                "chat_id": -1001645768111,
                "message_id": 7101,
                "telegram_date": 1787219378,
                "telegram_date_msk": "2026-08-20T12:49:38+03:00",
                "sender_user_id": 265299531,
                "sender_username": "TildaFormsBot",
                "sender_name": "TildaForms",
                "text": "Содержание заявки:\nname: Кристина\nphone: +79199356534\nDate: 07-11-2026",
            },
        ]
        normalized = normalize_known_source_events(events)
        self.assertEqual(normalized[0]["lead"]["source"], "MARQUIZ")
        self.assertEqual(normalized[1]["lead"]["source"], "САЙТ ТИЛЬДА")

    def test_max_tilda_veranda_source_stays_separate(self) -> None:
        leads = [
            {
                "source": "Тильда Веранда",
                "category": "TILDA_VERANDA",
                "channel": "MAX",
                "fields": {"source": "Тильда Веранда", "category": "TILDA_VERANDA"},
                "sender_name": "TildaForms",
                "max": {"sender_username": "tildaforms_bot"},
            }
        ]
        normalize_lead_sources(leads)
        self.assertEqual(leads[0]["source"], "Тильда Веранда")
        self.assertEqual(leads[0]["category"], "TILDA_VERANDA")

    def test_known_bot_reviews_do_not_remain_in_needs_review(self) -> None:
        items = [
            {"source": "Telegram", "sender": {"name": "MarquizBot", "username": "MarquizBot"}},
            {"source": "Telegram", "sender": {"name": "TildaForms", "username": "TildaFormsBot"}},
            {"source": "Telegram", "sender": {"name": "Someone", "username": "someone"}},
        ]
        result = filter_known_source_reviews(items)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["sender"]["name"], "Someone")


if __name__ == "__main__":
    unittest.main()
