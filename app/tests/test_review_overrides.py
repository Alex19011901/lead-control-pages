from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.amocrm_client import AmoCRMSearchResult
from lead_control.parsers.max_leads import HOST, IGNORE, STREET, TG_LEAD, TILDA_VERANDA, WEDWED
from lead_control.processor import apply_crm, rebuild_leads_and_needs_review
from lead_control.resolve_review import main as resolve_review_main
from lead_control.review_overrides import build_override, upsert_override
from lead_control.state import append_events, ensure_data_files, load_json, save_json


MAX_CHAT_ID = -71704692523093
BASE_TS_MS = 1787159436779


class ReviewOverrideTests(unittest.TestCase):
    def test_needs_review_resolves_to_host(self) -> None:
        text = "13.09 Оксана 89261860242"
        review = _review_item("MAX", MAX_CHAT_ID, "mid.host.override", text)
        override = build_override(review, HOST, "2026-08-19T21:40:00+03:00")
        leads, needs_review = rebuild_leads_and_needs_review(
            [_max_event("mid.host.override", text)],
            [review],
            [override],
        )
        crm = _FakeCRM(found=True)

        apply_crm(leads, crm)

        self.assertEqual(needs_review, [])
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["source"], "Заявки хост")
        self.assertEqual(leads[0]["category"], HOST)
        self.assertEqual(leads[0]["status"], "OK")
        self.assertEqual(crm.calls, [("79261860242", "phone")])

    def test_needs_review_resolves_to_street(self) -> None:
        text = "2.10.26 70чел. тел. 89851234567 София"
        review = _review_item("MAX", MAX_CHAT_ID, "mid.street.override", text)
        override = build_override(review, STREET, "2026-08-19T21:40:00+03:00")
        leads, needs_review = rebuild_leads_and_needs_review(
            [_max_event("mid.street.override", text)],
            [review],
            [override],
        )

        apply_crm(leads, _FakeCRM(found=True))

        self.assertEqual(needs_review, [])
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["source"], "С улицы")
        self.assertEqual(leads[0]["status"], "OK")

    def test_needs_review_resolves_to_tg_lead(self) -> None:
        text = "Ищем помещение на 27.08, 20 гостей. @urban_meow"
        review = _review_item("MAX", MAX_CHAT_ID, "mid.tg.override", text)
        override = build_override(review, TG_LEAD, "2026-08-19T21:40:00+03:00")
        leads, needs_review = rebuild_leads_and_needs_review(
            [_max_event("mid.tg.override", text)],
            [review],
            [override],
        )
        crm = _FakeCRM(found=True)

        apply_crm(leads, crm)

        self.assertEqual(needs_review, [])
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["source"], "Заявка с ТГ")
        self.assertEqual(leads[0]["identifier"], {"type": "telegram_username", "value": "urban_meow"})
        self.assertEqual(crm.calls, [("urban_meow", "telegram_username")])
        self.assertEqual(leads[0]["status"], "OK")

    def test_needs_review_resolves_to_ignore(self) -> None:
        text = "Служебное сообщение"
        review = _review_item("MAX", MAX_CHAT_ID, "mid.ignore.override", text)
        override = build_override(review, IGNORE, "2026-08-19T21:40:00+03:00")

        leads, needs_review = rebuild_leads_and_needs_review(
            [_max_event("mid.ignore.override", text)],
            [review],
            [override],
        )

        self.assertEqual(leads, [])
        self.assertEqual(needs_review, [])

    def test_needs_review_resolves_to_wedwed_without_crm(self) -> None:
        text = "WedWed\nНовый запрос с сайта WedWed\nДата: 28.08"
        review = _review_item("MAX", MAX_CHAT_ID, "mid.wedwed.override", text)
        override = build_override(review, WEDWED, "2026-08-19T21:40:00+03:00")
        leads, needs_review = rebuild_leads_and_needs_review(
            [_max_event("mid.wedwed.override", text)],
            [review],
            [override],
        )
        crm = _FakeCRM(found=True)

        apply_crm(leads, crm)

        self.assertEqual(needs_review, [])
        self.assertEqual(len(leads), 1)
        self.assertFalse(leads[0]["crm_required"])
        self.assertEqual(crm.calls, [])
        self.assertEqual(leads[0]["status"], "OK")

    def test_needs_review_resolves_to_tilda_veranda_without_crm(self) -> None:
        text = "\n".join(
            [
                "TildaForms",
                "Источник: https://svetliy-moscow.ru/menu",
                "Имя: Анна",
                "Телефон: +7 916 111-22-33",
                "Дата мероприятия: 30/08/2026",
                "Количество персон: 40",
            ]
        )
        review = _review_item("MAX", MAX_CHAT_ID, "mid.tilda.override", text)
        override = build_override(review, TILDA_VERANDA, "2026-08-19T21:40:00+03:00")
        leads, needs_review = rebuild_leads_and_needs_review(
            [_max_event("mid.tilda.override", text)],
            [review],
            [override],
        )
        crm = _FakeCRM(found=True)

        apply_crm(leads, crm)

        self.assertEqual(needs_review, [])
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["source"], "Тильда Веранда")
        self.assertFalse(leads[0]["crm_required"])
        self.assertEqual(crm.calls, [])
        self.assertEqual(leads[0]["status"], "OK")

    def test_repeat_override_is_idempotent(self) -> None:
        text = "13.09 Оксана 89261860242"
        review = _review_item("MAX", MAX_CHAT_ID, "mid.repeat.override", text)
        override = build_override(review, HOST, "2026-08-19T21:40:00+03:00")
        event = _max_event("mid.repeat.override", text)

        leads, needs_review = rebuild_leads_and_needs_review([event, dict(event)], [review], [override])
        crm = _FakeCRM(found=True)
        apply_crm(leads, crm)

        self.assertEqual(needs_review, [])
        self.assertEqual(len(leads), 1)
        self.assertEqual(crm.calls, [("79261860242", "phone")])

    def test_existing_decision_is_not_changed_automatically(self) -> None:
        text = "13.09 Оксана 89261860242"
        review = _review_item("MAX", MAX_CHAT_ID, "mid.fixed.override", text)
        host_override = build_override(review, HOST, "2026-08-19T21:40:00+03:00")
        street_override = build_override(review, STREET, "2026-08-19T21:41:00+03:00")

        with self.assertRaises(ValueError):
            upsert_override([host_override], street_override)

    def test_crm_required_without_identifier_is_not_alarm(self) -> None:
        text = "Подтверждённая вручную заявка без контакта"
        review = _review_item("MAX", MAX_CHAT_ID, "mid.noid.override", text)
        override = build_override(review, HOST, "2026-08-19T21:40:00+03:00")
        leads, needs_review = rebuild_leads_and_needs_review(
            [_max_event("mid.noid.override", text)],
            [review],
            [override],
        )
        crm = _FakeCRM(found=True)

        apply_crm(leads, crm)

        self.assertEqual(needs_review, [])
        self.assertEqual(len(leads), 1)
        self.assertEqual(crm.calls, [])
        self.assertEqual(leads[0]["crm_check_status"], "NO_IDENTIFIER")
        self.assertEqual(leads[0]["status"], "PENDING")
        self.assertEqual(leads[0]["violations"], [])

    def test_cli_stores_override_and_rebuilds_data_files(self) -> None:
        text = "13.09 Оксана 89261860242"
        review = _review_item("MAX", MAX_CHAT_ID, "mid.cli.override", text)
        event = _max_event("mid.cli.override", text)

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            ensure_data_files(data_dir)
            append_events(data_dir / "events.ndjson", [event])
            save_json(data_dir / "needs_review.json", {"schema_version": 1, "items": [review]})
            argv = [
                "resolve_review",
                "--data-dir",
                str(data_dir),
                "--channel",
                "MAX",
                "--chat-id",
                str(MAX_CHAT_ID),
                "--message-id",
                "mid.cli.override",
                "--decision",
                "HOST",
            ]

            with patch.object(sys, "argv", argv), patch.dict(os.environ, {"AMOCRM_TOKEN": ""}), redirect_stdout(io.StringIO()):
                resolve_review_main()

            overrides = load_json(data_dir / "review_overrides.json", {})
            needs_review = load_json(data_dir / "needs_review.json", {})
            leads = load_json(data_dir / "leads.json", {})

        self.assertEqual(len(overrides["items"]), 1)
        self.assertEqual(overrides["items"][0]["decision"], HOST)
        self.assertEqual(needs_review["items"], [])
        self.assertEqual(len(leads["leads"]), 1)


def _review_item(channel: str, chat_id: int, message_id: str, text: str) -> dict[str, object]:
    return {
        "channel": channel,
        "source": channel,
        "message_id": message_id,
        "chat_id": chat_id,
        "sender": {"user_id": 74336871, "username": None, "name": "Олеся"},
        "timestamp": BASE_TS_MS,
        "text": text,
        "review_reason": "ambiguous_contact_or_event_details",
        "status": "NEEDS_REVIEW",
    }


def _max_event(message_id: str, text: str) -> dict[str, object]:
    return {
        "type": "max_message_created",
        "source": "MAX",
        "update_type": "message_created",
        "chat_id": MAX_CHAT_ID,
        "message_id": message_id,
        "body_mid": message_id,
        "text": text,
        "sender_user_id": 74336871,
        "sender_username": None,
        "sender_name": "Олеся",
        "timestamp": BASE_TS_MS,
    }


class _FakeCRM:
    def __init__(self, found: bool) -> None:
        self.found = found
        self.calls: list[tuple[str, str]] = []

    def search(self, query: str, lead_id: str, identifier_type: str) -> AmoCRMSearchResult:
        self.calls.append((query, identifier_type))
        if not self.found:
            return AmoCRMSearchResult(found=False)
        return AmoCRMSearchResult(
            found=True,
            entity_type="lead",
            entity_id=42,
            created_at=BASE_TS_MS // 1000 + 60,
            updated_at=BASE_TS_MS // 1000 + 60,
            responsible_user_id=1,
        )


if __name__ == "__main__":
    unittest.main()
