from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

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

    def test_safe_rows_skips_rows_without_attribution_markers(self) -> None:
        rows = [{"ym:s:clientID": "123", "ym:s:lastDirectClickOrder": "0", "ym:s:lastDirectBannerGroup": "0", "ym:s:lastDirectClickBanner": ""}]
        self.assertEqual(safe_rows(rows), [])


if __name__ == "__main__":
    unittest.main()
