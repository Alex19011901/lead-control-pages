from __future__ import annotations

import copy
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from lead_control.closed_not_realized import (
    _read_preclose_record,
    _extract_text,
    apply_closed_not_realized_history,
)


def ts(day, hour=12):
    return int(datetime(2026, 9, day, hour, tzinfo=ZoneInfo('Europe/Moscow')).timestamp())


def lead(closed_at=None):
    return {
        'id': 'source-a',
        'crm': {'found': True, 'entity_type': 'lead', 'entity_id': 101, 'created_at': ts(10)},
        'crm_feedback': {
            'status_id': 143, 'status_name': 'Закрыто и не реализовано',
            'lead_created_at': ts(10), 'closed_at': closed_at or ts(28),
            'loss_reason_id': 501, 'loss_reason_name': 'Пропала потребность',
            'loss_reason_checked': True,
        },
    }


def note(text, at):
    return {'id': 1, 'entity_id': 101, 'created_at': at, 'note_type': 'common', 'params': {'text': text}}


class Client:
    def __init__(self, notes=None, events=None, tasks=None, fail=None, messages=None):
        self.data = {'notes': notes or [], 'events': events or [], 'tasks': tasks or []}
        self.fail = fail
        self.calls = []
        self.messages = messages or {}
        self.message_calls = []

    def _request_json(self, path, params):
        self.calls.append((path, dict(params)))
        collection = path.rsplit('/', 1)[-1]
        if collection == 'events':
            if 'filter[created_at][from]' not in params or 'filter[created_at][to]' not in params:
                raise RuntimeError('amoCRM request failed: HTTP 400')
        if collection == self.fail:
            raise RuntimeError('amoCRM request failed: HTTP 400')
        return {'_embedded': {collection: copy.deepcopy(self.data[collection])}, '_links': {}}

    def fetch_internal_messages(self, lead_id, message_ids):
        self.message_calls.append((int(lead_id), list(message_ids)))
        return {
            message_id: self.messages[message_id]
            for message_id in message_ids
            if message_id in self.messages
        }

    def _get_entity(self, *args, **kwargs):
        raise AssertionError('Current card is already available; do not reread it')


class PrecloseSnapshotRegressionTests(unittest.TestCase):
    def test_events_use_first_read_as_upper_boundary(self):
        client = Client(notes=[note('До закрытия', ts(28, 9))])
        row = lead()
        apply_closed_not_realized_history([row], client, now_ts=ts(28, 18))
        query = [p for path, p in client.calls if path.endswith('/events')][0]
        self.assertEqual(query['filter[created_at][from]'], 1)
        self.assertEqual(query['filter[created_at][to]'], ts(28, 18))
        self.assertEqual(row['closed_not_realized']['last_comment'], 'До закрытия')

    def test_missing_creation_date_still_sends_positive_lower_bound(self):
        client = Client()
        _read_preclose_record(client, 101, ts(28))
        query = [p for path, p in client.calls if path.endswith('/events')][0]
        self.assertEqual(query['filter[created_at][from]'], 1)

    def test_one_source_error_does_not_erase_notes_or_skip_tasks(self):
        client = Client(notes=[note('Сохранить запись', ts(28, 9))], fail='events')
        result = _read_preclose_record(client, 101, ts(28))
        self.assertEqual(result['last_comment'], 'Сохранить запись')
        self.assertEqual(result['last_record_status'], 'READ_ERROR')
        self.assertFalse(result['last_record_status'] != 'READ_ERROR')
        self.assertEqual(len(client.calls), 3)

    def test_latest_record_available_on_first_read_is_chosen(self):
        client = Client(
            notes=[note('Ранее', ts(28, 8)), note('Позже закрытия', ts(28, 13)), note('В момент закрытия', ts(28))],
            events=[{'entity_id': 101, 'type': 'entity_direct_message', 'created_at': ts(28, 9), 'value_after': [{'message': {'text': 'Сообщение'}}]}],
            tasks=[{'id': 9, 'entity_id': 101, 'updated_at': ts(28, 10), 'is_completed': True, 'result': {'text': 'Результат задачи'}}],
        )
        result = _read_preclose_record(client, 101, ts(28), read_at=ts(28, 18))
        self.assertEqual(result['last_comment'], 'Позже закрытия')
        self.assertEqual(result['last_comment_at'], ts(28, 13))
        self.assertEqual(result['last_record_status'], 'VERIFIED')

    def test_real_message_id_only_is_not_text_or_an_older_note(self):
        client = Client(notes=[note('Старая заметка', ts(28, 8))], events=[{
            'id': 'real-event-id', 'entity_id': 101, 'type': 'entity_direct_message',
            'created_at': ts(28) - 9, 'value_after': [{'message': {'id': 'message-uuid'}}],
        }])
        result = _read_preclose_record(client, 101, ts(28))
        self.assertEqual(result['last_record_status'], 'READ_ERROR')
        self.assertEqual(result['last_comment'], '')
        self.assertEqual(result['last_record_at'], ts(28) - 9)
        self.assertEqual(result['last_record_id'], 'message-uuid')
        self.assertEqual(client.message_calls, [(101, ['message-uuid'])])

    def test_saved_snapshot_avoids_all_history_calls_next_run(self):
        first = lead()
        client = Client(notes=[note('Зафиксировать', ts(28, 10))])
        apply_closed_not_realized_history([first], client, now_ts=ts(28, 18))
        self.assertEqual(len(client.calls), 3)
        second = lead()
        next_client = Client(notes=[note('После закрытия', ts(28, 13))])
        apply_closed_not_realized_history([second], next_client, now_ts=ts(29), previous_leads=[copy.deepcopy(first)])
        self.assertEqual(next_client.calls, [])
        self.assertEqual(second['closed_not_realized']['last_comment'], 'Зафиксировать')
        self.assertEqual(second['preclose_record_cache']['closed_at'], ts(28))

    def test_confirmed_no_record_is_distinct_and_cached(self):
        first = lead()
        apply_closed_not_realized_history([first], Client(), now_ts=ts(28, 18))
        self.assertEqual(first['closed_not_realized']['last_record_status'], 'EMPTY')
        second, client = lead(), Client()
        apply_closed_not_realized_history([second], client, now_ts=ts(29), previous_leads=[first])
        self.assertEqual(client.calls, [])

    def test_legacy_blank_is_not_treated_as_a_completed_snapshot(self):
        old = lead()
        old['closed_not_realized'] = {'crm_lead_id': 101, 'closed_at': ts(28), 'last_comment': '', 'last_comment_at': None}
        new, client = lead(), Client(notes=[note('Восстановлено', ts(28, 10))])
        apply_closed_not_realized_history([new], client, now_ts=ts(28, 18), previous_leads=[old])
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(new['closed_not_realized']['last_comment'], 'Восстановлено')

    def test_different_closing_timestamp_is_a_new_snapshot(self):
        old = lead()
        apply_closed_not_realized_history([old], Client(notes=[note('Первое закрытие', ts(28, 10))]), now_ts=ts(28, 18))
        new, client = lead(ts(29)), Client(notes=[note('Второе закрытие', ts(29, 10))])
        apply_closed_not_realized_history([new], client, now_ts=ts(29, 18), previous_leads=[old])
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(new['closed_not_realized']['last_comment'], 'Второе закрытие')

    def test_duplicate_source_leads_share_one_scan(self):
        a, b, client = lead(), lead(), Client(notes=[note('Один запрос', ts(28, 10))])
        b['id'] = 'source-b'
        apply_closed_not_realized_history([a, b], client, now_ts=ts(28, 18))
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(a['closed_not_realized'], b['closed_not_realized'])

    def test_failed_read_is_not_frozen(self):
        old, client = lead(), Client(fail='events')
        apply_closed_not_realized_history([old], client, now_ts=ts(28, 18))
        new, second = lead(), Client(notes=[note('После устранения ошибки', ts(28, 10))])
        apply_closed_not_realized_history([new], second, now_ts=ts(29), previous_leads=[old])
        self.assertEqual(len(second.calls), 3)
        self.assertEqual(new['closed_not_realized']['last_comment'], 'После устранения ошибки')

    def test_failed_read_preserves_valid_preclose_text_not_afterclose_text(self):
        old = lead()
        old['closed_not_realized'] = {'crm_lead_id': 101, 'closed_at': ts(28), 'last_comment': 'Сохранённая запись', 'last_comment_at': ts(28, 10)}
        new = lead()
        apply_closed_not_realized_history([new], Client(fail='notes'), now_ts=ts(28, 18), previous_leads=[old])
        self.assertEqual(new['closed_not_realized']['last_comment'], 'Сохранённая запись')
        self.assertEqual(new['closed_not_realized']['last_record_status'], 'READ_ERROR')
        self.assertFalse(new['closed_not_realized']['last_record_status'] != 'READ_ERROR')

    def test_system_name_and_ids_are_not_comments(self):
        self.assertEqual(_extract_text({'name': 'Provider', 'id': 'uuid'}), '')
        client = Client(events=[{'entity_id': 101, 'type': 'lead_status_changed', 'created_at': ts(28, 11), 'value_after': [{'name': 'Этап'}]}])
        self.assertEqual(_read_preclose_record(client, 101, ts(28))['last_record_status'], 'EMPTY')

    def test_out_of_window_retains_snapshot_without_display_or_history_read(self):
        old = lead(ts(24))
        apply_closed_not_realized_history([old], Client(notes=[note('История', ts(24, 10))]), now_ts=ts(24, 18))
        new, client = lead(ts(24)), Client()
        apply_closed_not_realized_history([new], client, now_ts=ts(30), previous_leads=[old])
        self.assertNotIn('closed_not_realized', new)
        self.assertEqual(new['preclose_record_cache']['last_comment'], 'История')
        self.assertEqual(client.calls, [])

    def test_nonclosed_card_does_not_reuse_old_closing(self):
        old = lead()
        apply_closed_not_realized_history([old], Client(notes=[note('История', ts(28, 10))]), now_ts=ts(28, 18))
        new, client = lead(), Client()
        new['crm_feedback'] = {'status_id': 123, 'status_name': 'Предбронь'}
        apply_closed_not_realized_history([new], client, now_ts=ts(29), previous_leads=[old])
        self.assertNotIn('closed_not_realized', new)
        self.assertNotIn('preclose_record_cache', new)
        self.assertEqual(client.calls, [])


if __name__ == '__main__':
    unittest.main()
