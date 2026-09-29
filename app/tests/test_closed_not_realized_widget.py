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
        self.assertIn("Последняя запись", rendered)
        self.assertIn("x.last_record", rendered)
        self.assertIn("closedRecordHtml", rendered)
        self.assertIn("closed-record-time", rendered)
        self.assertIn('id="outcomes"', rendered)
        self.assertIn("Результаты реализации", rendered)
        self.assertIn("O=view.outcomes||[]", rendered)
        self.assertIn("renderOutcomes()", rendered)
        self.assertIn("Успешно реализовано", rendered)
        self.assertIn("Отказ: ", rendered)
        self.assertIn('id="pipelineActivityCard"', rendered)
        self.assertIn('id="pipelineWeekSelect"', rendered)
        self.assertIn('id="pipelineActivityGrid"', rendered)
        self.assertIn("Активность по этапам воронки", rendered)
        self.assertIn("PA=view.pipeline_activity||{}", rendered)
        self.assertIn("renderPipelineActivity()", rendered)

    def test_dashboard_view_exports_last_record_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            leads_path = root / "leads.json"
            view_path = root / "dashboard_view.json"
            leads_path.write_text(
                json.dumps(
                    {
                        "leads": [
                            {
                                "id": "closed",
                                "received_at": "2026-09-28T10:00:00+03:00",
                                "crm": {
                                    "found": True,
                                    "entity_type": "lead",
                                    "entity_id": 48855703,
                                    "responsible_user_name": "Олеся",
                                },
                                "closed_not_realized": {
                                    "crm_lead_id": 48855703,
                                    "closed_at": 1790579990,
                                    "loss_reason_name": "Пропала потребность",
                                    "last_comment": "",
                                    "last_record_display": "Внутреннее сообщение",
                                    "last_record_at": 1790579981,
                                    "last_record_type": "entity_direct_message",
                                    "last_record_status": "TEXT_UNAVAILABLE",
                                },
                            }
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

            augment(leads_path, view_path, now_ts=1790581000)
            result = json.loads(view_path.read_text(encoding="utf-8"))
            row = result["closed_not_realized"][0]
            self.assertEqual(row["last_record"], "Внутреннее сообщение")
            self.assertEqual(row["last_record_type"], "entity_direct_message")
            self.assertEqual(row["last_record_status"], "TEXT_UNAVAILABLE")
            self.assertTrue(row["last_record_at"].startswith("2026-09-28T10:19:41"))

    def test_dashboard_view_exports_success_and_loss_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            leads_path = root / "leads.json"
            view_path = root / "dashboard_view.json"
            leads_path.write_text(
                json.dumps(
                    {
                        "pipeline_activity": {
                            "pipeline_id": 77,
                            "pipeline_name": "Основная воронка",
                            "today": "2026-09-21",
                            "weeks": [{"index": 0, "start": "2026-09-21", "end": "2026-09-27", "dates": ["2026-09-21"], "label": "21.09–27.09 · Текущая"}],
                            "stages": [{"id": 20, "name": "Предбронь", "sort": 20}],
                            "days": {"2026-09-21": {"20": 2}},
                            "total_movements": 2,
                        },
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
            self.assertEqual(result["pipeline_activity"]["total_movements"], 2)
            self.assertEqual(result["pipeline_activity"]["days"]["2026-09-21"]["20"], 2)
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
