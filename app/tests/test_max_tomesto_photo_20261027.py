from __future__ import annotations

import unittest

from lead_control.max_attachment_ocr import enrich_max_mail_attachments
from lead_control.processor import rebuild_leads_and_needs_review
from lead_control.review_overrides import normalize_decision

CHAT_ID = -71704692523093
PHOTO_ID = "mid.ffffbec8f345ffab01a17e37f95d3575"
CAPTION_ID = "mid.ffffbec8f345ffab01a17e38032a4d59"
OCR_FIXTURE = "\n".join([
    "Банкетная служба ТоМесто",
    "Заявка на банкет №49843",
    "» Дата: 25 сентября 2026 в 17:00",
    "e Имя: Илья Земсков",
    "» Телефон: +7 927 156-00-85",
    "» Число гостей: 60",
    "» Событие: день рождения",
])


class FakeMaxClient:
    def get_messages(self, message_ids):
        return []


class ToMestoPhoto20261027Test(unittest.TestCase):
    def test_photo_and_caption_make_one_to_mesto_lead(self):
        self.assertEqual(normalize_decision("TO_MESTO"), "TO_MESTO")
        photo = {
            "type": "max_message_created",
            "source": "MAX",
            "chat_id": CHAT_ID,
            "message_id": PHOTO_ID,
            "text": "",
            "sender_user_id": 74336871,
            "sender_name": "Al",
            "timestamp": 1793118959965,
            "has_attachments": True,
            "attachment_types": ["image"],
            "attachments": [{"type": "image", "payload": {"photo_id": 48941385831}}],
            "attachment_ocr_text": OCR_FIXTURE,
        }
        caption = {
            "type": "max_message_created",
            "source": "MAX",
            "chat_id": CHAT_ID,
            "message_id": CAPTION_ID,
            "text": "Заявка",
            "sender_user_id": 74336871,
            "sender_name": "Al",
            "timestamp": 1793118962474,
            "has_attachments": False,
        }
        events = [photo, caption]
        self.assertTrue(enrich_max_mail_attachments(events, FakeMaxClient()))
        self.assertEqual(caption["attachment_message_id"], PHOTO_ID)
        self.assertEqual(caption["attachment_text"], OCR_FIXTURE)
        self.assertTrue(photo["mail_attachment_only"])
        self.assertNotIn("attachment_text", photo)

        override = {
            "channel": "MAX",
            "chat_id": CHAT_ID,
            "message_id": CAPTION_ID,
            "decision": "TO_MESTO",
            "decided_at": "2026-10-27T22:00:00+03:00",
            "original_text": "Заявка",
            "photo_message_id": PHOTO_ID,
        }
        pending = {
            "channel": "MAX",
            "source": "MAX",
            "chat_id": CHAT_ID,
            "message_id": CAPTION_ID,
            "status": "NEEDS_REVIEW",
            "review_reason": "unmatched_max_message",
            "sender": {"user_id": 74336871, "name": "Al"},
            "timestamp": 1793118962474,
            "text": "Заявка",
        }
        leads, unresolved = rebuild_leads_and_needs_review(events, [pending], [override])
        self.assertEqual(unresolved, [])
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["source"], "ТоМесто")
        self.assertEqual(leads[0]["category"], "TO_MESTO")
        self.assertEqual(leads[0]["message_id"], CAPTION_ID)
        self.assertEqual(leads[0]["max"]["message_ids"], [CAPTION_ID])
        self.assertEqual(leads[0]["identifier"], {"type": "phone", "value": "79271560085"})
        self.assertEqual(leads[0]["fields"]["name"], "Илья Земсков")
        self.assertEqual(leads[0]["fields"]["guests_count"], 60)
        self.assertEqual(leads[0]["event_date"], "2026-09-25")

    def test_unreadable_photo_still_one_to_mesto_lead_without_invented_details(self):
        caption = {
            "type": "max_message_created",
            "source": "MAX",
            "chat_id": CHAT_ID,
            "message_id": CAPTION_ID,
            "text": "Заявка",
            "sender_user_id": 74336871,
            "sender_name": "Al",
            "timestamp": 1793118962474,
            "has_attachments": True,
            "attachments": [{"type": "image", "payload": {"photo_id": 48941385831}}],
        }
        override = {
            "channel": "MAX",
            "chat_id": CHAT_ID,
            "message_id": CAPTION_ID,
            "decision": "TO_MESTO",
            "decided_at": "2026-10-27T22:00:00+03:00",
            "original_text": "Заявка",
        }
        leads, unresolved = rebuild_leads_and_needs_review([caption], [], [override])
        self.assertEqual(unresolved, [])
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["source"], "ТоМесто")
        self.assertEqual(leads[0]["name"], "")
        self.assertEqual(leads[0]["phone"], "")
        self.assertFalse(leads[0]["crm_required"])


if __name__ == "__main__":
    unittest.main()
