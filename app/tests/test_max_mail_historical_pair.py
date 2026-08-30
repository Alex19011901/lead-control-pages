from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.max_attachment_ocr import enrich_max_mail_attachments
from lead_control.max_mail_lead_apply import apply_max_mail_leads
from lead_control.processor import rebuild_leads_and_needs_review


MID = "mid.ffffbec8f345ffab01a0342fe62a3fd3"
IMAGE_MID = "mid.ffffbec8f345ffab01a0342fe7d27a90"
OCR = """Проведение мероприятия
в октябре в ресторане "Светлый"
Ориентировочно до 150 чел
Алена Тимофеева
Руководитель по координации мероприятий
Моб. +7 (963) 669-88-19
timofeeva_a@kommersant.ru"""


class FakeMaxClient:
    def get_messages(self, message_ids):
        return []


class HistoricalPairTests(unittest.TestCase):
    def test_mail_header_pairs_next_image_and_builds_lead(self):
        header_mid = "mid.mail.header"
        image_mid = "mid.mail.image"
        copied_attachment = {"type": "image", "payload": {"photo_id": 456}}
        header = {
            "type": "max_message_created",
            "source": "MAX",
            "update_type": "message_created",
            "chat_id": -71704692523093,
            "message_id": header_mid,
            "body_mid": header_mid,
            "text": "Заявка почта:",
            "has_attachments": False,
            "attachments": [],
            "sender_user_id": 74336871,
            "sender_name": "Al",
            "timestamp": 1788111119016,
        }
        image = {
            "type": "max_message_created",
            "source": "MAX",
            "update_type": "message_created",
            "chat_id": -71704692523093,
            "message_id": image_mid,
            "body_mid": image_mid,
            "text": "",
            "has_attachments": True,
            "attachment_types": ["image"],
            "attachments": [copied_attachment],
            "attachment_ocr_text": OCR,
            "sender_user_id": 74336871,
            "sender_name": "Al",
            "timestamp": 1788111120641,
        }
        events = [header, image]

        self.assertTrue(enrich_max_mail_attachments(events, FakeMaxClient()))
        self.assertEqual(header["attachment_message_id"], image_mid)
        self.assertEqual(header["attachment_ocr_text"], OCR)
        self.assertTrue(image["mail_attachment_only"])
        self.assertEqual(image["paired_mail_header_message_id"], header_mid)

        leads, needs_review = rebuild_leads_and_needs_review(events, existing_needs_review=[])
        apply_max_mail_leads(leads, events)

        self.assertEqual(needs_review, [])
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["source"], "ЗАЯВКА ПОЧТА")
        self.assertEqual(leads[0]["fields"]["name"], "Алена Тимофеева")
        self.assertEqual(leads[0]["identifier"], {"type": "phone", "value": "79636698819"})

    def test_already_enriched_header_still_marks_real_image_as_attachment_only(self):
        copied_attachment = {"type": "image", "payload": {"photo_id": 123}}
        header = {
            "type": "max_message_created",
            "source": "MAX",
            "update_type": "message_created",
            "chat_id": -71704692523093,
            "message_id": MID,
            "body_mid": MID,
            "text": "Заявка сайт:",
            "has_attachments": True,
            "attachment_types": ["image"],
            "attachments": [copied_attachment],
            "attachment_message_id": IMAGE_MID,
            "attachment_ocr_text": OCR,
            "attachment_text": OCR,
            "sender_user_id": 74336871,
            "sender_name": "Al",
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
            "attachments": [copied_attachment],
            "attachment_ocr_text": OCR,
            "attachment_text": OCR,
            "sender_user_id": 74336871,
            "sender_name": "Al",
            "timestamp": 1787581949906,
        }
        events = [header, image]
        self.assertTrue(enrich_max_mail_attachments(events, FakeMaxClient()))
        self.assertTrue(image["mail_attachment_only"])
        self.assertEqual(image["paired_mail_header_message_id"], MID)
        self.assertNotIn("attachment_text", image)

        leads, needs_review = rebuild_leads_and_needs_review(events, existing_needs_review=[])
        apply_max_mail_leads(leads, events)
        self.assertEqual(needs_review, [])
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["source"], "ЗАЯВКА ПОЧТА")
        self.assertEqual(leads[0]["fields"]["name"], "Алена Тимофеева")
        self.assertEqual(leads[0]["identifier"], {"type": "phone", "value": "79636698819"})


if __name__ == "__main__":
    unittest.main()
