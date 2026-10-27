"""Run with: python server.py (open http://127.0.0.1:8765)."""
import argparse
import csv
import json
import mimetypes
import sqlite3
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from tracker import DEFAULT_DB, ROOT
from advanced import Tracker


class StateCache:
    """Short-lived live projections, invalidated by writes and database changes."""
    def __init__(self, ttl=5):
        self.ttl=ttl
        self.invalidate()

    def invalidate(self):
        self.value=None
        self.signature=None
        self.expires=0

    def get(self, tracker):
        def signature():
            values=[]
            for path in (tracker.path,Path(str(tracker.path)+'-wal')):
                try:
                    stat=path.stat();values.append((stat.st_mtime_ns,stat.st_size))
                except FileNotFoundError:
                    values.append(None)
            return (str(tracker.path.resolve()),tuple(values))
        current=signature()
        if self.value is not None and self.signature==current and time.monotonic()<self.expires:
            return self.value
        value=tracker.state()
        if tracker.refresh_records(_state=value):
            value=tracker.state()
            current=signature()
        self.value=value
        self.signature=current
        self.expires=time.monotonic()+self.ttl
        return value


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, value, content_type='application/json'):
        body = json.dumps(value).encode() if content_type == 'application/json' else value
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
            return self.reply(403, {'error': 'Use the localhost application address'})
        parsed = urlparse(self.path)
        if not parsed.path.startswith('/api/'):
            file=(ROOT/'web'/unquote(parsed.path).lstrip('/')).resolve() if parsed.path!='/' else ROOT/'web'/'index.html'
            if not file.is_relative_to(ROOT/'web') or not file.is_file():
                return self.reply(404,{'error':'Not found'})
            return self.reply(200,file.read_bytes(),mimetypes.guess_type(file)[0] or 'application/octet-stream')
        tracker = Tracker(self.server.db_path)
        try:
            if parsed.path == '/api/state':
                self.reply(200, self.server.state_cache.get(tracker))
            elif parsed.path == '/api/config':
                self.reply(200,tracker.configuration())
            elif parsed.path == '/api/ticket':
                self.reply(200, tracker.ticket(parse_qs(parsed.query).get('key', [''])[0]))
            elif parsed.path == '/api/report':
                q=parse_qs(parsed.query)
                self.reply(200,tracker.report(q.get('start_date',[''])[0],q.get('end_date',[''])[0],q.get('team_id',[None])[0],q.get('country',[None])[0],q.get('role',[None])[0],_state=self.server.state_cache.get(tracker)))
            elif parsed.path == '/api/backups':
                self.reply(200,tracker.backups())
            else:
                self.reply(404, {'error': 'Not found'})
        except ValueError as exc:
            self.reply(400, {'error': str(exc)})
        finally:
            tracker.db.close()

    def do_POST(self):
        # Block browser requests originating outside this localhost app (no login).
        host=self.headers.get('Host')
        expected = f'http://{host}'
        if host not in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}') or self.headers.get('Origin') not in (None, expected) or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.reply(403, {'error': 'Use the local application origin and JSON requests'})
        tracker = Tracker(self.server.db_path)
        route=urlparse(self.path).path
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 20 * 1024 * 1024:
                raise ValueError('Request must be between 1 byte and 20 MB')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data,dict):
                raise ValueError('Request body must be a JSON object')
            route = urlparse(self.path).path
            if route in ('/api/import/preview', '/api/import/commit'):
                result = tracker.import_csv(data['csv'], data.get('filename', 'jira.csv'), data['snapshot_at'], data.get('mapping'), route.endswith('preview'))
            elif route == '/api/recalculate':
                self.server.state_cache.invalidate()
                result=self.server.state_cache.get(tracker)
            elif route == '/api/settings':
                tracker.update_settings(data)
                result = {'ok': True}
            elif route == '/api/comments':
                tracker.add_comment(data)
                result = {'ok': True}
            elif route == '/api/comments/revise':
                tracker.revise_comment(data)
                result={'ok':True}
            elif route == '/api/backup':
                result = {'filename': tracker.backup()}
            elif route == '/api/restore':
                tracker.restore(data)
                result={'ok':True}
            elif route == '/api/archive':
                tracker.archive(data)
                result={'ok':True}
            elif route == '/api/holidays/remove':
                tracker.remove_holiday(data)
                result={'ok':True}
            elif route == '/api/corrections':
                tracker.correct(data)
                result={'ok':True}
            elif route == '/api/finalize':
                result={'count':tracker.finalize(data)}
            elif route == '/api/export':
                result=tracker.export(data,_state=self.server.state_cache.get(tracker))
            elif route.startswith('/api/save/'):
                result = {'id': tracker.save(route.rsplit('/', 1)[1], data)}
            else:
                return self.reply(404, {'error': 'Unknown endpoint'})
            self.reply(200, result)
        except (ValueError, KeyError, TypeError, sqlite3.DatabaseError, csv.Error, UnicodeError) as exc:
            message = 'This Jira identity, team name, role slot, holiday or workflow rule already exists. Check your assignments.' if isinstance(exc, sqlite3.IntegrityError) else str(exc)
            self.reply(400, {'error': message})
        finally:
            if route not in ('/api/import/preview','/api/export','/api/recalculate'):
                self.server.state_cache.invalidate()
            tracker.db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--open', action='store_true', help='Open the local application in your browser')
    args = parser.parse_args()
    Tracker(args.db).db.close()
    server = HTTPServer(('127.0.0.1', args.port), Handler)
    server.db_path = args.db
    server.state_cache=StateCache()
    if args.open:
        threading.Timer(0.5,lambda:webbrowser.open(f'http://127.0.0.1:{server.server_port}')).start()
    print(f'OP Tracker: http://127.0.0.1:{args.port} | database: {args.db.resolve()}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
