# From 大大王.DT
"""Bug 索引：多平台同步、统一索引、归属到期 / 事项、实时拉取（平台差异在 bugs/adapters）。"""
import json
import os
import re
import threading
from ..common import KBError, PERIODS, ROOT, load_settings, now, safe_name, save_settings
from ..periods import (
    _guess_task_kind,
    create_task,
    is_task,
    load_meta,
    log,
    period_dir,
    period_names,
    save_meta,
)
from ..search import index_docs
from ..plugins import plugins
from ..devprep import want_branches
from ..refresh import _notice
from ..bugs.sources import _bsrc, _src_call, bug_source, bug_source_conf, bug_sources
from .. import lazy
_bug_analysis = lazy('kblib.bugs.analysis')      # 上层模块：用到时才 import（不形成循环）
_anr_store = lazy('kblib.anr.store')      # 上层模块：用到时才 import（不形成循环）


ZT_DIR = ROOT / 'Bug'
if not ZT_DIR.exists() and (ROOT / '禅道').is_dir() and not (ROOT / '禅道').is_symlink():   # 2026-11 之前叫「禅道」：改名，数据原样带过来
    try:
        (ROOT / '禅道').rename(ZT_DIR)
        (ROOT / '禅道').symlink_to('Bug')       # 还在跑旧代码的进程（其他会话的 MCP）照旧写「禅道/」，实际写进同一份
    except OSError:
        pass
ZT_FILE = ZT_DIR / 'Bug索引.json'
ZT_MD = ZT_DIR / 'Bug索引.md'
ZT_OWNER = ('期', '事项', '待归纳', '未关联')
ZT_SCOPES = ['我的', '全部', '指定人']
ZT_HOURS = float(os.environ.get('KB_BUG_HOURS') or os.environ.get('KB_ZENTAO_HOURS') or '0.25')   # 默认 15 分钟一次，转给别人的 Bug 能及时移除
ZT_LOCAL = ('归属', '分析', '修复')      # 知识库自己的字段：从平台刷新索引时要保留
ZT_FIRST_DAYS = 30            # 第一次同步：未关闭的全部 + 最近 30 天改过的
_ZT_LOCK = threading.Lock()
ZT_STATE = {'running': False, 'last': '', 'result': '', 'next': ''}
BUG_PLUGIN = 'Bug平台'


def _zt_read():
    try:
        data = json.loads(ZT_FILE.read_text('utf-8'))
    except (OSError, ValueError):
        data = {}
    for k in ('Bug', '来源', '同步'):
        data.setdefault(k, {})
    if '游标' in data or '名称' in data:      # 老格式：游标 / 名称 / 同步 都是禅道的 → 挪到「来源/禅道」下
        st = data['来源'].setdefault('禅道', {})
        st.setdefault('游标', data.pop('游标', {}) or {})
        st.setdefault('名称', data.pop('名称', {}) or {})
        st.setdefault('同步', data.pop('同步', {}) or {})
        data['同步'] = {}
    for e in data['Bug'].values():
        _bug_upgrade(e)
    return data


def _bug_upgrade(e):
    """老条目（只有禅道时）补上统一字段。"""
    e.setdefault('来源', '禅道')
    if '禅道修改' in e:
        e['修改时间'] = e.pop('禅道修改')     # 旧进程写的以它为准（更新）
    if 'Jenkins任务' not in e:
        e['Jenkins任务'] = ''
    if '分组' not in e:
        e['分组'] = [g for g in ({'类型': '执行', 'ID': e.get('执行ID', '0'), '名': e.get('执行', ''), '强': 1},
                                {'类型': '项目', 'ID': e.get('项目ID', '0'), '名': e.get('项目', ''), '强': 0}) if g['ID'] not in ('', '0')]
    for k in ('分析', '修复'):
        if isinstance(e.get(k), dict) and '禅道修改' in e[k]:
            e[k]['修改时间'] = e[k].pop('禅道修改')
    an_skip(e)
    return e


def an_skip(e):
    """Bug 已修复（会话或手动标的）就不用再审分析了：待审核 / 需重分析 改成「无需审核」，原状态留着撤销时恢复。"""
    a, f = e.get('分析'), e.get('修复') or {}
    if isinstance(a, dict) and f.get('状态') == '已修复' and a.get('状态') in ('待审核', '需重分析'):
        a['跳过前'] = a['状态']
        a['状态'] = '无需审核'


def zt_load():
    """读 Bug 索引，并记下读到时每条 Bug 的样子：保存时和磁盘上的最新内容三方合并，
    免得同步（要跑几十秒）、修复会话、网页几个进程同时改时，后保存的把别人刚写的（如「修复中」）整份覆盖掉。"""
    data = _zt_read()
    data['_base'] = json.loads(json.dumps(data.get('Bug') or {}, ensure_ascii=False))
    return data


def _zt_merge(base, mine, theirs):
    """三方合并：我没改的取磁盘上的（别人改的），我改了的保留我的；同一字段都改了以我的为准。"""
    out = {}
    for bid in set(mine) | set(theirs):
        b, m, t = base.get(bid), mine.get(bid), theirs.get(bid)
        if m == b:
            v = t                      # 我没动：以磁盘为准（含别人新增 / 删除）
        elif t == b or t is None and b is None:
            v = m                      # 别人没动：用我的
        elif m is None:
            v = None if t == b else t  # 我删了、别人又改了：保留别人的
        elif t is None:
            v = m
        else:
            v = dict(t)
            for k in set(m) | set(t) | set(b or {}):
                bk, mk = (b or {}).get(k), m.get(k)
                if mk != bk:
                    if mk is None:
                        v.pop(k, None)
                    else:
                        v[k] = mk
        if v is not None:
            out[bid] = v
    return out


def zt_save(data):
    import fcntl
    ZT_DIR.mkdir(exist_ok=True)
    for k in ('Bug', '来源', '同步'):
        data.setdefault(k, {})
    base = data.pop('_base', None)
    with open(ZT_DIR / '.Bug索引.lock', 'w') as lk:          # 跨进程：读磁盘 → 合并 → 写，中间不让别人插进来
        fcntl.flock(lk, fcntl.LOCK_EX)
        if base is not None and ZT_FILE.exists():
            data['Bug'] = _zt_merge(base, data['Bug'], _zt_read().get('Bug') or {})
        tmp = ZT_FILE.with_suffix(f'.{os.getpid()}.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), 'utf-8')
        tmp.replace(ZT_FILE)
    data['_base'] = json.loads(json.dumps(data['Bug'], ensure_ascii=False))   # 接着用同一份 data 再存也能合并
    ZT_MD.write_text(_zt_md(data), 'utf-8')


_zt_norm = lambda s: _bsrc().norm(s)


def _zt_branch_key(b):
    return re.sub(r'[^a-z0-9]+', '-', (b or '').lower()).strip('-')


def _period_binds(m):
    """一期绑定的平台分组：「来源/类型/ID」。老的「禅道: {执行, 项目}」照样认。"""
    out = set(m.get('Bug绑定') or [])
    z = m.get('禅道') or {}
    out |= {f'禅道/执行/{x}' for x in z.get('执行') or []} | {f'禅道/项目/{x}' for x in z.get('项目') or []}
    return out


def _zt_periods():
    """每期用来认 Bug 的线索：绑定的分组（执行 / Sprint…）、开发分支、期名里的功能名。"""
    out = []
    for n in period_names():
        d = PERIODS / n
        m = load_meta(d)
        feat = re.sub(r'^[^-－—]*\d+[-－—]', '', n)          # 「综合版26-聊天室语音麦…」→「聊天室语音麦…」
        out.append({'名称': n, '绑定': _period_binds(m),
                    '分支': [k for k in (_zt_branch_key(x) for x in want_branches(d, m)) if len(k) >= 6],
                    '功能': '' if is_task(m) else _zt_norm(feat), '已完成': m.get('状态') == '已完成',
                    '类型': '事项' if is_task(m) else '期'})
    return out


def _gkey(e, g):
    return f'{e.get("来源") or "禅道"}/{g["类型"]}/{g["ID"]}'


def _zt_match(e, pers):
    """→ (期名, 依据)；认不出 → ('', '')。顺序：绑定的强分组（执行 / Sprint）→ Jenkins 分支 → 绑定的弱分组（项目 / 版本）→ 分组名和期名相近。"""
    gs = e.get('分组') or []
    for strong in (1, 0):
        if not strong and e.get('Jenkins任务'):
            jk = _zt_branch_key(e['Jenkins任务'])
            hit = [p for p in pers if any(jk.endswith(k) or k in jk for k in p['分支'])]
            if len(hit) == 1:
                return hit[0]['名称'], f'Jenkins 任务 {e["Jenkins任务"]} 对上开发分支'
        for g in gs:
            if bool(g.get('强')) == bool(strong):
                hit = [p for p in pers if _gkey(e, g) in p['绑定']]
                if len(hit) == 1:
                    return hit[0]['名称'], f'绑定的{g["类型"]}'
    for g in sorted(gs, key=lambda g: not g.get('强')):
        nm = _zt_norm(re.sub(r'/agent$', '', g.get('名') or '', flags=re.I))
        if len(nm) >= 4:
            hit = [p for p in pers if len(p['功能']) >= 4 and (nm in p['功能'] or p['功能'] in nm)]
            if len(hit) == 1:
                return hit[0]['名称'], f'{g["类型"]}名「{g["名"]}」与期名相近'
    return '', ''


def _zt_people(c, me):
    """同步范围里的人：我的 → 自己；指定人 → 设置里填的账号；全部 → 空（不按人筛）。"""
    sc = c.get('范围') or '我的'
    if sc == '全部':
        return set()
    if sc == '指定人':
        return {x.strip() for x in c.get('人员') or [] if x.strip()} or {me}
    return {me}


def _zt_mine(e, people):
    return bool(people & {e.get('指派账号'), e.get('解决账号')} - {''})


def _zt_keep(e):
    """手动归过类、做过分析的，即使不在同步范围里（换了平台 / 范围）也留着；但已经转给别人的不留（见 _zt_other）。"""
    return bool(e) and ((e.get('归属') or {}).get('依据') == '手动' or bool(e.get('分析')))


def _zt_other(e, people):
    """按人同步（我的 / 指定人）时，这条 Bug 已经指派给别人、也不是我们解决的：要从索引里移除，防止误分析、误修。
    正在修复的等会话结束再移除。"""
    return bool(people) and bool(e) and not _zt_mine(e, people) and (e.get('修复') or {}).get('状态') != '修复中'


def _zt_drop_other(e, by):
    """移除转给别人的 Bug：记到归属的期 / 事项里（分析结论文件留着，仍可检索）。"""
    o = e.get('归属') or {}
    if o.get('类型') in ('期', '事项') and o.get('名称') and (e.get('分析') or e.get('修复') or o.get('依据') == '手动'):
        try:
            log(period_dir(o['名称']), 'Bug', f'Bug {e["编号"]} {e["标题"]} 已指派给 {e.get("指派给") or "别人"}，从知识库移除（{by}）')
        except KBError:
            pass


def _zt_done(e):
    """平台上已解决 / 已关闭（不论哪个平台，适配器都统一成 激活 / 已解决 / 已关闭）：不进知识库。正在修复的等会话结束再说。"""
    return bool(e) and e.get('状态') != '激活' and (e.get('修复') or {}).get('状态') != '修复中'


def _zt_drop_done(e, by):
    """已解决 / 已关闭的移出索引；分析过、修过、手动归过的记一笔到归属的期 / 事项（分析结论文件留着，仍可检索）。"""
    o = e.get('归属') or {}
    if o.get('类型') in ('期', '事项') and o.get('名称') and (e.get('分析') or e.get('修复') or o.get('依据') == '手动'):
        try:
            log(period_dir(o['名称']), 'Bug', f'Bug {e["编号"]} {e["标题"]} 平台上{e.get("状态") or "已解决"}，从知识库移除（{by}）')
        except KBError:
            pass


def _src_of(bid, data=None):
    """这个编号属于哪个来源：索引里有就按索引；没有就看前缀 / 编号样子，都不像就用第一个缺陷平台。"""
    bid = str(bid)
    e = (data or zt_load())['Bug'].get(bid)
    ss = bug_sources('缺陷')
    if e:
        c = next((x for x in ss if x['ID'] == e.get('来源')), None)
        if c:
            return c
    bs = _bsrc()
    c = next((x for x in ss if bid.startswith(x['ID'] + '-')), None)
    c = c or next((x for x in ss if x.get('适配器') in bs.ADAPTERS and re.fullmatch(bs.ADAPTERS[x['适配器']].id_pattern, bid)), None)
    return c or bug_source_conf()


def _zt_recheck(ids, by='实时核对'):
    """动手（分析 / 修复）前实时核对指派：已经转给别人的立刻移除。返回 (仍是我们的, 移除说明)。连不上平台就不拦。"""
    keep, gone = [], []
    data = zt_load()
    for bid in ids:
        old = data['Bug'].get(bid)
        try:
            c = _src_of(bid, data)
            src = bug_source(c, by=by)
            people = _zt_people(c, src.account())
            if not people:
                keep.append(bid)
                continue
            e = src.get(bid, download=False, **({'names': data['来源'].setdefault(c['ID'], {}).setdefault('名称', {})} if c['适配器'] == '禅道' else {}))['条目']
        except Exception:
            keep.append(bid)
            continue
        if old:
            for k in ZT_LOCAL:
                if old.get(k):
                    e[k] = old[k]
        if _zt_other(e, people):
            if old:
                _zt_drop_other(e, by)
                data['Bug'].pop(bid, None)
            gone.append(f'{bid}：已指派给 {e.get("指派给") or "别人"}，已从知识库移除')
        else:
            keep.append(bid)
    if gone:
        zt_save(data)
    return keep, gone


def _zt_want(e, c, me):
    people = _zt_people(c, me)
    if people and not _zt_mine(e, people):          # 默认只要自己的（指派给我 / 我解决的）
        return False
    pf = c.get('平台') or '安卓'
    return pf == '全部' or e['平台'] == pf or (not e['平台'] and bool(people))


def _zt_assign(e, pers, people=frozenset()):
    old = e.get('归属') or {}
    if old.get('依据') == '手动' or old.get('类型') == '事项':
        return old
    per, why = _zt_match(e, pers)
    if per:
        kind = next((p['类型'] for p in pers if p['名称'] == per), '期')
        return {'类型': kind, '名称': per, '依据': why, '时间': old.get('时间') if old.get('名称') == per else now()}
    if e.get('线上') or _zt_mine(e, set(people)):
        return {'类型': '待归纳', '名称': '', '依据': '线上反馈' if e.get('线上') else '没对上任何一期',
                '时间': old.get('时间') if old.get('类型') == '待归纳' else now()}
    return {'类型': '未关联', '名称': '', '依据': '没对上任何一期（别的功能 / 别人负责）', '时间': old.get('时间') or now()}


def bug_sync(by='自动同步', full=False, only=''):
    """增量同步所有缺陷平台（或 only 指定的一个）的 Bug 索引；崩溃平台顺带同步到 ANR / 崩溃。只存索引字段。"""
    srcs = [c for c in bug_sources() if c['启用'] and (not only or c['ID'] == only)]
    if not srcs:
        return '没有启用的 Bug 平台' + ('' if only else '：网页「🐞 Bug」页点「＋ 接入平台」')
    if not _ZT_LOCK.acquire(blocking=False):
        return 'Bug 正在同步，稍后再看'
    ZT_STATE['running'] = True
    outs, errs = [], []
    try:
        pers = _zt_periods()
        for c in srcs:
            try:
                outs.append(_crash_sync(c, by, full) if c['类型'] == '崩溃' else _sync_one(c, pers, by, full))
            except (KBError, _bsrc().SourceError) as ex:
                errs.append(f'{c["ID"]} 同步失败：{ex}')
                data = zt_load()
                data['同步'][c['ID']] = f'{now()} 失败：{ex}'
                zt_save(data)
        index_docs()
        res = '\n'.join(outs + errs)
        ZT_STATE['result'] = res
        if errs and not outs:
            raise KBError(res)
        return res
    finally:
        ZT_STATE['running'] = False
        ZT_STATE['last'] = now()
        _ZT_LOCK.release()


def zentao_sync(by='自动同步', full=False):
    return bug_sync(by, full)


def _sync_one(c, pers, by, full):
    src = bug_source(c, by=by)
    sid = c['ID']
    me = _src_call(src.account)
    people = _zt_people(c, me)
    data = zt_load()
    bugs = data['Bug']
    state = data['来源'].setdefault(sid, {})
    if full:
        state.pop('游标', None)
    mine = lambda e: (e.get('来源') or '禅道') == sid
    for bid in [k for k, e in bugs.items() if mine(e) and ((not _zt_want(e, c, me) and not _zt_keep(e)) or _zt_other(e, people))]:
        if _zt_other(bugs[bid], people):
            _zt_drop_other(bugs[bid], by)
        bugs.pop(bid)                   # 范围 / 平台改小了、转给别人了：索引里先清掉
    for bid in [k for k, e in bugs.items() if mine(e) and _zt_done(e)]:
        _zt_drop_done(bugs.pop(bid), by)  # 已解决 / 已关闭的不留
    res = {'new': [], 'changed': 0, 'gone': 0}
    ctx = {'全量': full, '人员': people, '平台': c.get('平台') or '安卓', '首次天数': ZT_FIRST_DAYS,
           '已有': {k: e.get('修改原值') for k, e in bugs.items() if mine(e)}}
    for e in _src_call(lambda: list(src.sync(state, ctx))):
        if '删除' in e:
            if bugs.pop(e['删除'], None):
                res['gone'] += 1
            continue
        bid = e['编号']
        old = bugs.get(bid)
        if old and old.get('修改原值') == e['修改原值'] and not full:
            continue
        for k in ZT_LOCAL:
            if old and old.get(k):
                e[k] = old[k]
        if _zt_done(e):                 # 已解决 / 已关闭：不同步进来，原来有的移除
            if old:
                _zt_drop_done(e, by)
                bugs.pop(bid, None)
                res['gone'] += 1
            continue
        if (not _zt_want(e, c, me) and not _zt_keep(old)) or _zt_other(e, people):
            if old:                     # 不在范围里了（转给别人、换过范围 / 平台）：去掉
                if _zt_other(e, people):
                    _zt_drop_other(e, by)
                    res['gone'] += 1
                bugs.pop(bid, None)
            continue
        e['归属'] = _zt_assign(e, pers, people)
        if old and e.get('分析') and old.get('修改原值') != e['修改原值']:
            e['分析']['过时'] = True    # 分析之后平台上有改动：结论可能过时
        e['同步时间'] = now()
        bugs[bid] = e
        if old:
            res['changed'] += 1
        else:
            res['new'].append(e)
    data['同步'][sid] = f'{now()} 完成' + ''.join(f'；{v}' for v in (state.get('同步') or {}).values() if '失败' in str(v))
    data['上次同步'] = now()
    zt_save(data)
    new = res['new']
    for e in new:
        o = e['归属']
        if o['类型'] == '期':
            _notice(PERIODS / o['名称'], f'{sid} 新 Bug {e["编号"]}：{e["标题"]}（{e["链接"]}）')
    mineb = [e for e in bugs.values() if mine(e)]
    return (f'{sid} 同步完成（{by}）：新增 {len(new)}，更新 {res["changed"]}' + (f'，删除 {res["gone"]}' if res['gone'] else '') +
            f'；共 {len(mineb)} 条，待归纳 {sum(1 for e in mineb if e["归属"]["类型"] == "待归纳" and e["状态"] != "已关闭")}')


def _zt_md(data):
    bugs = list(data.get('Bug', {}).values())
    out = ['# Bug 索引', '', '> 自动生成。只记链接和简介；正文、评论、截图以 Bug 平台为准，处理时用 kb_bug_get 实时拉取。', '']
    groups = {}
    for e in bugs:
        o = e.get('归属') or {}
        groups.setdefault(o.get('名称') or o.get('类型') or '待归纳', []).append(e)
    for g in sorted(groups, key=lambda x: (x != '待归纳', x)):
        out += [f'## {g}', '']
        for e in sorted(groups[g], key=lambda x: x.get('修改原值') or '', reverse=True):
            out.append(f'- Bug {e["编号"]} ［{e.get("来源") or ""}·{e["状态"]}·{e.get("平台") or "?"}{"·线上" if e.get("线上") else ""}］{e["标题"]}　{e["链接"]}\n'
                       f'  {e.get("简介", "")}' + (f'\n  分析（{e["分析"].get("状态", "")}）：{e["分析"].get("摘要", "")}' if e.get('分析') else '')
                       + (f'\n  修复：{e["修复"].get("状态")} {" ".join(x["提交"][:8] for x in e["修复"].get("提交") or [])}' if e.get('修复') else ''))
        out.append('')
    return '\n'.join(out)


def _zt_groups(e):
    return '　'.join(f'{g["类型"]}：{g.get("名") or g["ID"]}' for g in e.get('分组') or [])


def _zt_line(e, detail=False):
    o = e.get('归属') or {}
    s = (f'- Bug {e["编号"]} ［{e.get("来源") or ""}·{e["状态"]}·严重{e.get("严重") or "?"}·{e.get("平台") or "平台?"}{"·线上" if e.get("线上") else ""}］{e["标题"]}\n'
         f'  {e["链接"]}　指派：{e.get("指派给") or "无"}　平台上修改：{e.get("修改时间")}\n'
         f'  简介：{e.get("简介") or "无"}\n  归属：{o.get("类型")}{" " + o["名称"] if o.get("名称") else ""}（{o.get("依据", "")}）')
    if detail:
        s += f'\n  产品：{e.get("产品") or "无"}　{_zt_groups(e)}　版本：{e.get("版本") or ""}' + \
             (f'\n  Jenkins：{e["Jenkins"]}' if e.get('Jenkins') else '')
    if e.get('修复'):
        f = e['修复']
        s += f'\n  修复（知识库标记）：{f["状态"]}' + (f'，提交 {"、".join(x["提交"][:8] for x in f.get("提交") or [])}' if f.get('提交') else '') + (f'：{f["说明"]}' if f.get('说明') else '')
    if e.get('分析'):
        a = e['分析']
        s += (f'\n  分析（{a.get("时间")}，{a.get("状态", "")}，置信度 {a.get("置信度") or "?"}{"，⚠ 平台上已有改动，可能过时" if a.get("过时") else ""}）：{a.get("摘要", "")}'
              + ''.join(f'\n    · {x["路径"]}:{x["行"]} {x["说明"]}' for x in (a.get('代码位置') or [])[:3])
              + (f'\n  审核意见：{a["意见"]}' if a.get('意见') else ''))
    return s


def bug_list(iteration='', owner='', status='未关闭', query='', limit=50):
    data = zt_load()
    es = list(data['Bug'].values())
    if iteration:
        n = period_dir(iteration).name
        es = [e for e in es if (e.get('归属') or {}).get('名称') == n]
    if owner:
        es = [e for e in es if (e.get('归属') or {}).get('类型') == owner]
    if status == '未关闭':
        es = [e for e in es if e['状态'] != '已关闭']
    elif status and status != '全部':
        es = [e for e in es if e['状态'] == status]
    if query:
        q = query.lower()
        es = [e for e in es if q in json.dumps(e, ensure_ascii=False).lower()]
    es.sort(key=lambda e: e.get('修改原值', ''), reverse=True)
    es.sort(key=lambda e: ((e.get('修复') or {}).get('状态') == '已修复',                    # 知识库标了已修复的沉底
                           {'激活': 0, '已解决': 1, '已关闭': 2}.get(e['状态'], 9), int(e.get('严重') or 9) if str(e.get('严重') or '').isdigit() else 9))
    head = f'Bug {len(es)} 条（上次同步 {data.get("上次同步") or "从未"}）'
    if not es:
        return head + '\n（没有）'
    return head + '\n' + '\n'.join(_zt_line(e, detail=bool(iteration)) for e in es[:limit]) + \
        (f'\n……还有 {len(es) - limit} 条' if len(es) > limit else '') + \
        '\n\n知识库只存简介；处理前用 kb_bug_get 从平台实时拉取正文、评论和截图。'


def bug_assign(bid, target, by='Claude', bind=True):
    """改 Bug 归属：target = 期名 / 事项名 / 「待归纳」/「事项:名称」（事项不存在就新建）。
    归到期且这个 Bug 有强分组（禅道执行、Jira Sprint）时，顺便把分组绑定到这一期。"""
    data = zt_load()
    e = data['Bug'].get(str(bid))
    if not e:
        raise KBError(f'Bug 索引里没有 {bid}（先同步，或它不在当前同步范围里）')
    target = (target or '').strip()
    if target in ('', '待归纳'):
        e['归属'] = {'类型': '待归纳', '名称': '', '依据': '手动', '时间': now()}
        zt_save(data)
        return f'Bug {bid} 已放回待归纳'
    msg_new = ''
    if target.startswith(('事项:', '事项：')):
        tn = target[3:].strip()
        if not tn:
            raise KBError('事项名不能为空')
        if not (PERIODS / safe_name(tn)).exists():
            zt_save(data)
            create_task(tn, f'由 Bug {bid} 建立：{e["标题"]}', '线上问题' if e.get('线上') else _guess_task_kind(e['标题']),
                        source=f'{e.get("来源") or ""} Bug {bid}', by=by)
            data = zt_load()
            e = data['Bug'][str(bid)]
            msg_new = f'（新建了事项「{safe_name(tn)}」）'
        target = tn
    d = period_dir(target)
    m = load_meta(d)
    kind = '事项' if is_task(m) else '期'
    e['归属'] = {'类型': kind, '名称': d.name, '依据': '手动', '时间': now()}
    msg = f'Bug {bid} 已归到{kind}「{d.name}」{msg_new}'
    g = next((g for g in e.get('分组') or [] if g.get('强')), None)
    if kind == '期' and bind and g:
        gk = _gkey(e, g)
        if gk not in _period_binds(m):
            m.setdefault('Bug绑定', []).append(gk)
            save_meta(d, m)
            msg += f'；{g["类型"]}「{g.get("名") or g["ID"]}」已绑定到这一期，以后这个{g["类型"]}的 Bug 自动归过来'
            for o in data['Bug'].values():          # 同一分组里还在待归纳的，一起归过来
                if (o.get('归属') or {}).get('类型') == '待归纳' and any(_gkey(o, x) == gk for x in o.get('分组') or []):
                    o['归属'] = {'类型': '期', '名称': d.name, '依据': f'绑定的{g["类型"]}', '时间': now()}
    log(d, 'Bug', f'Bug {bid} 归到本{kind}（{by}）：{e["标题"]} {e["链接"]}')
    zt_save(data)
    return msg


def bug_get(bid, download=True):
    """实时拉取一个 Bug 的完整内容（正文、评论、附件下载到临时目录），不写进知识库；顺便刷新索引字段。"""
    bid = str(bid).strip()
    data = zt_load()
    c = _src_of(bid, data)
    src = bug_source(c, by='实时拉取 Bug')
    st = data['来源'].setdefault(c['ID'], {})
    r = _src_call(src.get, bid, download, **({'names': st.setdefault('名称', {})} if c['适配器'] == '禅道' else {}))
    e = r['条目']
    old = data['Bug'].get(e['编号'])
    warn = ''
    if old:
        for k in ZT_LOCAL:
            if old.get(k):
                e[k] = old[k]
        if old.get('修改原值') and old['修改原值'] != e['修改原值']:
            warn = f'⚠ 这条 Bug 在 {old.get("修改时间")} 之后平台上又改过（现在 {e["修改时间"]}），以下以最新内容为准。'
            if e.get('分析'):
                e['分析']['过时'] = True
    me = _src_call(src.account)
    people = _zt_people(c, me)
    if not old:
        e['归属'] = _zt_assign(e, _zt_periods(), people or {me})
    e['同步时间'] = now()
    if people and not _zt_mine(e, people):
        warn = (f'⛔ 这个 Bug 已经指派给 {e.get("指派给") or "别人"}，不是你（或同步范围里的人）的了：不要分析、不要修改代码。'
                + ('修复会话请用 kb_bug_fixed done=false 说明「已转给别人」后结束。' if (e.get('修复') or {}).get('状态') == '修复中' else '已从知识库移除。')
                + ('\n' + warn if warn else ''))
        if _zt_other(e, people):
            if old:
                _zt_drop_other(e, '实时拉取')
            data['Bug'].pop(e['编号'], None)
        else:
            data['Bug'][e['编号']] = e
    else:
        data['Bug'][e['编号']] = e
    zt_save(data)
    out = [f'# {c["ID"]} Bug {e["编号"]}：{e["标题"]}', e['链接'], warn,
           f'状态：{e["状态"]}　严重：{e.get("严重") or "?"}　优先级：{e.get("优先级") or "?"}　平台：{e.get("平台") or "?"}{"　线上" if e.get("线上") else ""}　版本：{e.get("版本") or ""}',
           *[x for x in r.get('信息') or [] if x],
           f'指派：{e.get("指派给") or "无"}　创建：{e.get("创建人")} {e.get("创建时间")}　平台上修改：{e.get("修改时间")}',
           f'归属：{e["归属"]["类型"]} {e["归属"].get("名称", "")}（{e["归属"].get("依据", "")}）',
           (f'Jenkins：{e["Jenkins"]}' if e.get('Jenkins') else ''), '', '## 正文', r.get('正文') or '（空）']
    if r.get('评论'):
        out += ['', '## 评论 / 处理记录'] + [f'- {t} {who}（{act}）：{txt}' if act else f'- {t} {who}：{txt}' for t, who, act, txt in r['评论']]
    if r.get('附件'):
        out += ['', '## 附件 / 截图（临时下载，不进知识库；图片用 Read 查看）'] + [f'- {g}' for g in r['附件']]
    return '\n'.join(x for x in out if x is not None)


def zentao_bug(bid, download=True):
    return bug_get(bid, download)


def bug_status():
    data = zt_load()
    bugs = list(data['Bug'].values())
    open_ = [e for e in bugs if e['状态'] != '已关闭']
    srcs = []
    for c in bug_sources():
        mineb = [e for e in open_ if e.get('来源') == c['ID']]
        srcs.append({k: c.get(k) for k in ('ID', '适配器', '类型', '启用', '账号条目', '范围', '人员', '平台', '选项')} |
                    {'同步': data['同步'].get(c['ID'], ''), '未关闭': len(mineb)})
    return {'平台': srcs, '平台选项': _bsrc().PLATFORMS, '范围选项': ZT_SCOPES, '适配器': bug_adapters(),
            '上次同步': data.get('上次同步') or '', '正在同步': ZT_STATE['running'], '结果': ZT_STATE['result'],
            '下次同步': ZT_STATE['next'], '间隔小时': ZT_HOURS, '总数': len(bugs), '未关闭': len(open_),
            '待归纳': sum(1 for e in open_ if (e.get('归属') or {}).get('类型') == '待归纳')}


zentao_status = bug_status


def bug_adapters():
    """可选的平台：内置适配器 + 「Bug平台」插件。"""
    out = _bsrc().adapter_info()
    for p in plugins():
        if p.get('Bug平台') and not p.get('错误'):
            out.append({'名称': p.get('名称') or p['id'], '类型': p.get('平台类型') or '缺陷', '账号字段': p.get('说明') or '',
                        '选项': [], '关键字': [], '插件': p['id']})
    return out


def save_bug_source(sid, by='用户（网页）', remove=False, **kw):
    """新增 / 修改 / 删除一个平台来源。kw：适配器、账号条目、启用、范围、人员、平台、选项、新ID。
    改范围 / 平台会清掉游标，下次重新扫一遍。删除只去掉设置和没做过分析 / 手动归类的索引条目。"""
    sid = (sid or '').strip()
    if not sid:
        raise KBError('平台名称不能为空')
    bug_sources()
    s = load_settings()
    srcs = s['Bug平台']
    c = next((x for x in srcs if x['ID'] == sid), None)
    data = zt_load()
    if remove:
        if not c:
            raise KBError(f'没有这个平台：{sid}')
        srcs.remove(c)
        save_settings(s)
        n = 0
        for k in [k for k, e in data['Bug'].items() if e.get('来源') == sid and not _zt_keep(e) and not e.get('修复')]:
            data['Bug'].pop(k)
            n += 1
        data['来源'].pop(sid, None)
        data['同步'].pop(sid, None)
        zt_save(data)
        return f'已移除平台「{sid}」，索引里去掉 {n} 条（分析过、手动归过类、修复过的保留）'
    if not c:
        ad = kw.get('适配器') or ''
        if not any(a['名称'] == ad or a.get('插件') == ad for a in bug_adapters()):
            raise KBError(f'没有这种平台：{ad or "（没选）"}')
        if not re.fullmatch(r'[\w一-鿿.]{1,20}', sid):
            raise KBError('平台名称只能用中文、字母、数字、下划线、点，最多 20 个字（会当作编号前缀，如 jira-…）')
        c = {'ID': sid, '适配器': ad, '启用': True, '范围': '我的', '人员': [], '平台': '安卓'}
        srcs.append(c)
    reset = False
    if kw.get('平台') is not None:
        if kw['平台'] not in _bsrc().PLATFORMS:
            raise KBError(f'平台只能是：{"、".join(_bsrc().PLATFORMS)}')
        reset |= c.get('平台') != kw['平台']
        c['平台'] = kw['平台']
    if kw.get('人员') is not None:
        p = kw['人员']
        p = [x.strip() for x in (p.split(',') if isinstance(p, str) else p) if x.strip()]
        reset |= p != c.get('人员')
        c['人员'] = p
    if kw.get('范围') is not None:
        if kw['范围'] not in ZT_SCOPES:
            raise KBError(f'范围只能是：{"、".join(ZT_SCOPES)}')
        if kw['范围'] == '指定人' and not c.get('人员'):
            raise KBError('选「指定人」要填平台账号（多个用逗号隔开）')
        reset |= c.get('范围') != kw['范围']
        c['范围'] = kw['范围']
    if kw.get('启用') is not None:
        c['启用'] = bool(kw['启用'])
    if kw.get('账号条目') is not None:
        reset |= c.get('账号条目') != kw['账号条目']
        c['账号条目'] = kw['账号条目']
    if kw.get('选项') is not None:
        o = {k: v for k, v in kw['选项'].items() if str(v).strip() != ''}
        reset |= o != (c.get('选项') or {})
        c['选项'] = o
    save_settings(s)
    if reset:
        data['来源'].setdefault(sid, {}).pop('游标', None)
        zt_save(data)
    return bug_status()


def save_zentao_settings(platform=None, enabled=None, entry=None, scope=None, people=None, source=''):
    c = bug_source_conf(source)
    return save_bug_source(c['ID'], 平台=platform, 启用=enabled, 账号条目=entry, 范围=scope, 人员=people)


def zentao_bugs_json(period='', owner=''):
    """网页用：Bug 列表（含已关闭，前端自己筛）。"""
    _bug_analysis._fx_heal()
    es = list(zt_load()['Bug'].values())
    if period:
        es = [e for e in es if (e.get('归属') or {}).get('名称') == period]
    if owner:
        es = [e for e in es if (e.get('归属') or {}).get('类型') == owner]
    es.sort(key=lambda e: e.get('修改原值', ''), reverse=True)
    run = {b for x in _bug_analysis.an_sessions() if x.get('状态') == '运行中' and x.get('类型') != '修复' for b in x.get('Bug', [])}
    out = []
    for e in es:
        x = {k: v for k, v in e.items() if k != '修改原值'}
        a = e.get('分析')
        x['分析'] = {k: a.get(k) for k in ('摘要', '状态', '过时', '置信度', '时间', '意见')} if a else None
        x['分析中'] = e['编号'] in run
        f = e.get('修复')
        x['修复'] = {k: f.get(k) for k in ('状态', '时间', '提交', '说明', '标记', '等待', '阻塞')} if f else None
        out.append(x)
    return out


CRASH_DONE = {'resolved', 'closed', '已解决', '已关闭', '已处理'}     # 崩溃平台上已解决的问题也不同步


def _crash_sync(c, by, full):
    """崩溃平台 → ANR / 崩溃：每个平台问题对应一个样本（堆栈 + 平台上的累计次数），按签名和手动导入的日志合并。"""
    src = bug_source(c, by=by)
    data = zt_load()
    state = data['来源'].setdefault(c['ID'], {})
    if full:
        state.pop('游标', None)
    items = _src_call(lambda: [x for x in src.sync(state, {'全量': full, '平台': c.get('平台'), '首次天数': ZT_FIRST_DAYS})
                               if '删除' not in x and str(x.get('状态') or '').lower() not in CRASH_DONE])
    r = _anr_store.anr_platform_upsert(c['ID'], items, by=by)
    data['同步'][c['ID']] = f'{now()} 完成'
    data['上次同步'] = now()
    zt_save(data)
    return f'{c["ID"]} 同步完成（{by}）：{r}'
