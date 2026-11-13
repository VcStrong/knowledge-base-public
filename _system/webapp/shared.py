# From 大大王.DT
"""网页服务的公共部分（路由文件和 server 都 from webapp.shared import *）。知识库网页：资料浏览、进度看板、检索、拖拽上传。默认只听 127.0.0.1（本机）；部署在远端时 kb web --host 0.0.0.0，要先 kb passwd 设访问密码（见 kblib/infra/deploy.py）。

「开始开发」= 本人批准 + 后台启动开发会话（需输入期名确认，且只接受本页面发起的请求）；
没有单独的「批准开发」接口。
后台每隔 KB_REFRESH_HOURS 小时（默认 6，设 0 关闭）按登记的网址检查一遍未完成各期的来源有没有更新。
"""
import hashlib
import json
import mimetypes
import os
import queue
import re
import shutil
import sys
import threading
import time
import uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # _system，kb.py 在这
import kb  # noqa: E402

PAGE = Path(__file__).resolve().parents[1] / 'web.html'
UI_DIR = PAGE.parent / 'ui'          # 共用功能层（core.css / core.js）和各套界面模板（<目录>/index.html …）
UI_TYPES = {'.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.html': 'text/html; charset=utf-8',
            '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg',
            '.webp': 'image/webp', '.woff2': 'font/woff2', '.ico': 'image/x-icon'}
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


STEWARD_MIN = float(os.environ.get('KB_STEWARD_MINUTES', '5'))


def steward_auto():
    """管家：每 KB_STEWARD_MINUTES 分钟（默认 5）巡检一轮，明确的事自己做。设置里关掉管家时只看不做。"""
    time.sleep(180)
    while True:
        try:
            kb.steward_tick()
        except Exception as e:
            print('steward:', repr(e), flush=True)
        time.sleep(STEWARD_MIN * 60)


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


def _try(fn, *a):
    """辅助信息算不出来就不显示，不影响整页。"""
    try:
        return fn(*a)
    except Exception as e:
        print('辅助信息出错：', fn.__name__, repr(e), flush=True)
        return None


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
                        'dnd': bool(m.get('免打扰')), 'navHidden': (m.get('侧栏') or {}).get('状态') == '隐藏',
                        'kind': '事项' if kb.is_task(m) else '期', 'taskKind': m.get('事项类型', ''),
                        'priority': m.get('优先级', ''), 'from': m.get('来自', ''),
                        'running': (kb.dev_session(n) or {}).get('状态') == '运行中',
                        'plugins': sorted({x.get('插件') for x in m.get('外部来源') or []}),
                        'srcTitles': [x.get('标题') or x.get('编号') for x in m.get('外部来源') or []]})
    try:
        zb = [e for e in kb.zt_load()['Bug'].values() if e['状态'] != '已关闭' and not e.get('忽略')]
    except Exception:
        zb = []
    open_by = {}                     # 每期没解决的 Bug：平台上还是激活、知识库也没标已修复
    for e in zb:
        if e['状态'] == '激活' and (e.get('修复') or {}).get('状态') != '已修复':
            n = (e.get('归属') or {}).get('名称')
            open_by[n] = open_by.get(n, 0) + 1
    try:
        tb = kb.task_batches()
    except Exception:
        tb = {}
    for p in periods:
        p['openBugs'] = open_by.get(p['name'], 0)
        if p['name'] in tb:
            p['batch'] = tb[p['name']]
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
            'entries': kb.plugin_entries(), 'auth': kb.auth_required()}


def ui_page(want=''):
    """首页按界面模板给整站：经典 → web.html；其他 → ui/<目录>/index.html（没有就退回 web.html）。
    want：?ui= 临时指定（目录名或模板名，如 command / 指挥台 / classic），不改设置。"""
    t = (kb.ui_dir(want) if want else None) or kb.ui_dir(kb.ui_template()) or kb.CLASSIC
    d = t['目录']
    f = UI_DIR / d / 'index.html'
    return f.read_bytes() if d != 'classic' and f.is_file() else PAGE.read_bytes()


def ui_file(rel):
    """/ui/<文件>：只给 ui 目录里的文件，防目录穿越；返回 (内容, 类型) 或 None。
    core.js 由 ui/core/*.js 按文件名顺序拼成（功能分文件维护，页面照旧只引一个 core.js）。"""
    if unquote(rel) == 'core.js' and (UI_DIR / 'core').is_dir():
        parts = sorted((UI_DIR / 'core').glob('*.js'))
        return '\n'.join(f.read_text('utf-8') for f in parts).encode('utf-8'), UI_TYPES['.js']
    base = UI_DIR.resolve()
    p = (base / unquote(rel)).resolve()
    if base not in p.parents or not p.is_file() or p.name.startswith('.'):
        return None
    return p.read_bytes(), UI_TYPES.get(p.suffix.lower()) or mimetypes.guess_type(p.name)[0] or 'application/octet-stream'


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
        try:
            kb.talk_queue_tick()         # 期页面排队的内容：这一期会话都结束后开始处理
        except Exception as e:
            print('talk_queue_tick:', repr(e), flush=True)
        try:
            kb.stack_tick()              # 全栈各端：收尾、按名额启动排队的端和审查
        except Exception as e:
            print('stack_tick:', repr(e), flush=True)


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
                    _mt(x.get('日志', '')) for x in kb._an_load() if x.get('状态') == '运行中']   # 分析 / 修复进度
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
            'guide': _try(kb.period_guide, d.name), 'bugs': kb.zentao_bugs_json(d.name), 'fixq': kb.fix_queue(), 'taskKinds': kb.TASK_KINDS, 'taskPri': kb.TASK_PRI}


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


LOGIN_PAGE = '''<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>知识库登录</title><style>
:root{--bg:#f3f5f9;--fg:#1c2433;--card:#fff;--line:#e3e7ef;--acc:#3b5bdb;--mut:#667085}
@media (prefers-color-scheme:dark){:root{--bg:#0f141d;--fg:#e6eaf2;--card:#171e2a;--line:#283245;--acc:#7c97ff;--mut:#98a2b3}}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,"PingFang SC",system-ui,sans-serif}
form{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:28px;width:min(340px,calc(100vw - 32px));box-sizing:border-box}
h1{font-size:18px;margin:0 0 16px}input,button{width:100%;box-sizing:border-box;font:inherit;padding:10px 12px;border-radius:8px}
input{border:1px solid var(--line);background:var(--bg);color:var(--fg);margin-bottom:12px}button{border:0;background:var(--acc);color:#fff;cursor:pointer}
p{color:#c92a2a;min-height:1.5em;margin:8px 0 0;font-size:13px}</style></head><body>
<form id="f"><h1>本地知识库</h1><input type="password" id="p" placeholder="访问密码" autofocus autocomplete="current-password"><button>登录</button><p id="e"></p></form>
<script>document.getElementById('f').onsubmit=async e=>{e.preventDefault();const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({password:document.getElementById('p').value})});if(r.ok)location.href='/';else document.getElementById('e').textContent=(await r.json()).error||'登录失败'}</script>
</body></html>'''

__all__ = ['AUTO', 'BaseHTTPRequestHandler', 'DOC_FIRST', 'LOGIN_PAGE', 'PAGE', 'PAGE_SKIP', 'Path', 'REFRESH_HOURS', 'STEWARD_MIN', 'SimpleCookie', 'ThreadingHTTPServer', 'UI_DIR', 'UI_TYPES', '_SUBS', '_SUBS_LOCK', '_add_stamp', '_anr_counts', '_dev_stamp', '_file_info', '_fp', '_global_stamp', '_log_lines', '_mt', '_page_view', '_period_stamp', '_publish', '_safe', '_try', 'api_base', 'api_doc', 'api_docs', 'api_overview', 'api_overview_view', 'api_period', 'api_zentao', 'auto_refresh', 'dev_tick', 'doc_files', 'hashlib', 'json', 'kb', 'mimetypes', 'os', 'parse_qs', 'queue', 're', 'shutil', 'steward_auto', 'sys', 'threading', 'time', 'ui_file', 'ui_page', 'unquote', 'urlparse', 'uuid', 'watcher', 'zentao_auto']   # 路由文件 from webapp.shared import * 要用到下划线开头的帮助函数
