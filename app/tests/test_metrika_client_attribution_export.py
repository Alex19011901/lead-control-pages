from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from metrika_client_attribution_export import collect
from metrika_client_attribution_export import safe_rows


class MetrikaClientAttributionExportTests(unittest.TestCase):
    def test_safe_rows_hashes_client_id_and_keeps_direct_ids(self) -> None:
        client_id = "12345678901234567890"
        rows = [{
            "ym:s:clientID": client_id,
            "ym:s:dateTime": "2026-09-06 12:20:00",
            "ym:s:dateTimeUTC": "2026-09-06 12:20:00",
            "ym:s:visitDuration": "900",
            "ym:s:lastDirectClickOrder": "118776779",
            "ym:s:lastDirectBannerGroup": "5552984252",
            "ym:s:lastDirectClickBanner": "16902921501",
            "ym:s:lastDirectClickOrderName": "Search Wedding",
            "ym:s:lastClickBannerGroupName": "where wedding",
            "ym:s:lastDirectClickBannerName": "ad",
            "ym:s:lastDirectPlatformType": "search",
            "ym:s:lastDirectPlatform": "yandex",
        }]
        result = safe_rows(rows)
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertEqual(item["client_id_sha256"], hashlib.sha256(client_id.encode()).hexdigest())
        self.assertEqual(item["campaign_id"], "118776779")
        self.assertEqual(item["group_id"], "5552984252")
        self.assertEqual(item["ad_id"], "16902921501")
        self.assertEqual(item["visit_duration_seconds"], 900)
        self.assertEqual(item["id_source"], "direct_fields")
        self.assertNotIn(client_id, str(result))

    def test_safe_rows_keeps_utm_campaign_label_without_direct_ids(self) -> None:
        rows = [{
            "ym:s:clientID": "123",
            "ym:s:dateTime": "2026-09-05 10:00:00",
            "ym:s:visitDuration": "30",
            "ym:s:lastDirectClickOrder": "0",
            "ym:s:lastDirectBannerGroup": "0",
            "ym:s:lastDirectClickBanner": "0",
            "ym:s:lastUTMSource": "yandex_direct",
            "ym:s:lastUTMMedium": "cpc",
            "ym:s:lastUTMCampaign": "Svadba_poisk",
        }]
        result = safe_rows(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["utm_campaign"], "Svadba_poisk")
        self.assertEqual(result[0]["id_source"], "utm_campaign_label")
        self.assertEqual(result[0]["campaign_id"], "")

    def test_safe_rows_supports_automatic_attribution_fields(self) -> None:
        rows = [{
            "ym:s:clientID": "456",
            "ym:s:dateTime": "2026-09-14 13:18:50",
            "ym:s:dateTimeUTC": "2026-09-14 10:18:50",
            "ym:s:visitDuration": "60",
            "ym:s:automaticDirectClickOrder": "709907560",
            "ym:s:automaticDirectBannerGroup": "5750739685",
            "ym:s:automaticDirectClickBanner": "17718636795",
            "ym:s:automaticDirectClickOrderName": "Bankety search",
            "ym:s:automaticClickBannerGroupName": "banket group",
            "ym:s:automaticDirectClickBannerName": "banket ad",
            "ym:s:automaticDirectPhraseOrCond": "банкетный зал",
            "ym:s:automaticUTMSource": "yandex_direct",
            "ym:s:automaticUTMMedium": "cpc",
            "ym:s:automaticUTMCampaign": "Bankety_poisk_konversii",
        }]
        result = safe_rows(rows, attribution="AUTOMATIC")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["campaign_id"], "709907560")
        self.assertEqual(result[0]["group_id"], "5750739685")
        self.assertEqual(result[0]["ad_id"], "17718636795")
        self.assertEqual(result[0]["phrase_or_condition"], "банкетный зал")
        self.assertEqual(result[0]["utm_campaign"], "Bankety_poisk_konversii")

    def test_safe_rows_skips_rows_without_attribution_markers(self) -> None:
        rows = [{"ym:s:clientID": "123", "ym:s:lastDirectClickOrder": "0", "ym:s:lastDirectBannerGroup": "0", "ym:s:lastDirectClickBanner": ""}]
        self.assertEqual(safe_rows(rows), [])

    def test_collect_records_requested_attribution(self) -> None:
        class FakeClient:
            counter_id = 52597240

            def __init__(self) -> None:
                self.evaluate_attribution = ""
                self.export_attribution = ""

            def evaluate(self, **kwargs: object) -> None:
                self.evaluate_attribution = str(kwargs["attribution"])
                self.fields = tuple(kwargs["fields"])  # type: ignore[arg-type]

            def create_export(self, **kwargs: object):
                self.export_attribution = str(kwargs["attribution"])

                class Request:
                    request_id = 7
                    status = "processed"
                    parts = (0,)

                return Request()

            def download_part(self, _request_id: int, _part_number: int) -> str:
                return (
                    "ym:s:clientID\tym:s:dateTime\tym:s:automaticDirectClickOrder\n"
                    "456\t2026-09-14 13:18:50\t709907560\n"
                )

        client = FakeClient()
        payload = collect(client, date1="2026-09-14", date2="2026-09-14", poll_seconds=0, max_polls=0, attribution="AUTOMATIC")
        self.assertEqual(client.evaluate_attribution, "AUTOMATIC")
        self.assertEqual(client.export_attribution, "AUTOMATIC")
        self.assertIn("ym:s:automaticDirectClickOrder", client.fields)
        self.assertEqual(payload["attribution"], "AUTOMATIC")
        self.assertEqual(payload["mapped_rows"], 1)


if __name__ == "__main__":
    unittest.main()
