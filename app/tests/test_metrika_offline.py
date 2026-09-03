from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lead_control.metrika_offline import (
    AmoCRMEventsLookupError,
    DATETIME_SOURCE_AMOCRM_LEAD_STATUS_CHANGED,
    DATETIME_STATE_CONFIRMED,
    DATETIME_STATE_LOOKUP_FAILED,
    DATETIME_STATE_MISSING_TRANSITION_TIMESTAMP,
    METRIKA_UPLOAD_STATUSES,
    QUALIFYING_CRM_PIPELINE_ID,
    TARGET_QUALIFIED_LEAD,
    YANDEX_METRIKA_COUNTER_ID,
    MetrikaOfflineUploadBlocked,
    YandexMetrikaOfflineClient,
    build_idempotency_key,
    build_qualified_lead_detection,
    fetch_metrika_upload_status,
    default_metrika_offline_state,
    load_metrika_offline_state,
    lookup_first_qualification_datetime,
    prepare_metrika_offline_csv,
    parse_metrika_upload_status_response,
    record_qualified_lead_detection,
    record_qualified_lead_detection_with_datetime,
    save_metrika_offline_state,
    submit_metrika_offline_record,
)


QUALIFYING_STATUSES = [
    "Выслано предложение",
    "Принимают решение",
    "Предбронь",
    "Приедут на просмотр",
    "ЖДЕМ НА ДЕГУСТАЦИЮ",
    "Согласование договора",
    "Внесена п/о идет текущая работа",
    "Успешно реализовано",
]


IGNORED_STATUSES = [
    "Первичный контакт",
    "ЖДУНЫ",
    "Закрыто и не реализовано",
    "Контакты на декабрь 26",
]


class MetrikaOfflineTests(unittest.TestCase):
    def test_lead_without_yclid_is_ignored(self) -> None:
        lead = _lead(status_name="Выслано предложение", yclid="")

        self.assertIsNone(build_qualified_lead_detection(lead, detected_at="2026-09-03T10:00:00Z"))

    def test_non_qualifying_statuses_are_ignored(self) -> None:
        for status_name in IGNORED_STATUSES:
            with self.subTest(status_name=status_name):
                lead = _lead(status_name=status_name)

                self.assertIsNone(build_qualified_lead_detection(lead, detected_at="2026-09-03T10:00:00Z"))

    def test_qualifying_statuses_create_detection(self) -> None:
        for status_name in QUALIFYING_STATUSES:
            with self.subTest(status_name=status_name):
                lead = _lead(status_name=status_name, crm_lead_id=98765)

                record = build_qualified_lead_detection(lead, detected_at="2026-09-03T10:00:00Z")

                self.assertIsNotNone(record)
                assert record is not None
                self.assertEqual(record["target"], TARGET_QUALIFIED_LEAD)
                self.assertEqual(record["current_crm_status"], status_name)
                self.assertEqual(record["yclid"], "260903123456789")
                self.assertEqual(record["lead_id"], "lead-1")
                self.assertEqual(record["crm_lead_id"], 98765)
                self.assertEqual(record["detected_at"], "2026-09-03T10:00:00Z")
                self.assertEqual(record["state"], "detected")
                self.assertEqual(
                    record["idempotency_key"],
                    build_idempotency_key("98765", "260903123456789"),
                )

    def test_duplicate_same_lead_and_yclid_is_blocked(self) -> None:
        state = default_metrika_offline_state()
        lead = _lead(status_name="Выслано предложение", crm_lead_id=98765)

        first, first_duplicate = record_qualified_lead_detection(
            state,
            lead,
            detected_at="2026-09-03T10:00:00Z",
        )
        second, second_duplicate = record_qualified_lead_detection(
            state,
            lead,
            detected_at="2026-09-03T11:00:00Z",
        )

        self.assertIsNotNone(first)
        self.assertIs(first, second)
        self.assertFalse(first_duplicate)
        self.assertTrue(second_duplicate)
        self.assertEqual(len(state["conversions"]), 1)
        self.assertEqual(first["detected_at"], "2026-09-03T10:00:00Z")

    def test_transition_between_qualifying_statuses_does_not_create_second_detection(self) -> None:
        state = default_metrika_offline_state()
        lead = _lead(status_name="Выслано предложение", crm_lead_id=98765)
        record_qualified_lead_detection(state, lead, detected_at="2026-09-03T10:00:00Z")

        lead["crm_feedback"]["status_name"] = "ЖДЕМ НА ДЕГУСТАЦИЮ"
        existing, duplicate = record_qualified_lead_detection(
            state,
            lead,
            detected_at="2026-09-03T11:00:00Z",
        )

        self.assertTrue(duplicate)
        self.assertEqual(len(state["conversions"]), 1)
        self.assertEqual(existing["detected_at"], "2026-09-03T10:00:00Z")
        self.assertEqual(existing["current_crm_status"], "ЖДЕМ НА ДЕГУСТАЦИЮ")

    def test_fallback_to_internal_lead_id_works(self) -> None:
        lead = _lead(status_name="Успешно реализовано", crm_lead_id=None)
        lead["crm"].pop("entity_id", None)

        record = build_qualified_lead_detection(lead, detected_at="2026-09-03T10:00:00Z")

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record["crm_lead_id"], None)
        self.assertEqual(
            record["idempotency_key"],
            build_idempotency_key("lead-1", "260903123456789"),
        )

    def test_state_file_roundtrip(self) -> None:
        state = default_metrika_offline_state()
        lead = _lead(status_name="Принимают решение", crm_lead_id=98765)
        record_qualified_lead_detection(state, lead, detected_at="2026-09-03T10:00:00Z")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metrika_offline_state.json"
            save_metrika_offline_state(state, path)

            loaded = load_metrika_offline_state(path)

        self.assertEqual(loaded, state)

    def test_atomic_state_save_writes_valid_json_without_secrets(self) -> None:
        state = default_metrika_offline_state()
        state["conversions"]["example"] = _ready_record()

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metrika_offline_state.json"
            save_metrika_offline_state(state, path)

            text = path.read_text(encoding="utf-8")
            loaded = json.loads(text)
            temp_files = list(Path(tmp).glob(".metrika_offline_state.json.*.tmp"))

        self.assertEqual(loaded, state)
        self.assertEqual(temp_files, [])
        self.assertNotIn("fake-token", text)
        self.assertNotIn("YANDEX_METRIKA_OFFLINE_TOKEN", text)
        self.assertNotIn("Authorization", text)

    def test_atomic_state_save_preserves_final_file_and_cleans_temp_on_pre_replace_error(self) -> None:
        original_state = default_metrika_offline_state()
        original_state["conversions"]["old"] = dict(_ready_record(), state="submitted")
        new_state = default_metrika_offline_state()
        new_state["conversions"]["new"] = _ready_record(yclid="260903123456789123456789")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metrika_offline_state.json"
            save_metrika_offline_state(original_state, path)

            with mock.patch("lead_control.metrika_offline.os.fsync", side_effect=OSError("fsync failed")):
                with self.assertRaises(OSError):
                    save_metrika_offline_state(new_state, path)

            loaded = json.loads(path.read_text(encoding="utf-8"))
            temp_files = list(Path(tmp).glob(".metrika_offline_state.json.*.tmp"))

        self.assertEqual(loaded, original_state)
        self.assertEqual(temp_files, [])

    def test_first_qualifying_transition_is_selected(self) -> None:
        client = _FakeEventsClient(
            [
                _events_page(
                    [
                        _status_event(1_700, 79927034),
                        _status_event(1_600, 79927042),
                        _status_event(1_500, 79927038),
                    ]
                )
            ]
        )

        result = lookup_first_qualification_datetime(client, 98765)

        self.assertEqual(result.datetime_state, DATETIME_STATE_CONFIRMED)
        self.assertEqual(result.datetime_source, DATETIME_SOURCE_AMOCRM_LEAD_STATUS_CHANGED)
        self.assertEqual(result.qualification_datetime, 1_500)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["filter[entity]"], "lead")
        self.assertEqual(client.calls[0]["filter[entity_id][0]"], 98765)
        self.assertEqual(client.calls[0]["filter[type]"], "lead_status_changed")

    def test_later_qualifying_transition_does_not_replace_first(self) -> None:
        state = default_metrika_offline_state()
        lead = _lead(status_name="Принимают решение", crm_lead_id=98765)
        client = _FakeEventsClient(
            [
                _events_page(
                    [
                        _status_event(3_000, 79927042),
                        _status_event(2_000, 79927038),
                    ]
                )
            ]
        )

        record, duplicate = record_qualified_lead_detection_with_datetime(
            state,
            lead,
            client,
            detected_at="2026-09-03T10:00:00Z",
        )

        self.assertFalse(duplicate)
        self.assertEqual(record["qualification_datetime"], 2_000)
        self.assertEqual(record["datetime_state"], DATETIME_STATE_CONFIRMED)

        later_client = _FakeEventsClient([_events_page([_status_event(3_000, 79927042)])])
        same_record, duplicate = record_qualified_lead_detection_with_datetime(
            state,
            lead,
            later_client,
            detected_at="2026-09-03T11:00:00Z",
        )

        self.assertTrue(duplicate)
        self.assertIs(same_record, record)
        self.assertEqual(record["qualification_datetime"], 2_000)
        self.assertEqual(len(later_client.calls), 0)

    def test_non_qualifying_transition_is_ignored(self) -> None:
        client = _FakeEventsClient([_events_page([_status_event(1_500, 79927034)])])

        result = lookup_first_qualification_datetime(client, 98765)

        self.assertEqual(result.datetime_state, DATETIME_STATE_MISSING_TRANSITION_TIMESTAMP)
        self.assertIsNone(result.qualification_datetime)

    def test_other_pipeline_transition_is_ignored(self) -> None:
        client = _FakeEventsClient([_events_page([_status_event(1_500, 79927038, pipeline_id=123)])])

        result = lookup_first_qualification_datetime(client, 98765)

        self.assertEqual(result.datetime_state, DATETIME_STATE_MISSING_TRANSITION_TIMESTAMP)
        self.assertIsNone(result.qualification_datetime)

    def test_missing_events_marks_missing_transition_timestamp(self) -> None:
        state = default_metrika_offline_state()
        lead = _lead(status_name="Выслано предложение", crm_lead_id=98765)
        client = _FakeEventsClient([_events_page([])])

        record, duplicate = record_qualified_lead_detection_with_datetime(
            state,
            lead,
            client,
            detected_at="2026-09-03T10:00:00Z",
        )

        self.assertFalse(duplicate)
        self.assertEqual(record["state"], "detected")
        self.assertIsNone(record["qualification_datetime"])
        self.assertEqual(record["datetime_source"], "")
        self.assertEqual(record["datetime_state"], DATETIME_STATE_MISSING_TRANSITION_TIMESTAMP)

    def test_pagination_is_processed(self) -> None:
        client = _FakeEventsClient(
            [
                _events_page([_status_event(2_500, 79927034)], next_page=True),
                _events_page([_status_event(2_000, 79927038)]),
            ]
        )

        result = lookup_first_qualification_datetime(client, 98765)

        self.assertEqual(result.datetime_state, DATETIME_STATE_CONFIRMED)
        self.assertEqual(result.qualification_datetime, 2_000)
        self.assertEqual([call["page"] for call in client.calls], [1, 2])

    def test_malformed_event_does_not_break_lookup(self) -> None:
        client = _FakeEventsClient(
            [
                _events_page(
                    [
                        {},
                        {"type": "lead_status_changed", "entity_id": 98765, "created_at": "bad"},
                        {
                            "type": "lead_status_changed",
                            "entity_id": 98765,
                            "entity_type": "lead",
                            "created_at": 1_500,
                            "value_after": [{"lead_status": {"id": "bad", "pipeline_id": QUALIFYING_CRM_PIPELINE_ID}}],
                        },
                    ]
                )
            ]
        )

        result = lookup_first_qualification_datetime(client, 98765)

        self.assertEqual(result.datetime_state, DATETIME_STATE_MISSING_TRANSITION_TIMESTAMP)
        self.assertIsNone(result.qualification_datetime)

    def test_timeout_429_403_do_not_retry_or_break_caller(self) -> None:
        cases = [
            AmoCRMEventsLookupError("timeout"),
            AmoCRMEventsLookupError("http_error", http_status=429),
            AmoCRMEventsLookupError("http_error", http_status=403),
        ]

        for error in cases:
            with self.subTest(error=str(error)):
                state = default_metrika_offline_state()
                lead = _lead(status_name="Выслано предложение", crm_lead_id=98765)
                client = _FakeEventsClient(error=error)

                record, duplicate = record_qualified_lead_detection_with_datetime(
                    state,
                    lead,
                    client,
                    detected_at="2026-09-03T10:00:00Z",
                )

                self.assertFalse(duplicate)
                self.assertEqual(len(client.calls), 1)
                self.assertEqual(record["state"], "failed")
                self.assertEqual(record["datetime_state"], DATETIME_STATE_LOOKUP_FAILED)
                self.assertIsNone(record["qualification_datetime"])
                self.assertEqual(record["datetime_error"]["kind"], error.kind)
                self.assertEqual(record["datetime_error"]["http_status"], error.http_status)

    def test_prepare_csv_uses_yclid_target_and_confirmed_datetime(self) -> None:
        record = _ready_record(qualification_datetime=1_788_435_000)

        csv_bytes = prepare_metrika_offline_csv(record)

        self.assertEqual(
            csv_bytes.decode("utf-8"),
            "Yclid,Target,DateTime\n260903123456789,qualified_lead,1788435000\n",
        )

    def test_large_numeric_looking_yclid_is_preserved_exactly(self) -> None:
        yclid = "260903123456789123456789"
        lead = _lead(status_name="Выслано предложение", yclid=yclid, crm_lead_id=98765)

        record = build_qualified_lead_detection(lead, detected_at="2026-09-03T10:00:00Z")

        self.assertIsNotNone(record)
        assert record is not None
        self.assertIsInstance(record["yclid"], str)
        self.assertEqual(record["yclid"], yclid)
        self.assertEqual(record["idempotency_key"], build_idempotency_key("98765", yclid))

        record["qualification_datetime"] = 1_788_435_000
        record["datetime_source"] = DATETIME_SOURCE_AMOCRM_LEAD_STATUS_CHANGED
        record["datetime_state"] = DATETIME_STATE_CONFIRMED
        csv_text = prepare_metrika_offline_csv(record).decode("utf-8")

        self.assertIn(f"{yclid},qualified_lead,1788435000\n", csv_text)
        self.assertNotIn("e+", csv_text.lower())
        self.assertNotIn("260903123456789123456800", csv_text)

    def test_missing_confirmed_datetime_blocks_upload(self) -> None:
        state = default_metrika_offline_state()
        record = _ready_record()
        record["datetime_state"] = DATETIME_STATE_MISSING_TRANSITION_TIMESTAMP
        client = _metrika_client(_FakeUrlopen())

        result = submit_metrika_offline_record(state, record, client)

        self.assertFalse(result.attempted)
        self.assertEqual(result.blocked_reason, "datetime_not_confirmed")
        self.assertEqual(len(client._urlopen.calls), 0)
        with self.assertRaises(MetrikaOfflineUploadBlocked):
            prepare_metrika_offline_csv(record)

    def test_missing_yclid_blocks_upload(self) -> None:
        state = default_metrika_offline_state()
        record = _ready_record(yclid="")
        client = _metrika_client(_FakeUrlopen())

        result = submit_metrika_offline_record(state, record, client)

        self.assertFalse(result.attempted)
        self.assertEqual(result.blocked_reason, "missing_yclid")
        self.assertEqual(len(client._urlopen.calls), 0)

    def test_successful_post_marks_submitted_and_upload_id(self) -> None:
        state = default_metrika_offline_state()
        record = _ready_record()
        fake_urlopen = _FakeUrlopen(
            [_FakeHTTPResponse({"uploading": {"id": 12345, "status": "UPLOADED"}})]
        )
        client = _metrika_client(fake_urlopen)

        result = submit_metrika_offline_record(
            state,
            record,
            client,
            submitted_at="2026-09-03T12:00:00Z",
        )

        self.assertTrue(result.attempted)
        self.assertEqual(result.state, "submitted")
        self.assertEqual(result.upload_id, 12345)
        self.assertEqual(record["state"], "submitted")
        self.assertEqual(record["upload_id"], 12345)
        self.assertEqual(record["upload_status"], "UPLOADED")
        self.assertEqual(record["submitted_at"], "2026-09-03T12:00:00Z")
        self.assertNotIn("upload_error", record)
        self.assertEqual(len(fake_urlopen.calls), 1)

        request, timeout = fake_urlopen.calls[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(timeout, 30)
        self.assertEqual(
            request.full_url,
            f"https://api-metrika.yandex.net/management/v1/counter/{YANDEX_METRIKA_COUNTER_ID}/offline_conversions/upload",
        )
        headers = {key.casefold(): value for key, value in request.header_items()}
        self.assertEqual(headers["authorization"], "OAuth fake-token")
        self.assertTrue(headers["content-type"].startswith("multipart/form-data; boundary="))
        self.assertIn(b"Yclid,Target,DateTime\n260903123456789,qualified_lead,1788435000\n", request.data)

    def test_multipart_field_name_is_exact_file(self) -> None:
        state = default_metrika_offline_state()
        record = _ready_record()
        fake_urlopen = _FakeUrlopen(
            [_FakeHTTPResponse({"uploading": {"id": 12345, "status": "UPLOADED"}})]
        )
        client = _metrika_client(fake_urlopen)

        submit_metrika_offline_record(state, record, client)

        self.assertEqual(len(fake_urlopen.calls), 1)
        request, _timeout = fake_urlopen.calls[0]
        self.assertIn(
            b'Content-Disposition: form-data; name="file"; filename="offline-conversions.csv"\r\n',
            request.data,
        )

    def test_timeout_marks_uncertain_without_retry(self) -> None:
        state = default_metrika_offline_state()
        record = _ready_record()
        fake_urlopen = _FakeUrlopen(error=TimeoutError("timed out"))
        client = _metrika_client(fake_urlopen)

        result = submit_metrika_offline_record(state, record, client)

        self.assertTrue(result.attempted)
        self.assertEqual(result.state, "uncertain")
        self.assertEqual(record["state"], "uncertain")
        self.assertEqual(record["upload_error"]["kind"], "timeout")
        self.assertEqual(len(fake_urlopen.calls), 1)

    def test_429_marks_failed_without_retry(self) -> None:
        state = default_metrika_offline_state()
        record = _ready_record()
        fake_urlopen = _FakeUrlopen(error=_http_error(429, b'{"message":"rate limit"}'))
        client = _metrika_client(fake_urlopen)

        result = submit_metrika_offline_record(state, record, client)

        self.assertTrue(result.attempted)
        self.assertEqual(result.state, "failed")
        self.assertEqual(record["state"], "failed")
        self.assertEqual(record["upload_error"]["http_status"], 429)
        self.assertEqual(len(fake_urlopen.calls), 1)

    def test_403_marks_failed_without_retry(self) -> None:
        state = default_metrika_offline_state()
        record = _ready_record()
        fake_urlopen = _FakeUrlopen(error=_http_error(403, b'{"message":"forbidden"}'))
        client = _metrika_client(fake_urlopen)

        result = submit_metrika_offline_record(state, record, client)

        self.assertTrue(result.attempted)
        self.assertEqual(result.state, "failed")
        self.assertEqual(record["state"], "failed")
        self.assertEqual(record["upload_error"]["http_status"], 403)
        self.assertEqual(len(fake_urlopen.calls), 1)

    def test_duplicate_submitted_does_not_post(self) -> None:
        state = default_metrika_offline_state()
        record = _ready_record()
        state["conversions"][record["idempotency_key"]] = dict(record, state="submitted")
        fake_urlopen = _FakeUrlopen()
        client = _metrika_client(fake_urlopen)

        result = submit_metrika_offline_record(state, record, client)

        self.assertFalse(result.attempted)
        self.assertEqual(result.blocked_reason, "already_submitted")
        self.assertEqual(len(fake_urlopen.calls), 0)

    def test_duplicate_uncertain_does_not_post(self) -> None:
        state = default_metrika_offline_state()
        record = _ready_record()
        state["conversions"][record["idempotency_key"]] = dict(record, state="uncertain")
        fake_urlopen = _FakeUrlopen()
        client = _metrika_client(fake_urlopen)

        result = submit_metrika_offline_record(state, record, client)

        self.assertFalse(result.attempted)
        self.assertEqual(result.blocked_reason, "already_uncertain")
        self.assertEqual(len(fake_urlopen.calls), 0)

    def test_duplicate_failed_does_not_post_or_mutate_state(self) -> None:
        state = default_metrika_offline_state()
        record = _ready_record()
        failed_record = dict(
            record,
            state="failed",
            upload_error={"kind": "http_error", "http_status": 500, "message": "server error"},
        )
        state["conversions"][record["idempotency_key"]] = failed_record
        fake_urlopen = _FakeUrlopen()
        client = _metrika_client(fake_urlopen)

        result = submit_metrika_offline_record(state, record, client)

        self.assertFalse(result.attempted)
        self.assertEqual(result.blocked_reason, "already_failed")
        self.assertEqual(len(fake_urlopen.calls), 0)
        self.assertIs(state["conversions"][record["idempotency_key"]], failed_record)
        self.assertEqual(failed_record["state"], "failed")
        self.assertEqual(failed_record["upload_error"]["http_status"], 500)

    def test_token_is_not_saved_to_state_or_result_diagnostics(self) -> None:
        state = default_metrika_offline_state()
        record = _ready_record()
        fake_urlopen = _FakeUrlopen(error=_http_error(500, b'{"message":"fake-token OAuth fake-token"}'))
        client = _metrika_client(fake_urlopen)

        result = submit_metrika_offline_record(state, record, client)

        serialized = json.dumps({"state": state, "result": result.__dict__}, ensure_ascii=False)
        self.assertNotIn("fake-token", serialized)
        self.assertIn("[redacted]", serialized)

    def test_status_endpoint_parses_all_known_statuses(self) -> None:
        for status in sorted(METRIKA_UPLOAD_STATUSES):
            with self.subTest(status=status):
                payload = {"uploading": {"id": 12345, "status": status}}

                parsed = parse_metrika_upload_status_response(payload)

                self.assertEqual(parsed.lookup_state, "parsed")
                self.assertEqual(parsed.upload_id, 12345)
                self.assertEqual(parsed.status, status)
                self.assertTrue(parsed.known_status)

    def test_status_endpoint_get_is_mocked_and_parsed(self) -> None:
        fake_urlopen = _FakeUrlopen(
            [_FakeHTTPResponse({"uploading": {"id": 12345, "status": "PROCESSED"}})]
        )
        client = _metrika_client(fake_urlopen)

        result = fetch_metrika_upload_status(client, 12345)

        self.assertEqual(result.lookup_state, "parsed")
        self.assertEqual(result.status, "PROCESSED")
        self.assertEqual(len(fake_urlopen.calls), 1)
        request, _timeout = fake_urlopen.calls[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(
            request.full_url,
            f"https://api-metrika.yandex.net/management/v1/counter/{YANDEX_METRIKA_COUNTER_ID}/offline_conversions/uploading/12345",
        )

    def test_malformed_upload_response_does_not_break_caller(self) -> None:
        state = default_metrika_offline_state()
        record = _ready_record()
        fake_urlopen = _FakeUrlopen([_FakeHTTPResponse({"unexpected": "shape"})])
        client = _metrika_client(fake_urlopen)

        result = submit_metrika_offline_record(state, record, client)

        self.assertTrue(result.attempted)
        self.assertEqual(result.state, "failed")
        self.assertEqual(result.error_kind, "malformed_response")
        self.assertEqual(record["state"], "failed")
        self.assertEqual(record["upload_error"]["kind"], "malformed_response")

    def test_invalid_json_upload_response_does_not_break_caller(self) -> None:
        state = default_metrika_offline_state()
        record = _ready_record()
        fake_urlopen = _FakeUrlopen([_FakeHTTPResponse(b"not json")])
        client = _metrika_client(fake_urlopen)

        result = submit_metrika_offline_record(state, record, client)

        self.assertTrue(result.attempted)
        self.assertEqual(result.state, "failed")
        self.assertEqual(result.error_kind, "invalid_json")
        self.assertEqual(record["state"], "failed")


def _lead(
    *,
    status_name: str,
    yclid: str = "260903123456789",
    crm_lead_id: int | None = 98765,
) -> dict[str, object]:
    crm_feedback = {
        "status_name": status_name,
        "status_id": 1,
    }
    crm = {
        "found": True,
        "entity_type": "lead",
    }
    if crm_lead_id is not None:
        crm_feedback["crm_lead_id"] = crm_lead_id
        crm["entity_id"] = crm_lead_id

    return {
        "id": "lead-1",
        "fields": {"yclid": yclid},
        "crm_feedback": crm_feedback,
        "crm": crm,
    }


def _events_page(events: list[dict[str, object]], *, next_page: bool = False) -> dict[str, object]:
    links: dict[str, object] = {"self": {"href": "https://example.amocrm.ru/api/v4/events?page=1"}}
    if next_page:
        links["next"] = {"href": "https://example.amocrm.ru/api/v4/events?page=2"}
    return {"_links": links, "_embedded": {"events": events}}


def _status_event(
    created_at: int,
    status_id: int,
    *,
    pipeline_id: int = QUALIFYING_CRM_PIPELINE_ID,
    entity_id: int = 98765,
) -> dict[str, object]:
    return {
        "type": "lead_status_changed",
        "entity_id": entity_id,
        "entity_type": "lead",
        "created_at": created_at,
        "value_after": [
            {
                "lead_status": {
                    "id": status_id,
                    "pipeline_id": pipeline_id,
                }
            }
        ],
        "value_before": [],
    }


class _FakeEventsClient:
    def __init__(
        self,
        pages: list[dict[str, object]] | None = None,
        *,
        error: AmoCRMEventsLookupError | None = None,
    ) -> None:
        self.pages = pages or []
        self.error = error
        self.calls: list[dict[str, object]] = []

    def get_events(self, params: dict[str, object]) -> dict[str, object]:
        self.calls.append(dict(params))
        if self.error is not None:
            raise self.error
        index = len(self.calls) - 1
        if index < len(self.pages):
            return self.pages[index]
        return _events_page([])


def _ready_record(
    *,
    yclid: str = "260903123456789",
    qualification_datetime: int = 1_788_435_000,
) -> dict[str, object]:
    return {
        "idempotency_key": build_idempotency_key("98765", yclid),
        "lead_id": "lead-1",
        "crm_lead_id": 98765,
        "yclid": yclid,
        "target": TARGET_QUALIFIED_LEAD,
        "current_crm_status": "Выслано предложение",
        "detected_at": "2026-09-03T10:00:00Z",
        "qualification_datetime": qualification_datetime,
        "datetime_source": DATETIME_SOURCE_AMOCRM_LEAD_STATUS_CHANGED,
        "datetime_state": DATETIME_STATE_CONFIRMED,
        "state": "detected",
    }


def _metrika_client(fake_urlopen: "_FakeUrlopen") -> YandexMetrikaOfflineClient:
    return YandexMetrikaOfflineClient("fake-token", urlopen=fake_urlopen)


def _http_error(status: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api-metrika.yandex.net/example",
        status,
        "error",
        hdrs=None,
        fp=io.BytesIO(body),
    )


class _FakeHTTPResponse:
    def __init__(self, payload: dict[str, object] | bytes, *, status: int = 200) -> None:
        self.status = status
        if isinstance(payload, bytes):
            self._body = payload
        else:
            self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeUrlopen:
    def __init__(
        self,
        responses: list[_FakeHTTPResponse] | None = None,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.responses = responses or []
        self.error = error
        self.calls: list[tuple[object, int]] = []

    def __call__(self, request: object, *, timeout: int) -> _FakeHTTPResponse:
        self.calls.append((request, timeout))
        if self.error is not None:
            raise self.error
        index = len(self.calls) - 1
        if index < len(self.responses):
            return self.responses[index]
        return _FakeHTTPResponse({})
