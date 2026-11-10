#!/usr/bin/env python3
# From 大大王.DT
"""知识库本地网页：资料浏览、进度看板、检索、拖拽上传。只监听 127.0.0.1。

「开始开发」= 本人批准 + 后台启动开发会话（需输入期名确认，且只接受本页面发起的请求）；
没有单独的「批准开发」接口。
后台每隔 KB_REFRESH_HOURS 小时（默认 6，设 0 关闭）按登记的网址检查一遍未完成各期的来源有没有更新。
"""
import hashlib
import json
import mimetypes
import os
import queue
import shutil
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb  # noqa: E402

PAGE = Path(__file__).resolve().parent / 'web.html'
REFRESH_HOURS = float(os.environ.get('KB_REFRESH_HOURS', '6'))
AUTO = {'last': '', 'next': '', 'result': '', 'hours': REFRESH_HOURS}


def auto_refresh():
    time.sleep(300)   # 启动 5 分钟后第一次检查
    while True:
        try:
            ch = kb.refresh_all()
            AUTO['result'] = '；'.join(f'{n} {len(h)} 条有变化' for n, h in ch) or '没有变化'
        except Exception as e:
            AUTO['result'] = f'检查出错：{e!r}'
        AUTO['last'] = kb.now()
        AUTO['next'] = time.strftime('%Y-%m-%d %H:%M', time.localtime(time.time() + REFRESH_HOURS * 3600))
        time.sleep(REFRESH_HOURS * 3600)


def zentao_auto():
    """每 KB_BUG_HOURS 小时（默认 0.25）同步一次所有 Bug / 崩溃平台。没接入平台时空转。"""
    time.sleep(120)
    while True:
        try:
            if any(c['启用'] for c in kb.bug_sources()):
                kb.bug_sync()
        except Exception as e:
            kb.ZT_STATE['result'] = f'同步失败：{e}'
        kb.ZT_STATE['next'] = time.strftime('%Y-%m-%d %H:%M', time.localtime(time.time() + kb.ZT_HOURS * 3600))
        time.sleep(kb.ZT_HOURS * 3600)


def api_zentao(period='', owner=''):
    bugs = kb.zentao_bugs_json(period, owner)
    names = kb.period_names()
    tasks = [n for n in names if kb.is_task(kb.load_meta(kb.PERIODS / n))]
    return {'status': kb.zentao_status(), 'bugs': bugs, 'periods': [n for n in names if n not in tasks], 'tasks': tasks,
            'sessions': [x for x in reversed(kb.an_sessions()) if x.get('类型') != '修复' and (x.get('状态') == '运行中' or x.get('警告'))][:10],
            'fixq': kb.fix_queue(),
            'baseEntries': [{'编号': e['编号'], '名称': e['名称']} for e in kb.base_load()['条目']],
            'owners': list(kb.ZT_OWNER)}


def _file_info(p: Path):
    st = p.stat()
    info = {'name': p.name, 'path': str(p), 'isDir': p.is_dir(), 'mtime': st.st_mtime,
            'size': st.st_size, 'isImage': p.suffix.lower() in kb.IMG_EXT}
    if p.is_dir():
        files = [x for x in p.rglob('*') if x.is_file()]
        info['count'] = len(files)
        info['images'] = [str(x) for x in sorted(files) if x.suffix.lower() in kb.IMG_EXT and kb.HIST not in x.parts][:120]
        info['notes'] = {str(x): kb.read_text(x.with_name(x.name + kb.NOTE_SUFFIX)).split('\n', 2)[-1].strip()
                         for x in files if x.suffix.lower() in kb.IMG_EXT and x.with_name(x.name + kb.NOTE_SUFFIX).exists()}
    if info['isImage']:
        note = p.with_name(p.name + kb.NOTE_SUFFIX)
        info['note'] = kb.read_text(note).split('\n', 2)[-1].strip() if note.exists() else ''
    return info


def _log_lines(d):
    f = d / '记录.md'
    out = []
    if f.exists():
        for line in kb.read_text(f).splitlines():
            if line.startswith('- '):
                parts = [x.strip() for x in line[2:].split('｜', 2)]
                out.append(dict(zip(('time', 'action', 'content'), parts + [''] * (3 - len(parts)))))
    return out


def _safe(fn, *a):
    try:
        fn(*a)
    except Exception as e:
        kb.ZT_STATE['result'] = f'同步失败：{e}'


def api_overview():
    kb.init()
    periods = []
    for n in kb.period_names():
        d = kb.PERIODS / n
        m = kb.load_meta(d)
        mats = kb._materials(d)
        no_note = sum(1 for p in mats['设计图'] if p.suffix.lower() in kb.IMG_EXT
                      and not p.with_name(p.name + kb.NOTE_SUFFIX).exists())
        logs = _log_lines(d)
        imgs = sorted(x for x in (d / '设计图').rglob('*') if x.suffix.lower() in kb.IMG_EXT and kb.HIST not in x.parts)
        design_imgs = len(imgs)
        proto = d / '需求' / kb.PROTO_DIR
        proto_imgs = sum(1 for x in proto.iterdir() if x.suffix.lower() in kb.IMG_EXT) if proto.exists() else 0
        periods.append({'name': n, 'status': m.get('状态'), 'summary': m.get('说明', ''),
                        'created': m.get('创建时间', ''), 'updated': m.get('更新时间', ''),
                        'repos': m.get('关联仓库') or [],
                        'counts': {c: len(v) + len(kb.notes_of(d, c, m)) for c, v in mats.items()},
                        'branches': [kb.note_title(x) for x in kb.notes_of(d, m=m) if x['类型'] == '分支'],
                        'imagesWithoutNote': no_note, 'lastLog': logs[-1] if logs else None,
                        'designImages': design_imgs, 'protoImages': proto_imgs,
                        'cover': str(imgs[0]) if imgs else next((str(x) for x in sorted(proto.iterdir()) if x.suffix.lower() in kb.IMG_EXT), '')
                        if imgs or proto.exists() else '',   # 卡片封面：第一张设计稿，没有就用第一张原型图
                        'sources': len(m.get('来源') or []),
                        'pendingSources': sum(1 for x in m.get('来源') or [] if x.get('核对') != '已核对'),
                        'staleSources': sum(1 for x in m.get('来源') or [] if x.get('待更新')),
                        'pendingQ': sum(1 for q in m.get('待确认') or [] if q['状态'] == '待回答'),
                        'issues': sum(1 for q in m.get('非阻断问题') or [] if q['状态'] == '待处理'),
                        'retest': bool(m.get('待复测')), 'autoRetest': bool((m.get('待复测') or {}).get('自动')),
                        'dnd': bool(m.get('免打扰')),
                        'kind': '事项' if kb.is_task(m) else '期', 'taskKind': m.get('事项类型', ''),
                        'priority': m.get('优先级', ''), 'from': m.get('来自', ''),
                        'running': (kb.dev_session(n) or {}).get('状态') == '运行中',
                        'plugins': sorted({x.get('插件') for x in m.get('外部来源') or []}),
                        'srcTitles': [x.get('标题') or x.get('编号') for x in m.get('外部来源') or []]})
    try:
        zb = [e for e in kb.zt_load()['Bug'].values() if e['状态'] != '已关闭']
    except Exception:
        zb = []
    for p in periods:
        p['bugs'] = sum(1 for e in zb if (e.get('归属') or {}).get('名称') == p['name'])
    zentao = {'open': len(zb), 'pending': sum(1 for e in zb if (e.get('归属') or {}).get('类型') == '待归纳')}
    repos = []
    with kb.db() as c:
        for k, v in kb.load_repos().items():
            n = c.execute("select count(*) from files where kind='code' and repo=?", (k,)).fetchone()[0]
            repos.append({'name': k, 'path': v['路径'], 'files': n, 'added': v.get('加入时间', '')})
        docs = c.execute("select count(*) from files where kind='doc'").fetchone()[0]
    inbox = [_file_info(p) for p in sorted(kb.INBOX.iterdir()) if not p.name.startswith('.')]
    try:
        ph = kb.devices() if kb._adb() else None
    except Exception:
        ph = None
    return {'root': str(kb.ROOT), 'periods': periods,
            'phones': None if ph is None else {'total': len(ph), 'free': sum(1 for x in ph if x['空闲'])}, 'repos': repos, 'inbox': inbox, 'docs': docs,
            'statuses': kb.STATUSES, 'cats': kb.CATS, 'autoRefresh': AUTO, 'zentao': zentao,
            'taskKinds': kb.TASK_KINDS, 'taskPri': kb.TASK_PRI, 'anr': _anr_counts(),
            'entries': kb.plugin_entries()}


def _anr_counts():
    try:
        ps = kb.anr_problems()
    except Exception:
        return {'todo': 0, 'total': 0}
    return {'todo': sum(1 for p in ps if not p['事项'] or p['修复后又出现']), 'total': len(ps)}


# ---------------------------------------------------------------- 实时推送（SSE）
# 后台线程每秒看一眼相关文件的修改时间，有变化再算页面内容的指纹；指纹变了才推给浏览器，浏览器只刷新对应部分。

_SUBS = set()
_SUBS_LOCK = threading.Lock()
PAGE_SKIP = ('开发会话', '待确认', '变更通知', '更新时间', '更新会话')   # 这些归开发面板管，变了不必重画整页


def _publish(ev):
    with _SUBS_LOCK:
        for q in list(_SUBS):
            q.put(ev)


def _mt(p):
    try:
        st = os.stat(p)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _fp(obj):
    return hashlib.sha1(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def dev_tick():
    """每分钟：同步测试报告里的非阻断问题；设了自动复测的期，空闲手机够了就开始复测。"""
    while True:
        time.sleep(60)
        try:
            kb.dev_tick()
        except Exception as e:
            print('dev_tick:', repr(e), flush=True)
        try:
            kb.fix_queue_tick()          # 修复队列：仓库空出来、切好分支、提交了改动后自动开始
        except Exception as e:
            print('fix_queue_tick:', repr(e), flush=True)


def _period_stamp(d, m):
    dirs = [d] + [d / c for c in kb.CATS] + [x for c in kb.CATS if (d / c).is_dir() for x in (d / c).iterdir() if x.is_dir()]
    return [_mt(x) for x in dirs + [d / '期信息.json', d / '记录.md', kb.ZT_FILE]]


def _dev_stamp(d, m):
    s = m.get('开发会话') or {}
    docs = m.get('SDD目录')
    return [_mt(x) for x in [d / '期信息.json', s.get('日志') or '', (Path(docs) / 'sdd-status.md') if docs else '',
                             docs or '', (Path(docs) / 'tests') if docs else '', kb.devlock.FILE]]


def _global_stamp():
    return [_mt(x) for x in [kb.PERIODS, kb.INBOX, kb.REPOS_FILE, kb.ROOT, kb.ZT_FILE]] + [
        _mt(kb.PERIODS / n / '期信息.json') for n in kb.period_names()]


def _add_stamp():
    return [_mt(kb.ADD_FILE)] + [_mt(x.get('日志') or '') for x in kb._add_load() if x.get('状态') == '运行中']


def watcher():
    stamps, prints = {}, {}

    def check(key, stamp, make):
        if stamps.get(key) == stamp:
            return False
        stamps[key] = stamp
        fp = _fp(make())
        changed = key in prints and prints[key] != fp
        prints[key] = fp
        return changed
    while True:
        try:
            with _SUBS_LOCK:
                idle = not _SUBS
            if not idle:
                if check('overview', _global_stamp(), api_overview_view):
                    _publish({'kind': 'overview'})
                zs = [_mt(kb.ZT_FILE), kb.ZT_STATE['running'], _mt(kb.AN_SESS), _mt(kb.AR_FILE), _mt(kb.AR_PROB)] + [
                    _mt(x.get('日志', '')) for x in kb._an_load() if x.get('类型') == '修复' and x.get('状态') == '运行中']   # 修复进度
                if check('zentao', zs, lambda: zs):      # Bug 同步开始 / 结束：Bug 页刷新
                    _publish({'kind': 'overview'})
                if check('adds', _add_stamp(), kb.add_sessions):
                    _publish({'kind': 'adds'})
                for n in kb.period_names():
                    d = kb.PERIODS / n
                    m = kb.load_meta(d)
                    if check(('page', n), _period_stamp(d, m), lambda: _page_view(n)):
                        _publish({'kind': 'page', 'period': n})
                    if check(('dev', n), _dev_stamp(d, m), lambda: kb.dev_overview(n)):
                        _publish({'kind': 'dev', 'period': n})
            else:
                stamps.clear()
                prints.clear()
        except Exception as e:      # 文件正写到一半等，下一秒再看
            print('watcher:', repr(e), flush=True)
        time.sleep(1)


def api_overview_view():
    v = api_overview()
    v.pop('autoRefresh', None)
    for p in v['periods']:
        p.pop('updated', None)
    return v


def _page_view(name):
    v = api_period(name)
    v['meta'] = {k: x for k, x in v['meta'].items() if k not in PAGE_SKIP}
    v.pop('autoRefresh', None)
    return v


def api_period(name):
    d = kb.period_dir(name)
    kb.update_session(d.name)
    m = kb.load_meta(d)
    mats, hist = {}, {}
    for c, items in kb._materials(d).items():
        mats[c] = [_file_info(p) for p in items]
        h = d / c / kb.HIST
        hist[c] = [_file_info(p) for p in sorted(h.iterdir(), reverse=True)] if h.exists() else []
    return {'name': d.name, 'dir': str(d), 'meta': m, 'materials': mats, 'history': hist,
            'notes': {c: [{**n, '显示标题': kb.note_title(n)} for n in kb.notes_of(d, c, m)] for c in kb.CATS},
            'noteKinds': kb.NOTE_KINDS,
            'log': _log_lines(d), 'cats': kb.CATS, 'statuses': kb.STATUSES, 'autoRefresh': AUTO,
            'bugs': kb.zentao_bugs_json(d.name), 'fixq': kb.fix_queue(), 'taskKinds': kb.TASK_KINDS, 'taskPri': kb.TASK_PRI}


def api_base():
    files = [_file_info(p) for p in sorted(kb.BASE.rglob('*')) if p.is_file() and not p.name.startswith('.')
             and p not in (kb.BASE_FILE, kb.BASE_MD)] if kb.BASE.exists() else []
    return {**kb.base_load(), 'cats': kb.BASE_CATS, 'files': files, 'dir': str(kb.BASE)}


DOC_FIRST = ['使用说明']


def doc_files():
    """知识库根目录下的 .md 说明文档：使用说明在前，其余按名称。"""
    fs = {p.stem: p for p in kb.ROOT.glob('*.md') if p.is_file() and not p.name.startswith('.')}
    return [fs[n] for n in DOC_FIRST if n in fs] + [fs[n] for n in sorted(fs) if n not in DOC_FIRST]


def api_docs():
    return {'docs': [{'name': p.stem, 'path': str(p), 'mtime': p.stat().st_mtime} for p in doc_files()]}


def api_doc(name):
    p = next((p for p in doc_files() if p.stem == name), None)
    if not p:
        raise kb.KBError(f'没有这份文档：{name}')
    return {'name': p.stem, 'path': str(p), 'mtime': p.stat().st_mtime, 'text': p.read_text('utf-8')}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _guard(self, fn):
        try:
            self._send(200, fn())
        except kb.KBNeed as e:
            self._send(409, {'error': str(e), 'need': e.data})
        except kb.KBError as e:
            self._send(400, {'error': str(e)})
        except Exception as e:
            self._send(500, {'error': repr(e)})

    def _events(self):
        q = queue.Queue()
        with _SUBS_LOCK:
            _SUBS.add(q)
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(b'retry: 3000\n\n')
            self.wfile.flush()
            while True:
                try:
                    ev = q.get(timeout=20)
                    self.wfile.write(f'data: {json.dumps(ev, ensure_ascii=False)}\n\n'.encode())
                except queue.Empty:
                    self.wfile.write(b': ping\n\n')     # 保活，也用来发现浏览器已关闭
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with _SUBS_LOCK:
                _SUBS.discard(q)

    def _from_page(self):
        # 开始/停止开发、回答、免打扰只接受本页面发起的请求（浏览器必带 Origin）
        origin = self.headers.get('Origin', '')
        return bool(origin) and origin.endswith('//' + self.headers.get('Host', ''))

    def _local_only(self):
        # 防止其他网页跨站调用写接口
        origin = self.headers.get('Origin', '')
        host = self.headers.get('Host', '')
        return not origin or origin.endswith('//' + host)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == '/':
            return self._send(200, PAGE.read_bytes(), 'text/html; charset=utf-8')
        if u.path == '/api/events':
            return self._events()
        if u.path == '/api/overview':
            return self._guard(api_overview)
        if u.path == '/api/period':
            return self._guard(lambda: api_period(q.get('name', '')))
        if u.path == '/api/docs':
            return self._guard(api_docs)
        if u.path == '/api/doc':
            return self._guard(lambda: api_doc(q.get('name', '')))
        if u.path == '/api/base':
            return self._guard(api_base)
        if u.path == '/api/links':
            return self._guard(lambda: kb.period_links(q.get('name', '')))
        if u.path == '/api/settings':
            return self._guard(lambda: {'flows': kb.flows(), 'fields': kb.FLOW_FIELDS, 'vars': kb.FLOW_VARS,
                                        'engines': [dict(e, 状态=kb.engine_status(e), 接入说明=kb.engine_link_help(e))
                                                    for e in kb.engines()],
                                        'engineFields': kb.ENGINE_FIELDS, 'engineVars': kb.ENGINE_VARS,
                                        'plugins': kb.plugins(), 'pluginEvents': kb.PLUGIN_EVENTS,
                                        'pluginEnv': kb.PLUGIN_ENV, 'pluginDir': str(kb.PLUGIN_DIR),
                                        'baseEntries': [{'编号': e['编号'], '名称': e['名称'], '类型': e.get('类型', '')}
                                                        for e in kb.base_load()['条目']]})
        if u.path == '/api/zentao/analysis':
            return self._guard(lambda: kb.bug_analysis_view(q.get('id', '')))
        if u.path == '/api/zentao/sessions':
            return self._guard(lambda: {'items': list(reversed(kb.an_sessions()))[:20]})
        if u.path == '/api/anr':
            return self._guard(kb.anr_json)
        if u.path == '/api/zentao':
            return self._guard(lambda: api_zentao(q.get('period', ''), q.get('owner', '')))
        if u.path == '/api/settings/commands':
            return self._guard(lambda: {'items': kb.list_commands()})
        if u.path == '/api/adds':
            return self._guard(lambda: {'items': kb.add_sessions()})
        if u.path == '/api/plugin/resolve':
            return self._guard(lambda: {'items': kb.plugin_resolve(q.get('id', ''), q.get('q', ''))})
        if u.path == '/api/plugin/content':
            return self._guard(lambda: kb.plugin_content(q.get('id', ''), q.get('item', ''), q.get('fresh') == '1'))
        if u.path == '/api/dev/activity':
            return self._guard(lambda: kb.dev_activity_all(q.get('name', '')))
        if u.path == '/api/devices':
            return self._guard(lambda: {'items': kb.devices() if kb._adb() else None})
        if u.path == '/api/dev':
            return self._guard(lambda: kb.dev_overview(q.get('name', '')))
        if u.path == '/api/search':
            return self._guard(lambda: dict(zip(('hits', 'mode'), kb.search_hits(
                q.get('q', ''), q.get('period') or None, q.get('cat') or None,
                q.get('scope', 'all'), None, int(q.get('limit', 30))))))
        if u.path == '/api/read':
            return self._guard(lambda: {'text': kb.read_file(q.get('path', ''), int(q.get('start', 1)), 3000)})
        if u.path == '/file':
            p = Path(q.get('path', '')).expanduser().resolve()
            if not p.is_file() or not kb._allowed(p):
                return self._send(404, {'error': '无此文件'})
            ctype = mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
            return self._send(200, p.read_bytes(), ctype)
        self._send(404, {'error': 'not found'})

    def do_POST(self):
        if not self._local_only():
            return self._send(403, {'error': 'forbidden'})
        u = urlparse(self.path)
        n = int(self.headers.get('Content-Length') or 0)
        if u.path == '/api/upload':
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
        if u.path == '/api/anr/upload':
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
        body = json.loads(self.rfile.read(n) or b'{}')
        if u.path in ('/api/dev/start', '/api/dev/stop', '/api/dnd', '/api/answer', '/api/base/save',
                      '/api/base/secret', '/api/refresh/claude', '/api/add', '/api/settings/flow',
                      '/api/settings/flow/delete', '/api/settings/default', '/api/period/flow', '/api/settings/flow/draft',
                      '/api/engine', '/api/engine/delete', '/api/engine/default', '/api/engine/link', '/api/engine/test',
                      '/api/period/engine', '/api/retest', '/api/retest/plan', '/api/issue', '/api/device', '/api/dev/chat',
                      '/api/plugin', '/api/plugin/dir', '/api/plugin/remove', '/api/plugin/run', '/api/plugin/task', '/api/task/push', '/api/period/delete',
                      '/api/zentao/settings', '/api/bug/source', '/api/bug/test', '/api/zentao/analyze', '/api/zentao/review', '/api/zentao/fix',
                      '/api/zentao/fixed', '/api/zentao/unfix') and not self._from_page():
            return self._send(403, {'error': '只能在知识库网页上由本人操作'})
        if u.path == '/api/base/save':
            return self._guard(lambda: {'msg': kb.base_save(body.get('id', ''), body.get('category', ''), body.get('name'),
                                                            body.get('fields'), body.get('scope'), body.get('note'),
                                                            delete=bool(body.get('delete')), by='用户（网页）')})
        if u.path == '/api/base/secret':
            return self._guard(lambda: {'value': kb.base_secret(body.get('id', ''), body.get('field', ''), by='用户（网页）')})
        if u.path == '/api/dev/start':
            def run():
                if body.get('confirm', '').strip() != kb.period_dir(body.get('period', '')).name:
                    raise kb.KBError('输入的期名不一致，已取消')
                return {'msg': kb.dev_start(body.get('period', ''), body.get('note', ''), body.get('repo', ''),
                                            body.get('branch', ''), bool(body.get('keepBranch')))}
            return self._guard(run)
        if u.path == '/api/plugin/task':
            return self._guard(lambda: kb.plugin_to_task(body.get('id', ''), body.get('item', ''), body.get('task', ''),
                                                         body.get('name', ''), body.get('title', ''), body.get('url', '')))
        if u.path == '/api/task/push':
            return self._guard(lambda: {'msg': kb.task_push(body.get('period', ''), body.get('text', ''))})
        if u.path == '/api/dev/chat':
            return self._guard(lambda: {'msg': kb.dev_chat(body.get('period', ''), body.get('text', ''), bool(body.get('interrupt')))})
        if u.path == '/api/retest':
            return self._guard(lambda: {'msg': kb.retest_start(body.get('period', ''), body.get('scope', ''), body.get('note', ''))})
        if u.path == '/api/retest/plan':
            return self._guard(lambda: {'msg': kb.retest_plan(body.get('period', ''), bool(body.get('auto')), body.get('phones') or 1,
                                                              body.get('scope', ''))})
        if u.path == '/api/issue':
            return self._guard(lambda: {'msg': kb.set_issue(body.get('period', ''), body.get('id', ''), body.get('status', ''))})
        if u.path == '/api/device':
            return self._guard(lambda: {'msg': kb.device_mark(body.get('serial', ''), body.get('action', ''))})
        if u.path == '/api/dev/stop':
            return self._guard(lambda: {'msg': kb.dev_stop(body.get('period', ''))})
        if u.path == '/api/dnd':
            return self._guard(lambda: {'msg': kb.set_dnd(body.get('period', ''), bool(body.get('on')))})
        if u.path == '/api/answer':
            return self._guard(lambda: {'msg': kb.answer(body.get('period', ''), body.get('id', ''), body.get('answer', ''))})
        if u.path == '/api/new':
            return self._guard(lambda: {'msg': kb.create_period(body.get('name', ''), body.get('summary', ''))})
        if u.path == '/api/task':
            return self._guard(lambda: {'msg': kb.create_task(body.get('name', ''), body.get('summary', ''), body.get('kind', ''),
                                                              body.get('source', ''), body.get('priority', ''), body.get('bugs'),
                                                              by='用户（网页）'), 'name': kb.safe_name(body.get('name', ''))})
        if u.path == '/api/period/delete':
            def run():
                if body.get('confirm', '').strip() != kb.period_dir(body.get('period', '')).name:
                    raise kb.KBError('输入的名称不一致，没有删除')
                return {'msg': kb.delete_period(body.get('period', ''))}
            return self._guard(run)
        if u.path == '/api/task/meta':
            return self._guard(lambda: {'msg': kb.update_task(body.get('period', ''), body.get('kind'), body.get('source'),
                                                              body.get('priority'), body.get('summary'))})
        if u.path == '/api/inbox':
            def run():
                fs = [p for p in kb.INBOX.iterdir() if not p.name.startswith('.')]
                names = body.get('files')
                fs = [p for p in fs if not names or p.name in names]
                return {'msg': '\n'.join(kb.add_material(body.get('period', ''), p) for p in fs) or '收件箱是空的'}
            return self._guard(run)
        if u.path == '/api/note':
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
        if u.path == '/api/log':
            return self._guard(lambda: {'msg': kb.add_log(body.get('period', ''), body.get('note', ''))})
        if u.path == '/api/status':
            def run():
                if body.get('status') == '已批准开发':
                    raise kb.KBError('批准开发请在终端运行 kb approve')
                return {'msg': kb.set_status(body.get('period', ''), body.get('status', ''), body.get('note', ''),
                                             by_human=True)}
            return self._guard(run)
        if u.path == '/api/verify':
            return self._guard(lambda: {'msg': kb.verify_source(body.get('period', ''), body.get('sid', ''),
                                                                body.get('status', ''), body.get('note', ''))})
        if u.path == '/api/fixlink':
            return self._guard(lambda: {'msg': kb.fix_link(body.get('period', ''), body.get('old', ''), body.get('new', ''),
                                                           body.get('reason', ''), by='用户（网页）')})
        if u.path == '/api/refresh':
            return self._guard(lambda: {'msg': kb.refresh_sources(body.get('period', ''), body.get('sid', ''), by='用户（网页）')})
        if u.path == '/api/refresh/claude':
            return self._guard(lambda: {'msg': kb.claude_update(body.get('period', ''))})
        if u.path == '/api/plugin':
            return self._guard(lambda: {'msg': kb.save_plugin(body.get('id', ''), bool(body.get('enabled')),
                                                              body.get('events') or [], body.get('config') or {})})
        if u.path == '/api/plugin/dir':
            return self._guard(lambda: {'msg': kb.add_plugin_dir(body.get('path', ''))})
        if u.path == '/api/plugin/remove':
            return self._guard(lambda: {'msg': kb.remove_plugin_dir(body.get('id', ''))})
        if u.path == '/api/plugin/run':
            return self._guard(lambda: {'msg': kb.run_plugin_now(body.get('id', ''), body.get('period', ''),
                                                                 body.get('event') or '开发开始')})
        if u.path == '/api/settings/flow':
            return self._guard(lambda: dict(zip(('msg', 'id'), kb.save_flow(body.get('flow') or {}))))
        if u.path == '/api/engine':
            return self._guard(lambda: dict(zip(('msg', 'id'), kb.save_engine(body.get('engine') or {}))))
        if u.path == '/api/engine/delete':
            return self._guard(lambda: {'msg': kb.delete_engine(body.get('id', ''))})
        if u.path == '/api/engine/default':
            return self._guard(lambda: {'msg': kb.set_default_engine(body.get('id', ''))})
        if u.path == '/api/engine/link':
            return self._guard(lambda: {'msg': kb.engine_link(body.get('id', ''))})
        if u.path == '/api/engine/test':
            return self._guard(lambda: kb.engine_test(body.get('id', '')))
        if u.path == '/api/period/engine':
            return self._guard(lambda: {'msg': kb.set_period_engine(body.get('period', ''), body.get('id', ''))})
        if u.path == '/api/settings/flow/draft':
            return self._guard(lambda: {'flow': kb.flow_draft(body.get('path', ''), bool(body.get('ai')))})
        if u.path == '/api/settings/flow/delete':
            return self._guard(lambda: {'msg': kb.delete_flow(body.get('id', ''))})
        if u.path == '/api/settings/default':
            return self._guard(lambda: {'msg': kb.set_default_flow(body.get('id', ''))})
        if u.path == '/api/period/flow':
            return self._guard(lambda: {'msg': kb.set_period_flow(body.get('period', ''), body.get('id', ''))})
        if u.path == '/api/add':
            return self._guard(lambda: {'msg': kb.claude_add(body.get('text', ''), body.get('period', ''))})
        if u.path == '/api/zentao/sync':
            def run():
                if kb.ZT_STATE['running']:
                    return {'msg': '正在同步，稍等'}
                threading.Thread(target=lambda: _safe(kb.bug_sync, '用户（网页）', bool(body.get('full')), body.get('source') or ''), daemon=True).start()
                return {'msg': '开始同步，完成后页面自动刷新'}
            return self._guard(run)
        if u.path == '/api/zentao/analyze':
            return self._guard(lambda: {'msg': kb.bug_analyze_in(body.get('ids') or [], body['repo']) if body.get('repo')
                                        else kb.bug_analyze(body.get('ids') or [])})
        if u.path == '/api/zentao/fix':
            return self._guard(lambda: {'msg': kb.bug_fix(body.get('ids') or [])})
        if u.path == '/api/zentao/fixed':
            return self._guard(lambda: {'msg': kb.bug_fixed(str(body.get('id', '')), body.get('done', True) is not False,
                                                            body.get('commits') or [], body.get('note', ''), by='用户（网页）')})
        if u.path == '/api/zentao/unfix':
            return self._guard(lambda: {'msg': kb.bug_unfix(str(body.get('id', '')))})
        if u.path == '/api/zentao/review':
            return self._guard(lambda: {'msg': kb.bug_review(str(body.get('id', '')), body.get('action', ''), body.get('note', ''))})
        if u.path == '/api/zentao/assign':
            return self._guard(lambda: {'msg': kb.bug_assign(str(body.get('id', '')), body.get('target', ''), by='用户（网页）',
                                                             bind=body.get('bind', True) is not False)})
        if u.path == '/api/zentao/settings':
            return self._guard(lambda: {'status': kb.save_zentao_settings(
                platform=body.get('platform'), enabled=body.get('enabled'), scope=body.get('scope'), people=body.get('people'),
                source=body.get('source') or '')})
        if u.path == '/api/bug/source':          # 接入 / 修改 / 移除一个 Bug 或崩溃平台
            return self._guard(lambda: (lambda r: {'msg': r} if isinstance(r, str) else {'status': r, 'msg': '已保存'})(kb.save_bug_source(
                body.get('id', ''), remove=bool(body.get('remove')), 适配器=body.get('adapter'), 账号条目=body.get('entry'),
                启用=body.get('enabled'), 范围=body.get('scope'), 人员=body.get('people'), 平台=body.get('platform'), 选项=body.get('options'))))
        if u.path == '/api/bug/test':
            return self._guard(lambda: {'msg': kb.bug_test(body.get('id', ''))})
        if u.path == '/api/anr/link':
            def run():
                out = []
                if body.get('version'):
                    out.append(kb.anr_set_version(body.get('id', ''), body['version'], by='用户（网页）'))
                if any(k in body for k in ('task', 'status', 'note')):
                    out.append(kb.anr_link(body.get('id', ''), body.get('task'), body.get('status'), body.get('note')))
                return {'msg': '\n'.join(out) or '没有变化'}
            return self._guard(run)
        if u.path == '/api/anr/delete':
            return self._guard(lambda: {'msg': kb.anr_delete_sample(body.get('sample', ''))})
        if u.path == '/api/reindex':
            return self._guard(lambda: {'msg': kb.reindex(body.get('target', 'all'))})
        self._send(404, {'error': 'not found'})


def main(port=11555):
    kb.init()
    srv = ThreadingHTTPServer(('127.0.0.1', port), H)
    print(f'知识库网页：http://127.0.0.1:{port}', flush=True)
    kb.dev_reattach()
    threading.Thread(target=watcher, daemon=True).start()
    threading.Thread(target=dev_tick, daemon=True).start()
    if kb.ZT_HOURS > 0:
        kb.ZT_STATE['next'] = time.strftime('%Y-%m-%d %H:%M', time.localtime(time.time() + 120))
        threading.Thread(target=zentao_auto, daemon=True).start()
    if REFRESH_HOURS > 0:
        AUTO['next'] = time.strftime('%Y-%m-%d %H:%M', time.localtime(time.time() + 300))
        threading.Thread(target=auto_refresh, daemon=True).start()
    srv.serve_forever()


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 11555)
