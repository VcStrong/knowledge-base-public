"""智能状态：一份数据，五种呈现。网页的各套界面模板（_system/ui-templates.js）都只读这一份，按自己的方式摆放。

五种通用素材（以后加功能，只要产出其中一种，所有模板自动就有）：
  判断  需要你拍板的一件事：问题、AI 的建议、理由、把握、备选；确认走 brief_act，模板里没有业务逻辑
  活动  哪个 AI 正在做什么、最近几步（来自各后台会话的日志）
  关系  当前这一期的需求、设计、接口、各端、Bug 之间的连线和状态
  指标  数值和趋势
  叙述  AI 写给你的一段话，带引用
另有「进行中」（各期走到哪一步）、「其他」（模板不认识的东西按通用卡片显示）。
"""
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from kblib.core.common import KBError, PERIODS, now
from kblib.core.periods import is_task, load_meta, period_names
from kblib.core.notes import notes_of
from kblib.core.notes import _materials
from kblib.ai.devsession import _alive, dev_session
from kblib.ai.devices import dev_activity
from kblib.stack.plan import _sdir, period_ends
from kblib.stack.guide import period_guide
from kblib.bugs.index import zt_load
from kblib.bugs import analysis as _an
from kblib.steward import patrol as _st
from kblib.steward import chat as _chat

ROLE_COLOR = {'方案': '#8b5cf6', '服务端': '#0ea5e9', 'Web': '#06b6d4', 'Android': '#16a34a', 'iOS': '#64748b', '鸿蒙': '#e11d48',
              '审查': '#f59e0b', 'Bug 分析': '#ef4444', 'Bug 修复': '#dc2626', '开发': '#2f6fed', '整理': '#14b8a6', '管家': '#7c3aed'}


def _steps(logf, n=5):
    out = []
    for a in dev_activity(logf, 40)[-n * 3:]:
        if a.get('类型') == '工具':
            out.append(f'{a.get("工具", "")} {(a.get("内容") or "")[:70]}'.strip())
        elif a.get('类型') in ('说明', '结束', '输出'):
            t = (a.get('内容') or '').strip().splitlines()
            if t:
                out.append(t[0][:90])
    return out[-n:]


def _activities():
    """正在跑的 AI：期的开发会话、出方案、各端开发和审查、来源整理、Bug 分析和修复、问管家。"""
    out = []
    add = lambda role, obj, st, logf, link, ask=False, since='': out.append(
        {'id': f'{role}:{obj}', '角色': role, '颜色': ROLE_COLOR.get(role, '#64748b'), '对象': obj, '状态': st,
         '步骤': _steps(logf) if logf else [], '链接': link, '等你': ask, '开始': since})
    for n in period_names():
        try:
            m = load_meta(PERIODS / n)
        except Exception:
            continue
        link = '#/p/' + n
        q = any(x.get('状态') == '待回答' for x in m.get('待确认') or [])
        s = dev_session(n) or {}
        if s.get('状态') == '运行中' and _alive(s.get('pid', 0)):
            add('开发', n, '等你回答' if q else ('跟进' if s.get('类型') == '跟进' else '开发中'), s.get('日志'), link, q, s.get('开始时间', ''))
        ps = m.get('全栈会话') or {}
        if ps.get('状态') == '运行中' and _alive(ps.get('pid', 0)):
            add('方案', n, '出方案中', ps.get('日志'), link, False, ps.get('开始时间', ''))
        for end, x in (m.get('各端开发') or {}).items():
            stt = x.get('状态', '')
            if stt == '开发中' and _alive(x.get('pid', 0)):
                add(end, n, f'开发中 · 第 {x.get("轮次", 0) + 1} 轮', x.get('日志'), link, False, x.get('开始时间', ''))
            elif stt == '审查中' and _alive(x.get('pid', 0)):
                add('审查', f'{n} · {end}', '审查中', x.get('审查日志'), link, False, x.get('审查开始', ''))
            elif stt == '要你看':
                add(end, n, '要你看', x.get('日志'), link, True, x.get('结束时间', ''))
        u = m.get('更新会话') or {}
        if u.get('状态') == '运行中' and _alive(u.get('pid', 0)):
            add('整理', n, '按新原文整理资料', u.get('日志'), link, False, u.get('开始时间', ''))
    for x in _an.an_sessions():
        if x.get('状态') == '运行中':
            role = 'Bug 修复' if x.get('类型') == '修复' else 'Bug 分析'
            add(role, '、'.join(x.get('Bug', [])[:4]), '修复中' if role == 'Bug 修复' else '只读分析中', x.get('日志'), '#/bugs', False, x.get('开始时间', ''))
    for x in _chat._load()[-5:]:
        if x.get('状态') == '思考中':
            out.append({'id': 'chat:' + x['编号'], '角色': '管家', '颜色': ROLE_COLOR['管家'], '对象': x['问'][:40], '状态': '处理你交来的东西',
                        '步骤': [], '链接': '', '等你': False, '开始': x.get('时间', '')})
    return out


def _judgments(view):
    out = []
    for c in view['卡片']:
        j = {'id': c['id'], '类型': c['类型'], '问题': c['标题'], '说明': c.get('说明', ''), '理由': c.get('为什么', ''), '链接': c.get('链接', ''),
             '把握': None, '建议': '', '主动作': 'go', '备选': [{'标签': '不用了', '动作': 'dismiss'}]}
        if c.get('提议'):
            p = c['提议']
            j.update(主动作='confirm', 建议=f'在 {Path(p["默认仓库"]).name if p.get("默认仓库") else "（选一个工程）"}' + (f' 的 {p["默认分支"]}' if p.get('默认分支') else '') + ' 上处理',
                     提议=p, 把握=80 if p.get('默认仓库') else 40)
        elif c.get('选项'):
            j.update(主动作='choose', 选项=c['选项'], 建议=c['选项'][0]['标签'] if c['选项'] else '', 把握=50)
        elif c.get('动作') in ('run', 'ignore', 'upgrade'):
            j.update(主动作='do', 建议=c.get('按钮') or '现在就做')
        else:
            j.update(建议=c.get('按钮') or '去看看')
        out.append(j)
    have = {c['提议'].get('事项') for c in view['卡片'] if c.get('提议')}
    for x in _chat._load()[-10:]:                      # 问管家里还没确认的推动 / 分析（管家卡片里已有同一事项的就不重复）
        p = x.get('提议')
        if p and not p.get('已确认') and not (p.get('事项') and p['事项'] in have):
            tgt = p.get('事项') or '、'.join(p.get('Bug', []))
            out.insert(0, {'id': 'chat:' + x['编号'], '类型': '问你', '问题': f'「{tgt}」确认工程就开始' + ('处理' if p.get('类型') != 'Bug分析' else '只读分析'),
                           '说明': x['问'][:60], '理由': p.get('说明', ''), '链接': '#/p/' + p['事项'] if p.get('事项') else '#/bugs', '把握': 80 if p.get('默认仓库') else 40,
                           '建议': f'在 {Path(p["默认仓库"]).name}' + (f' 的 {p["默认分支"]}' if p.get('默认分支') else '') + ' 上处理' if p.get('默认仓库') else '选一个工程',
                           '主动作': 'confirm', '提议': p, '备选': []})
    return out


def _focus():
    """当前这一期：没完成、最近有动静的期（不是事项）。"""
    best = None
    for n in period_names():
        try:
            m = load_meta(PERIODS / n)
        except Exception:
            continue
        if is_task(m) or m.get('状态') in ('已完成', '已暂停'):
            continue
        t = m.get('更新时间') or m.get('创建时间') or ''
        if not best or t > best[1]:
            best = (n, t, m)
    return best


def _graph(name, m):
    d = PERIODS / name
    mats = _materials(d)
    cnt = lambda c: len(mats.get(c) or []) + len(notes_of(d, c, m))
    fs = (m.get('全栈') or {}).get('状态', '')
    nodes = [{'id': 'req', '类': '需求', '名称': '需求', '说明': f'{cnt("需求")} 份', '状态': 'miss' if not cnt('需求') else 'hot' if not fs else ''},
             {'id': 'des', '类': '设计', '名称': '设计稿', '说明': f'{cnt("设计图")} 份' if cnt('设计图') else '还没有', '状态': '' if cnt('设计图') else 'miss'},
             {'id': 'api', '类': '接口', '名称': '接口文档', '说明': f'{cnt("接口文档")} 份' if cnt('接口文档') else '还没有', '状态': '' if cnt('接口文档') else 'miss'}]
    plan = (_sdir(d) / '方案.json').exists()
    nodes.append({'id': 'ct', '类': '契约', '名称': '方案 · 接口契约', '说明': fs or ('已出' if plan else '未出'), '状态': 'core' if plan else 'dim'})
    edges = [['req', 'des'], ['req', 'api'], ['req', 'ct'], ['des', 'ct'], ['api', 'ct']]
    dev = m.get('各端开发') or {}
    for end, v in period_ends(d, m).items():
        x = dev.get(end) or {}
        s = x.get('状态', '')
        nodes.append({'id': 'e:' + end, '类': '端', '名称': end, '说明': s or (v.get('分支') or Path(v.get('仓库', '')).name),
                      '状态': 'hot' if s in ('开发中', '审查中', '排队中', '打回修改') else 'bad' if s in ('要你看', '失败') else 'ok' if s == '审查通过' else ''})
        edges.append(['ct', 'e:' + end])
    if fs in ('各端完成', '已验收'):
        nodes.append({'id': 'ev', '类': '证据', '名称': '证据包', '说明': '已验收' if fs == '已验收' else '等你验收', '状态': 'hot' if fs == '各端完成' else 'ok'})
        edges += [[n['id'], 'ev'] for n in nodes if n['类'] == '端']
    try:
        bugs = [e for e in zt_load()['Bug'].values() if (e.get('归属') or {}).get('名称') == name and e.get('状态') == '激活' and not e.get('忽略')]
    except Exception:
        bugs = []
    for e in bugs[:3]:
        nodes.append({'id': 'b:' + e['编号'], '类': '问题', '名称': f'Bug {e["编号"]}', '说明': e.get('标题', '')[:14], '状态': 'bad'})
        ends = [n['id'] for n in nodes if n['类'] == '端']
        edges.append([ends[0] if ends else 'ct', 'b:' + e['编号']])
    g = period_guide(name) or {}
    nx = g.get('下一步') or {}
    return {'标题': name, '链接': '#/p/' + name, '节点': nodes, '边': edges, '洞察': {'标题': nx.get('文字', ''), '内容': nx.get('说明', '')},
            '步骤': g.get('步骤') or []}


def _series(days=7):
    """管家这几天每天自动做了多少（真实记录）。"""
    cnt = {}
    for r in _st.steward_log(2000):
        if r.get('方式') in ('自动', '手动', '回答') and r.get('结果') not in ('失败',):
            cnt[r['时间'][:10]] = cnt.get(r['时间'][:10], 0) + int(r.get('数量') or 1)
    today = datetime.now()
    return [cnt.get((today - timedelta(days=i)).strftime('%Y-%m-%d'), 0) for i in range(days - 1, -1, -1)]


def _metrics(acts, judg):
    out = []
    try:
        from kblib.plugins.stats import work_stats
        r = work_stats('本周', by='网页') or {}
        for c in (r.get('卡片') or [])[:3]:
            out.append({'名称': c['标题'], '值': f'{c["值"]}', '单位': c.get('单位', ''), '说明': c.get('说明', ''), '链接': c.get('链接', '')})
    except Exception:
        pass
    s = _series()
    out.insert(0, {'名称': '管家近 7 天替你做的事', '值': str(sum(s)), '单位': '件', '趋势': s, '说明': f'今天 {s[-1]} 件'})
    out.insert(1, {'名称': '在工作的 AI', '值': str(len([a for a in acts if not a['等你']])), '单位': '个', '说明': '、'.join(sorted({a['角色'] for a in acts})[:4]) or '都在休息'})
    return out


def _progress():
    out = []
    for n in period_names():
        try:
            m = load_meta(PERIODS / n)
        except Exception:
            continue
        if is_task(m) or m.get('状态') in ('已完成',):
            continue
        g = period_guide(n) or {}
        st = g.get('步骤') or []
        done = sum(1 for x in st if x['状态'] == 'done')
        cur = next((x['名称'] for x in st if x['状态'] == 'cur'), '')
        out.append({'名称': n, '阶段': cur, '进度': round(100 * done / len(st)) if st else 0, '链接': '#/p/' + n,
                    '下一步': (g.get('下一步') or {}).get('文字', ''), '谁': (g.get('下一步') or {}).get('谁', '')})
    return out[:8]


def brief():
    view = _st.steward_view()
    acts = _activities()
    judg = _judgments(view)
    f = _focus()
    graph = _graph(f[0], f[2]) if f else None
    prog = _progress()
    asks = [j for j in judg if j['类型'] in ('问你', '待你')]
    working = [a for a in acts if not a['等你']]
    problems = [j for j in judg if j['id'].startswith(('push:', 'anr', 'bug-', 'ask:bug'))]
    state = '等你判断' if asks else '发现问题' if problems else '工作中' if working else '安静'
    today = view.get('今日已做', 0)
    if asks:
        title = f'{asks[0]["问题"]}' if len(asks) == 1 else f'有 {len(asks)} 件事想听你的判断'
    elif working:
        title = f'{len(working)} 个 AI 正在推进，暂时不需要你'
    else:
        title = '一切安静，没有需要你的事'
    cites, body = [], []

    def say(text, cite=None):
        if cite:
            cites.append(cite)
        body.append(text.rstrip('。；，') + (f'[{len(cites)}]' if cite else '') + '。')
    if graph:
        say(f'「{graph["标题"]}」' + (f'下一步是{graph["洞察"]["标题"]}' if graph['洞察']['标题'] else '在进行中')
            + (f'：{graph["洞察"]["内容"].rstrip("。")}' if graph['洞察']['内容'] else ''), {'文字': f'期「{graph["标题"]}」', '链接': graph['链接']})
    if working:
        say('正在工作的有 ' + '；'.join(f'{a["角色"]}（{a["对象"][:16]}，{a["状态"]}）' for a in working[:4]))
    if view.get('日报'):
        say(view['日报']['内容'], {'文字': '管家日报', '链接': ''})
    if problems:
        say(f'问题这边有 {len(problems)} 件要看：' + '；'.join(p['问题'] for p in problems[:3]), {'文字': 'Bug / ANR', '链接': '#/bugs'})
    if not body:
        body.append('没有进行中的期，也没有新问题。把需求、日志或文件交给我，我会接着推。')
    return {'时间': now(), '状态': {'名称': state, '在工作': len(working), '今天完成': today, '等你': len(asks)},
            '问候': title, '判断': judg, '活动': acts, '关系': graph, '指标': _metrics(acts, judg),
            '叙述': {'标题': title, '正文': ''.join(body), '引用': cites}, '进行中': prog, '其他': [],
            '管家': {'设置': view['设置'], '上次': view.get('上次', ''), '规矩': view.get('规矩') or []}}


def brief_act(jid, action='', value='', repo='', branch='', by='用户（网页）'):
    """模板上点的按钮都走这里：confirm（推动 / 分析）、do（现在就做 / 忽略 / 放权）、choose（选一个）、dismiss（不用了）。"""
    if not jid:
        raise KBError('缺判断编号')
    if jid.startswith('chat:'):
        return _chat.chat_confirm(jid[5:], repo, branch, by=by)
    if action == 'dismiss':
        return _st.steward_dismiss(jid)
    return _st.steward_answer(jid, value, by=by, repo=repo, branch=branch)


CLASSIC = {'名称': '经典', '说明': '左边目录、右边内容：分组导航 + 卡片，信息最全', '目录': 'classic', '顺序': 0}


def ui_templates():
    """界面模板清单：经典 + _system/ui/ 下每个有 index.html 和 template.json（名称、说明、顺序）的目录。
    加一套模板 = 加一个目录，不用改代码。"""
    import json
    ui = Path(__file__).resolve().parents[2] / 'ui'          # 程序目录里的 ui/（KB_ROOT 指向别处的数据目录时也对）
    out = [CLASSIC]
    for d in sorted(ui.iterdir()) if ui.is_dir() else []:
        f = d / 'template.json'
        if d.is_dir() and (d / 'index.html').is_file() and f.is_file():
            try:
                m = json.loads(f.read_text('utf-8'))
            except ValueError:
                continue
            if m.get('名称'):
                out.append({'名称': m['名称'], '说明': m.get('说明', ''), '目录': d.name, '顺序': m.get('顺序', 99)})
    return sorted(out, key=lambda x: (x['顺序'], x['名称']))


def ui_dir(name_or_dir):
    """模板名或目录名 → 模板（找不到为 None）。"""
    return next((x for x in ui_templates() if name_or_dir in (x['名称'], x['目录'])), None)


def ui_template():
    from kblib.core.common import load_settings
    t = load_settings().get('界面模板') or '经典'
    return t if ui_dir(t) else '经典'


def set_ui_template(name):
    from kblib.core.common import load_settings, save_settings
    if not ui_dir(name):
        raise KBError('没有这套模板：' + name)
    s = load_settings()
    s['界面模板'] = name
    save_settings(s)
    return f'界面换成「{name}」，回总览就能看到'
