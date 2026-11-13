"""接口 · 页面和静态文件。每个接口一个函数，用 @get / @post 注册（见 webapp/router.py）。"""
from webapp.router import get, post  # noqa: F401
from webapp.shared import *  # noqa: F401,F403


@get('/')
def _get_(self, u, q):
    return self._send(200, ui_page(q.get('ui', '')), 'text/html; charset=utf-8')


@get('/favicon.ico')
def _get_favicon_ico(self, u, q):
    return self._send(200, b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#3b5bdb"/><text x="16" y="21" font-size="13" text-anchor="middle" fill="#fff" font-family="sans-serif" font-weight="700">KB</text></svg>', 'image/svg+xml')


@get('/ui-templates.js')
def _get_ui_templates_js(self, u, q):
    return self._send(200, (PAGE.parent / 'ui-templates.js').read_bytes(), 'text/javascript; charset=utf-8')


@get('/ui-preview')
def _get_ui_preview(self, u, q):
    return self._send(200, (PAGE.parent / 'ui-preview.html').read_bytes(), 'text/html; charset=utf-8')


@get('/file')
def _get_file(self, u, q):
    p = Path(q.get('path', '')).expanduser().resolve()
    if not p.is_file() or not kb._allowed(p):
        return self._send(404, {'error': '无此文件'})
    ctype = mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
    return self._send(200, p.read_bytes(), ctype)
