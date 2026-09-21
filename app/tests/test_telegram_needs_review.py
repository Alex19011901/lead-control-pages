from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.processor import normalize_updates, rebuild_leads_and_needs_review
from lead_control.source_categories import normalize_known_source_events


CHAT_ID = -1001645768111
BASE_TS = 1787130000


class TelegramNeedsReviewTests(unittest.TestCase):
    def test_tilda_message_remains_lead_not_needs_review(self) -> None:
        events = normalize_updates([_message_update(1, 100, _tilda_text())], CHAT_ID, set())

        leads, review = rebuild_leads_and_needs_review(events)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "telegram_lead")
        self.assertFalse(events[0]["ignored"])
        self.assertEqual(len(leads), 1)
        self.assertEqual(review, [])

    def test_tatiana_telegram_message_is_excluded_before_rebuild(self) -> None:
        events = normalize_updates(
            [
                _message_update(
                    8,
                    105,
                    _tilda_text(),
                    sender={"first_name": "Tatiana", "last_name": "Ts", "username": "Tati_Ts_A"},
                )
            ],
            CHAT_ID,
            set(),
        )
        events = normalize_known_source_events(events)

        leads, review = rebuild_leads_and_needs_review(events)

        self.assertEqual(events, [])
        self.assertEqual(leads, [])
        self.assertEqual(review, [])

    def test_tatiana_unknown_text_is_excluded_from_needs_review(self) -> None:
        events = normalize_updates(
            [
                _message_update(
                    9,
                    106,
                    "Ищем площадку на 03.09 для 70 гостей",
                    sender={"first_name": "Tatiana", "last_name": "Ts", "username": "Tati_Ts_A"},
                )
            ],
            CHAT_ID,
            set(),
        )
        events = normalize_known_source_events(events)

        leads, review = rebuild_leads_and_needs_review(events)

        self.assertEqual(events, [])
        self.assertEqual(leads, [])
        self.assertEqual(review, [])

    def test_telegram_reaction_is_not_needs_review(self) -> None:
        events = normalize_updates([_reaction_update(2, 100)], CHAT_ID, set())

        leads, review = rebuild_leads_and_needs_review(events)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "telegram_reaction")
        self.assertEqual(leads, [])
        self.assertEqual(review, [])

    def test_test_message_is_not_needs_review(self) -> None:
        events = normalize_updates([_message_update(3, 101, "ТЕСТ РЕАКЦИИ")], CHAT_ID, set())

        leads, review = rebuild_leads_and_needs_review(events)

        self.assertEqual(events, [])
        self.assertEqual(leads, [])
        self.assertEqual(review, [])

    def test_unknown_text_message_goes_to_needs_review(self) -> None:
        events = normalize_updates(
            [_message_update(4, 102, "Добрый день, нужен зал на 12.09, кто ответит?")],
            CHAT_ID,
            set(),
        )

        leads, review = rebuild_leads_and_needs_review(events)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "telegram_needs_review")
        self.assertEqual(leads, [])
        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]["channel"], "Telegram")
        self.assertEqual(review[0]["chat_id"], CHAT_ID)
        self.assertEqual(review[0]["message_id"], 102)
        self.assertEqual(review[0]["sender"]["user_id"], 987654321)
        self.assertEqual(review[0]["sender"]["username"], "unknown_sender")
        self.assertEqual(review[0]["status"], "NEEDS_REVIEW")

    def test_repeated_telegram_message_id_does_not_duplicate_review(self) -> None:
        event = normalize_updates([_message_update(5, 103, "Неясный текст заявки")], CHAT_ID, set())[0]
        duplicate = dict(event)
        duplicate["update_id"] = 6

        leads, review = rebuild_leads_and_needs_review([event, duplicate])

        self.assertEqual(leads, [])
        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]["message_id"], 103)

    def test_existing_max_review_entries_are_preserved(self) -> None:
        telegram_event = normalize_updates([_message_update(7, 104, "Неясный Telegram текст")], CHAT_ID, set())[0]
        existing_max_review = {
            "channel": "MAX",
            "source": "MAX",
            "message_id": "mid.review",
            "chat_id": -71704692523093,
            "sender": {"user_id": 123, "username": None, "name": None},
            "timestamp": 1787159436779,
            "text": "28.08 Виктория 89991234567",
            "review_reason": "ambiguous_contact_or_event_details",
            "status": "NEEDS_REVIEW",
        }

        leads, review = rebuild_leads_and_needs_review([telegram_event], [existing_max_review])

        self.assertEqual(leads, [])
        self.assertEqual(len(review), 2)
        self.assertEqual({item["channel"] for item in review}, {"MAX", "Telegram"})


def _message_update(
    update_id: int,
    message_id: int,
    text: str,
    sender: dict[str, object] | None = None,
) -> dict[str, object]:
    sender_payload = {
        "id": 987654321,
        "is_bot": False,
        "first_name": "Unknown",
        "last_name": "Sender",
        "username": "unknown_sender",
    }
    if sender:
        sender_payload.update(sender)

    return {
        "update_id": update_id,
        "message": {
            "message_id": message_id,
            "date": BASE_TS,
            "chat": {"id": CHAT_ID, "title": "Заявки с САЙТА"},
            "from": sender_payload,
            "text": text,
        },
    }


def _reaction_update(update_id: int, message_id: int) -> dict[str, object]:
    return {
        "update_id": update_id,
        "message_reaction": {
            "chat": {"id": CHAT_ID, "title": "Заявки с САЙТА"},
            "message_id": message_id,
            "user": {
                "id": 123456789,
                "is_bot": False,
                "first_name": "Максим",
                "username": "empairbey",
            },
            "date": BASE_TS + 60,
            "old_reaction": [],
            "new_reaction": [{"type": "emoji", "emoji": "👍"}],
        },
    }


def _tilda_text() -> str:
    return "\n".join(
        [
            "TildaForms",
            "Имя: Анна",
            "Телефон: +7 916 111-22-33",
            "Дата мероприятия: 30/08/2026",
            "Количество гостей: 14",
        ]
    )


if __name__ == "__main__":
    unittest.main()
