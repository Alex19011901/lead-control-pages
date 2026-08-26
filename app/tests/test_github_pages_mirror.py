from pathlib import Path
import unittest

from scripts.build_github_pages_mirror import build_mirror


class GitHubPagesMirrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("dashboard/pageshare/index.html").read_text(encoding="utf-8")
        cls.mirror = build_mirror(cls.source)

    def test_approved_dashboard_is_preserved(self):
        for marker in (
            'data-manager="all"',
            'data-manager="Олеся"',
            'data-manager="Максим"',
            'Не внесённые заявки',
            'Обратная связь по внесённым лидам',
            'function refreshDashboard()',
            "currentManager!=='all'&&norm(x.manager)!==currentManager",
            "var nr=N.slice()",
        ):
            self.assertIn(marker, self.mirror)

    def test_public_build_has_no_github_token_or_api(self):
        for marker in (
            "__GITHUB_TOKEN__",
            "GITHUB_TOKEN",
            "github_pat_",
            "ghp_",
            "gho_",
            "Bearer",
            "Authorization",
            "api.github.com",
            "actions/workflows",
            "dispatchWorkflow",
            "findRun",
            "GH_ACCESS_STORAGE",
            "GH_OWNER",
            "GH_REPO",
            "GH_WORKFLOW",
            "GH_REF",
            "GH_DATA_REF",
        ):
            self.assertNotIn(marker, self.mirror)

    def test_public_build_uses_local_dashboard_view_json(self):
        self.assertIn("const DASHBOARD_DATA_URL='./dashboard_view.json';", self.mirror)
        self.assertIn("function dashboardDataUrl()", self.mirror)
        self.assertIn("async function loadDashboardPayload(){return requestJson(dashboardDataUrl()", self.mirror)

    def test_pages_refresh_waits_for_new_public_snapshot(self):
        self.assertIn("function snapshotValue(payload)", self.mirror)
        self.assertIn("function snapshotIsNewer(snap,previous)", self.mirror)
        self.assertIn("async function waitForPublicRefresh(previous,serial)", self.mirror)
        self.assertIn("progress(1,'Ожидание обновления системы…')", self.mirror)
        self.assertIn("progress(2,'Сбор Telegram/MAX + amoCRM…')", self.mirror)
        self.assertIn("var payload=await waitForPublicRefresh(previous,serial)", self.mirror)
        self.assertIn("btn.textContent='Обновить данные'", self.mirror)

    def test_publish_token_placeholder_is_not_exposed(self):
        self.assertNotIn("__GITHUB_TOKEN__", self.mirror)
        self.assertNotIn("ghp_", self.mirror)
        self.assertNotIn("github_pat_", self.mirror)


if __name__ == "__main__":
    unittest.main()
