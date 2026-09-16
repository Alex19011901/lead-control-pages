from __future__ import annotations

from pathlib import Path
import unittest

from scripts.inject_closed_not_realized_widget import inject


class ClosedNotRealizedWidgetTests(unittest.TestCase):
    def test_widget_is_injected_into_dashboard_template(self):
        source = Path("dashboard/pageshare/index.html").read_text(encoding="utf-8")
        rendered = inject(source)

        self.assertIn('id="closedNotRealizedCard"', rendered)
        self.assertIn('id="closedNotRealizedTb"', rendered)
        self.assertIn("C=view.closed_not_realized||[]", rendered)
        self.assertIn("renderClosedNotRealized()", rendered)
        self.assertIn("Закрыто и не реализовано — 5 дней", rendered)

    def test_injection_is_idempotent(self):
        source = Path("dashboard/pageshare/index.html").read_text(encoding="utf-8")
        once = inject(source)
        twice = inject(once)
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
