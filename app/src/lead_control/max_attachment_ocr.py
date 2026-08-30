from __future__ import annotations

import logging
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from .max_client import MaxClient, message_attachments

LOG = logging.getLogger(__name__)
MAIL_HEADER_RE = re.compile(r"^\s*заявка\s+(?:сайт|почта)\s*:\s*$", re.IGNORECASE)
PAIR_WINDOW_MS = 10_000


def enrich_max_mail_attachments(events: list[dict[str, Any]], client: MaxClient) -> bool:
    changed = False
    ordered = [
        event
        for event in sorted(events, key=lambda item: int(item.get("timestamp") or 0))
        if event.get("type") == "max_message_created" and event.get("source") == "MAX"
    ]
    by_message_id = {
        str(event.get("message_id") or ""): event
        for event in ordered
        if event.get("message_id")
    }

    for idx, header in enumerate(ordered):
        if not MAIL_HEADER_RE.match(str(header.get("text") or "")):
            continue

        # Historical runs may already have copied attachment metadata onto the
        # header. In that case _has_image(header) is true even though the real
        # image was a separate MAX message, so prefer the stored attachment MID
        # and recover the original image event first.
        stored_attachment_mid = str(header.get("attachment_message_id") or "")
        image_event = None
        if stored_attachment_mid and stored_attachment_mid != str(header.get("message_id") or ""):
            image_event = by_message_id.get(stored_attachment_mid)

        if image_event is None:
            image_event = header if _has_image(header) else _find_paired_image(ordered, idx, header)
        if image_event is None:
            continue

        paired_separate_image = image_event is not header
        if paired_separate_image:
            attachment_mid = image_event.get("message_id")
            if header.get("attachment_message_id") != attachment_mid:
                header["attachment_message_id"] = attachment_mid
                changed = True

            # MAX can deliver the caption/header and the image as two separate
            # adjacent messages. The image message is part of the same mail
            # lead and must never be independently classified as another lead.
            header_mid = header.get("message_id")
            if image_event.get("paired_mail_header_message_id") != header_mid:
                image_event["paired_mail_header_message_id"] = header_mid
                changed = True
            if image_event.get("mail_attachment_only") is not True:
                image_event["mail_attachment_only"] = True
                changed = True

        changed |= _enrich_one_image_event(image_event, client)
        attachments = image_event.get("attachments") or []
        if attachments and header.get("attachments") != attachments:
            header["attachments"] = attachments
            header["attachment_types"] = image_event.get("attachment_types") or ["image"]
            header["has_attachments"] = True
            changed = True

        ocr = str(image_event.get("attachment_ocr_text") or "").strip()
        if ocr and header.get("attachment_ocr_text") != ocr:
            header["attachment_ocr_text"] = ocr
            header["attachment_text"] = ocr
            changed = True

        # Keep OCR on the image event as metadata, but do not expose it through
        # attachment_text: the generic MAX classifier uses attachment_text as
        # message content and would otherwise create a second, false lead from
        # the same screenshot.
        if paired_separate_image and image_event.get("attachment_text"):
            image_event.pop("attachment_text", None)
            changed = True

    return changed


def _find_paired_image(
    events: list[dict[str, Any]],
    index: int,
    header: dict[str, Any],
) -> dict[str, Any] | None:
    ts = int(header.get("timestamp") or 0)
    sender = header.get("sender_user_id")
    chat = header.get("chat_id")
    for event in events[index + 1 : index + 4]:
        ets = int(event.get("timestamp") or 0)
        if ets - ts > PAIR_WINDOW_MS:
            break
        if (
            event.get("sender_user_id") == sender
            and event.get("chat_id") == chat
            and _has_image(event)
        ):
            return event
    return None


def _has_image(event: dict[str, Any]) -> bool:
    types = {str(value).lower() for value in (event.get("attachment_types") or [])}
    if "image" in types or "photo" in types:
        return True
    for item in event.get("attachments") or []:
        if str((item or {}).get("type") or "").lower() in {"image", "photo"}:
            return True
    return False


def _enrich_one_image_event(event: dict[str, Any], client: MaxClient) -> bool:
    changed = False
    mid = str(event.get("message_id") or "")
    attachments = event.get("attachments") or []
    if mid and (not attachments or not _find_urls(attachments)):
        try:
            messages = client.get_messages([mid])
            if messages:
                fetched = message_attachments(messages[0])
                if fetched and fetched != attachments:
                    event["attachments"] = fetched
                    event["attachment_types"] = [
                        str(item.get("type") or "")
                        for item in fetched
                        if item.get("type")
                    ]
                    event["has_attachments"] = True
                    attachments = fetched
                    changed = True
        except RuntimeError as exc:
            LOG.warning(
                "MAX attachment metadata fetch failed message_id=%s error=%s",
                mid,
                exc,
            )

    if event.get("attachment_ocr_text"):
        return changed

    urls = _find_urls(attachments)
    for url in urls:
        text = _ocr_url(url)
        if text:
            event["attachment_ocr_text"] = text
            event["attachment_text"] = text
            return True
    return changed


def _find_urls(value: Any) -> list[str]:
    found: list[tuple[int, str]] = []

    def walk(node: Any, path: str = "") -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                walk(child, f"{path}.{key}".lower())
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{path}[{index}]")
        elif isinstance(node, str) and node.startswith(("http://", "https://")):
            score = 0
            lowered_path = path.lower()
            if any(
                marker in lowered_path
                for marker in ("original", "full", "large", "1024", "1280", "1600", "2048")
            ):
                score += 10
            if any(ext in node.lower() for ext in (".jpg", ".jpeg", ".png", ".webp")):
                score += 3
            found.append((score, node))

    walk(value)
    result: list[str] = []
    for _, url in sorted(found, key=lambda item: -item[0]):
        if url not in result:
            result.append(url)
    return result


def _ocr_url(url: str) -> str:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "LeadControl/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(25 * 1024 * 1024)
            content_type = str(response.headers.get("Content-Type") or "").lower()

        suffix = ".png" if "png" in content_type else ".jpg"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"attachment{suffix}"
            path.write_bytes(data)
            proc = subprocess.run(
                ["tesseract", str(path), "stdout", "-l", "rus+eng", "--psm", "6"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if proc.returncode != 0:
                LOG.warning("Tesseract failed url=%s code=%s", url, proc.returncode)
                return ""
            return _clean_ocr(proc.stdout)
    except Exception as exc:  # keep collector resilient
        LOG.warning("MAX attachment OCR failed url=%s error=%s", url, exc)
        return ""


def _clean_ocr(text: str) -> str:
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in str(text or "").splitlines()
    ]
    return "\n".join(line for line in lines if line).strip()
