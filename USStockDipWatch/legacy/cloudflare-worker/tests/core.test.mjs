import test from 'node:test';
import assert from 'node:assert/strict';
import { computeSnapshot, parseYahoo, parseBinance, refreshState, WATCHLIST } from '../src/core.mjs';
const now=Date.UTC(2026,9,9,2), day=86400000;
const asset={...WATCHLIST[0],minBars:2};
const bars=(prices)=>prices.map((close,i)=>({date:new Date(now-(prices.length-i)*day).toISOString().slice(0,10),close,end:now-(prices.length-i)*day+3600000}));
test('exact threshold boundaries and gap through six tiers',()=>{
 const s=computeSnapshot(asset,bars([100,90]),null,now);assert.equal(s.levels[0].reached,true);assert.equal(s.alerts.length,1);
 const gap=computeSnapshot(asset,bars([100,39]),null,now);assert.equal(gap.alerts.length,6);
});
test('refresh is idempotent; rebound and recross produce a new dated event',()=>{
 const first=computeSnapshot(asset,bars([100,90]),null,now);
 assert.equal(computeSnapshot(asset,bars([100,90]),first,now).alerts.length,0);
 const prior=computeSnapshot(asset,bars([100,90,95]).map((b,i)=>({...b,date:new Date(now-(4-i)*day).toISOString().slice(0,10),end:now-(4-i)*day})),null,now);
 const next=computeSnapshot(asset,bars([100,90,95,89]),prior,now);assert.equal(next.alerts.length,1);
});
test('invalid and stale data cannot generate buy alerts',()=>{
 assert.throws(()=>computeSnapshot(asset,bars([100,NaN]),null,now),/不足/);
 assert.throws(()=>computeSnapshot(asset,bars([100,50]).map(b=>({...b,end:b.end-10*day})),null,now),/过期/);
});
test('Binance rejects still-open day and error payload',()=>{
 const rows=[[now-day,'','','','100','',now-1],[now,'','','','50','',now+day]];
 assert.equal(parseBinance(rows,now).length,1);assert.throws(()=>parseBinance({code:-1121},now));
});
test('Yahoo refuses wrong instrument and USD mapping; unfinished session excluded',()=>{
 assert.throws(()=>parseYahoo({chart:{result:[{meta:{instrumentType:'CRYPTOCURRENCY'}}]}},now));
 const n=Date.UTC(2026,9,8,18);const payload={chart:{result:[{meta:{instrumentType:'EQUITY',currency:'USD'},timestamp:[Date.UTC(2026,9,7,13,30)/1000,Date.UTC(2026,9,8,13,30)/1000],indicators:{quote:[{close:[100,50]}]}}]}};
 assert.equal(parseYahoo(payload,n).length,1);
});
test('partial provider outage preserves last valid data, reports errors, emits no alerts',async()=>{
 const initial={assets:[{...asset,price:90,asOf:'2026-10-08'}],alerts:[{id:'kept',date:'2026-10-08'}]};
 const s=await refreshState(initial,now,async()=>{throw Error('HTTP 451')});
 assert.equal(s.healthy,0);assert.equal(s.assets[0].price,90);assert.equal(s.alerts.length,1);assert.match(s.assets[0].error,/451/);
});
