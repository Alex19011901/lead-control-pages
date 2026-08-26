from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_dashboard_view import compact_lead, guest_bucket_label, merge_range


class DashboardGuestBucketTests(unittest.TestCase):
    def test_exact_values_are_bucketed_only_for_analytics(self):
        self.assertEqual(guest_bucket_label("2"), "1-20")
        self.assertEqual(guest_bucket_label("20"), "1-20")
        self.assertEqual(guest_bucket_label("21"), "21-50")
        self.assertEqual(guest_bucket_label("35-50"), "21-50")
        self.assertEqual(guest_bucket_label("до 40"), "21-50")
        self.assertEqual(guest_bucket_label("51"), "51-100")
        self.assertEqual(guest_bucket_label("100"), "51-100")
        self.assertEqual(guest_bucket_label("101-150"), "101-150")
        self.assertEqual(guest_bucket_label("150+"), "101-150")
        self.assertEqual(guest_bucket_label("151"), "151+")
        self.assertEqual(guest_bucket_label("unknown"), "Не указано")

    def test_range_analytics_have_only_approved_buckets(self):
        daily = {
            "2026-08-22": {
                "total": 6,
                "status": {"OK": 6},
                "source": {"Заявки хост": 6},
                "channel": {"MAX": 6},
                "guest_ranges": {
                    "2": 1,
                    "25": 1,
                    "35-50": 1,
                    "80": 1,
                    "120": 1,
                    "200": 1,
                },
                "event_types": {},
            }
        }
        result = merge_range(daily, date(2026, 8, 22), date(2026, 8, 22))
        self.assertEqual(
            result["guest"],
            {"1-20": 1, "21-50": 2, "51-100": 1, "101-150": 1, "151+": 1},
        )

    def test_lead_rows_keep_exact_guest_value(self):
        row = compact_lead(
            {
                "date": "2026-08-22",
                "ts": "2026-08-22T12:00:00+03:00",
                "source": "Заявки хост",
                "status": "OK",
                "channel": "MAX",
                "guest_range": "35-50",
                "guests": "35-50",
                "event_type": "Свадьба",
            }
        )
        self.assertEqual(row["guests"], "35-50")


if __name__ == "__main__":
    unittest.main()
