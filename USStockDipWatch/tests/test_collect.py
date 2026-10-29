import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import tempfile
import json
from pathlib import Path

import collect


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 9, 19, 0, tzinfo=timezone.utc)
        self.asset = dict(symbol='QQQ', source='Alpaca IEX', mode='intraday-v2')
        self.bars = [dict(t=(self.now-timedelta(days=i)).isoformat(), c=100)
                     for i in range(1, 240)]
        self.latest = dict(t=(self.now-timedelta(minutes=2)).isoformat(), c=75)

    def test_intraday_tiers_deduplicate_and_recross(self):
        row, alerts = collect.snapshot(self.asset, self.bars, self.latest, {}, self.now)
        self.assertEqual([a['tier'] for a in alerts], [10, 20])
        self.assertEqual(row['drawdown'], 25)
        self.assertEqual(collect.snapshot(self.asset, self.bars, self.latest, row, self.now)[1], [])
        rebound, _ = collect.snapshot(self.asset, self.bars, dict(self.latest, c=95), row, self.now)
        self.assertEqual(len(collect.snapshot(self.asset, self.bars, self.latest, rebound, self.now)[1]), 2)

    def test_incomplete_daily_bar_excluded(self):
        bars = self.bars + [dict(t=self.now.isoformat(), c=1000)]
        row, _ = collect.snapshot(self.asset, bars, self.latest, {}, self.now)
        self.assertEqual(row['peak'], 100)

    def test_stale_and_regressing_prices_rejected(self):
        for latest, old in [(dict(self.latest, t=(self.now-timedelta(hours=2)).isoformat()), {}),
                            (self.latest, dict(priceAsOf=self.now.isoformat()))]:
            with self.assertRaises(ValueError):
                collect.snapshot(self.asset, self.bars, latest, old, self.now)

    def test_pagination_collects_later_symbols(self):
        with patch.dict('os.environ', dict(ALPACA_API_KEY_ID='test', ALPACA_API_SECRET_KEY='test')):
            client = collect.Client()
        with patch.object(client, 'get', side_effect=[dict(bars={'QQQ':[1]}, next_page_token='next'),
                                                      dict(bars={'NVDA':[2]})]):
            self.assertEqual(client.history(['QQQ','NVDA'], self.now), dict(QQQ=[1], NVDA=[2]))

    def test_new_listing_filters_previous_ticker_and_requires_early_history(self):
        asset=dict(self.asset,symbol='SPCX',listingDate='2026-06-12')
        bars=self.bars+[dict(t='2026-05-01T04:00:00Z',c=9999)]
        row,_=collect.snapshot(asset,bars,self.latest,{},self.now)
        self.assertEqual(row['benchmark'],'since-listing')
        self.assertEqual(row['peak'],100)
        self.assertLess(row['coverageDays'],180)
        with self.assertRaises(ValueError):
            collect.snapshot(asset,self.bars[:60],self.latest,{},self.now)
        with self.assertRaises(ValueError):
            collect.snapshot(self.asset,self.bars[:60],self.latest,{},self.now)

    def test_contract_utc_calendar_currency_and_stale_quote(self):
        now=datetime(2026,10,10,1,tzinfo=timezone.utc)
        asset=dict(self.asset,symbol='ANTHROPICUSDT',kind='永续合约',currency='USDT',listingDate='2026-06-02',source='Binance USDⓈ-M')
        bars=[dict(t=(now-timedelta(days=i)).replace(hour=0).isoformat(),c=100) for i in range(1,131)]
        latest=dict(t=(now-timedelta(seconds=5)).isoformat(),c=80)
        row,alerts=collect.snapshot(asset,bars,latest,{},now)
        self.assertEqual(row['asOf'],'2026-10-10')
        self.assertEqual(row['tradingTimezone'],'UTC')
        self.assertIn('USDT',alerts[0]['notes'])
        with self.assertRaises(ValueError):
            collect.snapshot(asset,bars,dict(latest,t=(now-timedelta(minutes=6)).isoformat()),{},now)

    def test_binance_failure_does_not_block_stocks(self):
        with tempfile.TemporaryDirectory() as root, patch('collect.Client') as client, patch('collect.binance_snapshot',side_effect=ValueError('Binance HTTP 451')):
            client.return_value.feed='iex'
            client.return_value.history.return_value={s:self.bars for s in ['QQQ','NVDA','TSLA','SPCX']}
            client.return_value.get.return_value=dict(bars={s:self.latest for s in ['QQQ','NVDA','TSLA','SPCX']})
            with patch('collect.datetime') as dt:
                dt.now.return_value=self.now
                dt.fromisoformat.side_effect=datetime.fromisoformat
                self.assertEqual(collect.run(root),1)
            state=json.loads((Path(root)/'usstockdipwatch/data.json').read_text())
            self.assertEqual(state['healthy'],4)
            self.assertEqual(state['assets'][-1]['error'],'Binance HTTP 451')

    def test_failed_fetch_preserves_old_data_and_alerts(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / 'usstockdipwatch'
            target.mkdir()
            (target/'data.json').write_text(json.dumps(dict(assets=[dict(symbol='QQQ', price=123)],
                                                            alerts=[dict(id='old',date='2026-10-08')])))
            with patch('collect.Client') as client:
                client.return_value.feed = 'iex'
                client.return_value.history.side_effect = ValueError('Alpaca HTTP 403')
                self.assertEqual(collect.run(root), 1)
            state = json.loads((target/'data.json').read_text())
            self.assertEqual(state['assets'][0]['price'], 123)
            self.assertEqual(state['alerts'][0]['id'], 'old')
            self.assertEqual(state['healthy'], 0)


if __name__ == '__main__':
    unittest.main()
