from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_dashboard_snapshot import identifier_value


class DashboardReviewIdentifierTests(unittest.TestCase):
    def test_internal_review_message_is_not_shown_as_contact(self) -> None:
        lead = {
            "identifier": {
                "type": "review_message",
                "value": "MAX:-71704692523093:mid.internal",
            },
            "phone": "",
            "username": "",
        }

        self.assertEqual(identifier_value(lead), "")

    def test_real_phone_identifier_is_still_shown(self) -> None:
        lead = {
            "identifier": {"type": "phone", "value": "79031041281"},
        }

        self.assertEqual(identifier_value(lead), "79031041281")


if __name__ == "__main__":
    unittest.main()
