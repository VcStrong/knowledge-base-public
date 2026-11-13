#!/usr/bin/env python3
"""架构检查：改完程序跑一下（python3 tools/check-arch.py），有问题会列出来并以非 0 退出。

查这几件事：
  1. 分层：kblib 各包只能在模块顶部 import 同层或更下层的包（上层要用时写 lazy('kblib.x')，调用时才取）。
     已知的跨层读取登记在 ALLOWED 里，新增的跨层要么改结构，要么想清楚后登记并写原因。
  2. 重名：kblib 各模块的公开函数不能重名（kb.py 会把它们合到一个命名空间，后来的会覆盖先来的）。
  3. 接口：webapp/routes/ 里每个接口函数用到的名字都有定义；同一路径没有重复登记。
  4. 前端：ui/core/*.js 拼起来、ui-templates.js、各模板的 app.js 语法正确（有 node 才查）。
  5. 模板：ui/<目录>/ 里有 index.html 的，必须有 template.json（名称、说明、顺序）。
"""
import ast
import builtins
import glob
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYS = ROOT / '_system'
sys.path.insert(0, str(SYS))

# 层：下层不 import 上层。同一层之间可以互相用（尽量少）。
LAYERS = [
    ('core', 'infra'),                      # 基础：路径设置、期、资料、检索、基础信息、主机和版本库、锁、抓取、机密
    ('ai', 'plugins', 'sources'),           # 能力：AI 引擎和会话、插件机制、外部资料导入
    ('bugs', 'anr', 'tasks', 'stack'),      # 领域：Bug、ANR、事项、全栈
    ('steward',),                           # 管家：巡检、交给管家、智能状态、整站导航、引导
    ('api',),                               # 对外：MCP、命令行、总览文本（网页接口在 _system/webapp/）
]
ALLOWED = {   # 已知的跨层（下层 → 上层）读取：(从哪个模块, 到哪个包) → 原因
    ('kblib.ai.talk', 'bugs'): '期页面对话要带上这一期的 Bug 和分析会话',
    ('kblib.plugins.builds', 'bugs'): '构建要关联 Bug 的提测包',
    ('kblib.plugins.stats', 'bugs'): '工作统计要数 Bug',
    ('kblib.plugins.stats', 'anr'): '工作统计要数 ANR',
}
LEVEL = {p: i for i, grp in enumerate(LAYERS) for p in grp}
problems = []


def bad(kind, msg):
    problems.append(f'[{kind}] {msg}')


# ---- 1. 分层
for f in sorted((SYS / 'kblib').rglob('*.py')):
    rel = f.relative_to(SYS).with_suffix('')
    mod = '.'.join(rel.parts).removesuffix('.__init__')
    parts = mod.split('.')
    if len(parts) < 3:
        continue
    pkg = parts[1]
    for n in ast.parse(f.read_text('utf-8')).body:          # 只看模块顶部（函数里的 import 是用到时才取）
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith('kblib.'):
            tgt = n.module.split('.')[1]
            if tgt == pkg or tgt not in LEVEL or pkg not in LEVEL:
                continue
            if LEVEL[tgt] > LEVEL[pkg] and (mod, tgt) not in ALLOWED:
                bad('分层', f'{mod} 在顶部 import 了上层的 kblib.{tgt}（{LAYERS[LEVEL[pkg]]} 不能依赖 {LAYERS[LEVEL[tgt]]}）：'
                            f'改成 lazy(\'{n.module}\')，或把要用的东西移到下层')

# ---- 2. 重名（kb.py 导入时也会拦，这里给出更清楚的位置）
try:
    import kb  # noqa: F401
except ImportError as e:
    bad('重名', str(e))

# ---- 3. 接口
try:
    import web  # noqa: F401
    import webapp.shared as sh
    avail = set(sh.__all__) | set(dir(builtins))
    for p in sorted(glob.glob(str(SYS / 'webapp' / 'routes' / '*.py'))) + [str(SYS / 'webapp' / 'server.py')]:
        t = ast.parse(Path(p).read_text('utf-8'))
        top = set()
        for n in ast.walk(t):
            if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
                top.add(n.name)
        for n in t.body:
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                top |= {(a.asname or a.name).split('.')[0] for a in n.names}
        funcs = [n for n in t.body if isinstance(n, ast.FunctionDef)] + \
                [m for c in t.body if isinstance(c, ast.ClassDef) for m in c.body if isinstance(m, ast.FunctionDef)]
        for fn in funcs:
            loc = set()
            for x in ast.walk(fn):
                if isinstance(x, ast.arg):
                    loc.add(x.arg)
                elif isinstance(x, ast.Name) and isinstance(x.ctx, (ast.Store, ast.Del)):
                    loc.add(x.id)
                elif isinstance(x, ast.FunctionDef):
                    loc.add(x.name)
                elif isinstance(x, ast.ExceptHandler) and x.name:
                    loc.add(x.name)
                elif isinstance(x, (ast.Import, ast.ImportFrom)):
                    loc |= {(a.asname or a.name).split('.')[0] for a in x.names}
            for x in ast.walk(fn):
                if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load) and x.id not in loc | avail | top:
                    bad('接口', f'{Path(p).name}:{x.lineno} {fn.name} 用到了没定义的 {x.id}')
except Exception as e:   # 重复登记等会在 import 时抛出
    bad('接口', repr(e))

# ---- 4. 前端语法
node = shutil.which('node')
if node:
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as tmp:
        tmp.write('\n'.join(Path(f).read_text('utf-8') for f in sorted(glob.glob(str(SYS / 'ui' / 'core' / '*.js')))))
    files = [tmp.name, str(SYS / 'ui-templates.js')] + sorted(glob.glob(str(SYS / 'ui' / '*' / 'app.js')))
    for f in files:
        r = subprocess.run([node, '--check', f], capture_output=True, text=True)
        if r.returncode:
            bad('前端', (f if f != tmp.name else 'ui/core/*.js（拼接后）') + '：' + (r.stderr.strip().splitlines() or [''])[0])
    Path(tmp.name).unlink(missing_ok=True)
else:
    print('（没有 node，跳过前端语法检查）')

# ---- 5. 模板
for d in sorted((SYS / 'ui').iterdir()):
    if d.is_dir() and (d / 'index.html').is_file():
        f = d / 'template.json'
        if not f.is_file():
            bad('模板', f'ui/{d.name}/ 缺 template.json（名称、说明、顺序）')
            continue
        try:
            m = json.loads(f.read_text('utf-8'))
            if not m.get('名称'):
                bad('模板', f'ui/{d.name}/template.json 没写「名称」')
        except ValueError as e:
            bad('模板', f'ui/{d.name}/template.json 不是合法 JSON：{e}')

if problems:
    print('\n'.join(problems))
    sys.exit(1)
print('架构检查通过')
