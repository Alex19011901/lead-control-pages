import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from lead_control.closed_not_realized import (
    _extract_text, _read_preclose_record, apply_closed_not_realized_history,
)

CLOSE = int(datetime(2026, 9, 28, 10, 20, tzinfo=ZoneInfo('Europe/Moscow')).timestamp())


def lead():
    return {'id': 'source-a', 'crm': {'found': True, 'entity_type': 'lead', 'entity_id': 101},
            'crm_feedback': {'status_id': 143, 'status_name': 'Закрыто и не реализовано',
                             'closed_at': CLOSE, 'loss_reason_checked': True,
                             'loss_reason_name': 'Пропала потребность'}}


class Client:
    def __init__(self, notes=None, events=None, tasks=None, failure=None):
        self.data = {'notes': notes or [], 'events': events or [], 'tasks': tasks or []}
        self.calls = []
        self.failure = failure

    def _request_json(self, path, params):
        self.calls.append((path, dict(params)))
        collection = path.rsplit('/', 1)[-1]
        if collection == 'events':
            assert params['filter[created_at][from]'] > 0
            assert params['filter[created_at][to]'] == CLOSE - 1
        if collection == self.failure:
            raise RuntimeError('amoCRM request failed: HTTP 400')
        return {'_embedded': {collection: self.data[collection]}, '_links': {}}


def note(text='Запись перед закрытием', ts=CLOSE - 10):
    return {'id': 1, 'entity_id': 101, 'note_type': 'common',
            'created_at': ts, 'params': {'text': text}}


class PrecloseRecordRecoveryTests(unittest.TestCase):
    def test_events_query_has_both_bounds(self):
        record = _read_preclose_record(Client(notes=[note()]), 101, CLOSE)
        self.assertEqual(record['last_comment'], 'Запись перед закрытием')
        self.assertEqual(record['last_record_status'], 'VERIFIED')

    def test_records_at_or_after_closure_are_excluded(self):
        record = _read_preclose_record(Client(notes=[note(), note('После', CLOSE + 1),
                                                       note('Одновременно', CLOSE)]), 101, CLOSE)
        self.assertEqual(record['last_comment_at'], CLOSE - 10)

    def test_error_preserves_previously_saved_text(self):
        prior = lead()
        prior['closed_not_realized'] = {'crm_lead_id': 101, 'closed_at': CLOSE,
                                       'last_comment': 'Сохранённый текст',
                                       'last_comment_at': CLOSE - 5}
        current = lead()
        apply_closed_not_realized_history([current], Client(failure='events'), CLOSE + 60, [prior])
        self.assertEqual(current['closed_not_realized']['last_comment'], 'Сохранённый текст')
        self.assertEqual(current['closed_not_realized']['last_record_status'], 'READ_ERROR')
        self.assertTrue(current['closed_not_realized']['last_record_preserved'])

    def test_one_source_error_does_not_discard_other_source_text(self):
        record = _read_preclose_record(Client(notes=[note()], failure='events'), 101, CLOSE)
        self.assertEqual(record['last_comment'], 'Запись перед закрытием')
        self.assertEqual(record['last_record_status'], 'READ_ERROR')

    def test_successful_result_is_not_read_again_next_run(self):
        first = lead()
        apply_closed_not_realized_history([first], Client(notes=[note()]), CLOSE + 60)
        second, client = lead(), Client()
        apply_closed_not_realized_history([second], client, CLOSE + 120, [first])
        self.assertEqual(client.calls, [])
        self.assertEqual(first['closed_not_realized'], second['closed_not_realized'])

    def test_old_empty_value_is_read_again_once(self):
        prior = lead()
        prior['closed_not_realized'] = {'crm_lead_id': 101, 'closed_at': CLOSE, 'last_comment': ''}
        current, client = lead(), Client(notes=[note()])
        apply_closed_not_realized_history([current], client, CLOSE + 60, [prior])
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(current['closed_not_realized']['last_record_status'], 'VERIFIED')

    def test_message_id_is_not_treated_as_text(self):
        self.assertEqual(_extract_text([{'message': {'id': 'example-message-id'}}]), '')

    def test_newer_message_without_text_is_not_replaced_with_older_note(self):
        event = {'id': 'event-1', 'type': 'entity_direct_message', 'entity_id': 101,
                 'created_at': CLOSE - 5, 'value_after': [{'message': {'id': 'message-1'}}]}
        record = _read_preclose_record(Client(notes=[note()], events=[event]), 101, CLOSE)
        self.assertEqual(record['last_record_status'], 'TEXT_UNAVAILABLE')
        self.assertEqual(record['last_record_at'], CLOSE - 5)
        self.assertEqual(record['last_comment'], '')

    def test_duplicate_dashboard_rows_share_scan(self):
        first, second, client = lead(), lead(), Client(notes=[note()])
        second['id'] = 'source-b'
        apply_closed_not_realized_history([first, second], client, CLOSE + 60)
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(first['closed_not_realized'], second['closed_not_realized'])

    def test_old_record_remains_saved_but_leaves_five_day_widget(self):
        first = lead()
        apply_closed_not_realized_history([first], Client(notes=[note()]), CLOSE + 60)
        second, client = lead(), Client()
        apply_closed_not_realized_history([second], client, CLOSE + 6 * 86400, [first])
        self.assertNotIn('closed_not_realized', second)
        self.assertEqual(second['preclose_record_cache']['last_comment'], 'Запись перед закрытием')
        self.assertEqual(client.calls, [])

    def test_error_result_is_not_frozen(self):
        first = lead()
        apply_closed_not_realized_history([first], Client(failure='notes'), CLOSE + 60)
        second, client = lead(), Client(notes=[note()])
        apply_closed_not_realized_history([second], client, CLOSE + 120, [first])
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(second['closed_not_realized']['last_record_status'], 'VERIFIED')

    def test_old_timestamp_from_another_closure_is_not_reused(self):
        prior = lead()
        prior['closed_not_realized'] = {'crm_lead_id': 101, 'closed_at': CLOSE - 60,
                                       'last_comment': 'Другое закрытие', 'last_comment_at': CLOSE - 120}
        current = lead()
        apply_closed_not_realized_history([current], Client(failure='events'), CLOSE + 60, [prior])
        self.assertEqual(current['closed_not_realized']['last_comment'], '')


if __name__ == '__main__':
    unittest.main()
