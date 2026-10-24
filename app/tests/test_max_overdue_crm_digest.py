"""Offline tests for a 09:00 Moscow MAX message with only overdue CRM leads."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import max_overdue_crm_digest as digest

MOSCOW = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 10, 25, 9, tzinfo=MOSCOW)


def lead(day: int, hour: int, *, name: str = "Анна", phone: str = "79991112233",
         status: str = "ALARM_NO_CRM", duplicate: bool = False) -> dict:
    ts = datetime(2026, 10, day, hour, 15, tzinfo=MOSCOW)
    return {
        "id": f"test-{day}-{hour}-{phone}",
        "first_seen_at": ts.isoformat(),
        "first_seen_ts": int(ts.timestamp()),
        "status": status,
        "crm_required": True,
        "is_duplicate": duplicate,
        "crm": {"found": False},
        "source": "Заявки хост",
        "identifier": {"type": "phone", "value": phone},
        "fields": {"name": name},
    }


class FakeCRMResult:
    def __init__(self, found: bool):
        self.found = found
    def as_dict(self):
        return {"found": self.found, "entity_type": "lead", "entity_id": 1234}


class DigestTests(unittest.TestCase):
    def test_only_expired_nonduplicate_leads(self):
        rows = [
            lead(24, 14),
            lead(24, 21),  # deadline 25 Oct at 16:00: NOT late at 09:00
            lead(23, 21),  # deadline 24 Oct at 16:00: late
            lead(23, 14, duplicate=True),
            lead(23, 14, status="LATE_CRM"),
        ]
        selected = digest.overdue_candidates(rows, NOW)
        self.assertEqual([x["first_seen_at"][11:13] for x in selected], ["21", "14"])
        self.assertEqual([x["first_seen_at"][:10] for x in selected], ["2026-10-23", "2026-10-24"])

    def test_legacy_dashboard_exclusions(self):
        old = lead(24, 14, phone="79636698819")
        old["first_seen_at"] = "2026-08-24T14:15:00+03:00"
        old["first_seen_ts"] = int(datetime(2026, 8, 24, 14, 15, tzinfo=MOSCOW).timestamp())
        self.assertEqual(digest.overdue_candidates([old], NOW), [])

    def test_recheck_skips_newly_entered_crm_lead(self):
        client = Mock()
        client.search.side_effect = [FakeCRMResult(True), FakeCRMResult(False)]
        result = digest.still_missing([lead(23, 14), lead(24, 14)], client)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["first_seen_at"][:10], "2026-10-24")
        self.assertEqual(client.search.call_count, 2)

    def test_crm_error_aborts_without_false_alarm(self):
        client = Mock()
        client.search.side_effect = RuntimeError("Unavailable")
        with self.assertRaisesRegex(RuntimeError, "CRM verification failed"):
            digest.still_missing([lead(24, 14)], client)

    def test_approved_text(self):
        text = digest.message_for([lead(23, 21), lead(24, 14)], NOW)
        self.assertIn("LEAD CONTROL — НЕ ВНЕСЕНЫ В CRM", text)
        self.assertIn("25.10.2026 | 09:00 МСК", text)
        self.assertIn("Просрочено: 2 заявки", text)
        self.assertIn("23.10 в 21:15", text)
        self.assertIn("24.10 до 16:00", text)
        self.assertIn("+7 999 111-22-33", text)
        self.assertIn("Открыть Lead Control", text)

    def test_more_than_four_thousand_characters(self):
        rows = [lead(23, 14, phone=f"7999000{i:04d}", name="Ирина" * 20) for i in range(100)]
        text = digest.message_for(rows, NOW)
        self.assertLessEqual(len(text), 4000)
        self.assertIn("Просрочено: 100 заявок", text)
        self.assertIn("Полный список — в Lead Control", text)

    def test_max_post_uses_existing_group_and_no_bearer_prefix(self):
        class Reply:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps({"message": {"body": {"mid": "mid.abc"}}}).encode()
        with patch.object(digest, "_ssl_context", return_value=None), \
             patch.object(digest.urllib.request, "urlopen", return_value=Reply()) as request_mock:
            mid = digest.send_max_message("Привет", "secret", -123456, Path("ca.pem"))
        self.assertEqual(mid, "mid.abc")
        request = request_mock.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertIn("chat_id=-123456", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "secret")
        payload = json.loads(request.data)
        self.assertEqual(payload["text"], "Привет")
        self.assertEqual(payload["format"], "markdown")

    def test_zero_alerts_is_silent_and_marks_day_done(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            leads, snapshot, state = root / "leads.json", root / "view.json", root / "state.json"
            leads.write_text(json.dumps({"leads": [lead(24, 21)]}), encoding="utf-8")
            snapshot.write_text(json.dumps({"snapshot_generated_at": "2026-10-25T05:00:00Z"}), encoding="utf-8")
            kwargs = dict(leads_path=leads, snapshot_path=snapshot, state_path=state,
                          token="test", crm_token="test", crm_domain="https://example.com",
                          chat_id=123, ca_file=root / "ca.pem", now=NOW)
            with patch.object(digest, "send_max_message") as send:
                self.assertIn("still missing 0", digest.execute(**kwargs))
                self.assertIn("Already checked today", digest.execute(**kwargs))
                send.assert_not_called()
            self.assertFalse(json.loads(state.read_text())["last_sent"])

    def test_verified_overdue_sends_once(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            leads, snapshot, state = root / "leads.json", root / "view.json", root / "state.json"
            leads.write_text(json.dumps({"leads": [lead(24, 14)]}), encoding="utf-8")
            snapshot.write_text(json.dumps({"snapshot_generated_at": "2026-10-25T05:00:00Z"}), encoding="utf-8")
            kwargs = dict(leads_path=leads, snapshot_path=snapshot, state_path=state,
                          token="test", crm_token="test", crm_domain="https://example.com",
                          chat_id=123, ca_file=root / "ca.pem", now=NOW)
            with patch.object(digest, "AmoCRMClient") as crm, \
                 patch.object(digest, "send_max_message", return_value="mid.sent") as send:
                crm.return_value.search.return_value = FakeCRMResult(False)
                self.assertIn("alert sent: True", digest.execute(**kwargs))
                self.assertIn("Already checked today", digest.execute(**kwargs))
                send.assert_called_once()
            saved = json.loads(state.read_text())
            self.assertEqual(saved["last_count"], 1)
            self.assertEqual(saved["last_message_id"], "mid.sent")

    def test_stale_snapshot_suppresses_alert(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            leads, snapshot, state = root / "leads.json", root / "view.json", root / "state.json"
            leads.write_text(json.dumps({"leads": [lead(24, 14)]}), encoding="utf-8")
            snapshot.write_text(json.dumps({"snapshot_generated_at": "2026-10-24T05:00:00Z"}), encoding="utf-8")
            with patch.object(digest, "send_max_message") as send:
                with self.assertRaisesRegex(RuntimeError, "snapshot is missing"):
                    digest.execute(leads_path=leads, snapshot_path=snapshot, state_path=state,
                                   token="test", crm_token="test", crm_domain="https://example.com",
                                   chat_id=123, ca_file=root / "ca.pem", now=NOW)
                send.assert_not_called()
            self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main()
