import { createServer } from 'node:http';
import { readFile, writeFile } from 'node:fs/promises';
import worker from '../dist/server/index.js';
const statePath=new URL('../.local-state.json',import.meta.url);
const bucket={async get(){try{const text=await readFile(statePath,'utf8');return {etag:'local',async json(){return JSON.parse(text)}}}catch{return null}},async put(key,text){await writeFile(statePath,text);return {etag:'local'}}};
createServer(async(req,res)=>{try{const request=new Request('http://127.0.0.1:4173'+req.url,{method:req.method,headers:req.headers});const response=await worker.fetch(request,{BUCKET:bucket});res.writeHead(response.status,Object.fromEntries(response.headers));res.end(Buffer.from(await response.arrayBuffer()));}catch{res.writeHead(500);res.end('Local server error')}}).listen(4173,'127.0.0.1',()=>console.log('Local: http://127.0.0.1:4173'));
