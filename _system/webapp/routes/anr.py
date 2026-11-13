"""接口 · ANR / 崩溃：自建问题、上传、mapping、批次。每个接口一个函数，用 @get / @post 注册（见 webapp/router.py）。"""
from webapp.router import get, post  # noqa: F401
from webapp.shared import *  # noqa: F401,F403


@get('/api/anr')
def _get_api_anr(self, u, q):
    return self._guard(kb.anr_json)


@post('/api/anr/stage', '/api/chat/stage', raw=True)
def _post_api_anr_stage(self, u, n, body):
    if not self._from_page():
        return self._send(403, {'error': '只能在知识库网页上由本人操作'})
    sid = uuid.uuid4().hex
    d = kb.SYS / 'tmp' / ('chat-stage' if u.path == '/api/chat/stage' else 'anr-stage') / sid
    d.mkdir(parents=True)
    f = d / (kb.safe_name(unquote(self.headers.get('X-Filename', ''))) or 'log.txt')
    with f.open('wb') as fp:
        left = n
        while left > 0:
            chunk = self.rfile.read(min(left, 1 << 20))
            if not chunk:
                break
            fp.write(chunk)
            left -= len(chunk)
    return self._send(200, {'id': sid})


@post('/api/anr/upload', raw=True)
def _post_api_anr_upload(self, u, n, body):
    h = lambda k: unquote(self.headers.get(k, ''))
    tmp = kb.SYS / 'tmp' / uuid.uuid4().hex
    tmp.mkdir(parents=True)
    f = tmp / (kb.safe_name(h('X-Filename')) or 'log.txt')
    with f.open('wb') as fp:
        left = n
        while left > 0:
            chunk = self.rfile.read(min(left, 1 << 20))
            if not chunk:
                break
            fp.write(chunk)
            left -= len(chunk)

    def run():
        try:
            if h('X-Kind') == 'mapping':
                return {'msg': kb.anr_mapping(h('X-Version'), f, by='用户（网页）')}
            return {'msg': kb.anr_add([f], h('X-Version'), h('X-Source'), h('X-Task'), by='用户（网页）')}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return self._guard(run)


@post('/api/anr/batch', page_only=True)
def _post_api_anr_batch(self, u, n, body):
    return self._guard(lambda: {'msg': kb.anr_batch(body.get('ids') or [], body.get('task', ''), body.get('name', ''))})


@post('/api/anr/automap', page_only=True)
def _post_api_anr_automap(self, u, n, body):
    return self._guard(lambda: {'msg': kb.anr_auto_mapping(body.get('version', ''), by='用户（网页）')
                                or f'各期的构建里没找到版本 {body.get("version", "")} 的 mapping'})


@post('/api/anr/mapping-url', page_only=True)
def _post_api_anr_mapping_url(self, u, n, body):
    return self._guard(lambda: {'msg': kb.anr_mapping_url(body.get('version', ''), body.get('url', ''))})


@post('/api/anr/create', page_only=True)
def _post_api_anr_create(self, u, n, body):
    def run():
        root = kb.SYS / 'tmp' / 'anr-stage'
        staged = lambda i: next((root / i).iterdir()) if re.fullmatch(r'[0-9a-f]{32}', i or '') and (root / i).is_dir() else None
        files = [staged(i) for i in body.get('files') or []]
        mp = staged(body.get('mappingFile') or '')
        try:
            return {'msg': kb.anr_create(body.get('text', ''), [f for f in files if f], body.get('title', ''),
                                         body.get('version', ''), body.get('source', ''), body.get('task', ''),
                                         body.get('note', ''), body.get('mappingUrl', ''), mp or '',
                                         task_name=body.get('taskName', ''), branch=body.get('branch', ''),
                                         repo=body.get('repo', ''))}
        finally:
            for i in (body.get('files') or []) + [body.get('mappingFile') or '']:
                if re.fullmatch(r'[0-9a-f]{32}', i or ''):
                    shutil.rmtree(root / i, ignore_errors=True)
    return self._guard(run)


@post('/api/anr/link')
def _post_api_anr_link(self, u, n, body):
    def run():
        out = []
        if body.get('version'):
            out.append(kb.anr_set_version(body.get('id', ''), body['version'], by='用户（网页）'))
        if any(k in body for k in ('task', 'status', 'note')):
            out.append(kb.anr_link(body.get('id', ''), body.get('task'), body.get('status'), body.get('note')))
        return {'msg': '\n'.join(out) or '没有变化'}
    return self._guard(run)


@post('/api/anr/delete')
def _post_api_anr_delete(self, u, n, body):
    return self._guard(lambda: {'msg': kb.anr_delete_sample(body.get('sample', ''))})
