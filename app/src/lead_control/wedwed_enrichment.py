from __future__ import annotations

import html
import logging
import re
import urllib.request
from typing import Any, Callable

from .normalize import normalize_phone, parse_event_date


LOG = logging.getLogger(__name__)
WEDWED_LINK_RE = re.compile(
    r"https://wedwed\.ru/(?:l/[A-Za-z0-9_-]+|api/viewOrder/[^\s<>\"']+)",
    flags=re.IGNORECASE,
)


def enrich_wedwed_leads(
    leads: list[dict[str, Any]],
    events: list[dict[str, Any]],
    fetch_html: Callable[[str], str] | None = None,
) -> None:
    """Open WedWed request links and promote them to normal CRM-checked leads.

    If the linked page cannot be read or has no phone number, the lead remains
    CRM-not-required and the status policy renders it as '-'.
    """
    fetcher = fetch_html or _fetch_html
    events_by_message_id = {
        str(event.get("message_id")): event
        for event in events
        if event.get("type") == "max_message_created" and event.get("message_id")
    }

    for lead in leads:
        if str(lead.get("source") or "").strip() != "WedWed":
            continue
        if str(lead.get("channel") or "").upper() != "MAX":
            continue

        event = _event_for_lead(lead, events_by_message_id)
        if not event:
            continue
        url = _extract_wedwed_url(str(event.get("text") or ""))
        if not url:
            continue

        try:
            page = fetcher(url)
            data = parse_wedwed_request_page(page)
        except Exception as exc:  # network failures must not break the whole refresh
            LOG.warning("WedWed enrichment failed url=%s error=%s", url, exc)
            continue

        phone_raw = str(data.get("phone_raw") or "").strip()
        phone_digits = normalize_phone(phone_raw)
        if not phone_digits:
            LOG.warning("WedWed page has no phone url=%s", url)
            continue

        fields = lead.setdefault("fields", {})
        fields["source"] = "WedWed"
        fields["category"] = fields.get("category") or lead.get("category") or "WEDWED"
        fields["phone_raw"] = phone_raw
        fields["phone_digits"] = phone_digits
        fields["name"] = str(data.get("name") or "").strip()
        fields["event_date_raw"] = str(data.get("event_date_raw") or "").strip()
        fields["event_date"] = _normalize_event_date(fields["event_date_raw"])
        fields["guests_count"] = data.get("guests_count")
        fields["guests_raw"] = str(data.get("guests_raw") or "").strip()
        fields["wedwed_url"] = url

        lead["identifier"] = {"type": "phone", "value": phone_digits}
        lead["crm_required"] = True
        lead["crm_check_status"] = "PENDING"
        lead["name"] = fields["name"]
        lead["phone"] = phone_raw
        lead["event_date"] = fields["event_date"]
        lead["guests"] = data.get("guests_count")
        lead["guests_raw"] = fields["guests_raw"]
        lead["wedwed_url"] = url


def _event_for_lead(
    lead: dict[str, Any], events_by_message_id: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    message_ids = list((lead.get("max") or {}).get("message_ids") or [])
    if lead.get("message_id"):
        message_ids.append(lead.get("message_id"))
    for message_id in message_ids:
        event = events_by_message_id.get(str(message_id))
        if event and _extract_wedwed_url(str(event.get("text") or "")):
            return event
    return None


def _extract_wedwed_url(text: str) -> str:
    match = WEDWED_LINK_RE.search(text)
    if not match:
        return ""
    return match.group(0).rstrip(".,);]")


def _fetch_html(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "Mozilla/5.0 LeadControl/1.0",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def parse_wedwed_request_page(page: str) -> dict[str, Any]:
    rows: dict[str, str] = {}
    pattern = re.compile(
        r'<h3\b[^>]*class=["\'][^"\']*data-label[^"\']*["\'][^>]*>(.*?)</h3>\s*'
        r'<p\b[^>]*class=["\'][^"\']*data-value[^"\']*["\'][^>]*>(.*?)</p>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    for label_html, value_html in pattern.findall(page):
        label = _clean_html_text(label_html).casefold().replace("ё", "е").rstrip(":")
        value = _clean_html_text(value_html)
        if label:
            rows[label] = value

    event_date_raw = _first(rows, "дата мероприятия")
    guests_raw = _first(rows, "количество гостей")
    name = _first(rows, "имя")
    phone_raw = _first(rows, "телефон")

    guests_count = None
    guest_match = re.search(r"\d{1,4}", guests_raw)
    if guest_match:
        guests_count = int(guest_match.group(0))

    return {
        "event_date_raw": event_date_raw,
        "guests_raw": guests_raw,
        "guests_count": guests_count,
        "name": name,
        "phone_raw": phone_raw,
    }


def _normalize_event_date(value: str) -> str:
    direct = parse_event_date(value)
    if direct:
        return direct
    match = re.search(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b", str(value or ""))
    return parse_event_date(match.group(0)) if match else ""


def _first(rows: dict[str, str], label: str) -> str:
    key = label.casefold().replace("ё", "е")
    return str(rows.get(key) or "").strip()


def _clean_html_text(value: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", value, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()
