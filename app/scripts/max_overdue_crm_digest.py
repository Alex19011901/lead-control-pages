"""Daily 09:00 Moscow digest: overdue MAX/TG leads still missing in amoCRM.

An isolated read-only check. Does not alter Lead Control's main workflow or data.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from build_dashboard_view import LEGACY_NOT_ENTERED_EXCLUSIONS
from lead_control.amocrm_client import AmoCRMClient
from lead_control.crm_apply import _crm_match_is_current_for_lead
from lead_control.max_client import MAX_API_BASE_URL, MAX_CHAT_ID, _ssl_context
from lead_control.normalize import MOSCOW_TZ
from lead_control.status_policy import _crm_entry_deadline, _lead_received_at

DASHBOARD_URL = "https://alex19011901.github.io/lead-control-pages/"
MAX_MESSAGE_LIMIT = 4000


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def snapshot_is_fresh(snapshot: dict[str, Any], now: datetime) -> bool:
    stamp = str(snapshot.get("snapshot_generated_at") or "")
    try:
        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    return bool(dt.tzinfo) and dt.astimezone(MOSCOW_TZ).date() == now.date()


def overdue_candidates(leads: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Use existing ALARM_NO_CRM policy and the dashboard's manual exclusions."""
    result = []
    for lead in leads:
        if lead.get("is_duplicate") or lead.get("crm_required") is False:
            continue
        if lead.get("status") != "ALARM_NO_CRM" or (lead.get("crm") or {}).get("found"):
            continue
        identifier = lead.get("identifier") or {}
        if not isinstance(identifier, dict) or not str(identifier.get("value") or "").strip():
            continue
        received = _lead_received_at(lead)
        deadline = _crm_entry_deadline(lead)
        if received is None or deadline is None or deadline >= now:
            continue
        key = (received.date().isoformat(), str(identifier.get("value") or ""))
        if key in LEGACY_NOT_ENTERED_EXCLUSIONS:
            continue
        result.append(lead)
    return sorted(result, key=lambda item: int(item.get("first_seen_ts") or 0))


def still_missing(leads: list[dict[str, Any]], client: AmoCRMClient) -> list[dict[str, Any]]:
    """If any CRM lookup fails, abort the whole digest instead of posting stale data."""
    result = []
    for lead in leads:
        identifier = lead["identifier"]
        lead_id = str(lead.get("id") or "")
        try:
            found = client.search(
                query=str(identifier.get("value") or ""),
                lead_id=lead_id,
                identifier_type=str(identifier.get("type") or ""),
                target_created_at=int(lead.get("first_seen_ts") or 0) or None,
            )
        except Exception as exc:
            raise RuntimeError(f"CRM verification failed for lead id {lead_id}") from exc
        if not found.found or not _crm_match_is_current_for_lead(lead, found.as_dict()):
            result.append(lead)
    return result


def safe(value: Any, max_len: int = 80) -> str:
    raw = re.sub(r"\s+", " ", str(value or "")).strip()
    raw = raw[:max_len] or "Не указано"
    return re.sub(r"([\\*_\[\]()~])", r"\\\1", raw)


def contact_line(lead: dict[str, Any]) -> tuple[str, str]:
    identifier = lead.get("identifier") or {}
    kind = str(identifier.get("type") or "").strip().lower()
    value = str(identifier.get("value") or "").strip()
    if kind == "phone":
        digits = re.sub(r"\D", "", value)
        if len(digits) == 11 and digits[0] in "78":
            digits = "7" + digits[1:]
            return "Телефон", f"+7 {digits[1:4]} {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
        return "Телефон", safe(value)
    return "Контакт", safe(value)


def message_for(leads: list[dict[str, Any]], date_today: datetime) -> str:
    if not leads:
        raise ValueError("Cannot render an empty overdue digest")
    date_str = date_today.strftime("%d.%m.%Y")
    n = len(leads)
    noun = "заявка" if n % 10 == 1 and n % 100 != 11 else (
        "заявки" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "заявок"
    )
    header = (
        "⚠️ **LEAD CONTROL — НЕ ВНЕСЕНЫ В CRM**\n\n"
        f"📅 {date_str} | 09:00 МСК\n\n"
        f"**Просрочено: {n} {noun}**\n\n"
    )
    footer = (
        "\n❗ Заявки не найдены в amoCRM. Необходимо проверить и внести.\n\n"
        f"[Открыть Lead Control]({DASHBOARD_URL})"
    )
    blocks = []
    shown = 0
    # One MAX message per day; MAX has a strict 4,000 character limit.
    for idx, lead in enumerate(leads, 1):
        received = _lead_received_at(lead)
        deadline = _crm_entry_deadline(lead)
        label, contact = contact_line(lead)
        fields = lead.get("fields") or {}
        name = safe(fields.get("name") or lead.get("name") or "Без имени", 60)
        origin = safe(lead.get("source"), 70)
        block = (
            f"**{idx}. {name}**\n"
            f"- Получена: {received.strftime('%d.%m в %H:%M')}\n"
            f"- Источник: {origin}\n"
            f"- {label}: {contact}\n"
            f"- Срок внесения: {deadline.strftime('%d.%m до %H:%M')}\n"
        )
        overflow = f"\nПоказаны первые {idx} из {n} заявок. Полный список — в Lead Control.\n" if idx < n else ""
        if len(header + "\n".join(blocks + [block]) + overflow + footer) > MAX_MESSAGE_LIMIT:
            break
        blocks.append(block)
        shown = idx
    if not blocks:
        raise ValueError("First overdue entry exceeds MAX message limit")
    extra = f"\nПоказаны первые {shown} из {n} заявок. Полный список — в Lead Control.\n" if shown < n else ""
    body = header + "\n".join(blocks) + extra + footer
    if len(body) > MAX_MESSAGE_LIMIT:
        raise AssertionError("MAX digest exceeds 4,000 characters")
    return body


def send_max_message(text: str, token: str, chat_id: int, ca_file: Path) -> str:
    """One send attempt, no retries after ambiguous network failures."""
    if not token or not text or len(text) > MAX_MESSAGE_LIMIT:
        raise ValueError("MAX credentials or text invalid")
    url = MAX_API_BASE_URL + "/messages?" + urllib.parse.urlencode({
        "chat_id": int(chat_id), "disable_link_preview": "true"
    })
    payload = json.dumps(
        {"text": text, "format": "markdown", "notify": True}, ensure_ascii=False
    ).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers={
        "Authorization": token,
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
    }, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30, context=_ssl_context(str(ca_file))) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"MAX send failed: HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("MAX send failed: network error; no retry") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("MAX send returned invalid JSON; no retry") from exc
    message = result.get("message") if isinstance(result, dict) else None
    if not isinstance(message, dict):
        raise RuntimeError("MAX send returned no message object")
    return str((message.get("body") or {}).get("mid") or message.get("id") or "")


def execute(*, leads_path: Path, snapshot_path: Path, state_path: Path,
            token: str, crm_token: str, crm_domain: str, chat_id: int,
            ca_file: Path, now: datetime | None = None) -> str:
    now = now or datetime.now(MOSCOW_TZ)
    if now.tzinfo is None:
        raise ValueError("Timezone-aware timestamp required")
    now = now.astimezone(MOSCOW_TZ)
    today = now.date().isoformat()
    state = read_json(state_path) if state_path.exists() else {"schema_version": 1}
    if state.get("last_date") == today:
        return "Already checked today; no repeat"
    if now.hour < 9:
        raise RuntimeError("Cannot send the 09:00 Moscow digest before 09:00")
    if not snapshot_is_fresh(read_json(snapshot_path), now):
        raise RuntimeError("Today's Lead Control snapshot is missing; suppressing stale report")
    leads = read_json(leads_path).get("leads") or []
    if not isinstance(leads, list):
        raise ValueError("Lead data is not a list")
    candidates = overdue_candidates(leads, now)
    missing = still_missing(candidates, AmoCRMClient(crm_domain, crm_token)) if candidates else []
    message_id = send_max_message(message_for(missing, now), token, chat_id, ca_file) if missing else ""
    # Only store a daily marker after checks succeeded and MAX returned 200.
    # No client identifiers or message text are stored in the repo.
    new_state = {
        "schema_version": 1,
        "last_date": today,
        "last_count": len(missing),
        "last_sent": bool(missing),
        "last_message_id": message_id,
        "last_checked_at": now.isoformat(timespec="seconds"),
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(new_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(state_path)
    return f"Overdue {len(candidates)}; still missing {len(missing)}; alert sent: {bool(missing)}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--leads", type=Path, default=Path("runtime-data/leads.json"))
    parser.add_argument("--snapshot", type=Path, default=Path("runtime-data/dashboard_view.json"))
    parser.add_argument("--state", type=Path, default=Path("runtime-data/max_overdue_digest_state.json"))
    parser.add_argument("--ca-file", type=Path, default=Path("app/certs/max_ca_bundle.pem"))
    args = parser.parse_args()
    print(execute(
        leads_path=args.leads, snapshot_path=args.snapshot, state_path=args.state,
        token=os.environ["MAX_BOT_TOKEN"], crm_token=os.environ["AMOCRM_TOKEN"],
        crm_domain=os.environ.get("AMOCRM_DOMAIN", "https://alex1901yaru.amocrm.ru"),
        chat_id=int(os.environ.get("MAX_CHAT_ID", str(MAX_CHAT_ID))), ca_file=args.ca_file,
    ))


if __name__ == "__main__":
    main()
