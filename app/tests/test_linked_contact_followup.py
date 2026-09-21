from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.linked_contact_followup import remove_linked_contact_followup_leads


class LinkedContactFollowupTests(unittest.TestCase):
    def test_linked_personal_phone_followup_is_not_a_new_lead(self) -> None:
        original_message_id = "mid.original-julia"
        followup_message_id = "mid.ffffbec8f345ffab01a0aa39e1323282"
        leads = [
            {
                "channel": "MAX",
                "source": "Заявки хост",
                "message_id": original_message_id,
                "identifier": {"type": "phone", "value": "79652276267"},
                "name": "Юлия",
                "fields": {
                    "name": "Юлия",
                    "guests_raw": "6-8",
                    "event_date_raw": "29.12",
                },
                "max": {"message_ids": [original_message_id]},
            },
            {
                "channel": "MAX",
                "source": "Заявки хост",
                "message_id": followup_message_id,
                "identifier": {"type": "phone", "value": "79266560108"},
                "name": "",
                "fields": {},
                "max": {"message_ids": [followup_message_id]},
            },
        ]
        events = [
            {
                "type": "max_message_created",
                "source": "MAX",
                "message_id": followup_message_id,
                "has_linked_or_forwarded_message": True,
                "timestamp": 1789562315058,
                "text": "позвонили ещё раз, дали личный номер для связи. 89266560108",
            }
        ]

        removed = remove_linked_contact_followup_leads(leads, events)

        self.assertEqual(removed, 1)
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["name"], "Юлия")
        self.assertEqual(leads[0]["identifier"]["value"], "79652276267")

    def test_explicit_linked_application_is_never_removed(self) -> None:
        message_id = "mid.real-linked-lead"
        leads = [
            {
                "channel": "MAX",
                "source": "Заявки хост",
                "message_id": message_id,
                "identifier": {"type": "phone", "value": "79266560108"},
                "name": "Анна",
                "fields": {"name": "Анна", "guests_count": 20},
                "max": {"message_ids": [message_id]},
            }
        ]
        events = [
            {
                "type": "max_message_created",
                "source": "MAX",
                "message_id": message_id,
                "has_linked_or_forwarded_message": True,
                "timestamp": 1789562315058,
                "text": "ЗАЯВКА. 20.09. 20п. Анна. 89266560108",
            }
        ]

        removed = remove_linked_contact_followup_leads(leads, events)

        self.assertEqual(removed, 0)
        self.assertEqual(len(leads), 1)


if __name__ == "__main__":
    unittest.main()
