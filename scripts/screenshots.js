// Phone-size (390x844) screenshots of every Haq screen in both languages, against the stub server.
//
//   .venv/bin/python scripts/ui_stub_server.py &          # no model or web calls
//   npm install --prefix /tmp/haq-shots puppeteer-core@23.11.1
//   NODE_PATH=/tmp/haq-shots/node_modules node scripts/screenshots.js [outDir]
//
// Uses the locally installed Google Chrome (CHROME env var to override).
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const BASE = process.env.BASE || 'http://127.0.0.1:8001';
const OUT = process.argv[2] || 'docs/screenshots';
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-first-run'] });
  const report = { errors: [], checks: [] };

  async function newPage() {
    const page = await browser.newPage();
    await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
    page.on('pageerror', e => report.errors.push('pageerror: ' + e.message));
    page.on('console', m => { if (m.type() === 'error') report.errors.push('console: ' + m.text()); });
    return page;
  }
  // Layout checks run on every screenshot: horizontal overflow, tap targets < 44px, text clipped.
  async function check(page, name) {
    const r = await page.evaluate(() => {
      const vis = (el) => el.offsetParent !== null && getComputedStyle(el).visibility !== 'hidden';
      const small = [...document.querySelectorAll('button, a')].filter(vis).filter(el => {
        const b = el.getBoundingClientRect(); return b.width < 44 || b.height < 44;
      }).map(el => (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 30) + ` (${Math.round(el.getBoundingClientRect().width)}x${Math.round(el.getBoundingClientRect().height)})`);
      const clipped = [...document.querySelectorAll('.screen.on *')].filter(vis).filter(el =>
        el.children.length === 0 && (el.scrollWidth > el.clientWidth + 1) && getComputedStyle(el).overflow !== 'visible')
        .map(el => el.textContent.trim().slice(0, 30));
      const offscreen = [...document.querySelectorAll('.screen.on button')].filter(vis).filter(el => {
        const b = el.getBoundingClientRect(); return b.right > window.innerWidth + 1 || b.left < -1;
      }).map(el => el.textContent.trim().slice(0, 30));
      return { overflowX: document.documentElement.scrollWidth > window.innerWidth, small, clipped, offscreen };
    });
    report.checks.push({ name, ...r });
  }
  async function shot(page, name, full = true) {
    await sleep(450);
    await check(page, name);
    await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: full });
  }
  const clickBtn = (page, text, scope = '.screen.on') => page.evaluate((t, s) => {
    const b = [...document.querySelectorAll(`${s} button`)].find(b => b.offsetParent && b.textContent.includes(t));
    if (!b) throw new Error('button not found: ' + t); b.click();
  }, text, scope);
  const tapTag = (page, i, text) => page.evaluate((i, t) => {
    const card = document.querySelectorAll('#members .member')[i];
    [...card.querySelectorAll('button')].find(b => b.textContent.includes(t)).click();
  }, i, text);

  // ---- language choice (shown once, before any language is set)
  {
    const page = await newPage();
    await page.goto(BASE, { waitUntil: 'networkidle0' });
    await page.evaluate(() => { try { localStorage.clear(); } catch {} });
    await page.reload({ waitUntil: 'networkidle0' });
    await shot(page, '01-language', false);
    await page.close();
  }

  const L = {
    hi: { roles: ['दादी', 'पापा', 'बेटी'], tags: ['विधवा', 'किसान', 'पढ़ाई'], income: 'कम' },
    en: { roles: ['Grandmother', 'Father', 'Daughter'], tags: ['Widow', 'Farmer', 'Student'], income: 'Low' },
  };
  for (const lang of ['hi', 'en']) {
    await fetch(`${BASE}/stub/reset`, { method: 'POST' });
    const page = await newPage();
    await page.goto(BASE, { waitUntil: 'networkidle0' });
    await page.evaluate(() => { try { localStorage.clear(); } catch {} });
    await page.reload({ waitUntil: 'networkidle0' });
    await page.click(`[data-pick="${lang}"]`);
    await shot(page, `${lang}-02-start`, false);

    await page.click('#toBuilder');
    for (const r of L[lang].roles) await clickBtn(page, r, '#roleChips');
    for (let i = 0; i < 3; i++) await tapTag(page, i, L[lang].tags[i]);
    await shot(page, `${lang}-03-builder`, false);                       // what the phone shows (Continue pinned)
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await shot(page, `${lang}-03b-builder-scrolled`, false);

    await page.click('#builderGo');
    await page.waitForSelector('#s-follow.on');
    await shot(page, `${lang}-04-followup`, false);
    await page.evaluate(() => document.querySelectorAll('#qOptions .option')[0].click());
    await sleep(250);
    const more = await page.evaluate(() => document.querySelector('#s-follow.on') !== null);
    if (more) await page.evaluate(() => document.querySelectorAll('#qOptions .option')[1].click());

    await page.waitForSelector('#s-work.on');
    await page.waitForFunction(() => document.querySelectorAll('#steps .step').length >= 7, { timeout: 15000 });
    await shot(page, `${lang}-05-working`);

    await fetch(`${BASE}/stub/release`, { method: 'POST' });
    await page.waitForSelector('#s-results.on', { timeout: 20000 });
    await shot(page, `${lang}-06-results`);
    await page.evaluate(() => document.querySelector('.scheme .apply').click());
    await shot(page, `${lang}-07-results-where-to-apply`, false);
    await page.close();
  }
  fs.writeFileSync(`${OUT}/layout-report.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 1));
  await browser.close();
})().catch(e => { console.error('FAILED', e.stack || e.message); process.exit(1); });
