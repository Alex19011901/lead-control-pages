from pathlib import Path

parser = Path("app/src/lead_control/parsers/max_leads.py")
text = parser.read_text(encoding="utf-8")
old = '''        fields={
            "telegram_username": normalize_username(username),
            "phone_raw": phone_raw,
            "phone_digits": normalize_phone(phone_raw),
            "event_date_raw": _extract_date_raw(text) or _extract_period_raw(text),
            **(_extract_guest_value(text) or {"guests_count": _extract_guest_count(text)}),
            "description": text.strip(),
        },
    )


def _looks_like_freeform_event_request'''
new = '''        fields={
            "name": _extract_probable_name(text, phone_raw),
            "telegram_username": normalize_username(username),
            "phone_raw": phone_raw,
            "phone_digits": normalize_phone(phone_raw),
            "event_date_raw": _extract_date_raw(text) or _extract_period_raw(text),
            **(_extract_guest_value(text) or {"guests_count": _extract_guest_count(text)}),
            "description": text.strip(),
        },
    )


def _looks_like_freeform_event_request'''

count = text.count(old)
if count != 1:
    raise SystemExit(f"Expected exactly one Olesya TG parser block, found {count}")
parser.write_text(text.replace(old, new, 1), encoding="utf-8")

test = Path("app/tests/test_max_olesya_tg_name.py")
test.write_text('''from __future__ import annotations\n\nimport unittest\n\nfrom lead_control.parsers.max_leads import TG_LEAD, classify_max_event\n\n\nclass OlesyaTelegramLeadNameTest(unittest.TestCase):\n    def test_phone_followed_by_name_is_preserved(self) -> None:\n        text = (\n            "ЗАЯВКА\\n\\n"\n            "Здравствуйте))\\n\\n"\n            "На 13 ноября нужен зал под корпоратив порядка 200 м²\\n"\n            "Тип питания - фуршет\\n"\n            "100 гостей\\n\\n"\n            "Что можете из своих предложить и цены сразу, пожалуйста\\n\\n"\n            "+7 915 158-84-06\\n"\n            "Михаил"\n        )\n        result = classify_max_event({\n            "source": "MAX",\n            "sender_user_id": 48906491,\n            "sender_name": "Олеся",\n            "text": text,\n            "timestamp": 1788777009569,\n            "message_id": "mid.test-mikhail",\n        })\n        self.assertEqual(result["classification"], TG_LEAD)\n        self.assertEqual(result["display_name"], "Заявка с ТГ")\n        self.assertEqual(result["fields"]["phone_digits"], "79151588406")\n        self.assertEqual(result["fields"]["name"], "Михаил")\n        self.assertEqual(result["fields"]["guests_count"], 100)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding="utf-8")
