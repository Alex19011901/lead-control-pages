from pathlib import Path

# 1) Pair MAX mail screenshots both before and after the explicit mail header.
attachment_path = Path("app/src/lead_control/max_attachment_ocr.py")
attachment_text = attachment_path.read_text(encoding="utf-8")
old_pair = '''def _find_paired_image(
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
'''
new_pair = '''def _find_paired_image(
    events: list[dict[str, Any]],
    index: int,
    header: dict[str, Any],
) -> dict[str, Any] | None:
    ts = int(header.get("timestamp") or 0)
    sender = header.get("sender_user_id")
    chat = header.get("chat_id")
    header_mid = str(header.get("message_id") or "")
    candidates: list[tuple[int, int, dict[str, Any]]] = []

    # MAX may deliver the screenshot immediately before OR after the caption.
    # Search a small symmetric neighborhood and choose the closest image from
    # the same sender/chat inside the existing 10-second pairing window.
    start = max(0, index - 3)
    stop = min(len(events), index + 4)
    for candidate_index in range(start, stop):
        if candidate_index == index:
            continue
        event = events[candidate_index]
        ets = int(event.get("timestamp") or 0)
        if abs(ets - ts) > PAIR_WINDOW_MS:
            continue
        if event.get("sender_user_id") != sender or event.get("chat_id") != chat:
            continue
        if not _has_image(event):
            continue

        paired_to = str(event.get("paired_mail_header_message_id") or "")
        if paired_to and paired_to != header_mid:
            continue
        candidates.append((abs(ets - ts), abs(candidate_index - index), event))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]
'''
if attachment_text.count(old_pair) != 1:
    raise SystemExit(f"Expected one old pairing function, found {attachment_text.count(old_pair)}")
attachment_path.write_text(attachment_text.replace(old_pair, new_pair, 1), encoding="utf-8")

# 2) An explicit mail header must never be silently ignored when its image
# could not be paired. Route it to NEEDS_REVIEW instead.
parser_path = Path("app/src/lead_control/parsers/max_leads.py")
parser_text = parser_path.read_text(encoding="utf-8")
old_classifier = '''    if event_category is not None:
        result = event_category
    elif not classification_text.strip() and has_attachments:
'''
new_classifier = '''    mail_header_without_image = bool(
        re.fullmatch(r"\\s*заявка\\s+почта\\s*:\\s*", event_text, flags=re.IGNORECASE)
    ) and not has_attachments

    if event_category is not None:
        result = event_category
    elif mail_header_without_image:
        result = _needs_review(event_text, "mail_header_without_paired_image")
    elif not classification_text.strip() and has_attachments:
'''
if parser_text.count(old_classifier) != 1:
    raise SystemExit(f"Expected one classifier insertion point, found {parser_text.count(old_classifier)}")
parser_path.write_text(parser_text.replace(old_classifier, new_classifier, 1), encoding="utf-8")

# 3) Regression coverage: today's reverse order and mandatory review fallback.
test_path = Path("app/tests/test_max_mail_historical_pair.py")
test_text = test_path.read_text(encoding="utf-8")
marker = '''    def test_already_enriched_header_still_marks_real_image_as_attachment_only(self):
'''
addition = '''    def test_mail_image_before_header_pairs_and_builds_lead(self):
        header_mid = "mid.mail.header.reverse"
        image_mid = "mid.mail.image.reverse"
        copied_attachment = {"type": "image", "payload": {"photo_id": 39206957415}}
        image = {
            "type": "max_message_created",
            "source": "MAX",
            "update_type": "message_created",
            "chat_id": -71704692523093,
            "message_id": image_mid,
            "body_mid": image_mid,
            "text": "",
            "has_attachments": True,
            "attachment_types": ["image"],
            "attachments": [copied_attachment],
            "attachment_ocr_text": OCR,
            "sender_user_id": 74336871,
            "sender_name": "Al",
            "timestamp": 1788788908730,
        }
        header = {
            "type": "max_message_created",
            "source": "MAX",
            "update_type": "message_created",
            "chat_id": -71704692523093,
            "message_id": header_mid,
            "body_mid": header_mid,
            "text": "Заявка почта:",
            "has_attachments": False,
            "attachments": [],
            "sender_user_id": 74336871,
            "sender_name": "Al",
            "timestamp": 1788788909327,
        }
        events = [image, header]

        self.assertTrue(enrich_max_mail_attachments(events, FakeMaxClient()))
        self.assertEqual(header["attachment_message_id"], image_mid)
        self.assertEqual(header["attachment_ocr_text"], OCR)
        self.assertTrue(image["mail_attachment_only"])
        self.assertEqual(image["paired_mail_header_message_id"], header_mid)

        leads, needs_review = rebuild_leads_and_needs_review(events, existing_needs_review=[])
        apply_max_mail_leads(leads, events)
        self.assertEqual(needs_review, [])
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["source"], "ЗАЯВКА ПОЧТА")
        self.assertEqual(leads[0]["fields"]["name"], "Алена Тимофеева")
        self.assertEqual(leads[0]["identifier"], {"type": "phone", "value": "79636698819"})

    def test_unpaired_mail_header_goes_to_needs_review(self):
        header = {
            "type": "max_message_created",
            "source": "MAX",
            "update_type": "message_created",
            "chat_id": -71704692523093,
            "message_id": "mid.mail.header.unpaired",
            "body_mid": "mid.mail.header.unpaired",
            "text": "Заявка почта:",
            "has_attachments": False,
            "attachments": [],
            "sender_user_id": 74336871,
            "sender_name": "Al",
            "timestamp": 1788789000000,
        }

        leads, needs_review = rebuild_leads_and_needs_review([header], existing_needs_review=[])
        self.assertEqual(leads, [])
        self.assertEqual(len(needs_review), 1)
        self.assertEqual(needs_review[0]["status"], "NEEDS_REVIEW")
        self.assertEqual(needs_review[0]["review_reason"], "mail_header_without_paired_image")
        self.assertEqual(needs_review[0]["text"], "Заявка почта:")

'''
if test_text.count(marker) != 1:
    raise SystemExit(f"Expected one test insertion point, found {test_text.count(marker)}")
test_path.write_text(test_text.replace(marker, addition + marker, 1), encoding="utf-8")
