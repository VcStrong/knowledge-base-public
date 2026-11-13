"""接口 · 管家、交给管家、智能状态、界面模板、引导、目录浏览。每个接口一个函数，用 @get / @post 注册（见 webapp/router.py）。"""
from webapp.router import get, post  # noqa: F401
from webapp.shared import *  # noqa: F401,F403


@get('/api/onboard')
def _get_api_onboard(self, u, q):
    return self._guard(kb.onboard_status)


@get('/api/fs/dirs')
def _get_api_fs_dirs(self, u, q):
    return self._guard(lambda: kb.dir_list(q.get('path', '')))


@get('/api/onboard/scan')
def _get_api_onboard_scan(self, u, q):
    return self._guard(lambda: {'items': kb.repo_scan()})


@get('/api/brief')
def _get_api_brief(self, u, q):
    return self._guard(kb.brief)


@get('/api/intake/preview')
def _get_api_intake_preview(self, u, q):
    return self._guard(lambda: kb.preview(q.get('text', '')))


@get('/api/ui')
def _get_api_ui(self, u, q):
    return self._guard(lambda: {'模板': kb.ui_template(), '列表': [{k: x[k] for k in ('名称', '说明', '目录')} for x in kb.ui_templates()]})


@get('/api/site')
def _get_api_site(self, u, q):
    return self._guard(lambda: kb.site_nav(api_overview(), api_docs()['docs'], full=q.get('full') == '1'))


@get('/api/chat')
def _get_api_chat(self, u, q):
    return self._guard(kb.steward_chat)


@get('/api/steward')
def _get_api_steward(self, u, q):
    return self._guard(kb.steward_view)


@post('/api/onboard/repos', page_only=True)
def _post_api_onboard_repos(self, u, n, body):
    return self._guard(lambda: {'msg': kb.onboard_add_repos(body.get('paths') or [])})


@post('/api/demo', page_only=True)
def _post_api_demo(self, u, n, body):
    return self._guard(lambda: {'msg': kb.demo_create(), 'name': kb.DEMO})


@post('/api/onboard/hide', page_only=True)
def _post_api_onboard_hide(self, u, n, body):
    return self._guard(lambda: {'msg': kb.onboard_hide(body.get('hide', True) is not False)})


@post('/api/chat/ask', page_only=True)
def _post_api_chat_ask(self, u, n, body):
    def ask():
        root = kb.SYS / 'tmp' / 'chat-stage'
        files = [next((root / i).iterdir()) for i in body.get('files') or []
                 if re.fullmatch(r'[0-9a-f]{32}', i or '') and (root / i).is_dir()]
        return {'id': kb.steward_ask(body.get('text', ''), body.get('page', ''), files=files)}
    return self._guard(ask)


@post('/api/brief/act', page_only=True)
def _post_api_brief_act(self, u, n, body):
    return self._guard(lambda: {'msg': kb.brief_act(body.get('id', ''), body.get('action', ''), body.get('value', ''),
                                                    body.get('repo', ''), body.get('branch', ''))})


@post('/api/ui/template', page_only=True)
def _post_api_ui_template(self, u, n, body):
    return self._guard(lambda: {'msg': kb.set_ui_template(body.get('name', ''))})


@post('/api/chat/confirm', page_only=True)
def _post_api_chat_confirm(self, u, n, body):
    return self._guard(lambda: {'msg': kb.chat_confirm(body.get('id', ''), body.get('repo', ''), body.get('branch', ''))})


@post('/api/chat/clear', page_only=True)
def _post_api_chat_clear(self, u, n, body):
    return self._guard(lambda: {'msg': kb.steward_chat_clear()})


@post('/api/chat/rule', page_only=True)
def _post_api_chat_rule(self, u, n, body):
    return self._guard(lambda: {'msg': kb.steward_rule(body.get('text', ''), body.get('delete', ''), by='用户（网页）')})


@post('/api/steward/settings', page_only=True)
def _post_api_steward_settings(self, u, n, body):
    return self._guard(lambda: {'msg': kb.steward_set(body.get('on'), body.get('level'), body.get('limit'), body.get('actions'), body.get('new_days'))})


@post('/api/steward/dismiss', page_only=True)
def _post_api_steward_dismiss(self, u, n, body):
    return self._guard(lambda: {'msg': kb.steward_dismiss(body.get('id', ''))})


@post('/api/steward/answer', page_only=True)
def _post_api_steward_answer(self, u, n, body):
    return self._guard(lambda: {'msg': kb.steward_answer(body.get('id', ''), body.get('value', ''), repo=body.get('repo', ''), branch=body.get('branch', ''))})


@post('/api/steward/tick', page_only=True)
def _post_api_steward_tick(self, u, n, body):
    return self._guard(lambda: {'msg': kb.steward_tick('用户（网页）')})
