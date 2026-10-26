// Record the frames of Fiber Checker's How-to GIFs and stills from a running copy of the page.
//
//   node tools/record_howto.js URL OUT_DIR A.json B.json
//
// URL is the page (http://127.0.0.1:7860/ for `python3 app.py`), A.json and B.json two fiber.json records for the
// Compare guide. Writes OUT_DIR/<flow>-NN.png and OUT_DIR/frames.json ({flow: [[file, ms], ...]}) for
// `python3 tools/build_media.py --frames OUT_DIR`, plus shot-check.png, shot-result.png and shot-upload.png.
// Uses the PHerc0139 w030 example only (a public scroll on no prize list). Needs Node's playwright with Chromium.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const [url, out, aJson, bJson] = process.argv.slice(2);
const frames = {};
let page;

async function frame(flow, ms) {
  const list = (frames[flow] = frames[flow] || []);
  const file = `${flow}-${String(list.length).padStart(2, '0')}.png`;
  await page.screenshot({ path: path.join(out, file) });
  list.push([file, ms]);
}

async function open(tab) {
  await page.goto(url + (tab ? `?tab=${tab}` : ''), { waitUntil: 'load' });
  await page.waitForSelector('.fc-head', { timeout: 60000 });
  await page.waitForTimeout(2500);
}

(async () => {
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch();
  page = await browser.newPage({ viewport: { width: 1280, height: 860 } });

  // 1. your first check: pick the PHerc0139 example, press Check fibers, watch it finish
  await open('check');
  await page.getByLabel('Example (public scrolls on no prize list)').click();
  await page.getByRole('option', { name: /PHerc0139/ }).click();
  await page.waitForTimeout(1500);
  await frame('check', 1600);
  await page.getByRole('button', { name: 'Check fibers' }).click();
  const t0 = Date.now();
  while (!(await page.locator('.fc-verdict').count())) {
    if (Date.now() - t0 > 15 * 60000) throw new Error('the check did not finish in 15 minutes');
    await page.waitForTimeout(4000);
    await frame('check', 450);
  }
  await page.waitForTimeout(2500);
  await frame('check', 1800);
  await page.locator('.fc-verdict').scrollIntoViewIfNeeded();
  await page.mouse.wheel(0, 260);
  await page.waitForTimeout(800);
  await frame('check', 4000);
  await page.screenshot({ path: path.join(out, 'shot-result.png') });
  await page.mouse.wheel(0, -2000);
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(out, 'shot-check.png') });

  // 2. Fiber or not?: two rounds
  await open('game');
  await page.waitForSelector('.fc-game img', { timeout: 30000 });
  await page.waitForTimeout(1200);
  await frame('game', 2200);
  await page.getByRole('button', { name: 'A has fibers' }).click();
  await page.waitForTimeout(1200);
  await frame('game', 3200);
  await page.getByRole('button', { name: 'New pair' }).click();
  await page.waitForTimeout(1800);
  await frame('game', 2200);
  await page.getByRole('button', { name: 'B has fibers' }).click();
  await page.waitForTimeout(1200);
  await frame('game', 3600);

  // 3. Compare: two fiber.json files side by side
  await open('compare');
  await frame('compare', 1800);
  const inputs = page.locator('.fc-drop input[type=file]');
  await inputs.nth(0).setInputFiles(aJson);
  await page.waitForTimeout(1200);
  await inputs.nth(1).setInputFiles(bJson);
  await page.waitForTimeout(1200);
  await frame('compare', 1600);
  await page.getByRole('button', { name: 'Compare', exact: true }).click();
  await page.waitForSelector('.fc-cmp', { timeout: 30000 });
  await page.waitForTimeout(800);
  await frame('compare', 4500);

  // the upload box, for "Check your own trace"
  await open('check');
  await page.getByRole('tab', { name: 'Your own mesh' }).click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(out, 'shot-upload.png'), clip: { x: 0, y: 0, width: 1280, height: 860 } });

  fs.writeFileSync(path.join(out, 'frames.json'), JSON.stringify(frames, null, 1));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
