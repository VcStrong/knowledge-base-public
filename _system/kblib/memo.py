"""事项的「记事本」：一个事项是一组条目，每条都能单独推动给 AI 分析处理；分支、工程等放在「补充」里。

条目来源：
- 手记的（期信息「条目」：[{编号 E001, 内容, 时间}]）；
- 关联到这个事项的 ANR / 崩溃问题（anr:<编号>）、归到这个事项的 Bug（bug:<编号>），实时取，不另存。
每条的进展记在期信息「条目状态」：{条目键: {状态, 推动时间, 结论, 结论时间}}，状态：待处理 / 推动中 / 已解决 / 没解决 / 待确认。
推动（你本人点 = 批准）：不走开发流程（SDD 等），把这一条和补充交给 AI 自行判断；会话在跑就交给它（排在当前工作后面），\n推动过就接着上次的会话（保留上下文），否则新开会话。
AI 处理完用 kb_task_item 把这一条的结论记回来。
"""
from pathlib import Path

from .common import PERIODS, KBError, now
from .periods import is_task, load_meta, log, period_dir, period_names, save_meta, set_status
from .notes import note_title, notes_of
from .devsession import _NO_BG, _dev_spawn, _session_id, dev_chat, dev_session
from .bugs.index import zt_load
from .anr.store import anr_problems

ITEM_STATES = ('待处理', '推动中', '已解决', '没解决', '待确认')


def task_items(name):
    d = period_dir(name)
    m = load_meta(d)
    st = m.get('条目状态') or {}
    out = []
    for x in m.get('条目') or []:
        out.append({'键': x['编号'], '类型': '记录', '标题': x['内容'].split('\n')[0][:120], '内容': x['内容'], '时间': x.get('时间', '')})
    for p in anr_problems(True):
        if p.get('事项') == d.name:
            out.append({'键': 'anr:' + p['编号'], '类型': 'ANR' if p['类型'] == 'ANR' else '崩溃', '标题': p['标题'],
                        '内容': f'{p["类型"]} 问题 {p["编号"]}，{p["次数"]} 次' + (f'，版本 {"、".join(p["版本"])}' if p['版本'] else ''),
                        '时间': p['首次'], '编号': p['编号']})
    try:
        for e in zt_load()['Bug'].values():
            o = e.get('归属') or {}
            if o.get('类型') == '事项' and o.get('名称') == d.name:
                out.append({'键': 'bug:' + e['编号'], '类型': 'Bug', '标题': e['标题'], '内容': e.get('简介', ''),
                            '链接': e.get('链接', ''), '时间': e.get('创建时间', ''), '编号': e['编号']})
    except (KBError, OSError):
        pass
    for x in out:
        x.update(st.get(x['键']) or {})
        x.setdefault('状态', '待处理')
    return out


def task_memo(name):
    """事项记事本页：条目 + 补充（分支、工程、来自、文字资料）+ 会话状态。"""
    d = period_dir(name)
    m = load_meta(d)
    sup = [{'类型': n.get('类型'), '编号': n['编号'], '内容': note_title(n) if n.get('类型') == '分支' else n.get('内容') or note_title(n)}
           for n in notes_of(d, m=m)]
    s = dev_session(d.name) or {}
    return {'名称': d.name, '状态': m.get('状态'), '事项类型': m.get('事项类型', ''), '优先级': m.get('优先级', ''),
            '来自': m.get('来自', ''), '说明': m.get('说明', ''), '工程': m.get('开发仓库', ''), '补充': sup,
            '条目': task_items(d.name), '会话': {k: s.get(k) for k in ('状态', '开始时间', '结束时间', '仓库', '分支')} if s else None}


def task_item_add(name, text, by='用户（网页）'):
    d = period_dir(name)
    text = (text or '').strip()
    if not text:
        raise KBError('写点内容')
    m = load_meta(d)
    xs = m.setdefault('条目', [])
    nid = f'E{max([int(x["编号"][1:]) for x in xs] + [0]) + 1:03d}'
    xs.append({'编号': nid, '内容': text, '时间': now(), '记录人': by})
    save_meta(d, m)
    log(d, '条目', f'记一条 {nid}：{text[:100]}（{by}）')
    return f'已记 {nid}'


def task_item_delete(name, key, by='用户（网页）'):
    d = period_dir(name)
    m = load_meta(d)
    xs = m.get('条目') or []
    if not any(x['编号'] == key for x in xs):
        raise KBError('只能删手记的条目；ANR、Bug 在它们自己的页面取消关联')
    m['条目'] = [x for x in xs if x['编号'] != key]
    (m.get('条目状态') or {}).pop(key, None)
    save_meta(d, m)
    log(d, '条目', f'删除 {key}（{by}）')
    return f'已删除 {key}'


def task_item_set(name, key, status='', conclusion='', by='Claude'):
    """记一条的进展：AI 处理完用（kb_task_item），你也可以手动标已解决 / 重新打开。"""
    d = period_dir(name)
    items = {x['键']: x for x in task_items(d.name)}
    key = (key or '').strip()
    if key not in items:
        alt = [k for k in items if k.split(':')[-1] == key]
        if len(alt) != 1:
            raise KBError(f'事项「{d.name}」里没有条目 {key}；有：{"、".join(items)}')
        key = alt[0]
    if status and status not in ITEM_STATES:
        raise KBError(f'状态只能是：{"、".join(ITEM_STATES)}')
    m = load_meta(d)
    x = m.setdefault('条目状态', {}).setdefault(key, {})
    if status:
        x['状态'] = status
    if conclusion:
        x.update(结论=conclusion.strip(), 结论时间=now(), 结论人=by)
    save_meta(d, m)
    log(d, '条目', f'{key}「{items[key]["标题"][:40]}」→ {status or "补充结论"}' + (f'：{conclusion.strip()[:200]}' if conclusion else '') + f'（{by}）')
    return f'已记下 {key}：{status or ""} {conclusion[:80] if conclusion else ""}'.strip()


def _item_prompt(d, m, x, note, fresh):
    """推动一条：不走开发流程（SDD 等），只给这一条和补充信息，怎么查、怎么改由 AI 自己判断。"""
    how = {'ANR': f'用 kb_anr（id={x.get("编号")}）看合并后的关键堆栈和样本原文', '崩溃': f'用 kb_anr（id={x.get("编号")}）看堆栈和样本原文',
           'Bug': f'用 kb_bug_get（{x.get("编号")}）实时拉取正文和截图'}.get(x['类型'], '')
    sup = [f'- 工程：{m["开发仓库"]}'] if m.get('开发仓库') else []
    sup += [f'- {"分支" if n.get("类型") == "分支" else "补充"}：{note_title(n) if n.get("类型") == "分支" else (n.get("内容") or note_title(n))}'
            for n in notes_of(d, m=m)]
    head = (f'你是由知识库网页启动的【后台无人值守】会话，处理事项「{d.name}」里的一条。终端里没有人，'
            '不要在回复里提问，也不要用 AskUserQuestion；要问用户就用 kb_ask（iteration 填事项名），再用 kb_wait_answer 等回答。\n\n') if fresh else ''
    return (head + f'这一条（{x["键"]}）：{x["标题"]}\n{x["内容"] if x["内容"] != x["标题"] else ""}'
            + (f'\n{how}。' if how else '')
            + (f'\n用户补充：{note}' if note else '')
            + ('\n\n事项的补充信息：\n' + '\n'.join(sup) if sup else '')
            + '\n\n不走开发流程（不用 SDD、不用 kb_dev_package / kb_dev_prepare），怎么查、怎么改你自己判断：'
              '仓库不在补充里的分支上时，自己看有没有未提交的改动、能不能安全切换（不能就 kb_ask）；'
              '要改代码先用 kb_ask 说清根因和改法、等确认（kb_ask 提示免打扰就按你的建议做）；改完自测，按仓库惯例提交，不 push。'
            + f'\n最后用 kb_task_item（iteration=「{d.name}」，item={x["键"]}）记下这一条的结论（状态：已解决 / 没解决 / 待确认；结论一两句：根因、改了什么、提交号）。'
              '这一组里别的条目不用管，和这一条同一个根因的在结论里写明。不要改事项的状态。')


def task_item_push(name, key, note='', by='用户（网页）'):
    """点某一条的「推动」= 你本人批准处理这一条。不走开发流程，交给 AI 自行判断。"""
    d = period_dir(name)
    items = {x['键']: x for x in task_items(d.name)}
    if key not in items:
        raise KBError(f'没有条目 {key}')
    x = items[key]
    note = (note or '').strip()
    s = dev_session(d.name) or {}
    m = load_meta(d)
    root = m.get('开发仓库') or s.get('仓库') or ''
    if s.get('状态') != '运行中' and not (root and Path(root).is_dir()):
        raise KBError('先在「补充」里选好工程（代码仓库）')
    st = m.setdefault('条目状态', {}).setdefault(key, {})
    st.update(状态='推动中', 推动时间=now())
    save_meta(d, m)
    log(d, '推动', f'{key}「{x["标题"][:60]}」' + (f'：{note}' if note else '') + f'（{by}）')
    if s.get('状态') == '运行中':
        dev_chat(d.name, _item_prompt(d, m, x, note, False) + '\n（先把手头的事做完再处理这一条）')
        m = load_meta(d)
        if m.get('对话'):
            m['对话'][-1]['显示'] = f'推动 {x["键"]}：{x["标题"][:60]}' + (f'（{note}）' if note else '')
            save_meta(d, m)
        return f'AI 正在处理别的，已把「{x["标题"][:30]}」交给它，排在当前工作后面'
    if m.get('状态') != '开发中':
        set_status(d.name, '开发中', f'网页推动条目 {key}（本人批准）', by_human=True)
    branch = next((note_title(n) for n in notes_of(d, m=m) if n.get('类型') == '分支'), '') or s.get('分支', '')
    sid = _session_id(s['日志']) if s.get('日志') and s.get('仓库') == root else ''
    _dev_spawn(d, Path(root), branch, _item_prompt(d, m, x, note, not sid) + _NO_BG, sid, 续跑次数=0, 类型='跟进', 仅对话=True)
    return f'已{"接着上次的会话" if sid else "启动 AI"}推动「{x["标题"][:30]}」，进展看下面的动作'


# ---------------------------------------------------------------- 侧栏：批次挂在来源下面，可移除 / 加回
# 有关联的 ANR / 崩溃问题 → 挂在「💥 ANR / 崩溃」下（叫「批次」）；只有 Bug → 挂在「🐞 Bug」下；都没有 → 其他事项。
# 期信息「侧栏」：{状态: 显示 / 隐藏, 时间, 条目数}。没设过：没完成就显示。移除后，条目变多或关联的问题完成后又出现，会自动回来。
DONE_STATES = ('已解决', '没解决')


def task_batches():
    """每个事项的来源、进度、在不在侧栏（总览一次算完，不逐个调 task_items）。"""
    anr, back = {}, set()
    try:
        for p in anr_problems(True):
            if p.get('事项'):
                anr.setdefault(p['事项'], []).append('anr:' + p['编号'])
                if p.get('修复后又出现'):
                    back.add(p['事项'])
    except (KBError, OSError):
        pass
    bug = {}
    try:
        for e in zt_load()['Bug'].values():
            o = e.get('归属') or {}
            if o.get('类型') == '事项':
                bug.setdefault(o.get('名称'), []).append('bug:' + e['编号'])
    except (KBError, OSError):
        pass
    out = {}
    for n in period_names():
        m = load_meta(PERIODS / n)
        if not is_task(m):
            continue
        keys = [x['编号'] for x in m.get('条目') or []] + anr.get(n, []) + bug.get(n, [])
        st = m.get('条目状态') or {}
        done = sum(1 for k in keys if (st.get(k) or {}).get('状态') in DONE_STATES)
        nav = m.get('侧栏') or {}
        if nav.get('状态') == '显示':
            show = True
        elif nav.get('状态') == '隐藏':
            show = len(keys) > nav.get('条目数', 0) or n in back
        else:
            show = m.get('状态') != '已完成'
        out[n] = {'来源': 'anr' if n in anr else 'bug' if n in bug else '', '已处理': done, '总数': len(keys),
                  '待确认': sum(1 for k in keys if (st.get(k) or {}).get('状态') == '待确认'),
                  '侧栏': show, '移除过': nav.get('状态') == '隐藏'}
    return out


def task_nav(name, show, by='用户（网页）'):
    """期和事项都能从侧栏移除 / 加回（期没设过就显示）。"""
    d = period_dir(name)
    m = load_meta(d)
    n = len(task_items(d.name))
    m['侧栏'] = {'状态': '显示' if show else '隐藏', '时间': now(), '条目数': n}
    save_meta(d, m)
    log(d, '侧栏', ('加回侧栏' if show else '从侧栏移除' + ('（有新条目或问题又出现会自动回来）' if is_task(m) else '（在总览里可以加回）')) + f'（{by}）')
    return f'已{"加回侧栏" if show else "从侧栏移除"}「{d.name}」'
