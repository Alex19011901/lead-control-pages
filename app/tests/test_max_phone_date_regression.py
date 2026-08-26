import unittest

from lead_control.normalize import normalize_phone
from lead_control.parsers.max_leads import HOST, classify_max_text


class MaxPhoneDateRegressionTest(unittest.TestCase):
    def test_event_date_and_guest_count_are_not_a_phone(self) -> None:
        text = "Заявка\n26.06.2027\n25п.\n89099785464 Варвара"

        result = classify_max_text(text)

        self.assertEqual(result["classification"], HOST)
        self.assertEqual(result["fields"]["event_date_raw"], "26.06.2027")
        self.assertEqual(result["fields"]["guests_count"], 25)
        self.assertEqual(result["fields"]["name"], "Варвара")
        self.assertEqual(result["fields"]["phone_raw"], "89099785464")
        self.assertEqual(result["fields"]["phone_digits"], "79099785464")

    def test_date_plus_numeric_metadata_is_rejected_as_phone(self) -> None:
        self.assertEqual(normalize_phone("26.06.2027\n25"), "")


if __name__ == "__main__":
    unittest.main()
