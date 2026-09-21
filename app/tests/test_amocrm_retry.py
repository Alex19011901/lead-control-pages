from __future__ import annotations

import io
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.amocrm_client import AmoCRMClient


class FakeResponse:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self.payload


class CountingAmoCRMClient(AmoCRMClient):
    def __init__(self) -> None:
        super().__init__("https://example.amocrm.ru", "token")
        self.calls = 0

    def _request_json(self, path, params):
        self.calls += 1
        entity = path.rsplit("/", 1)[-1]
        return {"_embedded": {entity: [{"id": 1}]}} if path.count("/") == 3 else {"id": 1}


class AmoCRMRetryTests(unittest.TestCase):
    def test_retries_http_429_then_succeeds(self) -> None:
        client = AmoCRMClient("https://example.amocrm.ru", "token")
        error = urllib.error.HTTPError(
            "https://example.amocrm.ru/api/v4/leads",
            429,
            "Too Many Requests",
            {"Retry-After": "0"},
            io.BytesIO(),
        )
        response = FakeResponse(b'{"ok": true}')

        with patch("lead_control.amocrm_client.urllib.request.urlopen", side_effect=[error, response]) as urlopen:
            with patch("lead_control.amocrm_client.time.sleep") as sleep:
                payload = client._request_json("/api/v4/leads", {})

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(0.0)

    def test_does_not_retry_non_transient_http_error(self) -> None:
        client = AmoCRMClient("https://example.amocrm.ru", "token")
        error = urllib.error.HTTPError(
            "https://example.amocrm.ru/api/v4/leads",
            401,
            "Unauthorized",
            {},
            io.BytesIO(),
        )

        with patch("lead_control.amocrm_client.urllib.request.urlopen", side_effect=error) as urlopen:
            with patch("lead_control.amocrm_client.time.sleep") as sleep:
                with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
                    client._request_json("/api/v4/leads", {})

        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

    def test_retries_transient_network_error_then_succeeds(self) -> None:
        client = AmoCRMClient("https://example.amocrm.ru", "token")
        response = FakeResponse(b'{"ok": true}')

        with patch(
            "lead_control.amocrm_client.urllib.request.urlopen",
            side_effect=[urllib.error.URLError("temporary"), response],
        ) as urlopen:
            with patch("lead_control.amocrm_client.time.sleep") as sleep:
                payload = client._request_json("/api/v4/leads", {})

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(1.0)

    def test_search_collection_is_cached_within_run(self) -> None:
        client = CountingAmoCRMClient()

        first = client._search_collection("leads", "79990000000", None)
        second = client._search_collection("leads", "79990000000", None)

        self.assertEqual(first, second)
        self.assertEqual(client.calls, 1)


if __name__ == "__main__":
    unittest.main()
