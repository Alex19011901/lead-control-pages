from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.normalize import moscow_day_deadline_ts
from lead_control.status_policy import apply_crm_day_status_policy


MSK = ZoneInfo("Europe/Moscow")


class StatusPolicyTests(unittest.TestCase):
    def test_missing_crm_same_day_is_pending(self) -> None:
        lead = _lead("TELEGRAM", "2026-08-21T09:00:00+03:00", found=False)

        apply_crm_day_status_policy([lead], now_ts=_ts("2026-08-21T21:00:00+03:00"))

        self.assertEqual(lead["status"], "PENDING")
        self.assertEqual(lead["violations"], [])

    def test_lead_before_2000_is_alarm_after_midnight(self) -> None:
        lead = _lead("MAX", "2026-08-21T19:59:59+03:00", found=False)

        apply_crm_day_status_policy([lead], now_ts=_ts("2026-08-22T00:00:00+03:00"))

        self.assertEqual(lead["status"], "ALARM_NO_CRM")
        self.assertEqual(lead["violations"], ["ALARM_NO_CRM"])

    def test_lead_at_2000_stays_pending_until_next_day_1600(self) -> None:
        lead = _lead("MAX", "2026-08-21T20:00:00+03:00", found=False)

        apply_crm_day_status_policy([lead], now_ts=_ts("2026-08-22T16:00:00+03:00"))

        self.assertEqual(lead["status"], "PENDING")
        self.assertEqual(lead["violations"], [])

    def test_lead_after_2000_is_alarm_after_next_day_1600(self) -> None:
        lead = _lead("MAX", "2026-08-21T23:50:00+03:00", found=False)

        apply_crm_day_status_policy([lead], now_ts=_ts("2026-08-22T16:00:01+03:00"))

        self.assertEqual(lead["status"], "ALARM_NO_CRM")
        self.assertEqual(lead["violations"], ["ALARM_NO_CRM"])

    def test_stored_deadline_before_2000_is_same_day_235959(self) -> None:
        deadline = moscow_day_deadline_ts(_ts("2026-08-21T19:59:59+03:00"))

        self.assertEqual(deadline, _ts("2026-08-21T23:59:59+03:00"))

    def test_stored_deadline_at_2000_is_next_day_1600(self) -> None:
        deadline = moscow_day_deadline_ts(_ts("2026-08-21T20:00:00+03:00"))

        self.assertEqual(deadline, _ts("2026-08-22T16:00:00+03:00"))

    def test_crm_created_same_day_at_235959_is_ok(self) -> None:
        lead = _lead(
            "TELEGRAM",
            "2026-08-21T09:00:00+03:00",
            found=True,
            crm_created_at="2026-08-21T23:59:59+03:00",
        )

        apply_crm_day_status_policy([lead], now_ts=_ts("2026-08-22T10:00:00+03:00"))

        self.assertEqual(lead["status"], "OK")
        self.assertEqual(lead["violations"], [])

    def test_crm_created_next_day_at_midnight_is_late_for_daytime_lead(self) -> None:
        lead = _lead(
            "MAX",
            "2026-08-21T09:00:00+03:00",
            found=True,
            crm_created_at="2026-08-22T00:00:00+03:00",
        )

        apply_crm_day_status_policy([lead], now_ts=_ts("2026-08-22T10:00:00+03:00"))

        self.assertEqual(lead["status"], "LATE_CRM")
        self.assertEqual(lead["violations"], ["LATE_CRM"])

    def test_evening_lead_created_next_day_at_160000_is_ok(self) -> None:
        lead = _lead(
            "MAX",
            "2026-08-21T20:00:00+03:00",
            found=True,
            crm_created_at="2026-08-22T16:00:00+03:00",
        )

        apply_crm_day_status_policy([lead], now_ts=_ts("2026-08-22T17:00:00+03:00"))

        self.assertEqual(lead["status"], "OK")
        self.assertEqual(lead["violations"], [])

    def test_evening_lead_created_next_day_after_160000_is_late(self) -> None:
        lead = _lead(
            "MAX",
            "2026-08-21T20:00:00+03:00",
            found=True,
            crm_created_at="2026-08-22T16:00:01+03:00",
        )

        apply_crm_day_status_policy([lead], now_ts=_ts("2026-08-22T17:00:00+03:00"))

        self.assertEqual(lead["status"], "LATE_CRM")
        self.assertEqual(lead["violations"], ["LATE_CRM"])

    def test_not_entered_changes_to_late_when_crm_appears_later(self) -> None:
        lead = _lead("TELEGRAM", "2026-08-21T09:00:00+03:00", found=False)

        apply_crm_day_status_policy([lead], now_ts=_ts("2026-08-22T10:00:00+03:00"))
        self.assertEqual(lead["status"], "ALARM_NO_CRM")
        self.assertEqual(lead["violations"], ["ALARM_NO_CRM"])

        lead["crm"] = {
            "found": True,
            "created_at": _ts("2026-08-23T14:30:00+03:00"),
        }
        apply_crm_day_status_policy([lead], now_ts=_ts("2026-08-23T15:00:00+03:00"))

        self.assertEqual(lead["status"], "LATE_CRM")
        self.assertEqual(lead["violations"], ["LATE_CRM"])

    def test_reaction_does_not_affect_telegram_status(self) -> None:
        without_reaction = _lead("TELEGRAM", "2026-08-21T10:00:00+03:00", found=False)
        with_reaction = _lead("TELEGRAM", "2026-08-21T10:00:00+03:00", found=False)
        with_reaction["manager_reaction"] = {"name": "Максим"}

        apply_crm_day_status_policy(
            [without_reaction, with_reaction],
            now_ts=_ts("2026-08-21T20:00:00+03:00"),
        )

        self.assertEqual(without_reaction["status"], "PENDING")
        self.assertEqual(with_reaction["status"], "PENDING")
        self.assertNotIn("NO_REACTION", without_reaction["violations"])
        self.assertNotIn("NO_REACTION", with_reaction["violations"])

    def test_max_and_telegram_use_same_missing_crm_rule(self) -> None:
        telegram = _lead("TELEGRAM", "2026-08-20T10:00:00+03:00", found=False)
        max_lead = _lead("MAX", "2026-08-20T10:00:00+03:00", found=False)

        apply_crm_day_status_policy(
            [telegram, max_lead],
            now_ts=_ts("2026-08-21T10:00:00+03:00"),
        )

        self.assertEqual(telegram["status"], "ALARM_NO_CRM")
        self.assertEqual(max_lead["status"], "ALARM_NO_CRM")

    def test_crm_not_required_is_neutral_dash(self) -> None:
        lead = _lead("MAX", "2026-08-20T10:00:00+03:00", found=False)
        lead["crm_required"] = False

        apply_crm_day_status_policy([lead], now_ts=_ts("2026-08-21T10:00:00+03:00"))

        self.assertEqual(lead["status"], "-")
        self.assertEqual(lead["violations"], [])

    def test_no_identifier_is_neutral_dash(self) -> None:
        lead = _lead("TELEGRAM", "2026-08-21T10:00:00+03:00", found=False)
        lead["crm_check_status"] = "NO_IDENTIFIER"

        apply_crm_day_status_policy([lead], now_ts=_ts("2026-08-22T10:00:00+03:00"))

        self.assertEqual(lead["status"], "-")
        self.assertEqual(lead["violations"], [])


def _lead(
    channel: str,
    received_at: str,
    *,
    found: bool,
    crm_created_at: str | None = None,
) -> dict[str, object]:
    crm: dict[str, object] = {"found": found}
    if crm_created_at:
        crm["created_at"] = _ts(crm_created_at)
    return {
        "channel": channel,
        "crm_required": True,
        "first_seen_ts": _ts(received_at),
        "received_at": received_at,
        "crm": crm,
        "status": "PENDING",
        "violations": ["NO_REACTION"],
        "manager_reaction": None,
    }


def _ts(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp())


if __name__ == "__main__":
    unittest.main()
