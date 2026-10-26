"""Regression tests for reliable MAX group ingestion independent of /updates."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from lead_control.max_client import MaxClient, filter_new_max_events
from lead_control.max_history import (
    MAX_HISTORY_OVERLAP_MS, MaxHistoryRecovery, reconcile_max_history,
)

CHAT_ID = -71704692523093
BOT_ID = 45454
OTHER_ID = 78787
HOUR_MS = 3_600_000
NOW = int(datetime(2026, 10, 26, 20, 0, tzinfo=timezone.utc).timestamp() * 1000)


def _message(mid: str, timestamp: int, *, sender: int = OTHER_ID, text: str = "ЗАЯВКА 15.12 30п Аня 89999999999", attachment=False):
    result = {
        "timestamp": timestamp,
        "sender": {"user_id": sender, "name": "Алёна"},
        "body": {"mid": mid, "text": text},
        "recipient": {"chat_id": CHAT_ID},
    }
    if attachment:
        result["body"]["attachments"] = [
            {"type": "image", "payload": {"token": "image-example"}}
        ]
        result["linked_message"] = {"body": {"text": "Форвард с деталями"}}
    return result


def _known(mid: str, timestamp: int):
    return {
        "type": "max_message_created",
        "update_type": "message_created",
        "source": "MAX",
        "message_id": mid,
        "timestamp": timestamp,
        "chat_id": CHAT_ID,
    }


class FakeClient:
    def __init__(self, messages, bot_user_id=BOT_ID):
        self.messages = sorted(messages, key=lambda x: x["timestamp"], reverse=True)
        self.calls = []
        self.bot_user_id = bot_user_id

    def get_me(self):
        return {"user_id": self.bot_user_id}

    def get_chat_messages(self, chat_id, *, before_ms=None, since_ms=None, count=100):
        self.calls.append((chat_id, before_ms, since_ms, count))
        assert chat_id == CHAT_ID
        return [
            m for m in self.messages
            if (before_ms is None or m["timestamp"] <= before_ms)
            and (since_ms is None or m["timestamp"] >= since_ms)
        ][:count]


class MaxHistoryTests(unittest.TestCase):
    def test_restores_older_gap_even_if_later_message_was_saved(self):
        """12:23 missing, 12:44 saved, morning bot reports should not block."""
        last = NOW - 2 * HOUR_MS
        older_missing = last - 21 * 60_000
        client = FakeClient([
            _message("already-captured", last),
            _message("missing-before-last", older_missing, attachment=True),
            _message("bot-report", last + 15 * 60_000, sender=BOT_ID, text="⚠️ LEAD CONTROL"),
            _message("missing-after-last", last + HOUR_MS),
        ])
        result = reconcile_max_history(
            client, chat_id=CHAT_ID, events=[_known("already-captured", last)],
            state={}, now_ms=NOW,
        )
        self.assertEqual(
            [e["message_id"] for e in result.events],
            ["missing-after-last", "missing-before-last"],
        )
        self.assertEqual(result.bot_messages_skipped, 1)
        self.assertTrue(result.events[1]["has_attachments"])
        self.assertEqual(result.events[1]["linked_or_forwarded_text"], "Форвард с деталями")
        self.assertEqual(result.watermark_ms, last + HOUR_MS)
        self.assertEqual(client.calls[0][2], last - MAX_HISTORY_OVERLAP_MS)
        self.assertTrue(all(e["chat_id"] == CHAT_ID for e in result.events))

    def test_no_duplicates_on_second_refresh(self):
        msg = _message("new", NOW - HOUR_MS)
        client = FakeClient([msg])
        first = reconcile_max_history(
            client, chat_id=CHAT_ID, events=[], state={}, now_ms=NOW,
        )
        self.assertEqual(len(first.events), 1)
        saved = [_known("new", msg["timestamp"])]
        second = reconcile_max_history(
            client, chat_id=CHAT_ID, events=saved,
            state={"history_last_seen_ms": first.watermark_ms},
            now_ms=NOW,
        )
        self.assertEqual(second.events, [])
        self.assertEqual(second.watermark_ms, first.watermark_ms)

    def test_previous_long_poll_updates_are_not_imported_again(self):
        timestamp = NOW - HOUR_MS
        client = FakeClient([_message("same-id", timestamp)])
        result = reconcile_max_history(
            client, chat_id=CHAT_ID, events=[_known("same-id", timestamp)],
            state={}, now_ms=NOW,
        )
        self.assertEqual(result.events, [])

    def test_empty_group_does_not_move_history_watermark(self):
        client = FakeClient([])
        result = reconcile_max_history(
            client, chat_id=CHAT_ID, events=[],
            state={"history_last_seen_ms": NOW - HOUR_MS}, now_ms=NOW,
        )
        self.assertEqual(result.pages, 1)
        self.assertEqual(result.events, [])
        self.assertEqual(result.watermark_ms, NOW - HOUR_MS)

    def test_long_outage_paginates_all_messages_and_remains_ordered(self):
        messages = [
            _message(f"msg-{i}", NOW - (155 - i) * 60_000)
            for i in range(155)
        ]
        client = FakeClient(messages)
        result = reconcile_max_history(
            client, chat_id=CHAT_ID, events=[], state={}, now_ms=NOW,
        )
        self.assertEqual(result.pages, 2)
        self.assertEqual(result.scanned, 156)  # 100 then 56 with 1 boundary overlap
        self.assertEqual(len(result.events), 155)
        self.assertEqual(len({x["message_id"] for x in result.events}), 155)
        self.assertEqual(client.calls[1][1], min(m["timestamp"] for m in messages[-100:]))
        self.assertEqual(client.calls[0][3], 100)

    def test_max_pages_raises_instead_of_losing_old_messages(self):
        messages = [
            _message(f"msg-{i}", NOW - i * 60_000)
            for i in range(110)
        ]
        with self.assertRaisesRegex(RuntimeError, "exceeded 1 pages"):
            reconcile_max_history(
                FakeClient(messages), chat_id=CHAT_ID, events=[],
                state={}, now_ms=NOW, max_pages=1,
            )

    def test_pagination_that_does_not_advance_must_raise(self):
        class Broken(FakeClient):
            def get_chat_messages(self, chat_id, *, before_ms=None, since_ms=None, count=100):
                return self.messages[:100]

        messages = [
            _message(f"msg-{i}", NOW - i * 60_000)
            for i in range(110)
        ]
        with self.assertRaisesRegex(RuntimeError, "pagination did not advance"):
            reconcile_max_history(Broken(messages), chat_id=CHAT_ID, events=[],
                                  state={}, now_ms=NOW)

    def test_own_bot_messages_never_enter_history_even_if_leadlike(self):
        client = FakeClient([
            _message("outgoing-1", NOW - 15_000, sender=BOT_ID,
                     text="⚠️ LEAD CONTROL — НЕ ВНЕСЕНЫ В CRM"),
            _message("new-lead", NOW - 20_000),
        ])
        result = reconcile_max_history(client, chat_id=CHAT_ID,
                                       events=[], state={}, now_ms=NOW)
        self.assertEqual([e["message_id"] for e in result.events], ["new-lead"])
        self.assertEqual(result.bot_messages_skipped, 1)

    def test_chat_id_filter_is_enforced(self):
        client = FakeClient([_message("from-other-chat", NOW - 15_000)])
        client.messages[0]["recipient"]["chat_id"] = 123
        with self.assertRaisesRegex(RuntimeError, "different group"):
            reconcile_max_history(client, chat_id=CHAT_ID,
                                  events=[], state={}, now_ms=NOW)

    def test_missing_bot_identity_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "valid bot user ID"):
            reconcile_max_history(FakeClient([], bot_user_id=None),
                                  chat_id=CHAT_ID, events=[], state={}, now_ms=NOW)

    def test_missing_message_id_fails_closed(self):
        client = FakeClient([_message("one", NOW - 10000)])
        del client.messages[0]["body"]["mid"]
        with self.assertRaisesRegex(RuntimeError, "missing ID"):
            reconcile_max_history(client, chat_id=CHAT_ID,
                                  events=[], state={}, now_ms=NOW)

    def test_max_api_chat_parameters_are_correct(self):
        client = MaxClient("dummy")
        responses=[]
        def fake(path, params):
            responses.append((path, params))
            return {"messages": []}
        with patch.object(client, "_request_json", side_effect=fake):
            client.get_chat_messages(CHAT_ID, before_ms=1234567890123,
                                     since_ms=1200000000000, count=250)
        self.assertEqual(responses[0][0], "/messages")
        self.assertEqual(responses[0][1], {
            "chat_id": CHAT_ID,
            "count": 100,
            "from": 1234567890123,
            "to": 1200000000000,
        })

    def test_invalid_history_response_raises(self):
        client = MaxClient("dummy")
        with patch.object(client, "_request_json", return_value={"messages": None}):
            with self.assertRaisesRegex(RuntimeError, "invalid chat history response"):
                client.get_chat_messages(CHAT_ID)


if __name__ == "__main__":
    unittest.main()
