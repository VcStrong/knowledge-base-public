"""首次引导：装好打开网页，三步上手——AI 引擎能用 → 勾选本机代码仓库 → 放进第一个需求。

能探测的都不让人填：引擎自动检测装没装、接没接入；仓库在家目录下自动找 git / svn 工作副本，认出是哪个端。
三步都完成或你点「收起」后不再显示（设置.json「引导已收起」）。
"""
import json
import os
import threading
import time
from pathlib import Path

from .common import REPOS_FILE, load_settings, now, safe_name, save_settings
from .periods import period_names
from .repos import load_repos
from .search import index_repo
from .engines import engine_status, get_engine
from .stack import detect_ends, stack_repos, stack_set_end
from .periods import create_period
from .notes import add_note
from .common import PERIODS, SYS

_SKIP = {'Library', 'Applications', 'Movies', 'Music', 'Pictures', 'Public', 'node_modules', 'build', 'Pods', 'dist', 'out',
         'target', 'venv', '.venv', 'DerivedData', 'Caches', 'site-packages', 'vendor', 'knowledge-base', 'knowledge-base-public'}
_ADDING = {}


def repo_scan(max_depth=4, budget=4.0, limit=60):
    """在家目录下找代码仓库（有 .git 或 .svn 的目录），找到一个就不再往里找。最多几秒，找不全也没关系。"""
    t0, out, home = time.time(), [], Path.home()
    known = {str(Path(r['路径'] if isinstance(r, dict) else r).expanduser()) for r in load_repos().values()}

    def walk(p, depth):
        if time.time() - t0 > budget or len(out) >= limit:
            return
        try:
            names = {e.name: e for e in os.scandir(p)}
        except OSError:
            return
        kind = 'git' if '.git' in names else 'svn' if '.svn' in names else ''
        if kind and p != home:
            out.append((str(p), kind))
            return
        if depth >= max_depth:
            return
        for n, e in sorted(names.items()):
            if n.startswith('.') or n in _SKIP:
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    walk(Path(e.path), depth + 1)
            except OSError:
                pass
    walk(home, 0)
    res = [{'路径': pth, '名称': Path(pth).name, '版本库': kind, '端': detect_ends(pth), '已登记': pth in known} for pth, kind in out]
    return sorted(res, key=lambda x: (x['已登记'], not x['端'], x['名称'].lower()))


def onboard_status():
    s = load_settings()
    try:
        e = get_engine()
        st = engine_status(e)
        eng = {'id': e['id'], '名称': e['名称'], '已安装': st['已安装'], '已接入': st['已接入'], '版本': st['版本'],
               '能接入': bool(e.get('接入命令'))}
    except Exception as ex:
        eng = {'id': '', '名称': '', '已安装': False, '已接入': None, '版本': '', '错误': str(ex), '能接入': False}
    try:
        repos = len(stack_repos())          # 登记的 + 基础信息里的本地路径 + 各期用过的
    except Exception:
        repos = len(load_repos())
    periods = len(period_names())
    steps = [eng['已安装'] and eng['已接入'] is not False, repos > 0, periods > 0]
    return {'引擎': eng, '仓库数': repos, '期数': periods, '步骤': steps, '完成': all(steps),
            '收起': bool(s.get('引导已收起')), '登记中': sorted(_ADDING)}


def onboard_add_repos(paths):
    """登记勾选的仓库：先一起登记（马上能在每一期里选），代码索引在后台一个个建。"""
    paths = [str(Path(p).expanduser().resolve()) for p in paths or [] if p and Path(p).expanduser().is_dir()]
    if not paths:
        return '没有选仓库'
    repos = load_repos()
    names = []
    for p in paths:
        n = safe_name(Path(p).name)
        while n in repos and repos[n]['路径'] != p:
            n += '_'
        repos[n] = {'路径': p, '加入时间': now()}
        names.append(n)
        _ADDING[p] = time.time()
    REPOS_FILE.write_text(json.dumps(repos, ensure_ascii=False, indent=2), 'utf-8')

    def run():
        for n, p in zip(names, paths):
            try:
                index_repo(n)
            except Exception as e:
                print('建索引失败：', n, repr(e), flush=True)
            finally:
                _ADDING.pop(p, None)
    threading.Thread(target=run, daemon=True).start()
    return f'已登记 {len(paths)} 个仓库，现在就能在每一期里选；代码索引在后台建'


def onboard_hide(hide=True):
    s = load_settings()
    s['引导已收起'] = bool(hide)
    save_settings(s)
    return '引导已收起，在「? 帮助」里能看使用说明' if hide else '引导已打开'


# ---------------------------------------------------------------- 示例期：不用自己的仓库，点几下走完整个流程

DEMO = '示例-连续签到奖励'
_DEMO_REQ = """# 连续签到奖励（示例需求）

## 背景
提高日活：用户每天打开 App 签到，连续签到满 7 天弹出奖励弹窗。

## 需求
1. 首页右上角加「签到」入口，今天已签显示「已签到」。
2. 点签到：服务端记一次签到，返回连续天数。断签（昨天没签）从 1 重新算。
3. 连续第 7 天签到成功后弹奖励弹窗：标题「连续签到 7 天」，奖励金额由服务端下发（后台可配，默认 50 金币），按钮「收下」。
4. 领过的奖励不重复弹；第 8 天起重新累计。

## 验收
- 第 1~6 天签到只提示「已签到，连续 N 天」。
- 第 7 天签到后弹窗，金额与后台配置一致。
- 断签后连续天数归 1。
"""
_DEMO_SERVER = {
    'app.py': '''"""示例服务端：签到接口还没做。"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/ping':
            body = json.dumps({'ok': True}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == '__main__':
    HTTPServer(('127.0.0.1', 8000), H).serve_forever()
''',
    'requirements.txt': '',
    'README.md': '# 示例服务端\n\n`python app.py` 启动，端口 8000。\n',
}
_DEMO_ANDROID = {
    'settings.gradle': "rootProject.name = 'DemoApp'\ninclude ':app'\n",
    'build.gradle': '// 示例工程，只用来演示知识库流程\n',
    'app/build.gradle': "plugins { id 'com.android.application' }\n",
    'app/src/main/AndroidManifest.xml': '<manifest package="com.example.demo"><application android:label="Demo"><activity android:name=".HomeActivity"/></application></manifest>\n',
    'app/src/main/java/com/example/demo/HomeActivity.kt': '''package com.example.demo

import android.app.Activity
import android.os.Bundle

/** 首页：签到入口还没做。 */
class HomeActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
    }
}
''',
}


def _demo_repo(path, files):
    import subprocess
    if (path / '.git').exists():
        return
    for rel, body in files.items():
        f = path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, 'utf-8')
    g = lambda *a: subprocess.run(['git', *a], cwd=path, check=True, capture_output=True)
    g('init', '-q', '-b', 'main')
    g('add', '-A')
    g('-c', 'user.name=示例', '-c', 'user.email=demo@example.com', 'commit', '-qm', '示例仓库初始化')
    g('branch', 'feature-signin')


def demo_create(by='用户（网页）'):
    """建示例期：需求文档、设计说明、两个示例仓库（服务端 + Android，在 _system/示例仓库/），各端已选好。看完直接删这一期即可。"""
    if (PERIODS / DEMO).exists():
        return f'示例期已经有了：{DEMO}'
    base = SYS / '示例仓库'
    _demo_repo(base / 'server', _DEMO_SERVER)
    _demo_repo(base / 'android', _DEMO_ANDROID)
    create_period(DEMO, '示例：一个服务端 + Android 的小需求。跟着页面顶部的「下一步」点，体验出方案 → 拍板 → 开发 → 验收；看完右上角删除。')
    (PERIODS / DEMO / '需求' / '连续签到奖励.md').write_text(_DEMO_REQ, 'utf-8')
    add_note(DEMO, '奖励弹窗：居中卡片，圆角 16，顶部金币图标；标题「连续签到 7 天」18 号粗体；金额 32 号橙色；底部全宽按钮「收下」。'
             '签到入口：首页右上角，未签到显示「签到」，已签到显示灰色「已签到」。', category='设计图', kind='文字', title='设计说明（示例里用文字代替设计稿）')
    for end, sub in (('服务端', 'server'), ('Android', 'android')):
        stack_set_end(DEMO, end, str(base / sub), 'feature-signin', by=by)
    return f'已建好示例期「{DEMO}」：需求、设计说明、两个示例仓库都准备好了，打开它跟着顶部的「下一步」点就行'
