from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.parsers.marquiz import parse_marquiz_message


class MarquizParserTests(unittest.TestCase):
    def test_marquiz_sender_is_full_lead(self) -> None:
        message = {
            "from": {"username": "MarquizBot", "first_name": "MarquizBot"},
            "text": (
                '🎯 Заявка на квиз "Организуйте идеальное мероприятие в ресторане «Светлый»."\n\n'
                "Имя: Александр\n"
                "Телефон: +79036729289\n\n"
                "Какое мероприятие вы планируете?\n"
                "Корпоратив\n\n"
                "Сколько гостей ожидается?\n"
                "150+\n\n"
                "Уточните дату Вашего мероприятия?\n"
                "20.08.2026\n\n"
                "Какой формат мероприятия интересует?\n"
                "Банкет"
            ),
        }

        lead = parse_marquiz_message(message)

        self.assertIsNotNone(lead)
        assert lead is not None
        self.assertEqual(lead["source"], "MARQUIZ")
        self.assertEqual(lead["name"], "Александр")
        self.assertEqual(lead["phone_digits"], "79036729289")
        self.assertEqual(lead["event_type"], "Корпоратив")
        self.assertEqual(lead["event_format"], "Банкет")
        self.assertEqual(lead["event_date"], "2026-08-20")
        self.assertEqual(lead["guests_count"], 150)


if __name__ == "__main__":
    unittest.main()
