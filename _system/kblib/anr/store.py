# From 大大王.DT
"""ANR / 崩溃归并：样本、问题、事项关联、平台同步来的问题。"""
import json
import re
import shutil
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from ..common import KBError, PERIODS, ROOT, now, read_text, safe_name
from ..periods import create_task, is_task, load_meta, log, period_dir, period_names
from ..search import index_docs
from ..refresh import _notice


# 样本原文存在 ANR崩溃/样本/（用户给的日志，本来就是资料），归并结果存 样本.json；问题和事项的关联、忽略存 问题.json。
# 和事项只通过「问题 → 事项名」一条线关联：事项处理时用 kb_anr 读合并后的堆栈；不改事项的流程和状态。
AR_DIR = ROOT / 'ANR崩溃'
AR_SAMPLES = AR_DIR / '样本'
AR_MAPS = AR_DIR / 'mapping'
AR_FILE = AR_DIR / '样本.json'
AR_PROB = AR_DIR / '问题.json'
AR_MD = AR_DIR / 'ANR崩溃索引.md'
AR_MAX_BYTES = 50 << 20
AR_KINDS = ('ANR', 'Java崩溃', 'Native崩溃')
_AR_LOCK = threading.Lock()


def _ar_load():
    try:
        return json.loads(read_text(AR_FILE)) if AR_FILE.exists() else []
    except ValueError:
        return []


def _ar_save(samples):
    AR_DIR.mkdir(parents=True, exist_ok=True)
    AR_FILE.write_text(json.dumps(samples, ensure_ascii=False, indent=1), 'utf-8')


def _ar_probs():
    try:
        return json.loads(read_text(AR_PROB)) if AR_PROB.exists() else {}
    except ValueError:
        return {}


def _ar_save_probs(p):
    AR_DIR.mkdir(parents=True, exist_ok=True)
    AR_PROB.write_text(json.dumps(p, ensure_ascii=False, indent=1), 'utf-8')


def _ar_texts(path):
    """文件 / 目录 / zip（bugreport）→ [(名称, 文本)]；跳过二进制和超大文件。"""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise KBError(f'文件不存在：{p}')

    def dec(b):
        if b'\0' in b[:4096]:
            return None
        return b.decode('utf-8', 'replace')
    out = []
    files = [p] if p.is_file() else sorted(x for x in p.rglob('*') if x.is_file() and not x.name.startswith('.'))
    for f in files:
        if f.suffix.lower() == '.zip':
            with zipfile.ZipFile(f) as z:
                for zi in z.infolist():
                    n = zi.filename
                    base = n.rsplit('/', 1)[-1]
                    if zi.is_dir() or zi.file_size > AR_MAX_BYTES or base.startswith(('bugreport', '.')):
                        continue      # bugreport 主文件包含整机日志，噪音太多：只取 anr/、tombstones/ 和单独的日志
                    if not (re.search(r'(^|/)(anr|tombstones?)/', n) or re.search(r'\.(txt|log|trace)$', base, re.I) or base.startswith(('anr_', 'tombstone', 'traces'))):
                        continue
                    t = dec(z.read(zi))
                    if t:
                        out.append((f'{f.name}!{n}', t))
            continue
        if f.stat().st_size > AR_MAX_BYTES:
            continue
        t = dec(f.read_bytes())
        if t:
            out.append((f.name, t))
    return out


def _ar_map_file(ver):
    if not ver:
        return None
    f = AR_MAPS / f'{safe_name(ver)}.txt'
    return f if f.exists() else None


def _ar_analyze(evs):
    """evs: [(ev, 版本)] → [分析结果]；同一版本的 mapping 只读一遍。"""
    from ..anr import parse as anr
    need = {}
    for ev, ver in evs:
        if _ar_map_file(ver):
            need.setdefault(ver, set()).update(anr.obf_classes(ev['原文']))
    maps = {v: anr.Mapping(_ar_map_file(v), n) for v, n in need.items()}
    return [anr.analyze(ev, maps.get(ver)) for ev, ver in evs]


def _ar_record(s, r, ver):
    from ..anr import parse as anr
    s.update({k: r[k] for k in ('类型', '签名', '标题', '原因', '关键堆栈', '已还原', '应用帧')})
    s['版本'] = ver
    s['问题'] = anr.sig_id(r['签名'])
    if r.get('发生时间') and not s.get('发生时间'):
        s['发生时间'] = r['发生时间']
    return s


def anr_add(paths, version='', source='', task='', count=1, by='Claude'):
    """归档 ANR / 崩溃日志：拆成一次次事件，按堆栈签名合并到「问题」，累计次数。"""
    from ..anr import parse as anr
    if isinstance(paths, str):
        paths = [paths]
    if not paths:
        raise KBError('请给出日志文件（traces / anr_* / tombstone / logcat / Bugly 导出 / bugreport.zip，也可以是目录）')
    tdir = period_dir(task) if task else None
    count = max(1, int(count or 1))
    with _AR_LOCK:
        samples = _ar_load()
        have = {s['编号'] for s in samples}
        evs, names, dup, empty = [], [], 0, []
        for p in paths:
            texts = _ar_texts(p)
            got = 0
            for name, t in texts:
                for ev in anr.split_events(t):
                    rid = anr.raw_id(ev['原文'])
                    if rid in have:
                        dup += 1
                        continue
                    have.add(rid)
                    evs.append((ev, version or anr._version(ev['原文']) or anr._version(t)))
                    names.append((name, rid))
                    got += 1
            if not got:
                empty.append(Path(p).name)
        if not evs:
            msg = f'没有新的事件（重复 {dup} 次）' if dup else '没认出 ANR / 崩溃堆栈'
            raise KBError(msg + (f'：{"、".join(empty)}' if empty else ''))
        res = _ar_analyze(evs)
        AR_SAMPLES.mkdir(parents=True, exist_ok=True)
        probs = _ar_probs()
        known = {s['问题'] for s in samples}
        touched = {}
        for (ev, ver), r, (name, rid) in zip(evs, res, names):
            f = AR_SAMPLES / f'{datetime.now():%Y%m%d-%H%M%S}-{rid}.txt'
            f.write_text(ev['原文'] + '\n', 'utf-8')
            s = _ar_record({'编号': rid, '文件': f.name, '原文件': name, '加入时间': now(), '来源': source or '', '次数': count,
                            '发生时间': r.get('发生时间', ''), '加入': by}, r, ver)
            samples.append(s)
            touched.setdefault(s['问题'], []).append(s)
        if tdir:
            for pid in touched:
                probs.setdefault(pid, {})['事项'] = tdir.name
        _ar_save(samples)
        _ar_save_probs(probs)
    ps = {p['编号']: p for p in anr_problems(True)}
    out = [f'归档 {len(evs)} 次事件，归到 {len(touched)} 个问题（新问题 {sum(1 for x in touched if x not in known)} 个）'
           + (f'，重复跳过 {dup} 次' if dup else '') + (f'；没认出堆栈：{"、".join(empty)}' if empty else '')]
    for pid, ss in touched.items():
        p = ps[pid]
        tag = '新' if pid not in known else f'累计 {p["次数"]} 次'
        out.append(f'- {pid} ［{p["类型"]}·{tag}］{p["标题"]}' + (f'　→ {p["事项"]}' if p.get('事项') else '')
                   + ('\n  ⚠ 堆栈是混淆的，还没还原：' + (f'版本 {ss[0]["版本"]} 没有 mapping，用 kb_anr_mapping 归档后会自动重算' if ss[0]['版本']
                                                   else '认不出版本，用 kb_anr_mapping 归档 mapping 时指定这些样本的版本') if ss[0]['已还原'] is False else ''))
        if p.get('事项') and pid in known:
            try:
                d = period_dir(p['事项'])
                log(d, 'ANR/崩溃', f'问题 {pid} 又出现 {len(ss)} 次（累计 {p["次数"]}）')
                _notice(d, f'关联的 ANR / 崩溃问题 {pid} 又出现 {len(ss)} 次，用 kb_anr 看最新样本')
            except KBError:
                pass
    if not tdir and any(not ps[x].get('事项') for x in touched):
        out.append('没关联事项的问题，可以在网页「💥 ANR / 崩溃」点「建事项」，或 kb_anr_link 归到已有事项。')
    _ar_write_md()
    index_docs()
    return '\n'.join(out)


def anr_platform_upsert(sid, items, by='平台同步'):
    """崩溃平台同步来的问题 → 样本：每个平台问题一个样本（外部键 来源:问题ID），次数 / 用户数取平台上的累计值（覆盖，不累加）。
    堆栈交给 anr.analyze 算签名，和手动导入的 traces 按签名合并；没给堆栈的按平台问题单独成一个问题。"""
    from ..anr import parse as anr
    new = upd = 0
    with _AR_LOCK:
        samples = _ar_load()
        idx = {s.get('外部'): s for s in samples if s.get('外部')}
        todo = []
        for it in items:
            ext = f'{sid}:{it["外部ID"]}'
            s = idx.get(ext)
            if it.get('堆栈') is None and not s:
                continue                     # 新问题还没取到堆栈：下次再来
            stack = (it.get('堆栈') or '').strip()
            n = max(1, int(float(it.get('次数') or 1)))
            info = {'次数': n, '用户数': int(float(it.get('用户数') or 0)), '链接': it.get('链接') or '', '平台状态': it.get('状态') or '',
                    '发生时间': it.get('最近') or '', '首次': it.get('首次') or '', '平台标题': it.get('标题') or ''}
            if s and (it.get('堆栈') is None or s.get('堆栈指纹') == anr.raw_id(stack or ext)) and (s.get('版本') or '') == (it.get('版本') or s.get('版本') or ''):
                if any(s.get(k) != v for k, v in info.items()):
                    s.update(info)
                    upd += 1
                continue
            if not s:
                s = {'编号': anr.raw_id(ext), '外部': ext, '原文件': f'{sid} 问题 {it["外部ID"]}', '加入时间': now(), '来源': sid, '加入': by}
                samples.append(s)
                idx[ext] = s
                new += 1
            else:
                upd += 1
            s.update(info)
            s['堆栈指纹'] = anr.raw_id(stack or ext)
            f = AR_SAMPLES / f'平台-{safe_name(sid)}-{s["编号"]}.txt'
            AR_SAMPLES.mkdir(parents=True, exist_ok=True)
            f.write_text(f'# {it.get("标题") or ""}\n# {it.get("链接") or ""}\n\n{stack}\n', 'utf-8')
            s['文件'] = f.name
            kind = it.get('类型') if it.get('类型') in AR_KINDS else 'Java崩溃'
            if stack:
                todo.append((s, {'类型': kind, '原文': stack}, it.get('版本') or ''))
            else:
                _ar_record(s, {'类型': kind, '签名': f'EXT|{ext}', '标题': it.get('标题') or ext, '原因': it.get('原因') or '',
                               '关键堆栈': [], '已还原': None, '应用帧': []}, it.get('版本') or '')
        if todo:
            for (s, ev, ver), r in zip(todo, _ar_analyze([(ev, ver) for _, ev, ver in todo])):
                if not r.get('签名') or r['签名'].endswith('|'):
                    r = dict(r, 签名=f'EXT|{s["外部"]}', 标题=s.get('平台标题') or r.get('标题'))
                _ar_record(s, r, ver)
        _ar_save(samples)
    if new or upd:
        _ar_write_md()
    return f'ANR / 崩溃 新问题样本 {new}，更新 {upd}（共 {len(items)} 个平台问题）'


def auto_version():
    """没写版本时给 mapping（和同一次放进来的日志）起的版本名，不和已有的重名。"""
    base = f'未标版本-{datetime.now():%Y%m%d-%H%M%S}'
    v, i = base, 2
    while (AR_MAPS / f'{safe_name(v)}.txt').exists():
        v, i = f'{base}-{i}', i + 1
    return v


def anr_mapping(version, path, by='Claude'):
    """归档某个版本的 mapping.txt，并用它重算这个版本的样本（还原后签名会变，旧问题的事项关联会带过去）。"""
    version = (version or '').strip() or auto_version()   # 不写版本也能归档：之后给样本补上这个版本名即可还原
    src = Path(path).expanduser().resolve()
    if not src.is_file():
        raise KBError(f'文件不存在：{src}')
    with src.open(encoding='utf-8', errors='replace') as fp:
        head = ''.join(fp.readline() for _ in range(50))
    if not re.search(r'^\S+ -> \S+:\s*$', head, re.M):
        raise KBError(f'{src.name} 不像 ProGuard / R8 的 mapping.txt（没有「原类名 -> 混淆名:」）')
    AR_MAPS.mkdir(parents=True, exist_ok=True)
    dest = AR_MAPS / f'{safe_name(version)}.txt'
    if src != dest:
        shutil.copy2(src, dest)
    n, moved = _ar_reprocess(lambda s: s.get('版本') == version)
    return f'已归档 mapping：版本 {version}（{dest.stat().st_size >> 20} MB）→ {dest}\n重算这个版本的样本 {n} 次' + (f'，{moved} 次归到了新的问题（混淆前后签名不同，事项关联已带过去）' if moved else '')


def anr_set_version(target, version, by='Claude'):
    """给版本不明的样本补上版本号（target = 问题编号或样本编号），有 mapping 就顺便还原。"""
    version = (version or '').strip()
    if not version:
        raise KBError('请写版本号')
    ids = {target}
    n, moved = _ar_reprocess(lambda s: (s['问题'] in ids or s['编号'] in ids) and (s.get('版本') or '') != version, version)
    if not n:
        raise KBError(f'没找到问题 / 样本 {target}，或版本已经是 {version}')
    return f'已把 {n} 次事件的版本改为 {version}' + ('，并用 mapping 还原' if _ar_map_file(version) else '（这个版本还没有 mapping）') + (f'；{moved} 次归到了新的问题' if moved else '')


def _ar_reprocess(pred, version=None):
    from ..anr import parse as anr
    with _AR_LOCK:
        samples = _ar_load()
        todo = [s for s in samples if pred(s) and s.get('类型') != '手动']     # 手动建的没有堆栈，不重算
        if not todo:
            return 0, 0
        evs = []
        for s in todo:
            f = AR_SAMPLES / s['文件']
            evs.append(({'类型': s['类型'], '原文': read_text(f) if f.exists() else ''}, version or s.get('版本', '')))
        res = _ar_analyze(evs)
        probs = _ar_probs()
        moved = 0
        for s, (_, ver), r in zip(todo, evs, res):
            old = s['问题']
            _ar_record(s, r, ver)
            if s['问题'] != old:
                moved += 1
                o = probs.get(old) or {}
                n = probs.setdefault(s['问题'], {})
                for k in ('事项', '状态', '备注'):
                    if o.get(k) and not n.get(k):
                        n[k] = o[k]
        live = {s['问题'] for s in samples}
        probs = {k: v for k, v in probs.items() if k in live}
        _ar_save(samples)
        _ar_save_probs(probs)
    _ar_write_md()
    index_docs()
    return len(todo), moved


def _ar_done_at(task):
    try:
        m = load_meta(period_dir(task))
    except KBError:
        return None, ''
    if m.get('状态') != '已完成':
        return m.get('状态'), ''
    return '已完成', next((h['时间'] for h in reversed(m.get('状态历史') or []) if h.get('状态') == '已完成'), '')


def anr_problems(include_ignored=False):
    probs = _ar_probs()
    groups = {}
    for s in _ar_load():
        groups.setdefault(s['问题'], []).append(s)
    out = []
    for pid, ss in groups.items():
        ss.sort(key=lambda s: s.get('发生时间') or s['加入时间'])
        last = ss[-1]
        p = probs.get(pid) or {}
        if p.get('状态') == '忽略' and not include_ignored:
            continue
        task = p.get('事项', '')
        tst, done = _ar_done_at(task) if task else (None, '')
        again = sum(s.get('次数', 1) for s in ss if done and (s.get('发生时间') or s['加入时间']) > done)
        out.append({'编号': pid, '类型': last['类型'], '标题': p.get('标题') or last['标题'], '原因': last.get('原因', ''),
                    '次数': sum(s.get('次数', 1) for s in ss), '样本数': len(ss),
                    '版本': sorted({s['版本'] for s in ss if s.get('版本')}, key=lambda v: [int(x) if x.isdigit() else 0 for x in re.split(r'\D+', v)]),
                    '首次': ss[0].get('发生时间') or ss[0]['加入时间'], '最近': last.get('发生时间') or last['加入时间'],
                    '已还原': last.get('已还原'), '应用帧': last.get('应用帧') or [], '关键堆栈': last.get('关键堆栈') or [],
                    '平台': [{'来源': s['来源'], '链接': s['链接'], '次数': s.get('次数', 1), '用户数': s.get('用户数', 0)} for s in ss if s.get('外部')],
                    '事项': task, '事项状态': tst or '', '修复后又出现': again, '状态': p.get('状态', ''), '备注': p.get('备注', ''),
                    '样本': [{'编号': s['编号'], '路径': str(AR_SAMPLES / s['文件']), '原文件': s.get('原文件', ''), '版本': s.get('版本', ''),
                              '发生时间': s.get('发生时间', ''), '加入时间': s['加入时间'], '来源': s.get('来源', ''), '次数': s.get('次数', 1),
                              '链接': s.get('链接', ''), '用户数': s.get('用户数', 0), '平台状态': s.get('平台状态', '')}
                             for s in reversed(ss)]})
    out.sort(key=lambda p: p['最近'], reverse=True)
    out.sort(key=lambda p: (p['状态'] == '忽略', -p['修复后又出现'], -p['次数']))
    return out


def _ar_line(p):
    return (f'- {p["编号"]} ［{p["类型"]}·{p["次数"]} 次{"·忽略" if p["状态"] == "忽略" else ""}］{p["标题"]}'
            + (f'　版本 {"、".join(p["版本"][-3:])}' if p['版本'] else '') + f'　最近 {p["最近"][:16]}'
            + (f'　→ 事项「{p["事项"]}」{p["事项状态"]}' if p['事项'] else '')
            + (f'　⚠ 修复后又出现 {p["修复后又出现"]} 次' if p['修复后又出现'] else '')
            + ('　（混淆未还原）' if p['已还原'] is False else ''))


def anr_list(query='', task='', include_ignored=False):
    ps = anr_problems(include_ignored)
    if task:
        tn = period_dir(task).name
        ps = [p for p in ps if p['事项'] == tn]
    if query:
        q = query.lower()
        ps = [p for p in ps if q in json.dumps(p, ensure_ascii=False).lower()]
    if not ps:
        return '没有 ANR / 崩溃问题' + ('（符合条件的）' if query or task else '：把 traces / 崩溃日志给我，用 kb_anr_add 归档')
    return f'ANR / 崩溃问题 {len(ps)} 个（按次数排；kb_anr 带编号看关键堆栈和样本）：\n' + '\n'.join(_ar_line(p) for p in ps)


def anr_show(pid):
    p = next((x for x in anr_problems(True) if x['编号'] == pid), None)
    if not p:
        raise KBError(f'没有这个问题：{pid}')
    out = [f'# {p["编号"]} {p["标题"]}', f'类型：{p["类型"]}　次数：{p["次数"]}（样本 {p["样本数"]} 个）　首次 {p["首次"]}　最近 {p["最近"]}',
           f'版本：{"、".join(p["版本"]) or "不明"}' + ('　⚠ 混淆未还原（缺 mapping 或版本不明）' if p['已还原'] is False else ''),
           f'原因：{p["原因"] or "无"}', f'事项：{p["事项"] or "未关联"}' + (f'（{p["事项状态"]}）' if p['事项状态'] else '')
           + (f'　⚠ 事项完成后又出现 {p["修复后又出现"]} 次' if p['修复后又出现'] else '')]
    if p['备注'] or p['状态']:
        out.append(f'状态：{p["状态"] or "—"}　备注：{p["备注"] or "—"}')
    out.append('\n## 关键堆栈（最近一次' + ('，已用 mapping 还原' if p['已还原'] else '') + '）\n```\n' + '\n'.join(p['关键堆栈']) + '\n```')
    out.append('\n## 样本（最近 10 个，原文用 kb_read 读）')
    out += [f'- {s["编号"]} {s["发生时间"] or s["加入时间"]} 版本 {s["版本"] or "不明"}' + (f' ×{s["次数"]}' if s['次数'] > 1 else '')
            + (f' 来源 {s["来源"]}' if s['来源'] else '') + (f'（平台上累计，影响 {s["用户数"]} 人）{s["链接"]}' if s.get('链接') else '') + f'\n  {s["路径"]}' for s in p['样本'][:10]]
    out.append('\n排查前先 kb_search 看以前同类问题的结论；定位时以样本原文为准（关键堆栈只截了前几十行）。')
    return '\n'.join(out)


def _ar_task_name(p):
    a = (p['应用帧'] or [''])[0]
    if p['类型'] == 'ANR':
        parts = ['ANR', a or p['标题']]
    elif p['类型'] == 'Java崩溃':
        parts = ['崩溃', a, p['标题'].split(' · ')[0]]
    elif p['类型'] == '手动':
        parts = ['崩溃', p['标题']]
    else:
        parts = ['Native崩溃', a or p['标题']]
    parts = [re.sub(r'[（(].*$', '', x).strip() for x in parts if x]
    while len(parts) > 2 and len(' '.join(parts)) > 40:
        parts.pop()
    n = ' '.join(parts)[:40]
    return n if not (PERIODS / safe_name(n)).exists() else f'{n} {p["编号"]}'


def anr_link(pid, task=None, status=None, note=None, by='用户（网页）'):
    """问题 → 事项：task='＋新建' 建一个 ANR/崩溃 事项；事项名 = 归到已有事项（或期）；'' = 取消关联。status：''/忽略。"""
    p = next((x for x in anr_problems(True) if x['编号'] == pid), None)
    if not p:
        raise KBError(f'没有这个问题：{pid}')
    ch = []
    target = None
    if task in ('＋新建', '+新建', '新建'):
        name = _ar_task_name(p)
        create_task(name, f'{p["标题"]}\n{p["原因"]}'.strip(), 'ANR/崩溃', f'ANR崩溃 {pid}（{p["次数"]} 次）',
                    '高' if p['次数'] >= 10 else '中', by=by)
        target = PERIODS / safe_name(name)
        ch.append(f'新建事项「{target.name}」')
    elif task:
        target = period_dir(task)
    with _AR_LOCK:
        probs = _ar_probs()
        e = probs.setdefault(pid, {})
        if task is not None:
            old = e.get('事项', '')
            e['事项'] = target.name if target else ''
            if target and old != target.name:
                ch.append(f'关联到「{target.name}」')
                log(target, 'ANR/崩溃', f'关联问题 {pid}：{p["标题"]}（{p["次数"]} 次；kb_anr 看堆栈）（{by}）')
                _notice(target, f'关联了 ANR / 崩溃问题 {pid}，用 kb_anr 看合并后的堆栈和样本')
            elif not target and old:
                ch.append(f'取消关联「{old}」')
        if status is not None:
            if status not in ('', '忽略'):
                raise KBError('状态只能是 忽略 或 空')
            if e.get('状态', '') != status:
                e['状态'] = status
                ch.append('忽略' if status else '取消忽略')
        if note is not None and note != e.get('备注', ''):
            e['备注'] = note
            ch.append('备注已改')
        _ar_save_probs(probs)
    _ar_write_md()
    return f'问题 {pid}：' + ('；'.join(ch) or '没有变化')


def anr_delete_sample(rid, by='用户（网页）'):
    with _AR_LOCK:
        samples = _ar_load()
        s = next((x for x in samples if x['编号'] == rid), None)
        if not s:
            raise KBError(f'没有这个样本：{rid}')
        samples.remove(s)
        (AR_SAMPLES / s['文件']).unlink(missing_ok=True)
        _ar_save(samples)
    _ar_write_md()
    index_docs()
    return f'已删除样本 {rid}'


def _period_anr_md(name):
    try:
        ps = [p for p in anr_problems(True) if p['事项'] == name]
    except Exception:
        return ''
    if not ps:
        return ''
    return f'\n## ANR / 崩溃（{len(ps)} 个问题；kb_anr 带编号看合并后的关键堆栈和样本原文）\n' + '\n'.join(_ar_line(p) for p in ps)


def _ar_write_md():
    """生成可检索的索引（问题标题、原因、还原后的关键堆栈），以后同类问题能搜到。"""
    ps = anr_problems(True)
    if not ps and not AR_MD.exists():
        return
    out = ['# ANR / 崩溃索引', '', '> 知识库自动生成：按堆栈签名合并的问题。原文在 ANR崩溃/样本/。', '']
    for p in ps:
        out += [f'## {p["编号"]} {p["标题"]}', '',
                f'{p["类型"]} · {p["次数"]} 次 · 版本 {"、".join(p["版本"]) or "不明"} · 首次 {p["首次"]} · 最近 {p["最近"]}'
                + (f' · 事项「{p["事项"]}」' if p['事项'] else '') + (f' · {p["状态"]}' if p['状态'] else ''), '']
        if p['原因']:
            out += [f'原因：{p["原因"]}', '']
        if p['备注']:
            out += [f'备注：{p["备注"]}', '']
        out += ['```', *p['关键堆栈'][:25], '```', '']
    AR_DIR.mkdir(parents=True, exist_ok=True)
    AR_MD.write_text('\n'.join(out), 'utf-8')


def anr_json():
    ps = anr_problems(True)
    maps = sorted((f.stem for f in AR_MAPS.glob('*.txt')), reverse=True) if AR_MAPS.exists() else []
    return {'problems': ps, 'mappings': maps, 'tasks': [n for n in period_names() if is_task(load_meta(PERIODS / n))]}
