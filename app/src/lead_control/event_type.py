from __future__ import annotations

import re


_CANONICAL = {
    "свадьба": "Свадьба",
    "свадеба": "Свадьба",
    "wedding": "Свадьба",
    "svadba": "Свадьба",
    "корпоратив": "Корпоратив",
    "нг корпоратив": "Корпоратив",
    "corporate": "Корпоратив",
    "korporativ": "Корпоратив",
    "др": "Юбилей",
    "день рождения": "Юбилей",
    "birthday": "Юбилей",
    "юбилей": "Юбилей",
    "-летие": "Юбилей",
    "летие": "Юбилей",
    "бизнес-завтрак": "Бизнес-завтрак",
    "бизнес завтрак": "Бизнес-завтрак",
    "гала-ужин": "Гала-ужин",
    "гала ужин": "Гала-ужин",
    "клиентский вечер": "Клиентский вечер",
    "тимбилдинг": "Тимбилдинг",
    "team building": "Тимбилдинг",
    "team-building": "Тимбилдинг",
    "конференция": "Конференция",
    "семинар": "Семинар",
    "презентация": "Презентация",
    "выпускной": "Выпускной",
    "поминки": "Поминки",
    "съемки": "Съёмки",
    "съёмки": "Съёмки",
    "съемка": "Съёмки",
    "съёмка": "Съёмки",
    "фотосессия": "Съёмки",
    "банкет": "Банкет",
    "фуршет": "Фуршет",
    "вечеринка": "Вечеринка",
    "семейный ужин": "Семейный ужин",
    "детский праздник": "Детский праздник",
    "новый год": "Новый год",
}


def normalize_event_type(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return ""
    key = text.casefold().replace("ё", "е")
    if key in {"unknown", "не указано", "-", "—"}:
        return ""
    if key in _CANONICAL:
        return _CANONICAL[key]

    inferred = infer_event_type(text)
    return inferred or text


def infer_event_type(value: object) -> str:
    raw = str(value or "")
    if not raw.strip():
        return ""

    lowered = raw.casefold().replace("ё", "е")

    # Strong marketing/page clues are meaningful even when the form has no
    # explicit "event type" field. Example: /weddings/ + UTM campaign Svadba_poisk.
    marketing_patterns = (
        (r"(?:/weddings?(?:/|\b)|\bsvadba\b|\bwedding\b)", "Свадьба"),
        (r"(?:\bkorporativ\b|\bcorporate\b)", "Корпоратив"),
        (r"(?:\bbirthday\b|\bden[_-]?rozhden)", "Юбилей"),
        (r"(?:\byubile\w*\b)", "Юбилей"),
    )
    for pattern, event_type in marketing_patterns:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            return event_type

    # Ignore technical/marketing lines for ordinary Russian word matching so
    # generic campaigns such as Bankety_poisk do not become an event type.
    semantic_lines: list[str] = []
    for line in lowered.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(
            r"^(?:utm\b|utm[_ ]|campaign\s*:|medium\s*:|source\s*:|term\s*:|страница\s*:|https?://|код заявки\s*:|код блока\s*:|transaction id\s*:|block id\s*:)",
            stripped,
            flags=re.IGNORECASE,
        ):
            continue
        semantic_lines.append(stripped)
    semantic = "\n".join(semantic_lines)

    body_patterns = (
        (r"\b(?:свадьб\w*|свадебн\w*|венчани\w*|wedding)\b", "Свадьба"),
        (r"\b(?:тимбилдинг\w*|team[ -]?building)\b", "Тимбилдинг"),
        (r"\b(?:корпоратив\w*|corporate)\b", "Корпоратив"),
        (r"\b(?:день\s+рождения|д\.??\s*р\.??|др)\b", "Юбилей"),
        (r"\bюбиле\w*\b", "Юбилей"),
        (r"(?:\b\d{1,3}\s*[-–—]?\s*)?лети(?:е|я|ю)\b", "Юбилей"),
        (r"\bбизнес[- ]?завтрак\w*\b", "Бизнес-завтрак"),
        (r"\bгала[- ]?ужин\w*\b", "Гала-ужин"),
        (r"\bклиентск\w*\s+вечер\w*\b", "Клиентский вечер"),
        (r"\bконференц\w*\b", "Конференция"),
        (r"\bсеминар\w*\b", "Семинар"),
        (r"\bпрезентац\w*\b", "Презентация"),
        (r"\bвыпускн\w*\b", "Выпускной"),
        (r"\bпомин\w*\b", "Поминки"),
        (r"\b(?:съемк\w*|съёмк\w*|фотосесс\w*)\b", "Съёмки"),
        (r"\bсемейн\w*\s+ужин\w*\b", "Семейный ужин"),
        (r"\bдетск\w*\s+праздник\w*\b", "Детский праздник"),
        (r"\b(?:новый\s+год|новогодн\w*)\b", "Новый год"),
        (r"(?:^|\n)\s*банкет\b|\bформат\s+мероприятия\b.{0,30}\bбанкет\b", "Банкет"),
        (r"(?:^|\n)\s*фуршет\b|\bформат\s+мероприятия\b.{0,30}\bфуршет\b", "Фуршет"),
        (r"\bвечеринк\w*\b", "Вечеринка"),
    )
    for pattern, event_type in body_patterns:
        if re.search(pattern, semantic, flags=re.IGNORECASE | re.DOTALL):
            return event_type

    return ""
