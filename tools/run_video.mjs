// Usage: node run_video.mjs <video> <out.json> [port]
import { chromium } from 'playwright-core';
import fs from 'fs';
const [video, out, port = '8080'] = process.argv.slice(2);
const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args: ['--autoplay-policy=no-user-gesture-required'] });
const p = await b.newPage({ viewport: { width: 400, height: 860 } });
p.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') console.log('[page]', m.text().slice(0, 200)); });
p.on('pageerror', e => console.log('[pageerror]', e.message));
await p.goto(`http://127.0.0.1:${port}/?cpu=1`);
await p.click('#go-video');
await p.setInputFiles('#file', video);
const t0 = Date.now();
let last = 0;
while (true) {
  await new Promise(r => setTimeout(r, 5000));
  const st = await p.evaluate(() => ({ prog: window.__progress || 0, done: !!window.__summary }));
  if (Date.now() - last > 60000) { console.log(`${Math.round((Date.now() - t0) / 1000)}s ${(st.prog * 100).toFixed(1)}%`); last = Date.now(); }
  if (st.done) break;
}
const summary = await p.evaluate(() => window.__summary);
const text = await p.evaluate(() => window.__poseText());
fs.writeFileSync(out, text);
fs.writeFileSync(out.replace('.json', '.summary.json'), JSON.stringify(summary, null, 1));
await p.screenshot({ path: out.replace('.json', '.png'), fullPage: true });
console.log('done', summary.frames, 'frames', summary.took_s, 's', summary.speed_x, 'x', summary.body_pct, '% body');
await b.close();
