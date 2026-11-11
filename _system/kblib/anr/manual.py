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

from ..common import SYS, KBError, now
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


def anr_create(text='', paths=(), title='', version='', source='', task='', note='', mapping_url='', mapping_path='',
               by='用户（网页）'):
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
