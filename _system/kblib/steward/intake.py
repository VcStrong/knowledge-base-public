"""执行者视角的「收件」：给了日志就必然要处理，不追问信息全不全。

  贴 ANR / 崩溃日志（问管家、或管家巡检到新问题）→ 不调模型，直接：归档成问题（同一问题自动合并计数）→ 建事项（已有就用已有的）
  → 只问一个问题：在哪个工程、哪个分支（默认值已经选好）→ 你点「▶ 推动」= 你本人批准 → AI 分析、修改、自测、写结论。
提议（推动卡片）格式：{类型: 推动, 事项, 条目: [anr:编号…], 仓库: [{路径, 名称, 分支, 端}], 默认仓库, 默认分支, 说明}
"""
from pathlib import Path

from kblib.core.common import KBError, PERIODS
from kblib.core.periods import load_meta, period_names, is_task
from kblib.anr import parse as _parse
from kblib.anr.store import _ar_load, anr_link, anr_problems
from kblib.anr.manual import _setup_task, anr_create
from kblib.tasks.memo import task_item_push, task_items
from kblib.stack.plan import stack_repos
from kblib.core.notes import note_title, notes_of
from kblib.infra import hosts


def looks_like_log(text):
    """像不像 ANR / 崩溃日志：能切出至少一个事件（堆栈）。"""
    t = (text or '').strip()
    if len(t) < 80:
        return False
    try:
        return bool(_parse.split_events(t))
    except Exception:
        return False


def link_task(pids, by='管家'):
    """把问题归到事项：已经有事项的用原来的；没有的一起建一个新事项。返回事项名。"""
    ps = {p['编号']: p for p in anr_problems(True)}
    has = [ps[x]['事项'] for x in pids if x in ps and ps[x]['事项']]
    free = [x for x in pids if x in ps and not ps[x]['事项']]
    name = has[0] if has else ''
    for pid in free:
        if name:
            anr_link(pid, task=name, by=by)
        else:
            anr_link(pid, task='＋新建', by=by)
            name = next(p['事项'] for p in anr_problems(True) if p['编号'] == pid)
    return name


def anr_intake_text(text, by='用户（问管家）'):
    """贴的日志 → 问题 + 事项。返回 (事项名, 问题编号列表, 一句说明)。"""
    before = {s['编号'] for s in _ar_load()}
    try:
        msg = anr_create(text, by=by)
        pids = list(dict.fromkeys(s['问题'] for s in _ar_load() if s['编号'] not in before))
    except KBError as e:
        if '没有新的事件' not in str(e):
            raise
        raw = {_parse.raw_id(ev['原文']) for ev in _parse.split_events(text)}     # 这份日志以前收过：找回它的问题
        pids = list(dict.fromkeys(s['问题'] for s in _ar_load() if s['编号'] in raw))
        msg = '这份日志以前收过'
    if not pids:
        raise KBError('没从日志里认出 ANR / 崩溃：' + msg.splitlines()[0])
    ps = {p['编号']: p for p in anr_problems(True)}
    old = [x for x in pids if ps.get(x, {}).get('事项')]
    task = link_task(pids, by)
    seen = [x for x in pids if ps.get(x, {}).get('次数', 1) > 1]
    desc = ('这份日志以前收过，' if msg == '这份日志以前收过' else '') + f'认出 {len(pids)} 个问题（{"、".join(pids)}）' + \
        (f'，其中 {len(seen)} 个以前出现过，已合并计数' if seen and msg != '这份日志以前收过' else '') + \
        (f'，归到原来的事项「{task}」' if old else f'，建了事项「{task}」')
    return task, pids, desc


def _branch(path):
    try:
        return hosts.branch_of(path)
    except Exception:
        return ''


def push_repo_choices(task, kind='Android'):
    """候选工程和默认值：事项自己的 > 最近处理同类问题的事项用过的 > 认出是这一端的本机仓库。"""
    m = load_meta(PERIODS / task) if task and (PERIODS / task).is_dir() else {}
    used = []
    for n in sorted(period_names(), key=lambda n: load_meta(PERIODS / n).get('更新时间', ''), reverse=True):
        mm = load_meta(PERIODS / n)
        if is_task(mm) and mm.get('事项类型') == 'ANR/崩溃' and mm.get('开发仓库'):
            used.append(mm['开发仓库'])
    try:
        rs = stack_repos()
    except Exception:
        rs = []
    cands = []
    for p in [m.get('开发仓库')] + used + [r['路径'] for r in rs if kind in (r.get('端') or [])] + [r['路径'] for r in rs]:
        if p and p not in cands and not hosts.is_remote(p) and Path(p).is_dir():
            cands.append(p)
    out = [{'路径': p, '名称': Path(p).name, '分支': _branch(p)} for p in cands[:12]]
    return out, (out[0]['路径'] if out else ''), (out[0]['分支'] if out else '')


def _task_branch(task, m):
    return next((note_title(n) for n in notes_of(PERIODS / task, m=m) if n.get('类型') == '分支'), '')


def push_proposal(task, keys=None, kind='Android'):
    """推动卡片：事项里还没处理的 ANR / 崩溃条目 + 候选工程、默认工程和分支。"""
    items = [x for x in task_items(task) if x['键'].startswith('anr:') and x.get('状态') in (None, '', '待处理', '没解决')]
    keys = keys or [x['键'] for x in items]
    repos, repo, branch = push_repo_choices(task, kind)
    m = load_meta(PERIODS / task)
    return {'类型': '推动', '事项': task, '条目': keys, '仓库': repos, '默认仓库': m.get('开发仓库') or repo,
            '默认分支': _task_branch(task, m) or branch, '说明': '确认工程和分支，点「▶ 推动」就开始：定位原因 → 改代码 → 自测 → 写结论（你点了才算批准）'}


def confirm_proposal(p, repo, branch, by='用户（网页）'):
    """按提议的类型执行：推动事项条目 / Bug 只读分析。"""
    if p.get('类型') == 'Bug分析':
        from kblib.bugs.analysis import bug_analyze_in
        if not repo:
            raise KBError('先选仓库')
        return bug_analyze_in(p['Bug'], repo, by=by)
    return confirm_push(p['事项'], p['条目'], repo, branch, by=by)


def confirm_push(task, keys, repo, branch, by='用户（网页）'):
    """你点了「▶ 推动」：记下工程和分支，逐条推动（第一条起会话，其余排在它后面）。"""
    repo, branch = (repo or '').strip(), (branch or '').strip()
    if not repo:
        raise KBError('先选工程')
    if not Path(repo).expanduser().is_dir():
        raise KBError(f'工程目录不存在：{repo}')
    if not keys:
        raise KBError('没有要推动的条目')
    m = load_meta(PERIODS / task)
    _setup_task(task, branch if branch and branch != _task_branch(task, m) else '', repo if repo != m.get('开发仓库') else '', by)
    return '\n'.join(task_item_push(task, k, by=by) for k in keys)


# ---------------------------------------------------------------- 统一入口：文件、Bug、归档之后的下一步

LOG_EXT = {'.txt', '.log', '.zip', '.trace', '.traces', '.anr', '.gz'}


def is_log_file(p):
    p = Path(p)
    if p.suffix.lower() in ('.zip', '.gz', '.trace', '.traces', '.anr'):
        return True
    if p.suffix.lower() in LOG_EXT:
        try:
            return looks_like_log(p.read_text('utf-8', 'replace')[:400000])
        except OSError:
            return False
    return False


def anr_intake_files(paths, by='用户（问管家）'):
    """日志文件 → 问题 + 事项，和贴文字一样。"""
    from kblib.anr.manual import anr_create as _create
    before = {s['编号'] for s in _ar_load()}
    msg = _create('', [str(p) for p in paths], by=by)
    pids = list(dict.fromkeys(s['问题'] for s in _ar_load() if s['编号'] not in before))
    if not pids:
        raise KBError('没从文件里认出 ANR / 崩溃：' + msg.splitlines()[0])
    task = link_task(pids, by)
    return task, pids, f'从 {len(paths)} 个文件认出 {len(pids)} 个问题（{"、".join(pids)}），归到事项「{task}」'


def bug_refs(text):
    """文字里提到的、索引里有的 Bug（禅道链接 bug-view-123、「Bug 123」、#123、Jira 的 ABC-123）。"""
    import re
    from kblib.bugs.index import zt_load
    bugs = zt_load().get('Bug') or {}
    ids = re.findall(r'bug-view-(\d+)|[Bb]ug\s*[#：:]?\s*(\d{3,8})|#(\d{3,8})\b|\b([A-Z][A-Z0-9]+-\d+)\b', text or '')
    out = []
    for g in ids:
        x = next((v for v in g if v), '')
        if x and x in bugs and x not in out:
            out.append(x)
    if not out and re.fullmatch(r'\s*\d{3,8}(\s*[,，、\s]\s*\d{3,8})*\s*', text or ''):       # 只贴了编号
        out = [x for x in re.findall(r'\d{3,8}', text) if x in bugs]
    return out


def bug_proposal(ids, why=''):
    """不知道在哪个仓库分析的 Bug：给候选仓库，点了就只读分析。"""
    repos, repo, _ = push_repo_choices('', 'Android')
    return {'类型': 'Bug分析', 'Bug': ids, '仓库': repos, '默认仓库': repo,
            '说明': (why + '；' if why else '') + '选一个仓库，点「▶ 分析」就在那里只读分析（不改代码），以后同产品的 Bug 自动用它'}


def period_stamps():
    out = {}
    for n in period_names():
        try:
            out[n] = load_meta(PERIODS / n).get('更新时间', '')
        except Exception:
            pass
    return out


def next_steps(before):
    """这次动过（新建或更新）的期 / 事项，各自的下一步（期用 period_guide）。"""
    from kblib.stack.guide import period_guide
    out = []
    for n, t in period_stamps().items():
        if before.get(n) == t:
            continue
        try:
            g = period_guide(n)
        except Exception:
            g = None
        if g:
            x = g['下一步']
            out.append({'名称': n, '文字': x['文字'], '说明': x['说明'], '谁': x['谁'], '链接': '#/p/' + n})
        else:
            out.append({'名称': n, '文字': '已放进这个事项', '说明': '在事项页逐条点「推动」，或告诉我先处理哪条', '谁': '你', '链接': '#/p/' + n})
    return out


def preview(text):
    """理解预览（不调模型）：你还没回车，先说它看懂了什么、打算怎么做、有多大把握。"""
    import re
    t = (text or '').strip()
    if not t:
        return {'标签': [], '计划': '', '把握': None}
    if looks_like_log(t):
        tags = [['ANR / 崩溃日志', 'g']]
        try:
            raw = {_parse.raw_id(ev['原文']) for ev in _parse.split_events(t)}
            old = [s for s in _ar_load() if s['编号'] in raw]
            if old:
                ps = {p['编号']: p for p in anr_problems(True)}
                p = ps.get(old[0]['问题'], {})
                tags.append([f'收过的问题 {old[0]["问题"]} · 共 {p.get("次数", 1)} 次', 't'])
                if p.get('事项'):
                    tags.append([f'→ 事项「{p["事项"]}」', 't'])
        except Exception:
            pass
        _, repo, br = push_repo_choices('', 'Android')
        if repo:
            tags.append([f'工程 {Path(repo).name}' + (f' · {br}' if br else ''), 'g'])
        return {'标签': tags, '计划': '归成问题、建事项，只问你工程和分支，点「▶ 推动」就开始修', '把握': 95}
    bugs = bug_refs(t)
    if bugs:
        return {'标签': [[f'Bug {b}', 'g'] for b in bugs[:5]], '计划': '直接在它的仓库里只读分析，好了等你审核', '把握': 90}
    tags, plan, p = [], '交给管家整理归档，接着推下一步', 60
    urls = re.findall(r'https?://[^\s，。）)]+', t)
    for u in urls[:3]:
        host = re.sub(r'^https?://', '', u).split('/')[0]
        kind = '设计稿' if any(x in host for x in ('figma', 'lanhu')) else '需求文档' if any(x in u.lower() for x in ('wiki', 'confluence', 'prd', 'doc')) else '链接'
        tags.append([f'{kind} · {host}', 'g'])
        p = max(p, 75)
    hit = next((n for n in period_names() if n in t or (len(n) > 4 and n.split('-')[-1] in t)), '')
    if hit:
        tags.append([f'→ 期「{hit}」', 't'])
        p = max(p, 80)
    elif urls or len(t) > 40:
        tags.append(['→ 对不上就新建一期', 't'])
    if re.search(r'账号|密码|token|令牌|VPN|代理|Wi-?Fi', t, re.I):
        tags.append(['账号 / 环境 → 基础信息（密码加密保存）', 'w'])
        plan = '存进基础信息，密码单独加密'
    elif re.search(r'[？?]$|^(怎么|如何|为什么|什么|哪)', t):
        tags, plan, p = [['问题', 'g']], '查知识库再回答你', 80
    elif not tags:
        tags.append(['需求或说明', 'g'])
        p = 55
    return {'标签': tags, '计划': plan, '把握': p}
