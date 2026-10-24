"""Regression: verified Lilia phone correction affects both records, not raw events."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from lead_control.daily_duplicates import apply_daily_phone_duplicate_policy
from lead_control.lead_phone_corrections import apply_lead_phone_corrections, _message_key
from lead_control.processor import rebuild_leads_and_needs_review
from lead_control.source_categories import normalize_lead_sources


ROOT = Path(__file__).resolve().parents[2]
CORRECTIONS = ROOT / "runtime-data" / "lead_phone_corrections.json"
EVENTS = ROOT / "runtime-data" / "events.ndjson"


class LeadPhoneCorrectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CORRECTIONS.read_text(encoding="utf-8"))
        cls.keys = {
            (str(rule["channel"]).upper(), str(rule["chat_id"]), str(rule["message_id"]))
            for rule in cls.config["phone_corrections"]
        }
        cls.events = [
            event
            for line in EVENTS.read_text(encoding="utf-8").splitlines()
            if (event := json.loads(line)) and _message_key(event) in cls.keys
        ]
        if len(cls.events) != 2:
            raise AssertionError("Exactly the 2 confirmed source events must be present")

    def test_two_message_specific_source_events_only(self):
        before = deepcopy(self.events)
        fixed = apply_lead_phone_corrections(self.events, self.config)
        self.assertEqual(before, self.events, "Raw source events must not change")
        self.assertEqual(len(fixed), 2)
        expected = self.config["phone_corrections"][0]["correct_phone"]
        for event in fixed:
            if event["type"] == "telegram_lead":
                self.assertEqual(event["lead"]["phone_digits"], expected)
                self.assertEqual(event["lead"]["phone_raw"], "+" + expected)
                self.assertIn("+" + expected, event["lead"]["description"])
            else:
                self.assertIn("+" + expected, event["text"])
        for event in fixed:
            self.assertNotIn(self.config["phone_corrections"][0]["original_phone"], json.dumps(event, ensure_ascii=False))

    def test_rebuild_preserves_duplicate_and_both_numbers(self):
        fixed = apply_lead_phone_corrections(self.events, self.config)
        leads, needs_review = rebuild_leads_and_needs_review(fixed, [], [])
        normalize_lead_sources(leads)
        apply_daily_phone_duplicate_policy(leads, fixed)
        self.assertEqual(needs_review, [])
        self.assertEqual(len(leads), 2)

        expected = self.config["phone_corrections"][0]["correct_phone"]
        main = next(row for row in leads if row["channel"] == "MAX")
        duplicate = next(row for row in leads if row["channel"] == "TELEGRAM")

        self.assertEqual(main["identifier"]["value"], expected)
        self.assertEqual(duplicate["identifier"]["value"], expected)
        self.assertEqual(main["fields"]["phone_digits"], expected)
        self.assertEqual(duplicate["fields"]["phone_digits"], expected)
        self.assertEqual(main["first_seen_at"], "2026-10-23T12:27:03+03:00")
        self.assertEqual(duplicate["first_seen_at"], "2026-10-23T14:26:16+03:00")
        self.assertFalse(main.get("is_duplicate"))
        self.assertTrue(main["crm_required"])
        self.assertTrue(duplicate["is_duplicate"])
        self.assertFalse(duplicate["crm_required"])
        self.assertEqual(duplicate["duplicate_of"], main["id"])

    def test_other_events_untouched(self):
        unrelated = {"type": "max_message_created", "source": "MAX", "chat_id": -1,
                     "message_id": "test", "text": "call 79997775544"}
        working = apply_lead_phone_corrections(self.events + [unrelated], self.config)
        self.assertIs(working[-1], unrelated)
        self.assertEqual(unrelated["text"], "call 79997775544")

    def test_fails_if_target_original_changed_unexpectedly(self):
        tampered = deepcopy(self.events)
        for event in tampered:
            if event["type"] == "max_message_created":
                event["text"] = "Заявка с другим телефоном 79990000000"
        with self.assertRaisesRegex(ValueError, "Expected phone not found"):
            apply_lead_phone_corrections(tampered, self.config)

    def test_already_corrected_source_is_idempotent(self):
        first = apply_lead_phone_corrections(self.events, self.config)
        again = apply_lead_phone_corrections(first, self.config)
        self.assertEqual(first, again)

    def test_missing_target_aborts(self):
        with self.assertRaisesRegex(ValueError, "not found"):
            apply_lead_phone_corrections(self.events[:1], self.config)


if __name__ == "__main__":
    unittest.main()
