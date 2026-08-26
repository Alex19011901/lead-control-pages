from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.lead_enrichment import enrich_leads_from_events


class LeadEnrichmentTests(unittest.TestCase):
    def test_street_name_is_taken_from_same_line_after_phone(self) -> None:
        message_id = "mid.test-street-name"
        leads = [
            {
                "channel": "MAX",
                "source": "С улицы",
                "identifier": {"type": "phone", "value": "79852815965"},
                "fields": {
                    "name": "Ждут инфу",
                    "phone_digits": "79852815965",
                    "phone_raw": "89852815965",
                },
                "max": {"message_ids": [message_id]},
            }
        ]
        events = [
            {
                "type": "max_message_created",
                "message_id": message_id,
                "text": (
                    "Гости пришли на просмотр, зал показал 2.10.26, "
                    "70чел.тел.89852815965 София\nЖдут инфу."
                ),
            }
        ]

        enrich_leads_from_events(leads, events)

        self.assertEqual(leads[0]["fields"]["name"], "София")
        self.assertEqual(leads[0]["name"], "София")
        self.assertEqual(leads[0]["name_source"], "MESSAGE")

    def test_valid_existing_name_is_not_overwritten(self) -> None:
        leads = [
            {
                "channel": "MAX",
                "source": "С улицы",
                "identifier": {"type": "phone", "value": "79850000000"},
                "fields": {"name": "Анна"},
                "max": {"message_ids": ["mid.1"]},
            }
        ]
        events = [
            {
                "type": "max_message_created",
                "message_id": "mid.1",
                "text": "70чел. тел. 89850000000 София",
            }
        ]

        enrich_leads_from_events(leads, events)

        self.assertEqual(leads[0]["fields"]["name"], "Анна")
        self.assertNotIn("name_source", leads[0])

    def test_event_type_is_inferred_from_original_max_text(self) -> None:
        message_id = "mid.ffffbec8f345ffab01a029858d50628d"
        leads = [
            {
                "channel": "MAX",
                "source": "Заявка с ТГ",
                "message_id": message_id,
                "fields": {
                    "telegram_username": "gelk_a",
                    "guests_count": 25,
                    "event_type": "",
                },
                "max": {"message_ids": [message_id]},
            }
        ]
        events = [
            {
                "type": "max_message_created",
                "message_id": message_id,
                "text": (
                    "ЗАЯВКА\n\n"
                    "Добрый день! Планируем свадьбу на 15.05.2027, "
                    "количество персон 25 человек\n"
                    "Интересует полная информация по условиям\n\n"
                    "@gelk_a"
                ),
            }
        ]

        enrich_leads_from_events(leads, events)

        self.assertEqual(leads[0]["fields"]["event_type"], "Свадьба")
        self.assertEqual(leads[0]["event_type"], "Свадьба")
        self.assertEqual(leads[0]["event_type_source"], "MESSAGE")

    def test_existing_event_type_is_not_overwritten_by_message_inference(self) -> None:
        leads = [
            {
                "channel": "MAX",
                "source": "Заявки хост",
                "event_type": "Корпоратив",
                "fields": {"event_type": "Корпоратив"},
                "max": {"message_ids": ["mid.2"]},
            }
        ]
        events = [
            {
                "type": "max_message_created",
                "message_id": "mid.2",
                "text": "В тексте случайно упомянута свадьба, но тип уже определён",
            }
        ]

        enrich_leads_from_events(leads, events)

        self.assertEqual(leads[0]["event_type"], "Корпоратив")
        self.assertEqual(leads[0]["fields"]["event_type"], "Корпоратив")
        self.assertNotIn("event_type_source", leads[0])


if __name__ == "__main__":
    unittest.main()
