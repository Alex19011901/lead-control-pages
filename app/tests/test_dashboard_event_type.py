from __future__ import annotations

import unittest

from scripts.build_dashboard_snapshot import event_type_for_lead


class DashboardEventTypeTests(unittest.TestCase):
    def test_verified_tilda_lead_with_discarded_raw_text_is_wedding(self) -> None:
        lead = {
            "source": "САЙТ ТИЛЬДА",
            "identifier": {"type": "phone", "value": "79161553602"},
            "fields": {"event_type": ""},
        }
        self.assertEqual(event_type_for_lead(lead), "Свадьба")

    def test_freeform_description_is_read_semantically(self) -> None:
        lead = {
            "source": "Заявка с ТГ",
            "identifier": {"type": "telegram_username", "value": "example"},
            "fields": {
                "event_type": "",
                "description": "10 сентября. Клиентский вечер, 60 гостей. Ресторан в центре.",
            },
        }
        self.assertEqual(event_type_for_lead(lead), "Клиентский вечер")


if __name__ == "__main__":
    unittest.main()
