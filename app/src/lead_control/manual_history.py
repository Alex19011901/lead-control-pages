from __future__ import annotations

from typing import Any


MAIL_PHOTO_MESSAGE_ID = 5359
REVIEWED_TG_MESSAGE_ID = 5666


def missing_manual_history_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing = {
        (str(event.get("type") or ""), str(event.get("message_id") or ""))
        for event in events
    }
    candidates = _manual_events()
    return [
        event
        for event in candidates
        if (str(event.get("type") or ""), str(event.get("message_id") or "")) not in existing
    ]


def _manual_events() -> list[dict[str, Any]]:
    lead_event = {
        "type": "telegram_lead",
        "update_id": -5359001,
        "chat_id": -1001645768111,
        "message_id": MAIL_PHOTO_MESSAGE_ID,
        "telegram_date": 1782902955,
        "telegram_date_msk": "2026-07-01T13:49:15+03:00",
        "source": "Заявка почта",
        "ignored": False,
        "ignored_reason": "",
        "lead": {
            "source": "Заявка почта",
            "name": "Ирина",
            "phone_raw": "+7 (909) 917 10 59",
            "phone_digits": "79099171059",
            "telegram_username": "",
            "event_date_raw": "6.07.26",
            "event_date": "2026-07-06",
            "guests_count": 60,
            "event_type": "Корпоратив",
            "description": (
                "Заявка почта. Дата: 6.07.26; время: 16:00; "
                "количество гостей: 60; имя клиента: Ирина; "
                "телефон: +7 (909) 917 10 59; дополнительный номер: 9099857506; корпоратив."
            ),
            "has_photo": True,
        },
    }
    reaction_event = {
        "type": "telegram_reaction",
        "update_id": -5359002,
        "chat_id": -1001645768111,
        "message_id": MAIL_PHOTO_MESSAGE_ID,
        "telegram_date": 1782905081,
        "telegram_date_msk": "2026-07-01T14:24:41+03:00",
        "action": "reaction_set",
        "is_manager": True,
        "manager": {
            "name": "Максим",
            "username": "empairbey",
            "user_id": 392177002,
        },
        "new_reaction": [{"type": "emoji", "emoji": "👍"}],
    }

    # This exact Telegram message was already reviewed by the user earlier and
    # classified as TG_LEAD. Keep the raw review event so review_overrides.json
    # applies that persisted first decision; it must never be surfaced again.
    reviewed_tg_event = {
        "type": "telegram_needs_review",
        "update_id": -5666001,
        "chat_id": -1001645768111,
        "message_id": REVIEWED_TG_MESSAGE_ID,
        "telegram_date": 1787317672,
        "telegram_date_msk": "2026-08-21T16:07:52+03:00",
        "sender_user_id": 491166267,
        "sender_username": "Green1504",
        "sender_name": "Мишуткина",
        "text": "Добрый день! У меня запрос на 25 декабря, 150 человек\nБанкет. Пришлите кп",
        "review_reason": "historical_user_review",
    }

    return [lead_event, reaction_event, reviewed_tg_event]
