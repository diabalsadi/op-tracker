'use strict';
const $ = s => document.querySelector(s);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pages = ['Overview','Delivery','Utilization','Performance','Rankings','Members','Tickets','Imports','Administration'];
const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
let today = new Date();
let activePreset='month';
let state, page = 'Overview', period = today.toISOString().slice(0,7), team = '', country = '', adminTab = 'Members';
let startDate = period+'-01', endDate = today.toISOString().slice(0,10);
let profileTicketStatus = '';
let charts = [], profileId = null, profileYear = today.getFullYear(), profileMonth = today.getMonth(), ticketKey = null;
let reportData=null,profileData=null,profileRoster=[],renderSequence=0,rankingScope='Individual';
let pendingImport = null, importResult = null, edit = null, rankMetric = 'score', rankRole = '';
const countryName = code => state.countries.find(c => c.code === code)?.name || code;
const teamName = id => state.teams.find(t => t.id === Number(id))?.name || 'Unmapped';
const memberName = id => state.members.find(m => m.id === Number(id))?.name || 'Unmapped';
const opts = (xs, value, label='name', key='id') => xs.map(x => `<option value="${esc(x[key])}" ${String(x[key]) === String(value) ? 'selected' : ''}>${esc(x[label])}</option>`).join('');
const choices = (xs, value) => xs.map(x => `<option ${x === value ? 'selected' : ''}>${esc(x)}</option>`).join('');
const panel = (title, body) => `<section class="panel"><h2>${title}</h2>${body}</section>`;
const link = (text, attr) => `<button type="button" class="link" ${attr}>${esc(text)}</button>`;
const fmt = n => n === null || n === undefined || !Number.isFinite(n) ? 'N/A' : Number(n.toFixed(1)).toLocaleString();
const dateLabel = d => d ? new Date(d).toLocaleString() : 'Unknown timestamp';
const getMembers = () => reportData?.members || state.members.filter(m => !m.archived && (!team || m.team_id === Number(team)) && (!country || m.country === country));
const getTickets = () => state.tickets.filter(t => (!team || t.team_id === Number(team)) && (!country || state.members.find(m => m.id === t.member_id)?.country === country));
const monthOf = at => at?.slice(0,7);
function announce(text, error=false) { $('#notice').className = error ? 'notice error' : 'notice'; $('#notice').textContent = text; }
async function api(path, data) {
  const response = await fetch('/api/'+path, data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Request failed');
  return result;
}
async function reload() { state = await api('state');const badge=$('#data-status');badge.className='badge'+(state.stale_days>1?' warning':'');badge.textContent=state.stale_days===null?'No imports yet':state.stale_days>1?'Data '+state.stale_days+' days old · Upload today’s snapshot':'Daily data · Latest snapshot '+state.imports[0].snapshot_at.slice(0,10); }
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
function memberTable(ms) { return table(['Member','Role / team','Country','Done SP','Utilization','Score'],ms.map(m=>{const v=metric(m);return `<tr><td>${link(m.name,`data-person="${m.id}"`)}</td><td>${esc(m.role)} · ${esc(teamName(m.team_id))}</td><td>${esc(countryName(m.country))}</td><td>${v.target>0?fmt(v.sp):'N/A'}</td><td>${v.util===null?'N/A':fmt(v.util)+'%'}</td><td>${fmt(v.score)}</td></tr>`;})); }
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
  try {reportData=await api('report?'+new URLSearchParams({start_date:startDate,end_date:endDate,...(team?{team_id:team}:{}),...(country?{country}:{} )}));}catch(error){announce(error.message,true);return;}
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
  const stats=`<div class="grid">${[['Delivered SP',fmt(sum),fmt(totalTarget)+' SP target · Selected dates'],['Dev utilization',totalTarget?fmt(sum/totalTarget*100)+'%':'N/A',dev.length+' developers'],['Average score',fmt(avg),'Average of monthly scores · Selected months']].map(([l,v,n])=>`<div class="panel"><div class="muted">${l}</div><strong class="value">${v}</strong><div class="muted">${n}</div></div>`).join('')}</div>`;
  const content=$('#content');
  if(page==='Overview') {
    content.innerHTML=stats+`<div class="columns">${chartBox('delivery-chart','Developer delivery · Selected dates')}${chartBox('workflow-chart','Current workflow snapshot','Click a status to open its tickets. This chart shows latest observed state, not a historical month-end snapshot.')}</div>`+panel('Recent tickets',ticketsTable(ts))+panel('Data quality',`<p class="muted">${esc(state.calculation_note)}</p>${state.warnings.slice(0,12).map(w=>`<div class="row">${esc(w)}</div>`).join('')||'<p class="muted">No unresolved data warnings.</p>'}`);
    draw('delivery-chart','bar',dev.map(m=>m.name),[series('Done SP',dev.map(m=>metric(m).sp)),{...series('Period target',dev.map(rangeTarget),'#cad8d0','line'),borderDash:[5,5]}],'Story points',i=>profile(dev[i].id),'Developer');
    const statuses=[...new Set(ts.map(t=>t.status))]; draw('workflow-chart','bar',statuses,[series('Tickets',statuses.map(s=>ts.filter(t=>t.status===s).length))],'Ticket count',i=>{page='Tickets';render();$('#content').innerHTML=panel(statuses[i],ticketsTable(ts.filter(t=>t.status===statuses[i])));},'Status');
  }
  if(page==='Delivery'||page==='Utilization') {
    content.innerHTML=stats+chartBox('util-chart',page==='Delivery'?'Completed story points by developer':'Developer utilization vs 100% target','Click a bar to inspect the developer’s yearly history.')+panel('Developer records',memberTable(dev));
    const utilization=page==='Utilization';draw('util-chart','bar',dev.map(m=>m.name),[series(utilization?'Utilization (%)':'Done SP',dev.map(m=>utilization?metric(m).util:metric(m).sp)),{...series('Target',dev.map(m=>utilization?100:rangeTarget(m)),'#cad8d0','line'),borderDash:[5,5]}],utilization?'Utilization (%)':'Story points',i=>profile(dev[i].id),'Developer');
  }
  if(page==='Performance'||page==='Rankings') {
    let rows=ms;
    if(page==='Rankings')rows=rows.filter(m=>(!rankRole||m.role===rankRole)&&(rankMetric==='score'||m.role==='Dev')).sort((a,b)=>metric(b)[rankMetric]-metric(a)[rankMetric]);
    content.innerHTML=(page==='Rankings'?`<div class="toolbar"><label>Rank by<select id="rank-metric"><option value="score" ${rankMetric==='score'?'selected':''}>Performance score</option><option value="util" ${rankMetric==='util'?'selected':''}>Developer utilization</option></select></label><label>Role<select id="rank-role"><option value="">All roles</option>${choices(['Dev','QA','TPM'],rankRole)}</select></label></div>`:stats)+chartBox('score-chart','Member comparison','Click a bar to open the annual person dashboard.')+panel('Monthly performance',memberTable(rows));
    draw('score-chart','bar',rows.map(m=>m.name),[series(page==='Rankings'&&rankMetric==='util'?'Utilization (%)':'Score',rows.map(m=>metric(m)[page==='Rankings'?rankMetric:'score']))],page==='Rankings'&&rankMetric==='util'?'Utilization (%)':'Score points',i=>profile(rows[i].id),'Member');
  }
  if(page==='Members')content.innerHTML=panel('Team members',memberTable(ms))+`<button class="primary" data-admin="Members">Manage members & assignments</button>`;
  if(page==='Tickets')content.innerHTML=panel('Ticket explorer',ticketsTable(ts));
  if(page==='Rankings')renderRankings().catch(e=>announce(e.message,true));
  if(page==='Delivery')renderDurations();
  if(page==='Imports')renderImport();
  if(page==='Administration'){renderAdmin();appendAdminHistory();}
}
async function profile(id) {
  const seq=++renderSequence;
  const end=profileYear===today.getFullYear()?today.toISOString().slice(0,10):`${profileYear}-12-31`;
  let report;
  try{report=await api('report?'+new URLSearchParams({start_date:profileYear+'-01-01',end_date:end}));}catch(error){announce(error.message,true);return;}
  if(seq!==renderSequence)return;
  profileRoster=report.members;profileData=report.members.find(m=>m.id===Number(id))||null;

  if(profileId!==Number(id))profileTicketStatus='';
  destroyCharts();profileId=Number(id);ticketKey=null;const m=profileData||state.members.find(m=>m.id===profileId); if(!m)return;
  $('#title').textContent=m.name;$('#subtitle').textContent=`${m.role} · ${teamName(m.team_id)} · ${countryName(m.country)}`;$('#filters').hidden=true;
  const rows=months.map((name,i)=>{const key=`${profileYear}-${String(i+1).padStart(2,'0')}`,future=key>today.toISOString().slice(0,7);return {name,key,future,...metric(m,key)};});
  const hasDevHistory=rows.some(r=>r.target>0);
  const valid=rows.filter(r=>!r.future&&r.eligible),sp=valid.reduce((a,r)=>a+r.sp,0),score=valid.length?valid.reduce((a,r)=>a+r.score,0)/valid.length:null;
  $('#content').innerHTML=link('← Back to members','data-page="Members"')+`<div class="toolbar"><label>Person<select id="profile-person">${opts((profileRoster.length?profileRoster:state.members).filter(x=>(!country||x.country===country)&&(!team||x.team_id===Number(team))),m.id)}</select></label><label>Year<input type="number" id="profile-year" min="2000" max="${today.getFullYear()}" value="${profileYear}"></label><label>Country<select id="profile-country"><option value="">All countries</option>${opts(state.countries,country,'name','code')}</select></label></div><div id="profile-tickets"></div><div class="grid"><div class="panel"><div class="muted">${hasDevHistory?'Delivered SP':'Role'}</div><strong class="value">${hasDevHistory?fmt(sp):m.role}</strong><div class="muted">${profileYear} · Recorded period</div></div><div class="panel"><div class="muted">Average monthly score</div><strong class="value">${fmt(score)}</strong><div class="muted">${valid.length} active months · Finalized records preserved</div></div><div class="panel"><div class="muted">${hasDevHistory?'Period utilization':'Critical rewards'}</div><strong class="value">${hasDevHistory?(profileData?.util===null||profileData?.util===undefined?'N/A':fmt(profileData.util)+'%'):fmt(valid.reduce((a,r)=>a+r.critical,0))}</strong><div class="muted">${hasDevHistory?fmt(profileData?.target)+' SP target through selected year-end / today':'Performance only; no utilization target'}</div></div></div>`+(hasDevHistory?chartBox('year-delivery','Monthly delivery and target')+chartBox('year-util','Monthly utilization (%)'):'')+chartBox('year-score','Monthly performance score','Click a month for its detailed breakdown.')+`<div id="month-detail"></div>`+panel('Monthly records',table(['Month','Done SP','Utilization','Bonus','Deductions','Score'],rows.map((r,i)=>`<tr><td>${link(r.name,`data-month="${i}"`)}</td><td>${r.future?'—':hasDevHistory?fmt(r.sp):'N/A'}</td><td>${r.future?'—':hasDevHistory?fmt(r.util)+'%':'N/A'}</td><td>${r.future?'—':fmt(r.bonus+r.critical)}</td><td>${r.future?'—':fmt(r.penalties)}</td><td>${r.future?'Future':fmt(r.score)+' · '+r.record_status}</td></tr>`)));
  const pick=i=>{profileMonth=i;monthDetail();},data=key=>rows.map(r=>r.future||!r.eligible?null:r[key]);
  if(hasDevHistory) {
    draw('year-delivery','bar',months,[series('Done SP',data('sp')),{...series('Target SP',rows.map(r=>r.future||!r.eligible?null:r.target),'#cad8d0','line'),borderDash:[5,5]}],'Story points',pick);
    draw('year-util','line',months,[series('Utilization (%)',data('util'),'#66d1a3','line'),{...series('Target (%)',rows.map(r=>r.future||!r.eligible?null:100),'#cad8d0','line'),borderDash:[5,5]}],'Utilization (%)',pick);
  }
  draw('year-score','line',months,[series('Score',data('score'),'#66d1a3','line'),{...series('Baseline',rows.map(r=>r.future||!r.eligible?null:100),'#cad8d0','line'),borderDash:[5,5]}],'Score points',pick);monthDetail();renderProfileTickets();
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
  $('#month-detail').innerHTML=panel(months[profileMonth]+' '+profileYear,`<div class="toolbar"><label>Inspect month<select id="profile-month">${months.map((m,i)=>`<option value="${i}" ${profileMonth===i?'selected':''}>${m}</option>`).join('')}</select></label></div>`+(key>today.toISOString().slice(0,7)?'<div class="empty">Future month · No records.</div>':`<div class="columns"><div>${[['Baseline',100],['Utilization bonus',v.bonus],['Critical rewards',v.critical],['Delay deductions',-v.penalties],['Monthly score',v.score]].map(([l,n])=>`<div class="row"><span>${l}</span><strong>${fmt(n)}</strong></div>`).join('')}</div><div><h3>Delivery credits</h3>${v.credits.map(c=>`<div class="row">${link(c.key,`data-ticket="${esc(c.key)}"`)}<span>${c.sp} SP</span></div>`).join('')||'<p class="muted">No completion credits.</p>'}<h3>Score events</h3>${v.events.map(e=>`<div class="row"><div>${link(e.key,`data-ticket="${esc(e.key)}"`)}<p class="muted">${esc(e.reason)} · ${dateLabel(e.at)}</p></div><span>${e.points>0?'+':''}${e.points}</span></div>`).join('')||'<p class="muted">No score events.</p>'}</div></div>`));
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
function select(label,name,options){return `<label>${label}<select name="${name}">${options}</select></label>`;}
function renderAdmin() {
  $('#content').innerHTML=`<div class="tabs" aria-label="Administration sections">${['Members','Teams','Workflow rules','Workflow','Sprints','Calendars','Targets','Monthly records','Backup & restore'].map(t=>`<button data-tab="${t}" aria-pressed="${adminTab===t}">${t}</button>`).join('')}</div><div id="admin-body"></div>`;
  const b=$('#admin-body');
  if(['Workflow','Sprints','Monthly records','Backup & restore'].includes(adminTab)){renderExtraAdmin(b);return;}
  if(adminTab==='Members') {
    const m=edit||{country:'JO',role:'Dev',qa_slot:'Primary'};
    b.innerHTML=panel(edit?'Edit member':'Add member',`<form id="member-form" class="form"><input type="hidden" name="id" value="${m.id||''}"><div class="fields">${field('Effective from (local time)','effective_at',localNow(),'datetime-local','required')}${field('Full name','name',m.name,'text','required')}${field('Jira account ID','jira_id',m.jira_id,'text','required')}${select('Role','role',choices(['Dev','QA','TPM'],m.role))}${select('Team','team_id',opts(state.teams,m.team_id))}${select('Country','country',opts(state.countries,m.country,'name','code'))}${select('QA position (QA only)','qa_slot',choices(['Primary','Secondary'],m.qa_slot))}</div><div class="toolbar"><button class="primary" ${state.teams.length?'':'disabled'}>Save member</button><button type="button" data-cancel>Clear form</button></div>${state.teams.length?'':'<p class="muted">Create a team first.</p>'}</form>`)+panel('Member directory',table(['Name / Jira ID','Role','Country','Team',''],state.members.map(m=>`<tr><td>${esc(m.name)}<div class="muted">${esc(m.jira_id)}</div></td><td>${m.role}${m.qa_slot?' · '+m.qa_slot:''}</td><td>${esc(countryName(m.country))}</td><td>${esc(teamName(m.team_id))}</td><td><button data-edit-member="${m.id}">Edit</button> ${m.archived?`<span class="badge">Archived</span> <button data-reactivate-member="${m.id}">Reactivate</button>`:`<button data-archive-member="${m.id}">Archive</button>`}</td></tr>`)));
  }
  if(adminTab==='Teams') b.innerHTML=panel('Create team',`<form id="team-form" class="form"><input name="id" type="hidden" value="${edit?.id||''}">${field('Team name','name',edit?.name||'','text','required')}<button class="primary">Create team</button></form>`)+state.teams.map(t=>panel(esc(t.name),`<p class="muted">Use Members to assign or move people.</p><div class="toolbar"><button data-edit-team="${t.id}">Rename team</button>${t.archived?`<span class="badge">Archived</span> <button data-reactivate-team="${t.id}">Reactivate</button>`:`<button data-archive-team="${t.id}">Archive empty team</button>`}</div>${['Dev','QA','TPM'].map(r=>`<div class="row"><span>${r}</span><span>${state.members.filter(m=>m.team_id===t.id&&m.role===r).map(m=>esc(m.name)+(m.qa_slot?' ('+m.qa_slot+')':'')).join(', ')||'Unassigned'}</span></div>`).join('')}`)).join('');
  if(adminTab==='Workflow rules') {
    const r=edit||{status:'In Progress',severity:'High',sp:3,days:2,initial:2,daily:1};
    b.innerHTML=panel('Duration & severity rule',`<form id="rule-form" class="form"><input name="id" type="hidden" value="${r.id||''}"><div class="fields">${field('Effective from (local time)','effective_at',localNow(),'datetime-local','required')}${field('Status (exact Jira status)','status',r.status,'text','required list="workflow-statuses"')}<datalist id="workflow-statuses">${['To Do','In Progress','Code Review','QA','Ready for Release',...new Set(state.tickets.map(t=>t.status))].map(s=>`<option value="${esc(s)}"></option>`).join('')}</datalist>${field('Severity (exact Jira priority)','severity',r.severity,'text','required')}${field('Story points','sp',r.sp,'number','min="0" step="0.5" required')}${field('Allowed working days','days',r.days,'number','min="0.5" step="0.5" required')}${field('Initial deduction','initial',r.initial,'number','min="0" required')}${field('Daily overdue deduction','daily',r.daily,'number','min="0" required')}</div><div class="toolbar"><button class="primary">Save rule</button><button type="button" data-cancel>Clear form</button></div><p class="muted">New rules apply prospectively. Missing exact status/severity/SP matches are flagged, never guessed. Rule versions preserve their effective dates. Finalized months change only through an explicit revision.</p></form>`)+panel('Configured rules',table(['Status','Severity','SP','Working days','Penalty',''],state.rules.map(r=>`<tr><td>${esc(r.status)}</td><td>${esc(r.severity)}</td><td>${r.sp}</td><td>${r.days}</td><td>−${r.initial}, then −${r.daily}/day</td><td><button data-edit-rule="${r.id}">Edit</button></td></tr>`)))+panel('Rule calculator',`<form id="calc-form" class="form"><div class="fields">${select('Rule','rule',state.rules.map(r=>`<option value="${r.id}">${esc(r.status)} · ${esc(r.severity)} · ${r.sp} SP</option>`).join(''))}${field('Elapsed working days','elapsed',4,'number','min="0" step="0.5" required')}</div><button ${state.rules.length?'':'disabled'}>Calculate</button><div id="calc-result" class="rule-result" aria-live="polite"></div></form>`);
  }
  if(adminTab==='Calendars')b.innerHTML=state.countries.map(c=>panel(esc(c.name),`<form class="form calendar-form"><input type="hidden" name="code" value="${c.code}"><input type="hidden" name="name" value="${esc(c.name)}"><div class="fields"><fieldset><legend>Weekend days</legend><div class="weekdays">${['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map((d,i)=>`<label><input type="checkbox" name="weekend_day" value="${i}" ${JSON.parse(c.weekend).includes(i)?'checked':''}>${d}</label>`).join('')}</div></fieldset>${field('IANA timezone','timezone',c.timezone,'text','required')}</div><button>Save calendar</button></form>`)).join('')+panel('Add country holiday',`<form id="holiday-form" class="form"><input type="hidden" name="id" value="${edit?.id||''}"><div class="fields">${select('Country','country',opts(state.countries,edit?.country||'JO','name','code'))}${field('Date','day',edit?.day||today.toISOString().slice(0,10),'date','required')}${field('Through date (optional range)','end_day','','date')}${field('Holiday name','name',edit?.name||'','text','required')}</div><button class="primary">Add holiday</button></form>`)+panel('Configured holidays',table(['Country','Date','Name','Actions'],state.holidays.map(h=>`<tr><td>${esc(countryName(h.country))}</td><td>${h.day}</td><td>${esc(h.name)}</td><td><button data-edit-holiday="${h.id}">Edit</button><button data-remove-holiday="${h.id}">Remove</button></td></tr>`)));
  if(adminTab==='Targets')b.innerHTML=panel('Utilization & follow-up settings',`<form id="settings-form" class="form"><div class="fields">${field('Monthly SP target','monthly_target',state.settings.monthly_target,'number','min="1" required')}${field('Follow-up working days','followup_days',state.settings.followup_days,'number','min="1" required')}${field('Initial follow-up deduction','followup_initial',state.settings.followup_initial,'number','min="0" required')}${field('Additional daily deduction','followup_daily',state.settings.followup_daily,'number','min="0" required')}${field('Critical completion working days','critical_days',state.settings.critical_days,'number','min="0.5" step="0.5" required')}${field('Critical reward per owner','critical_reward',state.settings.critical_reward,'number','min="0" step="0.5" required')}</div>${field('Effective from (local time)','effective_at',localNow(),'datetime-local','required')}<button class="primary">Save settings</button></form>`)+panel('Backup','<p class="muted">Backups include SQLite data and original CSV contents. Automatic backups run before imports; 30 are retained.</p><button id="backup">Create backup now</button>');
}
function object(form){const d=Object.fromEntries(new FormData(form));if(d.id==='')delete d.id;return d;}
document.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;try {
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
  if(e.target.id==='start-date'||e.target.id==='end-date'){
    const a=$('#start-date').value,b=$('#end-date').value;
    if(!a||!b||a>b||b>today.toISOString().slice(0,10)){announce('Choose a valid start/end range ending no later than today.',true);return;}
    if(Number(b.slice(0,4))-Number(a.slice(0,4))>10){announce('Choose a range of at most 10 years.',true);return;}
    activePreset=null;startDate=a;endDate=b;announce('Partial months use a working-day target. Scores average full monthly records for the months included.');render();
  }
  if(e.target.id==='team'){team=e.target.value;render();}
  if(e.target.id==='country'){country=e.target.value;render();}
  if(e.target.id==='profile-ticket-status'){profileTicketStatus=e.target.value;renderProfileTickets();}
  if(e.target.id==='profile-person')profile(Number(e.target.value));
  if(e.target.id==='profile-year'){profileYear=Math.min(today.getFullYear(),Math.max(2000,Number(e.target.value)));profile(profileId);}
  if(e.target.id==='profile-country'){country=e.target.value;const candidates=(profileRoster.length?profileRoster:state.members).filter(m=>(!m.archived||m.id===profileId)&&(!team||m.team_id===Number(team))&&(!country||m.country===country));if(candidates.length)profile(candidates[0].id);else{page='Members';render();}}
  if(e.target.id==='profile-month'){profileMonth=Number(e.target.value);monthDetail();}
  if(e.target.id==='rank-metric'){rankMetric=e.target.value;render();}
  if(e.target.id==='rank-role'){rankRole=e.target.value;render();}
}catch(error){announce(error.message,true);}});
document.addEventListener('submit',async e=>{e.preventDefault();const form=e.target;const button=form.querySelector('button[type=submit],button:not([type])');if(button)button.disabled=true;try {
  const d=object(form);let resource;
  if(form.getAttribute('id')==='import-form') {
    const file=$('#csv-file').files[0];if(!file)throw new Error('Select a CSV file');
    if(file.size>15*1024*1024)throw new Error('CSV exceeds 15 MB');
    const mapping={};Object.entries(d).forEach(([k,v])=>{if(k.startsWith('map_')&&v.trim())mapping[k.slice(4)]=v.trim();});
    pendingImport={csv:new TextDecoder(d.csv_encoding||'utf-8',{fatal:true}).decode(await file.arrayBuffer()),filename:file.name,snapshot_at:new Date(d.snapshot_at).toISOString(),mapping};importResult=await api('import/preview',pendingImport);renderImport();return;
  }
  if(form.getAttribute('id')==='calc-form'){const r=state.rules.find(r=>r.id===Number(d.rule)),over=Number(d.elapsed)-r.days;$('#calc-result').textContent=(over>0?r.initial+Math.floor(over)*r.daily:0)+' score points deducted per accountable person';return;}
  if(form.classList.contains('comment-revision-form')){d.id=Number(d.id);d.occurred_at=new Date(d.occurred_at).toISOString();await api('comments/revise',d);await reload();await ticket(ticketKey);announce('Comment revision saved; original entry retained.');return;}
  if(form.getAttribute('id')==='comment-form'){d.ticket_key=ticketKey;d.author_id=Number(d.author_id);d.occurred_at=new Date(d.occurred_at).toISOString();await api('comments',d);await reload();await ticket(ticketKey);announce('Follow-up saved.');return;}
  if(d.effective_at)d.effective_at=new Date(d.effective_at).toISOString();
  if(form.getAttribute('id')==='member-form'){resource='members';d.team_id=Number(d.team_id);}
  if(form.getAttribute('id')==='team-form')resource='teams';
  if(form.getAttribute('id')==='rule-form')resource='rules';
  if(form.getAttribute('id')==='holiday-form')resource='holidays';
  if(form.classList.contains('calendar-form')){resource='countries';d.weekend=JSON.stringify(new FormData(form).getAll('weekend_day').map(Number));delete d.weekend_day;}
  if(form.getAttribute('id')==='settings-form')await api('settings',Object.fromEntries(Object.entries(d).map(([k,v])=>[k,k==='effective_at'?new Date(v).toISOString():Number(v)])));
  else if(resource)await api('save/'+resource,d);
  else return;
  edit=null;await reload();render();announce('Saved to your local database.');
}catch(error){announce(error.message,true);}finally{if(button)button.disabled=false;}});
