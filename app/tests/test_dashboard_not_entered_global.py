from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard" / "pageshare" / "index.html"


class DashboardNotEnteredGlobalTests(unittest.TestCase):
    def test_not_entered_block_ignores_selected_range(self) -> None:
        html = DASHBOARD.read_text(encoding="utf-8")
        self.assertIn("var nr=N.slice();", html)
        self.assertNotIn("if(nd>=a.s&&nd<=a.e)nr.push(N[i])", html)


if __name__ == "__main__":
    unittest.main()
