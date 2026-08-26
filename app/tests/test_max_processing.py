from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.amocrm_client import AmoCRMSearchResult
from lead_control.processor import apply_crm, rebuild_leads_and_needs_review
from lead_control.report import build_report


CHAT_ID = -71704692523093
BASE_TS_MS = 1787159436779


class MaxProcessingTests(unittest.TestCase):
    def test_tilda_veranda_creates_no_crm_lead(self) -> None:
        leads, review = rebuild_leads_and_needs_review(
            [
                _max_event(
                    "mid.tilda",
                    "\n".join(
                        [
                            "TildaForms",
                            "Источник: https://svetliy-moscow.ru/menu",
                            "Имя: Анна",
                            "Телефон: +7 916 111-22-33",
                            "Дата мероприятия: 30/08/2026",
                            "Количество персон: 40",
                        ]
                    ),
                )
            ]
        )
        crm = _FakeCRM(found=True)

        apply_crm(leads, crm)

        self.assertEqual(review, [])
        self.assertEqual(len(leads), 1)
        self.assertEqual(crm.calls, [])
        self.assertEqual(leads[0]["source"], "Тильда Веранда")
        self.assertFalse(leads[0]["crm_required"])
        self.assertEqual(leads[0]["status"], "OK")

    def test_wedwed_creates_no_crm_lead(self) -> None:
        leads, review = rebuild_leads_and_needs_review([
            _max_event("mid.wedwed", "WedWed\nНовый запрос с сайта WedWed\nДата: 28.08")
        ])
        crm = _FakeCRM(found=True)

        apply_crm(leads, crm)

        self.assertEqual(review, [])
        self.assertEqual(len(leads), 1)
        self.assertEqual(crm.calls, [])
        self.assertEqual(leads[0]["source"], "WedWed")
        self.assertFalse(leads[0]["crm_required"])
        self.assertEqual(leads[0]["status"], "OK")

    def test_host_crm_found_is_ok_without_no_reaction(self) -> None:
        leads, review = rebuild_leads_and_needs_review([
            _max_event("mid.host.ok", "ЗАЯВКА. 24.12. 20п. Ксения. 89161234567 Корпоратив.")
        ])

        apply_crm(leads, _FakeCRM(found=True, created_at=BASE_TS_MS // 1000 + 60))

        self.assertEqual(review, [])
        self.assertEqual(leads[0]["status"], "OK")
        self.assertNotIn("NO_REACTION", leads[0]["violations"])

    def test_host_crm_missing_is_alarm_no_crm(self) -> None:
        leads, review = rebuild_leads_and_needs_review([
            _max_event("mid.host.missing", "ЗАЯВКА. 24.12. 20п. Ксения. 89161234567 Корпоратив.")
        ])

        apply_crm(leads, _FakeCRM(found=False))

        self.assertEqual(review, [])
        self.assertEqual(leads[0]["status"], "ALARM_NO_CRM")
        self.assertEqual(leads[0]["violations"], ["ALARM_NO_CRM"])

    def test_street_creates_lead(self) -> None:
        leads, review = rebuild_leads_and_needs_review([
            _max_event(
                "mid.street",
                "\n".join(
                    [
                        "Гости пришли на просмотр, зал показал",
                        "2.10.26",
                        "70чел. тел. 89851234567",
                        "София",
                        "Ждут инфу.",
                    ]
                ),
            )
        ])

        self.assertEqual(review, [])
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["source"], "С улицы")
        self.assertTrue(leads[0]["crm_required"])

    def test_tg_lead_uses_username_for_crm_lookup(self) -> None:
        leads, review = rebuild_leads_and_needs_review([
            _max_event(
                "mid.tg",
                "\n".join(
                    [
                        "ЗАЯВКА",
                        "Здравствуйте! Ищу помещение для делового ужина на 27 августа.",
                        "Гостей может быть от 20 до 40.",
                        "@urban_meow",
                    ]
                ),
            )
        ])
        crm = _FakeCRM(found=True)

        apply_crm(leads, crm)

        self.assertEqual(review, [])
        self.assertEqual(crm.calls, [("urban_meow", "telegram_username")])
        self.assertEqual(leads[0]["status"], "OK")

    def test_max_never_gets_no_reaction(self) -> None:
        leads, _ = rebuild_leads_and_needs_review([
            _max_event("mid.no_reaction", "ЗАЯВКА. 24.12. 20п. Ксения. 89161234567 Корпоратив.")
        ])

        apply_crm(leads, _FakeCRM(found=True))

        self.assertEqual(leads[0]["channel"], "MAX")
        self.assertNotIn("NO_REACTION", leads[0]["violations"])

    def test_ignore_does_not_create_lead_or_review(self) -> None:
        leads, review = rebuild_leads_and_needs_review([
            _max_event("mid.ignore", "ПРОСМОТР\n17-08 в 16-00 малый зал")
        ])

        self.assertEqual(leads, [])
        self.assertEqual(review, [])

    def test_test_max_message_is_excluded(self) -> None:
        leads, review = rebuild_leads_and_needs_review([
            _max_event("mid.test", "ТЕСТ MAX PRODUCTION")
        ])

        self.assertEqual(leads, [])
        self.assertEqual(review, [])

    def test_needs_review_does_not_create_lead(self) -> None:
        leads, review = rebuild_leads_and_needs_review([
            _max_event("mid.review", "28.08 Виктория 89991234567")
        ])

        self.assertEqual(leads, [])
        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]["status"], "NEEDS_REVIEW")

    def test_crm_required_without_identifier_goes_to_needs_review(self) -> None:
        leads, review = rebuild_leads_and_needs_review([
            _max_event("mid.no_identifier", "ЗАЯВКА. 24.12. 20п. Ксения. Корпоратив.")
        ])

        self.assertEqual(leads, [])
        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]["review_reason"], "Нет надёжного идентификатора для CRM-проверки")

    def test_resolved_host_is_removed_from_existing_needs_review(self) -> None:
        message_id = "mid.ffffbec8f345ffab01a01b06531d70d7"
        leads, review = rebuild_leads_and_needs_review(
            [_max_event(message_id, "ЗАЯВКА.  13.09.   10-15п.  Оксана.  89261860242")],
            existing_needs_review=[
                {
                    "channel": "MAX",
                    "message_id": message_id,
                    "chat_id": CHAT_ID,
                    "sender": {"user_id": 121513620, "username": None, "name": None},
                    "timestamp": 1787159794461,
                    "text": "ЗАЯВКА.  13.09.   10-15п.  Оксана.  89261860242",
                    "review_reason": "ambiguous_contact_or_event_details",
                    "status": "NEEDS_REVIEW",
                }
            ],
        )

        self.assertEqual(len(leads), 1)
        self.assertEqual(review, [])
        self.assertEqual(leads[0]["source"], "Заявки хост")
        self.assertEqual(leads[0]["fields"]["guests_raw"], "10-15п.")
        self.assertEqual(leads[0]["fields"]["guests_min"], 10)
        self.assertEqual(leads[0]["fields"]["guests_max"], 15)
        self.assertIsNone(leads[0]["fields"]["guests_count"])
        self.assertEqual(leads[0]["guests_raw"], "10-15п.")
        self.assertEqual(leads[0]["guests_min"], 10)
        self.assertEqual(leads[0]["guests_max"], 15)
        self.assertIsNone(leads[0]["guests"])

    def test_repeated_message_id_does_not_duplicate_lead(self) -> None:
        event = _max_event("mid.duplicate", "ЗАЯВКА. 24.12. 20п. Ксения. 89161234567 Корпоратив.")

        leads, review = rebuild_leads_and_needs_review([event, dict(event)])

        self.assertEqual(review, [])
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["max"]["message_ids"], ["mid.duplicate"])

    def test_max_same_phone_as_telegram_stays_separate(self) -> None:
        telegram_ts = BASE_TS_MS // 1000
        telegram_event = {
            "type": "telegram_lead",
            "update_id": 1,
            "chat_id": -1001645768111,
            "message_id": 5697,
            "telegram_date": telegram_ts,
            "telegram_date_msk": "2026-08-26T12:39:26+03:00",
            "sender_user_id": 446491725,
            "sender_username": "MarquizBot",
            "sender_name": "MarquizBot",
            "source": "MARQUIZ",
            "ignored": False,
            "ignored_reason": "",
            "lead": {
                "source": "MARQUIZ",
                "name": "дарья",
                "phone_raw": "+79300000118",
                "phone_digits": "79300000118",
                "event_date": "2026-12-18",
                "event_date_raw": "18.12.2026",
                "event_type": "Корпоратив",
                "guests_count": 80,
                "guests_raw": "80",
                "telegram_username": "",
            },
        }
        max_event = _max_event(
            "mid.ffffbec8f345ffab01a03d919b2d0c06",
            "+79300000118 Дарья 18 дек  100 перс корпарат",
        )
        max_event["timestamp"] = (telegram_ts + 30 * 60) * 1000

        leads, review = rebuild_leads_and_needs_review([telegram_event, max_event])

        self.assertEqual(review, [])
        matches = [
            lead
            for lead in leads
            if (lead.get("identifier") or {}).get("value") == "79300000118"
        ]
        self.assertEqual(len(matches), 2)
        self.assertEqual({lead.get("channel") for lead in matches}, {"TELEGRAM", "MAX"})
        max_lead = next(lead for lead in matches if lead.get("channel") == "MAX")
        self.assertIn(
            "mid.ffffbec8f345ffab01a03d919b2d0c06",
            (max_lead.get("max") or {}).get("message_ids", []),
        )
        self.assertEqual(max_lead.get("fields", {}).get("guests_count"), 100)

    def test_report_counts_max_leads_and_needs_review(self) -> None:
        leads, review = rebuild_leads_and_needs_review(
            [
                _max_event("mid.wedwed.report", "WedWed\nНовый запрос с сайта WedWed\nДата: 28.08"),
                _max_event("mid.review.report", "28.08 Виктория 89991234567"),
            ]
        )
        apply_crm(leads, _FakeCRM(found=True))

        report = build_report(leads, "2026-08-19T20:00:00+03:00", needs_review_count=len(review))

        self.assertEqual(report["total_leads"], 1)
        self.assertEqual(report["needs_review"], 1)
        self.assertEqual(report["by_source"], {"WedWed": 1})


def _max_event(message_id: str, text: str) -> dict[str, object]:
    return {
        "type": "max_message_created",
        "source": "MAX",
        "update_type": "message_created",
        "chat_id": CHAT_ID,
        "message_id": message_id,
        "body_mid": message_id,
        "text": text,
        "sender_user_id": 74336871,
        "sender_username": None,
        "sender_name": "Олеся",
        "timestamp": BASE_TS_MS,
    }


class _FakeCRM:
    def __init__(self, found: bool, created_at: int | None = None) -> None:
        self.found = found
        self.created_at = created_at if created_at is not None else BASE_TS_MS // 1000 + 60
        self.calls: list[tuple[str, str]] = []

    def search(self, query: str, lead_id: str, identifier_type: str) -> AmoCRMSearchResult:
        self.calls.append((query, identifier_type))
        if not self.found:
            return AmoCRMSearchResult(found=False)
        return AmoCRMSearchResult(
            found=True,
            entity_type="lead",
            entity_id=42,
            created_at=self.created_at,
            updated_at=self.created_at,
            responsible_user_id=1,
        )


if __name__ == "__main__":
    unittest.main()
