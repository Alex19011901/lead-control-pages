from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.wedwed_enrichment import enrich_wedwed_leads, parse_wedwed_request_page


HTML = """
<div class="data-row"><h3 class="data-label">Дата мероприятия:</h3><p class="data-value">18.10.2026</p></div>
<div class="data-row"><h3 class="data-label">Количество гостей:</h3><p class="data-value">20</p></div>
<div class="data-row"><h3 class="data-label">Имя:</h3><p class="data-value">Василиса</p></div>
<div class="data-row"><h3 class="data-label">Телефон:</h3><p class="data-value"><a href="tel:+79256214274">+7 (925) 621-42-74</a></p></div>
"""


class WedWedEnrichmentTests(unittest.TestCase):
    def test_page_parser_extracts_crm_fields(self) -> None:
        data = parse_wedwed_request_page(HTML)
        self.assertEqual(data["event_date_raw"], "18.10.2026")
        self.assertEqual(data["guests_count"], 20)
        self.assertEqual(data["name"], "Василиса")
        self.assertEqual(data["phone_raw"], "+7 (925) 621-42-74")

    def test_wedwed_link_promotes_lead_to_crm_check(self) -> None:
        message_id = "mid.test-wedwed"
        leads = [{
            "source": "WedWed",
            "category": "WEDWED",
            "channel": "MAX",
            "message_id": message_id,
            "max": {"message_ids": [message_id]},
            "identifier": {"type": "max_message", "value": message_id},
            "fields": {"source": "WedWed", "category": "WEDWED"},
            "crm_required": False,
            "crm_check_status": "NOT_REQUIRED",
        }]
        events = [{
            "type": "max_message_created",
            "message_id": message_id,
            "text": "WedWed\nНовый запрос с сайта WedWed!\nДетали тут - https://wedwed.ru/l/DaJIJLh",
        }]

        enrich_wedwed_leads(leads, events, fetch_html=lambda _url: HTML)

        lead = leads[0]
        self.assertTrue(lead["crm_required"])
        self.assertEqual(lead["crm_check_status"], "PENDING")
        self.assertEqual(lead["identifier"], {"type": "phone", "value": "79256214274"})
        self.assertEqual(lead["name"], "Василиса")
        self.assertEqual(lead["guests"], 20)
        self.assertEqual(lead["event_date"], "2026-10-18")

    def test_wedwed_date_with_note_is_normalized(self) -> None:
        page = HTML.replace("18.10.2026", "10.10.2026 Рассматриваю и другие даты")
        message_id = "mid.date-note"
        leads = [{
            "source": "WedWed", "channel": "MAX", "message_id": message_id,
            "max": {"message_ids": [message_id]}, "fields": {}, "crm_required": False,
            "identifier": {"type": "max_message", "value": message_id},
        }]
        events = [{"type": "max_message_created", "message_id": message_id,
                   "text": "Новый запрос с сайта WedWed! https://wedwed.ru/l/dateNote"}]
        enrich_wedwed_leads(leads, events, fetch_html=lambda _url: page)
        self.assertEqual(leads[0]["event_date"], "2026-10-10")
        self.assertEqual(leads[0]["fields"]["event_date_raw"], "10.10.2026 Рассматриваю и другие даты")

    def test_wedwed_without_phone_stays_not_required(self) -> None:
        message_id = "mid.no-phone"
        leads = [{
            "source": "WedWed",
            "channel": "MAX",
            "message_id": message_id,
            "max": {"message_ids": [message_id]},
            "identifier": {"type": "max_message", "value": message_id},
            "fields": {},
            "crm_required": False,
        }]
        events = [{
            "type": "max_message_created",
            "message_id": message_id,
            "text": "Новый запрос с сайта WedWed! https://wedwed.ru/l/noPhone",
        }]
        page = '<h3 class="data-label">Имя:</h3><p class="data-value">Анна</p>'

        enrich_wedwed_leads(leads, events, fetch_html=lambda _url: page)

        self.assertFalse(leads[0]["crm_required"])
        self.assertEqual(leads[0]["identifier"]["type"], "max_message")


if __name__ == "__main__":
    unittest.main()
