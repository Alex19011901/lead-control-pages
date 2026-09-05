from __future__ import annotations

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
                        "description": "private text",
                        "yclid": "TEST_YCLID_20260905_1434",
                        "event_type": "Свадьба",
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

        self.assertEqual(result["lead_count"], 1)
        self.assertEqual(result["leads"][0]["lead_id"], "newhash")
        self.assertEqual(result["leads"][0]["yclid"], "TEST_YCLID_20260905_1434")
        self.assertEqual(result["leads"][0]["crm_status"], "Первичный контакт")
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("79265350168", serialized)
        self.assertNotIn("private text", serialized)
        self.assertNotIn('"name"', serialized)
        self.assertNotIn('"identifier"', serialized)


if __name__ == "__main__":
    unittest.main()
