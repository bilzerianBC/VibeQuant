"""Read-only Alpaca and Binance market collector. No trading endpoints or third-party dependencies."""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

UTC = timezone.utc
NY = ZoneInfo('America/New_York')
TIERS = (10, 20, 30, 40, 50, 60)
DEFAULTS = [('QQQ', 'Invesco QQQ', 'ETF'), ('NVDA', 'NVIDIA', '股票'),
            ('TSLA', 'Tesla', '股票'), ('SPCX', 'SpaceX', '股票'),
            ('ANTHROPICUSDT', 'Anthropic Pre-IPO 永续合约', '永续合约')]


def timestamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(UTC)


def positive(value):
    return isinstance(value, (int, float)) and math.isfinite(value) and value > 0


class Client:
    def __init__(self):
        self.key = os.environ.get('ALPACA_API_KEY_ID', '')
        self.secret = os.environ.get('ALPACA_API_SECRET_KEY', '')
        self.feed = os.environ.get('ALPACA_DATA_FEED', 'iex')
        if not self.key or not self.secret:
            raise ValueError('缺少 Alpaca API Key ID 或 Secret Key')
        if self.feed not in ('iex', 'sip'):
            raise ValueError('ALPACA_DATA_FEED 只支持 iex 或 sip')
        # Explicit environment-only proxy: never inherit macOS system proxy settings.
        proxies = {scheme: os.environ.get(scheme.upper() + '_PROXY', '')
                   for scheme in ('http', 'https')}
        for proxy in proxies.values():
            if proxy and (urllib.parse.urlsplit(proxy).scheme not in ('http', 'https')
                          or not urllib.parse.urlsplit(proxy).hostname):
                raise ValueError('代理必须是有效的 HTTP/HTTPS URL；不支持 SOCKS')
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))

    def get(self, path, params):
        url = 'https://data.alpaca.markets/v2/stocks/' + path + '?' + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={
            'APCA-API-KEY-ID': self.key, 'APCA-API-SECRET-KEY': self.secret,
            'User-Agent': 'VibeQuant-DipWatch/2'})
        try:
            with self.opener.open(request, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            messages = {401: '密钥无效', 403: '数据权限不足或访问被拒绝',
                        407: '代理认证失败', 429: '请求频率超限'}
            raise ValueError(f'Alpaca HTTP {error.code}：{messages.get(error.code, "接口请求失败")}') from None
        except (OSError, ValueError):
            # Do not log URLs, request headers, proxy credentials or response bodies.
            raise ValueError('网络、代理、TLS 或接口 JSON 错误；请检查配置') from None

    def history(self, symbols, now):
        params = dict(symbols=','.join(symbols), timeframe='1Day',
                      start=(now - timedelta(days=370)).date().isoformat(),
                      end=(now - timedelta(minutes=16)).isoformat(),
                      adjustment='split', feed=self.feed, limit=10000, sort='asc')
        rows = {s: [] for s in symbols}
        seen = set()
        for _ in range(20):
            payload = self.get('bars', params)
            for symbol in symbols:
                rows[symbol].extend(payload.get('bars', {}).get(symbol, []))
            token = payload.get('next_page_token')
            if not token:
                return rows
            if token in seen:
                break
            seen.add(token)
            params['page_token'] = token
        raise ValueError('历史日线分页异常，暂停更新')


def binance_snapshot(client, now):
    """Public market endpoints only; Alpaca credentials are never sent to Binance."""
    def get(path, params):
        url = 'https://fapi.binance.com/fapi/v1/' + path + '?' + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={'User-Agent': 'VibeQuant-DipWatch/3'})
        try:
            with client.opener.open(request, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise ValueError(f'Binance HTTP {error.code}') from None
        except (OSError, ValueError):
            raise ValueError('Binance 网络、代理、TLS 或 JSON 错误') from None
    symbol = 'ANTHROPICUSDT'
    rows = get('klines', dict(symbol=symbol, interval='1d', limit=500,
                             startTime=int((now-timedelta(days=370)).timestamp()*1000)))
    quote = get('ticker/price', dict(symbol=symbol))
    if not isinstance(rows, list) or not rows or not isinstance(quote, dict) or quote.get('symbol') != symbol:
        raise ValueError('Binance 未返回有效合约行情')
    try:
        bars = [dict(t=datetime.fromtimestamp(r[0]/1000, UTC).isoformat(), c=float(r[4]))
                for r in rows if r[6] < now.timestamp()*1000]
        latest = dict(t=datetime.fromtimestamp(int(quote['time'])/1000, UTC).isoformat(),
                      c=float(quote['price']))
    except (KeyError, IndexError, TypeError, ValueError, OverflowError):
        raise ValueError('Binance 合约行情字段无效') from None
    return bars, latest


def snapshot(asset, bars, latest, old, now):
    zone = UTC if asset.get('kind') == '永续合约' else NY
    today = now.astimezone(zone).date()
    listing = asset.get('listingDate')
    recent_listing = bool(listing and datetime.fromisoformat(listing).date() > today-timedelta(weeks=52))
    cutoff = today - timedelta(weeks=52)
    daily = {}
    for bar in bars:
        day = timestamp(bar['t']).astimezone(zone).date()
        if cutoff <= day < today and (not listing or day.isoformat() >= listing) and positive(bar.get('c')):
            daily[day.isoformat()] = bar['c']
    if len(daily) < (30 if recent_listing else 180):
        raise ValueError('新上市标的历史不足 30 根日线' if recent_listing else '历史日线覆盖不足 180 根')
    if recent_listing and datetime.fromisoformat(min(daily)).date() > datetime.fromisoformat(listing).date()+timedelta(days=7):
        raise ValueError('新上市标的缺少上市初期历史日线')
    date, peak = max(daily.items(), key=lambda item: (item[1], item[0]))
    last = timestamp(latest['t'])
    if not positive(latest.get('c')) or last > now or now - last > timedelta(days=5):
        raise ValueError('最新分钟行情无效或已过期')
    if zone == UTC and now-last > timedelta(minutes=5):
        raise ValueError('Binance 合约行情超过 5 分钟未更新')
    # During regular weekday sessions, reject a stalled intraday feed promptly.
    local = now.astimezone(NY)
    if zone != UTC and local.weekday() < 5 and (10, 0) <= (local.hour, local.minute) < (16, 0):
        if now - last > timedelta(minutes=45):
            raise ValueError('盘中行情超过 45 分钟未更新（休市时也暂停新提醒）')
    if old.get('priceAsOf') and last < timestamp(old['priceAsOf']):
        raise ValueError('行情时间倒退')
    price = latest['c']
    levels = [dict(tier=t, price=peak * (1-t/100), reached=price <= peak*(1-t/100)+peak*1e-12)
              for t in TIERS]
    # Legacy daily/provider state is not a compatible threshold baseline.
    previous = {l['tier']: l['reached'] for l in old.get('levels', [])} if old.get('mode') == asset['mode'] and old.get('source') == asset['source'] else {}
    events = []
    for level in levels:
        if level['reached'] and not previous.get(level['tier'], False):
            events.append(dict(id=f"{asset['symbol']}:{last.isoformat()}:{level['tier']}",
                               symbol=asset['symbol'], tier=level['tier'], date=last.astimezone(zone).date().isoformat(),
                               title=f"{asset['symbol']} 回撤达到 {level['tier']}%，关注买入",
                               notes=f"{asset.get('priceType', '分钟收盘价')} {price:.2f} {asset.get('currency', 'USD')}；{'上市以来' if recent_listing else '近52周'}最高日收盘价 {peak:.2f}；{asset['source']}；行情时间 {last.isoformat()}。"))
    return dict(asset, mode='intraday-v2', price=price, priceAsOf=last.isoformat(),
                asOf=last.astimezone(zone).date().isoformat(), peak=peak, peakDate=date,
                drawdown=max(0, (1-price/peak)*100), coverageStart=min(daily),
                coverageDays=len(daily), benchmark='since-listing' if recent_listing else '52-week',
                benchmarkLabel='上市以来最高收盘价' if recent_listing else '近52周最高收盘价',
                tradingTimezone='UTC' if zone == UTC else 'America/New_York', levels=levels, error=None,
                updatedAt=now.isoformat()), events


def atomic_json(path, value):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    try:
        temporary.chmod(0o644)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def run(site_root, diagnose=False):
    now = datetime.now(UTC)
    symbols = list(dict.fromkeys(os.environ.get('DIPWATCH_SYMBOLS', 'QQQ,NVDA,TSLA,SPCX').split(',')))
    if not 1 <= len(symbols) <= 5 or any(not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}', s) for s in symbols):
        raise ValueError('DIPWATCH_SYMBOLS 应包含 1 至 5 个有效美股/ETF代码')
    client = Client()
    if diagnose:
        payload = client.get('bars/latest', dict(symbols=symbols[0], feed=client.feed))
        bar = payload.get('bars', {}).get(symbols[0])
        if not bar or not positive(bar.get('c')):
            raise ValueError('连通成功，但未返回有效分钟行情')
        print(f"Alpaca 连通成功 feed={client.feed} symbol={symbols[0]} timestamp={bar['t']}")
        return 0
    target = Path(site_root) / 'usstockdipwatch'
    target.mkdir(parents=True, exist_ok=True)
    with (target / '.collect.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('另一采集任务正在运行') from None
        path = target / 'data.json'
        previous = json.loads(path.read_text()) if path.exists() else {}
        assets = [dict(symbol=s, name=n, kind=k, currency='USD' if k != '永续合约' else 'USDT') for s,n,k in DEFAULTS]
        for symbol in symbols:
            if symbol not in [a['symbol'] for a in assets]:
                assets.append(dict(symbol=symbol, name=symbol, kind='股票/ETF', currency='USD'))
        # Explicit replacement list of five verified stock symbols replaces pending placeholders.
        if len(symbols) == 5:
            assets = [next(a for a in assets if a['symbol'] == s) for s in symbols]
        for asset in assets:
            if asset['symbol'] == 'SPCX':
                asset['listingDate'] = '2026-06-12'
            elif asset['symbol'] == 'ANTHROPICUSDT':
                asset.update(listingDate='2026-06-02', source='Binance USDⓈ-M',
                             mode='intraday-v2', priceType='合约最新成交价')
        global_error = None
        try:
            history = client.history(symbols, now)
            latest = client.get('bars/latest', dict(symbols=','.join(symbols), feed=client.feed)).get('bars', {})
        except ValueError as error:
            global_error = str(error)
        rows, events = [], {a['id']: a for a in previous.get('alerts', [])}
        for asset in assets:
            old = next((a for a in previous.get('assets', []) if a['symbol'] == asset['symbol']), {})
            try:
                if asset['symbol'] == 'ANTHROPICUSDT':
                    daily_bars, quote = binance_snapshot(client, now)
                else:
                    if asset['symbol'] not in symbols:
                        raise ValueError('标的未加入 DIPWATCH_SYMBOLS 采集配置')
                    if global_error:
                        raise ValueError(global_error)
                    asset.update(source=f'Alpaca {client.feed.upper()}', mode='intraday-v2', priceType='分钟收盘价')
                    daily_bars, quote = history[asset['symbol']], latest[asset['symbol']]
                row, alerts = snapshot(asset, daily_bars, quote, old, now)
                events.update({a['id']: a for a in alerts})
            except (ValueError, KeyError, TypeError):
                import sys
                error = sys.exc_info()[1]
                message = str(error) if isinstance(error, ValueError) else '行情字段缺失或格式错误'
                row = dict(asset, **{k:v for k,v in old.items() if k not in ('symbol','name','kind','currency')})
                row['error'] = message
            rows.append(row)
        state = dict(version=2, mode='intraday-v2', attemptedAt=now.isoformat(), assets=rows,
                     alerts=sorted(events.values(), key=lambda a:(a['date'],a['id']), reverse=True),
                     healthy=sum(not a.get('error') for a in rows), expected=len(rows))
        atomic_json(path, state)
        # iPhone integration remains disabled; the existing reminder schema is retained.
        atomic_json(target / 'reminders.json', dict(configured=False, reminders=state['alerts']))
        print(f"Updated {state['healthy']}/{state['expected']} assets; feed={client.feed}; {path}")
        for row in rows:
            if row.get('error'):
                print(f"{row['symbol']}: {row['error']}")
        return 0 if state['healthy'] == state['expected'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site-root', default=os.environ.get('VIBEQUANT_SITE_DIR', '/srv/web'))
    parser.add_argument('--diagnose', action='store_true', help='One symbol, read-only, no file changes')
    args = parser.parse_args()
    try:
        raise SystemExit(run(args.site_root, args.diagnose))
    except (ValueError, OSError):
        import sys
        error = sys.exc_info()[1]
        print(str(error) if isinstance(error, ValueError) else '本地文件或运行环境错误', flush=True)
        raise SystemExit(2)
