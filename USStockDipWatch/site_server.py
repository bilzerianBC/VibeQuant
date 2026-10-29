"""Existing static portal plus password-protected, server-owned completion records."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import fcntl
import hmac
import json
import math
import os
from pathlib import Path
from datetime import datetime, timezone
from collect import atomic_json
from reminder_state import targets, merge


def update_completion(root, payload):
    if not isinstance(payload, dict) or type(payload.get('completed')) is not bool:
        raise ValueError('请求格式错误')
    path = root / 'completions.json'
    with (root / '.completion.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(path.read_text()) if path.exists() else {}
        old = next((r for r in state.get('records', []) if r['id'] == payload.get('id')), None)
        current = targets(json.loads((root / 'data.json').read_text()))
        target = next((r for r in current if r['id'] == payload.get('id')), None)
        if not target and not old:
            raise ValueError('该标的暂无有效目标价')
        if old and old['completed'] == payload['completed']:
            return state
        if payload['completed']:
            if not target:
                raise ValueError('行情无效，暂不能记录新的完成事项')
            shown = payload.get('expectedPrice')
            if not isinstance(shown, (int,float)) or not math.isclose(shown, target['targetPrice'], abs_tol=1e-8):
                raise ValueError('目标价已变化，请刷新后重新勾选')
        item = dict(target or old, completed=payload['completed'],
                    completedAt=datetime.now(timezone.utc).isoformat() if payload['completed'] else None)
        state = merge(state, [item])
        atomic_json(path, state)
        return state


class Handler(SimpleHTTPRequestHandler):
    def reply(self, status, value):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path not in ('/usstockdipwatch/api/auth', '/usstockdipwatch/api/completions'):
            return self.reply(404, dict(error='接口不存在'))
        password = os.environ.get('DIPWATCH_EDIT_PASSWORD', '')
        if not password:
            return self.reply(503, dict(error='请先配置网站操作密码'))
        provided = self.headers.get('Authorization', '').removeprefix('Bearer ')
        if not hmac.compare_digest(provided.encode(), password.encode()):
            return self.reply(401, dict(error='操作密码不正确'))
        if self.path.endswith('/auth'):
            return self.reply(200, dict(ok=True))
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 2048:
                raise ValueError('请求大小不合法')
            data = json.loads(self.rfile.read(length))
            state = update_completion(Path(self.directory)/'usstockdipwatch', data)
            self.reply(200, state)
        except (ValueError, TypeError):
            self.reply(400, dict(error='目标价或操作无效，请刷新后重试'))
        except OSError:
            self.reply(500, dict(error='保存失败，请稍后重试'))

    def list_directory(self, path):
        self.send_error(403)

    def do_GET(self):
        if any(p.startswith('.') for p in self.path.split('/') if p not in ('', '.')):
            return self.send_error(404)
        super().do_GET()


if __name__ == '__main__':
    root = os.environ.get('VIBEQUANT_SITE_DIR', '/srv/web')
    ThreadingHTTPServer(('0.0.0.0', 8000), partial(Handler, directory=root)).serve_forever()
