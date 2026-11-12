from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from scripts.build_dashboard_view import build


class DashboardViewCalendarTests(unittest.TestCase):
    def test_source_selector_exports_exact_last_30_moscow_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "dashboard_daily.json"
            output_path = root / "dashboard_view.json"
            input_path.write_text(
                json.dumps(
                    {
                        "snapshot_generated_at": "2026-09-28T10:00:00Z",
                        "generated_at": "2026-09-28T13:00:00+03:00",
                        "min_date": "2026-08-01",
                        "max_date": "2026-09-28",
                        "daily": {
                            "2026-09-28": {
                                "total": 3,
                                "status": {"OK": 3},
                                "source": {"Заявки хост": 2, "САЙТ ТИЛЬДА": 1},
                                "guest_ranges": {},
                                "event_types": {},
                                "channel": {"MAX": 2, "TELEGRAM": 1},
                            },
                            "2026-08-30": {
                                "total": 1,
                                "status": {"OK": 1},
                                "source": {"MARQUIZ": 1},
                                "guest_ranges": {},
                                "event_types": {},
                                "channel": {"TELEGRAM": 1},
                            },
                            "2026-08-29": {
                                "total": 9,
                                "status": {"OK": 9},
                                "source": {"Старый источник": 9},
                                "guest_ranges": {},
                                "event_types": {},
                                "channel": {"MAX": 9},
                            },
                        },
                        "leads": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch("scripts.build_dashboard_view.moscow_today", return_value=date(2026, 9, 28)):
                build(input_path, output_path)

            view = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(view["source_date_start"], "2026-08-30")
            self.assertEqual(view["source_date_end"], "2026-09-28")
            self.assertEqual(len(view["source_days"]), 30)
            self.assertEqual(
                view["source_days"]["2026-09-28"],
                {"Заявки хост": 2, "САЙТ ТИЛЬДА": 1},
            )
            self.assertEqual(view["source_days"]["2026-08-30"], {"MARQUIZ": 1})
            self.assertNotIn("2026-08-29", view["source_days"])

    def test_sources_widget_keeps_period_mode_and_visual_bars(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "dashboard" / "pageshare" / "index.html").read_text(encoding="utf-8")
        self.assertIn("По выбранному периоду", html)
        self.assertIn("source-card", html)
        self.assertIn("source-bars", html)
        self.assertIn("sourceDate?((SD&&SD[sourceDate])||{}):((R[currentRange]&&R[currentRange].src)||{})", html)

    def test_today_uses_moscow_calendar_even_when_latest_lead_is_yesterday(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "dashboard_daily.json"
            output_path = root / "dashboard_view.json"
            input_path.write_text(
                json.dumps(
                    {
                        "snapshot_generated_at": "2026-08-22T05:28:00Z",
                        "generated_at": "2026-08-21T22:54:48+03:00",
                        "min_date": "2026-08-21",
                        "max_date": "2026-08-21",
                        "daily": {
                            "2026-08-21": {
                                "total": 10,
                                "status": {"OK": 9, "ALARM_NO_CRM": 1},
                                "source": {"Заявки хост": 3},
                                "guest_ranges": {"50": 1},
                                "event_types": {"Свадьба": 1},
                                "channel": {"MAX": 6, "TELEGRAM": 4},
                            }
                        },
                        "leads": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch("scripts.build_dashboard_view.moscow_today", return_value=date(2026, 8, 22)):
                build(input_path, output_path)

            view = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(view["ranges"]["today"]["start"], "2026-08-22")
            self.assertEqual(view["ranges"]["today"]["end"], "2026-08-22")
            self.assertEqual(view["ranges"]["today"]["total"], 0)
            self.assertEqual(view["ranges"]["yesterday"]["start"], "2026-08-21")
            self.assertEqual(view["ranges"]["yesterday"]["total"], 10)


    def test_whole_period_dynamics_is_responsive_and_shows_first_of_every_month(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "dashboard" / "pageshare" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="dynAxis"', html)
        self.assertIn('id="dynMonthTicks"', html)
        self.assertIn("#dyn .dcol{flex:1 1 0;min-width:0", html)
        self.assertIn("#dyn.dyn-all{gap:1px}", html)
        self.assertIn("#dyn.dyn-all.dyn-dense{gap:0}", html)
        self.assertIn("dateKey.slice(8)!=='01'", html)
        self.assertIn("marker.textContent='01.'+dateKey.slice(5,7)", html)
        self.assertIn("marker.style.left=(100*i/d.length).toFixed(3)+'%'", html)
        self.assertIn("for(var stamp=start;stamp<=end;stamp+=86400000)", html)
        self.assertIn("axis.classList.toggle('dyn-all-axis',all)", html)
        self.assertIn("renderDynamics(a);", html)
        # The PageShare -> GitHub Pages transform and legacy widget injection
        # must remain compatible after adding the month-axis markup.
        from scripts.build_github_pages_mirror import build_mirror
        from scripts.inject_closed_not_realized_widget import inject
        published = inject(build_mirror(html))
        self.assertIn('id="dynMonthTicks"', published)
        self.assertIn("renderDynamics(a);", published)

    def test_only_selected_december_2026_dates_receive_colored_contours(self) -> None:
        import re
        root = Path(__file__).resolve().parents[1]
        html = (root / "dashboard" / "pageshare" / "index.html").read_text(encoding="utf-8")
        match = re.search(r"var heatDecember2026Borders=\{(.*?)\};", html, flags=re.S)
        self.assertIsNotNone(match)
        mapping = dict((int(day), color) for day, color in re.findall(r"(\d+):'(burgundy|yellow|purple)'", match.group(1)))
        self.assertEqual(mapping, {
            4: "burgundy", 5: "burgundy", 11: "burgundy", 18: "burgundy",
            22: "burgundy", 24: "burgundy", 25: "burgundy", 29: "burgundy",
            10: "yellow", 20: "yellow", 23: "yellow",
            12: "purple", 17: "purple",
        })
        self.assertIn("if(dateKey.slice(0,7)!=='2026-12')return '';", html)
        self.assertIn("return color?' hm-border-'+color:'';", html)
        self.assertIn("heatBorderClass(dateKey);", html)
        for color in ("burgundy", "yellow", "purple"):
            self.assertIn(".hm-day-cell.hm-border-" + color + "{box-shadow:inset", html)
        self.assertIn(".hm-level-5{background:#39a65b", html)
        self.assertIn("grid-template-columns:repeat(5,minmax(0,1fr))", html)
        from scripts.build_github_pages_mirror import build_mirror
        from scripts.inject_closed_not_realized_widget import inject
        published = inject(build_mirror(html))
        self.assertIn("heatBorderClass(dateKey);", published)

if __name__ == "__main__":
    unittest.main()
