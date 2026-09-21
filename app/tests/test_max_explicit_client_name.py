from __future__ import annotations

import unittest

from lead_control.parsers.max_leads import HOST, TG_LEAD, classify_max_event, classify_max_text


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

    def test_eto_elena_has_priority_over_greeting(self) -> None:
        text = (
            "ЗАЯВКА\n\n"
            "Добрый день!\n"
            "Это Елена, клуб Мафия Драйв и компания КорпИгра.\n"
            "Есть запрос: 23 или 24 декабря.\n"
            "Банкет 200-220 человек.\n"
            "+79067177838\n"
            "@elenamalanyina"
        )
        result = classify_max_event({
            "source": "MAX",
            "sender_user_id": 48906491,
            "sender_name": "Олеся",
            "text": text,
            "timestamp": 1789473374804,
            "message_id": "mid.test-elena",
        })
        self.assertEqual(result["classification"], TG_LEAD)
        self.assertEqual(result["fields"]["phone_digits"], "79067177838")
        self.assertEqual(result["fields"]["name"], "Елена")

    def test_ya_and_s_vami_are_explicit_names(self) -> None:
        variants = (
            ("Я Мария, организатор мероприятия.", "Мария"),
            ("С вами Ольга, агентство событий.", "Ольга"),
        )
        for introduction, expected_name in variants:
            with self.subTest(introduction=introduction):
                text = (
                    "ЗАЯВКА\n"
                    "Добрый день!\n"
                    f"{introduction}\n"
                    "24 декабря нужен зал на корпоратив, 35 гостей.\n"
                    "+79060000000\n"
                    "@client_test"
                )
                result = classify_max_event({
                    "source": "MAX",
                    "sender_user_id": 48906491,
                    "sender_name": "Олеся",
                    "text": text,
                    "timestamp": 1789473374804,
                    "message_id": f"mid.test-{expected_name}",
                })
                self.assertEqual(result["classification"], TG_LEAD)
                self.assertEqual(result["fields"]["name"], expected_name)

    def test_greeting_and_sentence_start_are_not_guessed_as_name(self) -> None:
        text = (
            "ЗАЯВКА\n"
            "Добрый день!\n"
            "Нужен зал на 24 декабря для корпоратива.\n"
            "35 гостей.\n"
            "+79060000000\n"
            "@client_test"
        )
        result = classify_max_event({
            "source": "MAX",
            "sender_user_id": 48906491,
            "sender_name": "Олеся",
            "text": text,
            "timestamp": 1789473374804,
            "message_id": "mid.test-no-name",
        })
        self.assertEqual(result["classification"], TG_LEAD)
        self.assertEqual(result["fields"]["name"], "")


if __name__ == "__main__":
    unittest.main()
