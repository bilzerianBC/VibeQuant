import unittest
from reminder_state import merge, targets


class ReminderStateTests(unittest.TestCase):
    def test_all_levels_exported_even_when_not_reached(self):
        state = dict(assets=[dict(symbol='QQQ',currency='USD',peak=100,peakDate='2026-10-09',
                                 levels=[dict(tier=t,price=100-t,reached=False) for t in (10,20,30,40,50,60)])])
        self.assertEqual(len(targets(state)),6)

    def test_repeated_sync_and_unchecking_preserve_stock_history(self):
        row = dict(id='QQQ:10',symbol='QQQ',tier=10,completed=True,
                   completedAt='2026-10-11T10:00:00+08:00',targetPrice=90)
        state = merge({},[row])
        state = merge(state,[row])
        self.assertEqual(len(state['records'][0]['history']),1)
        state = merge(state,[dict(row, completed=False,completedAt=None)])
        self.assertFalse(state['records'][0]['completed'])
        self.assertEqual(len(state['records'][0]['history']),1)
        state = merge(state,[dict(row,id='TSLA:10',symbol='TSLA')])
        self.assertEqual(len(state['records']),2)

    def test_unknown_ids_rejected(self):
        with self.assertRaises(ValueError):
            merge({},[dict(id='../secret',completed=True)])
