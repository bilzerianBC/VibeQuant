export const THRESHOLDS = [10, 20, 30, 40, 50, 60];
export const WATCHLIST = [
  { symbol: 'QQQ', name: 'Invesco QQQ', kind: 'ETF', currency: 'USD', source: 'Yahoo Finance', minBars: 180 },
  { symbol: 'NVDA', name: 'NVIDIA', kind: '股票', currency: 'USD', source: 'Yahoo Finance', minBars: 180 },
  { symbol: 'TSLA', name: 'Tesla', kind: '股票', currency: 'USD', source: 'Yahoo Finance', minBars: 180 },
  { symbol: 'SPCX', name: 'SpaceX', kind: '股票', currency: 'USD', source: 'Yahoo Finance', minBars: 2 },
  { symbol: 'ANTHROPICUSDT', name: 'Anthropic', kind: '永续合约', currency: 'USDT', source: 'Binance USDⓈ-M', minBars: 2 },
];
const DAY = 86400000;
export function normalizeBars(bars, now = Date.now(), lookbackDays = 364) {
  const cutoff = new Date(now - lookbackDays * DAY).toISOString().slice(0, 10);
  const dedup = new Map();
  for (const bar of bars) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(bar.date) || !Number.isFinite(bar.close) || bar.close <= 0) continue;
    if (bar.date < cutoff || !Number.isFinite(bar.end) || bar.end > now) continue;
    dedup.set(bar.date, bar);
  }
  return [...dedup.values()].sort((a, b) => a.date.localeCompare(b.date));
}
export function computeSnapshot(asset, input, previous, now = Date.now()) {
  const full = normalizeBars(input, now, 728);
  const bars = normalizeBars(full, now);
  if (bars.length < asset.minBars) throw new Error('历史数据覆盖不足');
  const last = bars.at(-1);
  const maxAge = asset.kind === '永续合约' ? 36 * 3600000 : 5 * DAY;
  if (now - last.end > maxAge) throw new Error('行情已过期，暂停生成提醒');
  if (previous?.asOf && last.date < previous.asOf) throw new Error('行情日期倒退，保留上一份结果');
  const peak = bars.reduce((best, b) => b.close >= best.close ? b : best, bars[0]);
  const drawdown = Math.max(0, (1 - last.close / peak.close) * 100);
  const crossed = (price, high, t) => price <= high * (1 - t / 100) + high * 1e-12;
  const alerts = [];
  // Bootstrap only currently reached tiers. Subsequent updates replay new completed days.
  for (let i = previous?.asOf ? 1 : full.length - 1; i < full.length; i++) {
    const bar = full[i];
    if (previous?.asOf && bar.date <= previous.asOf) continue;
    const rollingHigh = index => {
      const cutoff = new Date(Date.parse(full[index].date) - 364 * DAY).toISOString().slice(0,10);
      return Math.max(...full.slice(0,index+1).filter(b => b.date >= cutoff).map(b => b.close));
    };
    const high = rollingHigh(i);
    const priorHigh = i > 0 ? rollingHigh(i-1) : high;
    for (const tier of THRESHOLDS) {
      if (crossed(bar.close, high, tier) && (!previous?.asOf || !crossed(full[i - 1].close, priorHigh, tier))) {
        alerts.push({ id: `${asset.symbol}:${bar.date}:${tier}`, symbol: asset.symbol, name: asset.name,
          tier, date: bar.date, close: bar.close, peak: high, currency: asset.currency,
          title: `${asset.symbol} 回撤达到 ${tier}%，关注买入`,
          notes: `收盘价 ${bar.close.toFixed(2)} ${asset.currency}；近52周最高收盘价 ${high.toFixed(2)}；行情日期 ${bar.date}；来源 ${asset.source}。` });
      }
    }
  }
  return { ...asset, price: last.close, asOf: last.date, peak: peak.close, peakDate: peak.date,
    drawdown, coverageStart: bars[0].date, coverageDays: bars.length, history: bars.map(b => ({ date: b.date, close: b.close })),
    levels: THRESHOLDS.map(tier => ({ tier, price: peak.close * (1 - tier / 100), reached: crossed(last.close, peak.close, tier) })),
    updatedAt: new Date(now).toISOString(), error: null, alerts };
}
export function parseYahoo(payload, now = Date.now()) {
  const result = payload?.chart?.result?.[0];
  if (!result || payload.chart.error || !['EQUITY', 'ETF'].includes(result.meta?.instrumentType) || result.meta?.currency !== 'USD') throw new Error('股票数据接口未返回有效 USD 股票或 ETF 行情');
  const todayNY = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year:'numeric',month:'2-digit',day:'2-digit' }).format(new Date(now));
  const hourNY = Number(new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',hour:'2-digit',hourCycle:'h23'}).format(new Date(now)));
  const quote = result.indicators?.quote?.[0]?.close;
  if (!Array.isArray(quote)) throw new Error('股票日线缺失');
  return (result.timestamp || []).flatMap((timestamp, i) => {
    const date = new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(timestamp * 1000));
    // Do not use an in-progress US session. Historical chart timestamps are session-open timestamps.
    if (date === todayNY && (hourNY < 17 || now / 1000 < (result.meta?.currentTradingPeriod?.regular?.end || 0))) return [];
    return [{ date, close: quote[i], end: timestamp * 1000 + 6.5 * 3600000 }];
  });
}
export function parseBinance(rows, now = Date.now()) {
  if (!Array.isArray(rows)) throw new Error('币安合约日线不可用');
  return rows.filter(r => Array.isArray(r) && Number(r[6]) < now).map(r => ({
    date: new Date(Number(r[0])).toISOString().slice(0, 10), close: Number(r[4]), end: Number(r[6]),
  }));
}
export async function fetchBars(asset, now = Date.now(), fetcher = fetch) {
  async function get(url) {
    const response = await fetcher(url, { headers: { 'User-Agent': 'DipWatch/1.0' }, signal: AbortSignal.timeout(15000) });
    if (!response.ok) throw new Error(`行情服务 HTTP ${response.status}`);
    return response.json();
  }
  if (asset.kind === '永续合约') {
    const info = await get('https://fapi.binance.com/fapi/v1/exchangeInfo');
    const contract = info.symbols?.find(s => s.symbol === asset.symbol);
    if (!contract || contract.status !== 'TRADING' || contract.contractType !== 'PERPETUAL') throw new Error('币安未返回有效的 ANTHROPICUSDT 永续合约');
    return parseBinance(await get(`https://fapi.binance.com/fapi/v1/klines?symbol=${asset.symbol}&interval=1d&limit=730`), now);
  }
  const data = await get(`https://query1.finance.yahoo.com/v8/finance/chart/${asset.symbol}?range=2y&interval=1d&events=splits`);
  if (data.chart?.result?.[0]?.meta?.symbol !== asset.symbol) throw new Error('股票代码映射不匹配');
  return parseYahoo(data, now);
}
export async function refreshState(previous = {}, now = Date.now(), loader = fetchBars) {
  const rows = await Promise.all(WATCHLIST.map(async asset => {
    const old = previous.assets?.find(a => a.symbol === asset.symbol);
    try { return computeSnapshot(asset, await loader(asset, now), old, now); }
    catch (error) { return { ...(old || asset), alerts: [], error: error instanceof Error ? error.message : '行情更新失败' }; }
  }));
  const alerts = new Map((previous.alerts || []).map(a => [a.id, a]));
  for (const row of rows) for (const alert of row.alerts) alerts.set(alert.id, alert);
  return { version: 1, attemptedAt: new Date(now).toISOString(), assets: rows.map(({alerts, ...row}) => row),
    alerts: [...alerts.values()].sort((a,b) => b.date.localeCompare(a.date) || a.id.localeCompare(b.id)),
    healthy: rows.filter(r => !r.error).length, expected: WATCHLIST.length };
}
