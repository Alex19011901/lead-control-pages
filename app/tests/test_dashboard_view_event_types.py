from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "build_dashboard_view.py"
spec = importlib.util.spec_from_file_location("build_dashboard_view", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["build_dashboard_view"] = module
spec.loader.exec_module(module)


class DashboardViewEventTypeTests(unittest.TestCase):
    def test_undefined_event_types_fill_total(self) -> None:
        daily = {
            "2026-08-22": {
                "total": 7,
                "status": {"OK": 4, "PENDING": 2, "-": 1},
                "source": {"Заявка с ТГ": 1},
                "channel": {"MAX": 5, "TELEGRAM": 2},
                "guest_ranges": {},
                "event_types": {"Свадьба": 3},
            }
        }

        result = module.merge_range(daily, date(2026, 8, 22), date(2026, 8, 22))

        self.assertEqual(result["total"], 7)
        self.assertEqual(result["event"], {"Свадьба": 3, "Не определено": 4})
        self.assertEqual(sum(result["event"].values()), result["total"])

    def test_explicit_unknown_is_counted_as_undefined(self) -> None:
        daily = {
            "2026-08-22": {
                "total": 4,
                "event_types": {"Свадьба": 2, "unknown": 2},
            }
        }

        result = module.merge_range(daily, date(2026, 8, 22), date(2026, 8, 22))

        self.assertEqual(result["event"], {"Свадьба": 2, "Не определено": 2})


if __name__ == "__main__":
    unittest.main()
