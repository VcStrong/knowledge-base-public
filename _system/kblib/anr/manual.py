"""ANR / 崩溃页「＋ 自建问题」：日志可以是文件，也可以是粘贴的内容；mapping 可以是本地文件，也可以填 URL 自动下载。

认得出堆栈的照常按签名合并成问题（anr_add）；认不出的（只有一段描述、截断的日志）也能建：类型「手动」，签名按标题，
不参与 mapping 重算。
"""
import gzip
import io
import re
import shutil
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from ..common import PERIODS, SYS, KBError, now
from ..infra import fetch
from .store import (_AR_LOCK, AR_SAMPLES, _ar_load, _ar_probs, _ar_save, _ar_save_probs, _ar_write_md, anr_add, anr_link,
                    anr_mapping, auto_version)

MAP_MAX = 800 * 1024 * 1024


def _tmpdir():
    d = SYS / 'tmp' / uuid.uuid4().hex
    d.mkdir(parents=True)
    return d


def _unpack_mapping(name, data, d):
    """下载到的可能是 mapping.txt，也可能是 zip / gz：取出 mapping.txt。"""
    if data[:2] == b'PK':
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            cand = [i for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith('.txt')]
            if not cand:
                raise KBError(f'{name} 里没有 .txt 文件')
            best = next((i for i in cand if i.filename.lower().endswith('mapping.txt')), max(cand, key=lambda i: i.file_size))
            data = z.read(best)
    elif data[:2] == b'\x1f\x8b':
        data = gzip.decompress(data)
    f = d / 'mapping.txt'
    f.write_bytes(data)
    return f


def anr_mapping_url(version, url, by='用户（网页）'):
    """按 URL 下载 mapping（Jenkins 产物、网盘直链等；需要登录的站点用 kb login 存账号），归档到这个版本。"""
    url = (url or '').strip()
    version = (version or '').strip() or auto_version()
    if not re.match(r'https?://', url):
        raise KBError('mapping 地址要以 http:// 或 https:// 开头')
    d = _tmpdir()
    try:
        try:
            data, headers, final = fetch.http_get(url, MAP_MAX)
        except fetch.FetchError as e:
            raise KBError(f'下载 mapping 失败（地址不对，或站点要登录）：{e}')
        if data[:200].lstrip().lower().startswith((b'<!doctype', b'<html')):
            raise KBError('这个地址返回的是网页，不是 mapping 文件（要登录？用文件的直接下载地址）')
        return anr_mapping(version, _unpack_mapping(final.rsplit('/', 1)[-1], data, d), by=by)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _manual(text, title, version, source, by):
    """认不出堆栈：按标题建一个「手动」问题。"""
    from . import parse as anr
    title = (title or '').strip()
    lines = [x.rstrip() for x in (text or '').splitlines() if x.strip()]
    if not title:
        if not lines:
            raise KBError('没认出堆栈；要手动建问题，至少写个标题')
        title = lines[0][:80]
    rid = anr.raw_id((text or '') + title)
    with _AR_LOCK:
        samples = _ar_load()
        if any(s['编号'] == rid for s in samples):
            raise KBError('一样的内容已经建过了')
        AR_SAMPLES.mkdir(parents=True, exist_ok=True)
        f = AR_SAMPLES / f'{datetime.now():%Y%m%d-%H%M%S}-{rid}.txt'
        f.write_text((text or title) + '\n', 'utf-8')
        sig = 'manual:' + title
        samples.append({'编号': rid, '文件': f.name, '原文件': '手动输入', '加入时间': now(), '来源': source or '', '次数': 1,
                        '发生时间': '', '加入': by, '类型': '手动', '签名': sig, '标题': title, '原因': '',
                        '关键堆栈': lines[:15], '已还原': None, '应用帧': [], '版本': version or '', '问题': anr.sig_id(sig)})
        _ar_save(samples)
    _ar_write_md()
    return samples[-1]['问题']


def repo_choices():
    """自建问题 / 建事项时选代码仓库：登记过的仓库 + 各期用过的开发仓库，附当前分支、未提交改动、正被哪些期用着。"""
    from ..repos import load_repos
    from ..periods import load_meta, period_names
    import subprocess
    paths = {}
    for nm, r in load_repos().items():
        pth = r.get('路径') if isinstance(r, dict) else r
        if pth:
            paths.setdefault(str(Path(pth).expanduser()), set())
    for n in period_names():
        m = load_meta(PERIODS / n)
        if m.get('开发仓库'):
            u = paths.setdefault(m['开发仓库'], set())
            s = m.get('开发会话') or {}
            if m.get('状态') in ('已批准开发', '开发中') or s.get('状态') == '运行中':
                u.add(n)
    out = []
    for pth, users in paths.items():
        if not (Path(pth) / '.git').exists():
            continue
        g = lambda *a: subprocess.run(['git', '-C', pth, *a], capture_output=True, text=True).stdout.strip()
        dirty = len([x for x in g('status', '--porcelain').splitlines() if x.strip()])
        out.append({'路径': pth, '名称': Path(pth).name, '分支': g('branch', '--show-current'), '改动': dirty,
                    '在用': sorted(users)})
    return sorted(out, key=lambda x: (bool(x['在用']) or x['改动'] > 0, x['名称']))


def _setup_task(name, branch, repo, by):
    """新建的事项直接带上分支和代码仓库，点「开始开发」就能用。"""
    from ..periods import load_meta, log, period_dir, save_meta
    from ..notes import add_note
    d = period_dir(name)
    out = []
    if branch:
        add_note(d.name, branch, '其他资料', '分支', source=by)
        out.append(f'分支 {branch}')
    if repo:
        rp = Path(repo).expanduser()
        if not ((rp / '.git').exists() or (rp / '.svn').exists()):
            raise KBError(f'{rp} 不是 git 仓库，也不是 svn 工作副本')
        m = load_meta(d)
        m['开发仓库'] = str(rp)
        save_meta(d, m)
        log(d, '确认开发仓库', f'{rp}（建事项时指定，{by}）')
        out.append(f'仓库 {rp}')
    return out


def anr_create(text='', paths=(), title='', version='', source='', task='', note='', mapping_url='', mapping_path='',
               by='用户（网页）', task_name='', branch='', repo=''):
    """自建问题：先归档 mapping（有的话），再归档日志（文件 + 粘贴内容）；认不出堆栈的按标题建「手动」问题。"""
    version = (version or '').strip()
    text = (text or '').strip()
    paths = [Path(p) for p in paths or []]
    if not text and not paths and not (title or '').strip():
        raise KBError('粘贴日志内容、选日志文件，或至少写个标题')
    new_task = task in ('＋新建', '+新建', '新建')
    out = []
    if mapping_url or mapping_path:
        if not version:                 # 版本不是必填：先从日志里认，认不出就给这次的日志和 mapping 起一个共用的版本名
            from . import parse as anr
            version = anr._version(text) or next((anr._version(p.read_text('utf-8', 'replace')[:200000]) for p in paths
                                                  if p.is_file() and p.suffix.lower() != '.zip'), '') or auto_version()
        out.append(anr_mapping_url(version, mapping_url, by) if mapping_url else anr_mapping(version, mapping_path, by=by))
    d = _tmpdir()
    try:
        if text:
            f = d / f'粘贴-{datetime.now():%m%d-%H%M%S}.txt'
            f.write_text(text + '\n', 'utf-8')
            paths.append(f)
        before = {s['编号'] for s in _ar_load()}
        pids = []
        try:
            if not paths:
                raise KBError('没认出')         # 只写了标题：直接按标题建
            out.append(anr_add([str(p) for p in paths], version, source, '' if new_task else task, by=by))
            pids = list(dict.fromkeys(s['问题'] for s in _ar_load() if s['编号'] not in before))
        except KBError as e:
            if '没认出' not in str(e):
                raise
            pids = [_manual(text, title, version, source, by)]
            out.append(f'{"没认出 ANR / 崩溃堆栈，" if paths else ""}按标题建了问题 {pids[0]}（类型「手动」）')
    finally:
        shutil.rmtree(d, ignore_errors=True)
    if pids and not (mapping_url or mapping_path):          # 没带 mapping：到各期的构建里找同版本的（挂了构建插件时）
        from .store import _ar_map_file
        vers = {x['版本'] for x in _ar_load() if x['问题'] in pids and x.get('版本') and x.get('已还原') is False}
        for v in sorted(v for v in vers if not _ar_map_file(v)):
            try:
                from .. import builds
                r = builds.anr_auto_mapping(v, by)
                if r:
                    out.append(r)
            except KBError as e:
                out.append(f'从构建取版本 {v} 的 mapping 失败：{e}')
    if pids and new_task:              # 这次的问题都归到一个新事项（不是一个问题建一个）
        from .store import _ar_task_name, anr_problems
        from ..periods import create_task
        ps = {p['编号']: p for p in anr_problems(True)}
        first = ps[pids[0]]
        name = (task_name or '').strip() or (_ar_task_name(first) if len(pids) == 1
                                             else f'ANR/崩溃 {len(pids)} 个问题 {datetime.now():%m%d}')
        total = sum(ps[x]['次数'] for x in pids)
        create_task(name, f'{len(pids)} 个 ANR / 崩溃问题' + (f'（{source}）' if source else ''), 'ANR/崩溃', f'ANR崩溃 {"、".join(pids)}',
                    '高' if total >= 10 else '中', by=by)
        out = [x.replace('\n没关联事项的问题，可以在网页「💥 ANR / 崩溃」点「建事项」，或 kb_anr_link 归到已有事项。', '') for x in out]
        out.append(f'新建事项「{name}」，关联 {len(pids)} 个问题')
        out += _setup_task(name, (branch or '').strip(), (repo or '').strip(), by)
        task, new_task = name, False
        for pid in pids:
            anr_link(pid, task=name, by=by)
    elif pids and task and (branch or repo):
        out += _setup_task(task, (branch or '').strip(), (repo or '').strip(), by)
    if pids and ((title or '').strip() or note or task):
        probs = _ar_probs()
        for pid in pids:
            if (title or '').strip():
                probs.setdefault(pid, {})['标题'] = title.strip()
        _ar_save_probs(probs)
        for pid in pids:
            if note or new_task or (task and not probs.get(pid, {}).get('事项')):
                anr_link(pid, task=task or None, note=note or None, by=by)
        _ar_write_md()
    return '\n'.join(x for x in out if x)


def anr_batch(pids, task, name='', by='用户（网页）'):
    """问题列表里勾选几个：task='＋新建' 建一个新批次（事项）把它们都放进去；事项名 = 加入已有批次。"""
    from datetime import datetime
    from .store import anr_link, anr_problems
    from ..periods import create_task
    pids = [x for x in dict.fromkeys(pids or []) if x]
    if not pids:
        raise KBError('先勾选问题')
    ps = {p['编号']: p for p in anr_problems(True)}
    bad = [x for x in pids if x not in ps]
    if bad:
        raise KBError(f'没有这些问题：{"、".join(bad)}')
    out = []
    if task in ('＋新建', '+新建', '新建'):
        task = (name or '').strip() or f'ANR/崩溃 {len(pids)} 个问题 {datetime.now():%m%d}'
        total = sum(ps[x]['次数'] for x in pids)
        create_task(task, f'{len(pids)} 个 ANR / 崩溃问题', 'ANR/崩溃', f'ANR崩溃 {"、".join(pids)}', '高' if total >= 10 else '中', by=by)
        out.append(f'新建批次「{task}」')
    elif not task:
        raise KBError('选一个批次，或新建')
    for pid in pids:
        anr_link(pid, task=task, by=by)
    out.append(f'{len(pids)} 个问题放进「{task}」')
    return '；'.join(out)
