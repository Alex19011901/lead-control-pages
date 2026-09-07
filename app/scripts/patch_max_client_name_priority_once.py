from pathlib import Path

parser = Path("app/src/lead_control/parsers/max_leads.py")
text = parser.read_text(encoding="utf-8")
old = '''    stop_words = {
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
        same_line = re.sub(r"\\b\\d{1,2}[./-]\\d{1,2}(?:[./-]\\d{2,4})?\\b", " ", same_line)
        words = re.findall(r"[А-ЯЁ][а-яё]+(?:\\s+[А-ЯЁ][а-яё]+)?", same_line)
        for word in words:
            tokens = [token.casefold() for token in word.split()]
            if tokens and all(token not in stop_words for token in tokens):
                return word.strip()
'''
new = '''    stop_words = {
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
        "конец",
        "начало",
        "середина",
        "январь",
        "января",
        "февраль",
        "февраля",
        "март",
        "марта",
        "апрель",
        "апреля",
        "май",
        "мая",
        "июнь",
        "июня",
        "июль",
        "июля",
        "август",
        "августа",
        "сентябрь",
        "сентября",
        "октябрь",
        "октября",
        "ноябрь",
        "ноября",
        "декабрь",
        "декабря",
    }

    def first_human_name(fragment: str) -> str:
        fragment = re.sub(r"\\b\\d{1,2}[./-]\\d{1,2}(?:[./-]\\d{2,4})?\\b", " ", fragment)
        words = re.findall(r"[А-ЯЁ][а-яё]+(?:\\s+[А-ЯЁ][а-яё]+)?", fragment)
        for word in words:
            tokens = [token.casefold() for token in word.split()]
            if tokens and all(token not in stop_words for token in tokens):
                return word.strip()
        return ""

    # When a phone and a client name share a line, prefer the text immediately
    # after the phone. This covers formats like "8968... Оксана" and avoids
    # mistaking period words in "Конец декабрь, 150чел.8968... Оксана" for names.
    # If there is no name after the phone, fall back to the text before it so
    # formats like "Ксения 8916..." keep working.
    for line in _nonempty_lines(text):
        if phone_raw not in line:
            continue
        before_phone, _, after_phone = line.partition(phone_raw)
        for fragment in (after_phone, before_phone):
            name = first_human_name(fragment)
            if name:
                return name
'''
count = text.count(old)
if count != 1:
    raise SystemExit(f"Expected exactly one name parser block, found {count}")
parser.write_text(text.replace(old, new, 1), encoding="utf-8")

test = Path("app/tests/test_max_client_name_priority.py")
test.write_text('''from __future__ import annotations\n\nimport unittest\n\nfrom lead_control.parsers.max_leads import HOST, classify_max_event\n\n\nclass MaxClientNamePriorityTest(unittest.TestCase):\n    def test_client_name_after_phone_beats_period_words_and_sender_name(self) -> None:\n        result = classify_max_event({\n            "source": "MAX",\n            "sender_user_id": 205529129,\n            "sender_name": "Святослав",\n            "text": "Заявка:\\nКонец декабрь, 150чел.89688610725 Оксана",\n            "timestamp": 1788784272436,\n            "message_id": "mid.test-oksana",\n        })\n        self.assertEqual(result["classification"], HOST)\n        self.assertEqual(result["fields"]["name"], "Оксана")\n        self.assertEqual(result["fields"]["phone_digits"], "79688610725")\n        self.assertEqual(result["fields"]["guests_count"], 150)\n\n    def test_client_name_before_phone_still_works(self) -> None:\n        result = classify_max_event({\n            "source": "MAX",\n            "sender_user_id": 297178198,\n            "sender_name": "David Romanov",\n            "text": "Заявка\\n1 октября\\n80-100п.\\nАлина 89509579558",\n            "timestamp": 1788430500003,\n            "message_id": "mid.test-alina",\n        })\n        self.assertEqual(result["classification"], HOST)\n        self.assertEqual(result["fields"]["name"], "Алина")\n        self.assertEqual(result["fields"]["phone_digits"], "79509579558")\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding="utf-8")
