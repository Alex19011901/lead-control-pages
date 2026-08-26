from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.parsers.tilda import parse_tilda_message


class TildaParserTests(unittest.TestCase):
    def test_tilda_fixture_is_parsed_without_guessing_event_type(self) -> None:
        updates = json.loads((ROOT / "tests/fixtures/telegram_tilda_reaction.json").read_text(encoding="utf-8"))
        lead = parse_tilda_message(updates[0]["message"])

        self.assertIsNotNone(lead)
        assert lead is not None
        self.assertEqual(lead["source"], "САЙТ ТИЛЬДА")
        self.assertEqual(lead["phone_digits"], "79999999999")
        self.assertEqual(lead["guests_count"], 14)
        self.assertEqual(lead["event_date"], "2026-08-30")
        self.assertEqual(lead["event_type"], "")
        self.assertEqual(lead["ignored_reason"], "test_phone")

    def test_tildaforms_sender_is_source_even_without_tilda_in_text(self) -> None:
        message = {
            "from": {"username": "TildaFormsBot", "first_name": "TildaForms"},
            "text": (
                "Содержание заявки:\n"
                "name: Мурадин\n"
                "phone: 9771873844\n"
                "Input: 200\n"
                "Date: 25-12-2026\n"
                "Checkbox: yes\n\n"
                "https://moscowbanket.ru/#contact"
            ),
        }

        lead = parse_tilda_message(message)

        self.assertIsNotNone(lead)
        assert lead is not None
        self.assertEqual(lead["source"], "САЙТ ТИЛЬДА")
        self.assertEqual(lead["phone_digits"], "9771873844")
        self.assertEqual(lead["guests_count"], 200)
        self.assertEqual(lead["event_date"], "2026-12-25")

    def test_tilda_wedding_is_inferred_from_page_and_utm_campaign(self) -> None:
        message = {
            "from": {"username": "TildaFormsBot", "first_name": "TildaForms"},
            "text": (
                "Содержание заявки:\n"
                "Name: Юлия\n"
                "Phone: +79161553602\n"
                "Дата: 21-12-2026\n"
                "Кол-во_гостей: 50\n"
                "Checkbox: yes\n\n"
                "Дополнительная информация:\n"
                "Код заявки: 2925975:8619318402\n"
                "Код блока: rec1193957381\n"
                "https://moscowbanket.ru/weddings/#dati\n"
                "UTM source: yandex_direct\n"
                "UTM medium: cpc\n"
                "UTM campaign: Svadba_poisk\n"
                "UTM term: где отметить свадьбу в москве\n"
                "-----"
            ),
        }

        lead = parse_tilda_message(message)

        self.assertIsNotNone(lead)
        assert lead is not None
        self.assertEqual(lead["phone_digits"], "79161553602")
        self.assertEqual(lead["guests_count"], 50)
        self.assertEqual(lead["event_type"], "Свадьба")
        self.assertIn("Svadba_poisk", lead["description"])


if __name__ == "__main__":
    unittest.main()
