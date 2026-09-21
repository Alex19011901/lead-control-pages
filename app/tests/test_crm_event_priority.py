from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.amocrm_client import AmoCRMClient
from lead_control.status_policy import apply_crm_day_status_policy


class FakeAmoCRMClient(AmoCRMClient):
    def __init__(self, responses: dict[str, dict]) -> None:
        super().__init__("https://example.amocrm.ru", "token")
        self.responses = responses

    def _request_json(self, path: str, params: dict) -> dict:
        return self.responses.get(path, {})


class CrmEventPriorityTests(unittest.TestCase):
    def test_search_reads_event_type_from_crm_format_field(self) -> None:
        client = FakeAmoCRMClient(
            {
                "/api/v4/leads": {
                    "_embedded": {
                        "leads": [
                            {
                                "id": 101,
                                "created_at": 100,
                                "updated_at": 200,
                                "responsible_user_id": 7,
                                "custom_fields_values": [
                                    {
                                        "field_name": "Формат",
                                        "values": [{"value": "Свадьба"}],
                                    }
                                ],
                            }
                        ]
                    }
                },
                "/api/v4/contacts": {"_embedded": {"contacts": []}},
                "/api/v4/users/7": {"name": "Олеся"},
            }
        )

        result = client.search("79990000000", "lead-1", "phone")

        self.assertTrue(result.found)
        self.assertEqual(result.entity_type, "lead")
        self.assertEqual(result.entity_id, 101)
        self.assertEqual(result.event_type, "Свадьба")
        self.assertEqual(result.responsible_user_name, "Олеся")

    def test_search_reads_event_type_from_full_chosen_lead_card(self) -> None:
        client = FakeAmoCRMClient(
            {
                "/api/v4/leads": {
                    "_embedded": {
                        "leads": [
                            {
                                "id": 111,
                                "created_at": 100,
                                "updated_at": 200,
                                "responsible_user_id": 7,
                                "custom_fields_values": [],
                            }
                        ]
                    }
                },
                "/api/v4/contacts": {"_embedded": {"contacts": []}},
                "/api/v4/leads/111": {
                    "id": 111,
                    "created_at": 100,
                    "updated_at": 200,
                    "responsible_user_id": 7,
                    "custom_fields_values": [
                        {
                            "field_name": "Формат",
                            "values": [{"value": "Юбилей"}],
                        }
                    ],
                },
                "/api/v4/users/7": {"name": "Олеся"},
            }
        )

        result = client.search("79990000009", "lead-9", "phone")

        self.assertTrue(result.found)
        self.assertEqual(result.entity_id, 111)
        self.assertEqual(result.event_type, "Юбилей")

    def test_contact_uses_event_type_from_linked_crm_lead(self) -> None:
        client = FakeAmoCRMClient(
            {
                "/api/v4/leads": {"_embedded": {"leads": []}},
                "/api/v4/contacts": {
                    "_embedded": {
                        "contacts": [
                            {
                                "id": 201,
                                "created_at": 300,
                                "updated_at": 400,
                                "responsible_user_id": 8,
                                "_embedded": {"leads": [{"id": 301}]},
                            }
                        ]
                    }
                },
                "/api/v4/leads/301": {
                    "id": 301,
                    "created_at": 100,
                    "updated_at": 500,
                    "responsible_user_id": 8,
                    "custom_fields_values": [
                        {
                            "field_name": "Формат",
                            "values": [{"value": "Корпоратив"}],
                        }
                    ],
                },
                "/api/v4/users/8": {"name": "Максим"},
            }
        )

        result = client.search("79990000001", "lead-2", "phone")

        self.assertTrue(result.found)
        self.assertEqual(result.entity_type, "lead")
        self.assertEqual(result.entity_id, 301)
        self.assertEqual(result.event_type, "Корпоратив")

    def test_crm_event_type_overrides_message_event_type_only(self) -> None:
        received = "2026-08-21T10:00:00+03:00"
        lead = {
            "channel": "TELEGRAM",
            "crm_required": True,
            "first_seen_ts": int(datetime.fromisoformat(received).timestamp()),
            "received_at": received,
            "fields": {
                "event_type": "Банкет",
                "guests_count": 50,
            },
            "crm": {
                "found": True,
                "created_at": int(datetime.fromisoformat("2026-08-21T12:00:00+03:00").timestamp()),
                "event_type": "Свадьба",
            },
            "status": "PENDING",
            "violations": [],
        }

        apply_crm_day_status_policy(
            [lead],
            now_ts=int(datetime.fromisoformat("2026-08-21T20:00:00+03:00").timestamp()),
        )

        self.assertEqual(lead["fields"]["event_type"], "Свадьба")
        self.assertEqual(lead["event_type"], "Свадьба")
        self.assertEqual(lead["event_type_source"], "CRM")
        self.assertEqual(lead["fields"]["guests_count"], 50)
        self.assertEqual(lead["status"], "OK")


if __name__ == "__main__":
    unittest.main()
