"""接口 · 开发会话、手机、复测、问题、免打扰、回答 AI 的提问。每个接口一个函数，用 @get / @post 注册（见 webapp/router.py）。"""
from webapp.router import get, post  # noqa: F401
from webapp.shared import *  # noqa: F401,F403


@get('/api/dev/activity')
def _get_api_dev_activity(self, u, q):
    return self._guard(lambda: kb.dev_activity_all(q.get('name', '')))


@get('/api/devices')
def _get_api_devices(self, u, q):
    return self._guard(lambda: {'items': kb.devices() if kb._adb() else None})


@get('/api/dev')
def _get_api_dev(self, u, q):
    return self._guard(lambda: kb.dev_overview(q.get('name', '')))


@post('/api/dev/start', page_only=True)
def _post_api_dev_start(self, u, n, body):
    def run():
        if body.get('confirm', '').strip() != kb.period_dir(body.get('period', '')).name:
            raise kb.KBError('输入的期名不一致，已取消')
        return {'msg': kb.dev_start(body.get('period', ''), body.get('note', ''), body.get('repo', ''),
                                    body.get('branch', ''), bool(body.get('keepBranch')))}
    return self._guard(run)


@post('/api/dev/chat', page_only=True)
def _post_api_dev_chat(self, u, n, body):
    return self._guard(lambda: {'msg': kb.dev_chat(body.get('period', ''), body.get('text', ''), bool(body.get('interrupt')))})


@post('/api/retest', page_only=True)
def _post_api_retest(self, u, n, body):
    return self._guard(lambda: {'msg': kb.retest_start(body.get('period', ''), body.get('scope', ''), body.get('note', ''))})


@post('/api/retest/plan', page_only=True)
def _post_api_retest_plan(self, u, n, body):
    return self._guard(lambda: {'msg': kb.retest_plan(body.get('period', ''), bool(body.get('auto')), body.get('phones') or 1,
                                                      body.get('scope', ''))})


@post('/api/issue', page_only=True)
def _post_api_issue(self, u, n, body):
    return self._guard(lambda: {'msg': kb.set_issue(body.get('period', ''), body.get('id', ''), body.get('status', ''))})


@post('/api/device', page_only=True)
def _post_api_device(self, u, n, body):
    return self._guard(lambda: {'msg': kb.device_mark(body.get('serial', ''), body.get('action', ''))})


@post('/api/dev/stop', page_only=True)
def _post_api_dev_stop(self, u, n, body):
    return self._guard(lambda: {'msg': kb.dev_stop(body.get('period', ''))})


@post('/api/dnd', page_only=True)
def _post_api_dnd(self, u, n, body):
    return self._guard(lambda: {'msg': kb.set_dnd(body.get('period', ''), bool(body.get('on')))})


@post('/api/answer', page_only=True)
def _post_api_answer(self, u, n, body):
    return self._guard(lambda: {'msg': kb.answer(body.get('period', ''), body.get('id', ''), body.get('answer', ''))})
