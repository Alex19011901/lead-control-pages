from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from lead_control.manual_lead_corrections import apply_manual_lead_corrections


ROOT = Path(__file__).resolve().parents[2]


class ManualLeadCorrectionsTests(unittest.TestCase):
    def test_records_exist_only_for_requested_max_messages(self) -> None:
        payload = json.loads(
            (ROOT / "runtime-data" / "manual_lead_corrections.json").read_text(encoding="utf-8")
        )
        items = payload["items"]
        self.assertEqual(len(items), 2)
        by_id = {x["message_id"]: x for x in items}
        self.assertEqual(
            by_id["mid.ffffbec8f345ffab01a181e88678602b"]["display_phone"],
            "8-950-09-69-90",
        )
        self.assertEqual(
            by_id["mid.ffffbec8f345ffab01a183635ce71efd"]["name"],
            "Екатерина",
        )

    def test_manual_phone_correction_is_display_only(self) -> None:
        payload = json.loads(
            (ROOT / "runtime-data" / "manual_lead_corrections.json").read_text(encoding="utf-8")
        )
        lead = {
            "channel": "MAX", "name": "Ольга", "phone": "8-950-09-69-900",
            "identifier": {
                "type": "review_message",
                "value": "MAX:-71704692523093:mid.ffffbec8f345ffab01a181e88678602b"
            },
            "status": "-", "crm_check_status": "NO_IDENTIFIER",
            "crm": {"found": False},
            "manual_review": {"decision": "HOST"},
            "max": {"chat_id": -71704692523093,
                    "message_ids": ["mid.ffffbec8f345ffab01a181e88678602b"]},
            "fields": {"name": "Ольга", "phone_raw": "8-950-09-69-900",
                       "phone_digits": ""},
        }
        before = copy.deepcopy(lead)
        self.assertEqual(apply_manual_lead_corrections([lead], payload["items"]), 1)
        self.assertEqual(lead["phone"], "8-950-09-69-90")
        self.assertEqual(lead["fields"]["phone_raw"], "8-950-09-69-90")
        for key in ("identifier", "status", "crm_check_status", "crm", "manual_review"):
            self.assertEqual(lead[key], before[key])
        self.assertEqual(lead["fields"]["phone_digits"], "")
        self.assertEqual(apply_manual_lead_corrections([lead], payload["items"]), 0)

    def test_missing_name_recovers_only_exact_message(self) -> None:
        payload = json.loads(
            (ROOT / "runtime-data" / "manual_lead_corrections.json").read_text(encoding="utf-8")
        )
        target = {
            "channel": "MAX", "name": "", "status": "OK",
            "identifier": {"type": "phone", "value": "79853111554"},
            "crm": {"found": True, "guests": "30"}, "guests": None,
            "max": {"chat_id": -71704692523093,
                    "message_ids": ["mid.ffffbec8f345ffab01a183635ce71efd"]},
            "fields": {"name": "", "event_date_raw": "29.05.27"},
        }
        other = copy.deepcopy(target)
        other["max"]["message_ids"] = ["mid.other"]
        other["name"] = "Другой"
        other["fields"]["name"] = "Другой"
        before = copy.deepcopy(target)
        self.assertEqual(apply_manual_lead_corrections([target, other], payload["items"]), 1)
        self.assertEqual(target["name"], "Екатерина")
        self.assertEqual(target["fields"]["name"], "Екатерина")
        self.assertEqual(target["name_source"], "USER_VERIFIED_MAX_MESSAGE")
        self.assertEqual(target["status"], before["status"])
        self.assertEqual(target["crm"], before["crm"])
        self.assertEqual(target["identifier"], before["identifier"])
        self.assertEqual(other["name"], "Другой")
        self.assertEqual(apply_manual_lead_corrections([target, other], payload["items"]), 0)


if __name__ == "__main__":
    unittest.main()
