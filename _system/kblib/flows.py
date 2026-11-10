# From 大大王.DT
"""开发流程：「开始开发」后后台会话按哪套流程干活——怎么认仓库、文档目录在哪、提示词、进度怎么看、什么算做完。
内置「通用模板」；网页「⚙ 设置」里可修改（内置的改了能恢复默认）、新建、复制、导入导出，
方便其他研发组按自己的流程接入。每一期可单独选流程，不选就按仓库自动匹配、匹配不上用默认流程。"""
import json
import re
import subprocess
import uuid
from pathlib import Path
from .common import KBError, PERIODS, load_settings, read_text, save_settings
from .periods import is_task, load_meta, log, period_dir, period_names, save_meta
from . import lazy
_devices = lazy('kblib.devices')      # 上层模块：用到时才 import（不形成循环）


FLOW_VARS = {'期名': '期名', '仓库': '代码仓库绝对路径', '分支': '当前分支', '文档目录': '流程文档目录绝对路径',
             '资料目录': '本期资料副本目录绝对路径（文档目录/资料目录名）'}
FLOW_FIELDS = [   # 网页表单：键、标题、类型、说明
    ('名称', '名称', 'text', '如：iOS SDD、前端 Vibe 流程'),
    ('说明', '说明', 'textarea', '给人看的：适用哪个组、哪个端'),
    ('识别文件', '识别文件（每行一个，相对仓库根目录）', 'lines',
     '仓库里这些文件都存在才算用这套流程，用于自动匹配仓库；留空 = 任何 git 仓库都能用'),
    ('分支规则', '分支名规则（正则，可空）', 'text',
     '从文字资料里认出开发分支；带「/」的分支名（如 feature/xxx）总能认出，这里补充本组的命名，如 -stable 结尾'),
    ('文档目录方式', '文档目录怎么定', 'select:模板|命令', '开发文档、资料副本放在哪：按模板拼路径，或运行仓库里的脚本算出来'),
    ('文档目录模板', '文档目录模板', 'text', '相对仓库根目录或绝对路径，可用 {分支}、{分支目录}（「/」换成「_」）、{期名}、{仓库}'),
    ('文档目录命令', '文档目录命令', 'text', '在仓库根目录运行，输出路径；输出 JSON 时填下面的 JSON 键'),
    ('文档目录JSON键', '命令输出的 JSON 键', 'text', '如 PROJECT_DOCS；命令直接输出路径时留空'),
    ('资料目录名', '资料副本目录名', 'text', '本期资料拷到 文档目录/这个名字/（自动加 .gitignore，不进 git）'),
    ('准备方式', '准备方式', 'select:通用|SDD',
     '通用：拷资料 + 列候选链接；SDD：另外按仓库模板建 sdd-start.md / sdd-status.md，链接按 SDD 栏目分组'),
    ('流程配置文件', '流程配置文件（相对文档目录，可空）', 'text', '写着需求链接的配置文件（如 sdd-start.md）；更正链接时会一起改'),
    ('开发步骤', '开发步骤（后台会话按此推进）', 'textarea', '写清用什么命令、推进到什么状态算完成；可用变量见下方'),
    ('确认点', '需要人确认的地方', 'textarea', '流程里哪些地方要停下来让人确认（会用 kb_ask 发到网页）'),
    ('续跑提示', '自动续跑时的提示', 'textarea', '会话中途退出后续跑时，怎么确认实际进度'),
    ('开发约定', '开发约定（写进开发包）', 'textarea', '终端里手动开发时 Claude 也会看到'),
    ('需求变更提示', '需求有变化 / 链接更正时', 'textarea', '开发中需求来源更新或链接更正后，怎么同步到流程里'),
    ('进度类型', '进度怎么看', 'select:无|任务清单|SDD',
     '无：只看动作流水；任务清单：读文档目录下 Markdown 勾选框；SDD：读 sdd-status.md'),
    ('任务清单文件', '任务清单文件（相对文档目录）', 'text', '进度类型为「任务清单」时：- [x] 已完成、- [ ] 未完成；全部勾完算开发完成'),
    ('测试文件', '测试用例 / 自动化测试文件（每行一个，相对文档目录，可用通配符）', 'lines',
     '识别到这些文件，开发面板就出现「🔁 复测」：开发时手机不够、没连手机没测成的 case，条件具备后补测。'
     '用例写成「### 编号: PASS / FAIL / BLOCKED」能统计结果'),
    ('复测步骤', '复测步骤（点「复测」后后台会话按此执行）', 'textarea', '可用变量同上，另有 {范围}（只测没通过的 / 全部）'),
]
BUILTIN_FLOWS = {
    'generic': {
        '名称': '通用模板', '说明': '不依赖仓库里的特定脚本，任何 git 仓库都能用；其他研发组可以复制这一套改成自己的流程',
        '识别文件': [], '分支规则': '',
        '文档目录方式': '模板', '文档目录模板': 'docs/kb/{分支目录}', '文档目录命令': '', '文档目录JSON键': '',
        '资料目录名': 'kb-materials', '准备方式': '通用', '流程配置文件': '',
        '开发步骤': """1. kb_dev_prepare 准备资料（拷到 {资料目录}），通读需求、设计稿、接口文档和仓库相关代码。
2. 在 {文档目录}/plan.md 写技术方案（改哪些模块、接口、风险），在 {文档目录}/tasks.md 用「- [ ] 任务」列出任务清单；用 kb_ask 请用户确认方案后再写代码。
3. 按任务清单逐条开发：改代码 → 编译 / 运行相关测试 → 在 tasks.md 勾上「- [x]」→ 按仓库惯例提交；直到全部勾完。""",
        '确认点': '技术方案、与需求 / 设计稿不一致的地方、方案取舍、缺少账号或环境、操作被权限拦截等',
        '续跑提示': '先看 {文档目录}/tasks.md 的勾选情况和 git status / git log 确认实际进度，没做完的任务接着做',
        '开发约定': '- 先 kb_dev_prepare 拷贝资料，方案写在 {文档目录}/plan.md，任务清单写在 {文档目录}/tasks.md，做完一条勾一条',
        '需求变更提示': '先 kb_dev_prepare 同步资料副本，对照差异更新 plan.md / tasks.md；影响已写代码的用 kb_ask 确认，并 kb_log 记录',
        '进度类型': '任务清单', '任务清单文件': 'tasks.md',
        '测试文件': ['test-cases.md', 'tests/**/*'],
        '复测步骤': """1. 读 {文档目录} 下的测试用例和自动化测试脚本：{范围}。
2. 要用手机时 kb_devices 看、kb_device_claim 申请，只在申请到的手机上装包、测试（adb -s <序列号>）；有自动化测试脚本的直接运行脚本。
3. 结果追加到用例文件末尾的「## 复测（日期）」小节，每条写「### 编号: PASS / FAIL / BLOCKED（原因）」，不改原来的记录。""",
    },
}
BUILTIN_FLOWS['task-light'] = {
    '名称': '轻量（事项）', '说明': '事项默认用：ANR / 崩溃、加埋点、线上问题、小优化等不是产品需求的工作。定位 → 确认改法 → 修改自测 → 写结论',
    '识别文件': [], '分支规则': '',
    '文档目录方式': '模板', '文档目录模板': 'docs/kb/{分支目录}', '文档目录命令': '', '文档目录JSON键': '',
    '资料目录名': 'kb-materials', '准备方式': '通用', '流程配置文件': '',
    '开发步骤': '''1. kb_dev_prepare 准备资料（拷到 {资料目录}）。关联了 Bug 的，逐个用 kb_bug_get 实时拉取正文、评论、截图（截图用 Read 看）；关联了 ANR / 崩溃问题的，用 kb_anr 看合并后的关键堆栈（有 mapping 已还原）、次数、版本和样本原文；有日志、traces、堆栈的先读。
   在 {文档目录}/tasks.md 写下五步并逐步勾选：- [ ] 定位　- [ ] 确认改法　- [ ] 修改　- [ ] 自测　- [ ] 结论
2. 定位：kb_search（scope=code）、grep、git log / blame 找相关代码，写 {文档目录}/analysis.md：现象、根因（证据：代码 路径:行号、日志、复现步骤）、
   改法（可给备选）、影响范围、自测要点。埋点类写清事件名、参数、触发时机、上报位置；ANR / 崩溃写清卡住或崩溃的线程和调用链。
3. 用 kb_ask 把根因和改法发给用户确认（recommend 填你推荐的改法），拿到回答再改代码。
4. 按确认的改法修改 → 编译 / 跑相关测试 → 能上手机的按 kb_devices / kb_device_claim 申请后验证 → 按仓库惯例提交。验证不了的用 kb_issue 记下，继续。
5. 结论：用 kb_write_doc 在本事项「其他资料」写「结论.md」（现象、根因、改法、提交、改动的代码位置、验证情况、以后同类问题怎么查），
   kb_log 汇总，kb_set_status 改为「已完成」。''',
    '确认点': '根因和改法（必须确认后再改代码）、改动影响线上付费 / 核心链路、埋点事件名和参数口径、缺少日志或复现条件、操作被权限拦截等',
    '续跑提示': '先看 {文档目录}/tasks.md、analysis.md 和 git status / git log，确认做到哪一步，没做完的接着做',
    '开发约定': '- 这是「事项」（不是产品需求）：先定位写 analysis.md，用 kb_ask 确认改法再改代码，最后写 结论.md；改动尽量小，只改和本事项有关的代码',
    '需求变更提示': '先 kb_dev_prepare 同步资料副本；有关联 Bug 的重新 kb_bug_get 拉取，对照变化更新 analysis.md；影响已改代码的用 kb_ask 确认，并 kb_log 记录',
    '进度类型': '任务清单', '任务清单文件': 'tasks.md',
    '测试文件': [], '复测步骤': '',
}
TASK_FLOW = 'task-light'
DEFAULT_FLOW = 'generic'


def flows():
    """全部开发流程（内置的在前），每个带 id、内置、已修改、默认。"""
    s = load_settings()
    out = []
    for fid, base in BUILTIN_FLOWS.items():
        f = dict(base, **(s['流程'].get(fid) or {}))
        out.append(dict(f, id=fid, 内置=True, 已修改=fid in s['流程']))
    for fid, f in s['流程'].items():
        if fid not in BUILTIN_FLOWS:
            out.append(dict(BUILTIN_FLOWS['generic'], **f, id=fid, 内置=False, 已修改=False))
    for f in out:
        f['默认'] = f['id'] == s['默认流程']
    return out


def get_flow(fid=''):
    fs = flows()
    fid = fid or load_settings()['默认流程']
    f = next((x for x in fs if x['id'] == fid), None)
    if not f:
        if fid == load_settings()['默认流程']:
            return next(x for x in fs if x['id'] == DEFAULT_FLOW)
        raise KBError(f'没有这个开发流程：{fid}')
    return f


def save_flow(data, by='用户（网页）'):
    """新建 / 修改开发流程。data 带 id 是修改（内置的存为修改项），不带是新建。"""
    s = load_settings()
    keys = [k for k, *_ in FLOW_FIELDS]
    f = {k: data[k] for k in keys if k in data}
    for k, _, typ, _ in FLOW_FIELDS:
        if typ == 'lines' and isinstance(f.get(k), str):
            f[k] = [x.strip() for x in f[k].splitlines() if x.strip()]
    for k, _, typ, _ in FLOW_FIELDS:
        if typ.startswith('select:') and k in f and f[k] not in typ[7:].split('|'):
            raise KBError(f'「{k}」只能是：{typ[7:].replace("|", " / ")}')
    if f.get('分支规则'):
        try:
            re.compile(f['分支规则'])
        except re.error as e:
            raise KBError(f'分支名规则不是合法的正则：{e}')
    if not (f.get('名称') or '').strip():
        raise KBError('流程名称不能为空')
    fid = (data.get('id') or '').strip()
    if not fid:
        fid = 'flow-' + uuid.uuid4().hex[:6]
    elif fid not in BUILTIN_FLOWS and fid not in s['流程']:
        raise KBError(f'没有这个开发流程：{fid}')
    if any(x['名称'] == f['名称'] and x['id'] != fid for x in flows()):
        raise KBError(f'已经有叫「{f["名称"]}」的流程了')
    s['流程'][fid] = f
    save_settings(s)
    return f'已保存开发流程「{f["名称"]}」（{by}）', fid


def delete_flow(fid):
    """自定义的删除；内置的恢复默认。"""
    s = load_settings()
    if fid not in s['流程']:
        raise KBError('内置流程没有修改过，不用恢复' if fid in BUILTIN_FLOWS else f'没有这个开发流程：{fid}')
    name = get_flow(fid)['名称']
    s['流程'].pop(fid)
    if fid not in BUILTIN_FLOWS:
        if s['默认流程'] == fid:
            s['默认流程'] = DEFAULT_FLOW
        for n in period_names():
            d = PERIODS / n
            m = load_meta(d)
            if m.get('开发流程') == fid:
                m.pop('开发流程')
                save_meta(d, m)
    save_settings(s)
    return f'已恢复内置流程「{name}」的默认设置' if fid in BUILTIN_FLOWS else f'已删除开发流程「{name}」'


def set_default_flow(fid):
    f = get_flow(fid)
    s = load_settings()
    s['默认流程'] = f['id']
    save_settings(s)
    return f'默认开发流程改为「{f["名称"]}」'


def set_period_flow(period, fid):
    """某一期用哪套开发流程；空 = 自动（按仓库匹配，匹配不上用默认）。"""
    d = period_dir(period)
    f = get_flow(fid) if fid else None
    m = load_meta(d)
    if (m.get('开发流程') or '') == (fid or ''):
        return '没有变化'
    if f:
        m['开发流程'] = f['id']
    else:
        m.pop('开发流程', None)
    save_meta(d, m)
    log(d, '开发流程', f['名称'] if f else '自动（按仓库匹配）')
    return f'「{d.name}」的开发流程改为「{f["名称"] if f else "自动"}」'


def flow_matches(f, root):
    return all((Path(root) / x).exists() for x in f.get('识别文件') or [])


def flow_for(m, root):
    """这个仓库用哪套流程：这一期选定的 > 事项默认轻量流程 > 识别文件对得上的（默认流程优先）> 不要求识别文件的默认流程。对不上返回 None。"""
    if not m.get('开发流程') and is_task(m):
        return get_flow(TASK_FLOW)
    if m.get('开发流程'):
        f = get_flow(m['开发流程'])
        return f if flow_matches(f, root) else None
    fs = sorted(flows(), key=lambda x: not x['默认'])
    for f in fs:
        if f.get('识别文件') and flow_matches(f, root):
            return f
    f = fs[0]
    return f if not f.get('识别文件') else None


def period_flow(m):
    """还没定仓库时用的流程（开发包、需求变更提醒）：这一期选定的 > 上次开发用的 > 默认。"""
    for fid in (m.get('开发流程'), (m.get('开发会话') or {}).get('流程'), TASK_FLOW if is_task(m) else ''):
        if fid:
            try:
                return get_flow(fid)
            except KBError:
                pass
    return get_flow()


def flow_text(f, key, **v):
    """流程里的文字，替换 {期名} 等变量；不认识的 {xxx} 原样保留。"""
    class Keep(dict):
        def __missing__(self, k):
            return '{' + k + '}'
    try:
        return (f.get(key) or '').format_map(Keep(v))
    except (ValueError, IndexError):
        return f.get(key) or ''


def flow_docs(f, root, branch, period, store=''):
    """按流程算文档目录。"""
    root = Path(root)
    v = dict(仓库=str(root), 分支=branch, 分支目录=branch.replace('/', '_'), 期名=period)
    if f.get('文档目录方式') == '命令':
        cmd = flow_text(f, '文档目录命令', **v) + (f' {store}' if store else '')
        try:
            r = subprocess.run(cmd, shell=True, cwd=root, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            raise KBError(f'取文档目录超时：{cmd}')
        out = r.stdout.strip()
        try:
            p = json.loads(out)[f['文档目录JSON键']] if f.get('文档目录JSON键') else out.splitlines()[-1]
        except (ValueError, KeyError, IndexError, TypeError):
            raise KBError(f'取文档目录失败（{cmd}）：{(r.stderr or out).strip()[:500]}')
    else:
        p = flow_text(f, '文档目录模板', **v).strip()
        if not p:
            raise KBError(f'开发流程「{f["名称"]}」没有设置文档目录')
    p = Path(p).expanduser()
    return p if p.is_absolute() else (root / p).resolve()


def task_progress(f, docs):
    """任务清单进度：Markdown 勾选框。"""
    p = Path(docs or '') / (f.get('任务清单文件') or 'tasks.md')
    if not docs or not p.is_file():
        return None
    items = re.findall(r'^\s*[-*+]\s+\[([ xX])\]\s+(.+)$', read_text(p), re.M)
    done = sum(1 for x, _ in items if x.lower() == 'x')
    cur = next((t.strip() for x, t in items if x == ' '), '')
    return {'类型': '任务清单', '文件': str(p), '完成': done, '总数': len(items), '当前': cur[:200]}


def flow_progress(f, docs):
    if not f or not docs:
        return None
    if f.get('进度类型') == 'SDD':
        pg = _devices.sdd_progress(docs)
        return dict(pg, 类型='SDD') if pg else None
    if f.get('进度类型') == '任务清单':
        return task_progress(f, docs)
    return None


def flow_done(f, docs):
    if not f or not docs:
        return False
    if f.get('进度类型') == 'SDD':
        return _devices._sdd_status(docs).get('step3') == 'done'
    if f.get('进度类型') == '任务清单':
        t = task_progress(f, docs)
        return bool(t and t['总数'] and t['完成'] == t['总数'])
    return False
