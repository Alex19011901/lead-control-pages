from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.augment_dashboard_feedback import augment
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
        self.assertIn("Последний комментарий", rendered)
        self.assertIn("x.last_comment", rendered)
        self.assertIn('id="outcomes"', rendered)
        self.assertIn("Результаты реализации", rendered)
        self.assertIn("O=view.outcomes||[]", rendered)
        self.assertIn("renderOutcomes()", rendered)
        self.assertIn("Успешно реализовано", rendered)
        self.assertIn("Отказ: ", rendered)

    def test_dashboard_view_exports_success_and_loss_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            leads_path = root / "leads.json"
            view_path = root / "dashboard_view.json"
            leads_path.write_text(
                json.dumps(
                    {
                        "leads": [
                            {
                                "id": "success",
                                "received_at": "2026-09-21T10:00:00+03:00",
                                "crm": {
                                    "found": True,
                                    "entity_type": "lead",
                                    "entity_id": 1,
                                    "responsible_user_name": "Олеся",
                                },
                                "crm_outcome": {
                                    "result": "SUCCESS",
                                    "status_name": "Успешно реализовано",
                                },
                            },
                            {
                                "id": "lost",
                                "received_at": "2026-09-20T11:00:00+03:00",
                                "crm": {
                                    "found": True,
                                    "entity_type": "lead",
                                    "entity_id": 2,
                                    "responsible_user_name": "Максим",
                                },
                                "crm_outcome": {
                                    "result": "LOST",
                                    "status_name": "Закрыто и не реализовано",
                                    "loss_reason_name": "Не устроила цена",
                                },
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            view_path.write_text(
                json.dumps({"ranges": {}, "latest": [], "not_entered": []}),
                encoding="utf-8",
            )

            augment(leads_path, view_path, now_ts=1)
            result = json.loads(view_path.read_text(encoding="utf-8"))

            self.assertEqual(len(result["outcomes"]), 2)
            by_result = {row["result"]: row for row in result["outcomes"]}
            self.assertEqual(by_result["SUCCESS"]["date"], "2026-09-21")
            self.assertEqual(by_result["LOST"]["reason"], "Не устроила цена")

    def test_injection_is_idempotent(self):
        source = Path("dashboard/pageshare/index.html").read_text(encoding="utf-8")
        once = inject(source)
        twice = inject(once)
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
