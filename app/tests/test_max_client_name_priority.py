from __future__ import annotations

import unittest

from lead_control.parsers.max_leads import HOST, classify_max_event


class MaxClientNamePriorityTest(unittest.TestCase):
    def test_client_name_after_phone_beats_period_words_and_sender_name(self) -> None:
        result = classify_max_event({
            "source": "MAX",
            "sender_user_id": 205529129,
            "sender_name": "Святослав",
            "text": "Заявка:\nКонец декабрь, 150чел.89688610725 Оксана",
            "timestamp": 1788784272436,
            "message_id": "mid.test-oksana",
        })
        self.assertEqual(result["classification"], HOST)
        self.assertEqual(result["fields"]["name"], "Оксана")
        self.assertEqual(result["fields"]["phone_digits"], "79688610725")
        self.assertEqual(result["fields"]["guests_count"], 150)

    def test_client_name_before_phone_still_works(self) -> None:
        result = classify_max_event({
            "source": "MAX",
            "sender_user_id": 297178198,
            "sender_name": "David Romanov",
            "text": "Заявка\n1 октября\n80-100п.\nАлина 89509579558",
            "timestamp": 1788430500003,
            "message_id": "mid.test-alina",
        })
        self.assertEqual(result["classification"], HOST)
        self.assertEqual(result["fields"]["name"], "Алина")
        self.assertEqual(result["fields"]["phone_digits"], "79509579558")


if __name__ == "__main__":
    unittest.main()
