from __future__ import annotations

import logging
from pathlib import Path

from .amocrm_client import AmoCRMClient
from .config import load_config
from .crm_apply import apply_crm
from .crm_feedback import apply_crm_feedback_tracking
from .data_branch import commit_data_if_changed, prepare_data_worktree
from .lead_enrichment import enrich_leads_from_events
from .manual_history import missing_manual_history_events
from .manual_review_fields import enrich_manual_review_fields
from .max_attachment_ocr import enrich_max_mail_attachments
from .max_client import MaxClient, filter_new_max_events, normalize_max_updates
from .max_mail_lead_apply import apply_max_mail_leads
from .normalize import now_moscow_iso
from .processor import collect_known_manager_ids, normalize_updates, rebuild_leads_and_needs_review
from .report import build_report
from .source_categories import (
    filter_known_source_reviews,
    normalize_known_source_events,
    normalize_lead_sources,
)
from .state import (
    append_events,
    ensure_data_files,
    load_events,
    load_json,
    save_events,
    save_json,
    stable_json,
)
from .status_policy import apply_crm_day_status_policy
from .telegram_client import TelegramClient
from .telegram_history_import import import_telegram_history
from .wedwed_enrichment import enrich_wedwed_leads


LOG = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = load_config()
    repo_root = Path.cwd()

    data_worktree_root: Path | None = None
    branch_was_created = False
    if config.use_data_branch:
        data_dir, branch_was_created = prepare_data_worktree(repo_root, config.data_worktree)
        data_worktree_root = config.data_worktree.resolve()
    else:
        data_dir = config.data_dir

    bootstrap_changed = ensure_data_files(data_dir)
    telegram_history_events_added = import_telegram_history(data_dir)
    if telegram_history_events_added:
        LOG.info("Telegram historical events added: %s", telegram_history_events_added)

    state_path = data_dir / "state.json"
    leads_path = data_dir / "leads.json"
    needs_review_path = data_dir / "needs_review.json"
    review_overrides_path = data_dir / "review_overrides.json"
    events_path = data_dir / "events.ndjson"

    state = load_json(state_path, {})
    old_state_json = stable_json(state)
    old_leads_payload = load_json(leads_path, {"schema_version": 1, "leads": []})
    old_leads_json = stable_json(old_leads_payload)
    old_needs_review_payload = load_json(needs_review_path, {"schema_version": 1, "items": []})
    old_needs_review_json = stable_json(old_needs_review_payload)
    review_overrides_payload = load_json(review_overrides_path, {"schema_version": 1, "items": []})

    events = normalize_known_source_events(load_events(events_path))
    manual_history_events = missing_manual_history_events(events)
    if manual_history_events:
        append_events(events_path, manual_history_events)
        events.extend(manual_history_events)
        LOG.info("Manual historical events added: %s", len(manual_history_events))

    existing_update_ids = {int(event["update_id"]) for event in events if "update_id" in event}
    existing_max_message_ids = {
        str(event["message_id"])
        for event in events
        if event.get("source") == "MAX" and event.get("message_id")
    }
    known_manager_ids = collect_known_manager_ids(events)

    telegram = TelegramClient(config.telegram_bot_token)
    next_offset = (state.get("telegram") or {}).get("next_offset")
    updates = telegram.get_updates(offset=next_offset, limit=100, timeout=0)
    max_update_id = max((int(update["update_id"]) for update in updates), default=None)

    new_events = normalize_updates(
        updates=updates,
        chat_id=config.telegram_chat_id,
        existing_update_ids=existing_update_ids,
        known_manager_ids=known_manager_ids,
    )
    new_events = normalize_known_source_events(new_events)
    if new_events:
        append_events(events_path, new_events)
        events.extend(new_events)
    LOG.info("Telegram updates: %s; new events: %s", len(updates), len(new_events))

    offset_changed = False
    if max_update_id is not None:
        new_offset = max_update_id + 1
        telegram_state = state.setdefault("telegram", {})
        if telegram_state.get("next_offset") != new_offset:
            telegram_state["next_offset"] = new_offset
            offset_changed = True

    max_state = state.setdefault("max", {})
    max_marker = max_state.get("marker")
    max_client = MaxClient(config.max_bot_token, ca_file=str(repo_root / "certs" / "max_ca_bundle.pem"))
    max_result = max_client.get_updates(marker=max_marker, timeout=0)
    normalized_max_events = normalize_max_updates(max_result.updates, chat_id=config.max_chat_id)
    new_max_events = filter_new_max_events(normalized_max_events, existing_max_message_ids)
    if new_max_events:
        append_events(events_path, new_max_events)
        events.extend(new_max_events)

    max_attachment_changed = enrich_max_mail_attachments(events, max_client)
    if max_attachment_changed:
        save_events(events_path, events)
        LOG.info("MAX mail attachment events enriched")

    max_marker_changed = False
    if max_result.updates and max_result.marker is not None and max_state.get("marker") != max_result.marker:
        max_state["marker"] = max_result.marker
        max_marker_changed = True
    LOG.info(
        "MAX updates: %s; new events: %s; marker before: %s; marker after: %s",
        len(max_result.updates),
        len(new_max_events),
        max_marker,
        max_state.get("marker"),
    )

    leads, needs_review_items = rebuild_leads_and_needs_review(
        events,
        old_needs_review_payload.get("items", []),
        review_overrides_payload.get("items", []),
    )
    normalize_lead_sources(leads)
    apply_max_mail_leads(leads, events)
    enrich_leads_from_events(leads, events)
    enrich_manual_review_fields(leads, review_overrides_payload.get("items", []))
    enrich_wedwed_leads(leads, events)
    needs_review_items = filter_known_source_reviews(needs_review_items)

    leads_payload = {"schema_version": 1, "leads": leads}
    needs_review_payload = {"schema_version": 1, "items": needs_review_items}
    if leads_payload["leads"]:
        amocrm = AmoCRMClient(config.amocrm_domain, config.amocrm_token)
        previous_leads = old_leads_payload.get("leads", [])
        apply_crm(
            leads_payload["leads"],
            amocrm,
            previous_leads=previous_leads,
            reuse_confirmed=config.fast_refresh,
        )
        apply_crm_feedback_tracking(
            leads_payload["leads"],
            amocrm,
            previous_leads=previous_leads,
            reuse_stable=config.fast_refresh,
        )
    apply_crm_day_status_policy(leads_payload["leads"])

    leads_changed = stable_json(leads_payload) != old_leads_json
    needs_review_changed = stable_json(needs_review_payload) != old_needs_review_json
    data_changed = bool(
        telegram_history_events_added
        or manual_history_events
        or new_events
        or new_max_events
        or max_attachment_changed
        or offset_changed
        or max_marker_changed
        or leads_changed
        or needs_review_changed
    )

    if data_changed:
        state["last_data_update_at"] = now_moscow_iso()

    if bootstrap_changed or data_changed:
        save_json(leads_path, leads_payload)
        save_json(needs_review_path, needs_review_payload)
        save_json(
            data_dir / "latest_report.json",
            build_report(
                leads_payload["leads"],
                state.get("last_data_update_at"),
                needs_review_count=len(needs_review_payload["items"]),
            ),
        )
        save_json(state_path, state)

    if config.use_data_branch and data_worktree_root is not None:
        if commit_data_if_changed(data_worktree_root, "Update lead control data"):
            LOG.info("Data branch updated")
        elif branch_was_created:
            LOG.info("Data branch created with no file changes to commit")
        else:
            LOG.info("No data changes")
    else:
        if stable_json(state) != old_state_json or data_changed or bootstrap_changed:
            LOG.info("Local data files updated")
        else:
            LOG.info("No data changes")


if __name__ == "__main__":
    main()
