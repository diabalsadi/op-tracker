"""Local Jira tracker. Python 3.11+, SQLite, no third-party runtime dependencies."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / 'data' / 'tracker.sqlite3'
DONE = {'done', 'closed'}
PAUSED = {'blocked', 'on hold'}


def assignments(member):
    value=member.get('team_assignments')
    if isinstance(value,str):
        value=json.loads(value)
    return value or [{'team_id':int(member['team_id']),'qa_slot':member.get('qa_slot')}]


def in_team(member, team_id):
    if team_id is None:
        return False
    return any(a['team_id']==int(team_id) for a in assignments(member))


def team_owners(members, developer):
    result=[]
    for member in members:
        if member['id']==developer['id']:
            result.append(member)
        elif member['role'] in ('QA','TPM'):
            for assignment in assignments(member):
                if assignment['team_id']==developer['team_id']:
                    result.append({**member,'team_id':assignment['team_id'],'qa_slot':assignment.get('qa_slot')})
    return result


def now():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value):
    if not value:
        return None
    value = str(value).strip()
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        dt = None
        for fmt in ('%d/%b/%y %I:%M %p', '%d/%b/%y %H:%M', '%m/%d/%Y %H:%M', '%d/%m/%Y %H:%M', '%Y-%m-%d'):
            try:
                dt = datetime.strptime(value, fmt)
                break
            except ValueError:
                pass
        if dt is None:
            raise ValueError(f'Unsupported timestamp: {value}. Use ISO 8601 or configure your export.')
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


class Tracker:
    def __init__(self, path=DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS countries(code TEXT PRIMARY KEY,name TEXT NOT NULL,weekend TEXT NOT NULL,timezone TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS holidays(id INTEGER PRIMARY KEY,country TEXT REFERENCES countries(code),day TEXT NOT NULL,name TEXT NOT NULL,UNIQUE(country,day));
        CREATE TABLE IF NOT EXISTS teams(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS members(id INTEGER PRIMARY KEY,name TEXT NOT NULL,jira_id TEXT NOT NULL UNIQUE,role TEXT NOT NULL CHECK(role IN ('Dev','QA','TPM')),qa_slot TEXT,country TEXT NOT NULL REFERENCES countries(code),team_id INTEGER NOT NULL REFERENCES teams(id));
        CREATE TABLE IF NOT EXISTS rules(id INTEGER PRIMARY KEY,status TEXT NOT NULL,severity TEXT NOT NULL,sp REAL NOT NULL,days REAL NOT NULL,initial REAL NOT NULL,daily REAL NOT NULL,created_at TEXT NOT NULL,UNIQUE(status,severity,sp));
        CREATE TABLE IF NOT EXISTS imports(id INTEGER PRIMARY KEY,filename TEXT NOT NULL,snapshot_at TEXT NOT NULL,hash TEXT NOT NULL,raw TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(hash,snapshot_at));
        CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY,import_id INTEGER NOT NULL REFERENCES imports(id),ticket_key TEXT NOT NULL,observed_at TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(import_id,ticket_key));
        CREATE TABLE IF NOT EXISTS manual_comments(id INTEGER PRIMARY KEY,ticket_key TEXT NOT NULL,author_id INTEGER NOT NULL REFERENCES members(id),body TEXT NOT NULL,occurred_at TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,created_at TEXT NOT NULL,payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS observations_ticket_time ON observations(ticket_key,observed_at,id);
        CREATE INDEX IF NOT EXISTS comments_ticket ON manual_comments(ticket_key);
        ''')
        with self.db:
            # Upgraded databases enforce uniqueness only for active role holders.
            # Recreating legacy indexes here would reject archived replacements
            # before the versioned tracker gets a chance to run its migration.
            if 'archived' not in {r['name'] for r in self.rows('PRAGMA table_info(members)')}:
                self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_tpm ON members(team_id) WHERE role='TPM'")
                self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_qa_slot ON members(team_id,qa_slot) WHERE role='QA'")
            if 'author_jira' not in {r['name'] for r in self.rows('PRAGMA table_info(manual_comments)')}:
                self.db.execute('ALTER TABLE manual_comments ADD COLUMN author_jira TEXT')
            self.db.execute("INSERT OR IGNORE INTO settings VALUES('monthly_target','16')")
            self.db.execute("INSERT OR IGNORE INTO settings VALUES('followup_days','3')")
            self.db.execute("INSERT OR IGNORE INTO settings VALUES('followup_initial','2')")
            self.db.execute("INSERT OR IGNORE INTO settings VALUES('followup_daily','1')")
            self.db.execute("INSERT OR IGNORE INTO settings VALUES('critical_days','2')")
            self.db.execute("INSERT OR IGNORE INTO settings VALUES('critical_reward','1')")
            self.db.executemany('INSERT OR IGNORE INTO countries VALUES(?,?,?,?)', [
                ('JO', 'Jordan', '[4,5]', 'Asia/Amman'),
                ('DO', 'Dominican Republic', '[5,6]', 'America/Santo_Domingo'),
                ('AM', 'Armenia', '[5,6]', 'Asia/Yerevan')])

    def rows(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args)]

    def audit(self, kind, value):
        self.db.execute('INSERT INTO audit(kind,created_at,payload) VALUES(?,?,?)', (kind, now(), json.dumps(value)))

    def save(self, kind, data):
        self._work_cache={}
        self._day_cache={}
        specs = {
            'teams': ['name'],
            'members': ['name', 'jira_id', 'role', 'qa_slot', 'country', 'team_id'],
            'rules': ['status', 'severity', 'sp', 'days', 'initial', 'daily'],
            'holidays': ['country', 'day', 'name'],
            'countries': ['name', 'weekend', 'timezone'],
        }
        if kind not in specs:
            raise ValueError('Unknown resource')
        cols = specs[kind]
        obj = {c: data.get(c) for c in cols}
        for c in cols:
            if isinstance(obj[c], str):
                obj[c] = obj[c].strip()
        if any(obj[c] in (None, '') for c in cols if c != 'qa_slot'):
            raise ValueError('Fill every required field')
        if kind == 'members':
            if obj['role'] not in ('Dev', 'QA', 'TPM'):
                raise ValueError('Invalid role')
            obj['qa_slot'] = obj['qa_slot'] if obj['role'] == 'QA' else None
            if obj['role'] == 'QA' and obj['qa_slot'] not in ('Primary', 'Secondary'):
                raise ValueError('Choose Primary or Secondary QA')
        if kind == 'rules':
            for c in ('sp', 'days', 'initial', 'daily'):
                obj[c] = float(obj[c])
                if not math.isfinite(obj[c]) or obj[c] < 0:
                    raise ValueError('Rule values must be finite and nonnegative')
            if obj['days'] <= 0:
                raise ValueError('Allowed duration must be positive')
        if kind == 'holidays':
            date.fromisoformat(obj['day'])
        if kind == 'countries':
            weekend = json.loads(obj['weekend']) if isinstance(obj['weekend'], str) else obj['weekend']
            if not isinstance(weekend, list) or any(type(n) is not int or n < 0 or n > 6 for n in weekend):
                raise ValueError('Weekend must be day numbers 0–6, Monday=0')
            obj['weekend'] = json.dumps(weekend)
            try:
                ZoneInfo(obj['timezone'])
            except ZoneInfoNotFoundError:
                raise ValueError('Timezone data unavailable. On Windows run: pip install tzdata')
        identity = data.get('code') if kind == 'countries' else data.get('id')
        key = 'code' if kind == 'countries' else 'id'
        if kind == 'countries' and not identity:
            raise ValueError('Country code is required')
        with self.db:
            if identity:
                old = self.rows(f'SELECT * FROM {kind} WHERE {key}=?', (identity,))
                if not old:
                    raise ValueError('Record not found')
                self.db.execute(f"UPDATE {kind} SET {','.join(c+'=?' for c in cols)} WHERE {key}=?", [obj[c] for c in cols] + [identity])
            else:
                if kind == 'rules':
                    obj['created_at'] = now()
                cs = list(obj)
                identity = self.db.execute(f"INSERT INTO {kind}({','.join(cs)}) VALUES({','.join('?' for _ in cs)})", [obj[c] for c in cs]).lastrowid
            self.audit('configuration', {'resource': kind, 'identity': identity, 'previous': old[0] if data.get('id') or kind == 'countries' else None, 'new': obj})
        return identity

    def settings(self):
        return {r['key']: float(r['value']) for r in self.rows('SELECT * FROM settings')}

    def update_settings(self, data):
        allowed = {'monthly_target', 'followup_days', 'followup_initial', 'followup_daily', 'critical_days', 'critical_reward'}
        with self.db:
            for k, v in data.items():
                if k not in allowed or not math.isfinite(float(v)) or float(v) < 0 or (k in {'monthly_target', 'followup_days', 'critical_days'} and float(v) == 0):
                    raise ValueError('Invalid setting')
                self.db.execute('UPDATE settings SET value=? WHERE key=?', (str(float(v)), k))
            self.audit('settings', data)

    def parse_csv(self, raw, snapshot_at, mapping=None):
        snapshot_at = timestamp(snapshot_at)
        if not snapshot_at:
            raise ValueError('Snapshot date/time is required')
        if datetime.fromisoformat(snapshot_at) > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError('Snapshot cannot be in the future')
        aliases = {
            'key': ['Issue key', 'Key', 'Ticket'], 'summary': ['Summary', 'Title'],
            'status': ['Status'], 'severity': ['Priority', 'Severity'],
            'sp': ['Story Points', 'Story point estimate', 'Custom field (Story Points)', 'Custom field (Story point estimate)'],
            'assignee': ['Assignee Id', 'Assignee ID', 'Assignee'],
            'resolved': ['Resolved', 'Resolution date'], 'critical_at': ['Critical At', 'Critical since'],
            'status_at': ['Status Changed At', 'Status changed'],
        }
        try:
            dialect = csv.Sniffer().sniff(raw[:20000], delimiters=',;\t')
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(raw.lstrip('\ufeff')), dialect)
        export_timezone = (mapping or {}).get('_timezone','UTC')
        try:
            export_tz=ZoneInfo(export_timezone)
        except ZoneInfoNotFoundError:
            raise ValueError('Invalid CSV timezone or missing timezone data')
        def parse_time(value):
            if not value:
                return None
            normalized=timestamp(value)
            # Explicit ISO offsets win; otherwise timestamps belong to the selected export timezone.
            if re.search(r'(?:Z|[+-]\d\d:\d\d)$',str(value).strip()):
                return normalized
            naive=datetime.fromisoformat(normalized).replace(tzinfo=None)
            return naive.replace(tzinfo=export_tz).astimezone(timezone.utc).isoformat()
        headers = next(reader, [])
        if not headers:
            raise ValueError('CSV has no header')
        lookup = {h.strip().casefold(): i for i, h in enumerate(headers)}
        columns = {}
        for field, names in aliases.items():
            requested = (mapping or {}).get(field)
            columns[field] = lookup.get(requested.casefold()) if requested else next((lookup[n.casefold()] for n in names if n.casefold() in lookup), None)
        if columns['key'] is None or columns['status'] is None:
            raise ValueError('Map Issue key and Status columns before import')
        members = {r['jira_id']: r for r in (self.members_at(snapshot_at) if hasattr(self, 'members_at') else self.rows('SELECT * FROM members'))}
        results, warnings, seen = [], [], set()
        for number, row in enumerate(reader, 2):
            if not any(row):
                continue
            get = lambda k: row[columns[k]].strip() if columns[k] is not None and columns[k] < len(row) else ''
            key = get('key').upper()
            if not re.fullmatch(r'[A-Z][A-Z0-9_]*-\d+', key) or not get('status'):
                raise ValueError(f'Row {number}: invalid key or missing status')
            if key in seen:
                raise ValueError(f'Duplicate ticket {key} in CSV')
            seen.add(key)
            estimate = float(get('sp')) if get('sp') else None
            if estimate is not None and (not math.isfinite(estimate) or estimate < 0):
                raise ValueError(f'{key}: story points must be finite and nonnegative')
            member = members.get(get('assignee'))
            if not member:
                warnings.append(f'{key}: unmapped assignee {get("assignee") or "(empty)"}')
            if estimate is None:
                warnings.append(f'{key}: no story-point estimate')
            comments = []
            for i, h in enumerate(headers):
                if h.casefold().strip().startswith('comment') and i < len(row) and row[i].strip():
                    value = row[i].strip()
                    try:
                        values = json.loads(value)
                        values = values if isinstance(values, list) else [values]
                        for c in values:
                            comments.append({'author': c.get('author', ''), 'at': parse_time(c.get('at')), 'body': str(c.get('body', ''))})
                    except (ValueError, TypeError, AttributeError):
                        parts = value.split(';', 2)
                        try:
                            comments.append({'at': parse_time(parts[0]), 'author': parts[1], 'body': parts[2]})
                        except (ValueError, IndexError):
                            comments.append({'at': None, 'author': '', 'body': value})
                            warnings.append(f'{key}: comment author/time unavailable; cannot reset follow-up')
            payload = {'key': key, 'summary': get('summary'), 'status': get('status'), 'severity': get('severity') or 'Unspecified', 'sp': estimate, 'assignee': get('assignee'), 'member_id': member['id'] if member else None, 'team_id': member['team_id'] if member else None, 'resolved': parse_time(get('resolved')), 'critical_at': parse_time(get('critical_at')), 'status_at': parse_time(get('status_at')), 'comments': comments}
            if member and member['role'] != 'Dev':
                prior = self.rows('SELECT payload FROM observations WHERE ticket_key=? AND observed_at<? ORDER BY observed_at DESC,id DESC LIMIT 1', (key, snapshot_at))
                prior_id = json.loads(prior[0]['payload']).get('member_id') if prior else None
                member = next((m for m in members.values() if m['id'] == prior_id and m['role'] == 'Dev'), None)
                payload['member_id'] = member['id'] if member else None
                payload['team_id'] = member['team_id'] if member else None
                if not member:
                    warnings.append(f'{key}: QA/TPM assignee has no previous developer ownership')
            payload['owners'] = team_owners(members.values(),member) if member else []
            payload['sprints'] = [row[i].strip() for i,h in enumerate(headers) if h.strip().casefold()=='sprint' and i<len(row) and row[i].strip()]
            payload['time_in_status'] = []
            chart_index = lookup.get('custom field ([chart] time in status)')
            if chart_index is not None and chart_index < len(row) and row[chart_index].strip():
                for item in row[chart_index].split('_*|*_'):
                    parts = item.split('_*:*_')
                    if len(parts)==3 and parts[1].isdigit() and re.fullmatch(r'\d+(?:\.\d+)?',parts[2]):
                        payload['time_in_status'].append({'status_id':parts[0],'visits':int(parts[1]),'duration_raw':float(parts[2]),'unit':'unverified'})
                    else:
                        warnings.append(f'{key}: unsupported encoded Time in Status entry retained in source CSV')
            for c in comments:
                if c['at'] and c['at'] > snapshot_at:
                    raise ValueError(f'{key}: comment timestamp is after snapshot')
            for field in ('resolved', 'critical_at', 'status_at'):
                if payload[field] and payload[field] > snapshot_at:
                    raise ValueError(f'{key}: {field} is after snapshot')
            results.append(payload)
        if not results:
            raise ValueError('No ticket rows found')
        return results, warnings, snapshot_at, headers

    def import_csv(self, raw, filename, at, mapping=None, preview=False):
        rows, warnings, at, headers = self.parse_csv(raw, at, mapping)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        if self.rows('SELECT id FROM imports WHERE hash=? AND snapshot_at=?', (digest, at)):
            return {'duplicate': True, 'count': 0, 'warnings': []}
        existing = {r['ticket_key']: json.loads(r['payload']) for r in self.rows('SELECT * FROM observations WHERE observed_at=?', (at,))}
        if any(r['key'] in existing and existing[r['key']] != r for r in rows):
            raise ValueError('Conflicting data at the same snapshot time. Choose the correct source and timestamp.')
        result = {'count': len(rows), 'warnings': warnings, 'snapshot_at': at, 'headers': headers, 'sample': rows[:5]}
        if preview:
            return result
        self.backup()
        with self.db:
            iid = self.db.execute('INSERT INTO imports(filename,snapshot_at,hash,raw,created_at) VALUES(?,?,?,?,?)', (Path(filename).name, at, digest, raw, now())).lastrowid
            self.db.executemany('INSERT INTO observations(import_id,ticket_key,observed_at,payload) VALUES(?,?,?,?)', [(iid, r['key'], at, json.dumps(r)) for r in rows])
            self.audit('import', {'id': iid, 'count': len(rows), 'warnings': warnings})
        return result

    def backup(self):
        folder = self.path.parent / 'backups'
        folder.mkdir(exist_ok=True)
        dest = folder / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.sqlite3')
        with closing(sqlite3.connect(dest)) as db:
            self.db.backup(db)
        for old in sorted(folder.glob('*.sqlite3'))[:-30]:
            old.unlink()
        return dest.name

    def working_day(self, country, d):
        cache=getattr(self,'_day_cache',None)
        if cache is None:
            cache=self._day_cache={}
        key=(country,d)
        if key in cache:
            return cache[key]
        c = self.rows('SELECT * FROM countries WHERE code=?', (country,))[0]
        cache[key]=d.weekday() not in json.loads(c['weekend']) and not bool(self.rows('SELECT id FROM holidays WHERE country=? AND day=?', (country, d.isoformat())))
        return cache[key]

    def work(self, start, end, country):
        if not start or start >= end:
            return 0.0
        cache=getattr(self,'_work_cache',None)
        if cache is None:
            cache=self._work_cache={}
        key=(start,end,country)
        if key in cache:
            return cache[key]
        c = self.rows('SELECT * FROM countries WHERE code=?', (country,))[0]
        try:
            tz = ZoneInfo(c['timezone'])
        except ZoneInfoNotFoundError:
            raise ValueError('Install timezone data: pip install tzdata')
        a, b = datetime.fromisoformat(start).astimezone(tz), datetime.fromisoformat(end).astimezone(tz)
        total, current = 0.0, a.date()
        while current <= b.date():
            low = datetime.combine(current, datetime.min.time(), tz)
            high = datetime.combine(current + timedelta(days=1), datetime.min.time(), tz)
            if self.working_day(country, current):
                total += max(0, (min(b, high) - max(a, low)).total_seconds()) / 86400
            current += timedelta(days=1)
        cache[key]=total
        return total

    def ticket(self, key):
        observations = self.rows('SELECT * FROM observations WHERE ticket_key=? ORDER BY observed_at,id', (key,))
        if not observations:
            raise ValueError('Ticket not found')
        events, comments, unique, previous = [], [], set(), None
        for o in observations:
            p = json.loads(o['payload'])
            for field in ('status', 'assignee', 'severity', 'sp'):
                if previous is None or p[field] != previous[field]:
                    exact=field=='status' and p.get('status_at') and p['status_at']<=o['observed_at']
                    events.append({'at': p['status_at'] if exact else o['observed_at'], 'kind': field, 'from': previous.get(field) if previous else None, 'to': p[field], 'evidence': 'exported status timestamp' if exact else 'snapshot observation', 'import_id': o['import_id']})
            for c in p['comments']:
                ident = (c['author'], c['at'], c['body'])
                if ident not in unique:
                    comments.append({**c, 'source': 'Jira CSV'})
                    unique.add(ident)
            previous = p
        members = {m['id']: m for m in self.rows('SELECT * FROM members')}
        for c in self.rows('SELECT * FROM manual_comments WHERE ticket_key=?', (key,)):
            if hasattr(self,'effective_comment'):
                c=self.effective_comment(c)
            author = c.get('author_jira') or members[c['author_id']]['jira_id']
            ident = (author, c['occurred_at'], c['body'])
            if ident not in unique:
                comments.append({'author': author, 'at': c['occurred_at'], 'body': c['body'], 'source': 'Manual entry','manual_id':c['id']})
                unique.add(ident)
        return {'current': previous, 'events': events, 'comments': sorted(comments, key=lambda x: x['at'] or ''), 'observations': [{**o, 'payload': json.loads(o['payload'])} for o in observations]}

    def add_comment(self, data):
        detail = self.ticket(data['ticket_key'])
        at = timestamp(data['occurred_at'])
        ticket = detail['current']
        member = self.rows('SELECT * FROM members WHERE id=?', (data['author_id'],))
        if hasattr(self,'members_at') and at:
            observed=[o for o in detail['observations'] if o['observed_at']<=at]
            if not observed:
                raise ValueError('Comment predates available ownership evidence')
            ticket=observed[-1]['payload']
            member=[m for m in self.members_at(at) if m['id']==int(data['author_id'])]
        if not member or member[0]['id'] != ticket['member_id'] and not (member[0]['role'] == 'TPM' and in_team(member[0],ticket['team_id'])):
            raise ValueError('Choose this ticket’s developer or team TPM')
        body = str(data['body']).strip()
        if not body or not at or at > now():
            raise ValueError('Enter a comment and a valid past timestamp')
        with self.db:
            self.db.execute('INSERT INTO manual_comments(ticket_key,author_id,body,occurred_at,created_at,author_jira) VALUES(?,?,?,?,?,?)', (data['ticket_key'], data['author_id'], body, at, now(),member[0]['jira_id']))
            self.audit('manual_comment', data)

    def state(self, asof=None):
        asof = timestamp(asof) if asof else now()
        members = self.rows('SELECT * FROM members ORDER BY name')
        byid = {m['id']: m for m in members}
        credits, tickets, score_events, warnings = [], [], [], []
        settings = self.settings()
        for key in [r['ticket_key'] for r in self.rows('SELECT DISTINCT ticket_key FROM observations')]:
            detail = self.ticket(key)
            obs = [o for o in detail['observations'] if o['observed_at'] <= asof]
            if not obs:
                continue
            current = obs[-1]['payload']
            current['last_seen'] = next(o['observed_at'] for o in reversed(obs) if not o.get('virtual'))
            tickets.append(current)
            done = lambda status: self.workflow_at(status)['category']=='done' if hasattr(self,'workflow_at') else status.casefold() in DONE
            paused = lambda status: self.workflow_at(status)['category']=='paused' if hasattr(self,'workflow_at') else status.casefold() in PAUSED
            first = next((o for o in obs if done(o['payload']['status'])), None)
            if first:
                p = first['payload']
                completed = p['resolved'] or (first['observed_at'] if first != obs[0] else None)
                historical = p.get('owners', [])
                dev = next((m for m in historical if m['id'] == p['member_id']), p.get('developer_snapshot') or byid.get(p['member_id']))
                if completed and dev and dev['role'] == 'Dev' and p['sp'] is not None:
                    credits.append({'key': key, 'at': completed, 'sp': p['sp'], 'member_id': dev['id'], 'team_id': p['team_id'], 'evidence': 'resolution timestamp' if p['resolved'] else 'first observed Done'})
                    critical_dates=[o['payload']['critical_at'] for o in obs if o['payload'].get('critical_at') and o['observed_at']<=first['observed_at']]
                    critical_at=min(critical_dates) if critical_dates else None
                    policy=self.policy_at(completed) if hasattr(self,'policy_at') else {}
                    critical=self.is_critical(p['severity']) if hasattr(self,'is_critical') else p['severity'].casefold()=='critical'
                    if critical and not critical_at:
                        warnings.append(f'{key}: Critical reward needs an evidenced marked-Critical timestamp')
                    reward_country=dev['country']
                    if critical_at and hasattr(self,'members_at'):
                        earlier=[o for o in obs if o['observed_at']<=critical_at]
                        critical_dev_id=earlier[-1]['payload']['member_id'] if earlier else dev['id']
                        critical_owner=next((m for m in self.members_at(critical_at) if m['id']==critical_dev_id and m['role']=='Dev'),None)
                        if critical_owner:
                            reward_country=critical_owner['country']
                    if critical and critical_at and critical_at <= completed and self.work(critical_at, completed, reward_country) <= policy.get('critical_days',2):
                        owners = historical or [m for m in members if m['id'] == dev['id'] or m['team_id'] == p['team_id'] and m['role'] in ('QA', 'TPM')]
                        score_events.extend({'key': key, 'member_id': m['id'], 'at': completed, 'points': policy.get('critical_reward',1), 'reason': f'Critical completed within configured working-day window ({reward_country} calendar at marked-Critical time)'} for m in owners)
                else:
                    warnings.append(f'{key}: Done credit needs developer, SP, and evidenced completion time')
            # Status episodes are inferred from consecutive snapshots; exact transition history is not fabricated.
            episodes = []
            for o in obs:
                p = o['payload']
                signature = (p['status'], p['member_id'], p['team_id'], p['severity'], p['sp'],json.dumps(p.get('owners',[]),sort_keys=True))
                if not episodes or episodes[-1]['signature'] != signature:
                    exact=p.get('status_at')
                    valid=exact and exact<=o['observed_at'] and (not episodes or exact>episodes[-1]['start'] and episodes[-1]['p']['status']!=p['status'])
                    episodes.append({'signature': signature, 'p': p, 'start': exact if valid else o['observed_at']})
            for i, ep in enumerate(episodes):
                p, start = ep['p'], ep['start']
                end = episodes[i+1]['start'] if i+1 < len(episodes) else asof
                historical = p.get('owners', [])
                dev = next((m for m in historical if m['id'] == p['member_id']), p.get('developer_snapshot') or byid.get(p['member_id']))
                category = self.workflow_at(p['status'])['category'] if hasattr(self,'workflow_at') else ('done' if done(p['status']) else 'cancelled' if p['status'].casefold()=='cancelled' else 'active')
                if category=='unconfigured':
                    warnings.append(f'{key}: configure workflow category and accountable roles for {p["status"]} in Administration → Workflow')
                if not dev or dev['role'] != 'Dev' or category in ('unconfigured','done','cancelled','backlog'):
                    continue
                owners = [m for m in (historical or members) if m['id'] == dev['id'] or m['team_id'] == p['team_id'] and m['role'] == 'TPM' or m['team_id'] == p['team_id'] and m['role'] == 'QA' and p['status'].casefold() in ('qa', 'ready for release')]
                if p['status'].casefold() == 'ready for release':
                    owners = [m for m in owners if m['role'] != 'Dev']
                if hasattr(self,'workflow_at'):
                    allowed = json.loads(self.workflow_at(p['status'])['roles'])
                    roster = historical if 'owners' in p else members
                    owners = [m for m in roster if m['role'] in allowed and (m['id']==dev['id'] or m['team_id']==p['team_id'] and m['role']!='Dev')]
                if paused(p['status']):
                    if hasattr(self,'followup_history'):
                        if i and paused(episodes[i-1]['p']['status']):
                            continue
                        segments=[];j=i
                        while j<len(episodes) and paused(episodes[j]['p']['status']):
                            q=episodes[j]['p'];stop=episodes[j+1]['start'] if j+1<len(episodes) else asof
                            roster=q.get('owners',[])
                            active=[m for m in roster if m['id']==q['member_id'] and m['role']=='Dev' or m['team_id']==q['team_id'] and m['role']=='TPM']
                            segments.append({'start':episodes[j]['start'],'end':stop,'owners':active});j+=1
                        self.followup_history(key,start,segments[-1]['end'],segments,detail['comments'],score_events)
                        continue
                    owners = [m for m in owners if m['role'] in ('Dev', 'TPM')]
                    comment_times = sorted({c['at'] for c in detail['comments'] if c['at'] and start < c['at'] <= end and c['author'] in {m['jira_id'] for m in owners}})
                    for a, b in zip([start]+comment_times, comment_times+[end]):
                        policy = self.policy_at(a) if hasattr(self,'policy_at') else settings
                        self.followup_events(key, a, b, owners, policy, score_events)
                    continue
                rules = self.rows('SELECT * FROM rules WHERE lower(status)=lower(?) AND lower(severity)=lower(?) AND sp=?', (p['status'], p['severity'], p['sp']))
                if hasattr(self,'rules_at'):
                    rules = self.rules_at(p['status'],p['severity'],p['sp'],end)
                if not rules:
                    warnings.append(f'{key}: no duration rule for {p["status"]} / {p["severity"]} / {p["sp"]} SP')
                    continue
                rule = rules[0]
                # Rules are prospective; existing historical scores are not silently backdated.
                anchor, pauses = start, []
                for j in range(i-1, -1, -1):
                    previous = episodes[j]
                    previous_status = previous['p']['status'].casefold()
                    if paused(previous['p']['status']):
                        pauses.append((previous['start'], episodes[j+1]['start']))
                    elif previous_status != p['status'].casefold():
                        break
                    anchor = previous['start']
                if hasattr(self,'rules_at'):
                    boundaries=[r['effective_at'] for r in self.rows('SELECT DISTINCT effective_at FROM rule_versions WHERE effective_at>? AND effective_at<? ORDER BY effective_at',(anchor,end))]
                    for x,y in zip([anchor]+boundaries,boundaries+[end]):
                        version_rules=self.rules_at(p['status'],p['severity'],p['sp'],x)
                        for version in version_rules:
                            for m in owners:
                                self.penalty_events(key,max(anchor,version['created_at']),y,m,version,score_events,pauses,max(start,x))
                else:
                    anchor = max(anchor, rule['created_at'])
                    for m in owners:
                        self.penalty_events(key, anchor, end, m, rule, score_events, pauses, start)
        return {'members': members, 'teams': self.rows('SELECT * FROM teams ORDER BY name'), 'countries': self.rows('SELECT * FROM countries'), 'holidays': self.rows('SELECT * FROM holidays ORDER BY day'), 'rules': self.rows('SELECT * FROM rules'), 'settings': settings, 'tickets': tickets, 'credits': credits, 'score_events': score_events, 'warnings': sorted(set(warnings)), 'imports': self.rows('SELECT id,filename,snapshot_at,created_at FROM imports ORDER BY snapshot_at DESC,id DESC'), 'asof': asof, 'calculation_note': 'Live projections assume the last observed status continues. Exact transitions between exports are unknown.'}

    def penalty_events(self, key, start, end, member, rule, events, pauses=None, effective_start=None):
        if start >= end:
            return
        # Locate each working-day threshold to attribute deductions to the correct month.
        def elapsed_at(at):
            return self.work(start, at, member['country']) - sum(self.work(max(start, a), min(at, b), member['country']) for a, b in (pauses or []) if max(start, a) < min(at, b))
        threshold, elapsed = rule['days'], elapsed_at(end)
        n = 0
        while elapsed > threshold + n + 1e-9:
            low, high = datetime.fromisoformat(start), datetime.fromisoformat(end)
            for _ in range(35):
                mid = low + (high-low)/2
                if elapsed_at(mid.isoformat()) > threshold+n:
                    high = mid
                else:
                    low = mid
            if not effective_start or high.isoformat() >= effective_start:
                events.append({'key': key, 'member_id': member['id'], 'at': high.isoformat(), 'points': -rule['initial'] if n == 0 else -rule['daily'], 'reason': f'{rule["status"]} overdue (rule {rule["id"]})'})
            n += 1

    def followup_events(self, key, start, end, owners, settings, events):
        if not owners:
            return
        a, b = datetime.fromisoformat(start), datetime.fromisoformat(end)
        tz = ZoneInfo('Asia/Amman')
        a, b = a.astimezone(tz), b.astimezone(tz)
        day, elapsed, next_threshold = a.date(), 0.0, settings['followup_days']
        n = 0
        while day <= b.date():
            eligible = [m for m in owners if self.working_day(m['country'], day)]
            low = max(a, datetime.combine(day, datetime.min.time(), tz))
            high = min(b, datetime.combine(day+timedelta(days=1), datetime.min.time(), tz))
            fraction = max(0, (high-low).total_seconds()/86400) if eligible else 0
            while elapsed + fraction > next_threshold + 1e-9:
                at = low + timedelta(days=max(0, next_threshold-elapsed), microseconds=1)
                for m in eligible:
                    events.append({'key': key, 'member_id': m['id'], 'at': at.astimezone(timezone.utc).isoformat(), 'points': -settings['followup_initial'] if n == 0 else -settings['followup_daily'], 'reason': 'Blocked / On Hold follow-up overdue'})
                next_threshold += 1
                n += 1
            elapsed += fraction
            day += timedelta(days=1)
