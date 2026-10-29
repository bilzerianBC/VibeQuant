"""Shared target and completion-history helpers."""
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import sys
from collect import atomic_json


def targets(state):
    tasks = []
    for asset in state.get('assets', []):
        if asset.get('error'):
            continue
        for level in asset.get('levels', []):
            tasks.append(dict(id=f"{asset['symbol']}:{level['tier']}", symbol=asset['symbol'],
                              tier=level['tier'], targetPrice=level['price'], currency=asset['currency'],
                              peak=asset['peak'], peakDate=asset['peakDate'],
                              title=f"{asset['symbol']} 回撤 {level['tier']}% · {level['price']:.2f} {asset['currency']}",
                              notes=f"基准：近52周最高日收盘价 {asset['peak']:.2f}；高点日期 {asset['peakDate']}。关注买入，不自动交易。"))
    return tasks


def merge(previous, incoming):
    if not isinstance(incoming, list) or len(incoming) > 100:
        raise ValueError('Invalid completion batch')
    records = {r['id']: r for r in previous.get('records', [])}
    for item in incoming:
        identity = item.get('id', '')
        if not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}:(10|20|30|40|50|60)', identity):
            raise ValueError('Invalid task ID')
        if type(item.get('completed')) is not bool or identity != f"{item.get('symbol')}:{item.get('tier')}":
            raise ValueError('Invalid completion status')
        if item['completed']:
            datetime.fromisoformat(item['completedAt'])
        row = {key: item.get(key) for key in ('id', 'symbol', 'tier', 'completed', 'completedAt',
                                             'targetPrice', 'currency', 'peak', 'peakDate')}
        old = records.get(identity, {})
        history = list(old.get('history', []))
        if row['completed'] and (not old.get('completed') or row['completedAt'] != old.get('completedAt')):
            history.append({k:v for k,v in row.items() if k != 'completed'})
        row['history'] = history
        records[identity] = row
    return dict(version=1, syncedAt=datetime.now(timezone.utc).isoformat(),
                records=sorted(records.values(), key=lambda r:r['id']))

