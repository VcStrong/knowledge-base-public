"""接口 · 期 / 事项、资料、记录、检索、模糊添加。每个接口一个函数，用 @get / @post 注册（见 webapp/router.py）。"""
from webapp.router import get, post  # noqa: F401
from webapp.shared import *  # noqa: F401,F403


@get('/api/events')
def _get_api_events(self, u, q):
    return self._events()


@get('/api/overview')
def _get_api_overview(self, u, q):
    return self._guard(api_overview)


@get('/api/period')
def _get_api_period(self, u, q):
    return self._guard(lambda: api_period(q.get('name', '')))


@get('/api/adds')
def _get_api_adds(self, u, q):
    return self._guard(lambda: {'items': kb.add_sessions()})


@get('/api/task/memo')
def _get_api_task_memo(self, u, q):
    return self._guard(lambda: kb.task_memo(q.get('name', '')))


@get('/api/repos/choices')
def _get_api_repos_choices(self, u, q):
    return self._guard(lambda: {'items': kb.repo_choices()})


@get('/api/period/talk')
def _get_api_period_talk(self, u, q):
    return self._guard(lambda: kb.period_talk(q.get('name', '')))


@get('/api/search')
def _get_api_search(self, u, q):
    return self._guard(lambda: dict(zip(('hits', 'mode'), kb.search_hits(
        q.get('q', ''), q.get('period') or None, q.get('cat') or None,
        q.get('scope', 'all'), None, int(q.get('limit', 30))))))


@get('/api/read')
def _get_api_read(self, u, q):
    return self._guard(lambda: {'text': kb.read_file(q.get('path', ''), int(q.get('start', 1)), 3000)})


@post('/api/upload', raw=True)
def _post_api_upload(self, u, n, body):
    period = unquote(self.headers.get('X-Period', ''))
    cat = unquote(self.headers.get('X-Category', '')) or None
    fname = kb.safe_name(unquote(self.headers.get('X-Filename', '')))
    tmp = kb.SYS / 'tmp' / uuid.uuid4().hex
    tmp.mkdir(parents=True)
    f = tmp / fname
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
            return {'msg': kb.add_material(period, f, cat, '网页上传')}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return self._guard(run)


@post('/api/task/nav', page_only=True)
def _post_api_task_nav(self, u, n, body):
    return self._guard(lambda: {'msg': kb.task_nav(body.get('period', ''), bool(body.get('show')))})


@post('/api/task/item', page_only=True)
def _post_api_task_item(self, u, n, body):
    def run():
        p, k, act = body.get('period', ''), body.get('key', ''), body.get('action', '')
        if act == 'add':
            return {'msg': kb.task_item_add(p, body.get('text', ''))}
        if act == 'delete':
            return {'msg': kb.task_item_delete(p, k)}
        if act == 'repo':
            return {'msg': '；'.join(kb._setup_task(p, '', body.get('text', ''), '用户（网页）')) or '没有变化'}
        if act == 'push':
            return {'msg': kb.task_item_push(p, k, body.get('text', ''))}
        return {'msg': kb.task_item_set(p, k, body.get('status', ''), body.get('text', ''), by='用户（网页）')}
    return self._guard(run)


@post('/api/task/push', page_only=True)
def _post_api_task_push(self, u, n, body):
    return self._guard(lambda: {'msg': kb.task_push(body.get('period', ''), body.get('text', ''))})


@post('/api/period/say', page_only=True)
def _post_api_period_say(self, u, n, body):
    return self._guard(lambda: {'msg': kb.period_say(body.get('period', ''), body.get('text', ''), body.get('target', ''),
                                                     body.get('interrupt', True) is not False, mode=body.get('mode') or 'insert')})


@post('/api/new')
def _post_api_new(self, u, n, body):
    return self._guard(lambda: {'msg': kb.create_period(body.get('name', ''), body.get('summary', ''))})


@post('/api/task')
def _post_api_task(self, u, n, body):
    return self._guard(lambda: {'msg': kb.create_task(body.get('name', ''), body.get('summary', ''), body.get('kind', ''),
                                                      body.get('source', ''), body.get('priority', ''), body.get('bugs'),
                                                      by='用户（网页）'), 'name': kb.safe_name(body.get('name', ''))})


@post('/api/period/delete', page_only=True)
def _post_api_period_delete(self, u, n, body):
    def run():
        if body.get('confirm', '').strip() != kb.period_dir(body.get('period', '')).name:
            raise kb.KBError('输入的名称不一致，没有删除')
        return {'msg': kb.delete_period(body.get('period', ''))}
    return self._guard(run)


@post('/api/task/meta')
def _post_api_task_meta(self, u, n, body):
    return self._guard(lambda: {'msg': kb.update_task(body.get('period', ''), body.get('kind'), body.get('source'),
                                                      body.get('priority'), body.get('summary'))})


@post('/api/inbox')
def _post_api_inbox(self, u, n, body):
    def run():
        fs = [p for p in kb.INBOX.iterdir() if not p.name.startswith('.')]
        names = body.get('files')
        fs = [p for p in fs if not names or p.name in names]
        return {'msg': '\n'.join(kb.add_material(body.get('period', ''), p) for p in fs) or '收件箱是空的'}
    return self._guard(run)


@post('/api/note')
def _post_api_note(self, u, n, body):
    def run():
        f = {k: body.get(k) for k in ('content', 'category', 'kind', 'title', 'url', 'source')}
        if not body.get('id'):
            msg = kb.add_note(body.get('period', ''), **f)
            new, olds = kb.design_conflicts(body.get('period', ''), f'{f["url"] or ""} {f["content"] or ""}')
            return {'msg': msg, 'new': new, 'replace': olds}
        return {'msg': kb.update_note(body.get('period', ''), body['id'], bool(body.get('delete')),
                                      内容=f['content'], 分类=f['category'], 类型=f['kind'],
                                      标题=f['title'], 链接=f['url'], 来自=f['source'])}
    return self._guard(run)


@post('/api/log')
def _post_api_log(self, u, n, body):
    return self._guard(lambda: {'msg': kb.add_log(body.get('period', ''), body.get('note', ''))})


@post('/api/status')
def _post_api_status(self, u, n, body):
    def run():
        if body.get('status') == '已批准开发':
            raise kb.KBError('批准开发请在终端运行 kb approve')
        return {'msg': kb.set_status(body.get('period', ''), body.get('status', ''), body.get('note', ''),
                                     by_human=True)}
    return self._guard(run)


@post('/api/verify')
def _post_api_verify(self, u, n, body):
    return self._guard(lambda: {'msg': kb.verify_source(body.get('period', ''), body.get('sid', ''),
                                                        body.get('status', ''), body.get('note', ''))})


@post('/api/fixlink')
def _post_api_fixlink(self, u, n, body):
    return self._guard(lambda: {'msg': kb.fix_link(body.get('period', ''), body.get('old', ''), body.get('new', ''),
                                                   body.get('reason', ''), by='用户（网页）')})


@post('/api/refresh')
def _post_api_refresh(self, u, n, body):
    return self._guard(lambda: {'msg': kb.refresh_sources(body.get('period', ''), body.get('sid', ''), by='用户（网页）')})


@post('/api/refresh/claude', page_only=True)
def _post_api_refresh_claude(self, u, n, body):
    return self._guard(lambda: {'msg': kb.claude_update(body.get('period', ''))})


@post('/api/add', page_only=True)
def _post_api_add(self, u, n, body):
    return self._guard(lambda: {'msg': kb.claude_add(body.get('text', ''), body.get('period', ''))})


@post('/api/reindex')
def _post_api_reindex(self, u, n, body):
    return self._guard(lambda: {'msg': kb.reindex(body.get('target', 'all'))})
