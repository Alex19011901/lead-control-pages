from pathlib import Path
import unittest


class PageShareManagerModesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("dashboard/pageshare/index.html").read_text(encoding="utf-8")

    def test_three_manager_buttons_exist(self):
        self.assertIn('data-manager="all"', self.html)
        self.assertIn('data-manager="Олеся"', self.html)
        self.assertIn('data-manager="Максим"', self.html)

    def test_personal_mode_hides_general_dashboard(self):
        self.assertIn("id('generalDashboard').style.display=personal?'none':''", self.html)

    def test_feedback_is_filtered_by_manager(self):
        self.assertIn("currentManager!=='all'&&norm(x.manager)!==currentManager", self.html)

    def test_not_entered_is_outside_general_dashboard(self):
        self.assertIn('</div>\n</div>\n<div class="card section-gap"><div class="feedback-head"><div style="flex:1;min-width:0"><div class="title" style="margin-bottom:3px">Не внесённые заявки</div>', self.html)

    def test_not_entered_remains_global(self):
        self.assertIn('var nr=N.slice()', self.html)

if __name__ == '__main__':
    unittest.main()
