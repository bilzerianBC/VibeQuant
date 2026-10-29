import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from site_server import update_completion, Handler
from functools import partial
from http.server import ThreadingHTTPServer
import threading
import urllib.request
import urllib.error


class WebsiteCompletionTests(unittest.TestCase):
    def test_http_save_read_and_repeated_click(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ',{'DIPWATCH_EDIT_PASSWORD':'test-password'}):
            root=Path(directory)/'usstockdipwatch'
            root.mkdir()
            (root/'data.json').write_text(json.dumps(dict(assets=[dict(symbol='QQQ',currency='USD',peak=100,
                peakDate='2026-10-09',levels=[dict(tier=10,price=90)])])))
            server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=directory))
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            url=f'http://127.0.0.1:{server.server_port}/usstockdipwatch/'
            try:
                body=json.dumps(dict(id='QQQ:10',completed=True,expectedPrice=90)).encode()
                for _ in range(2):
                    request=urllib.request.Request(url+'api/completions',data=body,headers={'Authorization':'Bearer test-password','Content-Type':'application/json'})
                    with urllib.request.urlopen(request) as response:
                        self.assertEqual(response.status,200)
                with urllib.request.urlopen(url+'completions.json') as response:
                    state=json.load(response)
                self.assertEqual(len(state['records'][0]['history']),1)
                self.assertEqual(state['records'][0]['symbol'],'QQQ')
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    urllib.request.urlopen(urllib.request.Request(url+'api/completions',data=body))
                self.assertEqual(denied.exception.code,401)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_persistent_idempotent_history_and_price_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'data.json').write_text(json.dumps(dict(assets=[dict(symbol='QQQ',currency='USD',
                peak=100,peakDate='2026-10-09',levels=[dict(tier=10,price=90)])])))
            request = dict(id='QQQ:10',completed=True,expectedPrice=90)
            state = update_completion(root,request)
            self.assertEqual(state,update_completion(root,request))
            self.assertEqual(len(state['records'][0]['history']),1)
            self.assertEqual(state['records'][0]['targetPrice'],90)
            state = update_completion(root,dict(request,completed=False))
            self.assertEqual(len(state['records'][0]['history']),1)
            self.assertFalse(state['records'][0]['completed'])
            with self.assertRaises(ValueError):
                update_completion(root,dict(request,expectedPrice=80))
            self.assertEqual(state,json.loads((root/'completions.json').read_text()))

    def test_unknown_symbol_cannot_be_written(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'data.json').write_text('{"assets":[]}')
            with self.assertRaises(ValueError):
                update_completion(root,dict(id='UNKNOWN:10',completed=True,expectedPrice=1))
            self.assertFalse((root/'completions.json').exists())

    def test_unauthorized_write_never_reaches_store(self):
        handler = Handler.__new__(Handler)
        handler.path='/usstockdipwatch/api/completions'
        handler.headers={'Authorization':'Bearer wrong'}
        with patch.dict('os.environ',{'DIPWATCH_EDIT_PASSWORD':'test-password'}), patch.object(handler,'reply') as reply, patch('site_server.update_completion') as update:
            handler.do_POST()
            self.assertEqual(reply.call_args.args[0],401)
            update.assert_not_called()
