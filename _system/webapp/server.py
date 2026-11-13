"""网页服务：请求处理器（鉴权、本人操作检查、按注册表分发）和启动（后台循环）。接口本身在 webapp/routes/。"""
import importlib
import json

from webapp.shared import *  # noqa: F401,F403
from webapp import router

ROUTE_MODULES = ['static', 'periods', 'dev', 'stack', 'bugs', 'anr', 'plugins', 'settings', 'base', 'steward']
for _m in ROUTE_MODULES:
    importlib.import_module(f'webapp.routes.{_m}')


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _guard(self, fn):
        try:
            self._send(200, fn())
        except kb.KBNeed as e:
            self._send(409, {'error': str(e), 'need': e.data})
        except kb.KBError as e:
            self._send(400, {'error': str(e)})
        except Exception as e:
            self._send(500, {'error': repr(e)})

    def _events(self):
        q = queue.Queue()
        with _SUBS_LOCK:
            _SUBS.add(q)
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(b'retry: 3000\n\n')
            self.wfile.flush()
            while True:
                try:
                    ev = q.get(timeout=20)
                    self.wfile.write(f'data: {json.dumps(ev, ensure_ascii=False)}\n\n'.encode())
                except queue.Empty:
                    self.wfile.write(b': ping\n\n')     # 保活，也用来发现浏览器已关闭
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with _SUBS_LOCK:
                _SUBS.discard(q)

    def _from_page(self):
        # 开始/停止开发、回答、免打扰只接受本页面发起的请求（浏览器必带 Origin）
        origin = self.headers.get('Origin', '')
        return bool(origin) and origin.endswith('//' + self.headers.get('Host', ''))

    def _mcp(self, n):
        auth = self.headers.get('Authorization', '')
        tok = auth[7:] if auth.startswith('Bearer ') else ''
        sess = kb.remote_session(tok) if tok else None
        if not sess and kb.check_token(tok):
            sess = {}                                   # kb token 生成的令牌：普通用户身份，不属于某个后台会话
        if sess is None:
            return self._send(401, {'error': '令牌无效：远处的 Claude Code 用 kb token add 生成的令牌；'
                                             '各端远程会话的令牌在网页服务重启后失效，到期页面重新开工这个端'})
        try:
            msg = json.loads(self.rfile.read(n) or b'{}')
        except ValueError:
            return self._send(400, {'error': 'bad json'})
        from kblib.api import mcp as _m
        from kblib.core.common import with_sess_env
        env = {'KB_PERIOD': sess['KB_PERIOD'], 'KB_SESSION': sess['KB_SESSION']} if sess else {'KB_SESSION': '', 'KB_PERIOD': ''}
        if isinstance(msg, list):
            out = [r for r in (with_sess_env(env, _m.handle, x) for x in msg) if r is not None]
        else:
            out = with_sess_env(env, _m.handle, msg)
        if out is None or out == []:
            self.send_response(202)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        return self._send(200, out)

    def _local_only(self):
        # 防止其他网页跨站调用写接口
        origin = self.headers.get('Origin', '')
        host = self.headers.get('Host', '')
        return not origin or origin.endswith('//' + host)

    def _cookie(self):
        c = SimpleCookie(self.headers.get('Cookie', ''))
        return c['kb_s'].value if 'kb_s' in c else ''

    def _authed(self):
        return not kb.auth_required() or kb.check_session(self._cookie())

    def _https(self):
        return self.headers.get('X-Forwarded-Proto', '') == 'https'

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == '/login':
            return self._send(200, LOGIN_PAGE, 'text/html; charset=utf-8')
        if not self._authed():
            if u.path == '/':
                self.send_response(302)
                self.send_header('Location', '/login')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            return self._send(401, {'error': '要先登录', 'login': True})
        if u.path.startswith('/ui/'):                    # 共用功能层和各套界面模板的静态文件
            r = ui_file(u.path[4:])
            return self._send(200, *r) if r else self._send(404, {'error': 'not found'})
        r = router.find('GET', u.path)
        if not r:
            return self._send(404, {'error': 'not found'})
        return r.fn(self, u, q)

    def do_POST(self):
        if not self._local_only():
            return self._send(403, {'error': 'forbidden'})
        u = urlparse(self.path)
        n = int(self.headers.get('Content-Length') or 0)
        if u.path == '/mcp':           # 远程机器上的会话（开工时发的令牌）、远处的 Claude Code（kb token 生成的令牌）
            return self._mcp(n)
        if u.path == '/api/login':
            try:
                pw = (json.loads(self.rfile.read(n) or b'{}') or {}).get('password', '')
                t = kb.web_login(pw)
            except (ValueError, kb.KBError) as e:
                return self._send(403, {'error': str(e) if isinstance(e, kb.KBError) else 'bad json'})
            body = json.dumps({'msg': '已登录'}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Set-Cookie', f'kb_s={t}; Path=/; HttpOnly; SameSite=Strict; Max-Age={kb.SESS_DAYS * 86400}'
                             + ('; Secure' if self._https() else ''))
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if u.path == '/api/logout':
            kb.web_logout(self._cookie())
            self.send_response(200)
            self.send_header('Set-Cookie', 'kb_s=; Path=/; Max-Age=0')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if not self._authed():
            return self._send(401, {'error': '要先登录', 'login': True})
        r = router.find('POST', u.path)
        if not r:
            return self._send(404, {'error': 'not found'})
        if r.page_only and not self._from_page():
            return self._send(403, {'error': '只能在知识库网页上由本人操作'})
        if r.raw:
            return r.fn(self, u, n, None)
        try:
            body = json.loads(self.rfile.read(n) or b'{}')
        except ValueError:
            return self._send(400, {'error': '请求体不是 JSON'})
        return r.fn(self, u, n, body)


def main(port=11555, host=''):
    kb.init()
    host = host or os.environ.get('KB_HOST') or '127.0.0.1'
    try:
        kb.check_bind(host)
    except kb.KBError as e:
        print(f'没有启动：{e}', flush=True)
        sys.exit(2)
    os.environ['KB_WEB_PORT'] = str(port)        # 各端远程会话的 ssh 反向通道连这个端口
    kb.stackdev_port(port)
    srv = ThreadingHTTPServer((host, port), H)
    print(f'知识库网页：http://{host}:{port}' + ('（已开启访问密码）' if kb.auth_required() else ''), flush=True)
    kb.dev_reattach()
    threading.Thread(target=watcher, daemon=True).start()
    threading.Thread(target=dev_tick, daemon=True).start()
    if kb.ZT_HOURS > 0:
        kb.ZT_STATE['next'] = time.strftime('%Y-%m-%d %H:%M', time.localtime(time.time() + 120))
        threading.Thread(target=zentao_auto, daemon=True).start()
    if STEWARD_MIN > 0:
        threading.Thread(target=steward_auto, daemon=True).start()
    if REFRESH_HOURS > 0:
        AUTO['next'] = time.strftime('%Y-%m-%d %H:%M', time.localtime(time.time() + 300))
        threading.Thread(target=auto_refresh, daemon=True).start()
    srv.serve_forever()

