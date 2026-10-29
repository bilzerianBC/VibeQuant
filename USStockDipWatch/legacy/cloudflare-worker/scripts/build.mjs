import { readFile, mkdir, writeFile } from 'node:fs/promises';
const core = (await readFile('src/core.mjs','utf8')).replace(/^export /gm,'');
const html = await readFile('../../web/index.html','utf8');
const worker = (await readFile('src/worker.mjs','utf8')).replace(/^import .*;\n/gm,'');
await mkdir('dist/server', {recursive:true});
await writeFile('src/page.mjs', `export default ${JSON.stringify(html)};\n`);
await writeFile('dist/server/index.js', `${core}\nconst HTML = ${JSON.stringify(html)};\n${worker}`);
console.log('Built dependency-free Cloudflare Worker: dist/server/index.js');
