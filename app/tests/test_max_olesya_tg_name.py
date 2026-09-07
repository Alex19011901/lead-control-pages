from __future__ import annotations

import unittest

from lead_control.parsers.max_leads import TG_LEAD, classify_max_event


class OlesyaTelegramLeadNameTest(unittest.TestCase):
    def test_phone_followed_by_name_is_preserved(self) -> None:
        text = (
            "ЗАЯВКА\n\n"
            "Здравствуйте))\n\n"
            "На 13 ноября нужен зал под корпоратив порядка 200 м²\n"
            "Тип питания - фуршет\n"
            "100 гостей\n\n"
            "Что можете из своих предложить и цены сразу, пожалуйста\n\n"
            "+7 915 158-84-06\n"
            "Михаил"
        )
        result = classify_max_event({
            "source": "MAX",
            "sender_user_id": 48906491,
            "sender_name": "Олеся",
            "text": text,
            "timestamp": 1788777009569,
            "message_id": "mid.test-mikhail",
        })
        self.assertEqual(result["classification"], TG_LEAD)
        self.assertEqual(result["display_name"], "Заявка с ТГ")
        self.assertEqual(result["fields"]["phone_digits"], "79151588406")
        self.assertEqual(result["fields"]["name"], "Михаил")
        self.assertEqual(result["fields"]["guests_count"], 100)


if __name__ == "__main__":
    unittest.main()
