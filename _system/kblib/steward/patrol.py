"""管家：把知识库当成会主动干活的员工。明确的事自己做，要你批准的事备好等你点，不明确的事只问一个问题。

每一轮（web.py 每 5 分钟；终端 kb steward tick）：
  1. 看：从现有数据收集每件事现在在哪一步（Bug、来源、全栈、待确认、停滞的期、ANR），这一步不调模型。
  2. 判：每件事只给当前状态下能做的动作，一次一个决定、不写长计划（借鉴 browser-use/jev-ultrafast）；
     每个决定带置信度、候选和去向（自动 / 交给人），格式借鉴 laya（calibrated typed decisions）。
  3. 分流（自主矩阵）：
       明确、只读或能重做    → 自动做，写进记录和日报（Bug 只读分析、需求资料重新整理）
       你点了就等于批准的    → 只出「待你处理」卡片（拍板、开工、验收、推动、修复、svn 提交），管家从不代点
       不明确                → 只问一个问题，选项按可能性排好（如 Bug 不知道在哪个仓库分析）
  4. 做：执行前再查一次状态（已经有人处理就不做），先记下决定再执行（不会重复做）；有总开关和每日上限。
  5. 记：每个决定写进 _system/管家/记录.jsonl（日报、统计用，将来也是训练决策模型的数据）。
设置在 设置.json「管家」：开启、自主度（保守 / 标准 / 放手）、每日上限、关闭的动作。
"""
import json
import threading
import time
from datetime import datetime, timedelta

from kblib.core.common import KBError, PERIODS, SYS, load_settings, now, save_settings
from kblib.core.periods import is_task, load_meta, period_names
from kblib.ai.devsession import _alive, _notify
from kblib.bugs.index import zt_load
from kblib.bugs import analysis as _an
from kblib.sources import refresh as _refresh
from kblib.anr.store import anr_problems
from kblib.stack.guide import period_guide
from kblib.stack.plan import stack_plan_start

DIR = SYS / '管家'
LOG = DIR / '记录.jsonl'
STATE = DIR / '状态.json'
LEVELS = ('保守', '标准', '放手')
STALL_DAYS = 3
STALE_DAYS = 30               # 平台上这么久没动、也没分析过的 Bug：建议你忽略
PER_TICK = 3                   # 每一轮最多自动分析几个 Bug（防止第一次开启时一下子起很多会话）
ACTIONS = {                    # 管家能自己做的动作：都是只读或可以重做的
    'Bug分析': ('Bug 只读分析', '最近几天新建的 Bug、被你打回的，自动在它的仓库里只读分析（不改代码），结论等你审核；陈旧的老 Bug 不分析'),
    '来源整理': ('需求资料重新整理', '需求原文有变化时，后台按新原文重新整理条目，标出改了什么'),
    '出方案': ('资料齐了就出方案', '最近有动静的期：需求放进来了、端的仓库也选好了，自动让 AI 出方案（只读，不改代码），出好了等你拍板'),
    'ANR建事项': ('新 ANR / 崩溃建事项', '最近几天新出现、还没归属的 ANR / 崩溃问题，自动建事项（同一批归一个），然后只问你在哪个工程、哪个分支推动'),
}
_LOCK = threading.Lock()


def steward_settings():
    s = load_settings().get('管家') or {}
    return {'开启': s.get('开启', True), '自主度': s.get('自主度') if s.get('自主度') in LEVELS else '标准',
            '每日上限': int(s.get('每日上限') or 20), '新Bug天数': int(s.get('新Bug天数') or 3), '关闭动作': [a for a in s.get('关闭动作') or [] if a in ACTIONS]}


def steward_set(on=None, level=None, limit=None, actions=None, new_days=None):
    s = load_settings()
    cur = steward_settings()
    if on is not None:
        cur['开启'] = bool(on)
    if level:
        if level not in LEVELS:
            raise KBError(f'自主度只能是：{"、".join(LEVELS)}')
        cur['自主度'] = level
    if limit not in (None, ''):
        n = int(limit)
        if not 0 <= n <= 200:
            raise KBError('每日上限在 0 到 200 之间')
        cur['每日上限'] = n
    if new_days not in (None, ''):
        n = int(new_days)
        if not 1 <= n <= 60:
            raise KBError('新 Bug 天数在 1 到 60 之间')
        cur['新Bug天数'] = n
    if isinstance(actions, dict):
        off = set(cur['关闭动作'])
        for k, v in actions.items():
            if k in ACTIONS:
                (off.discard if v else off.add)(k)
        cur['关闭动作'] = sorted(off)
    s['管家'] = cur
    save_settings(s)
    return '管家' + ('已关闭' if not cur['开启'] else f'已开启（{cur["自主度"]}，每天最多自动做 {cur["每日上限"]} 件）')


def _state():
    try:
        return json.loads(STATE.read_text('utf-8'))
    except (OSError, ValueError):
        return {}


def _save_state(st):
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), 'utf-8')
    tmp.replace(STATE)


def _record(**kv):
    DIR.mkdir(parents=True, exist_ok=True)
    kv = {'时间': now(), **kv}
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(kv, ensure_ascii=False) + '\n')
    return kv


def steward_log(n=50, day=''):
    try:
        lines = LOG.read_text('utf-8').splitlines()
    except OSError:
        return []
    out = []
    for x in reversed(lines):
        try:
            r = json.loads(x)
        except ValueError:
            continue
        if day and not r.get('时间', '').startswith(day):
            if r.get('时间', '') < day:
                break
            continue
        out.append(r)
        if len(out) >= n:
            break
    return out


def _used_today():
    return sum(int(r.get('数量') or 1) for r in steward_log(500, now()[:10]) if r.get('方式') == '自动' and r.get('结果') != '失败')


# ---------------------------------------------------------------- 1. 看：每件事现在在哪一步

def _since(days):
    return (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M')


def _bug_need(e, new_days=None):
    """这个 Bug 需不需要（重新）分析，为什么。只管新 Bug 和你打回的：陈旧的老 Bug 分析了也是浪费。"""
    if e.get('状态') != '激活' or e.get('忽略'):
        return ''
    if (e.get('修复') or {}).get('状态') in ('排队中', '修复中', '已修复'):
        return ''
    a = e.get('分析') or {}
    if a.get('状态') == '需重分析':
        return '你打回了分析，按你的意见重新分析'
    cut = _since(new_days or steward_settings()['新Bug天数'])
    if not a:
        return '新 Bug，还没分析' if (e.get('创建时间') or '') >= cut else ''
    if a.get('过时') and a.get('状态') == '待审核' and (e.get('修改时间') or '') >= cut:
        return '分析之后平台上又改过，结论可能过时'
    return ''


def _bug_key(e):
    a = e.get('分析') or {}
    return f'Bug分析:{e["编号"]}:{e.get("修改时间", "")}:{a.get("状态", "")}:{a.get("时间", "")}'


def _sev(e):
    try:
        return int(e.get('严重') or 9)
    except ValueError:
        return 9


def _observe():
    """返回 (自动候选, 卡片)。自动候选：[(动作, 键, 对象, 依据, 附加)]；卡片见 steward_view。"""
    autos, cards = [], []
    try:
        data = zt_load()
        bugs = data.get('Bug') or {}
    except Exception:
        bugs = {}
    running = [x for x in _an.an_sessions() if x.get('状态') == '运行中']
    busy = {b for x in running for b in x.get('Bug', [])}
    no_repo, review, svn, stale = [], [], [], []
    nd, scut = steward_settings()['新Bug天数'], _since(STALE_DAYS)
    for e in sorted(bugs.values(), key=lambda e: (_sev(e), e.get('创建时间', '')), reverse=False):
        if e.get('忽略'):
            continue
        a = e.get('分析') or {}
        if e.get('状态') == '激活' and not a and not e.get('修复') and (e.get('修改时间') or '9') < scut:
            stale.append(e)
        if a.get('状态') == '待审核' and e.get('状态') == '激活':
            review.append(e['编号'])
        if (e.get('修复') or {}).get('待提交'):
            svn.append(e['编号'])
        why = _bug_need(e, nd)
        if not why or e['编号'] in busy:
            continue
        root, _, how = _an._bug_repo(e)
        if root:
            autos.append(('Bug分析', _bug_key(e), e['编号'], f'{why}；仓库：{how}', {'严重': e.get('严重', ''), '标题': e.get('标题', '')}))
        else:
            no_repo.append(e)
    if no_repo:
        from kblib.core.repos import load_repos
        cands = sorted({str(v) for v in (load_settings().get('Bug仓库') or {}).values()} | {v['路径'] for v in load_repos().values()})
        ids = [e['编号'] for e in no_repo]
        cards.append({'id': 'ask:bug-repo:' + ','.join(ids[:20]), '类型': '问你', '标题': f'{len(ids)} 个 Bug 不知道在哪个仓库分析',
                      '说明': '、'.join(f'{e["编号"]} {e.get("标题", "")[:24]}' for e in no_repo[:5]) + ('…' if len(no_repo) > 5 else ''),
                      '为什么': '它们没归到有开发仓库的期，产品也没用过固定仓库。选一个，我在那里只读分析，以后同产品的 Bug 自动用它。',
                      '选项': [{'值': c, '标签': c} for c in cands], '动作': 'bug-repo', '对象': ids, '链接': '#/bugs'})
    if stale:
        ids = [e['编号'] for e in stale]
        cards.append({'id': 'bug-stale:' + ','.join(ids[:40]), '类型': '建议', '标题': f'{len(ids)} 个 Bug 超过 {STALE_DAYS} 天没动、也没分析过',
                      '说明': '、'.join(f'{e["编号"]} {e.get("标题", "")[:20]}' for e in stale[:4]) + ('…' if len(stale) > 4 else ''),
                      '为什么': '陈旧的老 Bug 我不会去分析（省 token）。不打算处理就忽略：只在知识库标记，不改 Bug 平台，不再算「没解决」，随时能在 Bug 页取消。',
                      '按钮': f'全部忽略（{len(ids)}）', '动作': 'ignore', '对象': ids, '链接': '#/bugs'})
    if review:
        cards.append({'id': 'bug-review:' + ','.join(review[:30]), '类型': '待你', '标题': f'{len(review)} 个 Bug 分析等你审核',
                      '说明': '、'.join(review[:8]) + ('…' if len(review) > 8 else ''), '为什么': '审核通过才能修复；不对就打回写意见，我会重新分析。',
                      '按钮': '去审核', '链接': '#/bugs'})
    if svn:
        cards.append({'id': 'bug-svn:' + ','.join(svn), '类型': '待你', '标题': f'{len(svn)} 个 Bug 修好了，等你提交到 svn',
                      '说明': '、'.join(svn[:8]), '为什么': 'svn 一提交就进服务器，只能你点；没提交前同一工作副本的其他修复会排队。', '按钮': '去提交', '链接': '#/bugs'})

    for n in period_names():
        d = PERIODS / n
        try:
            m = load_meta(d)
        except Exception:
            continue
        st = m.get('状态', '')
        link = '#/p/' + n
        pend = [s for s in m.get('来源') or [] if s.get('待更新')]
        if pend and st in _refresh.REFRESH_STATUSES:
            u = m.get('更新会话') or {}
            if not (u.get('状态') == '运行中' and _alive(u.get('pid', 0))):
                sids = sorted(s['编号'] for s in pend)
                autos.append(('来源整理', f'来源整理:{n}:{",".join(sids)}', n,
                              f'{len(sids)} 条需求原文有变化', {}))
        q = [x for x in m.get('待确认') or [] if x.get('状态') == '待回答']
        if q:
            cards.append({'id': f'ask:{n}:{len(q)}:{q[-1].get("时间", "")}', '类型': '待你', '标题': f'「{n}」有 {len(q)} 个问题等你回答',
                          '说明': (q[0].get('问题') or '')[:80], '为什么': 'AI 在等你决定，不回答它会停在这里；不想被打扰可以开「🌙 免打扰」。',
                          '按钮': '去回答', '链接': link})
        fs = (m.get('全栈') or {}).get('状态')
        if not is_task(m) and st in ('收集中', '已批准开发', '开发中') and (m.get('更新时间') or '') >= _since(14):
            try:
                g = period_guide(n)
            except Exception:
                g = None
            nx = (g or {}).get('下一步') or {}
            if nx.get('文字') == '让 AI 出方案' and (m.get('全栈') or {}).get('状态') == '出方案失败':
                cards.append({'id': f'planfail:{n}:{(m.get("全栈") or {}).get("方案时间", "")}', '类型': '待你', '标题': f'「{n}」上次方案没出来',
                              '说明': '看「全栈」里的记录，补资料或改意见后再点「🧭 出方案」', '为什么': '失败过的我不自动重试，免得白花 token。',
                              '按钮': '去看看', '链接': link})
            elif nx.get('文字') == '让 AI 出方案' and not any(r.get('动作') == '出方案' and r.get('对象') == n for r in steward_log(200, now()[:10])):
                autos.append(('出方案', f'出方案:{n}:{m.get("更新时间", "")}', n, '需求和各端仓库都有了', {}))
            elif nx.get('文字') in ('给涉及的端选代码仓库', '方案已拍板，点开工'):
                cards.append({'id': f'guide:{n}:{nx["文字"]}', '类型': '待你', '标题': f'「{n}」：{nx["文字"]}', '说明': nx.get('说明', ''),
                              '为什么': '这一步要你定，定了我接着往下推。', '按钮': nx.get('按钮') or '去处理', '链接': link})
        if fs == '待拍板':
            cards.append({'id': f'approve:{n}:{(m.get("全栈") or {}).get("方案时间", "")}', '类型': '待你', '标题': f'「{n}」的方案出好了，等你拍板',
                          '说明': '需求规格、设计对照、各端改动和接口契约', '为什么': '拍板后才能开工；不对就写意见重出。', '按钮': '去拍板', '链接': link})
        elif fs == '各端完成':
            cards.append({'id': f'accept:{n}:{(m.get("全栈") or {}).get("完成时间", "")}', '类型': '待你', '标题': f'「{n}」各端都做完了，等你验收',
                          '说明': '看证据包：每条需求在各端的完成度和审查结论', '为什么': '验收后才推送 / 提交到服务器。', '按钮': '去验收', '链接': link})
        elif st == '开发中' and not is_task(m):
            s = m.get('开发会话') or {}
            idle = not (s.get('状态') == '运行中' and _alive(s.get('pid', 0)))
            try:
                age = time.time() - (d / '记录.md').stat().st_mtime
            except OSError:
                age = 0
            if idle and age > STALL_DAYS * 86400 and not q:
                cards.append({'id': f'stall:{n}:{int((d / "记录.md").stat().st_mtime)}', '类型': '建议', '标题': f'「{n}」已经 {int(age // 86400)} 天没有进展',
                              '说明': '开发中，但没有会话在跑，也没有新记录', '为什么': '可能卡在什么地方。去看看：继续开发、补充说明，或者改成已暂停。',
                              '按钮': '去看看', '链接': link})
    try:
        free = [p for p in anr_problems() if not p.get('事项') and p.get('状态') != '忽略']
    except Exception:
        free = []
    cut = _since(nd)
    fresh = [p for p in free if (p.get('最近') or '') >= cut]
    new = [p for p in free if p not in fresh]
    if fresh:
        ids = sorted(p['编号'] for p in fresh)
        autos.append(('ANR建事项', 'ANR建事项:' + ','.join(ids), ids, f'{len(ids)} 个新出现的 ANR / 崩溃问题还没归属', {}))
    cards += _push_cards(cut)
    if new:
        cards.append({'id': 'anr-new:' + ','.join(sorted(p['编号'] for p in new))[:300], '类型': '建议', '标题': f'{len(new)} 个 ANR / 崩溃问题还没放进批次',
                      '说明': '、'.join(f'{p["编号"]}（{p.get("次数", 0)} 次）' for p in sorted(new, key=lambda p: -(p.get('次数') or 0))[:5]),
                      '为什么': '放进批次后才能逐条推动处理；推动会让 AI 改代码，所以要你点。', '按钮': '去处理', '链接': '#/anr'})
    return autos, cards


def _push_cards(cut):
    """最近建的 ANR / 崩溃事项里还没推动的条目：只问工程和分支（默认值选好），点了就推动。"""
    from kblib.steward.intake import push_proposal
    out = []
    for n in period_names():
        try:
            m = load_meta(PERIODS / n)
        except Exception:
            continue
        if not is_task(m) or m.get('事项类型') != 'ANR/崩溃' or m.get('状态') == '已完成' or (m.get('创建时间') or '') < cut:
            continue
        s = m.get('开发会话') or {}
        if s.get('状态') == '运行中' and _alive(s.get('pid', 0)):
            continue
        st = m.get('条目状态') or {}
        try:
            prop = push_proposal(n)
        except Exception:
            continue
        keys = [k for k in prop['条目'] if not (st.get(k) or {}).get('状态')]
        if not keys:
            continue
        prop['条目'] = keys
        out.append({'id': f'push:{n}:{",".join(keys)}', '类型': '问你', '标题': f'「{n}」{len(keys)} 个问题，确认工程就开始处理',
                    '说明': '默认工程和分支已经选好，不对就改', '为什么': '推动会让 AI 改代码，要你点一下；点了就定位原因 → 改代码 → 自测 → 写结论。',
                    '提议': prop, '链接': '#/p/' + n})
    return out


# ---------------------------------------------------------------- 2-4. 判、分流、做

def _decide(autos, cfg, st):
    """自主矩阵：返回 (要自动做的, 转成建议卡片的)。每个决定带置信度和去向（规则判定的置信度为 1）。"""
    done = st.get('已做') or {}
    left = max(0, cfg['每日上限'] - _used_today())
    go, suggest = [], []
    for act, key, obj, why, extra in autos:
        if key in done:
            continue
        reason = ''
        if not cfg['开启']:
            reason = '管家已关闭'
        elif cfg['自主度'] == '保守':
            reason = '自主度是「保守」：只建议，不自动做'
        elif act in cfg['关闭动作']:
            reason = f'「{ACTIONS[act][0]}」没开自动'
        elif left <= 0:
            reason = f'今天已经自动做了 {cfg["每日上限"]} 件，到上限了'
        if reason:
            suggest.append((act, key, obj, why, reason))
            continue
        go.append({'动作': act, '键': key, '对象': obj, '依据': why, '置信度': 1.0, '去向': 'auto', **extra})
        left -= 1
    return go, suggest


def _fresh(d):
    """执行前再查一次：别人已经处理了就不做（jev 的「过期就重新看」）。"""
    if d['动作'] == 'Bug分析':
        e = (zt_load().get('Bug') or {}).get(d['对象'])
        return bool(e) and _bug_need(e) and _bug_key(e) == d['键']
    if d['动作'] == '出方案':
        try:
            return (period_guide(d['对象']) or {}).get('下一步', {}).get('文字') == '让 AI 出方案'
        except Exception:
            return False
    if d['动作'] == 'ANR建事项':
        ps = {p['编号']: p for p in anr_problems()}
        return all(x in ps and not ps[x].get('事项') for x in d['对象'])
    if d['动作'] == '来源整理':
        try:
            m = load_meta(PERIODS / d['对象'])
        except Exception:
            return False
        u = m.get('更新会话') or {}
        return any(s.get('待更新') for s in m.get('来源') or []) and not (u.get('状态') == '运行中' and _alive(u.get('pid', 0)))
    return False


def _act(go, st):
    out = []
    done = st.setdefault('已做', {})
    bugs = [d for d in go if d['动作'] == 'Bug分析'][:PER_TICK]
    running = sum(1 for x in _an.an_sessions() if x.get('状态') == '运行中' and x.get('类型') != '修复')
    if running >= _an.AN_MAX_RUN:
        bugs = []                          # 分析会话满了，下一轮再说（不记「已做」）
    bugs = [d for d in bugs if _fresh(d)]
    for d in bugs:
        done[d['键']] = now()              # 先记下决定再执行，出错也不会反复重试
    if bugs:
        _save_state(st)
        ids = [d['对象'] for d in bugs]
        try:
            msg = _an.bug_analyze(ids, by='管家（自动）')
            res = '已开始'
        except Exception as e:
            msg, res = str(e), '失败'
        out.append(_record(方式='自动', 动作='Bug分析', 对象=ids, 数量=len(ids), 结果=res, 说明=msg,
                           依据={d['对象']: d['依据'] for d in bugs}, 置信度=1.0, 去向='auto', 链接='#/bugs'))
    for d in [d for d in go if d['动作'] == '出方案'][:2]:
        if not _fresh(d):
            continue
        done[d['键']] = now()
        _save_state(st)
        try:
            msg, res = stack_plan_start(d['对象'], by='管家（自动）'), '已开始'
        except Exception as e:
            msg, res = str(e), '失败'
        out.append(_record(方式='自动', 动作='出方案', 对象=d['对象'], 数量=1, 结果=res, 说明=msg, 依据=d['依据'],
                           置信度=1.0, 去向='auto', 链接='#/p/' + d['对象']))
    for d in [d for d in go if d['动作'] == 'ANR建事项']:
        if not _fresh(d):
            continue
        done[d['键']] = now()
        _save_state(st)
        try:
            from kblib.steward.intake import link_task
            task = link_task(d['对象'], by='管家（自动）')
            msg, res = f'{len(d["对象"])} 个问题归到事项「{task}」，等你确认工程推动', '已建事项'
        except Exception as e:
            task, msg, res = '', str(e), '失败'
        out.append(_record(方式='自动', 动作='ANR建事项', 对象=d['对象'], 数量=1, 结果=res, 说明=msg, 依据=d['依据'],
                           置信度=1.0, 去向='auto', 链接=('#/p/' + task) if task else '#/anr'))
    for d in [d for d in go if d['动作'] == '来源整理']:
        if not _fresh(d):
            continue
        done[d['键']] = now()
        _save_state(st)
        try:
            msg, res = _refresh.claude_update(d['对象']), '已开始'
        except Exception as e:
            msg, res = str(e), '失败'
        out.append(_record(方式='自动', 动作='来源整理', 对象=d['对象'], 数量=1, 结果=res, 说明=msg, 依据=d['依据'],
                           置信度=1.0, 去向='auto', 链接='#/p/' + d['对象']))
    return out


def _brief(st, cards):
    """日报：每天第一次巡检（8 点以后）汇总昨天做了什么、今天要你点什么。"""
    today = now()[:10]
    if st.get('日报日期') == today or datetime.now().hour < 8:
        return
    y = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    did = [r for r in steward_log(500, y) if r.get('方式') == '自动' and r.get('结果') != '失败']
    cnt = {}
    for r in did:
        cnt[r['动作']] = cnt.get(r['动作'], 0) + int(r.get('数量') or 1)
    mine = [c for c in cards if c['类型'] in ('待你', '问你')]
    text = ('昨天自动做了：' + '，'.join(f'{ACTIONS.get(k, (k,))[0]} {v} 件' for k, v in cnt.items()) if cnt else '昨天没有需要自动做的事') + \
        (f'。今天有 {len(mine)} 件等你：' + '；'.join(c['标题'] for c in mine[:5]) if mine else '。今天没有要你点的事')
    st['日报日期'] = today
    st['日报'] = {'日期': today, '内容': text}
    _record(方式='日报', 动作='日报', 说明=text)
    _notify('知识库 · 管家日报', text, '管家')


def steward_tick(by='定时'):
    """巡检一轮。返回这一轮的结果说明。"""
    if not _LOCK.acquire(blocking=False):
        return '上一轮还没结束'
    try:
        cfg = steward_settings()
        st = _state()
        autos, cards = _observe()
        go, _ = _decide(autos, cfg, st)
        did = _act(go, st) if cfg['开启'] else []
        cards = [c for c in cards if c['id'] not in (st.get('忽略') or {})]
        if cfg['开启']:
            _brief(st, cards)
            asked = st.setdefault('已提醒', {})
            for c in cards:
                if c['类型'] == '问你' and c['id'] not in asked:
                    asked[c['id']] = now()
                    _notify('知识库 · 管家有问题问你', c['标题'] + '\n' + (c.get('说明') or ''), '管家')
            if len(asked) > 500:
                st['已提醒'] = dict(sorted(asked.items(), key=lambda kv: kv[1])[-300:])
        done = st.get('已做') or {}
        if len(done) > 3000:                  # 只留最近的
            st['已做'] = dict(sorted(done.items(), key=lambda kv: kv[1])[-2000:])
        st.update(上次=now(), 结果=('；'.join(f'{ACTIONS[r["动作"]][0]}：{r["结果"]}' for r in did) or '没有要自动做的事'), 发起=by)
        _save_state(st)
        return st['结果']
    finally:
        _LOCK.release()


# ---------------------------------------------------------------- 网页

def steward_view():
    cfg = steward_settings()
    st = _state()
    autos, cards = _observe()
    _, suggest = _decide(autos, cfg, st)
    ign = st.get('忽略') or {}
    by_act = {}
    for act, key, obj, why, reason in suggest:
        by_act.setdefault(act, []).append((obj, why, reason))
    for act, xs in by_act.items():
        name, desc = ACTIONS[act]
        objs = [x[0] for x in xs]
        cards.append({'id': f'suggest:{act}:' + ','.join(map(str, objs[:30])), '类型': '建议', '标题': f'建议{name}：{len(xs)} 件',
                      '说明': '；'.join(f'{o}（{w}）' for o, w, _ in xs[:4]) + ('…' if len(xs) > 4 else ''), '为什么': xs[0][2],
                      '按钮': '现在就做', '动作': 'run', '对象': {'动作': act, '对象': objs[:20]},
                      '链接': '#/bugs' if act == 'Bug分析' else '#/anr' if act == 'ANR建事项' else '#/p/' + objs[0]})
    for act, key, obj, why, _ in autos:            # 自动整理过一次还没整理完：不再自动重试，交给你看
        if act == '来源整理' and key in (st.get('已做') or {}):
            cards.append({'id': 'src-left:' + key, '类型': '待你', '标题': f'「{obj}」的需求资料自动整理过一次，还没整理完',
                          '说明': why, '为什么': '可能原文改动太大或链接失效，去「来源核对」看看。', '按钮': '去看看', '链接': '#/p/' + obj})
    cards += _upgrade_cards(cfg)
    cards = [c for c in cards if c['id'] not in ign]
    order = {'问你': 0, '待你': 1, '建议': 2}
    cards.sort(key=lambda c: order.get(c['类型'], 3))
    today = now()[:10]
    return {'设置': cfg, '自主度选项': list(LEVELS), '动作': [{'id': k, '名称': v[0], '说明': v[1], '开启': k not in cfg['关闭动作']} for k, v in ACTIONS.items()],
            '卡片': cards, '已做': [r for r in steward_log(30) if r.get('方式') == '自动'], '今日已做': _used_today(),
            '日报': st.get('日报') if (st.get('日报') or {}).get('日期') == today else None,
            '上次': st.get('上次', ''), '结果': st.get('结果', ''),
            '规矩': [r for r in load_settings().get('管家规矩') or [] if isinstance(r, dict) and r.get('内容')]}


def _upgrade_cards(cfg):
    """信任逐步建立：某类建议你最近 14 天里都点了「现在就做」（≥3 次、没点过「不用了」），问你以后要不要直接做。"""
    if not cfg['开启']:
        return []
    since = _since(14)
    logs = [r for r in steward_log(500) if r.get('时间', '') >= since]
    out = []
    for act, (name, _) in ACTIONS.items():
        auto_now = cfg['自主度'] != '保守' and act not in cfg['关闭动作']
        if auto_now:
            continue
        ran = sum(1 for r in logs if r.get('方式') == '手动' and r.get('动作') == act)
        no = sum(1 for r in logs if r.get('方式') == '忽略' and str(r.get('对象', '')).startswith(f'suggest:{act}:'))
        if ran >= 3 and not no:
            out.append({'id': f'upgrade:{act}', '类型': '建议', '标题': f'「{name}」以后让我直接做？',
                        '说明': f'最近 14 天这类建议你都点了「现在就做」（{ran} 次）', '为什么': '直接做的事每天早上的日报里都看得到，随时能在设置里关掉。',
                        '按钮': '以后直接做', '动作': 'upgrade', '对象': act, '链接': '#/settings'})
    return out


def steward_dismiss(cid):
    if not cid:
        raise KBError('缺卡片编号')
    st = _state()
    ign = st.setdefault('忽略', {})
    ign[cid] = now()
    if len(ign) > 500:
        st['忽略'] = dict(sorted(ign.items(), key=lambda kv: kv[1])[-300:])
    _save_state(st)
    _record(方式='忽略', 动作='忽略', 对象=cid)
    return '好，这件事先不提了；情况有变化会再出现'


def _mark_done(act, objs):
    """你手动让管家做过的，记进「已做」，免得会话刚结束又被建议一遍。"""
    st = _state()
    done = st.setdefault('已做', {})
    if act == 'Bug分析':
        bugs = zt_load().get('Bug') or {}
        for b in objs:
            if b in bugs:
                done[_bug_key(bugs[b])] = now()
    else:
        for n in objs:
            try:
                pend = sorted(s['编号'] for s in load_meta(PERIODS / n).get('来源') or [] if s.get('待更新'))
            except Exception:
                continue
            done[f'来源整理:{n}:{",".join(pend)}'] = now()
    _save_state(st)


def steward_answer(cid, value, by='用户（网页）', repo='', branch=''):
    """回答管家的问题 / 点建议卡片上的「现在就做」。"""
    v = steward_view()
    c = next((x for x in v['卡片'] if x['id'] == cid), None)
    if not c:
        raise KBError('这件事已经变了，刷新看看')
    if c.get('提议'):
        from kblib.steward.intake import confirm_push
        p = c['提议']
        msg = confirm_push(p['事项'], p['条目'], repo, branch, by=by)
        _record(方式='手动', 动作='推动', 对象=p['事项'], 数量=len(p['条目']), 结果='已推动', 说明=msg, 回答人=by, 工程=repo, 分支=branch)
        return msg
    if c.get('动作') == 'bug-repo':
        if not value:
            raise KBError('先选一个仓库')
        msg = _an.bug_analyze_in(c['对象'], value, by=by)
        _mark_done('Bug分析', c['对象'])
        _record(方式='回答', 动作='Bug分析', 对象=c['对象'], 数量=len(c['对象']), 结果='已开始', 说明=msg, 回答=value, 回答人=by)
        return msg
    if c.get('动作') == 'upgrade':
        act = c['对象']
        msg = steward_set(level='标准' if steward_settings()['自主度'] == '保守' else None, actions={act: True})
        _record(方式='手动', 动作='放权', 对象=act, 结果='已开启', 说明=msg, 回答人=by)
        return f'好，以后「{ACTIONS[act][0]}」我直接做，日报里告诉你。' + ('（自主度改成了「标准」）' if '标准' in msg else '')
    if c.get('动作') == 'ignore':
        from kblib.bugs.index import bug_ignore
        msg = bug_ignore(c['对象'], True, f'管家建议：超过 {STALE_DAYS} 天没动', by=by)
        _record(方式='手动', 动作='忽略Bug', 对象=c['对象'], 数量=len(c['对象']), 结果='已忽略', 说明=msg, 回答人=by)
        return msg
    if c.get('动作') == 'run':
        act, objs = c['对象']['动作'], c['对象']['对象']
        if act == 'Bug分析':
            msg = _an.bug_analyze(objs, by=by)
        elif act == '出方案':
            msg = '\n'.join(stack_plan_start(o, by=by) for o in objs)
        elif act == 'ANR建事项':
            from kblib.steward.intake import link_task
            msg = '归到事项「' + link_task([x for o in objs for x in (o if isinstance(o, list) else [o])], by=by) + '」，确认工程就能推动'
        else:
            msg = '\n'.join(_refresh.claude_update(o) for o in objs)
        _mark_done(act, objs)
        _record(方式='手动', 动作=act, 对象=objs, 数量=len(objs), 结果='已开始', 说明=msg, 回答人=by)
        return msg
    raise KBError('这张卡片要到对应页面处理')


def steward_text():
    v = steward_view()
    s = v['设置']
    lines = [f'管家：{"开启" if s["开启"] else "关闭"} · 自主度 {s["自主度"]} · 今天自动做了 {v["今日已做"]}/{s["每日上限"]} 件 · 上次巡检 {v["上次"] or "还没有"}（{v["结果"]}）']
    if v['日报']:
        lines.append('日报：' + v['日报']['内容'])
    for c in v['卡片']:
        lines.append(f'- [{c["类型"]}] {c["标题"]}：{c.get("说明", "")}')
    for r in v['已做'][:10]:
        lines.append(f'· {r["时间"]} {ACTIONS.get(r["动作"], (r["动作"],))[0]} {r.get("对象")}：{r.get("结果")}')
    return '\n'.join(lines)
