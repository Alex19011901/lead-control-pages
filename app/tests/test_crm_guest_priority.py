from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from lead_control.crm_guests import extract_crm_guest_value
from apply_dashboard_crm_guest_priority import apply_priority, effective_guest_value
from build_dashboard_snapshot import build


class CRMGuestPriorityTests(unittest.TestCase):
    def test_extracts_explicit_guest_field_from_amo_card(self):
        entity = {
            "custom_fields_values": [
                {"field_name": "Формат", "values": [{"value": "Свадьба"}]},
                {"field_name": "Количество гостей", "values": [{"value": 42}]},
            ]
        }
        self.assertEqual(extract_crm_guest_value(entity), "42")

    def test_crm_guest_value_overrides_source_for_analytics(self):
        lead = {
            "crm": {"found": True, "guests": "80"},
            "fields": {"description": "Заявка на 25 гостей", "guests_count": 25},
        }
        self.assertEqual(effective_guest_value(lead), "80")

    def test_source_value_remains_fallback_when_crm_guest_field_is_empty(self):
        lead = {
            "crm": {"found": True},
            "fields": {"description": "Заявка на 25 гостей", "guests_count": 25},
        }
        self.assertEqual(effective_guest_value(lead), "25")

    def test_dashboard_row_uses_crm_guest_value_when_source_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            leads_path = root / "leads.json"
            snapshot_path = root / "dashboard_daily.json"
            leads_path.write_text(
                json.dumps(
                    {
                        "leads": [
                            {
                                "received_at": "2026-08-26T12:59:35+03:00",
                                "status": "OK",
                                "source": "САЙТ ТИЛЬДА",
                                "channel": "TELEGRAM",
                                "identifier": {"type": "phone", "value": "79251546047"},
                                "fields": {"name": "Наталия"},
                                "crm": {
                                    "found": True,
                                    "guests": "60",
                                    "responsible_user_name": "Максим",
                                    "event_type": "Детский праздник",
                                },
                                "event_type": "Детский праздник",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            build(leads_path, snapshot_path)
            result = json.loads(snapshot_path.read_text(encoding="utf-8"))

            self.assertEqual(result["latest"][0]["guests"], "60")
            self.assertEqual(result["latest"][0]["guest_range"], "60")

    def test_only_guest_analytics_are_recomputed_with_crm_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            leads_path = root / "leads.json"
            view_path = root / "dashboard_view.json"
            leads_path.write_text(
                json.dumps(
                    {
                        "leads": [
                            {
                                "received_at": "2026-08-22T10:00:00+03:00",
                                "crm": {"found": True, "guests": "80"},
                                "fields": {"description": "25 гостей", "guests_count": 25},
                            },
                            {
                                "received_at": "2026-08-22T11:00:00+03:00",
                                "crm": {"found": True},
                                "fields": {"description": "15 гостей", "guests_count": 15},
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            original = {
                "ranges": {
                    "all": {
                        "start": "2026-08-22",
                        "end": "2026-08-22",
                        "total": 2,
                        "status": {"OK": 2},
                        "source": {"MARQUIZ": 2},
                        "channel": {"MAX": 2},
                        "event": {"Свадьба": 2},
                        "guest": {"21-50": 1, "1-20": 1},
                    }
                },
                "latest": [{"name": "Не менять"}],
                "not_entered": [],
                "feedback_summary": {"no_feedback": 1},
            }
            view_path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")

            apply_priority(leads_path, view_path)
            result = json.loads(view_path.read_text(encoding="utf-8"))

            self.assertEqual(result["ranges"]["all"]["guest"], {"51-100": 1, "1-20": 1})
            self.assertEqual(result["ranges"]["all"]["status"], original["ranges"]["all"]["status"])
            self.assertEqual(result["ranges"]["all"]["source"], original["ranges"]["all"]["source"])
            self.assertEqual(result["latest"], original["latest"])
            self.assertEqual(result["feedback_summary"], original["feedback_summary"])


if __name__ == "__main__":
    unittest.main()
