from __future__ import annotations

from datetime import datetime
import unittest

from lead_control.lead_enrichment import enrich_leads_from_events
from lead_control.normalize import MOSCOW_TZ
from lead_control.manual_review_fields import enrich_manual_review_fields
from lead_control.parsers.max_leads import HOST, RESTAURANT_RATING, classify_max_text
from lead_control.processor import rebuild_leads_and_needs_review
from lead_control.review_overrides import build_override
from lead_control.source_categories import normalize_lead_sources


def _ts(year: int, month: int, day: int, hour: int) -> int:
    return int(datetime(year, month, day, hour, tzinfo=MOSCOW_TZ).timestamp())


def _lead(
    phone: str,
    first_seen_ts: int,
    *,
    name: str,
    channel: str,
    source: str,
    message_id: str,
) -> dict:
    first_seen_at = datetime.fromtimestamp(first_seen_ts, tz=MOSCOW_TZ).isoformat()
    lead = {
        "id": f"{channel}:{message_id}",
        "source": source,
        "channel": channel,
        "first_seen_ts": first_seen_ts,
        "first_seen_at": first_seen_at,
        "received_at": first_seen_at,
        "last_seen_ts": first_seen_ts,
        "last_seen_at": first_seen_at,
        "identifier": {"type": "phone", "value": phone},
        "fields": {"phone_digits": phone, "name": name},
        "name": name,
        "phone": phone,
        "crm_required": True,
        "manager_reaction": None,
    }
    if channel == "MAX":
        lead["message_id"] = message_id
        lead["max"] = {"message_ids": [message_id]}
    else:
        lead["telegram"] = {"message_ids": [int(message_id)], "update_ids": [int(message_id)]}
    return lead


class DailyLeadRegressionTests(unittest.TestCase):
    def test_same_phone_on_next_day_is_new_lead(self) -> None:
        first = _lead(
            "79269765311",
            _ts(2026, 9, 13, 11),
            name="Владимир",
            channel="TELEGRAM",
            source="САЙТ ТИЛЬДА",
            message_id="5880",
        )
        next_day = _lead(
            "89269765311",
            _ts(2026, 9, 14, 13),
            name="Владимир",
            channel="MAX",
            source="Заявки хост",
            message_id="5888",
        )
        leads = [first, next_day]

        enrich_leads_from_events(leads, [])

        self.assertEqual(len(leads), 2)
        self.assertEqual(leads[0]["first_seen_at"][:10], "2026-09-13")
        self.assertEqual(leads[1]["first_seen_at"][:10], "2026-09-14")

    def test_same_phone_same_day_same_name_is_one_lead(self) -> None:
        telegram = _lead(
            "79269765311",
            _ts(2026, 9, 14, 13),
            name="Владимир ЛУКЬЯНОВ",
            channel="TELEGRAM",
            source="САЙТ ТИЛЬДА",
            message_id="5888",
        )
        max_lead = _lead(
            "89269765311",
            _ts(2026, 9, 14, 13) + 360,
            name="Владимир",
            channel="MAX",
            source="Заявки хост",
            message_id="5890",
        )
        leads = [telegram, max_lead]

        enrich_leads_from_events(leads, [])

        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["first_seen_at"][:10], "2026-09-14")

    def test_same_phone_same_day_different_names_are_separate_leads(self) -> None:
        first = _lead(
            "79036692848",
            _ts(2026, 9, 11, 12),
            name="Ирина",
            channel="MAX",
            source="Restoran.Cafe",
            message_id="101",
        )
        second = _lead(
            "79036692848",
            _ts(2026, 9, 11, 12) + 23 * 60,
            name="Аида",
            channel="MAX",
            source="Заявки хост",
            message_id="102",
        )
        leads = [first, second]

        enrich_leads_from_events(leads, [])

        self.assertEqual(len(leads), 2)

    def test_explicit_host_with_season_and_phone_is_a_lead(self) -> None:
        result = classify_max_text("ЗАЯВКА. лето, 2027. Анна. 89854108881")

        self.assertEqual(result["classification"], HOST)
        self.assertTrue(result["include_in_stats"])
        self.assertEqual(result["fields"]["name"], "Анна")
        self.assertEqual(result["fields"]["phone_digits"], "79854108881")
        self.assertEqual(result["fields"]["event_date_raw"], "лето, 2027")

    def test_explicit_host_with_only_name_and_phone_is_still_a_lead(self) -> None:
        result = classify_max_text("ЗАЯВКА. Анна. 89854108881")

        self.assertEqual(result["classification"], HOST)
        self.assertEqual(result["fields"]["name"], "Анна")
        self.assertEqual(result["fields"]["phone_digits"], "79854108881")


    def test_confirmed_restaurant_rating_lead_has_own_source_and_photo_fields(self) -> None:
        message_id = "mid.ffffbec8f345ffab01a21c1606c2719a"
        received_ts = 1795767535298
        review = {
            "channel": "MAX",
            "source": "MAX",
            "chat_id": -71704692523093,
            "message_id": message_id,
            "sender": {"name": "Олеся", "user_id": 48906491},
            "status": "NEEDS_REVIEW",
            "timestamp": received_ts,
            "text": "ЗАЯВКА РЕСТОРАННЫЙ РЕЙТИНГ",
        }
        event = {
            "type": "max_message_created",
            "source": "MAX",
            "chat_id": review["chat_id"],
            "message_id": message_id,
            "sender_name": "Олеся",
            "sender_user_id": 48906491,
            "text": review["text"],
            "timestamp": received_ts,
        }
        override = build_override(review, RESTAURANT_RATING, "2026-11-27T18:41:00+03:00")
        override["lead_fields"] = {
            "name": "Олеся Жердецкая",
            "phone_raw": "+7 915 188-73-72",
            "event_date_raw": "10 декабря 2026",
            "event_date": "2026-12-10",
            "event_time": "16:00",
            "guests_count": 15,
            "event_type": "Корпоративный Новый год",
            "event_name": "КНГ Студия АР Рум/Олеся Жердецкая",
        }

        leads, pending = rebuild_leads_and_needs_review([event, dict(event)], [review], [override])
        normalize_lead_sources(leads)
        enrich_manual_review_fields(leads, [override])

        self.assertEqual(pending, [])
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["category"], RESTAURANT_RATING)
        self.assertEqual(leads[0]["source"], "Ресторанный рейтинг")
        self.assertEqual(leads[0]["name"], "Олеся Жердецкая")
        self.assertEqual(leads[0]["identifier"], {"type": "phone", "value": "79151887372"})
        self.assertEqual(leads[0]["event_date"], "2026-12-10")
        self.assertEqual(leads[0]["fields"]["event_time"], "16:00")
        self.assertEqual(leads[0]["guests"], 15)
        self.assertTrue(leads[0]["crm_required"])
        self.assertEqual(leads[0]["crm_check_status"], "PENDING")


if __name__ == "__main__":
    unittest.main()
