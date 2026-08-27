const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const AUTH = process.env.DOCSINBOX_STORAGE_STATE || path.join(__dirname,'dxbx-storage-state.json');
const OUT = process.argv[2] || path.join(__dirname,'history','interfood_20260520_raw.json');
const SUPPLIER = 'интерфуд';
const START_ISO = '2026-05-20';
const END_ISO = '2026-05-26';

function ruToIso(s){
  const m=String(s||'').match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
  return m ? `${m[3]}-${m[2]}-${m[1]}` : '';
}
(async()=>{
  if(!fs.existsSync(AUTH)) throw new Error('DOCSINBOX_AUTH_MISSING');
  const browser=await chromium.launch({headless:true});
  const context=await browser.newContext({storageState:AUTH});
  const page=await context.newPage();
  await page.goto('https://dxbx.ru/fe/supplies?offset=0',{waitUntil:'domcontentloaded',timeout:60000});

  const selected=await page.evaluate(async ({supplierNeedle,startIso,endIso})=>{
    const ruToIso=s=>{const m=String(s||'').match(/^(\d{2})\.(\d{2})\.(\d{4})$/);return m?`${m[3]}-${m[2]}-${m[1]}`:''};
    const all=[]; let offset=0;
    for(let n=0;n<100;n++){
      const r=await fetch('/api/front/supplies?offset='+offset,{credentials:'include'});
      if(!r.ok) throw new Error('supplies HTTP '+r.status);
      const j=await r.json(), rows=j.data||[];
      all.push(...rows);
      if(!rows.length) break;
      const isos=rows.map(x=>ruToIso(x.date)).filter(Boolean);
      if(isos.length && isos.every(x=>x<startIso)) break;
      offset+=rows.length;
      if(rows.length<10) break;
    }
    return all.filter(s=>{
      const iso=ruToIso(s.date);
      return iso>=startIso && iso<=endIso && String(s.supplier?.name||'').toLowerCase().includes(supplierNeedle);
    }).map(s=>({
      date:s.date, number:s.number, supplier:s.supplier?.name||'',
      invoices:(s.invoices||[]).map(i=>({number:i.number,publicId:i.publicId,link:i.link,products:i.products||[],itemsCount:i.itemsCount,sum:i.sum,createDate:i.createDate}))
    }));
  },{supplierNeedle:SUPPLIER,startIso:START_ISO,endIso:END_ISO});

  const docs=[];
  for(const supply of selected){
    for(const inv of (supply.invoices||[])){
      await page.goto(inv.link,{waitUntil:'domcontentloaded',timeout:60000});
      await page.waitForFunction(()=>{
        const table=[...document.querySelectorAll('table')].find(t=>{
          const h=[...t.querySelectorAll('th')].map(x=>(x.textContent||'').replace(/\s+/g,' ').trim());
          return h.includes('Номер') && h.includes('Сумма') && h.includes('Кол.') && h.some(x=>/Номенклатура/i.test(x));
        });
        return Boolean(table && [...table.querySelectorAll('tr')].some(tr=>tr.querySelectorAll(':scope > td').length>=5));
      },undefined,{timeout:30000});
      const detail=await page.evaluate(()=>{
        const clean=v=>String(v??'').replace(/\u00a0/g,' ').replace(/\s+/g,' ').trim();
        const num=v=>{const z=Number(clean(v).replace(/\s/g,'').replace(',','.').replace(/[^\d.-]/g,''));return Number.isFinite(z)?z:null};
        const heading=[...document.querySelectorAll('h1,h2,h3,h4')].find(x=>/Накладная №/i.test(clean(x.textContent)));
        const table=[...document.querySelectorAll('table')].find(t=>{
          const h=[...t.querySelectorAll('th')].map(x=>clean(x.textContent));
          return h.includes('Номер') && h.includes('Сумма') && h.includes('Кол.') && h.some(x=>/Номенклатура/i.test(x));
        });
        const items=[];
        if(table) for(const tr of table.querySelectorAll('tr')){
          const td=[...tr.querySelectorAll(':scope > td')];
          if(td.length<5) continue;
          const line=num(td[0]?.textContent), sum=num(td[1]?.textContent), count=num(td[2]?.textContent), unit=clean(td[3]?.textContent), name=clean(td[4]?.textContent);
          if(line===null||sum===null||count===null||!unit||!name) continue;
          items.push({line,name,count,unit,sum});
        }
        return {title:clean(heading?.textContent),items};
      });
      if(!detail.items.length) throw new Error('INVOICE_ROWS_NOT_FOUND:'+inv.number+':'+inv.publicId);
      docs.push({date:supply.date,number:inv.number||supply.number,publicId:inv.publicId,products:inv.products,sourceItemsCount:inv.itemsCount,sourceSum:inv.sum,title:detail.title,items:detail.items});
      console.log('Recovered',inv.number,detail.items.length);
    }
  }
  await browser.close();
  fs.mkdirSync(path.dirname(OUT),{recursive:true});
  const payload={supplier:'ООО "ИНТЕРФУД"',start:'20.05.2026',end:'26.05.2026',docs};
  fs.writeFileSync(OUT,JSON.stringify(payload,null,2),'utf8');
  console.log('RECOVERY_SUMMARY',JSON.stringify({docs:docs.length,rows:docs.reduce((s,d)=>s+d.items.length,0),numbers:docs.map(d=>d.number)}));
})().catch(e=>{console.error(e&&e.stack||e);process.exit(1)});