"""Versioned configuration, historical reporting, finalized records and administration."""
import io
import csv
import json
import math
import sqlite3
import copy
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from tracker import Tracker as BaseTracker, now, timestamp


class Tracker(BaseTracker):
    def __init__(self, path=None):
        if path is None:
            super().__init__()
        else:
            super().__init__(path)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS member_versions(id INTEGER PRIMARY KEY,member_id INTEGER NOT NULL REFERENCES members(id),effective_at TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(member_id,effective_at));
        CREATE TABLE IF NOT EXISTS rule_versions(id INTEGER PRIMARY KEY,rule_id INTEGER NOT NULL REFERENCES rules(id),effective_at TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(rule_id,effective_at));
        CREATE TABLE IF NOT EXISTS policy_versions(id INTEGER PRIMARY KEY,effective_at TEXT NOT NULL UNIQUE,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS workflow(name TEXT PRIMARY KEY,category TEXT NOT NULL,roles TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sprints(id INTEGER PRIMARY KEY,name TEXT NOT NULL,start_date TEXT NOT NULL,end_date TEXT NOT NULL,team_id INTEGER REFERENCES teams(id));
        CREATE TABLE IF NOT EXISTS import_profiles(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE,mapping TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS corrections(id INTEGER PRIMARY KEY,ticket_key TEXT NOT NULL,effective_at TEXT NOT NULL,patch TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS monthly_records(id INTEGER PRIMARY KEY,member_id INTEGER NOT NULL REFERENCES members(id),month TEXT NOT NULL,revision INTEGER NOT NULL,payload TEXT NOT NULL,finalized_at TEXT NOT NULL,reason TEXT NOT NULL,UNIQUE(member_id,month,revision));
        CREATE TABLE IF NOT EXISTS status_id_mappings(status_id TEXT PRIMARY KEY,status_name TEXT NOT NULL,unit TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS critical_priorities(name TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS comment_revisions(id INTEGER PRIMARY KEY,comment_id INTEGER NOT NULL REFERENCES manual_comments(id),body TEXT NOT NULL,occurred_at TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL);
        ''')
        with self.db:
            for table in ('members', 'teams'):
                cols = {r['name'] for r in self.rows(f'PRAGMA table_info({table})')}
                if 'archived' not in cols:
                    self.db.execute(f'ALTER TABLE {table} ADD COLUMN archived INTEGER NOT NULL DEFAULT 0')
            self.db.execute('DROP INDEX IF EXISTS one_tpm')
            self.db.execute('DROP INDEX IF EXISTS one_qa_slot')
            self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS active_tpm ON members(team_id) WHERE role='TPM' AND archived=0")
            self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS active_qa ON members(team_id,qa_slot) WHERE role='QA' AND archived=0")
            for m in self.rows('SELECT * FROM members'):
                if not self.rows('SELECT id FROM member_versions WHERE member_id=?', (m['id'],)):
                    self.db.execute('INSERT INTO member_versions(member_id,effective_at,payload) VALUES(?,?,?)', (m['id'], '1900-01-01T00:00:00+00:00', json.dumps(m)))
            for r in self.rows('SELECT * FROM rules'):
                if not self.rows('SELECT id FROM rule_versions WHERE rule_id=?', (r['id'],)):
                    self.db.execute('INSERT INTO rule_versions(rule_id,effective_at,payload) VALUES(?,?,?)', (r['id'], r['created_at'], json.dumps(r)))
            if not self.rows('SELECT id FROM policy_versions'):
                self.db.execute('INSERT INTO policy_versions(effective_at,payload) VALUES(?,?)', ('1900-01-01T00:00:00+00:00', json.dumps(self.settings())))
            self.db.executemany('INSERT OR IGNORE INTO workflow VALUES(?,?,?)', [
                ('To Do','active','["Dev","TPM"]'),('In Progress','active','["Dev","TPM"]'),
                ('Code Review','active','["Dev","TPM"]'),('QA','active','["Dev","QA","TPM"]'),
                ('Ready for Release','active','["QA","TPM"]'),('Blocked','paused','["Dev","TPM"]'),
                ('On Hold','paused','["Dev","TPM"]'),('Done','done','[]'),('Closed','done','[]'),('Cancelled','cancelled','[]')])
            if not self.rows('SELECT name FROM critical_priorities'):
                self.db.execute("INSERT INTO critical_priorities VALUES('Critical')")

    def members_at(self, at):
        result = {}
        for row in self.rows('SELECT * FROM member_versions WHERE effective_at<=? ORDER BY effective_at,id', (at,)):
            m = json.loads(row['payload'])
            result[m['id']] = m
        return [m for m in result.values() if not m.get('archived')]

    def workflow_at(self, status):
        rows = self.rows('SELECT * FROM workflow WHERE lower(name)=lower(?)', (status,))
        return rows[0] if rows else {'name': status, 'category': 'active', 'roles': '["Dev","TPM"]'}

    def is_critical(self,severity):
        return bool(self.rows('SELECT name FROM critical_priorities WHERE lower(name)=lower(?)',(severity,)))

    def rules_at(self, status, severity, sp, at):
        versions = {}
        for row in self.rows('SELECT * FROM rule_versions WHERE effective_at<=? ORDER BY effective_at,id', (at,)):
            rule = json.loads(row['payload'])
            rule['version_id'] = row['id']
            versions[rule['id']] = rule
        return [r for r in versions.values() if r['status'].casefold() == status.casefold() and r['severity'].casefold() == severity.casefold() and r['sp'] == sp]

    def policy_at(self, at):
        rows = self.rows('SELECT * FROM policy_versions WHERE effective_at<=? ORDER BY effective_at DESC,id DESC LIMIT 1', (at,))
        return json.loads(rows[0]['payload']) if rows else self.settings()

    def save(self, kind, data):
        if kind in ('sprints', 'import_profiles', 'workflow','status_id_mappings','critical_priorities'):
            return self.save_extra(kind, data)
        if kind=='holidays' and data.get('end_day') and data['end_day']!=data['day']:
            self._day_cache={};self._work_cache={}
            first,last=date.fromisoformat(data['day']),date.fromisoformat(data['end_day'])
            if first>last or (last-first).days>366 or data.get('id'):
                raise ValueError('Use a range of up to 366 days for new holidays; edit existing dates individually')
            dates=[first+timedelta(days=n) for n in range((last-first).days+1)]
            if any(self.rows('SELECT id FROM holidays WHERE country=? AND day=?',(data['country'],d.isoformat())) for d in dates):
                raise ValueError('The range overlaps an existing holiday; edit the existing dates first')
            with self.db:
                self.db.executemany('INSERT INTO holidays(country,day,name) VALUES(?,?,?)',[(data['country'],d.isoformat(),data['name']) for d in dates])
                self.audit('holiday_range',data)
            return len(dates)
        effective = timestamp(data.get('effective_at') or now())
        identity = data.get('id')
        if kind in ('members', 'rules') and identity:
            table, column = ('member_versions','member_id') if kind == 'members' else ('rule_versions','rule_id')
            last = self.rows(f'SELECT effective_at FROM {table} WHERE {column}=? ORDER BY effective_at DESC LIMIT 1', (identity,))
            if last and effective <= last[0]['effective_at']:
                raise ValueError('Effective time must be after the previous version. Use ticket corrections for evidence repairs.')
        if effective > now():
            raise ValueError('Future-dated configuration is not supported; save when it becomes effective')
        if kind == 'members' and data.get('team_id'):
            team = self.rows('SELECT archived FROM teams WHERE id=?', (data['team_id'],))
            if not team or team[0]['archived']:
                raise ValueError('Choose an active team')
            # Revalidate role slots at the effective date, not only against current members.
            for m in self.members_at(effective):
                if m['id'] != int(identity or 0) and m['team_id'] == int(data['team_id']) and m['role'] == data['role'] and (m['role'] == 'TPM' or m['role'] == 'QA' and m['qa_slot'] == data.get('qa_slot')):
                    raise ValueError('That team role is occupied at the selected effective date')
        if kind=='rules':
            duplicates=self.rows('SELECT id FROM rules WHERE lower(status)=lower(?) AND lower(severity)=lower(?) AND sp=?',(data['status'],data['severity'],float(data['sp'])))
            if any(r['id']!=int(identity or 0) for r in duplicates):
                raise ValueError('A case-insensitive status/severity/SP rule already exists; edit it instead')
        result = super().save(kind, data)
        with self.db:
            if kind == 'members':
                member = self.rows('SELECT * FROM members WHERE id=?', (result,))[0]
                if identity:
                    archived = int(data.get('archived', member['archived']))
                    self.db.execute('UPDATE members SET archived=? WHERE id=?', (archived, result))
                    member['archived'] = archived
                self.db.execute('INSERT INTO member_versions(member_id,effective_at,payload) VALUES(?,?,?)', (result, effective, json.dumps(member)))
            if kind == 'rules':
                rule = self.rows('SELECT * FROM rules WHERE id=?', (result,))[0]
                if not identity:
                    self.db.execute('UPDATE rules SET created_at=? WHERE id=?', (effective, result))
                    rule['created_at'] = effective
                self.db.execute('INSERT INTO rule_versions(rule_id,effective_at,payload) VALUES(?,?,?)', (result, effective, json.dumps(rule)))
            self.audit('effective_configuration', {'resource':kind,'id':result,'effective_at':effective})
        return result

    def update_settings(self, data):
        effective = timestamp(data.get('effective_at') or now())
        if effective > now():
            raise ValueError('Future policy date is not supported')
        latest = self.rows('SELECT effective_at FROM policy_versions ORDER BY effective_at DESC LIMIT 1')[0]['effective_at']
        if effective <= latest:
            raise ValueError('Policy effective time must follow the latest version')
        super().update_settings({k:v for k,v in data.items() if k != 'effective_at'})
        with self.db:
            self.db.execute('INSERT INTO policy_versions(effective_at,payload) VALUES(?,?)', (effective,json.dumps(self.settings())))

    def save_extra(self, kind, data):
        identity = data.get('id')
        if kind=='critical_priorities':
            if not isinstance(data['names'],list):
                raise ValueError('Priority names must be a list')
            names=[str(n).strip() for n in data['names'] if str(n).strip()]
            if not names:
                raise ValueError('At least one critical priority name is required')
            with self.db:
                self.db.execute('DELETE FROM critical_priorities')
                self.db.executemany('INSERT INTO critical_priorities VALUES(?)',[(n,) for n in dict.fromkeys(names)])
                self.audit('critical_priorities',data)
            return 'priorities'
        if kind=='status_id_mappings':
            status_id=str(data['status_id']).strip();name=str(data['status_name']).strip();unit=data['unit']
            if not status_id or not name or unit not in ('milliseconds','seconds','minutes','unverified'):
                raise ValueError('Choose a status ID, name and verified duration unit')
            with self.db:
                self.db.execute('INSERT INTO status_id_mappings VALUES(?,?,?) ON CONFLICT(status_id) DO UPDATE SET status_name=excluded.status_name,unit=excluded.unit',(status_id,name,unit))
                self.audit('status_id_mapping',data)
            return status_id
        if kind == 'workflow':
            name = str(data['name']).strip()
            category = data['category']
            roles = data['roles'] if isinstance(data['roles'],list) else json.loads(data['roles'])
            if not name or category not in ('active','paused','done','cancelled','backlog') or not set(roles) <= {'Dev','QA','TPM'}:
                raise ValueError('Invalid workflow category or roles')
            if category == 'paused' and set(roles) != {'Dev','TPM'}:
                raise ValueError('Shared follow-up statuses require Dev and TPM accountability')
            with self.db:
                self.db.execute('INSERT INTO workflow VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET category=excluded.category,roles=excluded.roles', (name,category,json.dumps(roles)))
                self.audit('workflow',data)
            return name
        if kind == 'sprints':
            start,end = date.fromisoformat(data['start_date']),date.fromisoformat(data['end_date'])
            if start > end:
                raise ValueError('Sprint start must precede its end')
            payload = {'name':str(data['name']).strip(),'start_date':start.isoformat(),'end_date':end.isoformat(),'team_id':int(data['team_id']) if data.get('team_id') else None}
        else:
            mapping = data['mapping'] if isinstance(data['mapping'],dict) else json.loads(data['mapping'])
            if not isinstance(mapping,dict) or not all(isinstance(k,str) and isinstance(v,str) for k,v in mapping.items()):
                raise ValueError('Mapping must be an object of field-to-column names')
            payload = {'name':str(data['name']).strip(),'mapping':json.dumps(mapping)}
        if not payload['name']:
            raise ValueError('Name is required')
        keys=list(payload)
        with self.db:
            if identity:
                if not self.rows(f'SELECT id FROM {kind} WHERE id=?',(identity,)):
                    raise ValueError('Record not found')
                self.db.execute(f"UPDATE {kind} SET {','.join(k+'=?' for k in keys)} WHERE id=?",list(payload.values())+[identity])
            else:
                identity=self.db.execute(f"INSERT INTO {kind}({','.join(keys)}) VALUES({','.join('?' for _ in keys)})",list(payload.values())).lastrowid
            self.audit(kind,data)
        return identity

    def archive(self, data):
        resource = data['resource']
        archived=bool(data.get('archived',True))
        if resource not in ('members','teams'):
            raise ValueError('Only members and teams can be archived')
        record = self.rows(f'SELECT * FROM {resource} WHERE id=?',(int(data['id']),))
        if not record:
            raise ValueError('Record not found')
        if resource == 'teams' and archived and self.rows('SELECT id FROM members WHERE team_id=? AND archived=0',(data['id'],)):
            raise ValueError('Move or archive the active members before archiving this team')
        if resource == 'members':
            effective=timestamp(data.get('effective_at') or now())
            last=self.rows('SELECT effective_at FROM member_versions WHERE member_id=? ORDER BY effective_at DESC LIMIT 1',(data['id'],))[0]['effective_at']
            if effective <= last or effective > now():
                raise ValueError('Archive time must follow the last version and not be in the future')
            if not archived and self.rows('SELECT archived FROM teams WHERE id=?',(record[0]['team_id'],))[0]['archived']:
                raise ValueError('Reactivate the member’s team first')
        self.backup()
        with self.db:
            self.db.execute(f'UPDATE {resource} SET archived=? WHERE id=?',(int(archived),data['id']))
            if resource == 'members':
                record[0]['archived']=int(archived)
                self.db.execute('INSERT INTO member_versions(member_id,effective_at,payload) VALUES(?,?,?)',(data['id'],effective,json.dumps(record[0])))
            self.audit('archive',data)

    def remove_holiday(self,data):
        self._day_cache={};self._work_cache={}
        with self.db:
            old=self.rows('SELECT * FROM holidays WHERE id=?',(data['id'],))
            if not old:
                raise ValueError('Holiday not found')
            self.db.execute('DELETE FROM holidays WHERE id=?',(data['id'],))
            self.audit('remove_holiday',old[0])

    def correct(self,data):
        self.ticket(data['ticket_key'])
        patch=data['patch'] if isinstance(data['patch'],dict) else json.loads(data['patch'])
        if not patch or set(patch)-{'member_id','team_id','sp','resolved','critical_at','status_at','severity'}:
            raise ValueError('Allowed correction fields: member_id, team_id, sp, resolved, critical_at, status_at, severity')
        reason=str(data.get('reason','')).strip()
        effective=timestamp(data['effective_at'])
        if not reason or effective > now():
            raise ValueError('Give a reason and a nonfuture effective time')
        if 'sp' in patch and (not isinstance(patch['sp'],(float,int)) or not math.isfinite(patch['sp']) or patch['sp']<0):
            raise ValueError('SP must be finite and nonnegative')
        if 'severity' in patch and (not isinstance(patch['severity'],str) or not patch['severity'].strip()):
            raise ValueError('Severity must be a nonempty string')
        if 'team_id' in patch and 'member_id' not in patch:
            raise ValueError('Correct member_id; its historical team will be derived automatically')
        for key in ('resolved','critical_at','status_at'):
            if key in patch:
                patch[key]=timestamp(patch[key])
                if patch[key] and patch[key]>now():
                    raise ValueError('Evidence timestamp cannot be in the future')
        if 'member_id' in patch:
            owners=self.members_at(effective)
            dev=next((m for m in owners if m['id']==int(patch['member_id']) and m['role']=='Dev'),None)
            if not dev:
                raise ValueError('Choose a developer active at the correction time')
            patch['member_id']=dev['id']
            patch['team_id']=dev['team_id']
            patch['owners']=[m for m in owners if m['id']==dev['id'] or m['team_id']==dev['team_id'] and m['role'] in ('QA','TPM')]
        self.backup()
        with self.db:
            self.db.execute('INSERT INTO corrections(ticket_key,effective_at,patch,reason,created_at) VALUES(?,?,?,?,?)',(data['ticket_key'],effective,json.dumps(patch),reason,now()))
            self.audit('ticket_correction',data)

    def effective_comment(self,comment):
        revisions=self.rows('SELECT * FROM comment_revisions WHERE comment_id=? ORDER BY id DESC LIMIT 1',(comment['id'],))
        return {**comment,**{k:revisions[0][k] for k in ('body','occurred_at')} } if revisions else comment

    def revise_comment(self,data):
        rows=self.rows('SELECT * FROM manual_comments WHERE id=?',(data['id'],))
        if not rows:
            raise ValueError('Manual comment not found')
        body=str(data['body']).strip();reason=str(data['reason']).strip();at=timestamp(data['occurred_at'])
        if not body or not reason or not at or at>now():
            raise ValueError('Comment text, reason and a nonfuture timestamp are required')
        self.backup()
        with self.db:
            self.db.execute('INSERT INTO comment_revisions(comment_id,body,occurred_at,reason,created_at) VALUES(?,?,?,?,?)',(data['id'],body,at,reason,now()))
            self.audit('comment_revision',data)

    def ticket(self,key):
        result=super().ticket(key)
        for c in self.rows('SELECT * FROM corrections WHERE ticket_key=? ORDER BY effective_at,id',(key,)):
            patch=json.loads(c['patch'])
            # Evidence repairs take effect even when no newer CSV exists.
            prior=[o for o in result['observations'] if o['observed_at']<c['effective_at']]
            if prior and c['effective_at']<=now() and not any(o['observed_at']==c['effective_at'] for o in result['observations']):
                source=max(prior,key=lambda o:o['observed_at'])
                result['observations'].append({'id':-c['id'],'ticket_key':key,'import_id':None,
                    'observed_at':c['effective_at'],'payload':copy.deepcopy(source['payload']),'virtual':True})
                result['observations'].sort(key=lambda o:o['observed_at'])
            for obs in result['observations']:
                if obs['observed_at']>=c['effective_at']:
                    obs['payload'].update(patch)
            result['events'].append({'at':c['created_at'],'kind':'correction','from':None,'to':patch,'evidence':c['reason'],'effective_at':c['effective_at']})
        original=result['observations']
        enriched=[]
        changes=[r['effective_at'] for r in self.rows('SELECT DISTINCT effective_at FROM member_versions WHERE effective_at>? AND effective_at<=? ORDER BY effective_at',(original[0]['observed_at'],now()))]
        times=sorted(set([o['observed_at'] for o in original]+changes))
        actual={o['observed_at']:o for o in original}
        last=None
        for at in times:
            if at in actual:
                item=copy.deepcopy(actual[at]);last=item['payload']
                enriched.append(item)
                continue
            p=copy.deepcopy(last)
            roster=self.members_at(at)
            dev=next((m for m in roster if m['id']==p['member_id'] and m['role']=='Dev'),None)
            p['team_id']=dev['team_id'] if dev else last.get('team_id')
            p['member_id']=dev['id'] if dev else last.get('member_id')
            p['developer_snapshot']=dev or last.get('developer_snapshot') or next((m for m in last.get('owners',[]) if m['id']==last.get('member_id')),None)
            p['owners']=[m for m in roster if (dev and m['id']==dev['id']) or m['team_id']==p['team_id'] and m['role'] in ('QA','TPM')]
            if p['owners']!=last.get('owners',[]) or p['member_id']!=last.get('member_id'):
                enriched.append({'id':-len(enriched),'ticket_key':key,'import_id':None,'observed_at':at,'payload':p,'virtual':True})
                result['events'].append({'at':at,'kind':'ownership/calendar','from':last.get('team_id'),'to':{'team_id':p['team_id'],'owners':[{'name':m['name'],'role':m['role'],'country':m['country']} for m in p['owners']]},'evidence':'Effective-dated local member/team configuration'})
                last=p
        result['observations']=enriched
        result['current']=result['observations'][-1]['payload']
        for duration in result['current'].get('time_in_status',[]):
            mapping=self.rows('SELECT * FROM status_id_mappings WHERE status_id=?',(duration['status_id'],))
            if mapping:
                duration['status_name']=mapping[0]['status_name'];duration['unit']=mapping[0]['unit']
                factor={'milliseconds':1/3600000,'seconds':1/3600,'minutes':1/60}.get(duration['unit'])
                duration['hours']=duration['duration_raw']*factor if factor else None
        return result

    def followup_history(self,key,start,end,segments,comments,events):
        # A shared deadline survives team/owner/calendar changes. Only qualifying comments reset it.
        qualified=[]
        for comment in comments:
            at=comment.get('at')
            if not at or not start<at<=end:
                continue
            owners=next((s['owners'] for s in segments if s['start']<=at<s['end']),[])
            if comment['author'] in {m['jira_id'] for m in owners}:
                qualified.append(at)
        resets=sorted(set(qualified))
        for a,b in zip([start]+resets,resets+[end]):
            elapsed=0.0;n=0
            slices=[]
            for segment in segments:
                low=max(a,segment['start']);high=min(b,segment['end'])
                boundaries=[r['effective_at'] for r in self.rows(
                    'SELECT effective_at FROM policy_versions WHERE effective_at>? AND effective_at<? ORDER BY effective_at',(low,high))]
                slices.extend({**segment,'start':x,'end':y} for x,y in zip([low]+boundaries,boundaries+[high]) if x<y)
            for segment in slices:
                low=max(a,segment['start']);high=min(b,segment['end'])
                if low>=high:
                    continue
                policy=self.policy_at(low)
                threshold=policy['followup_days']+n
                from zoneinfo import ZoneInfo
                tz=ZoneInfo('Asia/Amman')
                first=datetime.fromisoformat(low).astimezone(tz);last=datetime.fromisoformat(high).astimezone(tz);day=first.date()
                while day<=last.date():
                    begin=max(first,datetime.combine(day,datetime.min.time(),tz));stop=min(last,datetime.combine(day+timedelta(days=1),datetime.min.time(),tz))
                    eligible=[m for m in segment['owners'] if self.working_day(m['country'],day)]
                    fraction=max(0,(stop-begin).total_seconds()/86400) if eligible else 0
                    while elapsed+fraction>threshold+1e-9:
                        occurred=begin+timedelta(days=max(0,threshold-elapsed),microseconds=1)
                        for m in eligible:
                            events.append({'key':key,'member_id':m['id'],'at':occurred.astimezone(timezone.utc).isoformat(),'points':-policy['followup_initial'] if n==0 else -policy['followup_daily'],'reason':'Blocked / On Hold follow-up overdue'})
                        threshold+=1;n+=1
                    elapsed+=fraction;day+=timedelta(days=1)

    def state(self,asof=None):
        result=super().state(asof)
        result.update({'membership_history':self.rows('SELECT * FROM member_versions ORDER BY effective_at,id'),
                       'policy_history':self.rows('SELECT * FROM policy_versions ORDER BY effective_at,id'),
                       'rule_history':self.rows('SELECT * FROM rule_versions ORDER BY effective_at,id'),
                       'workflow':self.rows('SELECT * FROM workflow'),
                       'sprints':self.rows('SELECT * FROM sprints ORDER BY start_date DESC'),
                       'import_profiles':self.rows('SELECT * FROM import_profiles'),
                       'monthly_records':self.rows('SELECT id,member_id,month,revision,finalized_at,reason FROM monthly_records ORDER BY month DESC,revision DESC')})
        result['backups']=self.backups()
        result['status_id_mappings']=self.rows('SELECT * FROM status_id_mappings')
        result['critical_priorities']=[r['name'] for r in self.rows('SELECT name FROM critical_priorities')]
        for team in result['teams']:
            if team.get('archived'):
                continue
            roster=[m for m in result['members'] if m['team_id']==team['id'] and not m.get('archived')]
            missing=[]
            if not any(m['role']=='TPM' for m in roster):
                missing.append('TPM')
            for slot in ('Primary','Secondary'):
                if not any(m['role']=='QA' and m['qa_slot']==slot for m in roster):
                    missing.append(slot+' QA')
            if missing:
                result['warnings'].append('Team '+team['name']+': assign '+', '.join(missing)+' to complete accountability')
        durations=[]
        for ticket in result['tickets']:
            detail=self.ticket(ticket['key']);episodes=[]
            for o in detail['observations']:
                if o['observed_at']>result['asof']:
                    continue
                if not episodes or episodes[-1]['p']['status']!=o['payload']['status']:
                    episodes.append({'p':o['payload'],'start':o['observed_at']})
            for i,ep in enumerate(episodes):
                stop=episodes[i+1]['start'] if i+1<len(episodes) else result['asof']
                p=ep['p'];owner=next((m for m in p.get('owners',[]) if m['id']==p.get('member_id')),None)
                if self.workflow_at(p['status'])['category'] not in ('active','paused'):
                    continue
                rules=self.rules_at(p['status'],p['severity'],p['sp'],ep['start'])
                durations.append({'key':ticket['key'],'status':p['status'],'severity':p['severity'],'sp':p['sp'],'member_id':p['member_id'],'team_id':p['team_id'],'start':ep['start'],'end':stop,'working_days':self.work(ep['start'],stop,owner['country']) if owner else None,'allowed_days':rules[0]['days'] if rules else None,'evidence':'Observed interval; transitions may have occurred between imports'})
        result['durations']=durations
        result['pending_revisions']=[]
        for record in self.rows('SELECT * FROM monthly_records WHERE id IN (SELECT max(id) FROM monthly_records GROUP BY member_id,month)'):
            frozen=json.loads(record['payload']);live=self.monthly(record['member_id'],record['month'],result)
            totals_changed = any(round(float(frozen.get(k) or 0),6)!=round(float(live.get(k) or 0),6) for k in ('sp','target','score','critical','penalties'))
            evidence_changed = any(json.dumps(frozen.get(k), sort_keys=True) != json.dumps(live.get(k), sort_keys=True)
                                   for k in ('eligible','credits','events','membership_segments'))
            if totals_changed or evidence_changed:
                result['pending_revisions'].append({'member_id':record['member_id'],'month':record['month'],'revision':record['revision']})
                result['warnings'].append(f'Monthly record {record["month"]} for member {record["member_id"]}: new evidence or configuration differs; finalized revision {record["revision"]} retained')
        if result['imports']:
            age=(datetime.fromisoformat(result['asof'])-datetime.fromisoformat(result['imports'][0]['snapshot_at'])).total_seconds()/86400
            result['stale_days']=max(0,math.floor(age))
        else:
            result['stale_days']=None
        return result

    def restore(self,data):
        name=str(data['filename'])
        if Path(name).name!=name or not name.endswith('.sqlite3'):
            raise ValueError('Choose a listed backup filename')
        path=self.path.parent/'backups'/name
        if not path.is_file():
            raise ValueError('Backup not found')
        # Validate and migrate an isolated copy before touching the active dataset.
        # Close the selected file before retention runs (important on Windows).
        with tempfile.TemporaryDirectory(prefix='op-tracker-restore-') as folder:
            source=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
            staged_path=Path(folder)/'tracker.sqlite3'
            try:
                if source.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                    raise ValueError('Backup integrity check failed')
                required={'members','teams','countries','holidays','settings','rules','observations','imports','manual_comments','audit'}
                if not required <= {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                    raise ValueError('This is not an OP Tracker backup')
                staged_db=sqlite3.connect(staged_path)
                try:
                    source.backup(staged_db)
                finally:
                    staged_db.close()
            finally:
                source.close()
            staged=type(self)(staged_path)
            try:
                if staged.rows('PRAGMA foreign_key_check'):
                    raise ValueError('Backup contains invalid references')
                staged.state()
                self.backup()
                staged.db.backup(self.db)
                self._day_cache={};self._work_cache={}
            finally:
                staged.db.close()
        with self.db:
            self.audit('restore',{'filename':name})

    def backups(self):
        folder=self.path.parent/'backups'
        return [{'filename':p.name,'size':p.stat().st_size} for p in sorted(folder.glob('*.sqlite3'),reverse=True)]

    def _history_segments(self,member_id,start,end):
        versions=self.rows('SELECT * FROM member_versions WHERE member_id=? AND effective_at<? ORDER BY effective_at,id',(member_id,end))
        for i,row in enumerate(versions):
            a=max(start,row['effective_at']);b=min(end,versions[i+1]['effective_at'] if i+1<len(versions) else end)
            m=json.loads(row['payload'])
            if a<b and not m.get('archived'):
                yield a,b,m

    def target(self,member_id,start,end,team_id=None,country=None,role='Dev'):
        total=0.0
        for a,b,m in self._history_segments(member_id,start,end):
            if m['role']!=role or team_id and m['team_id']!=int(team_id) or country and m['country']!=country:
                continue
            policies=[r['effective_at'] for r in self.rows('SELECT effective_at FROM policy_versions WHERE effective_at>? AND effective_at<? ORDER BY effective_at',(a,b))]
            for x,y in zip([a]+policies,policies+[b]):
                cursor=datetime.fromisoformat(x)
                while cursor.isoformat()<y:
                    next_month=(cursor.replace(day=1)+timedelta(days=32)).replace(day=1,hour=0,minute=0,second=0,microsecond=0)
                    stop=min(y,next_month.isoformat())
                    month_start=cursor.replace(day=1,hour=0,minute=0,second=0,microsecond=0).isoformat()
                    full=self.work(month_start,next_month.isoformat(),m['country'])
                    total+=self.policy_at(x)['monthly_target']*(self.work(cursor.isoformat(),stop,m['country'])/full if full else 0)
                    cursor=datetime.fromisoformat(stop)
        return total

    def monthly(self,member_id,month,state=None):
        first=date.fromisoformat(month+'-01')
        following=(first.replace(day=28)+timedelta(days=4)).replace(day=1)
        start=first.isoformat()+'T00:00:00+00:00';end=following.isoformat()+'T00:00:00+00:00'
        state=state or self.state()
        segments=list(self._history_segments(member_id,start,end))
        target=self.target(member_id,start,end)
        credits=[c for c in state['credits'] if c['member_id']==member_id and start<=c['at']<end]
        events=[e for e in state['score_events'] if e['member_id']==member_id and start<=e['at']<end]
        sp=sum(c['sp'] for c in credits)
        utilization=sp/target*100 if target>0 else None
        bonus=10*math.floor(max(0,(utilization or 0)-100)/20+1e-9)
        eligible=bool(segments)
        return {'member_id':member_id,'month':month,'eligible':eligible,'sp':sp,'target':target,'util':utilization,
                'bonus':bonus,'critical':sum(e['points'] for e in events if e['points']>0),
                'penalties':-sum(e['points'] for e in events if e['points']<0),
                'score':100+bonus+sum(e['points'] for e in events) if eligible else None,
                'credits':credits,'events':events,'membership_segments':[(a,b,m) for a,b,m in segments]}

    def finalize(self,data,_state=None):
        month=data['month'];first=date.fromisoformat(month+'-01')
        if month>=date.today().isoformat()[:7]:
            raise ValueError('Only elapsed months can be finalized')
        reason=str(data.get('reason','')).strip()
        if not reason:
            raise ValueError('A finalization/revision reason is required')
        state=_state or self.state()
        self.backup()
        count=0
        with self.db:
            for m in state['members']:
                value=self.monthly(m['id'],month,state)
                previous=self.rows('SELECT * FROM monthly_records WHERE member_id=? AND month=? ORDER BY revision DESC LIMIT 1',(m['id'],month))
                if not value['eligible'] and not (previous and data.get('revise')):
                    continue
                if previous and not data.get('revise'):
                    continue
                revision=previous[0]['revision']+1 if previous else 1
                start=date.fromisoformat(month+'-01');stop=(start.replace(day=28)+timedelta(days=4)).replace(day=1)
                value['daily_targets']=[]
                day=start
                while day<stop:
                    a=day.isoformat()+'T00:00:00+00:00';b=(day+timedelta(days=1)).isoformat()+'T00:00:00+00:00'
                    for x,y,membership in self._history_segments(m['id'],a,b):
                        value['daily_targets'].append({'day':day.isoformat(),'team_id':membership['team_id'],'country':membership['country'],'role':membership['role'],'target':self.target(m['id'],x,y,membership['team_id'],membership['country']) if membership['role']=='Dev' else 0})
                    day+=timedelta(days=1)
                self.db.execute('INSERT INTO monthly_records(member_id,month,revision,payload,finalized_at,reason) VALUES(?,?,?,?,?,?)',(m['id'],month,revision,json.dumps(value),now(),reason))
                count+=1
            self.audit('monthly_finalization',{'month':month,'count':count,'reason':reason,'revise':bool(data.get('revise'))})
        return count

    def refresh_records(self):
        state=self.state()
        if not state['imports']:
            return
        evidence_dates=[i['snapshot_at'][:10] for i in state['imports']]+[c['at'][:10] for c in state['credits']]
        cursor=date.fromisoformat(min(evidence_dates)).replace(day=1)
        while cursor<date.today().replace(day=1):
            month=cursor.isoformat()[:7]
            if not self.rows('SELECT id FROM monthly_records WHERE month=? LIMIT 1',(month,)):
                self.finalize({'month':month,'reason':'Automatic elapsed-month finalization'},_state=state)
            cursor=(cursor.replace(day=28)+timedelta(days=4)).replace(day=1)

    def report(self,start_date,end_date,team_id=None,country=None,role=None,live=False):
        a,b=date.fromisoformat(start_date),date.fromisoformat(end_date)
        if a>b or (b-a).days>3660 or b>date.today():
            raise ValueError('Select a nonfuture date range of at most ten years')
        start=a.isoformat()+'T00:00:00+00:00';end=(b+timedelta(days=1)).isoformat()+'T00:00:00+00:00'
        months=[];d=a.replace(day=1)
        while d<=b:
            months.append(d.isoformat()[:7]);d=(d.replace(day=28)+timedelta(days=4)).replace(day=1)
        state=self.state()
        rows=[]
        for member in state['members']:
            monthly=[]
            segments=[]
            for month in months:
                record=self.rows('SELECT * FROM monthly_records WHERE member_id=? AND month=? ORDER BY revision DESC LIMIT 1',(member['id'],month))
                if record and not live:
                    v=json.loads(record[0]['payload']);v['record_status']='Finalized';v['revision']=record[0]['revision']
                    if any(r['member_id']==member['id'] and r['month']==month for r in state.get('pending_revisions',[])):
                        v['record_status']='Finalized · Revision available'
                else:
                    v=self.monthly(member['id'],month,state);v['record_status']='Provisional' if month==date.today().isoformat()[:7] else 'Unfinalized'
                matching=[(max(x,start),min(y,end),m) for x,y,m in v['membership_segments']
                          if x<end and y>start and (not team_id or m['team_id']==int(team_id))
                          and (not country or m['country']==country) and (not role or m['role']==role)]
                if v['eligible'] and matching:
                    monthly.append(v)
                    segments.extend(matching)
            if not segments:
                continue
            credits=[c for v in monthly for c in v['credits'] if start<=c['at']<end and (not team_id or c['team_id']==int(team_id)) and any(x<=c['at']<y for x,y,m in segments if m['role']=='Dev')]
            target=0.0
            for v in monthly:
                if v.get('record_status','').startswith('Finalized') and 'daily_targets' in v:
                    target+=sum(d['target'] for d in v['daily_targets'] if start_date<=d['day']<=end_date and (not team_id or d['team_id']==int(team_id)) and (not country or d['country']==country) and (not role or d['role']==role))
                else:
                    month_start=v['month']+'-01T00:00:00+00:00'
                    month_next=(date.fromisoformat(v['month']+'-01').replace(day=28)+timedelta(days=4)).replace(day=1).isoformat()+'T00:00:00+00:00'
                    if not role or role=='Dev':
                        target+=self.target(member['id'],max(start,month_start),min(end,month_next),team_id,country)
            points=sum(c['sp'] for c in credits)
            last=segments[-1][2]
            rows.append({**last,'id':member['id'],'sp':points,'target':target,'util':points/target*100 if target>0 else None,
                         'score':sum(v['score'] for v in monthly)/len(monthly) if monthly else None,'months':monthly})
        return {'start_date':start_date,'end_date':end_date,'members':rows,'months':months,
                'sp':sum(r['sp'] for r in rows),'target':sum(r['target'] for r in rows),
                'score':sum(r['score'] for r in rows if r['score'] is not None)/sum(r['score'] is not None for r in rows) if any(r['score'] is not None for r in rows) else None}

    def export(self,data):
        report=self.report(data['start_date'],data['end_date'],data.get('team_id'),data.get('country'),data.get('role'))
        stream=io.StringIO();writer=csv.writer(stream)
        writer.writerow(['Member','Jira ID','Role','Team ID','Country','Delivered SP','Target SP','Utilization %','Average score','Start','End'])
        for r in report['members']:
            cells=[r['name'],r['jira_id'],r['role'],r['team_id'],r['country'],r['sp'],r['target'],r['util'],r['score'],report['start_date'],report['end_date']]
            writer.writerow(["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v for v in cells])
        return {'filename':f'op-tracker-{report["start_date"]}-{report["end_date"]}.csv','csv':stream.getvalue()}
