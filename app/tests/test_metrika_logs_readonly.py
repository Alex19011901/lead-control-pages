from __future__ import annotations

import importlib.util
import io
import sys
import unittest
import urllib.error
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "metrika_logs_readonly.py"
SPEC = importlib.util.spec_from_file_location("metrika_logs_readonly", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)

HITS_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "metrika_hits_url_diagnostic.py"
HITS_SPEC = importlib.util.spec_from_file_location("metrika_hits_url_diagnostic", HITS_MODULE_PATH)
assert HITS_SPEC is not None and HITS_SPEC.loader is not None
hits_mod = importlib.util.module_from_spec(HITS_SPEC)
sys.modules[HITS_SPEC.name] = hits_mod
HITS_SPEC.loader.exec_module(hits_mod)

TIME_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "metrika_visit_time_diagnostic.py"
TIME_SPEC = importlib.util.spec_from_file_location("metrika_visit_time_diagnostic", TIME_MODULE_PATH)
assert TIME_SPEC is not None and TIME_SPEC.loader is not None
time_mod = importlib.util.module_from_spec(TIME_SPEC)
sys.modules[TIME_SPEC.name] = time_mod
TIME_SPEC.loader.exec_module(time_mod)


class FakeClient:
    def __init__(self) -> None:
        self.counter_id = 112267492
        self.counters_calls = 0
        self.counter_calls = 0
        self.evaluate_calls = []
        self.create_calls = []
        self.status_calls = []
        self.download_calls = []
        self._status_count = 0

    def counters(self):
        self.counters_calls += 1
        return {"counters": [{"id": 112267492}, {"id": 1}]}

    def counter(self):
        self.counter_calls += 1
        return {"counter": {"id": 112267492}}

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
        self.assertTrue(mod._allowed_path("GET", "/counters"))
        self.assertTrue(mod._allowed_path("GET", "/counter/112267492"))
        self.assertTrue(mod._allowed_path("POST", "/counter/112267492/logrequests"))
        self.assertTrue(mod._allowed_path("GET", "/counter/112267492/logrequests/evaluate"))
        self.assertTrue(mod._allowed_path("GET", "/counter/112267492/logrequest/77"))
        self.assertTrue(mod._allowed_path("GET", "/counter/112267492/logrequest/77/part/0/download"))
        self.assertFalse(mod._allowed_path("POST", "/counters"))
        self.assertFalse(mod._allowed_path("POST", "/counter/112267492"))
        self.assertFalse(mod._allowed_path("POST", "/counter/112267492/offline_conversions/upload"))
        self.assertFalse(mod._allowed_path("POST", "/counter/112267492/logrequest/77/clean"))
        self.assertFalse(mod._allowed_path("PUT", "/counter/112267492/logrequests"))
        self.assertFalse(mod._allowed_path("DELETE", "/counter/112267492/logrequests"))

    def test_export_query_allows_only_read_logs_sources(self):
        client = mod.MetrikaLogsReadOnlyClient("token", counter_id=112267492)

        visits_query = client._export_query(
            date1="2026-09-01",
            date2="2026-09-03",
            fields=("ym:s:visitID",),
            attribution=mod.DEFAULT_ATTRIBUTION,
        )
        hits_query = client._export_query(
            date1="2026-09-01",
            date2="2026-09-03",
            fields=("ym:pv:URL",),
            attribution=mod.DEFAULT_ATTRIBUTION,
            source="hits",
        )

        self.assertEqual(visits_query["source"], "visits")
        self.assertEqual(hits_query["source"], "hits")
        with self.assertRaises(ValueError):
            client._export_query(
                date1="2026-09-01",
                date2="2026-09-03",
                fields=("ym:pv:URL",),
                attribution=mod.DEFAULT_ATTRIBUTION,
                source="offline_conversions",
            )

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
        self.assertEqual(result["access"]["token_access_status"], "ok")
        self.assertEqual(result["access"]["counter_access_status"], "ok")
        self.assertTrue(result["access"]["counter_visible_in_list"])
        self.assertEqual(client.counters_calls, 1)
        self.assertEqual(client.counter_calls, 1)
        self.assertEqual(len(client.evaluate_calls), 1)
        self.assertEqual(len(client.create_calls), 1)
        self.assertEqual(client.download_calls, [(77, 0), (77, 1)])

    def test_collect_blocks_when_token_cannot_list_counters(self):
        class ForbiddenClient(FakeClient):
            def counters(self):
                self.counters_calls += 1
                raise mod.LogsApiError("http_403:Forbidden:Access is denied")

        client = ForbiddenClient()
        result = mod.collect(
            client,
            yclid="5288069203188252671",
            date1="2026-09-03",
            date2="2026-09-03",
            poll_seconds=0,
            max_polls=3,
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "counter_access_failed")
        self.assertEqual(result["access"]["token_access_status"], "http_403:Forbidden:Access is denied")
        self.assertEqual(result["access"]["counter_access_status"], "not_checked")
        self.assertEqual(result["matches_count"], 0)
        self.assertEqual(client.counters_calls, 1)
        self.assertEqual(client.counter_calls, 0)
        self.assertEqual(len(client.evaluate_calls), 0)
        self.assertEqual(len(client.create_calls), 0)

    def test_collect_preserves_access_diagnostic_when_evaluate_fails(self):
        class EvaluateForbiddenClient(FakeClient):
            def evaluate(self, **kwargs):
                self.evaluate_calls.append(kwargs)
                raise mod.LogsApiError("http_403:Forbidden:Access is denied")

        client = EvaluateForbiddenClient()
        result = mod.collect(
            client,
            yclid="5288069203188252671",
            date1="2026-09-03",
            date2="2026-09-03",
            poll_seconds=0,
            max_polls=3,
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "http_403:Forbidden:Access is denied")
        self.assertEqual(result["access"]["token_access_status"], "ok")
        self.assertEqual(result["access"]["counter_access_status"], "ok")
        self.assertTrue(result["access"]["counter_visible_in_list"])
        self.assertEqual(len(client.evaluate_calls), 1)
        self.assertEqual(len(client.create_calls), 0)

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

    def test_safe_api_error_redacts_authorization_tokens(self):
        error = urllib.error.HTTPError(
            "https://api-metrika.yandex.net/safe",
            403,
            "Forbidden",
            {},
            io.BytesIO(
                b'{"errors":[{"error_type":"access_denied","message":"Bearer abc123token denied"}]}'
            ),
        )

        result = mod._safe_api_error(error)

        self.assertIn("access_denied", result)
        self.assertIn("Bearer [redacted]", result)
        self.assertNotIn("abc123token", result)


class MetrikaHitsUrlDiagnosticTests(unittest.TestCase):
    def test_hits_diagnostic_uses_hits_source_and_finds_yclid_in_page_url(self):
        client = HitsFakeClient(
            "ym:pv:watchID\tym:pv:pageViewID\tym:pv:visitID\tym:pv:dateTime\tym:pv:clientID\tym:pv:URL\tym:pv:referer\tym:pv:UTMSource\tym:pv:params\n"
            "1\t10\t100\t2026-09-03 17:23:00\tclient-a\thttps://example.test/?foo=1\t\t\t\n"
            "2\t20\t200\t2026-09-03 17:24:00\tclient-b\thttps://example.test/?yclid=5288069203188252671&utm_source=yandex\t\tyandex\t\n"
        )

        result = hits_mod.collect_hits_url_diagnostic(
            client,
            yclid="5288069203188252671",
            date1="2026-09-01",
            date2="2026-09-03",
            poll_seconds=0,
            max_polls=2,
        )

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["source"], "hits")
        self.assertEqual(result["matches_count"], 1)
        self.assertEqual(result["matches"][0]["ym:pv:visitID"], "200")
        self.assertEqual(result["matches"][0]["url_sanitized"]["has_yclid"], True)
        self.assertIn("ym:pv:URL", result["matches"][0]["yclid_sources"])
        self.assertNotIn("ym:pv:URL", result["matches"][0])
        self.assertEqual(client.evaluate_calls[0]["source"], "hits")
        self.assertEqual(client.create_calls[0]["source"], "hits")

    def test_hits_diagnostic_can_find_yclid_in_params_without_raw_params_output(self):
        client = HitsFakeClient(
            "ym:pv:watchID\tym:pv:pageViewID\tym:pv:visitID\tym:pv:dateTime\tym:pv:clientID\tym:pv:URL\tym:pv:referer\tym:pv:params\n"
            "3\t30\t300\t2026-09-03 17:25:00\tclient-c\thttps://example.test/?foo=1\t\t{\"yclid\":\"5288069203188252671\"}\n"
        )

        result = hits_mod.collect_hits_url_diagnostic(
            client,
            yclid="5288069203188252671",
            date1="2026-09-01",
            date2="2026-09-03",
            poll_seconds=0,
            max_polls=2,
        )

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["matches_count"], 1)
        self.assertIn("ym:pv:params", result["matches"][0]["params_fields_with_yclid"])
        self.assertNotIn("ym:pv:params", result["matches"][0])

    def test_hits_diagnostic_returns_not_found_when_yclid_is_absent(self):
        client = HitsFakeClient(
            "ym:pv:watchID\tym:pv:pageViewID\tym:pv:visitID\tym:pv:dateTime\tym:pv:clientID\tym:pv:URL\tym:pv:referer\tym:pv:params\n"
            "4\t40\t400\t2026-09-03 17:26:00\tclient-d\thttps://example.test/?foo=1\t\t{}\n"
        )

        result = hits_mod.collect_hits_url_diagnostic(
            client,
            yclid="5288069203188252671",
            date1="2026-09-01",
            date2="2026-09-03",
            poll_seconds=0,
            max_polls=2,
        )

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["matches_count"], 0)
        self.assertEqual(result["matches"], [])


class HitsFakeClient(FakeClient):
    def __init__(self, tsv: str) -> None:
        super().__init__()
        self._tsv = tsv

    def create_export(self, **kwargs):
        self.create_calls.append(kwargs)
        return mod.LogRequest(request_id=88, status="processed", parts=(0,))

    def download_part(self, request_id, part_number):
        self.download_calls.append((request_id, part_number))
        return self._tsv


class MetrikaVisitTimeDiagnosticTests(unittest.TestCase):
    def test_workflow_passes_leading_dash_utm_term_as_arg_value(self):
        workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "metrika-logs-readonly-diagnostic.yml").read_text(encoding="utf-8")

        self.assertIn("--utm-term=---autotargeting", workflow)
        self.assertNotIn("--utm-term ---autotargeting", workflow)

    def test_visit_time_diagnostic_returns_nearest_utm_candidates(self):
        client = VisitTimeFakeClient(
            "ym:s:visitID\tym:s:dateTime\tym:s:dateTimeUTC\tym:s:clientID\tym:s:startURL\tym:s:endURL\tym:s:referer\tym:s:lastDirectClickOrderName\tym:s:lastDirectBannerGroup\tym:s:lastUTMSource\tym:s:lastUTMMedium\tym:s:lastUTMCampaign\tym:s:lastUTMTerm\tym:s:lastAdvEngine\n"
            "1\t2026-09-03 16:20:00\t2026-09-03 13:20:00\tclient-a\thttps://example.test/?utm_source=yandex_direct\t\t\tCampaign A\t10\tyandex_direct\tcpc\tBankety_poisk_konversii\t---autotargeting\tdirect\n"
            "2\t2026-09-03 16:49:20\t2026-09-03 13:49:20\tclient-b\thttps://example.test/?utm_source=yandex_direct&utm_campaign=Bankety_poisk_konversii\t\t\tCampaign B\t20\tyandex_direct\tcpc\tBankety_poisk_konversii\t---autotargeting\tdirect\n"
            "3\t2026-09-03 21:00:00\t2026-09-03 18:00:00\tclient-c\thttps://example.test/?utm_source=yandex_direct\t\t\tCampaign C\t30\tyandex_direct\tcpc\tOther\t---autotargeting\tdirect\n"
        )

        result = time_mod.collect_visit_time_diagnostic(
            client,
            lead_timestamp_utc=1788443371,
            date1="2026-09-01",
            date2="2026-09-03",
            window_minutes=120,
            sample_limit=10,
            utm_source="yandex_direct",
            utm_medium="cpc",
            utm_campaign="Bankety_poisk_konversii",
            utm_term="---autotargeting",
            poll_seconds=0,
            max_polls=2,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["matching_mode"], "time_utm_heuristic")
        self.assertEqual(result["exact_yclid_match_available"], False)
        self.assertEqual(result["time_basis"], "ym:s:dateTime_as_counter_timezone_utc_plus_3")
        self.assertEqual(result["candidates_total"], 2)
        self.assertEqual(result["utm_filter_matches"], 2)
        self.assertEqual(result["nearest_candidates"][0]["ym:s:visitID"], "2")
        self.assertEqual(result["nearest_candidates"][0]["delta_seconds_from_lead_counter_tz"], -11)
        self.assertEqual(result["nearest_candidates"][0]["delta_seconds_from_lead_utc_field_as_utc"], -11)
        self.assertEqual(result["nearest_candidates"][0]["utm"]["ym:s:lastUTMCampaign"], "Bankety_poisk_konversii")
        self.assertEqual(result["utm_filter_nearest_candidates"][0]["ym:s:visitID"], "2")
        self.assertNotIn("ym:s:startURL", result["nearest_candidates"][0])
        self.assertEqual(client.evaluate_calls[0]["source"], "visits")
        self.assertEqual(client.create_calls[0]["source"], "visits")

    def test_visit_time_diagnostic_falls_back_to_counter_timezone_when_utc_missing(self):
        client = VisitTimeFakeClient(
            "ym:s:visitID\tym:s:dateTime\tym:s:dateTimeUTC\tym:s:clientID\tym:s:startURL\n"
            "4\t2026-09-03 16:49:31\t\tclient-d\thttps://example.test/\n"
        )

        result = time_mod.collect_visit_time_diagnostic(
            client,
            lead_timestamp_utc=1788443371,
            date1="2026-09-01",
            date2="2026-09-03",
            window_minutes=5,
            poll_seconds=0,
            max_polls=2,
        )

        self.assertEqual(result["candidates_total"], 1)
        self.assertEqual(result["nearest_candidates"][0]["delta_seconds_from_lead_counter_tz"], 0)


class VisitTimeFakeClient(FakeClient):
    def __init__(self, tsv: str) -> None:
        super().__init__()
        self._tsv = tsv

    def create_export(self, **kwargs):
        self.create_calls.append(kwargs)
        return mod.LogRequest(request_id=99, status="processed", parts=(0,))

    def download_part(self, request_id, part_number):
        self.download_calls.append((request_id, part_number))
        return self._tsv


if __name__ == "__main__":
    unittest.main()
