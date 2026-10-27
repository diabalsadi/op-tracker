// Optional browser verification: npm install --no-save playwright
// PLAYWRIGHT_MODULE and CHROMIUM_PATH can select an existing runtime/browser.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const folder=fs.mkdtempSync(path.join(os.tmpdir(),'op-tracker-browser-'));
const port=Number(process.env.TEST_PORT||8932),origin=`http://127.0.0.1:${port}`;
const server=spawn(process.env.PYTHON||'python',['server.py','--port',String(port),'--db',path.join(folder,'tracker.sqlite3')]);
server.stderr.on('data',()=>{});
await new Promise((resolve,reject)=>{server.stdout.once('data',resolve);server.once('error',reject);server.once('exit',code=>reject(Error('Server exited '+code)));});
let browser;
const post=async(route,data)=>{const response=await fetch(origin+'/api/'+route,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const value=await response.json();if(!response.ok)throw Error(JSON.stringify(value));return value;};
try {
  const team=await post('save/teams',{name:'Alpha'});
  await post('save/members',{name:'Test Developer',jira_id:'dev-a',role:'Dev',country:'JO',team_id:team.id,effective_at:'2026-07-01T00:00:00Z'});
  await post('save/members',{name:'Test TPM',jira_id:'tpm-a',role:'TPM',country:'DO',team_id:team.id,effective_at:'2026-07-01T00:00:00Z'});
  for(const [file,day] of [['day-1',19],['day-2',20]])await post('import/commit',{csv:fs.readFileSync('examples/'+file+'.csv','utf8'),filename:file+'.csv',snapshot_at:`2026-10-${day}T12:00:00Z`});
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{}),args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu']});
  const page=await browser.newPage({viewport:{width:1280,height:960}}),errors=[];
  page.on('pageerror',e=>{errors.push(e.message);console.error('Page error:',e.message);});page.on('response',async r=>{if(r.status()>=400)console.error('HTTP',r.status(),r.url(),await r.text());});
  async function scan(label){
    for(const width of [1280,1024,736,540,360,320]){
      await page.setViewportSize({width,height:960});await page.waitForTimeout(25);
      const issues=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth+1,wide:[...document.querySelectorAll('body *')].filter(e=>{const r=e.getBoundingClientRect();return r.width&&r.right>innerWidth+1&&!e.closest('.table-wrap');}).slice(0,8).map(e=>({tag:e.tagName,cls:e.className,w:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right})),black:[...document.querySelectorAll('h1,h2,h3,strong,label,td,th,p,span,button,input,select')].filter(e=>e.getBoundingClientRect().width&&getComputedStyle(e).color==='rgb(0, 0, 0)').map(e=>e.tagName)}));
      if(issues.overflow||issues.black.length)throw Error(label+' at '+width+': '+JSON.stringify(issues));
    }
    await page.setViewportSize({width:1280,height:960});
  }
  await page.goto(origin);await page.locator('#delivery-chart').waitFor();
  for(const name of ['Overview','Delivery','Utilization','Performance','Rankings','Members','Tickets','Imports','Administration']){
    await page.locator(`nav button[data-page="${name}"]`).click();await page.waitForFunction(n=>document.querySelector('#title').textContent===n,name);
    if(name==='Rankings')for(const scope of ['Team','Role','Individual']){await page.locator('#ranking-scope').selectOption(scope);await page.waitForFunction(s=>document.querySelector('#ranking-scope')?.value===s&&document.querySelector('#content h2')?.textContent===s+' ranking',scope);}
    await scan(name);
  }
  for(const tab of ['Members','Teams','Workflow rules','Workflow','Sprints','Calendars','Targets','Monthly records','Backup & restore']){
    await page.locator(`[data-tab="${tab}"]`).click();await page.locator(`[data-tab="${tab}"][aria-pressed=true]`).waitFor();
    await scan('Administration: '+tab);
  }
  await page.locator('[data-tab="Members"]').click();
  await page.locator('#member-form input[name=name]').fill('Created In Browser');
  await page.locator('#member-form input[name=jira_id]').fill('browser-user');
  await page.locator('#member-form button.primary').click();await page.getByText('Saved to your local database.',{exact:true}).waitFor();
  await page.locator('[data-tab="Workflow rules"]').click();
  await page.locator('#rule-form input[name=effective_at]').fill('2026-10-01T09:00');
  await page.locator('#rule-form button.primary').click();await page.getByText('Saved to your local database.',{exact:true}).waitFor();
  await page.locator('[data-tab="Sprints"]').click();
  await page.locator('#sprint-form input[name=name]').fill('Browser Sprint');
  await page.locator('#sprint-form button.primary').click();await page.getByText('Saved to your local database.',{exact:true}).waitFor();
  await page.locator('[data-tab="Calendars"]').click();
  await page.locator('#holiday-form input[name=day]').fill('2026-09-20');
  await page.locator('#holiday-form input[name=name]').fill('Browser holiday');
  await page.locator('#holiday-form button.primary').click();await page.getByText('Saved to your local database.',{exact:true}).waitFor();
  await page.locator('[data-tab="Workflow"]').click();
  await page.locator('#workflow-form input[name=name]').fill('Awaiting Release');
  await page.locator('#workflow-form button.primary').click();await page.getByText('Saved to your local database.',{exact:true}).waitFor();
  await page.locator('nav button[data-page="Overview"]').click();await page.locator('#start-date').waitFor();
  await page.locator('#start-date').fill('2026-07-01');await page.locator('#start-date').dispatchEvent('change');await page.waitForTimeout(150);
  await page.locator('#end-date').fill('2026-09-30');await page.locator('#end-date').dispatchEvent('change');await page.waitForTimeout(150);
  await page.getByText('48 SP target · Selected dates',{exact:true}).waitFor();
  await page.locator('nav button[data-page="Members"]').click();await page.locator('[data-person]').first().click();await page.locator('#year-score').waitFor();
  await scan('Annual member profile');
  await page.locator('#profile-country').selectOption('DO');await page.waitForFunction(()=>document.querySelector('#title').textContent==='Test TPM');
  if(await page.locator('#year-util').count())throw Error('TPM should not have a utilization chart');
  await page.locator('#profile-country').selectOption('JO');await page.waitForFunction(()=>document.querySelector('#subtitle').textContent.includes('Jordan'));await page.locator('#profile-person').selectOption('1');await page.waitForFunction(()=>document.querySelector('#title').textContent==='Test Developer');
  await page.locator('#profile-month').selectOption('0');await page.waitForTimeout(50);
  await page.locator('#profile-year').fill('2025');await page.locator('#profile-year').dispatchEvent('change');await page.locator('#year-score').waitFor();
  await page.locator('nav button[data-page="Tickets"]').click();await page.locator('[data-ticket]').first().click();await page.locator('#comment-form').waitFor();
  await scan('Ticket lifecycle');
  await page.locator('#comment-form textarea').fill('Browser-tested follow-up');await page.locator('#comment-form button').click();await page.getByText('Follow-up saved.',{exact:true}).waitFor();
  await page.locator('nav button[data-page="Overview"]').click();await page.locator('#delivery-chart').waitFor();
  const sizes=[1280,1024,736,540,360,320];
  for(const width of sizes){await page.setViewportSize({width,height:960});await page.waitForTimeout(70);const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);if(overflow)throw Error('Page overflow at '+width);}
  const contrast=await page.locator('.value').first().evaluate(el=>({color:getComputedStyle(el).color,font:getComputedStyle(el).fontSize}));
  if(contrast.color==='rgb(0, 0, 0)')throw Error('Metric text is black');
  if(process.env.QA_SCREENSHOTS){fs.mkdirSync(process.env.QA_SCREENSHOTS,{recursive:true});await page.setViewportSize({width:1280,height:960});await page.screenshot({path:path.join(process.env.QA_SCREENSHOTS,'overview.png'),fullPage:true});}
  if(errors.length)throw Error(errors.join('\n'));
  console.log('Browser checks passed: all pages/admin sections, record creation, rankings, Q3 target, annual profiles, follow-up, real Chart.js, six viewport sizes.');
} finally {if(browser)await browser.close();server.kill();}
