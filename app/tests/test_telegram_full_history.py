from __future__ import annotations

import unittest

from lead_control.telegram_history_202607_202608 import load_history
from lead_control.telegram_history_import import _lead_for_item


class TelegramFullHistoryTests(unittest.TestCase):
    def test_full_history_contains_only_confirmed_historical_leads(self) -> None:
        items = load_history()
        self.assertEqual(len(items), 122)
        by_source = {}
        for item in items:
            source = item["lead"]["source"]
            by_source[source] = by_source.get(source, 0) + 1

        self.assertEqual(by_source["САЙТ ТИЛЬДА"], 101)
        self.assertEqual(by_source["MARQUIZ"], 20)
        self.assertEqual(by_source["Заявка с ТГ"], 1)

        ids = {int(item["id"]) for item in items}
        self.assertNotIn(5666, ids)
        self.assertNotIn(5670, ids)
        self.assertNotIn(5668, ids)  # Cebikova/Tatiana sender id 1366518980
        self.assertNotIn(5433, ids)  # Marquiz test
        self.assertNotIn(5645, ids)  # Tilda test

    def test_parsed_history_item_is_ready_for_normal_import(self) -> None:
        item = next(item for item in load_history() if int(item["id"]) == 5620)
        lead = _lead_for_item(item)
        self.assertIsNotNone(lead)
        self.assertEqual(lead["source"], "Заявка с ТГ")
        self.assertEqual(lead["name"], "Стася Семенова")
        self.assertEqual(lead["phone_digits"], "79265577396")
        self.assertEqual(lead["guests_raw"], "40-50")
        self.assertEqual(lead["event_type"], "Юбилей")
        self.assertEqual(item["sender_name"], "Мишуткина")
        self.assertEqual(item["sender_user_id"], 491166267)


if __name__ == "__main__":
    unittest.main()
