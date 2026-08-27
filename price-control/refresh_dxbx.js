const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const ROOT = __dirname;
const AUTH = process.env.DOCSINBOX_STORAGE_STATE || path.join(ROOT, 'dxbx-storage-state.json');
const OUT = process.argv[2] || path.join(ROOT, 'current.json');
const PRICE_FILE = path.join(ROOT, 'price_20260826.json');
const SUPPLIER = 'парадис экзотика';
const WEEK_KEY = '2026-08-26';
const START_ISO = '2026-08-26';
const END_ISO = '2026-09-01';
const START_RU = '26.08.2026';
const END_RU = '01.09.2026';

function round2(v) {
  if (!Number.isFinite(v)) return null;
  return Math.round((v + Number.EPSILON) * 100) / 100;
}
function norm(v) {
  return String(v ?? '')
    .replace(/\u00a0/g, ' ')
    .replace(/ё/g, 'е')
    .toLowerCase()
    .replace(/^[!/*+\s]+/, '')
    .replace(/\s+([,.;:])/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();
}
function coreName(displayName, unit) {
  let s = String(displayName ?? '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
  const eu = String(unit ?? '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  if (eu) {
    s = s.replace(new RegExp(',\\s*' + eu + '\\s*\\([^)]*\\)\\s*$', 'i'), '');
    s = s.replace(new RegExp(',\\s*' + eu + '\\s*$', 'i'), '');
  }
  return s.trim();
}
function ruToIso(s) {
  const m = String(s || '').match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
  return m ? `${m[3]}-${m[2]}-${m[1]}` : '';
}
function buildPriceMap(priceDoc) {
  const buckets = new Map();
  for (const r of priceDoc.rows || []) {
    const key = norm(r.name) + '\u0000' + norm(r.unit);
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(Number(r.price));
  }
  const map = new Map();
  for (const [key, vals] of buckets) {
    const uniq = [...new Set(vals.filter(Number.isFinite).map(v => round2(v)))];
    if (uniq.length === 1) map.set(key, uniq[0]);
    else map.set(key, null);
  }
  return map;
}

(async () => {
  if (!fs.existsSync(AUTH)) throw new Error('DOCSINBOX_AUTH_MISSING');
  let priceDoc = JSON.parse(fs.readFileSync(PRICE_FILE, 'utf8'));
  if (!Array.isArray(priceDoc.rows) || !priceDoc.rows.length) {
    const partFiles = [
      'price_bz2_part_01a.txt',
      'price_bz2_part_01b.txt',
      'price_bz2_part_02.txt',
      'price_bz2_part_03.txt'
    ];
    const encoded = partFiles.map(name => fs.readFileSync(path.join(ROOT, name), 'utf8').trim()).join('');
    const compressed = Buffer.from(encoded, 'base64');
    const raw = execFileSync('bzip2', ['-dc'], { input: compressed, maxBuffer: 10 * 1024 * 1024 });
    priceDoc = JSON.parse(raw.toString('utf8'));
  }
  if (!Array.isArray(priceDoc.rows) || !priceDoc.rows.length) throw new Error('PRICE_PAYLOAD_EMPTY');
  const priceMap = buildPriceMap(priceDoc);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ storageState: AUTH });
  const page = await context.newPage();
  await page.goto('https://dxbx.ru/fe/supplies?offset=0', { waitUntil: 'domcontentloaded', timeout: 60000 });

  const selected = await page.evaluate(async ({supplierNeedle, startIso, endIso}) => {
    const ruToIso = s => {
      const m = String(s || '').match(/^(\\d{2})\\.(\\d{2})\\.(\\d{4})$/);
      return m ? `${m[3]}-${m[2]}-${m[1]}` : '';
    };
    const all = [];
    let offset = 0;
    for (let pageNo = 0; pageNo < 50; pageNo++) {
      const r = await fetch('/api/front/supplies?offset=' + offset, { credentials: 'include' });
      if (!r.ok) throw new Error('supplies HTTP ' + r.status);
      const j = await r.json();
      const rows = j.data || [];
      all.push(...rows);
      if (!rows.length) break;
      const isos = rows.map(x => ruToIso(x.date)).filter(Boolean);
      if (isos.length && isos.every(x => x < startIso)) break;
      offset += rows.length;
      if (rows.length < 10) break;
    }

    return all
      .filter(s => {
        const iso = ruToIso(s.date);
        return iso >= startIso && iso <= endIso &&
          String(s.supplier?.name || '').toLowerCase().includes(supplierNeedle);
      })
      .map(s => ({
        date: s.date,
        number: s.number,
        invoices: s.invoices || []
      }));
  }, {supplierNeedle: SUPPLIER, startIso: START_ISO, endIso: END_ISO});

  console.log('Selected supplies:', JSON.stringify(selected.map(s => ({date:s.date, number:s.number, invoices:(s.invoices || []).length}))));
  const docs = [];
  const parseNum = v => {
    const z = Number(String(v ?? '').replace(/\\s/g, '').replace(',', '.').replace(/[^\\d.-]/g, ''));
    return Number.isFinite(z) ? z : null;
  };

  for (const supply of selected) {
    for (const inv of (supply.invoices || [])) {
      await page.goto(inv.link, { waitUntil: 'domcontentloaded', timeout: 60000 });
      await page.waitForFunction(() => {
        const heading = [...document.querySelectorAll('h1,h2,h3,h4')]
          .find(x => /Накладная №/i.test((x.textContent || '').replace(/\\s+/g, ' ')));
        const table = [...document.querySelectorAll('table')].find(t => {
          const h = [...t.querySelectorAll('th')].map(x => (x.textContent || '').replace(/\\s+/g, ' ').trim());
          return h.includes('Номер') && h.includes('Сумма') && h.includes('Кол.') &&
            h.some(x => /Номенклатура/i.test(x));
        });
        return Boolean(heading && table && [...table.querySelectorAll('tr')]
          .some(tr => tr.querySelectorAll(':scope > td').length >= 5));
      }, undefined, { timeout: 30000 });

      const detail = await page.evaluate(() => {
        const clean = v => String(v ?? '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();
        const num = v => {
          const z = Number(clean(v).replace(/\\s/g, '').replace(',', '.').replace(/[^\\d.-]/g, ''));
          return Number.isFinite(z) ? z : null;
        };
        const heading = [...document.querySelectorAll('h1,h2,h3,h4')]
          .find(x => /Накладная №/i.test(clean(x.textContent)));
        const table = [...document.querySelectorAll('table')].find(t => {
          const h = [...t.querySelectorAll('th')].map(x => clean(x.textContent));
          return h.includes('Номер') && h.includes('Сумма') && h.includes('Кол.') &&
            h.some(x => /Номенклатура/i.test(x));
        });
        if (!table) return { title: clean(heading?.textContent), items: [] };

        const items = [];
        for (const tr of table.querySelectorAll('tr')) {
          const td = [...tr.querySelectorAll(':scope > td')];
          if (td.length < 5) continue;
          const line = num(td[0]?.textContent);
          const sum = num(td[1]?.textContent);
          const count = num(td[2]?.textContent);
          const unit = clean(td[3]?.textContent);
          const name = clean(td[4]?.textContent);
          if (line === null || sum === null || count === null || !unit || !name) continue;
          items.push({ line, name, count, unit, sum });
        }
        return { title: clean(heading?.textContent), items };
      });

      if (!detail.items.length) {
        throw new Error(`INVOICE_ROWS_NOT_FOUND:${inv.number || supply.number}:${inv.publicId || ''}`);
      }
      const vm = detail.title.match(/\\(вер\\.(\\d+)\\)/i);
      docs.push({
        date: supply.date,
        number: inv.number || supply.number,
        publicId: inv.publicId,
        version: vm ? vm[1] : null,
        title: detail.title,
        items: detail.items
      });
      console.log('Invoice rows OK:', inv.number || supply.number, detail.items.length);
    }
  }

  await browser.close();

  const numberCounts = new Map();
  for (const d of docs) numberCounts.set(d.number, (numberCounts.get(d.number) || 0) + 1);
  const rowsData = [];

  for (const d of docs.sort((a,b) => ruToIso(b.date).localeCompare(ruToIso(a.date)))) {
    const count = numberCounts.get(d.number) || 1;
    let invoiceLabel = d.number;
    if (count > 1) {
      if (d.version) invoiceLabel += ` (вер.${d.version})`;
      else invoiceLabel += ` · ${String(d.publicId || '').slice(0,8)}`;
    }
    for (const it of (d.items || []).sort((a,b) => (a.line || 0) - (b.line || 0))) {
      const qty = Number(it.count);
      const fact = qty && Number.isFinite(Number(it.sum)) ? round2(Number(it.sum) / qty) : null;
      const core = coreName(it.name, it.unit);
      const key = norm(core) + '\u0000' + norm(it.unit);
      const price = priceMap.has(key) ? priceMap.get(key) : undefined;
      let status = 'UNMATCHED', delta = null, impact = 0;
      if (price !== undefined && price !== null && fact !== null) {
        delta = round2(fact - price);
        impact = round2(delta * qty);
        if (delta > 0) status = 'ABOVE';
        else if (delta < 0) status = 'BELOW';
        else status = 'EQUAL';
      }
      rowsData.push([
        it.name || core, d.date, invoiceLabel, qty, it.unit,
        price === undefined || price === null ? null : price,
        fact, delta, status === 'UNMATCHED' ? 0 : impact, status
      ]);
    }
  }

  const above = rowsData.filter(r => r[9] === 'ABOVE').length;
  const below = rowsData.filter(r => r[9] === 'BELOW').length;
  const equal = rowsData.filter(r => r[9] === 'EQUAL').length;
  const unmatched = rowsData.filter(r => r[9] === 'UNMATCHED').length;
  const overpay = round2(rowsData.filter(r => r[9] === 'ABOVE').reduce((s,r) => s + Number(r[8] || 0), 0));
  if (docs.length && rowsData.length === 0) throw new Error('NO_INVOICE_ROWS');

  const payload = {
    generatedAt: new Date().toISOString(),
    week: {
      key: WEEK_KEY,
      label: 'Прайс 26.08 → 01.09',
      supplier: 'Парадис Экзотика',
      start: START_RU,
      end: END_RU,
      docs: docs.length,
      rows: rowsData.length,
      above, below, equal, unmatched, overpay,
      priceDocumentDate: '26.08.2026',
      indexGroup: 'paradis',
      rowsData
    }
  };
  fs.writeFileSync(OUT, JSON.stringify(payload, null, 2), 'utf8');
  console.log(JSON.stringify({docs:docs.length,rows:rowsData.length,above,below,equal,unmatched,overpay,generatedAt:payload.generatedAt}));
})().catch(err => {
  console.error(err && (err.stack || err.message) || err);
  process.exit(1);
});
