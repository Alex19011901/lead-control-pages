from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_metrika_offline

from lead_control.metrika_offline import (
    QUALIFYING_CRM_PIPELINE_ID,
    build_idempotency_key,
    default_metrika_offline_state,
    save_metrika_offline_state,
)


class MetrikaOfflineRunnerTests(unittest.TestCase):
    def test_production_workflow_does_not_run_metrika_offline_upload(self) -> None:
        workflow_path = ROOT.parent / ".github" / "workflows" / "lead-control-public.yml"
        text = workflow_path.read_text(encoding="utf-8")
        step_names = [
            line.split("- name:", 1)[1].strip()
            for line in text.splitlines()
            if line.startswith("      - name:")
        ]

        self.assertEqual(
            step_names,
            [
                "Checkout public repo",
                "Set up Python",
                "Test exact Tilda test exclusion",
                "Install OCR",
                "Collect Telegram MAX and amoCRM",
                "Rebuild dashboard",
                "Save refreshed data",
                "Configure Pages",
                "Upload Pages artifact",
                "Deploy Pages",
            ],
        )
        self.assertLess(
            step_names.index("Rebuild dashboard"),
            step_names.index("Save refreshed data"),
        )
        self.assertNotIn("Metrika offline conversions disabled runner", step_names)
        self.assertNotIn("run_metrika_offline.py", text)
        self.assertNotIn("YANDEX_METRIKA_OFFLINE_TOKEN", text)
        self.assertNotIn("METRIKA_OFFLINE_ENABLED", text)
        self.assertNotIn("METRIKA_OFFLINE_DRY_RUN", text)

    def test_default_disabled_does_not_call_http(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _write_leads(data_dir, [_lead()])
            events_factory = _Factory(_FakeEventsClient())
            metrika_factory = _Factory(_FakeMetrikaClient())

            result = _run(data_dir, {}, events_factory, metrika_factory)

            self.assertEqual(result.code, 0)
            self.assertEqual(result.summary["status"], "disabled")
            self.assertFalse(result.summary["enabled"])
            self.assertEqual(len(events_factory.calls), 0)
            self.assertEqual(len(metrika_factory.calls), 0)
            self.assertEqual(_read_state(data_dir)["runner"]["status"], "disabled")

    def test_enabled_zero_does_not_call_http(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _write_leads(data_dir, [_lead()])
            events_factory = _Factory(_FakeEventsClient())
            metrika_factory = _Factory(_FakeMetrikaClient())

            result = _run(
                data_dir,
                {"METRIKA_OFFLINE_ENABLED": "0"},
                events_factory,
                metrika_factory,
            )

            self.assertEqual(result.code, 0)
            self.assertEqual(result.summary["status"], "disabled")
            self.assertEqual(len(events_factory.calls), 0)
            self.assertEqual(len(metrika_factory.calls), 0)

    def test_enabled_default_dry_run_does_not_call_http(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _write_leads(data_dir, [_lead()])
            events_factory = _Factory(_FakeEventsClient())
            metrika_factory = _Factory(_FakeMetrikaClient())

            result = _run(
                data_dir,
                {"METRIKA_OFFLINE_ENABLED": "1"},
                events_factory,
                metrika_factory,
            )

            self.assertEqual(result.code, 0)
            self.assertEqual(result.summary["status"], "dry_run")
            self.assertTrue(result.summary["dry_run"])
            self.assertEqual(result.summary["candidates"], 1)
            self.assertEqual(len(events_factory.calls), 0)
            self.assertEqual(len(metrika_factory.calls), 0)

    def test_dry_run_adds_read_only_lead_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _write_leads(data_dir, [_lead()])
            events_client = _FakeEventsClient(
                lead_payload={
                    "id": 48223023,
                    "name": "Фирстова Татьяна Валерьевна",
                    "created_at": 1_788_445_384,
                    "updated_at": 1_788_445_392,
                    "pipeline_id": QUALIFYING_CRM_PIPELINE_ID,
                    "status_id": 79927038,
                    "price": 123456,
                    "_embedded": {"contacts": [{"id": 1}]},
                },
            )
            metrika_factory = _Factory(_FakeMetrikaClient())

            result = _run(
                data_dir,
                {
                    "METRIKA_OFFLINE_ENABLED": "1",
                    "METRIKA_OFFLINE_DRY_RUN": "1",
                    "AMOCRM_TOKEN": "amo-token",
                },
                _Factory(events_client),
                metrika_factory,
            )

            diagnostics = result.summary["diagnostics"]["amocrm_lead_48223023"]
            self.assertEqual(
                set(diagnostics),
                {
                    "id",
                    "name",
                    "created_at",
                    "created_at_iso",
                    "updated_at",
                    "updated_at_iso",
                    "pipeline_id",
                    "status_id",
                    "lead_created_matches_lead_added",
                },
            )
            self.assertEqual(diagnostics["id"], 48223023)
            self.assertEqual(diagnostics["name"], "Фирстова Татьяна Валерьевна")
            self.assertEqual(diagnostics["created_at"], 1_788_445_384)
            self.assertEqual(diagnostics["created_at_iso"], "2026-09-03T14:23:04Z")
            self.assertEqual(diagnostics["updated_at"], 1_788_445_392)
            self.assertEqual(diagnostics["updated_at_iso"], "2026-09-03T14:23:12Z")
            self.assertEqual(diagnostics["pipeline_id"], QUALIFYING_CRM_PIPELINE_ID)
            self.assertEqual(diagnostics["status_id"], 79927038)
            self.assertTrue(diagnostics["lead_created_matches_lead_added"])
            self.assertEqual(events_client.lead_calls, [48223023])
            self.assertEqual(len(metrika_factory.calls), 0)

    def test_dry_run_lead_diagnostics_exposes_only_safe_fields(self) -> None:
        secret = "amo-token"
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _write_leads(data_dir, [_lead()])
            events_client = _FakeEventsClient(
                lead_payload={
                    "id": 48223023,
                    "name": "Safe name",
                    "created_at": 1_788_445_000,
                    "updated_at": 1_788_445_392,
                    "pipeline_id": QUALIFYING_CRM_PIPELINE_ID,
                    "status_id": 79927038,
                    "secret": secret,
                    "custom_fields_values": [{"field_name": "phone", "values": ["hidden"]}],
                },
            )

            result = _run(
                data_dir,
                {
                    "METRIKA_OFFLINE_ENABLED": "1",
                    "METRIKA_OFFLINE_DRY_RUN": "1",
                    "AMOCRM_TOKEN": secret,
                },
                _Factory(events_client),
                _Factory(_FakeMetrikaClient()),
            )

            diagnostics = result.summary["diagnostics"]["amocrm_lead_48223023"]
            self.assertFalse(diagnostics["lead_created_matches_lead_added"])
            serialized = json.dumps({"summary": result.summary, "stdout": result.stdout, "stderr": result.stderr})
            self.assertNotIn(secret, serialized)
            self.assertNotIn("custom_fields_values", serialized)

    def test_missing_token_while_enabled_blocks_upload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _write_leads(data_dir, [_lead()])
            events_factory = _Factory(_FakeEventsClient())
            metrika_factory = _Factory(_FakeMetrikaClient())

            result = _run(
                data_dir,
                {
                    "METRIKA_OFFLINE_ENABLED": "1",
                    "METRIKA_OFFLINE_DRY_RUN": "0",
                    "AMOCRM_TOKEN": "amo-token",
                },
                events_factory,
                metrika_factory,
            )

            self.assertEqual(result.code, 0)
            self.assertEqual(result.summary["status"], "missing_metrika_token")
            self.assertEqual(result.summary["candidates"], 1)
            self.assertEqual(len(events_factory.calls), 0)
            self.assertEqual(len(metrika_factory.calls), 0)

    def test_no_candidates_does_not_call_http(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _write_leads(
                data_dir,
                [
                    _lead(yclid=""),
                    _lead(status_name="Первичный контакт"),
                    _lead(crm_lead_id=None, crm_entity_id=None),
                ],
            )
            events_factory = _Factory(_FakeEventsClient())
            metrika_factory = _Factory(_FakeMetrikaClient())

            result = _run(
                data_dir,
                {
                    "METRIKA_OFFLINE_ENABLED": "1",
                    "METRIKA_OFFLINE_DRY_RUN": "0",
                    "AMOCRM_TOKEN": "amo-token",
                    "YANDEX_METRIKA_OFFLINE_TOKEN": "metrika-token",
                },
                events_factory,
                metrika_factory,
            )

            self.assertEqual(result.code, 0)
            self.assertEqual(result.summary["status"], "no_candidates")
            self.assertEqual(result.summary["candidates"], 0)
            self.assertEqual(len(events_factory.calls), 0)
            self.assertEqual(len(metrika_factory.calls), 0)

    def test_candidate_filtering_happens_before_api_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            submitted_key = build_idempotency_key("777", "submitted-yclid")
            state = default_metrika_offline_state()
            state["conversions"][submitted_key] = {
                "idempotency_key": submitted_key,
                "yclid": "submitted-yclid",
                "target": "qualified_lead",
                "state": "submitted",
            }
            save_metrika_offline_state(state, data_dir / "metrika_offline_state.json")
            _write_leads(
                data_dir,
                [
                    _lead(crm_lead_id=98765, yclid="valid-yclid"),
                    _lead(yclid=""),
                    _lead(status_name="Первичный контакт"),
                    _lead(crm_lead_id=None, crm_entity_id=None),
                    _lead(crm_lead_id=777, yclid="submitted-yclid"),
                ],
            )
            events_client = _FakeEventsClient()
            metrika_client = _FakeMetrikaClient()
            events_factory = _Factory(events_client)
            metrika_factory = _Factory(metrika_client)

            result = _run(
                data_dir,
                {
                    "METRIKA_OFFLINE_ENABLED": "1",
                    "METRIKA_OFFLINE_DRY_RUN": "0",
                    "AMOCRM_TOKEN": "amo-token",
                    "YANDEX_METRIKA_OFFLINE_TOKEN": "metrika-token",
                },
                events_factory,
                metrika_factory,
            )

            self.assertEqual(result.code, 0)
            self.assertEqual(result.summary["status"], "completed")
            self.assertEqual(result.summary["candidates"], 1)
            self.assertEqual(len(events_factory.calls), 1)
            self.assertEqual(len(events_client.calls), 1)
            self.assertEqual(events_client.calls[0]["filter[entity_id][0]"], 98765)
            self.assertEqual(len(metrika_factory.calls), 1)
            self.assertEqual(len(metrika_client.uploads), 1)

    def test_exception_in_runner_path_exits_zero_and_saves_valid_state(self) -> None:
        secret = "metrika-secret-token"
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _write_leads(data_dir, [_lead()])
            events_factory = _Factory(error=RuntimeError(f"boom {secret}"))

            result = _run(
                data_dir,
                {
                    "METRIKA_OFFLINE_ENABLED": "1",
                    "METRIKA_OFFLINE_DRY_RUN": "0",
                    "AMOCRM_TOKEN": "amo-secret-token",
                    "YANDEX_METRIKA_OFFLINE_TOKEN": secret,
                },
                events_factory,
                _Factory(_FakeMetrikaClient()),
            )

            state = _read_state(data_dir)
            serialized = json.dumps({"state": state, "stdout": result.stdout, "stderr": result.stderr})
            self.assertEqual(result.code, 0)
            self.assertEqual(result.summary["status"], "failed")
            self.assertEqual(state["runner"]["status"], "failed")
            self.assertNotIn(secret, serialized)
            self.assertNotIn("amo-secret-token", serialized)
            self.assertIn("[redacted]", serialized)

    def test_state_file_remains_valid_json_after_disabled_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _write_leads(data_dir, [_lead()])

            result = _run(data_dir, {}, _Factory(_FakeEventsClient()), _Factory(_FakeMetrikaClient()))

            self.assertEqual(result.code, 0)
            state = _read_state(data_dir)
            self.assertEqual(state["schema_version"], 1)
            self.assertIsInstance(state["conversions"], dict)
            self.assertEqual(state["runner"]["status"], "disabled")

    def test_runner_does_not_modify_leads_or_dashboard_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "runtime-data"
            data_dir.mkdir()
            dashboard_root = root / "dashboard_view.json"
            dashboard_daily = data_dir / "dashboard_daily.json"
            dashboard_view = data_dir / "dashboard_view.json"
            _write_leads(data_dir, [_lead()])
            dashboard_root.write_text('{"dashboard":"root"}\n', encoding="utf-8")
            dashboard_daily.write_text('{"dashboard":"daily"}\n', encoding="utf-8")
            dashboard_view.write_text('{"dashboard":"view"}\n', encoding="utf-8")
            before = {
                path: path.read_text(encoding="utf-8")
                for path in (data_dir / "leads.json", dashboard_root, dashboard_daily, dashboard_view)
            }

            result = _run(
                data_dir,
                {"METRIKA_OFFLINE_ENABLED": "1"},
                _Factory(_FakeEventsClient()),
                _Factory(_FakeMetrikaClient()),
            )

            self.assertEqual(result.code, 0)
            for path, content in before.items():
                self.assertEqual(path.read_text(encoding="utf-8"), content)


def _run(
    data_dir: Path,
    env: dict[str, str],
    events_factory: "_Factory",
    metrika_factory: "_Factory",
) -> "_RunResult":
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = run_metrika_offline.run(
        env=env,
        data_dir=data_dir,
        stdout=stdout,
        stderr=stderr,
        events_client_factory=events_factory,
        metrika_client_factory=metrika_factory,
    )
    lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
    summary = json.loads(lines[-1]) if lines else {}
    return _RunResult(code, summary, stdout.getvalue(), stderr.getvalue())


def _write_leads(data_dir: Path, leads: list[dict[str, object]]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "leads.json").write_text(
        json.dumps({"schema_version": 1, "leads": leads}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_state(data_dir: Path) -> dict[str, object]:
    return json.loads((data_dir / "metrika_offline_state.json").read_text(encoding="utf-8"))


def _workflow_step_body(text: str, step_name: str) -> str:
    marker = f"      - name: {step_name}\n"
    start = text.index(marker)
    next_start = text.find("\n      - name:", start + len(marker))
    if next_start == -1:
        return text[start:]
    return text[start:next_start]


def _workflow_step_bodies(text: str) -> list[tuple[str, str]]:
    step_starts = [
        (line.split("- name:", 1)[1].strip(), offset)
        for offset, line in _line_offsets(text)
        if line.startswith("      - name:")
    ]
    result: list[tuple[str, str]] = []
    for index, (name, start) in enumerate(step_starts):
        end = step_starts[index + 1][1] if index + 1 < len(step_starts) else len(text)
        result.append((name, text[start:end]))
    return result


def _line_offsets(text: str) -> list[tuple[int, str]]:
    offsets: list[tuple[int, str]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        offsets.append((offset, line.rstrip("\n")))
        offset += len(line)
    return offsets


def _lead(
    *,
    status_name: str = "Выслано предложение",
    yclid: str = "260903123456789",
    crm_lead_id: int | None = 98765,
    crm_entity_id: int | None = 98765,
) -> dict[str, object]:
    lead: dict[str, object] = {
        "id": f"lead-{yclid or status_name}",
        "fields": {"yclid": yclid},
        "crm_feedback": {
            "status_name": status_name,
            "crm_lead_id": crm_lead_id,
        },
        "crm": {
            "entity_id": crm_entity_id,
        },
    }
    if crm_lead_id is None:
        lead["crm_feedback"] = {"status_name": status_name}
    if crm_entity_id is None:
        lead["crm"] = {}
    return lead


class _RunResult:
    def __init__(self, code: int, summary: dict[str, object], stdout: str, stderr: str) -> None:
        self.code = code
        self.summary = summary
        self.stdout = stdout
        self.stderr = stderr


class _Factory:
    def __init__(self, client: object | None = None, *, error: BaseException | None = None) -> None:
        self.client = client
        self.error = error
        self.calls: list[tuple[object, ...]] = []

    def __call__(self, *args: object) -> object:
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.client


class _FakeEventsClient:
    def __init__(self, *, lead_payload: dict[str, object] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.lead_calls: list[int] = []
        self.lead_payload = lead_payload or {
            "id": 48223023,
            "name": "Diagnostic lead",
            "created_at": 1_788_445_384,
            "updated_at": 1_788_445_392,
            "pipeline_id": QUALIFYING_CRM_PIPELINE_ID,
            "status_id": 79927038,
        }

    def get_events(self, params: dict[str, object]) -> dict[str, object]:
        self.calls.append(dict(params))
        return {
            "_embedded": {
                "events": [
                    {
                        "type": "lead_status_changed",
                        "entity_type": "lead",
                        "entity_id": params["filter[entity_id][0]"],
                        "created_at": 1_788_435_000,
                        "value_after": [
                            {
                                "lead_status": {
                                    "id": 79927038,
                                    "pipeline_id": QUALIFYING_CRM_PIPELINE_ID,
                                }
                            }
                        ],
                    }
                ]
            },
            "_links": {},
        }

    def get_lead(self, lead_id: int) -> dict[str, object]:
        self.lead_calls.append(lead_id)
        return dict(self.lead_payload)


class _FakeMetrikaClient:
    def __init__(self) -> None:
        self.uploads: list[bytes] = []

    def upload_offline_conversion_csv(self, csv_bytes: bytes) -> dict[str, object]:
        self.uploads.append(csv_bytes)
        return {"uploading": {"id": 12345, "status": "UPLOADED"}}


if __name__ == "__main__":
    unittest.main()
