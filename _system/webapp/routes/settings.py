"""接口 · AI 引擎、角色、开发流程。每个接口一个函数，用 @get / @post 注册（见 webapp/router.py）。"""
from webapp.router import get, post  # noqa: F401
from webapp.shared import *  # noqa: F401,F403


@get('/api/settings')
def _get_api_settings(self, u, q):
    return self._guard(lambda: {'flows': kb.flows(), 'fields': kb.FLOW_FIELDS, 'vars': kb.FLOW_VARS,
                                'engines': [dict(e, 状态=kb.engine_status(e), 接入说明=kb.engine_link_help(e))
                                            for e in kb.engines()],
                                'roles': kb.role_engines(),
                                'engineFields': kb.ENGINE_FIELDS, 'engineVars': kb.ENGINE_VARS,
                                'plugins': kb.plugins(), 'pluginEvents': kb.PLUGIN_EVENTS,
                                'pluginEnv': kb.PLUGIN_ENV, 'pluginDir': str(kb.PLUGIN_DIR),
                                'baseEntries': [{'编号': e['编号'], '名称': e['名称'], '类型': e.get('类型', '')}
                                                for e in kb.base_load()['条目']]})


@get('/api/settings/commands')
def _get_api_settings_commands(self, u, q):
    return self._guard(lambda: {'items': kb.list_commands()})


@post('/api/settings/flow', page_only=True)
def _post_api_settings_flow(self, u, n, body):
    return self._guard(lambda: dict(zip(('msg', 'id'), kb.save_flow(body.get('flow') or {}))))


@post('/api/engine/role', page_only=True)
def _post_api_engine_role(self, u, n, body):
    return self._guard(lambda: {'msg': kb.set_role_engine(body.get('role', ''), body.get('engine', ''))})


@post('/api/engine', page_only=True)
def _post_api_engine(self, u, n, body):
    return self._guard(lambda: dict(zip(('msg', 'id'), kb.save_engine(body.get('engine') or {}))))


@post('/api/engine/delete', page_only=True)
def _post_api_engine_delete(self, u, n, body):
    return self._guard(lambda: {'msg': kb.delete_engine(body.get('id', ''))})


@post('/api/engine/default', page_only=True)
def _post_api_engine_default(self, u, n, body):
    return self._guard(lambda: {'msg': kb.set_default_engine(body.get('id', ''))})


@post('/api/engine/link', page_only=True)
def _post_api_engine_link(self, u, n, body):
    return self._guard(lambda: {'msg': kb.engine_link(body.get('id', ''))})


@post('/api/engine/test', page_only=True)
def _post_api_engine_test(self, u, n, body):
    return self._guard(lambda: kb.engine_test(body.get('id', '')))


@post('/api/period/engine', page_only=True)
def _post_api_period_engine(self, u, n, body):
    return self._guard(lambda: {'msg': kb.set_period_engine(body.get('period', ''), body.get('id', ''))})


@post('/api/settings/flow/draft', page_only=True)
def _post_api_settings_flow_draft(self, u, n, body):
    return self._guard(lambda: {'flow': kb.flow_draft(body.get('path', ''), bool(body.get('ai')))})


@post('/api/settings/flow/delete', page_only=True)
def _post_api_settings_flow_delete(self, u, n, body):
    return self._guard(lambda: {'msg': kb.delete_flow(body.get('id', ''))})


@post('/api/settings/default', page_only=True)
def _post_api_settings_default(self, u, n, body):
    return self._guard(lambda: {'msg': kb.set_default_flow(body.get('id', ''))})


@post('/api/period/flow', page_only=True)
def _post_api_period_flow(self, u, n, body):
    return self._guard(lambda: {'msg': kb.set_period_flow(body.get('period', ''), body.get('id', ''))})


@get('/api/repos/settings')
def _get_api_repos_settings(self, u, q):
    return self._guard(lambda: {'items': kb.repo_settings(), 'ends': list(kb.REPO_ENDS)})


@post('/api/repos/settings', page_only=True)
def _post_api_repos_settings(self, u, n, body):
    return self._guard(lambda: {'msg': kb.repo_set(body.get('path', ''), body.get('end'), body.get('flow'))})
