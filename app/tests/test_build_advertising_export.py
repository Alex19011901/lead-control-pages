from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_advertising_export.py"


class AdvertisingExportTests(unittest.TestCase):
    def test_export_is_anonymized_and_starts_from_cutoff(self) -> None:
        yclid = "TEST_YCLID_20260905_1434"
        client_id = "12345678901234567890"
        payload = {
            "schema_version": 1,
            "leads": [
                {
                    "id": "old",
                    "first_seen_at": "2026-09-04T12:00:00+03:00",
                    "first_seen_ts": 1,
                    "source": "САЙТ ТИЛЬДА",
                    "channel": "TELEGRAM",
                    "identifier": {"type": "phone", "value": "79999999999"},
                    "fields": {"name": "Old", "phone_raw": "+79999999999", "yclid": "OLD"},
                },
                {
                    "id": "newhash",
                    "first_seen_at": "2026-09-05T14:53:52+03:00",
                    "first_seen_ts": 1788612832,
                    "source": "САЙТ ТИЛЬДА",
                    "channel": "TELEGRAM",
                    "identifier": {"type": "phone", "value": "79265350168"},
                    "fields": {
                        "name": "Test",
                        "phone_raw": "+79265350168",
                        "yclid": yclid,
                        "metrika_client_id": client_id,
                        "event_type": "Свадьба",
                        "description": (
                            "private text\n"
                            "UTM source: yandex_search\n"
                            "UTM medium: cpc\n"
                            "UTM campaign: Search_Main\n"
                            "UTM content: search|cid|707720217|gid|5724131407|aid|17630916799|dvc|desktop\n"
                            "UTM term: potentially sensitive query\n"
                        ),
                    },
                    "status": "PENDING",
                    "crm": {"found": True, "status_name": "Первичный контакт"},
                    "crm_found": True,
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "leads.json"
            output = Path(tmp) / "advertising_leads.json"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            subprocess.run(
                [sys.executable, str(SCRIPT), "--input", str(source), "--output", str(output), "--start-date", "2026-09-05"],
                check=True,
            )
            result = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result["schema_version"], 5)
        self.assertEqual(result["lead_count"], 1)
        item = result["leads"][0]
        self.assertEqual(item["lead_id"], "newhash")
        self.assertTrue(item["has_yclid"])
        self.assertEqual(item["yclid_sha256"], hashlib.sha256(yclid.encode()).hexdigest())
        self.assertTrue(item["has_metrika_client_id"])
        self.assertEqual(item["metrika_client_id_sha256"], hashlib.sha256(client_id.encode()).hexdigest())
        self.assertEqual(item["crm_status"], "Первичный контакт")
        self.assertEqual(item["campaign_id"], "707720217")
        self.assertEqual(item["group_id"], "5724131407")
        self.assertEqual(item["ad_id"], "17630916799")
        self.assertEqual(item["advertising_id_source"], "utm_content")
        self.assertFalse(item["has_callibri"])
        self.assertEqual(item["utm_campaign"], "Search_Main")
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("79265350168", serialized)
        self.assertNotIn("private text", serialized)
        self.assertNotIn("potentially sensitive query", serialized)
        self.assertNotIn(yclid, serialized)
        self.assertNotIn(client_id, serialized)
        self.assertNotIn('"name"', serialized)
        self.assertNotIn('"identifier"', serialized)

    def test_export_parses_callibri_ids_without_raw_payload(self) -> None:
        payload = {
            "schema_version": 1,
            "leads": [
                {
                    "id": "callibri-lead",
                    "first_seen_at": "2026-09-05T16:10:00+03:00",
                    "first_seen_ts": 1788617400,
                    "source": "MARQUIZ",
                    "channel": "WEB",
                    "fields": {
                        "description": (
                            "https://example.test/?callibri=yd_c:712849433_gb:5773918659_"
                            "ad:1915822986185365500_ph:205773918659_st:search"
                            "&utm_source=yandex_direct&utm_medium=cpc&utm_campaign=Bankety_poisk_quiz"
                            "&keyword=%D1%80%D0%B5%D1%81%D1%82%D0%BE%D1%80%D0%B0%D0%BD"
                        ),
                    },
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "leads.json"
            output = Path(tmp) / "advertising_leads.json"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            subprocess.run(
                [sys.executable, str(SCRIPT), "--input", str(source), "--output", str(output), "--start-date", "2026-09-05"],
                check=True,
            )
            result = json.loads(output.read_text(encoding="utf-8"))

        item = result["leads"][0]
        self.assertTrue(item["has_callibri"])
        self.assertEqual(item["advertising_id_source"], "callibri")
        self.assertEqual(item["campaign_id"], "712849433")
        self.assertEqual(item["group_id"], "5773918659")
        self.assertEqual(item["ad_id"], "1915822986185365500")
        self.assertEqual(item["utm_source"], "yandex_direct")
        self.assertEqual(item["utm_medium"], "cpc")
        self.assertEqual(item["utm_campaign"], "Bankety_poisk_quiz")
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("205773918659", serialized)
        self.assertNotIn("ресторан", serialized)

    def test_export_accepts_client_id_alias_from_fields_and_description(self) -> None:
        payload = {
            "schema_version": 1,
            "leads": [
                {
                    "id": "ymuid-field",
                    "first_seen_at": "2026-09-05T14:53:52+03:00",
                    "first_seen_ts": 1788612832,
                    "source": "САЙТ ТИЛЬДА",
                    "fields": {"_ym_uid": "111222333444555666", "phone_raw": "+79265350168"},
                },
                {
                    "id": "yandex-description",
                    "first_seen_at": "2026-09-05T15:53:52+03:00",
                    "first_seen_ts": 1788616432,
                    "source": "САЙТ ТИЛЬДА",
                    "fields": {
                        "phone_raw": "+79265350169",
                        "description": "Yandex Client ID: 777888999000111222\n",
                    },
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "leads.json"
            output = Path(tmp) / "advertising_leads.json"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            subprocess.run(
                [sys.executable, str(SCRIPT), "--input", str(source), "--output", str(output), "--start-date", "2026-09-05"],
                check=True,
            )
            result = json.loads(output.read_text(encoding="utf-8"))

        by_id = {item["lead_id"]: item for item in result["leads"]}
        self.assertTrue(by_id["ymuid-field"]["has_metrika_client_id"])
        self.assertEqual(
            by_id["ymuid-field"]["metrika_client_id_sha256"],
            hashlib.sha256("111222333444555666".encode()).hexdigest(),
        )
        self.assertTrue(by_id["yandex-description"]["has_metrika_client_id"])
        self.assertEqual(
            by_id["yandex-description"]["metrika_client_id_sha256"],
            hashlib.sha256("777888999000111222".encode()).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
