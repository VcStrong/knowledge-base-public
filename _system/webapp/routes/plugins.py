"""接口 · 插件、构建、工作统计。每个接口一个函数，用 @get / @post 注册（见 webapp/router.py）。"""
from webapp.router import get, post  # noqa: F401
from webapp.shared import *  # noqa: F401,F403


@get('/api/stats')
def _get_api_stats(self, u, q):
    return self._guard(lambda: kb.work_stats(q.get('range', '')))


@get('/api/plugin/targets')
def _get_api_plugin_targets(self, u, q):
    return self._guard(kb.plugin_targets)


@get('/api/plugin/job')
def _get_api_plugin_job(self, u, q):
    return self._guard(lambda: kb.plugin_job(q.get('id', '')))


@get('/api/plugin/resolve')
def _get_api_plugin_resolve(self, u, q):
    return self._guard(lambda: {'items': kb.plugin_resolve(q.get('id', ''), q.get('q', ''))})


@get('/api/plugin/content')
def _get_api_plugin_content(self, u, q):
    return self._guard(lambda: kb.plugin_content(q.get('id', ''), q.get('item', ''), q.get('fresh') == '1'))


@get('/api/period/builds')
def _get_api_period_builds(self, u, q):
    return self._guard(lambda: kb.period_builds(q.get('name', ''), fresh=q.get('fresh') == '1'))


@post('/api/plugin/task', page_only=True)
def _post_api_plugin_task(self, u, n, body):
    return self._guard(lambda: kb.plugin_to_task(body.get('id', ''), body.get('item', ''), body.get('task', ''),
                                                 body.get('name', ''), body.get('title', ''), body.get('url', '')))


@post('/api/plugin', page_only=True)
def _post_api_plugin(self, u, n, body):
    return self._guard(lambda: {'msg': kb.save_plugin(body.get('id', ''), bool(body.get('enabled')),
                                                      body.get('events') or [], body.get('config') or {})})


@post('/api/plugin/dir', page_only=True)
def _post_api_plugin_dir(self, u, n, body):
    return self._guard(lambda: {'msg': kb.add_plugin_dir(body.get('path', ''))})


@post('/api/plugin/remove', page_only=True)
def _post_api_plugin_remove(self, u, n, body):
    return self._guard(lambda: {'msg': kb.remove_plugin_dir(body.get('id', ''))})


@post('/api/plugin/run2', page_only=True)
def _post_api_plugin_run2(self, u, n, body):
    return self._guard(lambda: {'job': kb.plugin_run_start(body.get('id', ''), body.get('target', ''), body.get('repo', ''),
                                                           body.get('push', True) is not False)})


@post('/api/plugin/run', page_only=True)
def _post_api_plugin_run(self, u, n, body):
    return self._guard(lambda: {'msg': kb.run_plugin_now(body.get('id', ''), body.get('period', ''),
                                                         body.get('event') or '开发开始')})


@post('/api/period/builds', page_only=True)
def _post_api_period_builds(self, u, n, body):
    return self._guard(lambda: {'msg': kb.set_period_jobs(body.get('period', ''), body.get('jobs', ''))})


@post('/api/build/mapping', page_only=True)
def _post_api_build_mapping(self, u, n, body):
    return self._guard(lambda: {'msg': kb.build_mapping(body.get('url', ''), body.get('version', ''))})
