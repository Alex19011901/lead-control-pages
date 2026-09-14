from __future__ import annotations

from datetime import datetime
import unittest

from lead_control.amocrm_client import AmoCRMSearchResult
from lead_control.crm_apply import apply_crm
from lead_control.daily_duplicates import apply_daily_phone_duplicate_policy
from lead_control.normalize import MOSCOW_TZ
from lead_control.status_policy import apply_crm_day_status_policy


PHONE = "79269765311"


def _ts(day: int, hour: int, minute: int = 0) -> int:
    return int(datetime(2026, 9, day, hour, minute, tzinfo=MOSCOW_TZ).timestamp())


def _tg_event(message_id: int, day: int, hour: int, minute: int, name: str = "Владимир ЛУКЬЯНОВ") -> dict:
    ts = _ts(day, hour, minute)
    return {
        "type": "telegram_lead",
        "update_id": message_id + 1000,
        "chat_id": -1001,
        "message_id": message_id,
        "telegram_date": ts,
        "telegram_date_msk": datetime.fromtimestamp(ts, MOSCOW_TZ).isoformat(),
        "source": "САЙТ ТИЛЬДА",
        "lead": {
            "source": "САЙТ ТИЛЬДА",
            "name": name,
            "phone_digits": PHONE,
            "phone_raw": "+79269765311",
            "event_date": "2026-10-05",
            "guests_count": 10,
            "description": "Name: Владимир ЛУКЬЯНОВ\nPhone: +79269765311\nDate: 05-10-2026\nInput: 10",
        },
    }


def _merged_tg_lead() -> dict:
    ts = _ts(13, 11, 28)
    return {
        "id": "merged-tg",
        "source": "САЙТ ТИЛЬДА",
        "channel": "TELEGRAM",
        "first_seen_ts": ts,
        "first_seen_at": datetime.fromtimestamp(ts, MOSCOW_TZ).isoformat(),
        "received_at": datetime.fromtimestamp(ts, MOSCOW_TZ).isoformat(),
        "last_seen_ts": _ts(14, 13, 6),
        "last_seen_at": datetime.fromtimestamp(_ts(14, 13, 6), MOSCOW_TZ).isoformat(),
        "identifier": {"type": "phone", "value": PHONE},
        "fields": {"source": "САЙТ ТИЛЬДА", "name": "Владимир", "phone_digits": PHONE},
        "name": "Владимир",
        "phone": PHONE,
        "crm_required": True,
        "crm": {"found": False},
        "status": "PENDING",
        "violations": [],
        "telegram": {"chat_id": -1001, "message_ids": [5880, 5888, 5889], "update_ids": [6880, 6888, 6889]},
    }


def _max_event() -> dict:
    ts = _ts(14, 13, 12)
    return {
        "type": "max_message_created",
        "source": "MAX",
        "message_id": "mid.vladimir.today",
        "chat_id": -717,
        "sender_name": "Алёна",
        "timestamp": ts * 1000,
        "text": "ЗАЯВКА. 05.10. 10п. Владимир. 89269765311",
        "has_attachments": False,
        "has_linked_or_forwarded_message": False,
    }


def _max_lead() -> dict:
    ts = _ts(14, 13, 12)
    return {
        "id": "max-today",
        "source": "Заявки хост",
        "category": "HOST",
        "channel": "MAX",
        "message_id": "mid.vladimir.today",
        "first_seen_ts": ts,
        "first_seen_at": datetime.fromtimestamp(ts, MOSCOW_TZ).isoformat(),
        "received_at": datetime.fromtimestamp(ts, MOSCOW_TZ).isoformat(),
        "last_seen_ts": ts,
        "last_seen_at": datetime.fromtimestamp(ts, MOSCOW_TZ).isoformat(),
        "identifier": {"type": "phone", "value": PHONE},
        "fields": {"source": "Заявки хост", "name": "Владимир", "phone_digits": PHONE},
        "name": "Владимир",
        "phone": PHONE,
        "crm_required": True,
        "crm": {"found": False},
        "status": "PENDING",
        "violations": [],
        "max": {"chat_id": -717, "message_ids": ["mid.vladimir.today"]},
    }


class FakeCRM:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, **kwargs) -> AmoCRMSearchResult:
        self.queries.append(query)
        return AmoCRMSearchResult(found=False)


class DailyDuplicatePolicyTests(unittest.TestCase):
    def test_next_day_is_new_lead_and_same_day_repeats_are_visible_duplicates_without_crm(self) -> None:
        events = [
            _tg_event(5880, 13, 11, 28, "Владимир"),
            _tg_event(5888, 14, 13, 6),
            _tg_event(5889, 14, 13, 7),
            _max_event(),
        ]
        leads = [_merged_tg_lead(), _max_lead()]

        apply_daily_phone_duplicate_policy(leads, events)

        self.assertEqual(len(leads), 4)
        sep13 = [lead for lead in leads if lead["first_seen_at"][:10] == "2026-09-13"]
        sep14 = sorted(
            [lead for lead in leads if lead["first_seen_at"][:10] == "2026-09-14"],
            key=lambda lead: lead["first_seen_ts"],
        )
        self.assertEqual(len(sep13), 1)
        self.assertFalse(sep13[0].get("is_duplicate", False))
        self.assertEqual(len(sep14), 3)
        self.assertFalse(sep14[0].get("is_duplicate", False))
        self.assertTrue(sep14[0].get("daily_repeat_phone"))
        self.assertEqual([lead["status"] for lead in sep14[1:]], ["DUPLICATE", "DUPLICATE"])
        self.assertTrue(all(lead["crm_required"] is False for lead in sep14[1:]))
        self.assertTrue(all(lead["duplicate_of"] == sep14[0]["id"] for lead in sep14[1:]))

        crm = FakeCRM()
        apply_crm(leads, crm)
        self.assertEqual(len(crm.queries), 2)

        apply_crm_day_status_policy(leads, now_ts=_ts(14, 14, 0))
        self.assertEqual([lead["status"] for lead in sep14[1:]], ["DUPLICATE", "DUPLICATE"])


if __name__ == "__main__":
    unittest.main()
