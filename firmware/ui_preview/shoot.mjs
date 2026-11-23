// screenshots of the firmware web UI mock (desktop + phone width): start mock_server.py 8020 SAFE and 8021 ARMED first
import {createRequire} from 'module';
const ROOT = new URL('../../', import.meta.url).pathname;
const puppeteer = createRequire(ROOT + 'tools/render/package.json')('puppeteer');
const out = ROOT + 'firmware/openfireworks_node_v2/';
const b = await puppeteer.launch({headless: 'new', args: ['--no-sandbox']});
for (const [port, st] of [[8020, 'safe'], [8021, 'armed']]) {
  for (const [w, tag] of [[1100, 'desktop'], [400, 'phone']]) {
    const p = await b.newPage(); await p.setViewport({width: w, height: 900, deviceScaleFactor: 1});
    await p.goto('http://127.0.0.1:' + port + '/', {waitUntil: 'networkidle0'});
    await new Promise(r => setTimeout(r, 800));
    await p.screenshot({path: out + 'ui_' + st + '_' + tag + '.png', fullPage: true}); await p.close();
  }
}
await b.close(); console.log('ok');
