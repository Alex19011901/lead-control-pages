from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.event_type import infer_event_type, normalize_event_type


class EventTypeInferenceTests(unittest.TestCase):
    def test_wedding_from_wedding_url_and_utm(self) -> None:
        text = (
            "https://moscowbanket.ru/weddings/#dati\n"
            "UTM campaign: Svadba_poisk\n"
            "UTM term: где отметить свадьбу в москве"
        )
        self.assertEqual(infer_event_type(text), "Свадьба")

    def test_client_evening_from_freeform_request(self) -> None:
        self.assertEqual(
            infer_event_type("10 сентября. Клиентский вечер, 60 гостей. Ресторан в центре."),
            "Клиентский вечер",
        )

    def test_gala_dinner_from_freeform_request(self) -> None:
        self.assertEqual(
            infer_event_type("Нужно красивое пространство для благотворительного гала-ужина."),
            "Гала-ужин",
        )

    def test_generic_bankety_utm_is_not_misclassified_as_banquet(self) -> None:
        self.assertEqual(
            infer_event_type("UTM campaign: Bankety_poisk_konversii\nhttps://moscowbanket.ru/#contact"),
            "",
        )

    def test_50_letie_is_jubilee(self) -> None:
        self.assertEqual(
            infer_event_type("Ищем ресторан на 50-летие, 40 гостей"),
            "Юбилей",
        )

    def test_legacy_letie_label_is_jubilee(self) -> None:
        self.assertEqual(normalize_event_type("-летие"), "Юбилей")

    def test_birthday_and_dr_are_merged_into_jubilee(self) -> None:
        self.assertEqual(normalize_event_type("ДР"), "Юбилей")
        self.assertEqual(normalize_event_type("День рождения"), "Юбилей")
        self.assertEqual(normalize_event_type("birthday"), "Юбилей")


if __name__ == "__main__":
    unittest.main()
