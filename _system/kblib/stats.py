"""工作统计：知识库只交「事实」，算哪些数、怎么算由统计插件决定（插件/工作统计/，可换成自己的）。

插件约定：plugin.json「类型: 工具」「能力: ["统计"]」，在「⚙ 设置 → 插件」挂载后总览显示统计。
  运行：命令 + `stats <范围>`，标准输入是事实 JSON（stats_facts），标准输出最后一行是结果 JSON：
    {"范围": "本周", "起": "2026-11-09", "卡片": [{"标题", "值", "说明", "链接"}],
     "进度": [{"名称", "状态", "完成", "总数", "说明", "链接"}]}
  终端 kb stats [范围]、AI 用 kb_plugin_call 也能调（插件没收到标准输入时自己运行 `kb stats --facts` 取事实）。
"""
import json
import re
import subprocess
import sys
import time

from .common import KBError, PERIODS, now
from .periods import is_task, load_meta, period_names
from .flows import flow_progress
from .devsession import DEV_DIR, session_flow
from .plugins import _plugin_env, plugins
from .bugs.index import zt_load
from .anr.store import _ar_done_at, anr_problems

STAT_CAP = '统计'
RANGES = ('今天', '本周', '本月', '近7天', '近30天', '全部')
_CACHE = {}


def _progress(m):
    """这一期做到哪了 → {完成, 总数, 说明}；看不出来时 None。"""
    ends = m.get('各端开发') or {}
    if ends:
        ok = sum(1 for x in ends.values() if x.get('状态') == '审查通过')
        return {'完成': ok, '总数': len(ends), '说明': f'全栈 {ok}/{len(ends)} 端审查通过'}
    pg = flow_progress(session_flow(m), m.get('SDD目录'))
    if not pg:
        return None
    if pg.get('类型') == '任务清单':
        return {'完成': pg['完成'], '总数': pg['总数'], '说明': f'任务清单 {pg["完成"]}/{pg["总数"]}' + (f'，在做：{pg["当前"][:40]}' if pg.get('当前') else '')}
    steps = pg.get('步骤') or []
    t = pg.get('任务') or {}
    code_done = any(s['名称'] == '代码实现' and s['状态'] == 'done' for s in steps)
    if t.get('总数'):
        done = t['总数'] if code_done else max(0, t['序号'] - 1)
        return {'完成': done, '总数': t['总数'], '说明': f'开发任务 {done}/{t["总数"]}' + (f'，在做：{t["当前"][:40]}' if t.get('当前') and not code_done else '')}
    done = sum(1 for s in steps if s['状态'] == 'done')
    cur = next((s['名称'] for s in steps if s['状态'] != 'done'), '')
    return {'完成': done, '总数': len(steps), '说明': f'SDD 第 {done}/{len(steps)} 步' + (f'，在做：{cur}' if cur else '')}


def _sessions(d):
    """这一期跑过的后台 AI 会话的开始时间（会话记录文件名里的时间）。"""
    out = []
    for f in (d / DEV_DIR).glob('*.jsonl') if (d / DEV_DIR).is_dir() else []:
        mm = re.search(r'(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)(\d\d)$', f.stem)
        if mm:
            out.append('{}-{}-{} {}:{}:{}'.format(*mm.groups()))
    return sorted(out)


def stats_facts():
    """统计用的原始事实（不含资料正文、不含机密）。"""
    out = {'生成时间': now(), '期': [], 'Bug': [], 'ANR': []}
    for n in period_names():
        d = PERIODS / n
        try:
            m = load_meta(d)
            prog = _progress(m)
        except Exception:                 # 一期的文档读不出来不影响整体统计
            m, prog = load_meta(d), None
        out['期'].append({'名称': n, '类型': '事项' if is_task(m) else '期', '事项类型': m.get('事项类型', ''),
                         '状态': m.get('状态', ''), '创建时间': m.get('创建时间', ''),
                         '状态历史': [{'时间': h.get('时间', ''), '状态': h.get('状态', '')} for h in m.get('状态历史') or []],
                         '进度': prog, 'AI会话': _sessions(d),
                         '待确认': sum(1 for q in m.get('待确认') or [] if q.get('状态') == '待回答')})
    try:
        for e in zt_load()['Bug'].values():
            if e.get('忽略'):          # 你标了忽略的陈旧 Bug 不算
                continue
            f = e.get('修复') or {}
            out['Bug'].append({'编号': e.get('编号', ''), '平台状态': e.get('状态', ''), '期': (e.get('归属') or {}).get('名称', ''),
                               '修复状态': f.get('状态', ''), '修复时间': f.get('时间', ''),
                               '创建时间': e.get('创建时间', ''), '修改时间': e.get('修改时间', ''), '严重': e.get('严重', ''), '线上': bool(e.get('线上'))})
    except Exception:
        pass
    try:
        done, items = {}, {}
        for p in anr_problems(include_ignored=True):
            t = p['事项']
            if t and t not in done:
                done[t] = _ar_done_at(t)[1]
                items[t] = load_meta(PERIODS / t).get('条目状态') or {} if (PERIODS / t).is_dir() else {}
            it = (items.get(t) or {}).get('anr:' + p['编号']) or {}
            out['ANR'].append({'编号': p['编号'], '类型': p['类型'], '次数': p['次数'], '状态': p['状态'],
                               '事项': t, '事项状态': p['事项状态'], '完成时间': done.get(t, '') if t else '',
                               '结论': it.get('状态', ''), '结论时间': it.get('结论时间', ''),
                               '修复后又出现': p['修复后又出现'], '首次': p['首次'], '最近': p['最近']})
    except Exception:
        pass
    return out


def stats_plugin():
    return next((p for p in plugins() if STAT_CAP in (p.get('能力') or []) and p.get('启用') and not p.get('错误')), None)


def work_stats(rng='', by='网页'):
    """运行统计插件。没挂统计插件 → None；插件出错 → {'错误': …}（总览照常显示）。结果缓存 60 秒。"""
    p = stats_plugin()
    if not p:
        return None
    rng = rng if rng in RANGES else (p['配置'].get('默认范围') or '本周')
    k = (p['id'], rng)
    if k in _CACHE and time.time() - _CACHE[k][0] < 60:
        return _CACHE[k][1]
    cmd = [sys.executable if x == '{python}' else x for x in p['命令']] + ['stats', rng]
    try:
        r = subprocess.run(cmd, cwd=p['目录'], env=_plugin_env(p, by, KB_EVENT='统计'), input=json.dumps(stats_facts(), ensure_ascii=False),
                           capture_output=True, text=True, timeout=int(p.get('超时') or 60))
        if r.returncode:
            raise KBError(f'退出码 {r.returncode}：{(r.stderr or r.stdout).strip()[-500:]}')
        res = json.loads(r.stdout.strip().splitlines()[-1])
    except (KBError, OSError, ValueError, IndexError, subprocess.TimeoutExpired) as e:
        res = {'错误': f'统计插件「{p["名称"]}」出错：{e}'}
    res.update(插件=p['名称'], 插件id=p['id'], 范围=res.get('范围') or rng, 范围列表=list(RANGES))
    _CACHE[k] = (time.time(), res)
    return res


def stats_text(rng=''):
    """终端 kb stats：把统计结果排成几行字。"""
    r = work_stats(rng, by='终端')
    if r is None:
        return '没有挂载统计插件：网页「⚙ 设置 → 插件」挂载「工作统计」'
    if r.get('错误'):
        raise KBError(r['错误'])
    lines = [f'工作统计（{r["范围"]}{"，" + r["起"] + " 起" if r.get("起") else ""}）']
    lines += [f'- {c["标题"]}：{c["值"]} {c.get("单位", "")}' + (f'（{c["说明"]}）' if c.get('说明') else '') for c in r.get('卡片') or []]
    if r.get('进度'):
        lines.append('进度：')
        lines += [f'- {x["名称"]}（{x.get("状态", "")}）{x.get("说明", "")}' for x in r['进度']]
    return '\n'.join(lines)
