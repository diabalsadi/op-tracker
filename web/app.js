'use strict';
const $ = s => document.querySelector(s);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pages = ['Overview','Delivery','Utilization','Performance','Rankings','Members','Tickets','Imports','Administration'];
const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
let today = new Date();
let activePreset='month';
let adminMemberFilters={query:'',role:'',team:'',country:''};
let state, page = 'Overview', period = today.toISOString().slice(0,7), team = '', country = '', adminTab = 'Members';
let startDate = period+'-01', endDate = today.toISOString().slice(0,10);
let peopleSearch='',peoplePosition='';
let profileTicketStatus = '';
let charts = [], profileId = null, profileYear = today.getFullYear(), profileMonth = today.getMonth(), ticketKey = null;
let stateDirty=false;
const reportCache=new Map();
let reportData=null,profileData=null,profileRoster=[],renderSequence=0,rankingScope='Individual';
let pendingImport = null, importResult = null, edit = null, rankMetric = 'score';
const countryName = code => state.countries.find(c => c.code === code)?.name || code;
const teamName = id => state.teams.find(t => t.id === Number(id))?.name || 'Unmapped';
const memberAssignments = m => {const raw=typeof m.team_assignments==='string'?JSON.parse(m.team_assignments):m.team_assignments;return raw||[{team_id:m.team_id,qa_slot:m.qa_slot}];};
const memberInTeam = (m,id) => memberAssignments(m).some(a=>a.team_id===Number(id));
const memberTeams = m => memberAssignments(m).map(a=>teamName(a.team_id)+(m.role==='QA'?' ('+a.qa_slot+')':'')).join(', ');
const memberName = id => state.members.find(m => m.id === Number(id))?.name || 'Unmapped';
const opts = (xs, value, label='name', key='id') => xs.map(x => `<option value="${esc(x[key])}" ${String(x[key]) === String(value) ? 'selected' : ''}>${esc(x[label])}</option>`).join('');
const choices = (xs, value) => xs.map(x => `<option ${x === value ? 'selected' : ''}>${esc(x)}</option>`).join('');
const panel = (title, body) => `<section class="panel"><h2>${title}</h2>${body}</section>`;
const link = (text, attr) => `<button type="button" class="link" ${attr}>${esc(text)}</button>`;
const scoreLabel = n => n===null||n===undefined?'Not yet assessed':fmt(n);
const fmt = n => n === null || n === undefined || !Number.isFinite(n) ? 'N/A' : Number(n.toFixed(1)).toLocaleString();
const dateLabel = d => d ? new Date(d).toLocaleString() : 'Unknown timestamp';
const getMembers = () => reportData?.members || state.members.filter(m => !m.archived && (!team || memberInTeam(m,team)) && (!country || m.country === country));
const getTickets = () => state.tickets.filter(t => (!team || t.team_id === Number(team)) && (!country || state.members.find(m => m.id === t.member_id)?.country === country));
const workflowTickets = () => state.tickets.filter(t=>{const assignee=state.members.find(m=>!m.archived&&m.jira_id===t.assignee);return assignee&&(!team||memberInTeam(assignee,team))&&(!country||assignee.country===country);});
const monthOf = at => at?.slice(0,7);
function announce(text, error=false) { $('#notice').className = error ? 'notice error' : 'notice'; $('#notice').textContent = text; }
async function api(path, data) {
  const cached=data===undefined&&path.startsWith('report?')?reportCache.get(path):null;
  if(cached&&cached.expires>Date.now())return cached.promise;
  const promise=(async()=>{
    const response=await fetch('/api/'+path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    const result=await response.json();
    if(!response.ok)throw new Error(result.error||'Request failed');
    if(data!==undefined&&!['import/preview','export'].includes(path)){reportCache.clear();stateDirty=true;}
    return result;
  })();
  if(data===undefined&&path.startsWith('report?')){
    for(const [key,entry] of reportCache)if(entry.expires<=Date.now())reportCache.delete(key);
    if(reportCache.size>=20)reportCache.delete(reportCache.keys().next().value);
    reportCache.set(path,{promise,expires:Date.now()+5000});
    promise.catch(()=>{if(reportCache.get(path)?.promise===promise)reportCache.delete(path);});
  }
  return promise;
}
function updateDataStatus(){const badge=$('#data-status');badge.className='badge'+(state.stale_days>1?' warning':'');badge.textContent=state.stale_days===null?'No imports yet':state.stale_days>1?'Data '+state.stale_days+' days old · Upload today’s snapshot':'Daily data · Latest snapshot '+state.imports[0].snapshot_at.slice(0,10);}
async function reload(force=false) {
  const partial=state&&page==='Administration'&&!force;
  const data=await api(partial?'config':'state');
  state=partial?{...state,...data}:data;
  if(!partial)stateDirty=false;
  updateDataStatus();
}
function destroyCharts() { charts.forEach(c => c.destroy()); charts = []; }
function monthlyMetric(m, month) {
  const credits = state.credits.filter(c => c.member_id === m.id && monthOf(c.at) === month);
  const sp = credits.reduce((a,c) => a+c.sp,0), util = m.role === 'Dev' ? sp/state.settings.monthly_target*100 : null;
  const bonus = util === null ? 0 : Math.floor(Math.max(0,util-100)/20)*10;
  const events = state.score_events.filter(e => e.member_id === m.id && monthOf(e.at) === month);
  return {sp,util,bonus,critical:events.filter(e=>e.points>0).reduce((a,e)=>a+e.points,0),penalties:events.filter(e=>e.points<0).reduce((a,e)=>a-e.points,0),score:100+bonus+events.reduce((a,e)=>a+e.points,0),events,credits};
}
function dateInRange(at) {const d=at?.slice(0,10);return d>=startDate&&d<=endDate;}
function rangeMonths() {
  const result=[],d=new Date(startDate+'T12:00:00Z');d.setUTCDate(1);
  while(d.toISOString().slice(0,10)<=endDate){result.push(d.toISOString().slice(0,7));d.setUTCMonth(d.getUTCMonth()+1);}
  return result;
}
function rangeTarget(m) { return reportData?.members.find(r=>r.id===m.id)?.target ?? 0; }
function metric(m,month=null) {
  if(month) return profileData?.months.find(r=>r.month===month) || {sp:0,target:0,util:null,bonus:0,critical:0,penalties:0,score:null,events:[],credits:[],eligible:false,record_status:'Not active'};
  return reportData?.members.find(r=>r.id===m.id) || {sp:0,util:null,score:null,target:0,months:[]};
}
function table(headers, rows) { return `<div class="table-wrap"><table><thead><tr>${headers.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('') || `<tr><td colspan="${headers.length}" class="empty">No records for this selection.</td></tr>`}</tbody></table></div>`; }
function memberTable(ms) { return table(['Member','Role / team','Country','Done SP','Utilization','Score'],ms.map(m=>{const v=metric(m);return `<tr><td>${link(m.name,`data-person="${m.id}"`)}</td><td>${esc(m.role)} · ${esc(memberTeams(m))}</td><td>${esc(countryName(m.country))}</td><td>${v.target>0?fmt(v.sp):'N/A'}</td><td>${v.util===null?'N/A':fmt(v.util)+'%'}</td><td>${scoreLabel(v.score)}</td></tr>`;})); }
function ticketsTable(ts) { return table(['Ticket','Summary','Status','Owner','SP','Last seen'],ts.map(t=>`<tr><td>${link(t.key,`data-ticket="${esc(t.key)}"`)}</td><td>${esc(t.summary)}</td><td><span class="badge ${['blocked','on hold'].includes(t.status.toLowerCase())?'warning':''}">${esc(t.status)}</span></td><td>${esc(memberName(t.member_id))}</td><td>${fmt(t.sp)}</td><td>${dateLabel(t.last_seen)}</td></tr>`)); }
function chartBox(id,title,note='Hover for values. Click a legend item to toggle its series.') { return panel(title,`<div class="chart"><canvas id="${id}" role="img" aria-label="${esc(title)}; values are available in the accompanying tables."></canvas></div><p class="chart-note">${note}</p>`); }
function draw(id,type,labels,datasets,yTitle,click,xTitle='Month') {
  const el = $('#'+id); if(!el) return;
  if(!globalThis.Chart) { el.parentElement.textContent='Chart unavailable. See the values below.'; return; }
  charts.push(new Chart(el,{type,data:{labels,datasets},options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:'index',intersect:false},plugins:{legend:{display:datasets.length>1,labels:{color:'#d2dfd7',font:{size:12}}},tooltip:{backgroundColor:'#14271c',titleColor:'#f1f6f3',bodyColor:'#f1f6f3',padding:12}},scales:{x:{grid:{display:false},ticks:{color:'#b5c4bb',maxRotation:0},title:{display:true,text:xTitle,color:'#d2dfd7'}},y:{beginAtZero:true,grid:{color:'#789e8833'},ticks:{color:'#b5c4bb'},title:{display:true,text:yTitle,color:'#d2dfd7'}}},onClick:(_,els)=>{if(els.length && click) click(els[0].index);}}}));
}
const series = (label,data,color='#66d1a3',type='bar') => ({label,data,type,backgroundColor:color,borderColor:color,borderWidth:type==='line'?2:0,borderRadius:type==='bar'?5:0,pointRadius:type==='line'?3:0,tension:.2});
async function render() {
  today=new Date();
  if(activePreset){const y=today.getUTCFullYear(),m=today.getUTCMonth();startDate=activePreset==='year'?`${y}-01-01`:`${y}-${String((activePreset==='quarter'?Math.floor(m/3)*3:m)+1).padStart(2,'0')}-01`;endDate=today.toISOString().slice(0,10);}
  const sequence=++renderSequence;
  try {
    if(stateDirty&&page!=='Administration')await reload(true);
    if(!['Administration','Imports','Tickets'].includes(page))reportData=await api('report?'+new URLSearchParams({start_date:startDate,end_date:endDate,...(team?{team_id:team}:{}),...(country?{country}:{} )}));
  }catch(error){announce(error.message,true);return;}
  if(sequence!==renderSequence)return;
  destroyCharts(); profileId=null; ticketKey=null;
  $('nav').innerHTML=pages.map(p=>`<button data-page="${p}" ${p===page?'aria-current="page"':''}>${p}</button>`).join('');
  $('#title').textContent=page; $('#subtitle').textContent='Delivery, accountability, and team momentum.';
  $('#filters').hidden=['Imports','Administration'].includes(page);
  $('#filters').innerHTML=`<label>Start date (UTC)<input id="start-date" type="date" value="${startDate}" max="${endDate}"></label><label>End date (UTC)<input id="end-date" type="date" value="${endDate}" min="${startDate}" max="${today.toISOString().slice(0,10)}"></label><label>Team<select id="team"><option value="">All teams</option>${opts(state.teams.filter(t=>!t.archived),team)}</select></label><label>Country<select id="country"><option value="">All countries</option>${opts(state.countries,country,'name','code')}</select></label><div class="tabs"><button type="button" data-range="month" aria-pressed="${activePreset==='month'}">This month</button><button type="button" data-range="quarter" aria-pressed="${activePreset==='quarter'}">This quarter</button><button type="button" data-range="year" aria-pressed="${activePreset==='year'}">This year</button></div><label>Sprint<select id="sprint-filter"><option value="">Custom dates</option>${opts(state.sprints,'')}</select></label><button id="export-report">Export CSV</button><span class="badge">${rangeMonths().length} monthly score record(s) · Working-day target</span>`;
  const last=state.imports[0]; $('#freshness').textContent=last?'Last snapshot: '+dateLabel(last.snapshot_at)+(state.stale_days?' · '+state.stale_days+' day(s) old':' · Up to date'):'No CSV imported yet · Empty local database';
  const ms=getMembers(), dev=ms.filter(m=>m.target>0), ts=getTickets(), values=ms.map(m=>metric(m));
  const sum=dev.reduce((a,m)=>a+metric(m).sp,0), avg=reportData.score;
  const totalTarget=dev.reduce((s,m)=>s+rangeTarget(m),0);
  const stats=`<div class="grid">${[['Delivered SP',fmt(sum),fmt(totalTarget)+' SP target · Selected dates'],['Dev utilization',totalTarget?fmt(sum/totalTarget*100)+'%':'N/A',dev.length+' developers'],['Average score',scoreLabel(avg),'Average of monthly scores · Selected months']].map(([l,v,n])=>`<div class="panel"><div class="muted">${l}</div><strong class="value">${v}</strong><div class="muted">${n}</div></div>`).join('')}</div>`;
  const content=$('#content');
  if(page==='Overview') {
    content.innerHTML=stats+`<div class="columns">${chartBox('delivery-chart','Developer delivery · Selected dates')}${chartBox('workflow-chart','Current workflow snapshot','Configured assignees only. Click a status to open its tickets. Latest observed state, across all dates.')}</div>`+panel('Recent tickets',ticketsTable(ts))+panel('Data quality',`<p class="muted">${esc(state.calculation_note)}</p>${state.warnings.slice(0,12).map(w=>`<div class="row">${esc(w)}</div>`).join('')||'<p class="muted">No unresolved data warnings.</p>'}`);
    draw('delivery-chart','bar',dev.map(m=>m.name),[series('Done SP',dev.map(m=>metric(m).sp)),{...series('Period target',dev.map(rangeTarget),'#cad8d0','line'),borderDash:[5,5]}],'Story points',i=>profile(dev[i].id),'Developer');
    const workflowRows=workflowTickets(),statuses=[...new Set(workflowRows.map(t=>t.status))]; draw('workflow-chart','bar',statuses,[series('Tickets',statuses.map(s=>workflowRows.filter(t=>t.status===s).length))],'Ticket count',async i=>{page='Tickets';await render();$('#content').innerHTML=panel(esc(statuses[i]),ticketsTable(workflowRows.filter(t=>t.status===statuses[i])));},'Status');
  }
  if(page==='Delivery'||page==='Utilization') {
    content.innerHTML=stats+chartBox('util-chart',page==='Delivery'?'Completed story points by developer':'Developer utilization vs 100% target','Click a bar to inspect the developer’s yearly history.')+panel('Developer records',memberTable(dev));
    const utilization=page==='Utilization';draw('util-chart','bar',dev.map(m=>m.name),[series(utilization?'Utilization (%)':'Done SP',dev.map(m=>utilization?metric(m).util:metric(m).sp)),{...series('Target',dev.map(m=>utilization?100:rangeTarget(m)),'#cad8d0','line'),borderDash:[5,5]}],utilization?'Utilization (%)':'Story points',i=>profile(dev[i].id),'Developer');
  }
  if(page==='Performance')renderPerformance();
  if(page==='Members')content.innerHTML=panel('Team members',memberTable(ms))+`<button class="primary" data-admin="Members">Manage members & assignments</button>`;
  if(page==='Tickets')content.innerHTML=panel('Ticket explorer',ticketsTable(ts));
  if(page==='Rankings')renderRankings().catch(e=>announce(e.message,true));
  if(page==='Delivery')renderDurations();
  if(page==='Imports')renderImport();
  if(page==='Administration'){renderAdmin();appendAdminHistory();}
}
function filteredPeople(rows) {
  const query=peopleSearch.trim().normalize('NFKC').toLocaleLowerCase();
  return rows.filter(m=>(!peoplePosition||m.role===peoplePosition)&&(!query||[m.name,m.jira_id].some(value=>String(value||'').normalize('NFKC').toLocaleLowerCase().includes(query))));
}
function peopleFilterControls() {
  return `<div class="toolbar" aria-label="People filters"><label>Search name or Jira ID<input id="people-search" type="search" value="${esc(peopleSearch)}" placeholder="Search people…"></label><label>Position<select id="people-position"><option value="">All positions</option>${[{id:'Dev',name:'Developer'},{id:'QA',name:'QA'},{id:'TPM',name:'TPM'}].map(r=>`<option value="${r.id}" ${peoplePosition===r.id?'selected':''}>${r.name}</option>`).join('')}</select></label><span class="muted">Combine with the Team and Country filters above.</span><button type="button" id="clear-people-filters">Clear search & position</button></div>`;
}
function renderPerformance() {
  $('#content').innerHTML=peopleFilterControls()+`<div id="performance-results"></div>`;
  updatePerformance();
}
function performanceReview(rows) {
  const tickets=new Map(),people=[];
  for(const m of rows){
    const events=m.review_events||[],deductions=events.reduce((sum,e)=>sum-e.points,0),reasons=[];
    if(m.score===null)reasons.push('Not yet assessed: insufficient scoring evidence');
    if(m.score!==null&&m.score<100)reasons.push(`Score ${fmt(m.score)} (below 100)`);
    if(m.target>0&&m.util!==null&&m.util<100)reasons.push(`Delivery ${fmt(m.util)}% of ${fmt(m.target)} SP target`);
    if(deductions>0)reasons.push(`${fmt(deductions)} deduction points`);
    if(reasons.length)people.push({m,deductions,reasons});
    for(const e of events){
      if(!tickets.has(e.key))tickets.set(e.key,{key:e.key,points:0,people:new Map(),reasons:new Set(),last:e.at});
      const t=tickets.get(e.key);t.points-=e.points;t.people.set(m.id,m.name);t.reasons.add(e.reason);if(e.at>t.last)t.last=e.at;
    }
  }
  people.sort((a,b)=>(a.m.score??100)-(b.m.score??100)||b.deductions-a.deductions||a.m.name.localeCompare(b.m.name));
  const flagged=[...tickets.values()].sort((a,b)=>b.points-a.points||a.key.localeCompare(b.key));
  return panel('People to look into',`<p class="muted">Review prompts: insufficient scoring evidence, score below 100, developer delivery below the selected period’s target, or recorded deductions. Uses your search, position, team, country and date filters. Scores retain the monthly calculation shown above.</p><div id="review-people">${people.length?table(['Person','Position','Why review'],people.map(({m,reasons})=>`<tr><td>${link(m.name,`data-person="${m.id}"`)}</td><td>${esc(m.role)}</td><td>${reasons.map(esc).join(' · ')}</td></tr>`)):'<p class="muted">No people meet these review criteria.</p>'}</div>`)+panel('Tickets to look into',`<p class="muted">Tickets with deductions recorded during the selected dates, highest total first. Totals include each accountable person; finalized records are preserved. Click a ticket to inspect its timeline and deductions.</p><div id="review-tickets">${flagged.length?table(['Ticket','Deduction points','People affected','Reason','Latest deduction'],flagged.map(t=>`<tr><td>${link(t.key,`data-ticket="${esc(t.key)}"`)}</td><td>${fmt(t.points)}</td><td>${[...t.people.values()].map(esc).join(', ')}</td><td>${[...t.reasons].map(esc).join(' · ')}</td><td>${dateLabel(t.last)}</td></tr>`)):'<p class="muted">No ticket deductions recorded for these filters.</p>'}</div>`);
}
function updatePerformance() {
  const rows=filteredPeople(getMembers()),dev=rows.filter(m=>m.target>0);
  const total=key=>dev.reduce((sum,m)=>sum+(m[key]||0),0),scores=rows.filter(m=>m.score!==null);
  const target=total('target'),sp=total('sp'),score=scores.length?scores.reduce((sum,m)=>sum+m.score,0)/scores.length:null;
  destroyCharts();
  $('#performance-results').innerHTML=`<p class="muted" role="status">${rows.length} people match your filters</p><div class="grid">${[['Delivered SP',fmt(sp)],['Dev utilization',target?fmt(sp/target*100)+'%':'N/A'],['Average score',scoreLabel(score)]].map(([label,value])=>`<div class="panel"><div class="muted">${label}</div><strong class="value">${value}</strong></div>`).join('')}</div>`+chartBox('score-chart','Member comparison','Click a bar to open the annual person dashboard.')+panel('Monthly performance',memberTable(rows))+performanceReview(rows);
  draw('score-chart','bar',rows.map(m=>m.name),[series('Score',rows.map(m=>m.score))],'Score points',i=>profile(rows[i].id),'Member');
}
function updatePeopleFilters(){if(page==='Performance')updatePerformance();if(page==='Rankings')renderRankings().catch(e=>announce(e.message,true));}
document.addEventListener('input',e=>{if(e.target.id==='people-search'){peopleSearch=e.target.value;updatePeopleFilters();}});
async function profile(id) {
  const seq=++renderSequence;
  const end=profileYear===today.getFullYear()?today.toISOString().slice(0,10):`${profileYear}-12-31`;
  let report;
  try{report=await api('report?'+new URLSearchParams({start_date:profileYear+'-01-01',end_date:end}));}catch(error){announce(error.message,true);return;}
  if(seq!==renderSequence)return;
  profileRoster=report.members;profileData=report.members.find(m=>m.id===Number(id))||null;

  if(profileId!==Number(id))profileTicketStatus='';
  destroyCharts();profileId=Number(id);ticketKey=null;const m=profileData||state.members.find(m=>m.id===profileId); if(!m)return;
  $('#title').textContent=m.name;$('#subtitle').textContent=`${m.role} · ${memberTeams(m)} · ${countryName(m.country)}`;$('#filters').hidden=true;
  const rows=months.map((name,i)=>{const key=`${profileYear}-${String(i+1).padStart(2,'0')}`,future=key>today.toISOString().slice(0,7);return {name,key,future,...metric(m,key)};});
  const hasDevHistory=rows.some(r=>r.target>0);
  const valid=rows.filter(r=>!r.future&&r.eligible),assessed=valid.filter(r=>r.score!==null),sp=valid.reduce((a,r)=>a+r.sp,0),score=assessed.length?assessed.reduce((a,r)=>a+r.score,0)/assessed.length:null;
  $('#content').innerHTML=link('← Back to members','data-page="Members"')+`<div class="toolbar"><label>Person<select id="profile-person">${opts((profileRoster.length?profileRoster:state.members).filter(x=>(!country||x.country===country)&&(!team||memberInTeam(x,team))),m.id)}</select></label><label>Year<input type="number" id="profile-year" min="2000" max="${today.getFullYear()}" value="${profileYear}"></label><label>Country<select id="profile-country"><option value="">All countries</option>${opts(state.countries,country,'name','code')}</select></label></div><div id="profile-tickets"></div><div class="grid"><div class="panel"><div class="muted">${hasDevHistory?'Delivered SP':'Role'}</div><strong class="value">${hasDevHistory?fmt(sp):m.role}</strong><div class="muted">${profileYear} · Recorded period</div></div><div class="panel"><div class="muted">Average monthly score</div><strong class="value">${scoreLabel(score)}</strong><div class="muted">${valid.length} active months · Finalized records preserved</div></div><div class="panel"><div class="muted">${hasDevHistory?'Period utilization':'Critical rewards'}</div><strong class="value">${hasDevHistory?(profileData?.util===null||profileData?.util===undefined?'N/A':fmt(profileData.util)+'%'):fmt(valid.reduce((a,r)=>a+r.critical,0))}</strong><div class="muted">${hasDevHistory?fmt(profileData?.target)+' SP target through selected year-end / today':'Performance only; no utilization target'}</div></div></div>`+(hasDevHistory?chartBox('year-delivery','Monthly delivery and target')+chartBox('year-util','Monthly utilization (%)'):'')+chartBox('year-score','Monthly performance score','Click a month for its detailed breakdown.')+`<div id="month-detail"></div>`+panel('Monthly records',table(['Month','Done SP','Utilization','Bonus','Deductions','Score'],rows.map((r,i)=>`<tr><td>${link(r.name,`data-month="${i}"`)}</td><td>${r.future?'—':hasDevHistory?fmt(r.sp):'N/A'}</td><td>${r.future?'—':hasDevHistory?fmt(r.util)+'%':'N/A'}</td><td>${r.future?'—':fmt(r.bonus+r.critical)}</td><td>${r.future?'—':fmt(r.penalties)}</td><td>${r.future?'Future':scoreLabel(r.score)+' · '+r.record_status}</td></tr>`)));
  const pick=i=>{profileMonth=i;monthDetail();},data=key=>rows.map(r=>r.future||!r.eligible?null:r[key]);
  if(hasDevHistory) {
    draw('year-delivery','bar',months,[series('Done SP',data('sp')),{...series('Target SP',rows.map(r=>r.future||!r.eligible?null:r.target),'#cad8d0','line'),borderDash:[5,5]}],'Story points',pick);
    draw('year-util','line',months,[series('Utilization (%)',data('util'),'#66d1a3','line'),{...series('Target (%)',rows.map(r=>r.future||!r.eligible||r.score===null?null:100),'#cad8d0','line'),borderDash:[5,5]}],'Utilization (%)',pick);
  }
  draw('year-score','line',months,[series('Score',data('score'),'#66d1a3','line'),{...series('Baseline',rows.map(r=>r.future||!r.eligible||r.score===null?null:100),'#cad8d0','line'),borderDash:[5,5]}],'Score points',pick);monthDetail();renderProfileTickets();
}
function renderProfileTickets() {
  const container=$('#profile-tickets');if(!container||profileId===null)return;
  const tickets=state.tickets.filter(t=>t.member_id===profileId||(t.owners||[]).some(m=>m.id===profileId));
  const statuses=[...new Set(tickets.map(t=>t.status))].sort((a,b)=>a.localeCompare(b));
  if(!statuses.includes(profileTicketStatus))profileTicketStatus='';
  const selected=tickets.filter(t=>!profileTicketStatus||t.status===profileTicketStatus);
  const points=rows=>rows.reduce((sum,t)=>sum+(Number.isFinite(t.sp)?t.sp:0),0);
  const missing=selected.filter(t=>!Number.isFinite(t.sp)).length;
  const summary=table(['Status','Tickets','Story points'],statuses.map(status=>{
    const rows=tickets.filter(t=>t.status===status);
    return `<tr><td><button type="button" data-profile-status="${esc(status)}" aria-pressed="${profileTicketStatus===status}">${esc(status)}</button></td><td>${rows.length}</td><td>${fmt(points(rows))}${rows.some(t=>!Number.isFinite(t.sp))?' + unknown':''}</td></tr>`;
  }));
  container.innerHTML=panel('Tickets by status',`<p class="muted">Latest observed tickets assigned to this developer or accountable team member, across all dates. The annual charts below use the selected year. Status SP totals are current estimates, separate from completed delivery credit.</p><div class="toolbar"><label>Status<select id="profile-ticket-status"><option value="">All statuses (${tickets.length})</option>${statuses.map(status=>`<option value="${esc(status)}" ${profileTicketStatus===status?'selected':''}>${esc(status)} (${tickets.filter(t=>t.status===status).length})</option>`).join('')}</select></label><span id="profile-ticket-total" class="badge" role="status">${selected.length} ticket${selected.length===1?'':'s'} · ${fmt(points(selected))} SP${missing?` · ${missing} missing estimate(s)`:''}</span></div>`+summary+`<h3>${esc(profileTicketStatus||'All statuses')}</h3><div id="profile-ticket-list">${ticketsTable(selected)}</div>`);
}
function monthDetail() {
  const m=state.members.find(m=>m.id===profileId);if(!m)return;const key=`${profileYear}-${String(profileMonth+1).padStart(2,'0')}`,v=metric(m,key);
  $('#month-detail').innerHTML=panel(months[profileMonth]+' '+profileYear,`<div class="toolbar"><label>Inspect month<select id="profile-month">${months.map((m,i)=>`<option value="${i}" ${profileMonth===i?'selected':''}>${m}</option>`).join('')}</select></label></div>`+(key>today.toISOString().slice(0,7)?'<div class="empty">Future month · No records.</div>':`<div class="columns"><div>${[['Baseline',v.score===null?null:100],['Utilization bonus',v.bonus],['Critical rewards',v.critical],['Delay deductions',-v.penalties],['Monthly score',v.score]].map(([l,n])=>`<div class="row"><span>${l}</span><strong>${l==='Monthly score'?scoreLabel(n):fmt(n)}</strong></div>`).join('')}</div><div><h3>Delivery credits</h3>${v.credits.map(c=>`<div class="row">${link(c.key,`data-ticket="${esc(c.key)}"`)}<span>${c.sp} SP</span></div>`).join('')||'<p class="muted">No completion credits.</p>'}<h3>Score events</h3>${v.events.map(e=>`<div class="row"><div>${link(e.key,`data-ticket="${esc(e.key)}"`)}<p class="muted">${esc(e.reason)} · ${dateLabel(e.at)}</p></div><span>${e.points>0?'+':''}${e.points}</span></div>`).join('')||'<p class="muted">No score events.</p>'}</div></div>`));
}
async function ticket(key) {
  const detail=await api('ticket?key='+encodeURIComponent(key));destroyCharts();profileId=null;ticketKey=key;$('#filters').hidden=true;
  const t=detail.current;$('#title').textContent=key;$('#subtitle').textContent=t.summary;
  const authorIds=new Set(detail.observations.flatMap(o=>(o.payload.owners||[]).filter(m=>m.id===o.payload.member_id&&m.role==='Dev'||m.team_id===o.payload.team_id&&m.role==='TPM').map(m=>m.id)));
  const authors=state.members.filter(m=>authorIds.has(m.id));
  const events=[...detail.events.map(e=>({at:e.at,title:`${e.kind}: ${typeof e.from==='object'&&e.from?JSON.stringify(e.from):e.from??'First observed'} → ${typeof e.to==='object'&&e.to?JSON.stringify(e.to):e.to??'Unknown'}`,body:e.evidence})),...detail.comments.map(c=>({at:c.at,title:`Comment · ${c.author||'Unknown author'}`,body:c.body+' · '+c.source})),...state.score_events.filter(e=>e.key===key).map(e=>({at:e.at,title:`${memberName(e.member_id)} · ${e.points>0?'+':''}${e.points} points`,body:e.reason}))].sort((a,b)=>(a.at||'').localeCompare(b.at||''));
  $('#content').innerHTML=link('← Back to tickets','data-page="Tickets"')+`<div class="toolbar"><span class="badge">${esc(t.status)}</span><span>${esc(t.severity)} · ${fmt(t.sp)} SP · ${esc(memberName(t.member_id))} · ${esc(teamName(t.team_id))}</span></div><div class="columns">`+panel('Lifecycle & evidence',events.map(e=>`<div class="step">${esc(e.title)}<p>${dateLabel(e.at)}</p><p class="break">${esc(e.body)}</p></div>`).join(''))+panel('Add follow-up',`<form class="form" id="comment-form"><label>Recorded author<select name="author_id" required>${opts(authors,authors[0]?.id)}</select></label><label>Occurred at (your local time)<input name="occurred_at" type="datetime-local" required value="${localNow()}"></label><label>Comment<textarea name="body" required placeholder="Blocker or progress update…"></textarea></label><button class="primary" ${authors.length?'':'disabled'}>Save follow-up</button><p class="muted">One comment by the developer or TPM resets the shared follow-up clock. Earlier valid deductions remain.</p></form>`)+`</div>`+panel('Manual follow-up revisions',detail.comments.filter(c=>c.manual_id).map(c=>`<form class="form comment-revision-form"><input type="hidden" name="id" value="${c.manual_id}">${field('Occurrence time','occurred_at',new Date(new Date(c.at)-new Date(c.at).getTimezoneOffset()*60000).toISOString().slice(0,16),'datetime-local','required')}<label>Comment<textarea name="body" required>${esc(c.body)}</textarea></label>${field('Correction reason','reason','','text','required')}<button>Save revised comment</button></form>`).join('')||'<p class="muted">No manual comments to revise.</p>')+ticketExtras(t);
}
function localNow(){const d=new Date();return new Date(d-d.getTimezoneOffset()*60000).toISOString().slice(0,16);}
function renderImport() {
  $('#content').innerHTML=panel('Daily Jira CSV snapshot',`<form id="import-form" class="form"><div class="notice">Tickets match by Jira key. Changed statuses and new comments update their timeline. Existing snapshots are preserved; missing tickets are not removed.</div><div class="fields"><label>CSV file<input id="csv-file" type="file" accept=".csv,text/csv" required></label><label>Snapshot time (your local time)<input name="snapshot_at" type="datetime-local" value="${localNow()}" required></label></div><details><summary>Column mapping overrides (optional)</summary><div class="fields">${[['key','Ticket key'],['status','Status'],['assignee','Jira assignee ID'],['sp','Story points'],['severity','Severity'],['resolved','Resolved timestamp'],['critical_at','Critical since'],['status_at','Status changed timestamp']].map(([k,l])=>`<label>${l}<input name="map_${k}" placeholder="Auto-detect header"></label>`).join('')}</div></details><button class="primary">Preview import</button></form>`)+(importResult?panel('Import preview',`<p>${importResult.count} rows · ${dateLabel(importResult.snapshot_at)}</p>${(importResult.warnings||[]).map(w=>`<div class="row">${esc(w)}</div>`).join('')}<div class="table-wrap"><table><thead><tr><th>Key</th><th>Status</th><th>Assignee</th><th>SP</th></tr></thead><tbody>${(importResult.sample||[]).map(t=>`<tr><td>${t.key}</td><td>${esc(t.status)}</td><td>${esc(t.assignee)}</td><td>${fmt(t.sp)}</td></tr>`).join('')}</tbody></table></div>${importResult.duplicate?'<p class="muted">Already imported. No changes.</p>':'<button id="commit-import" class="primary">Commit snapshot</button>'}`):'')+panel('Import history',table(['File','Snapshot time','Imported at'],state.imports.map(i=>`<tr><td>${esc(i.filename)}</td><td>${dateLabel(i.snapshot_at)}</td><td>${dateLabel(i.created_at)}</td></tr>`)));
}
function field(label,name,value='',type='text',extra=''){return `<label>${label}<input name="${name}" type="${type}" value="${esc(value)}" ${extra}></label>`;}
function select(label,name,options,required=false){return `<label>${label}<select name="${name}"${required?' required':''}>${options}</select></label>`;}
function renderMemberAssignmentFields(member) {
  const container=$('#member-team-options');if(!container)return;
  const selected=memberAssignments(member);
  const teams=state.teams.filter(t=>!t.archived);
  container.innerHTML=`<label>Teams</label><details class="team-multiselect"><summary id="member-team-summary">Choose teams</summary><div class="team-options">${teams.map(t=>`<label><input type="checkbox" name="assigned_team" value="${t.id}" ${selected.some(a=>a.team_id===t.id)?'checked':''}>${esc(t.name)}</label>`).join('')}</div></details><div class="member-qa-slots">${teams.map(t=>{const current=selected.find(a=>a.team_id===t.id);return `<label class="member-qa-slot" data-qa-team="${t.id}">${esc(t.name)} · QA position<select name="qa_slot_${t.id}">${choices(['Primary','Secondary'],current?.qa_slot||'Primary')}</select></label>`;}).join('')}</div>`;
  updateMemberAssignmentRole();
}
function updateMemberAssignmentRole() {
  const role=$('#member-form select[name=role]')?.value;if(!role)return;
  $('#member-single-team').hidden=role!=='Dev';
  $('#member-team-options').hidden=role==='Dev';
  const chosen=[...document.querySelectorAll('#member-team-options [name=assigned_team]:checked')].map(input=>Number(input.value));
  $('#member-team-summary').textContent=chosen.length?chosen.map(teamName).join(', '):'Choose teams';
  document.querySelectorAll('.member-qa-slot').forEach(el=>el.hidden=role!=='QA'||!chosen.includes(Number(el.dataset.qaTeam)));
}
function renderAdminMemberDirectory() {
  const container=$('#admin-member-directory');if(!container)return;
  const normalized=value=>String(value||'').normalize('NFKC').toLocaleLowerCase();
  const query=normalized(adminMemberFilters.query.trim());
  const members=state.members.filter(m=>(!query||normalized(m.name).includes(query)||normalized(m.jira_id).includes(query))
    &&(!adminMemberFilters.role||m.role===adminMemberFilters.role)
    &&(!adminMemberFilters.team||memberInTeam(m,adminMemberFilters.team))
    &&(!adminMemberFilters.country||m.country===adminMemberFilters.country));
  $('#admin-member-count').textContent=`${members.length} of ${state.members.length} people`;
  container.innerHTML=table(['Name / Jira ID','Role','Country','Teams',''],members.map(m=>`<tr><td>${esc(m.name)}<div class="muted">${esc(m.jira_id)}</div></td><td>${m.role}</td><td>${esc(countryName(m.country))}</td><td>${esc(memberTeams(m))}</td><td><button data-edit-member="${m.id}">Edit</button> ${m.archived?`<span class="badge">Archived</span> <button data-reactivate-member="${m.id}">Reactivate</button>`:`<button data-archive-member="${m.id}">Archive</button>`}</td></tr>`));
}
document.addEventListener('input',e=>{
  if(e.target.id==='admin-member-search'){adminMemberFilters.query=e.target.value;renderAdminMemberDirectory();}
});
function renderAdmin() {
  $('#content').innerHTML=`<div class="tabs" aria-label="Administration sections">${['Members','Teams','Workflow rules','Workflow','Sprints','Calendars','Targets','Monthly records','Backup & restore'].map(t=>`<button data-tab="${t}" aria-pressed="${adminTab===t}">${t}</button>`).join('')}</div><div id="admin-body"></div>`;
  const b=$('#admin-body');
  if(['Workflow','Sprints','Monthly records','Backup & restore'].includes(adminTab)){renderExtraAdmin(b);return;}
  if(adminTab==='Members') {
    const m=edit||{country:'JO',role:'Dev',qa_slot:'Primary'};
    b.innerHTML=panel(edit?'Edit member':'Add member',`<form id="member-form" class="form"><input type="hidden" name="id" value="${m.id||''}"><div class="fields">${field('Effective from (local time)','effective_at',localNow(),'datetime-local','required')}${field('Full name','name',m.name,'text','required')}${field('Jira account ID','jira_id',m.jira_id,'text','required')}${select('Role','role',choices(['Dev','QA','TPM'],m.role))}<div id="member-single-team">${select('Team (developer)','team_id',opts(state.teams.filter(t=>!t.archived),m.team_id))}</div><div id="member-team-options"></div>${select('Country','country',opts(state.countries,m.country,'name','code'))}</div><div class="toolbar"><button class="primary" ${state.teams.length?'':'disabled'}>Save member</button><button type="button" data-cancel>Clear form</button></div>${state.teams.length?'':'<p class="muted">Create a team first.</p>'}</form>`)+panel('Member directory',`<div class="toolbar" aria-label="Member directory filters"><label>Search name or Jira ID<input id="admin-member-search" type="search" value="${esc(adminMemberFilters.query)}" placeholder="Search people…"></label><label>Role<select id="admin-member-role"><option value="">All roles</option>${choices(['Dev','QA','TPM'],adminMemberFilters.role)}</select></label><label>Team<select id="admin-member-team"><option value="">All teams</option>${opts(state.teams,adminMemberFilters.team)}</select></label><label>Country<select id="admin-member-country"><option value="">All countries</option>${opts(state.countries,adminMemberFilters.country,'name','code')}</select></label><button type="button" id="clear-admin-member-filters">Clear filters</button></div><p id="admin-member-count" class="muted" role="status"></p><div id="admin-member-directory"></div>`);
  }
  if(adminTab==='Members'){renderMemberAssignmentFields(edit||{role:'Dev'});renderAdminMemberDirectory();}
  if(adminTab==='Teams') b.innerHTML=panel('Create team',`<form id="team-form" class="form"><input name="id" type="hidden" value="${edit?.id||''}">${field('Team name','name',edit?.name||'','text','required')}<button class="primary">Create team</button></form>`)+state.teams.map(t=>panel(esc(t.name),`<p class="muted">Use Members to assign or move people.</p><div class="toolbar"><button data-edit-team="${t.id}">Rename team</button>${t.archived?`<span class="badge">Archived</span> <button data-reactivate-team="${t.id}">Reactivate</button>`:`<button data-archive-team="${t.id}">Archive empty team</button>`}</div>${['Dev','QA','TPM'].map(r=>`<div class="row"><span>${r}</span><span>${state.members.filter(m=>!m.archived&&memberInTeam(m,t.id)&&m.role===r).map(m=>esc(m.name)+(m.role==='QA'?' ('+memberAssignments(m).find(a=>a.team_id===t.id)?.qa_slot+')':'')).join(', ')||'Unassigned'}</span></div>`).join('')}`)).join('');
  if(adminTab==='Workflow rules') {
    const r=edit||{status:'In Progress',severity:'High',sp:3,days:2,initial:2,daily:1};
    b.innerHTML=panel('Duration & severity rule',`<form id="rule-form" class="form"><input name="id" type="hidden" value="${r.id||''}"><div class="fields">${field('Effective from (local time)','effective_at',localNow(),'datetime-local','required')}${select('Status (from Workflow)','status','<option value="">Choose status</option>'+opts(state.workflow,r.status,'name','name'),true)}${select('Severity (from Priority configuration)','severity','<option value="*" '+(r.severity==='*'?'selected':'')+'>All priorities</option>'+opts(state.priorities,r.severity,'name','name'),true)}<label><span>Story points</span><span><input type="checkbox" name="all_sp" ${r.sp===-1?'checked':''}> All story points</span><input name="sp" type="number" min="0" step="0.5" value="${r.sp===-1?'':r.sp}" ${r.sp===-1?'disabled':'required'}></label>${select('Working calendar','calendar',`<option value="country" ${r.calendar!=='mon_fri'?'selected':''}>Country calendar</option><option value="mon_fri" ${r.calendar==='mon_fri'?'selected':''}>Monday–Friday</option>`)}${field('Allowed working days','days',r.days,'number','min="0.5" step="0.5" required')}${field('Initial deduction','initial',r.initial,'number','min="0" required')}${field('Daily overdue deduction','daily',r.daily,'number','min="0" required')}</div><div class="toolbar"><button class="primary">Save rule</button><button type="button" data-cancel>Clear form</button></div><p class="muted">New rules apply prospectively. All-priority and all-story-point rules cover any value; more specific rules take precedence. Monday–Friday rules retain configured holidays. Rule versions preserve their effective dates. Finalized months change only through an explicit revision.</p></form>`)+panel('Configured rules',table(['Status','Severity','SP','Working days','Penalty',''],state.rules.map(r=>`<tr><td>${esc(r.status)}</td><td>${r.severity==='*'?'All':esc(r.severity)}</td><td>${r.sp===-1?'All':r.sp}</td><td>${r.days}</td><td>−${r.initial}, then −${r.daily}/day</td><td><button data-edit-rule="${r.id}">Edit</button></td></tr>`)))+panel('Rule calculator',`<form id="calc-form" class="form"><div class="fields">${select('Rule','rule',state.rules.map(r=>`<option value="${r.id}">${esc(r.status)} · ${r.severity==='*'?'All priorities':esc(r.severity)} · ${r.sp===-1?'All':r.sp} SP</option>`).join(''))}${field('Elapsed working days','elapsed',4,'number','min="0" step="0.5" required')}</div><button ${state.rules.length?'':'disabled'}>Calculate</button><div id="calc-result" class="rule-result" aria-live="polite"></div></form>`);
  }
  if(adminTab==='Calendars')b.innerHTML=state.countries.map(c=>panel(esc(c.name),`<form class="form calendar-form"><input type="hidden" name="code" value="${c.code}"><input type="hidden" name="name" value="${esc(c.name)}"><div class="fields"><fieldset><legend>Weekend days</legend><div class="weekdays">${['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map((d,i)=>`<label><input type="checkbox" name="weekend_day" value="${i}" ${JSON.parse(c.weekend).includes(i)?'checked':''}>${d}</label>`).join('')}</div></fieldset>${field('IANA timezone','timezone',c.timezone,'text','required')}</div><button>Save calendar</button></form>`)).join('')+panel('Add country holiday',`<form id="holiday-form" class="form"><input type="hidden" name="id" value="${edit?.id||''}"><div class="fields">${select('Country','country',opts(state.countries,edit?.country||'JO','name','code'))}${field('Date','day',edit?.day||today.toISOString().slice(0,10),'date','required')}${field('Through date (optional range)','end_day','','date')}${field('Holiday name','name',edit?.name||'','text','required')}</div><button class="primary">Add holiday</button></form>`)+panel('Configured holidays',table(['Country','Date','Name','Actions'],state.holidays.map(h=>`<tr><td>${esc(countryName(h.country))}</td><td>${h.day}</td><td>${esc(h.name)}</td><td><button data-edit-holiday="${h.id}">Edit</button><button data-remove-holiday="${h.id}">Remove</button></td></tr>`)));
  if(adminTab==='Targets')b.innerHTML=panel('Utilization & follow-up settings',`<form id="settings-form" class="form"><div class="fields">${field('Monthly SP target','monthly_target',state.settings.monthly_target,'number','min="1" required')}${field('Follow-up working days','followup_days',state.settings.followup_days,'number','min="1" required')}${field('Initial follow-up deduction','followup_initial',state.settings.followup_initial,'number','min="0" required')}${field('Additional daily deduction','followup_daily',state.settings.followup_daily,'number','min="0" required')}${field('Critical completion working days','critical_days',state.settings.critical_days,'number','min="0.5" step="0.5" required')}${field('Critical reward per owner','critical_reward',state.settings.critical_reward,'number','min="0" step="0.5" required')}</div>${field('Effective from (local time)','effective_at',localNow(),'datetime-local','required')}<button class="primary">Save settings</button></form>`)+panel('Backup','<p class="muted">Backups include SQLite data and original CSV contents. Automatic backups run before imports; 30 are retained.</p><button id="backup">Create backup now</button>');
}
function object(form){const d=Object.fromEntries(new FormData(form));if(d.id==='')delete d.id;return d;}
document.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;try {
  if(b.id==='recalculate'){const person=profileId,ticketId=ticketKey;b.disabled=true;announce('Recalculating live results…');state=await api('recalculate',{});stateDirty=false;updateDataStatus();if(person!==null)await profile(person);else if(ticketId)await ticket(ticketId);else if(page==='Administration')renderAdminMemberDirectory();else await render();announce('Calculations updated. Finalized monthly records are preserved; use Monthly records to create an explicit revision.');b.disabled=false;}
  if(b.id==='clear-people-filters'){peopleSearch='';peoplePosition='';$('#people-search').value='';$('#people-position').value='';updatePeopleFilters();}
  if(b.id==='clear-admin-member-filters'){adminMemberFilters={query:'',role:'',team:'',country:''};for(const id of ['search','role','team','country'])$('#admin-member-'+id).value='';renderAdminMemberDirectory();}
  if(b.dataset.range){
    activePreset=b.dataset.range;
    await render();
    announce(`${{month:'This month',quarter:'This quarter',year:'This year'}[activePreset]} to date: ${startDate} through ${endDate} (UTC). Delivery and targets use these dates; scores average the included monthly records.`);
  }
  if(b.dataset.page){page=b.dataset.page;edit=null;announce('');render();}
  if(b.dataset.admin){page='Administration';adminTab=b.dataset.admin;edit=null;render();}
  if(b.hasAttribute('data-profile-status')){profileTicketStatus=b.dataset.profileStatus;renderProfileTickets();}
  if(b.dataset.person)profile(Number(b.dataset.person));
  if(b.dataset.ticket)await ticket(b.dataset.ticket);
  if(b.hasAttribute('data-month')){profileMonth=Number(b.dataset.month);monthDetail();}
  if(b.dataset.tab){adminTab=b.dataset.tab;edit=null;renderAdmin();appendAdminHistory();}
  if(b.hasAttribute('data-cancel')){edit=null;renderAdmin();}
  if(b.dataset.editMember){edit=state.members.find(m=>m.id===Number(b.dataset.editMember));renderAdmin();}
  if(b.dataset.editRule){edit=state.rules.find(r=>r.id===Number(b.dataset.editRule));renderAdmin();}
  if(b.id==='commit-import'&&pendingImport){b.disabled=true;const r=await api('import/commit',pendingImport);pendingImport=null;importResult=null;await reload();render();announce(r.duplicate?'Snapshot already imported.':`Imported ${r.count} tickets. Preserved prior snapshots.`);}
  if(b.id==='backup'){const r=await api('backup',{});await reload();if(page==='Administration')renderAdmin();announce('Backup created in data/backups/'+r.filename);}
}catch(error){announce(error.message,true);b.disabled=false;}});
document.addEventListener('change',e=>{try {
  if(e.target.name==='all_sp'){const input=e.target.form.elements.namedItem('sp');input.disabled=e.target.checked;input.required=!e.target.checked;}
  const adminFilters={'admin-member-role':'role','admin-member-team':'team','admin-member-country':'country'};
  if(adminFilters[e.target.id]){adminMemberFilters[adminFilters[e.target.id]]=e.target.value;renderAdminMemberDirectory();}
  if(e.target.id==='start-date'||e.target.id==='end-date'){
    const a=$('#start-date').value,b=$('#end-date').value;
    if(!a||!b||a>b||b>today.toISOString().slice(0,10)){announce('Choose a valid start/end range ending no later than today.',true);return;}
    if(Number(b.slice(0,4))-Number(a.slice(0,4))>10){announce('Choose a range of at most 10 years.',true);return;}
    activePreset=null;startDate=a;endDate=b;announce('Partial months use a working-day target. Scores average full monthly records for the months included.');render();
  }
  if(e.target.id==='team'){team=e.target.value;render();}
  if(e.target.id==='country'){country=e.target.value;render();}
  if(e.target.closest('form')?.getAttribute('id')==='member-form'&&['role','assigned_team'].includes(e.target.name))updateMemberAssignmentRole();
  if(e.target.id==='profile-ticket-status'){profileTicketStatus=e.target.value;renderProfileTickets();}
  if(e.target.id==='profile-person')profile(Number(e.target.value));
  if(e.target.id==='profile-year'){profileYear=Math.min(today.getFullYear(),Math.max(2000,Number(e.target.value)));profile(profileId);}
  if(e.target.id==='profile-country'){country=e.target.value;const candidates=(profileRoster.length?profileRoster:state.members).filter(m=>(!m.archived||m.id===profileId)&&(!team||memberInTeam(m,team))&&(!country||m.country===country));if(candidates.length)profile(candidates[0].id);else{page='Members';render();}}
  if(e.target.id==='profile-month'){profileMonth=Number(e.target.value);monthDetail();}
  if(e.target.id==='rank-metric'){rankMetric=e.target.value;updatePeopleFilters();}
  if(e.target.id==='people-position'){peoplePosition=e.target.value;updatePeopleFilters();}
}catch(error){announce(error.message,true);}});
document.addEventListener('submit',async e=>{e.preventDefault();const form=e.target;const button=form.querySelector('button[type=submit],button:not([type])');if(button)button.disabled=true;try {
  const d=object(form);let resource;
  if(form.getAttribute('id')==='import-form') {
    const file=$('#csv-file').files[0];if(!file)throw new Error('Select a CSV file');
    if(file.size>15*1024*1024)throw new Error('CSV exceeds 15 MB');
    const mapping={};Object.entries(d).forEach(([k,v])=>{if(k.startsWith('map_')&&v.trim())mapping[k.slice(4)]=v.trim();});
    pendingImport={csv:new TextDecoder(d.csv_encoding||'utf-8',{fatal:true}).decode(await file.arrayBuffer()),filename:file.name,snapshot_at:new Date(d.snapshot_at).toISOString(),mapping};importResult=await api('import/preview',pendingImport);renderImport();return;
  }
  if(form.getAttribute('id')==='calc-form'){const r=state.rules.find(r=>r.id===Number(d.rule)),over=Number(d.elapsed)-r.days;$('#calc-result').textContent=(over>0?r.initial+Math.max(0,Math.ceil(over)-1)*r.daily:0)+' score points deducted per accountable person';return;}
  if(form.classList.contains('comment-revision-form')){d.id=Number(d.id);d.occurred_at=new Date(d.occurred_at).toISOString();await api('comments/revise',d);await reload();await ticket(ticketKey);announce('Comment revision saved; original entry retained.');return;}
  if(form.getAttribute('id')==='comment-form'){d.ticket_key=ticketKey;d.author_id=Number(d.author_id);d.occurred_at=new Date(d.occurred_at).toISOString();await api('comments',d);await reload();await ticket(ticketKey);announce('Follow-up saved.');return;}
  if(d.effective_at)d.effective_at=new Date(d.effective_at).toISOString();
  if(form.getAttribute('id')==='member-form'){resource='members';d.team_id=Number(d.team_id);if(d.role!=='Dev'){d.team_assignments=[...form.querySelectorAll('[name=assigned_team]:checked')].map(input=>({team_id:Number(input.value),qa_slot:d.role==='QA'?form.elements.namedItem('qa_slot_'+input.value).value:null}));}delete d.assigned_team;Object.keys(d).filter(k=>k.startsWith('qa_slot_')).forEach(k=>delete d[k]);}
  if(form.getAttribute('id')==='team-form')resource='teams';
  if(form.getAttribute('id')==='rule-form'){resource='rules';if(d.all_sp)d.sp=-1;delete d.all_sp;}
  if(form.getAttribute('id')==='holiday-form')resource='holidays';
  if(form.classList.contains('calendar-form')){resource='countries';d.weekend=JSON.stringify(new FormData(form).getAll('weekend_day').map(Number));delete d.weekend_day;}
  if(form.getAttribute('id')==='settings-form')await api('settings',Object.fromEntries(Object.entries(d).map(([k,v])=>[k,k==='effective_at'?new Date(v).toISOString():Number(v)])));
  else if(resource)await api('save/'+resource,d);
  else return;
  edit=null;await reload();render();announce('Saved to your local database.');
}catch(error){announce(error.message,true);}finally{if(button)button.disabled=false;}});
