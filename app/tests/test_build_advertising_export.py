from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_advertising_export.py"
CALLIBRI_IMPORT_SCRIPT = ROOT / "scripts" / "import_callibri_calls.py"


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

        self.assertEqual(result["schema_version"], 6)
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

    def test_hostess_lead_matches_single_callibri_call_by_phone_and_time(self) -> None:
        payload = {
            "schema_version": 1,
            "leads": [
                {
                    "id": "host-call",
                    "first_seen_at": "2026-09-17T14:11:49+03:00",
                    "first_seen_ts": 1790000000,
                    "source": "Заявки хост",
                    "channel": "MAX",
                    "identifier": {"type": "phone", "value": "79054025777"},
                    "fields": {"phone_raw": "89054025777", "event_type": "Корпоратив"},
                },
            ],
        }
        callibri = {
            "schema_version": 1,
            "status": "ok",
            "calls": [
                {
                    "call_id_sha256": hashlib.sha256("call-1".encode()).hexdigest(),
                    "started_at": "2026-09-17T14:05:00+03:00",
                    "phone_sha256": hashlib.sha256("79054025777".encode()).hexdigest(),
                    "utm_source": "yandex_direct",
                    "utm_medium": "cpc",
                    "utm_campaign": "Bankety_poisk_quiz",
                    "utm_term": "банкетный зал",
                    "campaign_id": "712849433",
                    "group_id": "5773918677",
                    "ad_id": "1915822986185365518",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "leads.json"
            calls = Path(tmp) / "callibri_calls.json"
            output = Path(tmp) / "advertising_leads.json"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            calls.write_text(json.dumps(callibri, ensure_ascii=False), encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--start-date",
                    "2026-09-05",
                    "--callibri-calls",
                    str(calls),
                ],
                check=True,
            )
            result = json.loads(output.read_text(encoding="utf-8"))

        item = result["leads"][0]
        self.assertEqual(result["callibri_calls_loaded"], 1)
        self.assertTrue(item["has_callibri"])
        self.assertEqual(item["callibri_match_status"], "matched")
        self.assertEqual(item["advertising_id_source"], "callibri_phone_time_match")
        self.assertEqual(item["campaign_id"], "712849433")
        self.assertEqual(item["group_id"], "5773918677")
        self.assertEqual(item["ad_id"], "1915822986185365518")
        self.assertEqual(item["utm_term"], "банкетный зал")
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("79054025777", serialized)
        self.assertNotIn("89054025777", serialized)

    def test_hostess_lead_does_not_guess_ambiguous_callibri_calls(self) -> None:
        payload = {
            "schema_version": 1,
            "leads": [
                {
                    "id": "host-call",
                    "first_seen_at": "2026-09-17T14:11:49+03:00",
                    "first_seen_ts": 1790000000,
                    "source": "Заявки хост",
                    "identifier": {"type": "phone", "value": "79054025777"},
                    "fields": {"phone_raw": "89054025777"},
                },
            ],
        }
        phone_hash = hashlib.sha256("79054025777".encode()).hexdigest()
        callibri = {
            "schema_version": 1,
            "status": "ok",
            "calls": [
                {"started_at": "2026-09-17T14:01:00+03:00", "phone_sha256": phone_hash, "campaign_id": "1"},
                {"started_at": "2026-09-17T14:05:00+03:00", "phone_sha256": phone_hash, "campaign_id": "2"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "leads.json"
            calls = Path(tmp) / "callibri_calls.json"
            output = Path(tmp) / "advertising_leads.json"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            calls.write_text(json.dumps(callibri, ensure_ascii=False), encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--start-date",
                    "2026-09-05",
                    "--callibri-calls",
                    str(calls),
                ],
                check=True,
            )
            result = json.loads(output.read_text(encoding="utf-8"))

        item = result["leads"][0]
        self.assertEqual(item["callibri_match_status"], "ambiguous_callibri_calls")
        self.assertEqual(item["callibri_candidate_count"], 2)
        self.assertEqual(item["campaign_id"], "")
        self.assertEqual(item["advertising_id_source"], "")

    def test_hostess_lead_reports_phone_missing_from_callibri(self) -> None:
        payload = {
            "schema_version": 1,
            "leads": [
                {
                    "id": "host-call",
                    "first_seen_at": "2026-09-17T14:11:49+03:00",
                    "first_seen_ts": 1790000000,
                    "source": "Заявки хост",
                    "identifier": {"type": "phone", "value": "79054025777"},
                    "fields": {"phone_raw": "89054025777"},
                },
            ],
        }
        other_phone_hash = hashlib.sha256("79160000000".encode()).hexdigest()
        callibri = {
            "schema_version": 1,
            "status": "ok",
            "calls": [
                {"started_at": "2026-09-17T14:05:00+03:00", "phone_sha256": other_phone_hash, "campaign_id": "1"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "leads.json"
            calls = Path(tmp) / "callibri_calls.json"
            output = Path(tmp) / "advertising_leads.json"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            calls.write_text(json.dumps(callibri, ensure_ascii=False), encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--start-date",
                    "2026-09-05",
                    "--callibri-calls",
                    str(calls),
                ],
                check=True,
            )
            result = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result["leads"][0]["callibri_match_status"], "no_callibri_phone_match")

    def test_hostess_lead_reports_nearest_callibri_call_outside_window(self) -> None:
        payload = {
            "schema_version": 1,
            "leads": [
                {
                    "id": "host-call",
                    "first_seen_at": "2026-09-17T14:11:49+03:00",
                    "first_seen_ts": 1790000000,
                    "source": "Заявки хост",
                    "identifier": {"type": "phone", "value": "79054025777"},
                    "fields": {"phone_raw": "89054025777"},
                },
            ],
        }
        callibri = {
            "schema_version": 1,
            "status": "ok",
            "calls": [
                {
                    "started_at": "2026-09-17T01:00:00+03:00",
                    "phone_sha256": hashlib.sha256("79054025777".encode()).hexdigest(),
                    "campaign_id": "1",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "leads.json"
            calls = Path(tmp) / "callibri_calls.json"
            output = Path(tmp) / "advertising_leads.json"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            calls.write_text(json.dumps(callibri, ensure_ascii=False), encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--start-date",
                    "2026-09-05",
                    "--callibri-calls",
                    str(calls),
                ],
                check=True,
            )
            result = json.loads(output.read_text(encoding="utf-8"))

        item = result["leads"][0]
        self.assertEqual(item["callibri_match_status"], "nearest_call_outside_window")
        self.assertGreater(item["callibri_nearest_delta_seconds"], 12 * 3600)

    def test_hostess_lead_does_not_attribute_unconfirmed_callibri_tracking(self) -> None:
        payload = {
            "schema_version": 1,
            "leads": [
                {
                    "id": "host-call",
                    "first_seen_at": "2026-09-17T14:11:49+03:00",
                    "first_seen_ts": 1790000000,
                    "source": "Заявки хост",
                    "identifier": {"type": "phone", "value": "79054025777"},
                    "fields": {"phone_raw": "89054025777"},
                },
            ],
        }
        callibri = {
            "schema_version": 1,
            "status": "ok",
            "calls": [
                {
                    "started_at": "2026-09-17T14:05:00+03:00",
                    "phone_sha256": hashlib.sha256("79054025777".encode()).hexdigest(),
                    "tracking_accurate": False,
                    "campaign_id": "712849433",
                    "group_id": "5773918677",
                    "ad_id": "1915822986185365518",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "leads.json"
            calls = Path(tmp) / "callibri_calls.json"
            output = Path(tmp) / "advertising_leads.json"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            calls.write_text(json.dumps(callibri, ensure_ascii=False), encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--start-date",
                    "2026-09-05",
                    "--callibri-calls",
                    str(calls),
                ],
                check=True,
            )
            result = json.loads(output.read_text(encoding="utf-8"))

        item = result["leads"][0]
        self.assertTrue(item["has_callibri"])
        self.assertEqual(item["callibri_match_status"], "matched_unconfirmed_tracking")
        self.assertIs(item["callibri_tracking_accurate"], False)
        self.assertEqual(item["campaign_id"], "")
        self.assertEqual(item["group_id"], "")
        self.assertEqual(item["ad_id"], "")
        self.assertEqual(item["advertising_id_source"], "")

    def test_import_callibri_calls_accepts_csv_and_hashes_phone(self) -> None:
        csv_text = (
            "phone;started_at;callibri;utm_source;utm_medium;utm_campaign;duration\n"
            "+7 905 402-57-77;2026-09-17 14:05:00;"
            "yd_c:712849433_gb:5773918677_ad:1915822986185365518_ph:111;"
            "yandex_direct;cpc;Bankety_poisk_quiz;01:12\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "callibri.csv"
            output = Path(tmp) / "callibri_calls.json"
            source.write_text(csv_text, encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    str(CALLIBRI_IMPORT_SCRIPT),
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--date-from",
                    "2026-09-05",
                ],
                check=True,
            )
            result = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["call_count"], 1)
        item = result["calls"][0]
        self.assertEqual(item["phone_sha256"], hashlib.sha256("79054025777".encode()).hexdigest())
        self.assertEqual(item["campaign_id"], "712849433")
        self.assertEqual(item["group_id"], "5773918677")
        self.assertEqual(item["ad_id"], "1915822986185365518")
        self.assertEqual(item["duration_seconds"], 72)
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("79054025777", serialized)
        self.assertNotIn("+7 905", serialized)

    def test_import_callibri_calls_accepts_single_l_env_alias(self) -> None:
        csv_text = (
            "phone;started_at;callibri\n"
            "+7 905 402-57-77;2026-09-17 14:05:00;"
            "yd_c:712849433_gb:5773918677_ad:1915822986185365518\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "callibri.csv"
            output = Path(tmp) / "callibri_calls.json"
            source.write_text(csv_text, encoding="utf-8")
            env = dict(os.environ)
            env.pop("CALLIBRI_CALLS_FILE", None)
            env["CALIBRI_CALLS_FILE"] = str(source)
            subprocess.run(
                [
                    sys.executable,
                    str(CALLIBRI_IMPORT_SCRIPT),
                    "--output",
                    str(output),
                    "--date-from",
                    "2026-09-05",
                ],
                check=True,
                env=env,
            )
            result = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["call_count"], 1)
        self.assertEqual(result["calls"][0]["campaign_id"], "712849433")

    def test_import_callibri_calls_accepts_official_statistics_payload(self) -> None:
        payload = {
            "channels_statistics": [
                {
                    "name_channel": "Динамический коллтрекинг",
                    "number": "+74950000000",
                    "calls": [
                        {
                            "id": "call-1",
                            "date": "17.09.2026 14:05",
                            "phone": "+7 905 402-57-77",
                            "status": "Лид",
                            "call_status": "Успешный звонок",
                            "accurately": "да",
                            "source": "yandex_direct",
                            "query": "банкетный зал",
                            "metrika_client_id": "12345678901234567890",
                            "utm_source": "yandex_direct",
                            "utm_medium": "cpc",
                            "utm_campaign": "Bankety_poisk_quiz",
                            "utm_content": "search|cid|712849433|gid|5773918677|aid|1915822986185365518",
                        },
                    ],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "callibri.json"
            output = Path(tmp) / "callibri_calls.json"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    str(CALLIBRI_IMPORT_SCRIPT),
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--date-from",
                    "2026-09-05",
                ],
                check=True,
            )
            result = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["call_count"], 1)
        item = result["calls"][0]
        self.assertEqual(item["call_id_sha256"], hashlib.sha256("call-1".encode()).hexdigest())
        self.assertEqual(item["phone_sha256"], hashlib.sha256("79054025777".encode()).hexdigest())
        self.assertEqual(item["metrika_client_id_sha256"], hashlib.sha256("12345678901234567890".encode()).hexdigest())
        self.assertIs(item["tracking_accurate"], True)
        self.assertEqual(item["utm_source"], "yandex_direct")
        self.assertEqual(item["utm_medium"], "cpc")
        self.assertEqual(item["utm_campaign"], "Bankety_poisk_quiz")
        self.assertEqual(item["utm_term"], "банкетный зал")
        self.assertEqual(item["campaign_id"], "712849433")
        self.assertEqual(item["group_id"], "5773918677")
        self.assertEqual(item["ad_id"], "1915822986185365518")
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("79054025777", serialized)
        self.assertNotIn("+7 905", serialized)
        self.assertNotIn("12345678901234567890", serialized)

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
