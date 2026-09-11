from __future__ import annotations

import unittest

from lead_control.parsers.max_leads import HOST, classify_max_text


class MaxExplicitClientNameTest(unittest.TestCase):
    def test_menya_zovut_has_priority_over_greeting(self) -> None:
        text = (
            "ЗАЯВКА\n\n"
            "Добрый день. Меня зовут Юлия. Скажите, пожалуйста, можно ли "
            "провести выпускной в банкетным зале Светлый?\n"
            "+7 903 669-28-48"
        )
        result = classify_max_text(text)
        self.assertEqual(result["classification"], HOST)
        self.assertEqual(result["fields"]["phone_digits"], "79036692848")
        self.assertEqual(result["fields"]["name"], "Юлия")


if __name__ == "__main__":
    unittest.main()
