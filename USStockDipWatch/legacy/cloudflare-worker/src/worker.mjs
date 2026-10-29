import { WATCHLIST, refreshState } from './core.mjs';
import HTML from './page.mjs';
const KEY = 'dip-watch/state-v1.json';
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'X-Content-Type-Options':'nosniff' } });
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    // Owner-private Sites dispatch authenticates both browser requests and service callers.
    // Never expose this Worker directly on a public domain without adding authorization.
    try {
      if (url.pathname === '/' && request.method === 'GET') return new Response(HTML, { headers: { 'Content-Type':'text/html; charset=utf-8', 'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff', 'Referrer-Policy':'same-origin' } });
      if (!env.BUCKET) return json({ error: '持久化存储未配置' }, 503);
      if (url.pathname === '/api/data' && request.method === 'GET') {
        const obj = await env.BUCKET.get(KEY);
        return json(obj ? await obj.json() : { assets: WATCHLIST, alerts: [], healthy:0, expected:5 });
      }
      if (url.pathname === '/api/reminders' && request.method === 'GET') {
        const obj = await env.BUCKET.get(KEY);
        const state = obj ? await obj.json() : {};
        return json({ attemptedAt:state.attemptedAt || null, reminders: (state.alerts || []).map(a => ({...a, notes: `${a.notes}\nDipWatch-ID: ${a.id}\n${url.origin}/`})) });
      }
      if (url.pathname === '/api/refresh' && request.method === 'POST') {
        // Restrict browser cross-origin writes in addition to platform authentication.
        if (request.headers.get('Origin') && request.headers.get('Origin') !== url.origin) return json({error:'来源不匹配'},403);
        const old = await env.BUCKET.get(KEY);
        const previous = old ? await old.json() : {};
        const state = await refreshState(previous);
        const saved = await env.BUCKET.put(KEY, JSON.stringify(state), {
          onlyIf: old ? { etagMatches: old.etag } : { etagDoesNotMatch:'*' },
          httpMetadata: { contentType:'application/json' },
        });
        if (!saved) return json({error:'其他更新正在进行，请重新读取状态后重试'},409);
        return json({ attemptedAt:state.attemptedAt, healthy:state.healthy, expected:state.expected, alerts:state.alerts.length,
          errors:state.assets.filter(a=>a.error).map(a=>({symbol:a.symbol,error:a.error})) }, state.healthy===5?200:207);
      }
      return json({error:'接口不存在或请求方法不支持'},404);
    } catch { return json({error:'存储或更新服务暂不可用；已保存的数据不会被清空'},503); }
  }
};
