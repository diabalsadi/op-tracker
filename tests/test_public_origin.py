import tempfile
import threading
import unittest
import json
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path
from server import Handler, StateCache
from advanced import Tracker


class PublicOriginTests(unittest.TestCase):
    def test_tunnel_reads_writes_and_origin_guards(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'tracker.sqlite3'
            Tracker(path).db.close()
            server=HTTPServer(('127.0.0.1',0),Handler)
            server.db_path=path;server.state_cache=StateCache()
            server.public_origins=['https://example.ngrok-free.app']
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            def request(method,path,host,origin=None,data=None):
                conn=HTTPConnection('127.0.0.1',server.server_port)
                headers={'Host':host,'Content-Type':'application/json'}
                if origin:headers['Origin']=origin
                conn.request(method,path,body=json.dumps(data) if data else None,headers=headers)
                response=conn.getresponse();status=response.status;response.read();conn.close();return status
            try:
                self.assertEqual(request('GET','/','example.ngrok-free.app'),200)
                self.assertEqual(request('POST','/api/save/teams','example.ngrok-free.app','https://example.ngrok-free.app',{'name':'Example team'}),200)
                self.assertEqual(request('POST','/api/save/teams','example.ngrok-free.app','https://other.example',{'name':'Rejected'}),403)
                self.assertEqual(request('GET','/','unlisted.ngrok-free.app'),403)
                self.assertEqual(request('GET','/',f'localhost:{server.server_port}'),200)
                self.assertEqual(request('POST','/api/save/teams','example.ngrok-free.app','http://example.ngrok-free.app',{'name':'Rejected'}),403)
            finally:
                server.shutdown();thread.join();server.server_close()
