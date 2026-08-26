from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.parsers.max_leads import (  # noqa: E402
    HOST,
    IGNORE,
    NEEDS_REVIEW,
    RESTORAN_CAFE,
    SITE_LEAD,
    STREET,
    TG_LEAD,
    TILDA_VERANDA,
    WEDWED,
    classify_max_event,
    classify_max_text,
)


class MaxLeadClassifierTests(unittest.TestCase):
    def test_tilda_veranda(self) -> None:
        result = classify_max_text(
            "\n".join(
                [
                    "TildaForms",
                    "Источник: https://svetliy-moscow.ru/menu",
                    "Имя: Анна",
                    "Телефон: +7 916 111-22-33",
                    "Дата мероприятия: 30/08/2026",
                    "Количество персон: 40",
                ]
            )
        )

        self.assertEqual(result["classification"], TILDA_VERANDA)
        self.assertTrue(result["include_in_stats"])
        self.assertFalse(result["crm_check_required"])
        self.assertEqual(result["business_source"], "Тильда Веранда")
        self.assertEqual(result["fields"]["phone_digits"], "79161112233")
        self.assertEqual(result["fields"]["guests_count"], 40)

    def test_tilda_veranda_plain_site_url(self) -> None:
        result = classify_max_text(
            "\n".join(
                [
                    "Request details:",
                    "Name: Алексей",
                    "Дата: 14-08-2026",
                    "Количество_персон: 2",
                    "Phone: +79166824480",
                    "https://svetliy-moscow.ru/",
                ]
            )
        )

        self.assertEqual(result["classification"], TILDA_VERANDA)
        self.assertFalse(result["crm_check_required"])
        self.assertEqual(result["fields"]["guests_count"], 2)

    def test_wedwed(self) -> None:
        result = classify_max_text("WedWed\nНовый запрос с сайта WedWed\nДата: 28.08")

        self.assertEqual(result["classification"], WEDWED)
        self.assertTrue(result["include_in_stats"])
        self.assertFalse(result["crm_check_required"])
        self.assertEqual(result["business_source"], "WedWed")

    def test_wedwed_order_url(self) -> None:
        result = classify_max_text("https://wedwed.ru/api/viewOrder/?code=60408")

        self.assertEqual(result["classification"], WEDWED)
        self.assertFalse(result["crm_check_required"])

    def test_host_with_header(self) -> None:
        result = classify_max_text("ЗАЯВКА. 24.12. 20п. Ксения. 89161234567 Корпоратив.")

        self.assertEqual(result["classification"], HOST)
        self.assertTrue(result["include_in_stats"])
        self.assertEqual(result["business_source"], "Заявки хост")
        self.assertEqual(result["fields"]["name"], "Ксения")
        self.assertEqual(result["fields"]["phone_digits"], "79161234567")
        self.assertEqual(result["fields"]["event_type"], "Корпоратив")
        self.assertEqual(result["fields"]["guests_raw"], "20п.")
        self.assertEqual(result["fields"]["guests_count"], 20)
        self.assertIsNone(result["fields"]["guests_min"])
        self.assertIsNone(result["fields"]["guests_max"])

    def test_host_with_guest_range_hyphen(self) -> None:
        result = classify_max_text("ЗАЯВКА. 13.09. 10-15п. Оксана. 89261860242")

        self.assertEqual(result["classification"], HOST)
        self.assertEqual(result["fields"]["name"], "Оксана")
        self.assertEqual(result["fields"]["phone_digits"], "79261860242")
        self.assertEqual(result["fields"]["guests_raw"], "10-15п.")
        self.assertEqual(result["fields"]["guests_min"], 10)
        self.assertEqual(result["fields"]["guests_max"], 15)
        self.assertIsNone(result["fields"]["guests_count"])

    def test_host_with_guest_range_en_dash(self) -> None:
        result = classify_max_text("ЗАЯВКА. 14.09. 20–25п. Елена. 89761234567")

        self.assertEqual(result["classification"], HOST)
        self.assertEqual(result["fields"]["guests_raw"], "20–25п.")
        self.assertEqual(result["fields"]["guests_min"], 20)
        self.assertEqual(result["fields"]["guests_max"], 25)
        self.assertIsNone(result["fields"]["guests_count"])

    def test_host_with_guest_up_to(self) -> None:
        result = classify_max_text("ЗАЯВКА. 7.10. До 20п. Маргарита. 89761234567")

        self.assertEqual(result["classification"], HOST)
        self.assertEqual(result["fields"]["name"], "Маргарита")
        self.assertEqual(result["fields"]["guests_raw"], "До 20п.")
        self.assertIsNone(result["fields"]["guests_min"])
        self.assertEqual(result["fields"]["guests_max"], 20)
        self.assertIsNone(result["fields"]["guests_count"])

    def test_host_without_header(self) -> None:
        result = classify_max_text(
            "\n".join(
                [
                    "12.09",
                    "23п свадьба",
                    "8-916-123-45-67",
                    "Радик",
                ]
            )
        )

        self.assertEqual(result["classification"], HOST)
        self.assertEqual(result["fields"]["name"], "Радик")
        self.assertEqual(result["fields"]["guests_count"], 23)
        self.assertEqual(result["fields"]["event_type"], "свадьба")

    def test_host_broad_confirmed_format(self) -> None:
        result = classify_max_text("Заявка 12 сентября 25п. 89267338786 Людмила")

        self.assertEqual(result["classification"], HOST)
        self.assertEqual(result["fields"]["phone_digits"], "79267338786")
        self.assertEqual(result["fields"]["guests_count"], 25)

    def test_street_with_viewing_phrase_and_client_data(self) -> None:
        result = classify_max_text(
            "\n".join(
                [
                    "Гости пришли на просмотр, зал показал",
                    "2.10.26",
                    "70чел. тел. 89851234567",
                    "София",
                    "Ждут инфу.",
                ]
            )
        )

        self.assertEqual(result["classification"], STREET)
        self.assertTrue(result["include_in_stats"])
        self.assertEqual(result["business_source"], "С улицы")
        self.assertEqual(result["fields"]["name"], "София")
        self.assertEqual(result["fields"]["guests_count"], 70)

    def test_tg_lead(self) -> None:
        result = classify_max_text(
            "\n".join(
                [
                    "ЗАЯВКА",
                    "Здравствуйте! Ищу помещение для делового ужина на 27 августа.",
                    "Гостей может быть от 20 до 40.",
                    "@urban_meow",
                ]
            )
        )

        self.assertEqual(result["classification"], TG_LEAD)
        self.assertTrue(result["include_in_stats"])
        self.assertEqual(result["business_source"], "Заявка с ТГ")
        self.assertEqual(result["fields"]["telegram_username"], "urban_meow")

    def test_ignore_confirmed_examples(self) -> None:
        examples = [
            "16.08 веранда п/о\n16.08 вип п/о\n18.08 фуршет 2 эт п/о",
            "Привет! 25.08 есть что-то? Гляньте кто-нибудь",
            "Добрый день!\nВип в 11.00\nКаминка в 18.00",
            "БРОНЬ\n24-08\nДенио 7п 17-00\nкаминный зал",
            "ПРОСМОТР\n17-08 в 16-00 малый зал",
            "7.08 Тоже потеряли очки, Елизавета.\n89031234567",
            "ТЕСТ MAX PRODUCTION",
        ]

        for example in examples:
            with self.subTest(example=example):
                result = classify_max_text(example)
                self.assertEqual(result["classification"], IGNORE)
                self.assertFalse(result["include_in_stats"])

    def test_plain_viewing_word_is_not_automatic_street(self) -> None:
        result = classify_max_text("ПРОСМОТР\n17-08 в 16-00 малый зал")

        self.assertEqual(result["classification"], IGNORE)

    def test_service_message_has_priority_over_host_shape(self) -> None:
        result = classify_max_text("БРОНЬ\n13.09. 10-15п. Оксана. 89261860242")

        self.assertEqual(result["classification"], IGNORE)

    def test_lost_glasses_with_phone_is_ignore(self) -> None:
        result = classify_max_text("7.08 Тоже потеряли очки, Елизавета.\n89031234567")

        self.assertEqual(result["classification"], IGNORE)

    def test_phone_name_only_is_ignore(self) -> None:
        result = classify_max_text("+79197203672 Александра")

        self.assertEqual(result["classification"], IGNORE)
        self.assertEqual(result["review_reason"], "phone_name_without_lead_context")

    def test_table_booking_context_is_ignore(self) -> None:
        for text in ("Запишите меня на 20:00", "8 человек веранда"):
            with self.subTest(text=text):
                result = classify_max_text(text)
                self.assertEqual(result["classification"], IGNORE)
                self.assertFalse(result["include_in_stats"])

    def test_ambiguous_message_needs_review(self) -> None:
        result = classify_max_text("28.08 Виктория 89991234567")

        self.assertEqual(result["classification"], NEEDS_REVIEW)
        self.assertFalse(result["include_in_stats"])
        self.assertEqual(result["review_reason"], "ambiguous_contact_or_event_details")

    def test_needs_review_preserves_max_metadata(self) -> None:
        result = classify_max_event(
            {
                "source": "MAX",
                "chat_id": -71704692523093,
                "message_id": "mid.1",
                "sender_user_id": 123,
                "sender_username": "manager",
                "sender_name": "Олеся",
                "timestamp": 1787159436779,
                "text": "28.08 Виктория 89991234567",
            }
        )

        self.assertEqual(result["classification"], NEEDS_REVIEW)
        self.assertEqual(result["source"], "MAX")
        self.assertEqual(result["chat_id"], -71704692523093)
        self.assertEqual(result["message_id"], "mid.1")
        self.assertEqual(result["sender_user_id"], 123)
        self.assertEqual(result["sender_username"], "manager")
        self.assertEqual(result["sender_name"], "Олеся")
        self.assertEqual(result["timestamp"], 1787159436779)
        self.assertEqual(result["text"], "28.08 Виктория 89991234567")
        self.assertEqual(result["review_reason"], "ambiguous_contact_or_event_details")

    def test_empty_text_image_without_caption_is_ignore(self) -> None:
        result = classify_max_event(
            {
                "source": "MAX",
                "chat_id": -71704692523093,
                "message_id": "mid.image",
                "text": "",
                "has_attachments": True,
                "attachments": [{"type": "image"}],
            }
        )

        self.assertEqual(result["classification"], IGNORE)
        self.assertFalse(result["include_in_stats"])
        self.assertEqual(result["review_reason"], "empty_attachment_without_caption")

    def test_restoran_cafe_photo_lead(self) -> None:
        result = classify_max_event(
            {
                "source": "MAX",
                "chat_id": -71704692523093,
                "message_id": "mid.restoran",
                "text": "Заявка",
                "has_attachments": True,
                "attachments": [{"type": "image"}],
                "attachment_text": "\n".join(
                    [
                        "Заявка на банкет от Restoran.Cafe",
                        "Дата: 30.08.26",
                        "Количество гостей: 50",
                        "Имя клиента: Жасмин",
                        "Тел.: +7 (985) 765 72 98",
                    ]
                ),
            }
        )

        self.assertEqual(result["classification"], RESTORAN_CAFE)
        self.assertEqual(result["display_name"], "Restoran.Cafe")
        self.assertEqual(result["business_source"], "Restoran.Cafe")
        self.assertTrue(result["is_lead"])
        self.assertFalse(result["crm_check_required"])

    def test_site_lead_photo(self) -> None:
        result = classify_max_event(
            {
                "source": "MAX",
                "chat_id": -71704692523093,
                "message_id": "mid.site",
                "text": "Заявка сайт",
                "has_attachments": True,
                "attachments": [{"type": "image"}],
            }
        )

        self.assertEqual(result["classification"], SITE_LEAD)
        self.assertEqual(result["display_name"], "Заявка сайт")
        self.assertEqual(result["business_source"], "Заявка сайт")
        self.assertTrue(result["is_lead"])
        self.assertFalse(result["crm_check_required"])

    def test_empty_text_file_without_caption_is_ignore(self) -> None:
        result = classify_max_event(
            {
                "source": "MAX",
                "chat_id": -71704692523093,
                "message_id": "mid.file",
                "text": "",
                "has_attachments": True,
                "attachments": [{"type": "file", "filename": "Планируемые мероприятия.xlsx"}],
            }
        )

        self.assertEqual(result["classification"], IGNORE)
        self.assertFalse(result["include_in_stats"])

    def test_empty_text_linked_message_without_text_is_ignore(self) -> None:
        result = classify_max_event(
            {
                "source": "MAX",
                "chat_id": -71704692523093,
                "message_id": "mid.linked",
                "text": "",
                "has_linked_or_forwarded_message": True,
            }
        )

        self.assertEqual(result["classification"], IGNORE)
        self.assertFalse(result["include_in_stats"])

    def test_attachment_caption_with_lead_is_classified_by_caption(self) -> None:
        result = classify_max_event(
            {
                "source": "MAX",
                "chat_id": -71704692523093,
                "message_id": "mid.caption",
                "text": "",
                "has_attachments": True,
                "attachments": [
                    {
                        "type": "image",
                        "caption": "ЗАЯВКА. 24.12. 20п. Ксения. 89161234567 Корпоратив.",
                    }
                ],
            }
        )

        self.assertEqual(result["classification"], HOST)
        self.assertEqual(result["fields"]["phone_digits"], "79161234567")
        self.assertEqual(result["text"], "ЗАЯВКА. 24.12. 20п. Ксения. 89161234567 Корпоратив.")


if __name__ == "__main__":
    unittest.main()
