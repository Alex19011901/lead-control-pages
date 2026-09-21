from __future__ import annotations

from lead_control.lead_enrichment import enrich_leads_from_events
from lead_control.normalize import THREE_DAYS_SECONDS


def _lead(
    phone: str,
    first_seen_ts: int,
    *,
    channel: str,
    source: str,
    message_id: str,
) -> dict:
    lead = {
        "id": f"{channel}:{message_id}",
        "source": source,
        "channel": channel,
        "first_seen_ts": first_seen_ts,
        "first_seen_at": str(first_seen_ts),
        "last_seen_ts": first_seen_ts,
        "last_seen_at": str(first_seen_ts),
        "identifier": {"type": "phone", "value": phone},
        "fields": {"phone_digits": phone},
        "phone": phone,
        "crm_required": True,
        "manager_reaction": None,
    }
    if channel == "MAX":
        lead["message_id"] = message_id
        lead["max"] = {"message_ids": [message_id]}
    else:
        lead["telegram"] = {"message_ids": [int(message_id)], "update_ids": [int(message_id)]}
    return lead


def test_same_phone_same_day_is_one_lead_even_for_different_max_sources() -> None:
    first = _lead(
        "79852337945",
        1_000_000,
        channel="MAX",
        source="Заявки хост",
        message_id="101",
    )
    second = _lead(
        "+7 (985) 233-79-45",
        1_000_000 + 9 * 60 * 60,
        channel="MAX",
        source="Restoran.Cafe",
        message_id="102",
    )
    leads = [first, second]

    enrich_leads_from_events(leads, [])

    assert len(leads) == 1
    assert leads[0] is first
    assert leads[0]["source"] == "Заявки хост"
    assert leads[0]["max"]["message_ids"] == ["101", "102"]


def test_same_phone_is_duplicate_across_channels() -> None:
    telegram = _lead(
        "89852337945",
        2_000_000,
        channel="TELEGRAM",
        source="Telegram",
        message_id="201",
    )
    max_lead = _lead(
        "79852337945",
        2_000_000 + 60,
        channel="MAX",
        source="MAX",
        message_id="202",
    )
    leads = [telegram, max_lead]

    enrich_leads_from_events(leads, [])

    assert len(leads) == 1
    assert leads[0] is telegram
    assert leads[0]["telegram"]["message_ids"] == [201]
    assert leads[0]["max"]["message_ids"] == ["202"]


def test_same_phone_after_duplicate_window_remains_new_lead() -> None:
    first = _lead(
        "79852337945",
        3_000_000,
        channel="MAX",
        source="Заявки хост",
        message_id="301",
    )
    later = _lead(
        "79852337945",
        3_000_000 + THREE_DAYS_SECONDS + 1,
        channel="MAX",
        source="Restoran.Cafe",
        message_id="302",
    )
    leads = [first, later]

    enrich_leads_from_events(leads, [])

    assert len(leads) == 2
