from __future__ import annotations

import re
from typing import Any

from ..normalize import normalize_phone, normalize_username


TILDA_VERANDA = "TILDA_VERANDA"
WEDWED = "WEDWED"
HOST = "HOST"
STREET = "STREET"
TG_LEAD = "TG_LEAD"
RESTORAN_CAFE = "RESTORAN_CAFE"
SITE_LEAD = "SITE_LEAD"
IGNORE = "IGNORE"
NEEDS_REVIEW = "NEEDS_REVIEW"

DISPLAY_NAMES = {
    TILDA_VERANDA: "Заявка Тильда Веранда",
    WEDWED: "WedWed",
    HOST: "Заявки хост",
    STREET: "С улицы",
    TG_LEAD: "Заявка с ТГ",
    RESTORAN_CAFE: "Restoran.Cafe",
    SITE_LEAD: "Заявка сайт",
    IGNORE: "IGNORE",
    NEEDS_REVIEW: "NEEDS_REVIEW",
}

BUSINESS_SOURCES = {
    TILDA_VERANDA: "Тильда Веранда",
    WEDWED: "WedWed",
    HOST: "Заявки хост",
    STREET: "С улицы",
    TG_LEAD: "Заявка с ТГ",
    RESTORAN_CAFE: "Restoran.Cafe",
    SITE_LEAD: "Заявка сайт",
}

LEAD_CATEGORIES = {TILDA_VERANDA, WEDWED, HOST, STREET, TG_LEAD, RESTORAN_CAFE, SITE_LEAD}

MONTHS_PATTERN = (
    "января|февраля|марта|апреля|мая|июня|июля|августа|сентября|"
    "октября|ноября|декабря"
)


def classify_max_event(event: dict[str, Any]) -> dict[str, Any]:
    event_text = str(event.get("text") or "")
    classification_text = _event_classification_text(event)
    attachment_text = _event_attachment_text(event)
    has_attachments = _event_has_attachments(event)

    event_category = _classify_restoran_cafe_event(event_text, attachment_text, has_attachments)
    if event_category is None:
        event_category = _classify_site_lead_event(event_text, attachment_text, has_attachments)

    if event_category is not None:
        result = event_category
    elif not classification_text.strip() and has_attachments:
        result = _result(
            IGNORE,
            event_text,
            is_lead=False,
            crm_check_required=False,
            review_reason="empty_attachment_without_caption",
        )
    elif _is_olesya_event(event):
        lowered = classification_text.lower()
        tilda = _classify_tilda_veranda(classification_text, lowered)
        wedwed = _classify_wedwed(classification_text, lowered)
        tg_lead = _classify_tg_lead_from_olesya(classification_text)
        if tilda is not None:
            result = tilda
        elif wedwed is not None:
            result = wedwed
        elif tg_lead is not None:
            result = tg_lead
        else:
            result = classify_max_text(classification_text)
    else:
        result = classify_max_text(classification_text)
    result.update(
        {
            "source": "MAX",
            "chat_id": event.get("chat_id"),
            "message_id": event.get("message_id"),
            "sender_user_id": event.get("sender_user_id"),
            "sender_username": event.get("sender_username"),
            "sender_name": event.get("sender_name"),
            "timestamp": event.get("timestamp"),
            "text": classification_text,
        }
    )
    return result


def _classify_restoran_cafe_event(
    event_text: str,
    attachment_text: str,
    has_attachments: bool,
) -> dict[str, Any] | None:
    if not has_attachments:
        return None

    normalized_event = _normalize_space(event_text).lower()
    normalized_attachment = _normalize_space(attachment_text).lower()
    if normalized_event != "заявка":
        return None
    if "restoran.cafe" not in normalized_attachment:
        return None
    if "заявка на банкет" not in normalized_attachment:
        return None

    return _result(
        RESTORAN_CAFE,
        event_text,
        is_lead=True,
        crm_check_required=False,
        fields={
            "description": attachment_text.strip(),
        },
    )


def _classify_site_lead_event(
    event_text: str,
    attachment_text: str,
    has_attachments: bool,
) -> dict[str, Any] | None:
    if not has_attachments:
        return None
    combined_text = _normalize_space("\n".join([event_text, attachment_text])).lower()
    if "заявка сайт" not in combined_text and "заявка почта" not in combined_text:
        return None

    return _result(
        SITE_LEAD,
        event_text or attachment_text,
        is_lead=True,
        crm_check_required=False,
        fields={
            "description": attachment_text.strip() or event_text.strip(),
        },
    )


def classify_max_text(text: str) -> dict[str, Any]:
    normalized_text = _normalize_space(text)
    lowered = normalized_text.lower()

    street = _classify_street(text, lowered)
    if street is not None:
        return street

    ignore_reason = _ignore_reason(text, lowered)
    if ignore_reason:
        if re.match(r"^\s*заявка\b", text, flags=re.IGNORECASE) and _has_review_protected_lead_signal(text):
            return _needs_review(text, f"service_conflict:{ignore_reason}")
        return _result(IGNORE, text, is_lead=False, crm_check_required=False, review_reason=ignore_reason)

    tilda = _classify_tilda_veranda(text, lowered)
    if tilda is not None:
        return tilda

    wedwed = _classify_wedwed(text, lowered)
    if wedwed is not None:
        return wedwed

    tg_lead = _classify_tg_lead(text, lowered)
    if tg_lead is not None:
        return tg_lead

    host = _classify_host(text)
    if host is not None:
        return host

    return _needs_review(text, _review_reason(text))


def _classify_tilda_veranda(text: str, lowered: str) -> dict[str, Any] | None:
    is_tilda = "tildaforms" in lowered or "tilda forms" in lowered or "request details:" in lowered
    if not (is_tilda and "svetliy-moscow.ru" in lowered):
        return None

    fields = _parse_key_value_fields(text)
    phone_raw = fields.get("phone") or _extract_phone_raw(text)
    return _result(
        TILDA_VERANDA,
        text,
        is_lead=True,
        crm_check_required=False,
        fields={
            "name": fields.get("name", ""),
            "event_date_raw": fields.get("event_date") or _extract_date_raw(text),
            "guests_count": _parse_int(fields.get("guests_count")) or _extract_guest_count(text),
            "phone_raw": phone_raw,
            "phone_digits": normalize_phone(phone_raw),
        },
    )


def _classify_wedwed(text: str, lowered: str) -> dict[str, Any] | None:
    if "wedwed" not in lowered:
        return None
    if "новый запрос с сайта wedwed" not in lowered and not (
        "новый запрос" in lowered and "с сайта wedwed" in lowered
    ) and "/api/vieworder/" not in lowered:
        return None

    return _result(
        WEDWED,
        text,
        is_lead=True,
        crm_check_required=False,
        fields={
            "event_date_raw": _extract_date_raw(text),
            "guests_count": _extract_guest_count(text),
        },
    )


def _classify_host(text: str) -> dict[str, Any] | None:
    with_header = _parse_host_with_header(text)
    if with_header is not None:
        return _result(HOST, text, is_lead=True, crm_check_required=True, fields=with_header)

    without_header = _parse_host_without_header(text)
    if without_header is not None:
        return _result(HOST, text, is_lead=True, crm_check_required=True, fields=without_header)

    broad = _parse_host_broad(text)
    if broad is not None:
        return _result(HOST, text, is_lead=True, crm_check_required=True, fields=broad)

    return None


def _classify_street(text: str, lowered: str) -> dict[str, Any] | None:
    explicit_side = "со стороны" in lowered
    explicit_visit = "гости пришли на просмотр" in lowered
    if not explicit_side and not explicit_visit:
        return None

    phone_raw = _extract_phone_raw(text)
    if explicit_visit and not (phone_raw and _extract_guest_count(text) and _extract_date_raw(text)):
        return None

    return _result(
        STREET,
        text,
        is_lead=True,
        crm_check_required=True,
        fields={
            "name": _extract_name_near_contact(text),
            "event_date_raw": _extract_date_raw(text),
            "guests_count": _extract_guest_count(text),
            "phone_raw": phone_raw,
            "phone_digits": normalize_phone(phone_raw),
        },
    )


def _classify_tg_lead(text: str, lowered: str) -> dict[str, Any] | None:
    lines = _nonempty_lines(text)
    if not lines or lines[0].strip().upper() != "ЗАЯВКА":
        return None
    username = _extract_username(text)
    if not username:
        return None
    if not (_extract_date_raw(text) and _extract_guest_count(text)):
        return None

    return _result(
        TG_LEAD,
        text,
        is_lead=True,
        crm_check_required=True,
        fields={
            "telegram_username": normalize_username(username),
            "event_date_raw": _extract_date_raw(text),
            "guests_count": _extract_guest_count(text),
            "description": text.strip(),
        },
    )


def _classify_tg_lead_from_olesya(text: str) -> dict[str, Any] | None:
    compact = _normalize_space(text)
    lowered = compact.lower()
    if "wedwed" in lowered:
        return None
    if not _looks_like_freeform_event_request(text, lowered):
        return None
    contact = _extract_username(text) or _extract_phone_raw(text)
    if not contact:
        return None
    if not (_extract_date_raw(text) or _extract_period_raw(text)):
        return None

    username = _extract_username(text)
    phone_raw = _extract_phone_raw(text)
    return _result(
        TG_LEAD,
        text,
        is_lead=True,
        crm_check_required=True,
        fields={
            "telegram_username": normalize_username(username),
            "phone_raw": phone_raw,
            "phone_digits": normalize_phone(phone_raw),
            "event_date_raw": _extract_date_raw(text) or _extract_period_raw(text),
            **(_extract_guest_value(text) or {"guests_count": _extract_guest_count(text)}),
            "description": text.strip(),
        },
    )


def _looks_like_freeform_event_request(text: str, lowered: str) -> bool:
    if not (re.match(r"^\s*заявка\b", text, flags=re.IGNORECASE) or len(text) >= 120):
        return False
    request_words = (
        "свадьб",
        "банкет",
        "фуршет",
        "мероприят",
        "ужин",
        "корпоратив",
        "зал",
        "площадк",
        "день рождения",
    )
    return any(word in lowered for word in request_words)


def _parse_host_with_header(text: str) -> dict[str, Any] | None:
    if not re.match(r"^\s*заявка\b", text, flags=re.IGNORECASE):
        return None

    compact = _normalize_space(text)
    match = re.search(
        r"заявка\.?\s+"
        r"(?P<date>\d{1,2}[.]\d{1,2}(?:[.]\d{2,4})?)\.?\s+"
        r"(?P<guests>(?:до\s*)?\d{1,4}(?:\s*[-–]\s*\d{1,4})?\s*п\.?)\s+"
        r"(?P<tail>.+)$",
        compact,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    guests = _parse_guest_value(match.group("guests"))
    if guests is None:
        return None

    tail = match.group("tail")
    phone_raw = _extract_phone_raw(tail)
    if phone_raw:
        before_phone, _, after_phone = tail.partition(phone_raw)
        name = before_phone.strip(" .")
    else:
        chunks = [chunk.strip() for chunk in tail.split(".") if chunk.strip()]
        name = chunks[0] if chunks else ""
        after_phone = chunks[1] if len(chunks) > 1 else ""
    if not name or _looks_service_like(name):
        return None

    return {
        "name": name,
        "event_date_raw": match.group("date"),
        **guests,
        "phone_raw": phone_raw,
        "phone_digits": normalize_phone(phone_raw),
        "event_type": _clean_optional_event_type(after_phone),
    }


def _parse_host_without_header(text: str) -> dict[str, Any] | None:
    lines = _nonempty_lines(text)
    if len(lines) < 4:
        return None
    if not re.fullmatch(r"\d{1,2}[.]\d{1,2}(?:[.]\d{2,4})?", lines[0].strip()):
        return None

    guest_match = re.match(
        r"^\s*(?P<guests>(?:до\s*)?\d{1,4}(?:\s*[-–]\s*\d{1,4})?\s*п\.?)\s*(?P<event_type>.*)$",
        lines[1],
        flags=re.IGNORECASE,
    )
    if not guest_match:
        return None
    guests = _parse_guest_value(guest_match.group("guests"))
    if guests is None:
        return None

    phone_raw = _extract_phone_raw(lines[2])
    if not phone_raw:
        return None

    name = lines[3].strip(" .")
    if not name or re.search(r"\d", name) or _looks_service_like(name):
        return None

    return {
        "name": name,
        "event_date_raw": lines[0].strip(),
        **guests,
        "phone_raw": phone_raw,
        "phone_digits": normalize_phone(phone_raw),
        "event_type": _clean_optional_event_type(guest_match.group("event_type")),
    }


def _parse_host_broad(text: str) -> dict[str, Any] | None:
    if _looks_like_phone_name_only(text):
        return None
    if not _extract_phone_raw(text):
        return None

    lowered = text.lower()
    has_header = bool(re.match(r"^\s*заявка\b", text, flags=re.IGNORECASE))
    has_guest = bool(_extract_guest_value(text) or _extract_guest_count(text))
    has_date = bool(_extract_date_raw(text) or _extract_period_raw(text))
    has_event = _has_event_word(lowered)
    has_event_shape = bool(has_guest or has_date or has_event)
    if not has_header and not (has_guest or has_event):
        return None
    if has_header and _looks_like_service_forward(text):
        return None
    if not has_event_shape:
        return None

    phone_raw = _extract_phone_raw(text)
    guests = _extract_guest_value(text) or {"guests_count": _extract_guest_count(text)}
    event_date_raw = _extract_date_raw(text) or _extract_period_raw(text)
    return {
        "name": _extract_probable_name(text, phone_raw),
        "event_date_raw": event_date_raw,
        **guests,
        "phone_raw": phone_raw,
        "phone_digits": normalize_phone(phone_raw),
        "event_type": _extract_event_type(text),
    }


def _ignore_reason(text: str, lowered: str) -> str:
    stripped = text.strip()
    upper = stripped.upper()

    if not stripped:
        return ""
    if _looks_like_short_service_reply(stripped, lowered):
        return "short_service_reply"
    if upper.startswith("БРОНЬ"):
        return "booking_service_message"
    if upper.startswith("ПРОСМОТР") or upper.startswith("ПРОСМОРТ"):
        return "viewing_service_message"
    if upper.startswith("ПРЕДБРОНЬ"):
        return "booking_service_message"
    if upper.startswith("ТЕСТ MAX"):
        return "max_test_message"
    if _looks_like_service_forward(text):
        return "staff_forwarding_or_work_message"
    if _looks_like_phone_name_only(text):
        return "phone_name_without_lead_context"
    if _looks_like_table_booking_service(text, lowered):
        return "table_booking_service_message"
    if "потеряли" in lowered or "потерял" in lowered or "потеряла" in lowered:
        return "lost_items"
    if "очки" in lowered and ("потер" in lowered or "забы" in lowered):
        return "lost_items"
    if "п/о" in lowered:
        return "hall_availability"
    if "есть что-то" in lowered and "глянь" in lowered:
        return "staff_availability_question"
    if _looks_like_room_schedule(text):
        return "room_schedule"
    if ".xlsx" in lowered or ".xls" in lowered or "excel" in lowered:
        return "excel_file"
    if _looks_like_internal_work_message(lowered):
        return "internal_work_message"

    return ""


def _has_review_protected_lead_signal(text: str) -> bool:
    if _extract_phone_raw(text) or _extract_date_raw(text) or _extract_period_raw(text):
        return True

    compact = _normalize_space(text)
    compact = re.sub(r"^\s*заявка[.!:]?\s*", "", compact, flags=re.IGNORECASE)
    stop_words = {
        "заявка",
        "почта",
        "проверь",
        "проверьте",
        "отправил",
        "отправила",
        "кому",
        "переслать",
        "дошло",
        "напоминание",
        "бронь",
        "предбронь",
        "просмотр",
        "коллеги",
        "привет",
    }
    for candidate in re.findall(r"\b[А-ЯЁ][а-яё]{2,}\b", compact):
        if candidate.casefold() not in stop_words:
            return True
    return False


def _looks_like_short_service_reply(stripped: str, lowered: str) -> bool:
    simple = lowered.strip(" .!?)(")
    return simple in {
        "да",
        "ок",
        "окей",
        "есть",
        "мне",
        "я",
        "алло",
        "спасибо",
        "подписал",
        "напоминание",
        "доброе утро",
        "доброе утро)",
        "👍",
    }


def _looks_like_service_forward(text: str) -> bool:
    lowered = text.lower()
    service_fragments = (
        "заявка почта",
        "заявка. кому переслать",
        "заявка кому переслать",
        "завяка почта",
        "отправил на почту",
        "отправил запрос на почту",
        "проверь дошло",
        "проверьте дошло",
        "проверьте отправил",
        "проверьте плз",
        "проверь плз",
        "кому слать",
        "кому переслать",
        "не пропустите",
        "на почту переслал",
        "заявки переслал",
        "напишите дошли",
    )
    return any(fragment in lowered for fragment in service_fragments)


def _looks_like_phone_name_only(text: str) -> bool:
    compact = _normalize_space(text)
    if "\n" in text.strip() or len(compact) > 80:
        return False
    phone_raw = _extract_phone_raw(compact)
    if not phone_raw:
        return False
    without_phone = compact.replace(phone_raw, " ").strip(" .,;:-")
    if not without_phone:
        return False
    lowered = compact.lower()
    if _extract_date_raw(compact) or _extract_guest_count(compact) or _has_event_word(lowered):
        return False
    return bool(re.fullmatch(r"[A-Za-zА-Яа-яЁё ]{2,60}", without_phone))


def _looks_like_table_booking_service(text: str, lowered: str) -> bool:
    if _extract_phone_raw(text):
        return False
    compact = _normalize_space(text)
    if "запишите меня" in lowered:
        return True
    if "запиши плз" in lowered:
        return True
    if re.fullmatch(
        r"\d{1,3}\s*(?:человек|чел\.?|персон|перс|п\.?)\s+(?:веранда|вип|камин(?:ка|ный зал)?|малый зал|зал)",
        compact,
        flags=re.IGNORECASE,
    ):
        return True
    return False


def _looks_like_internal_work_message(lowered: str) -> bool:
    fragments = (
        "проверьте плз",
        "проверь плз",
        "проверьте отправил",
        "малый свободен",
        "что нужно от заказчика",
        "презентац",
        "вип подтвержден",
        "вип подтврежден",
        "все будут",
        "подтвердились",
        "дошёл",
        "дошел",
        "случайно",
        "флешку",
        "носитель",
        "книги броней",
        "детали в календаре",
        "подробности в календаре",
        "обратная связь",
        "для хостес",
        "будут в",
        "изменили время",
        "если будут звонить",
        "попросили связаться",
        "позвоните у меня",
        "показал",
        "зал понравился",
        "хотят весь этаж",
        "ждут меню",
        "депозит сказал",
        "так и писать",
        "покажем",
        "уже приехала",
        "пообедала",
        "склоняется",
        "приезжали",
        "потеряли",
        "потерял",
        "потеряла",
        "дегустация",
        "фуршет 2 эт п/о",
        "бюджет ей озвучили",
        "озвучивали бюджет",
        "подтверждали",
        "едут",
        "моя смена",
        "свяжусь",
        "напишите контакт",
        "напишите, пожалуйста, контакт",
        "только малый зал свободен",
        "а здесь др",
        "здесь",
        "денег дал",
        "деньги дал",
        "спам",
        "на заявках",
        "заявки с формы квиз",
        "канал для статистики",
        "бартером",
        "пожар",
        "вентиляц",
        "кровлю",
        "запишите меня",
        "персоналу",
        "магний",
        "к показу",
        "стало известно",
        "рассматривают как",
        "приехала по приглашению",
        "велся диалог",
        "просмотр в течении часа",
        "сразу перезвонила",
        "что то есть",
        "коллеги привет",
        "нет, сразу проверил",
        "привет! нет",
        "в табличке пусто",
    )
    return any(fragment in lowered for fragment in fragments)


def _looks_like_room_schedule(text: str) -> bool:
    lines = _nonempty_lines(text)
    if not lines or _extract_phone_raw(text):
        return False

    hall_words = ("вип", "каминка", "камин", "веранда", "малый зал", "зал")
    time_lines = 0
    for line in lines:
        lowered = line.lower()
        if any(word in lowered for word in hall_words) and re.search(r"\b\d{1,2}[.:]\d{2}\b", lowered):
            time_lines += 1
    return time_lines >= 1 and len(lines) <= 5


def _result(
    classification: str,
    text: str,
    *,
    is_lead: bool,
    crm_check_required: bool | None,
    fields: dict[str, Any] | None = None,
    review_reason: str = "",
) -> dict[str, Any]:
    result = {
        "classification": classification,
        "display_name": DISPLAY_NAMES[classification],
        "is_lead": is_lead,
        "include_in_stats": classification in LEAD_CATEGORIES,
        "crm_check_required": crm_check_required,
        "text": text,
        "fields": fields or {},
    }
    if classification in BUSINESS_SOURCES:
        result["business_source"] = BUSINESS_SOURCES[classification]
    if review_reason:
        result["review_reason"] = review_reason
    return result


def _needs_review(text: str, reason: str) -> dict[str, Any]:
    return _result(
        NEEDS_REVIEW,
        text,
        is_lead=False,
        crm_check_required=False,
        review_reason=reason,
    )


def _review_reason(text: str) -> str:
    if _extract_phone_raw(text) or _extract_username(text) or _extract_date_raw(text):
        return "ambiguous_contact_or_event_details"
    return "unmatched_max_message"


def _event_classification_text(event: dict[str, Any]) -> str:
    text = str(event.get("text") or "")
    if text.strip():
        return text

    return _event_attachment_text(event)


def _event_attachment_text(event: dict[str, Any]) -> str:
    direct_parts = [
        event.get("caption"),
        event.get("body_caption"),
        event.get("attachment_text"),
        event.get("attachment_caption"),
        event.get("linked_or_forwarded_text"),
        event.get("linked_text"),
        event.get("forwarded_text"),
    ]
    for value in direct_parts:
        if isinstance(value, str) and value.strip():
            return value

    attachment_parts: list[str] = []
    attachments = event.get("attachments")
    if isinstance(attachments, list):
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            for key in ("caption", "text", "description"):
                value = attachment.get(key)
                if isinstance(value, str) and value.strip():
                    attachment_parts.append(value.strip())
            payload = attachment.get("payload")
            if isinstance(payload, dict):
                for key in ("caption", "text", "description"):
                    value = payload.get(key)
                    if isinstance(value, str) and value.strip():
                        attachment_parts.append(value.strip())

    return "\n".join(attachment_parts)


def _event_has_attachments(event: dict[str, Any]) -> bool:
    if event.get("has_attachments"):
        return True
    if event.get("has_linked_or_forwarded_message"):
        return True
    attachments = event.get("attachments")
    return isinstance(attachments, list) and bool(attachments)


def _parse_key_value_fields(text: str) -> dict[str, str]:
    aliases = {
        "name": {"name", "имя", "ваше имя"},
        "phone": {"phone", "телефон", "номер телефона"},
        "event_date": {"дата мероприятия", "дата", "event date"},
        "guests_count": {"количество персон", "количество_персон", "количество гостей", "кол-во гостей", "гостей", "guests"},
    }
    result: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*([^:=]{2,80})\s*[:=]\s*(.+?)\s*$", line)
        if not match:
            continue
        label = _normalize_space(match.group(1)).lower()
        value = match.group(2).strip()
        for field_name, labels in aliases.items():
            if label in labels:
                result[field_name] = value
                break
    return result


def _extract_phone_raw(text: str) -> str:
    separator = r"[ \t\u00a0().-]*"
    patterns = [
        rf"(?<!\d)(?:\+7|7|8)(?:{separator}\d){{10}}(?!\d)",
        rf"(?<!\d)9(?:{separator}\d){{9}}(?!\d)",
    ]
    for line in text.splitlines():
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                return match.group(0).strip()
    return ""


def _extract_username(text: str) -> str:
    match = re.search(r"@([A-Za-z0-9_]{3,})", text)
    return match.group(1) if match else ""


def _extract_date_raw(text: str) -> str:
    numeric = re.search(r"\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b", text)
    if numeric:
        return numeric.group(0)
    month = re.search(rf"\b\d{{1,2}}\s+(?:{MONTHS_PATTERN})\b", text, flags=re.IGNORECASE)
    return month.group(0) if month else ""


def _extract_period_raw(text: str) -> str:
    patterns = [
        rf"\b(?:конец|начало|середина|первая половина|вторая половина)\s+(?:{MONTHS_PATTERN})\b",
        rf"\b(?:{MONTHS_PATTERN})\s+\d{{4}}\b",
        r"\b(?:июль|июле|август|августе|сентябрь|сентябре|октябрь|октябре|ноябрь|ноябре|декабрь|декабре)\b(?:\s+\d{4})?",
        r"\bдата\s+(?:открыта|не\s+известна|под\s+вопросом|нет)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return ""


def _extract_guest_count(text: str | None) -> int | None:
    if not text:
        return None
    direct = _parse_int(text) if re.fullmatch(r"\s*\d{1,4}\s*", text) else None
    if direct is not None:
        return direct

    match = re.search(
        r"\b(?:от\s+)?(?P<count>\d{1,4})\s*(?:чел\.?|человек|гост(?:ей|я|ь)?|персон|перс|п\.?)\b",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return int(match.group("count"))

    guest_first = re.search(
        r"\b(?:гост(?:ей|я|ь)?|человек|персон)\b.{0,40}?\b(?:от\s+)?(?P<count>\d{1,4})\b",
        text,
        flags=re.IGNORECASE,
    )
    return int(guest_first.group("count")) if guest_first else None


def _extract_guest_value(text: str) -> dict[str, int | str | None] | None:
    patterns = [
        r"\bдо\s*\d{1,4}\s*(?:п\.?|персон|перс|чел\.?|человек|гостей)\b",
        r"\b\d{1,4}\s*[-–]\s*\d{1,4}\s*(?:п\.?|персон|перс|чел\.?|человек|гостей)\b",
        r"\b(?:от\s*)?\d{1,4}\s*до\s*\d{1,4}\s*(?:п\.?|персон|перс|чел\.?|человек|гостей)\b",
        r"\b\d{1,4}\s*(?:п\.?|персон|перс|чел\.?|человек|гостей)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw = match.group(0)
        parsed = _parse_guest_value(_normalize_guest_for_parse(raw))
        if parsed is not None:
            parsed["guests_raw"] = _normalize_guest_raw(raw)
            return parsed
    return None


def _parse_guest_value(value: str) -> dict[str, int | str | None] | None:
    raw = _normalize_guest_raw(value)
    lowered = raw.lower()

    up_to = re.fullmatch(r"до\s*(?P<max>\d{1,4})\s*п\.?", lowered)
    if up_to:
        return {
            "guests_raw": raw,
            "guests_min": None,
            "guests_max": int(up_to.group("max")),
            "guests_count": None,
        }

    range_match = re.fullmatch(r"(?P<min>\d{1,4})\s*[-–]\s*(?P<max>\d{1,4})\s*п\.?", lowered)
    if range_match:
        guests_min = int(range_match.group("min"))
        guests_max = int(range_match.group("max"))
        if guests_min > guests_max:
            return None
        return {
            "guests_raw": raw,
            "guests_min": guests_min,
            "guests_max": guests_max,
            "guests_count": None,
        }

    count_match = re.fullmatch(r"(?P<count>\d{1,4})\s*п\.?", lowered)
    if count_match:
        count = int(count_match.group("count"))
        return {
            "guests_raw": raw,
            "guests_min": None,
            "guests_max": None,
            "guests_count": count,
        }

    return None


def _normalize_guest_raw(value: str) -> str:
    raw = re.sub(r"\s+", " ", value.strip())
    raw = re.sub(r"\s*([-.–])\s*", r"\1", raw)
    raw = re.sub(r"\s*п\.?$", "п.", raw, flags=re.IGNORECASE)
    return raw


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None


def _normalize_guest_for_parse(value: str) -> str:
    raw = _normalize_space(value)
    raw = re.sub(r"\b(?:персон|перс|чел\.?|человек|гостей)\b", "п.", raw, flags=re.IGNORECASE)
    range_words = re.fullmatch(
        r"(?:от\s*)?(?P<min>\d{1,4})\s*до\s*(?P<max>\d{1,4})\s*п\.?",
        raw,
        flags=re.IGNORECASE,
    )
    if range_words:
        return f"{range_words.group('min')}-{range_words.group('max')}п."
    return raw


def _extract_name_near_contact(text: str) -> str:
    lines = _nonempty_lines(text)
    phone_raw = _extract_phone_raw(text)
    if not phone_raw:
        return ""

    for index, line in enumerate(lines):
        if phone_raw in line:
            for candidate in lines[index + 1 : index + 3]:
                cleaned = candidate.strip(" .")
                if cleaned and not re.search(r"\d", cleaned) and not _looks_service_like(cleaned):
                    return cleaned
    return ""


def _clean_optional_event_type(value: str) -> str:
    cleaned = value.strip(" .")
    if not cleaned:
        return ""
    if re.fullmatch(r"[A-Za-zА-Яа-яЁё -]{3,40}", cleaned):
        return cleaned
    return ""


def _looks_service_like(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in ("бронь", "просмотр", "п/о", "вип", "каминка"))


def _has_event_word(lowered: str) -> bool:
    if re.search(r"\bдр\b", lowered, flags=re.IGNORECASE):
        return True
    return any(
        word in lowered
        for word in (
            "свадьб",
            "корпоратив",
            "юбилей",
            "день рождения",
            "банкет",
            "фуршет",
            "поминки",
            "съемк",
            "сьемк",
            "бизнес",
            "завтрак",
            "мероприят",
            "кино",
            "аренда",
            "закрытие",
            "условия",
            "меню",
            "весь ресторан",
            "весь этаж",
            "мал зал",
            "малый зал",
            "основной зал",
            "оз",
            "веранда",
        )
    )


def _extract_event_type(text: str) -> str:
    lowered = text.lower()
    if re.search(r"\bдр\b", lowered, flags=re.IGNORECASE) or "день рождения" in lowered:
        return "ДР"
    for value, needles in (
        ("Свадьба", ("свадьб",)),
        ("Корпоратив", ("корпоратив",)),
        ("Юбилей", ("юбилей",)),
        ("Фуршет", ("фуршет",)),
        ("Поминки", ("поминки",)),
        ("Съемки", ("съемк", "сьемк", "кино")),
        ("Бизнес-завтрак", ("бизнес-завтрак", "бизнес завтрак")),
    ):
        if any(needle in lowered for needle in needles):
            return value
    return ""


def _extract_probable_name(text: str, phone_raw: str) -> str:
    if not phone_raw:
        return ""

    stop_words = {
        "заявка",
        "свадьба",
        "корпоратив",
        "юбилей",
        "дата",
        "игра",
        "мафия",
        "выпускной",
        "выпускные",
        "банкет",
        "фуршет",
        "мероприятие",
        "или",
        "до",
        "весь",
        "малый",
        "основной",
    }

    # Highest priority: a human name written on the same line as the phone.
    # This preserves free-form host requests such as:
    # "Ксения 8916...", "Ангелина 8983...", "04.09 Валерия 8917...".
    for line in _nonempty_lines(text):
        if phone_raw not in line:
            continue
        same_line = line.replace(phone_raw, " ")
        same_line = re.sub(r"\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b", " ", same_line)
        words = re.findall(r"[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?", same_line)
        for word in words:
            tokens = [token.casefold() for token in word.split()]
            if tokens and all(token not in stop_words for token in tokens):
                return word.strip()

    # Fallback for older host formats where the name is not on the phone line.
    compact = _normalize_space(text)
    before, _, after = compact.partition(phone_raw)
    for candidate in (after, before):
        words = re.findall(r"[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?", candidate)
        for word in words:
            tokens = [token.casefold() for token in word.split()]
            if tokens and all(token not in stop_words for token in tokens):
                return word.strip()
    return ""


def _is_olesya_event(event: dict[str, Any]) -> bool:
    sender_id = event.get("sender_user_id")
    sender_name = str(event.get("sender_name") or "").lower()
    return sender_id == 48906491 or "олеся" in sender_name


def _nonempty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())
