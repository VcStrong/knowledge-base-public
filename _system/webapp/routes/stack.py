"""接口 · 全栈：各端仓库、出方案、拍板、开工、变更、验收。每个接口一个函数，用 @get / @post 注册（见 webapp/router.py）。"""
from webapp.router import get, post  # noqa: F401
from webapp.shared import *  # noqa: F401,F403


@get('/api/stack')
def _get_api_stack(self, u, q):
    return self._guard(lambda: kb.stack_get(q.get('name', '')))


@get('/api/stack/repos')
def _get_api_stack_repos(self, u, q):
    return self._guard(lambda: {'items': kb.stack_repos(), 'ends': list(kb.ENDS)})


@get('/api/stack/branches')
def _get_api_stack_branches(self, u, q):
    return self._guard(lambda: kb.stack_branches(q.get('repo', '')))


@post('/api/stack/end', page_only=True)
def _post_api_stack_end(self, u, n, body):
    return self._guard(lambda: {'msg': kb.stack_set_end(body.get('period', ''), body.get('end', ''), body.get('repo', ''), body.get('branch', ''))})


@post('/api/stack/plan', page_only=True)
def _post_api_stack_plan(self, u, n, body):
    return self._guard(lambda: {'msg': kb.stack_plan_start(body.get('period', ''), body.get('note', ''))})


@post('/api/stack/change', page_only=True)
def _post_api_stack_change(self, u, n, body):
    return self._guard(lambda: {'msg': kb.stack_change_add(body.get('period', ''), body.get('title', ''), body.get('detail', ''), body.get('ends') or [])})


@post('/api/stack/reject', page_only=True)
def _post_api_stack_reject(self, u, n, body):
    return self._guard(lambda: {'msg': kb.stack_change_reject(body.get('period', ''), body.get('id', ''))})


@post('/api/stack/accept', page_only=True)
def _post_api_stack_accept(self, u, n, body):
    return self._guard(lambda: {'msg': kb.stack_accept(body.get('period', ''))})


@post('/api/stack/dev', page_only=True)
def _post_api_stack_dev(self, u, n, body):
    return self._guard(lambda: {'msg': kb.stack_dev_start(body.get('period', ''), body.get('end', ''))})


@post('/api/stack/stop', page_only=True)
def _post_api_stack_stop(self, u, n, body):
    return self._guard(lambda: {'msg': kb.stack_dev_stop(body.get('period', ''), body.get('end', ''))})


@post('/api/stack/approve', page_only=True)
def _post_api_stack_approve(self, u, n, body):
    return self._guard(lambda: {'msg': kb.stack_approve(body.get('period', ''))})
