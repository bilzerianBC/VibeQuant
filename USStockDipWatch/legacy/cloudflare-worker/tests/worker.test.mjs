import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../dist/server/index.js';
const req=(path,options)=>new Request('https://example.test'+path,options);
test('HTML and first-run data load without invented prices',async()=>{
 const html=await worker.fetch(req('/'),{});assert.equal(html.status,200);assert.match(await html.text(),/回撤观察/);
 const r=await worker.fetch(req('/api/data'),{BUCKET:{get:async()=>null}});const state=await r.json();assert.equal(state.assets.length,5);assert.equal(state.assets[0].price,undefined);assert.equal(state.alerts.length,0);
});
test('reminder feed preserves stable IDs and provides idempotency marker',async()=>{
 const alert={id:'QQQ:2026-10-08:20',notes:'price',title:'QQQ',date:'2026-10-08'};
 const r=await worker.fetch(req('/api/reminders'),{BUCKET:{get:async()=>({json:async()=>({alerts:[alert]})})}});
 const feed=await r.json();assert.equal(feed.reminders[0].id,alert.id);assert.match(feed.reminders[0].notes,/DipWatch-ID: QQQ:2026-10-08:20/);
});
test('missing binding, wrong method, and cross-origin writes fail',async()=>{
 assert.equal((await worker.fetch(req('/api/data'),{})).status,503);
 assert.equal((await worker.fetch(req('/api/refresh'),{BUCKET:{}})).status,404);
 assert.equal((await worker.fetch(req('/api/refresh',{method:'POST',headers:{Origin:'https://other.test'}}),{BUCKET:{}})).status,403);
});
test('provider rejection is persisted with 207; conflicting conditional write cannot replace state',async()=>{
 const original=globalThis.fetch;globalThis.fetch=async()=>new Response('{}',{status:451});
 try {
  let saved,options;
  const bucket={get:async()=>null,put:async(key,value,opts)=>{saved=JSON.parse(value);options=opts;return {etag:'ok'}}};
  const response=await worker.fetch(req('/api/refresh',{method:'POST'}),{BUCKET:bucket});
  assert.equal(response.status,207);assert.equal(saved.healthy,0);assert.equal(saved.alerts.length,0);assert.deepEqual(options.onlyIf,{etagDoesNotMatch:'*'});
  bucket.get=async()=>({etag:'previous',json:async()=>({assets:[],alerts:[]})});bucket.put=async()=>null;
  assert.equal((await worker.fetch(req('/api/refresh',{method:'POST'}),{BUCKET:bucket})).status,409);
 } finally {globalThis.fetch=original;}
});
