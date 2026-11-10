# From 大大王.DT
"""禅道 REST 接口（/api.php/v1）客户端：只负责登录和读写请求，不落盘。

凭据由调用方传入（知识库从基础知识库读取，密码在钥匙串），令牌只留在内存里。
"""
import json
import urllib.error
import urllib.request
from urllib.parse import urlencode

UA = 'kb-local/1.0'


class ZentaoError(Exception):
    pass


class Zentao:
    def __init__(self, base, account, password, timeout=20):
        self.base = base.rstrip('/')
        self.account, self._pw = account, password
        self.timeout = timeout
        self.token = ''

    # ---- 底层
    def _req(self, method, path, params=None, body=None, auth=True):
        url = f'{self.base}/api.php/v1/{path.lstrip("/")}'
        if params:
            url += ('&' if '?' in url else '?') + urlencode({k: v for k, v in params.items() if v not in (None, '')})
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header('User-Agent', UA)
        req.add_header('Content-Type', 'application/json')
        if auth:
            if not self.token:
                self.login()
            req.add_header('Token', self.token)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
            if e.code == 401 and auth and self.token:      # 令牌过期：重新登录一次
                self.token = ''
                return self._req(method, path, params, body, auth)
            raise ZentaoError(f'禅道接口 {method} {path} 返回 {e.code}：{raw[:200].decode("utf-8", "replace")}')
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ZentaoError(f'连不上禅道（{self.base}）：{e}')
        try:
            return json.loads(raw.decode('utf-8', 'replace'))
        except ValueError:
            raise ZentaoError(f'禅道接口 {path} 返回的不是 JSON：{raw[:200].decode("utf-8", "replace")}')

    def login(self):
        r = self._req('POST', 'tokens', body={'account': self.account, 'password': self._pw}, auth=False)
        tok = isinstance(r, dict) and r.get('token')
        if not tok:
            msg = r.get('error') or r.get('message') if isinstance(r, dict) else r
            raise ZentaoError(f'禅道登录失败：{msg}')
        self.token = tok
        return tok

    def get(self, path, **params):
        return self._req('GET', path, params)

    def post(self, path, body):
        return self._req('POST', path, body=body)

    # ---- 常用
    def pages(self, path, key, limit=100, max_pages=50, stop=None, **params):
        """翻页取列表；stop(item) 返回 True 时提前结束（按修改时间倒序增量同步用）。"""
        for page in range(1, max_pages + 1):
            r = self.get(path, page=page, limit=limit, **params)
            items = (r.get(key) if isinstance(r, dict) else None) or []
            for it in items:
                if stop and stop(it):
                    return
                yield it
            total = int(r.get('total') or 0) if isinstance(r, dict) else 0
            if len(items) < limit or (total and page * limit >= total):
                return

    def products(self):
        return list(self.pages('products', 'products', limit=500))

    def bug(self, bid):
        return self.get(f'bugs/{bid}')

    def bug_url(self, bid):
        return f'{self.base}/bug-view-{bid}.html'

    def file_url(self, fid):
        return f'{self.base}/api.php/v1/files/{fid}'      # 带 Token 头就能下载（网页地址要会话登录）
