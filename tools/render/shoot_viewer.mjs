// README screenshots of the enclosure + board 3D viewer (enclosure/viewer) with the case opened.
// Start a server first:  (cd enclosure/viewer && python3 -m http.server 8031)
// Run:   ZOOM_OUT=5 DRAG_Y=-120 DRAG_X=-60 node tools/render/shoot_viewer.mjs   (the README shot)
// Out:                   enclosure/renders/viewer_open.jpg
import {createRequire} from 'module';
const ROOT = new URL('../../', import.meta.url).pathname;
const puppeteer = createRequire(ROOT + 'tools/render/package.json')('puppeteer');
const out = ROOT + 'enclosure/renders/';
const url = 'http://127.0.0.1:8031/';
const b = await puppeteer.launch({headless: 'new', args: ['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']});
const p = await b.newPage();
await p.setViewport({width: 1600, height: 900, deviceScaleFactor: 1});
p.on('pageerror', e => console.error('pageerror', e.message));
await p.goto(url, {waitUntil: 'networkidle0', timeout: 180000});
await new Promise(r => setTimeout(r, 3000));
const set = (id, v) => p.evaluate((id, v) => { const e = document.getElementById(id); e.value = v;
  e.dispatchEvent(new Event('input', {bubbles: true})); }, id, v);
await p.evaluate(() => { const r = document.getElementById('bRot'); if (r.classList.contains('on')) r.click(); });
await p.mouse.move(930, 470);
for (let i = 0; i < +(process.env.ZOOM_OUT || 8); i++) { await p.mouse.wheel({deltaY: 240}); await new Promise(r => setTimeout(r, 120)); }
// orbit to a lower three-quarter view: left-drag on the model
const dy = +(process.env.DRAG_Y || -140), dx = +(process.env.DRAG_X || 0);
await p.mouse.move(930, 470); await p.mouse.down();
for (let i = 1; i <= 10; i++) { await p.mouse.move(930 + dx * i / 10, 470 + dy * i / 10); await new Promise(r => setTimeout(r, 40)); }
await p.mouse.up();
await set('lid', 120); await set('open', 100);
await new Promise(r => setTimeout(r, 2500));
await p.screenshot({path: out + 'viewer_open.jpg', type: 'jpeg', quality: 88});
await b.close();
console.log('ok');
