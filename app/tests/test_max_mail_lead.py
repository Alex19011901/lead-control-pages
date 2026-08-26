from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from lead_control.max_attachment_ocr import enrich_max_mail_attachments
from lead_control.max_client import normalize_max_update
from lead_control.max_mail_lead import MAIL_LEAD, classify_max_mail_event, parse_attachment_fields
from lead_control.max_mail_lead_apply import apply_max_mail_leads
from lead_control.processor import rebuild_leads_and_needs_review
from apply_dashboard_mail_source import apply as apply_dashboard_mail_source


MID = "mid.ffffbec8f345ffab01a0342fe62a3fd3"
IMAGE_MID = "mid.ffffbec8f345ffab01a0342fe7d27a90"
OCR = """Имя: Анна Иванова
Телефон: +7 999 123-45-67
Дата мероприятия: 25.09.2026
Количество гостей: 45
Формат мероприятия: Свадьба
Telegram: @anna_event
Email: anna@example.com"""

REAL_OCR = """17:31 98%
Проведение мероприятия
в октябре в ресторане
\"Светлый\"
24 авг. 2026, 17:14
Добрый день.
Хотела бы узнать о возможности и условиях проведения закрытого мероприятия в октябре в ресторане «Светлый».
Дата 14 октября, но рассматриваем и 13,15 октября.
Время: 17:30-23:00
Кол-во гостей: до 150 чел
Алена Тимофеева
Руководитель по координации мероприятий
Издательский Дом «Коммерсантъ»
Моб. +7 (963) 669-88-19
timofeeva_a@kommersant.ru
служебный мусор 30-23"""


def mail_event() -> dict:
    return {
        "type": "max_message_created",
        "source": "MAX",
        "update_type": "message_created",
        "chat_id": -71704692523093,
        "message_id": MID,
        "body_mid": MID,
        "text": "Заявка сайт:",
        "has_attachments": True,
        "attachment_types": ["image"],
        "attachments": [{"type": "image", "payload": {"url": "https://example.test/x.jpg"}}],
        "attachment_ocr_text": OCR,
        "attachment_text": OCR,
        "attachment_message_id": IMAGE_MID,
        "sender_user_id": 74336871,
        "sender_name": "Al",
        "sender_username": None,
        "timestamp": 1787581949482,
    }


class FakeMaxClient:
    def get_messages(self, message_ids):
        return []


class MaxMailLeadTests(unittest.TestCase):
    def test_image_site_header_is_mail_lead(self):
        result = classify_max_mail_event(mail_event())
        self.assertIsNotNone(result)
        self.assertEqual(result["classification"], MAIL_LEAD)
        self.assertEqual(result["business_source"], "ЗАЯВКА ПОЧТА")
        self.assertTrue(result["crm_check_required"])

    def test_attachment_fields_are_extracted(self):
        fields = parse_attachment_fields(OCR)
        self.assertEqual(fields["name"], "Анна Иванова")
        self.assertEqual(fields["phone_digits"], "79991234567")
        self.assertEqual(fields["event_date_raw"], "25.09.2026")
        self.assertEqual(fields["guests_count"], 45)
        self.assertEqual(fields["event_type"], "Свадьба")
        self.assertEqual(fields["telegram_username"], "anna_event")
        self.assertEqual(fields["email"], "anna@example.com")

    def test_real_ocr_extracts_signature_and_explicit_event_date(self):
        fields = parse_attachment_fields(REAL_OCR)
        self.assertEqual(fields["name"], "Алена Тимофеева")
        self.assertEqual(fields["phone_digits"], "79636698819")
        self.assertEqual(fields["event_date_raw"].lower(), "14 октября")
        self.assertEqual(fields["guests_count"], 150)
        self.assertEqual(fields["guests_max"], 150)
        self.assertEqual(fields["email"], "timofeeva_a@kommersant.ru")
        self.assertNotEqual(fields["event_date_raw"], "30-23")

    def test_mail_lead_does_not_stay_in_needs_review(self):
        event = mail_event()
        existing = [{
            "channel": "MAX",
            "chat_id": event["chat_id"],
            "message_id": MID,
            "source": "MAX",
            "status": "NEEDS_REVIEW",
            "text": "Заявка сайт:",
        }]
        leads, needs_review = rebuild_leads_and_needs_review([event], existing_needs_review=existing)
        apply_max_mail_leads(leads, [event])
        self.assertEqual(len(leads), 1)
        self.assertFalse(any(str(item.get("message_id")) == MID for item in needs_review))
        lead = leads[0]
        self.assertEqual(lead["source"], "ЗАЯВКА ПОЧТА")
        self.assertEqual(lead["category"], "ЗАЯВКА ПОЧТА")
        self.assertEqual(lead["identifier"], {"type": "phone", "value": "79991234567"})
        self.assertEqual(lead["fields"]["attachment_ocr_text"], OCR)
        self.assertEqual(lead["fields"]["guests_count"], 45)

    def test_separate_image_message_does_not_create_duplicate_lead(self):
        header = {
            "type": "max_message_created",
            "source": "MAX",
            "update_type": "message_created",
            "chat_id": -71704692523093,
            "message_id": MID,
            "body_mid": MID,
            "text": "Заявка сайт:",
            "has_attachments": False,
            "sender_user_id": 74336871,
            "sender_name": "Al",
            "sender_username": None,
            "timestamp": 1787581949482,
        }
        image = {
            "type": "max_message_created",
            "source": "MAX",
            "update_type": "message_created",
            "chat_id": -71704692523093,
            "message_id": IMAGE_MID,
            "body_mid": IMAGE_MID,
            "text": "",
            "has_attachments": True,
            "attachment_types": ["image"],
            "attachments": [{"type": "image", "payload": {"photo_id": 123}}],
            "attachment_ocr_text": REAL_OCR,
            "attachment_text": REAL_OCR,
            "sender_user_id": 74336871,
            "sender_name": "Al",
            "sender_username": None,
            "timestamp": 1787581949906,
        }
        events = [header, image]
        self.assertTrue(enrich_max_mail_attachments(events, FakeMaxClient()))
        self.assertEqual(header["attachment_message_id"], IMAGE_MID)
        self.assertEqual(header["attachment_ocr_text"], REAL_OCR)
        self.assertTrue(image["mail_attachment_only"])
        self.assertNotIn("attachment_text", image)

        leads, needs_review = rebuild_leads_and_needs_review(events, existing_needs_review=[])
        apply_max_mail_leads(leads, events)
        self.assertEqual(len(leads), 1)
        self.assertEqual(needs_review, [])
        self.assertEqual(leads[0]["source"], "ЗАЯВКА ПОЧТА")
        self.assertEqual(leads[0]["identifier"], {"type": "phone", "value": "79636698819"})

    def test_missing_ocr_fields_still_stays_mail_lead(self):
        event = mail_event()
        event["attachment_ocr_text"] = "не удалось уверенно распознать поля"
        event["attachment_text"] = event["attachment_ocr_text"]
        leads, needs_review = rebuild_leads_and_needs_review([event], existing_needs_review=[])
        apply_max_mail_leads(leads, [event])
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["source"], "ЗАЯВКА ПОЧТА")
        self.assertFalse(leads[0]["crm_required"])
        self.assertEqual(needs_review, [])

    def test_normalizer_preserves_attachment_metadata(self):
        update = {
            "update_type": "message_created",
            "timestamp": 1787581949906,
            "message": {
                "recipient": {"chat_id": -71704692523093},
                "sender": {"user_id": 74336871, "name": "Al"},
                "body": {
                    "mid": "mid.image",
                    "text": "",
                    "attachments": [{"type": "image", "payload": {"url": "https://example.test/x.jpg", "token": "t"}}],
                },
            },
        }
        event = normalize_max_update(update)
        self.assertTrue(event["has_attachments"])
        self.assertEqual(event["attachment_types"], ["image"])
        self.assertEqual(event["attachments"][0]["payload"]["url"], "https://example.test/x.jpg")

    def test_existing_host_category_is_not_changed(self):
        event = {
            "type": "max_message_created",
            "source": "MAX",
            "update_type": "message_created",
            "chat_id": -71704692523093,
            "message_id": "mid.host",
            "text": "ЗАЯВКА. 25.09. 45п. Анна. 89991234567. Свадьба.",
            "sender_user_id": 121513620,
            "sender_name": "Елена",
            "timestamp": 1787581949482,
        }
        leads, _ = rebuild_leads_and_needs_review([event])
        before = (leads[0]["source"], leads[0]["category"])
        apply_max_mail_leads(leads, [event])
        self.assertEqual((leads[0]["source"], leads[0]["category"]), before)

    def test_dashboard_counts_mail_source_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "view.json"
            path.write_text(json.dumps({
                "ranges": {"all": {"source": {"Заявка почта": 1, "Заявка сайт": 2, "САЙТ ТИЛЬДА": 3}}},
                "latest": [{"source": "Заявка почта"}],
                "not_entered": [],
                "feedback": [],
            }, ensure_ascii=False), encoding="utf-8")
            apply_dashboard_mail_source(path)
            view = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(view["ranges"]["all"]["source"]["ЗАЯВКА ПОЧТА"], 1)
            self.assertEqual(view["ranges"]["all"]["source"]["Заявка сайт"], 2)
            self.assertEqual(view["ranges"]["all"]["source"]["САЙТ ТИЛЬДА"], 3)
            self.assertEqual(view["latest"][0]["source"], "ЗАЯВКА ПОЧТА")


if __name__ == "__main__":
    unittest.main()
