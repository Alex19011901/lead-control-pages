from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.source_categories import canonical_source


class MailSourceCategoryTests(unittest.TestCase):
    def test_mail_source_name_is_exact(self) -> None:
        self.assertEqual(canonical_source("Заявка почта"), "ЗАЯВКА ПОЧТА")
        self.assertEqual(canonical_source("ЗАЯВКА ПОЧТА"), "ЗАЯВКА ПОЧТА")


if __name__ == "__main__":
    unittest.main()
