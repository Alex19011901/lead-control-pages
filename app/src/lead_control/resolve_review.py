from __future__ import annotations

import argparse
import os
from pathlib import Path

from .amocrm_client import AmoCRMClient
from .normalize import now_moscow_iso
from .processor import apply_crm, rebuild_leads_and_needs_review
from .report import build_report
from .review_overrides import (
    build_override,
    find_needs_review_item,
    normalize_decision,
    review_key,
    overrides_by_key,
    upsert_override,
)
from .state import ensure_data_files, load_events, load_json, save_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve one Lead Control NEEDS_REVIEW item.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--channel", required=True)
    parser.add_argument("--chat-id", required=True, type=int)
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--decision", required=True)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    ensure_data_files(data_dir)

    decision = normalize_decision(args.decision)
    key = review_key(args.channel, args.chat_id, args.message_id)
    needs_review_path = data_dir / "needs_review.json"
    review_overrides_path = data_dir / "review_overrides.json"
    leads_path = data_dir / "leads.json"
    state_path = data_dir / "state.json"

    needs_review_payload = load_json(needs_review_path, {"schema_version": 1, "items": []})
    review_overrides_payload = load_json(review_overrides_path, {"schema_version": 1, "items": []})
    review_items = list(needs_review_payload.get("items", []))
    override_items = list(review_overrides_payload.get("items", []))
    existing_override = overrides_by_key(override_items).get(key)

    review_item = find_needs_review_item(
        review_items,
        channel=args.channel,
        chat_id=args.chat_id,
        message_id=args.message_id,
    )
    if review_item is None and existing_override is None:
        raise SystemExit(f"NEEDS_REVIEW item not found: {key}")
    if review_item is None and existing_override is not None:
        if normalize_decision(str(existing_override.get("decision") or "")) != decision:
            raise SystemExit(f"Override already exists for {key} with another decision")
        print(f"Override already exists: {key} -> {decision}. No changes.")
        return

    assert review_item is not None
    override = build_override(review_item, decision, now_moscow_iso())
    override_items, override_changed = upsert_override(override_items, override)

    print(f"Resolving {key} -> {decision}")
    print(f"Text: {_short_text(str(review_item.get('text') or ''))}")

    events = load_events(data_dir / "events.ndjson")
    leads, needs_review_items = rebuild_leads_and_needs_review(events, review_items, override_items)
    if leads and os.environ.get("AMOCRM_TOKEN"):
        apply_crm(
            leads,
            AmoCRMClient(
                os.environ.get("AMOCRM_DOMAIN", "https://alex1901yaru.amocrm.ru"),
                os.environ["AMOCRM_TOKEN"],
            ),
        )

    state = load_json(state_path, {})
    state["last_data_update_at"] = now_moscow_iso()
    save_json(review_overrides_path, {"schema_version": 1, "items": override_items})
    save_json(leads_path, {"schema_version": 1, "leads": leads})
    save_json(needs_review_path, {"schema_version": 1, "items": needs_review_items})
    save_json(
        data_dir / "latest_report.json",
        build_report(leads, state.get("last_data_update_at"), needs_review_count=len(needs_review_items)),
    )
    save_json(state_path, state)

    print(f"Override stored: {'yes' if override_changed else 'already existed'}")
    print(f"Leads: {len(leads)}")
    print(f"Needs review: {len(needs_review_items)}")


def _short_text(text: str) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= 120:
        return one_line
    return one_line[:117] + "..."


if __name__ == "__main__":
    main()
