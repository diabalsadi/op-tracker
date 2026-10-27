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
  const utcNow=new Date(), dateEnd=utcNow.toISOString().slice(0,10), year=utcNow.getUTCFullYear();
  for(const preset of ['year','quarter','month']){
    const month=preset==='year'?0:preset==='quarter'?Math.floor(utcNow.getUTCMonth()/3)*3:utcNow.getUTCMonth();
    const expectedStart=`${year}-${String(month+1).padStart(2,'0')}-01`;
    const response=page.waitForResponse(r=>r.url().includes('/api/report?')&&new URL(r.url()).searchParams.get('start_date')===expectedStart);
    await page.locator(`[data-range="${preset}"]`).click();await response;
    await page.waitForFunction(([a,b])=>document.querySelector('#start-date').value===a&&document.querySelector('#end-date').value===b,[expectedStart,dateEnd]);
    await page.locator(`[data-range="${preset}"][aria-pressed=true]`).waitFor();
    const rendered=await page.locator('.grid .panel').first().innerText();
    if(!rendered.includes('SP target'))throw Error('Preset did not refresh report: '+preset);
  }
  // A preset must override custom dates, including an input that still has focus.
  await page.locator('#start-date').fill(`${year}-07-01`);
  await page.locator('#start-date').dispatchEvent('change');
  await page.waitForFunction(()=>document.querySelectorAll('[data-range][aria-pressed=true]').length===0);
  await page.locator('#end-date').fill(`${year}-09-30`);
  await page.locator('[data-range="year"]').click();
  await page.waitForFunction(y=>document.querySelector('#start-date').value===y+'-01-01'&&document.querySelector('[data-range="year"]').getAttribute('aria-pressed')==='true',year);
  await page.locator('[data-range="month"]').focus();await page.keyboard.press('Enter');
  await page.locator('[data-range="month"][aria-pressed=true]').waitFor();
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
  await page.locator('.comment-revision-form textarea').fill('Revised browser follow-up');
  await page.locator('.comment-revision-form input[name=reason]').fill('Fix test wording');
  await page.locator('.comment-revision-form button').click();await page.getByText('Comment revision saved; original entry retained.',{exact:true}).waitFor();
  await page.locator('#correction-form input[name=reason]').fill('Browser evidence repair');
  await page.locator('#correction-form input[name=correct_sp]').fill('8');
  await page.locator('#correction-form button').click();await page.getByText('Evidence correction saved. Revise finalized months explicitly if needed.',{exact:true}).waitFor();
  await page.locator('nav button[data-page="Imports"]').click();await page.locator('#import-form').waitFor();
  await page.locator('#import-form details summary').click();
  await page.locator('[name=map_key]').fill('Issue key');
  await page.locator('[name=profile_name]').fill('Browser mapping');
  await page.locator('#save-profile').click();await page.getByText('Import mapping profile saved.',{exact:true}).waitFor();
  await page.locator('[name=profile_id]').selectOption({label:'Browser mapping'});
  if(await page.locator('[name=map_key]').inputValue()!=='Issue key')throw Error('Mapping profile did not reload');
  const upload=path.join(folder,'browser-upload.csv');
  fs.writeFileSync(upload,'Issue key,Summary,Status,Assignee Id,Story Points,Priority\nOP-99,ملف اختبار,In Progress,dev-a,3,High\n');
  await page.locator('#csv-file').setInputFiles(upload);
  await page.locator('#import-form button.primary').click();await page.locator('#commit-import').waitFor();
  await page.locator('#commit-import').click();await page.getByText('Imported 1 tickets. Preserved prior snapshots.',{exact:true}).waitFor();
  await page.locator('nav button[data-page="Overview"]').click();await page.locator('#export-report').waitFor();
  const downloadPromise=page.waitForEvent('download');await page.locator('#export-report').click();
  const download=await downloadPromise;await download.saveAs(path.join(folder,'export.csv'));
  if(!fs.readFileSync(path.join(folder,'export.csv'),'utf8').includes('Delivered SP'))throw Error('CSV export missing header');
  await page.locator('nav button[data-page="Administration"]').click();
  await page.locator('[data-tab="Teams"]').click();
  await page.locator('#team-form input[name=name]').fill('فريق اختبار باسم طويل لعرض الأسماء');
  await page.locator('#team-form button').click();await page.getByText('Saved to your local database.',{exact:true}).waitFor();
  let liveState=await (await fetch(origin+'/api/state')).json();
  const createdTeam=liveState.teams.find(t=>t.name.startsWith('فريق')).id;
  await page.locator(`[data-edit-team="${createdTeam}"]`).click();
  await page.locator('#team-form input[name=name]').fill('Renamed browser team');
  await page.locator('#team-form button').click();await page.getByRole('heading',{name:'Renamed browser team',exact:true}).waitFor();
  page.on('dialog',dialog=>dialog.accept());
  await page.locator(`[data-archive-team="${createdTeam}"]`).click();
  await page.locator(`[data-reactivate-team="${createdTeam}"]`).waitFor();
  await page.locator(`[data-reactivate-team="${createdTeam}"]`).click();
  await page.locator(`[data-archive-team="${createdTeam}"]`).waitFor();
  await page.locator('[data-tab="Members"]').click();
  liveState=await (await fetch(origin+'/api/state')).json();
  const createdMember=liveState.members.find(m=>m.jira_id==='browser-user').id;
  await page.locator(`[data-archive-member="${createdMember}"]`).click();
  await page.locator(`[data-reactivate-member="${createdMember}"]`).waitFor();
  await page.locator(`[data-reactivate-member="${createdMember}"]`).click();
  await page.locator(`[data-archive-member="${createdMember}"]`).waitFor();
  await page.locator('[data-edit-member="1"]').click();
  await page.locator('#member-form input[name=name]').fill('Test Developer · اسم عربي طويل للاختبار');
  await page.locator('#member-form input[name=effective_at]').fill('2026-10-01T09:00');
  await page.locator('#member-form button.primary').click();await page.getByText('Saved to your local database.',{exact:true}).waitFor();
  await page.locator('[data-tab="Monthly records"]').click();
  await page.locator('#finalize-form input[name=month]').fill('2026-09');
  await page.locator('#finalize-form input[name=reason]').fill('Browser finalization');
  await page.locator('#finalize-form button').click();await page.getByText('2 monthly record(s) saved.',{exact:true}).waitFor();
  await page.locator('#finalize-form input[name=month]').fill('2026-09');
  await page.locator('#finalize-form input[name=reason]').fill('Browser explicit revision');
  await page.locator('#finalize-form select[name=revise]').selectOption('yes');
  await page.locator('#finalize-form button').click();await page.getByText('2 monthly record(s) saved.',{exact:true}).waitFor();
  await page.locator('[data-tab="Backup & restore"]').click();
  await page.locator('#backup').click();await page.getByText('Backup created in data/backups/',{exact:false}).waitFor();
  const selectedBackup=await page.locator('#restore-form select').inputValue();
  await post('save/teams',{name:'Created after UI backup'});
  await page.locator('#restore-form input[name=confirmation]').fill('RESTORE');
  await page.locator('#restore-form button').click();await page.getByText('Backup restored. A safety backup of the previous database was retained.',{exact:true}).waitFor();
  const restored=await (await fetch(origin+'/api/state')).json();
  if(restored.teams.some(t=>t.name==='Created after UI backup'))throw Error('UI restore failed: '+selectedBackup);
  const profileMember=await post('save/members',{name:'Example Member',jira_id:'example-profile',role:'Dev',country:'JO',team_id:team.id,effective_at:'2026-07-01'});
  await post('import/commit',{filename:'synthetic-profile.csv',snapshot_at:'2026-10-26T12:00:00Z',csv:'Issue key,Summary,Status,Assignee Id,Story Points\n'+[
    ['PROFILE-1','Example one','In Progress',3],['PROFILE-2','Example two','Code Review',3],
    ['PROFILE-3','Example three','Code Review',3],['PROFILE-4','Example four','QA',3],
    ['PROFILE-5','Example five','Design Review',2],['PROFILE-6','Example six','Design Review',3]
  ].map(([key,title,status,sp])=>[key,title,status,'example-profile',sp].join(',')).join('\n')});
  await page.reload();await page.locator('#delivery-chart').waitFor();
  await page.locator('nav button[data-page="Members"]').click();
  await page.locator(`[data-person="${profileMember.id}"]`).click();
  await page.getByText('6 tickets · 17 SP',{exact:true}).waitFor();
  if(await page.locator('#profile-ticket-list [data-ticket]').count()!==6)throw Error('Member tickets missing');
  await page.locator('#profile-ticket-status').selectOption('Code Review');
  await page.getByText('2 tickets · 6 SP',{exact:true}).waitFor();
  if(await page.locator('#profile-ticket-list [data-ticket]').count()!==2)throw Error('Status filter did not narrow tickets');
  await page.locator('[data-profile-status="QA"]').click();
  await page.getByText('1 ticket · 3 SP',{exact:true}).waitFor();
  await page.locator('#profile-ticket-status').selectOption('');
  await page.getByText('6 tickets · 17 SP',{exact:true}).waitFor();
  await scan('Member status breakdown');
  if(process.env.QA_SCREENSHOTS)await page.screenshot({path:path.join(process.env.QA_SCREENSHOTS,'member-status.png'),fullPage:true});
  await page.locator('#profile-ticket-status').selectOption('Code Review');
  await page.locator('#profile-person').selectOption('1');
  await page.waitForFunction(()=>document.querySelector('#profile-ticket-status').value==='');
  if(await page.locator('#profile-ticket-list [data-ticket="PROFILE-1"]').count())throw Error('Other member tickets leaked into profile');
  await page.locator('nav button[data-page="Overview"]').click();await page.locator('#delivery-chart').waitFor();
  const sizes=[1280,1024,736,540,360,320];
  for(const width of sizes){await page.setViewportSize({width,height:960});await page.waitForTimeout(70);const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);if(overflow)throw Error('Page overflow at '+width);}
  const contrast=await page.locator('.value').first().evaluate(el=>({color:getComputedStyle(el).color,font:getComputedStyle(el).fontSize}));
  if(contrast.color==='rgb(0, 0, 0)')throw Error('Metric text is black');
  if(process.env.QA_SCREENSHOTS){fs.mkdirSync(process.env.QA_SCREENSHOTS,{recursive:true});await page.setViewportSize({width:1280,height:960});await page.screenshot({path:path.join(process.env.QA_SCREENSHOTS,'overview.png'),fullPage:true});}
  if(errors.length)throw Error(errors.join('\n'));
  console.log('Browser checks passed: all pages/admin sections, six viewport sizes, preset/custom dates, keyboard activation, mappings and file import, comments/revisions/corrections, exports, team/member archive/reactivation, finalization/revision, backup/restore, rankings, profiles, real Chart.js.');
} finally {if(browser)await browser.close();server.kill();}
