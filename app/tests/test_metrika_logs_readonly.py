from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "metrika_logs_readonly.py"
SPEC = importlib.util.spec_from_file_location("metrika_logs_readonly", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class FakeClient:
    def __init__(self) -> None:
        self.evaluate_calls = []
        self.create_calls = []
        self.status_calls = []
        self.download_calls = []
        self._status_count = 0

    def evaluate(self, **kwargs):
        self.evaluate_calls.append(kwargs)
        return {"log_request_evaluation": {"possible": True}}

    def create_export(self, **kwargs):
        self.create_calls.append(kwargs)
        return mod.LogRequest(request_id=77, status="created", parts=())

    def status(self, request_id):
        self.status_calls.append(request_id)
        self._status_count += 1
        if self._status_count == 1:
            return mod.LogRequest(request_id=77, status="created", parts=())
        return mod.LogRequest(request_id=77, status="processed", parts=(0, 1))

    def download_part(self, request_id, part_number):
        self.download_calls.append((request_id, part_number))
        header = "ym:s:visitID\tym:s:dateTime\tym:s:dateTimeUTC\tym:s:clientID\tym:s:startURL\tym:s:lastDirectClickOrder\n"
        if part_number == 0:
            return header + "1\t2026-09-03 16:45:00\t2026-09-03 16:45:00\t123\thttps://example.test/?foo=1\t10\n"
        return header + "2\t2026-09-03 16:46:00\t2026-09-03 16:46:00\t124\thttps://example.test/?yclid=5288069203188252671&utm_source=yandex\t11\n"


class MetrikaLogsReadonlyTests(unittest.TestCase):
    def test_large_yclid_is_preserved_exactly_as_string(self):
        value = "5288069203188252671"
        url = "https://example.test/?yclid=" + value
        self.assertEqual(mod.extract_yclid(url), value)
        self.assertIsInstance(mod.extract_yclid(url), str)

    def test_extract_yclid_handles_encoded_query(self):
        self.assertEqual(
            mod.extract_yclid("https://example.test/path?a=1&yclid=1234567890123456789&b=2"),
            "1234567890123456789",
        )

    def test_allowed_paths_are_strict(self):
        self.assertTrue(mod._allowed_path("POST", "/counter/112267492/logrequests"))
        self.assertTrue(mod._allowed_path("GET", "/counter/112267492/logrequests/evaluate"))
        self.assertTrue(mod._allowed_path("GET", "/counter/112267492/logrequest/77"))
        self.assertTrue(mod._allowed_path("GET", "/counter/112267492/logrequest/77/part/0/download"))
        self.assertFalse(mod._allowed_path("POST", "/counter/112267492/offline_conversions/upload"))
        self.assertFalse(mod._allowed_path("POST", "/counter/112267492/logrequest/77/clean"))
        self.assertFalse(mod._allowed_path("PUT", "/counter/112267492/logrequests"))
        self.assertFalse(mod._allowed_path("DELETE", "/counter/112267492/logrequests"))

    def test_collect_finds_target_locally_in_start_url(self):
        client = FakeClient()
        result = mod.collect(
            client,
            yclid="5288069203188252671",
            date1="2026-09-03",
            date2="2026-09-03",
            poll_seconds=0,
            max_polls=3,
        )
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["yclid"], "5288069203188252671")
        self.assertEqual(result["request_id"], 77)
        self.assertEqual(result["matches_count"], 1)
        self.assertEqual(result["visits"][0]["ym:s:visitID"], "2")
        self.assertEqual(result["visits"][0]["ym:s:lastDirectClickOrder"], "11")
        self.assertEqual(len(client.evaluate_calls), 1)
        self.assertEqual(len(client.create_calls), 1)
        self.assertEqual(client.download_calls, [(77, 0), (77, 1)])

    def test_collect_returns_not_found_without_fallback_matching(self):
        client = FakeClient()
        result = mod.collect(
            client,
            yclid="9999999999999999999",
            date1="2026-09-03",
            date2="2026-09-03",
            poll_seconds=0,
            max_polls=3,
        )
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["matches_count"], 0)
        self.assertEqual(result["visits"], [])

    def test_safe_diagnostic_does_not_add_unrequested_fields(self):
        row = {
            "ym:s:visitID": "2",
            "ym:s:startURL": "https://example.test/?yclid=5288069203188252671",
            "secret": "must-not-leak",
        }
        result = mod.safe_diagnostic([row], yclid="5288069203188252671", request_id=1)
        self.assertNotIn("secret", result["visits"][0])


if __name__ == "__main__":
    unittest.main()
