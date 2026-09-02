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

    def test_public_build_has_no_private_github_token_or_api(self):
        for marker in (
            "__GITHUB_TOKEN__",
            "GITHUB_TOKEN",
            "github_pat_",
            "ghp_",
            "gho_",
            "lead-control.yml",
            "GH_ACCESS_STORAGE",
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
        self.assertIn("async function waitForPublicRefresh(created,previous,serial,runId)", self.mirror)
        self.assertIn("progress(1,'Ожидание обновления системы…')", self.mirror)
        self.assertIn("progress(2,'Сбор Telegram/MAX + amoCRM…')", self.mirror)
        self.assertIn("var payload=await waitForPublicRefresh(start.created,previous,serial,start.runId)", self.mirror)
        self.assertIn("btn.textContent='Обновить данные'", self.mirror)

    def test_pages_refresh_dispatches_public_workflow(self):
        self.assertIn("PUBLIC_REFRESH_TOKEN='__PUBLIC_REFRESH_TOKEN__'", self.mirror)
        self.assertIn("GH_REPO='lead-control-pages'", self.mirror)
        self.assertIn("GH_WORKFLOW='lead-control-public.yml'", self.mirror)
        self.assertIn("https://api.github.com/repos/", self.mirror)
        self.assertIn("Authorization:'Bearer '+PUBLIC_REFRESH_TOKEN", self.mirror)
        self.assertIn("async function dispatchPublicWorkflow()", self.mirror)
        self.assertIn("async function listPublicRuns()", self.mirror)
        self.assertIn("async function findActivePublicRun()", self.mirror)
        self.assertIn("async function ensurePublicWorkflow()", self.mirror)
        self.assertIn("async function findPublicRun(created,runId)", self.mirror)
        self.assertIn("var start=await ensurePublicWorkflow()", self.mirror)

    def test_pages_refresh_reuses_active_workflow_instead_of_dispatching_duplicate(self):
        self.assertIn("'queued':1", self.mirror)
        self.assertIn("'pending':1", self.mirror)
        self.assertIn("'in_progress':1", self.mirror)
        self.assertIn("'waiting':1", self.mirror)
        self.assertIn("'requested':1", self.mirror)
        self.assertIn("if(active)return {created:active.created_at||new Date().toISOString(),runId:active.id,reused:true}", self.mirror)
        self.assertIn("if(start.reused)progress(1,'Обновление уже запущено…')", self.mirror)
        self.assertIn("waitForPublicRefresh(start.created,previous,serial,start.runId)", self.mirror)

    def test_publish_token_placeholder_is_not_exposed(self):
        self.assertNotIn("__GITHUB_TOKEN__", self.mirror)
        self.assertNotIn("ghp_", self.mirror)
        self.assertNotIn("github_pat_", self.mirror)


if __name__ == "__main__":
    unittest.main()
