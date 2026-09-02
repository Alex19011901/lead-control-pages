from __future__ import annotations

import unittest

from lead_control.amocrm_client import AmoCRMClient, AmoCRMSearchResult
from lead_control.crm_apply import apply_crm


class FakeAmoCRMClient(AmoCRMClient):
    def __init__(self, leads=None, contacts=None, entities=None):
        super().__init__("https://example.amocrm.ru", "token")
        self.leads = leads or []
        self.contacts = contacts or []
        self.entities = entities or {}

    def _search_collection(self, entity_type, query, with_value):
        return list(self.leads if entity_type == "leads" else self.contacts)

    def _get_entity(self, entity_type, entity_id, params=None):
        return self.entities.get((entity_type, entity_id))

    def _get_user_name(self, user_id):
        return "Менеджер" if user_id else None


class AmoCRMDealMatchingTests(unittest.TestCase):
    def test_contact_is_not_a_crm_match_without_deal(self):
        client = FakeAmoCRMClient(
            contacts=[{"id": 10, "created_at": 100, "_embedded": {"leads": []}}],
            entities={("contacts", 10): {"id": 10, "_embedded": {"leads": []}}},
        )
        result = client.search("79990000000", "lead-1", "phone")
        self.assertFalse(result.found)
        self.assertIsNone(result.entity_type)

    def test_linked_deal_format_is_read_from_full_card(self):
        client = FakeAmoCRMClient(
            contacts=[{"id": 10, "created_at": 500, "_embedded": {"leads": [{"id": 20}]}}],
            entities={
                ("leads", 20): {
                    "id": 20,
                    "created_at": 200,
                    "updated_at": 250,
                    "responsible_user_id": 7,
                    "custom_fields_values": [
                        {"field_name": "Формат", "values": [{"value": "Свадьба"}]}
                    ],
                }
            },
        )
        result = client.search("79990000000", "lead-2", "phone")
        self.assertTrue(result.found)
        self.assertEqual(result.entity_type, "lead")
        self.assertEqual(result.entity_id, 20)
        self.assertEqual(result.event_type, "Свадьба")
        self.assertEqual(result.responsible_user_name, "Менеджер")

    def test_nearest_deal_can_be_selected_by_source_timestamp(self):
        client = FakeAmoCRMClient(
            leads=[
                {"id": 30, "created_at": 1000, "updated_at": 1000},
                {"id": 31, "created_at": 3000, "updated_at": 3000},
            ],
            entities={
                ("leads", 30): {
                    "id": 30,
                    "created_at": 1000,
                    "custom_fields_values": [
                        {"field_name": "Формат", "values": [{"value": "Юбилей"}]}
                    ],
                },
                ("leads", 31): {
                    "id": 31,
                    "created_at": 3000,
                    "custom_fields_values": [
                        {"field_name": "Формат", "values": [{"value": "Корпоратив"}]}
                    ],
                },
            },
        )
        result = client.search(
            "79990000000",
            "lead-3",
            "phone",
            target_created_at=1200,
        )
        self.assertEqual(result.entity_id, 30)
        self.assertEqual(result.event_type, "Юбилей")


class StaleAggregatorClient:
    def __init__(self):
        self.search_calls = 0

    def search(self, query, lead_id, identifier_type, target_created_at=None):
        self.search_calls += 1
        return AmoCRMSearchResult(
            found=True,
            entity_type="lead",
            entity_id=48145609,
            created_at=1000,
            updated_at=1100,
            responsible_user_id=7,
            responsible_user_name="Олеся",
            event_type="Юбилей",
        )

    def _get_entity(self, entity_type, entity_id):
        return {
            "id": entity_id,
            "created_at": 1000,
            "custom_fields_values": [
                {"field_name": "Количество гостей", "values": [{"value": 20}]}
            ],
        }


class AggregatorCRMRecencyTests(unittest.TestCase):
    def test_old_same_phone_crm_deal_does_not_confirm_new_restoran_cafe_request(self):
        lead = {
            "id": "new-restoran-request",
            "category": "RESTORAN_CAFE",
            "channel": "MAX",
            "first_seen_ts": 40000,
            "deadline_msk_ts": 90000,
            "crm_required": True,
            "identifier": {"type": "phone", "value": "79852337945"},
            "status": "PENDING",
            "violations": [],
        }
        previous = {
            **lead,
            "crm": {
                "found": True,
                "entity_type": "lead",
                "entity_id": 48145609,
                "created_at": 1000,
                "guests": "20",
            },
        }
        client = StaleAggregatorClient()

        apply_crm([lead], client, previous_leads=[previous], reuse_confirmed=True)

        self.assertEqual(client.search_calls, 1)
        self.assertFalse(lead["crm"]["found"])
        self.assertIsNone(lead["crm"]["entity_id"])
        self.assertNotIn("guests", lead["crm"])

    def test_recent_crm_deal_can_confirm_restoran_cafe_request(self):
        lead = {
            "category": "RESTORAN_CAFE",
            "first_seen_ts": 40000,
        }
        from lead_control.crm_apply import _crm_match_is_current_for_lead
        self.assertTrue(
            _crm_match_is_current_for_lead(
                lead,
                {"found": True, "created_at": 39000},
            )
        )
        self.assertFalse(
            _crm_match_is_current_for_lead(
                lead,
                {"found": True, "created_at": 30000},
            )
        )


if __name__ == "__main__":
    unittest.main()
