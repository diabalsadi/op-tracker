"""Run with: python server.py (open http://127.0.0.1:8765)."""
import argparse
import json
import mimetypes
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from tracker import DEFAULT_DB, ROOT, Tracker


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
        tracker = Tracker(self.server.db_path)
        try:
            if parsed.path == '/api/state':
                self.reply(200, tracker.state())
            elif parsed.path == '/api/ticket':
                self.reply(200, tracker.ticket(parse_qs(parsed.query).get('key', [''])[0]))
            else:
                file = (ROOT / 'web' / unquote(parsed.path).lstrip('/')).resolve() if parsed.path != '/' else ROOT / 'web' / 'index.html'
                if not file.is_relative_to(ROOT / 'web') or not file.is_file():
                    self.reply(404, {'error': 'Not found'})
                else:
                    self.reply(200, file.read_bytes(), mimetypes.guess_type(file)[0] or 'application/octet-stream')
        except ValueError as exc:
            self.reply(400, {'error': str(exc)})
        finally:
            tracker.db.close()

    def do_POST(self):
        # Block browser requests originating outside this localhost app (no login).
        expected = f'http://127.0.0.1:{self.server.server_port}'
        if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}' or self.headers.get('Origin') not in (None, expected) or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.reply(403, {'error': 'Use the local application origin and JSON requests'})
        tracker = Tracker(self.server.db_path)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 20 * 1024 * 1024:
                raise ValueError('Request must be between 1 byte and 20 MB')
            data = json.loads(self.rfile.read(size))
            route = urlparse(self.path).path
            if route in ('/api/import/preview', '/api/import/commit'):
                result = tracker.import_csv(data['csv'], data.get('filename', 'jira.csv'), data['snapshot_at'], data.get('mapping'), route.endswith('preview'))
            elif route == '/api/settings':
                tracker.update_settings(data)
                result = {'ok': True}
            elif route == '/api/comments':
                tracker.add_comment(data)
                result = {'ok': True}
            elif route == '/api/backup':
                result = {'filename': tracker.backup()}
            elif route.startswith('/api/save/'):
                result = {'id': tracker.save(route.rsplit('/', 1)[1], data)}
            else:
                return self.reply(404, {'error': 'Unknown endpoint'})
            self.reply(200, result)
        except (ValueError, KeyError, TypeError, sqlite3.IntegrityError) as exc:
            message = 'This Jira identity, team name, role slot, holiday or workflow rule already exists. Check your assignments.' if isinstance(exc, sqlite3.IntegrityError) else str(exc)
            self.reply(400, {'error': message})
        finally:
            tracker.db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    Tracker(args.db).db.close()
    server = HTTPServer(('127.0.0.1', args.port), Handler)
    server.db_path = args.db
    print(f'OP Tracker: http://127.0.0.1:{args.port} | database: {args.db.resolve()}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
