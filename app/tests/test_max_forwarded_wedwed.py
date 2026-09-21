from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.max_forwarded import enrich_incomplete_forwarded_messages
from lead_control.parsers.max_leads import WEDWED, classify_max_event
from lead_control.wedwed_enrichment import enrich_wedwed_leads


HTML = """
<div class="data-row"><h3 class="data-label">Дата мероприятия:</h3><p class="data-value">18.10.2026</p></div>
<div class="data-row"><h3 class="data-label">Количество гостей:</h3><p class="data-value">20</p></div>
<div class="data-row"><h3 class="data-label">Имя:</h3><p class="data-value">Василиса</p></div>
<div class="data-row"><h3 class="data-label">Телефон:</h3><p class="data-value"><a href="tel:+79256214274">+7 (925) 621-42-74</a></p></div>
"""


class FakeMaxClient:
    def get_messages(self, message_ids: list[str]):
        self.message_ids = message_ids
        return [{
            "body": {"mid": message_ids[0], "text": ""},
            "linked_message": {
                "body": {
                    "text": "",
                    "attachments": [{
                        "type": "share",
                        "title": "Заявка от пользователя Wedwed",
                        "description": "Новый запрос с сайта WedWed!",
                        "payload": {"url": "https://wedwed.ru/l/4zGkilt"},
                    }],
                },
            },
        }]


class MaxForwardedWedWedTests(unittest.TestCase):
    def test_empty_forwarded_wedwed_is_recovered_and_enriched(self) -> None:
        message_id = "mid.forwarded-wedwed"
        event = {
            "type": "max_message_created",
            "source": "MAX",
            "update_type": "message_created",
            "chat_id": -71704692523093,
            "message_id": message_id,
            "body_mid": message_id,
            "text": "",
            "has_attachments": False,
            "has_linked_or_forwarded_message": True,
            "sender_user_id": 48906491,
            "sender_name": "Олеся",
            "timestamp": 1789231870924,
        }
        client = FakeMaxClient()

        changed = enrich_incomplete_forwarded_messages([event], client)

        self.assertTrue(changed)
        self.assertEqual(client.message_ids, [message_id])
        recovered = event["linked_or_forwarded_text"]
        self.assertIn("Новый запрос с сайта WedWed!", recovered)
        self.assertIn("https://wedwed.ru/l/4zGkilt", recovered)

        classification = classify_max_event(event)
        self.assertEqual(classification["classification"], WEDWED)
        self.assertTrue(classification["is_lead"])

        lead = {
            "source": "WedWed",
            "category": "WEDWED",
            "channel": "MAX",
            "message_id": message_id,
            "max": {"message_ids": [message_id]},
            "identifier": {"type": "max_message", "value": message_id},
            "fields": {"source": "WedWed", "category": "WEDWED"},
            "crm_required": False,
            "crm_check_status": "NOT_REQUIRED",
        }
        enrich_wedwed_leads([lead], [event], fetch_html=lambda _url: HTML)

        self.assertEqual(lead["identifier"], {"type": "phone", "value": "79256214274"})
        self.assertEqual(lead["name"], "Василиса")
        self.assertEqual(lead["guests"], 20)
        self.assertEqual(lead["event_date"], "2026-10-18")
        self.assertEqual(lead["wedwed_url"], "https://wedwed.ru/l/4zGkilt")


if __name__ == "__main__":
    unittest.main()
