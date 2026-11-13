"""接口 · Bug 平台：同步、分析、审核、修复、忽略、平台接入。每个接口一个函数，用 @get / @post 注册（见 webapp/router.py）。"""
from webapp.router import get, post  # noqa: F401
from webapp.shared import *  # noqa: F401,F403


@get('/api/zentao/analysis')
def _get_api_zentao_analysis(self, u, q):
    return self._guard(lambda: kb.bug_analysis_view(q.get('id', '')))


@get('/api/zentao/sessions')
def _get_api_zentao_sessions(self, u, q):
    return self._guard(lambda: {'items': list(reversed(kb.an_sessions()))[:20]})


@get('/api/zentao')
def _get_api_zentao(self, u, q):
    return self._guard(lambda: api_zentao(q.get('period', ''), q.get('owner', '')))


@post('/api/zentao/sync')
def _post_api_zentao_sync(self, u, n, body):
    def run():
        if kb.ZT_STATE['running']:
            return {'msg': '正在同步，稍等'}
        threading.Thread(target=lambda: _safe(kb.bug_sync, '用户（网页）', bool(body.get('full')), body.get('source') or ''), daemon=True).start()
        return {'msg': '开始同步，完成后页面自动刷新'}
    return self._guard(run)


@post('/api/zentao/analyze', page_only=True)
def _post_api_zentao_analyze(self, u, n, body):
    return self._guard(lambda: {'msg': kb.bug_analyze_in(body.get('ids') or [], body['repo']) if body.get('repo')
                                else kb.bug_analyze(body.get('ids') or [])})


@post('/api/zentao/fix', page_only=True)
def _post_api_zentao_fix(self, u, n, body):
    return self._guard(lambda: {'msg': kb.bug_fix(body.get('ids') or [], note=body.get('note'))})


@post('/api/zentao/fixed', page_only=True)
def _post_api_zentao_fixed(self, u, n, body):
    return self._guard(lambda: {'msg': kb.bug_fixed(str(body.get('id', '')), body.get('done', True) is not False,
                                                    body.get('commits') or [], body.get('note', ''), by='用户（网页）')})


@post('/api/zentao/svncommit')
def _post_api_zentao_svncommit(self, u, n, body):
    return self._guard(lambda: {'msg': kb.bug_svn_commit(str(body.get('id', '')))})


@post('/api/zentao/unfix', page_only=True)
def _post_api_zentao_unfix(self, u, n, body):
    return self._guard(lambda: {'msg': kb.bug_unfix(str(body.get('id', '')))})


@post('/api/zentao/review', page_only=True)
def _post_api_zentao_review(self, u, n, body):
    return self._guard(lambda: {'msg': kb.bug_review(str(body.get('id', '')), body.get('action', ''), body.get('note', ''))})


@post('/api/zentao/ignore', page_only=True)
def _post_api_zentao_ignore(self, u, n, body):
    return self._guard(lambda: {'msg': kb.bug_ignore(body.get('ids') or [], body.get('on', True) is not False, body.get('note', ''))})


@post('/api/zentao/assign')
def _post_api_zentao_assign(self, u, n, body):
    return self._guard(lambda: {'msg': kb.bug_assign(str(body.get('id', '')), body.get('target', ''), by='用户（网页）',
                                                     bind=body.get('bind', True) is not False)})


@post('/api/zentao/settings', page_only=True)
def _post_api_zentao_settings(self, u, n, body):
    return self._guard(lambda: {'status': kb.save_zentao_settings(
        platform=body.get('platform'), enabled=body.get('enabled'), scope=body.get('scope'), people=body.get('people'),
        source=body.get('source') or '')})


@post('/api/bug/source', page_only=True)
def _post_api_bug_source(self, u, n, body):
    return self._guard(lambda: (lambda r: {'msg': r} if isinstance(r, str) else {'status': r, 'msg': '已保存'})(kb.save_bug_source(
        body.get('id', ''), remove=bool(body.get('remove')), 适配器=body.get('adapter'), 账号条目=body.get('entry'),
        启用=body.get('enabled'), 范围=body.get('scope'), 人员=body.get('people'), 平台=body.get('platform'), 选项=body.get('options'))))


@post('/api/bug/test', page_only=True)
def _post_api_bug_test(self, u, n, body):
    return self._guard(lambda: {'msg': kb.bug_test(body.get('id', ''))})
