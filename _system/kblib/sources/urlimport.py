# From 大大王.DT
"""网址导入（Confluence、设计稿等）。"""
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from kblib.core.common import (
    CATS,
    DOC_EXT,
    HIST,
    KBError,
    NOTE_SUFFIX,
    PROTO_DIR,
    SYS,
    now,
    read_text,
    safe_name,
    uuid_hex,
)
from kblib.core.periods import add_material, guess_category, load_meta, log, period_dir, save_meta, write_doc
from kblib.core.search import index_docs
from kblib import lazy
_refresh = lazy('kblib.sources.refresh')      # 上层模块：用到时才 import（不形成循环）


SRC_DIR = '来源快照'


def _fetch():
    from kblib.infra import fetch
    return fetch


def _page(url):
    f = _fetch()
    try:
        return f.get_page(url)
    except f.FetchError as e:
        raise KBError(str(e))


def _page_header(pg):
    meta = [f'来源：[{pg["title"]}]({pg["url"]})']
    if pg.get('path'):
        meta.append(f'位置：{pg["path"]}')
    if pg.get('version'):
        meta.append(f'页面版本：v{pg["version"]}（最后修改：{pg["updated_by"]} {pg["updated_at"]}）')
    elif pg.get('updated_at'):
        meta.append(f'最后修改：{pg["updated_at"]}')
    meta.append(f'抓取时间：{now()}')
    return meta


def fetch_url(url, start=0, max_chars=30000):
    """只读取不保存，给 AI 看原文、定位条目。"""
    pg = _page(url)
    md = pg['md']
    start = max(0, int(start or 0))
    part = md[start:start + max_chars]
    out = [f'# {pg["title"]}'] + [f'> {x}' for x in _page_header(pg)]
    out.append(f'\n（正文共 {len(md)} 字，本次第 {start}-{start + len(part)} 字）\n')
    out.append(part)
    if start + len(part) < len(md):
        out.append(f'\n…（未完，继续读用 start={start + len(part)}）')
    if pg['attachments']:
        out.append(f'\n## 附件（{len(pg["attachments"])}）')
        out += [f'- {a["name"]}' + (f'（{a["size"] // 1024} KB）' if a.get('size') else '') for a in pg['attachments']]
    if pg.get('embedded'):
        out.append(f'\n## 页面内嵌图片（{len(pg["embedded"])} 张，正文中以「嵌入图片N」标记；导入时 attachments 含 "embedded" 即可存为设计图）')
    if pg['children']:
        out.append(f'\n## 子页面（{len(pg["children"])}）')
        out += [f'- [{c["title"]}]({c["url"]})' for c in pg['children']]
    return '\n'.join(out)


def _save_snapshot(d, pg):
    sd = d / SRC_DIR
    sd.mkdir(exist_ok=True)
    name = safe_name(f'{pg["title"]}' + (f'-{pg["id"]}' if pg.get('id') else '')) + '.md'
    f = sd / name
    if f.exists() and f'({pg["url"]})' not in read_text(f)[:2000]:   # 同标题的另一个网页，别互相覆盖
        import hashlib
        f = sd / (f.stem + '-' + hashlib.sha1(pg['url'].encode()).hexdigest()[:6] + '.md')
    body = f'# {pg["title"]}（原文快照）\n\n' + '\n'.join(f'> {x}' for x in _page_header(pg)) + '\n\n' + pg['md'] + '\n'
    if f.exists():
        old = read_text(f)
        strip = lambda s: re.sub(r'> 抓取时间：.*\n', '', s)
        if strip(old) != strip(body):
            h = sd / HIST
            h.mkdir(exist_ok=True)
            shutil.move(str(f), str(h / f'{f.stem}.{datetime.now():%Y%m%d-%H%M%S}.md'))
    f.write_text(body, 'utf-8')
    return f


def _auto_notes(d, pg, stem, md):
    """原型图按所在章节 + 图注自动生成说明，便于检索；已有说明的不覆盖。md 为含「嵌入图片N」占位的原文。"""
    for n, (alt, ext, _) in enumerate(pg['embedded'], 1):
        img = d / '需求' / PROTO_DIR / f'{stem}-图{n:02d}.{ext}'
        side = img.with_name(img.name + NOTE_SUFFIX)
        if not img.exists() or side.exists():
            continue
        pos = md.find(f'](嵌入图片{n})')
        before = md[:pos] if pos >= 0 else ''
        heads = re.findall(r'^#+ (.+)$', before, re.M)
        tops = re.findall(r'^# (\d+(?:\.\d+)*\.? .+)$', before, re.M)  # 「# 5.8 xxx」这类编号章节
        where = [x.strip() for x in ([tops[-1]] if tops else []) + ([heads[-1]] if heads else [])]
        where = list(dict.fromkeys(where))
        text = f'出自《{pg["title"]}》' + (f'章节「{" › ".join(where)}」' if where else '')
        if alt:
            text += f'\n\n图注：{alt}'
        side.write_text(f'# 图片说明：{img.name}\n\n【原型图/参考图，仅用于理解交互逻辑，UI 以设计稿为准】\n{text}\n\n'
                        f'（自动生成；可让 AI 看图补充细节）\n', 'utf-8')


def import_url(iteration, url, category, item='', summary='', content='', attachments=None, filename=''):
    """把网页 / Confluence 页面（或其中某个条目）导入一期，并登记来源，便于人工核对。"""
    d = period_dir(iteration)
    if category not in CATS:
        raise KBError(f'分类只能是：{" / ".join(CATS)}')
    if not (summary or '').strip():
        raise KBError('请写一段简介（这份资料讲了什么、对应哪个条目），用户要据此核对。')
    pg = _page(url)
    pg['指纹'] = _refresh._fingerprint(pg)
    pg['导入参数'] = {'分类': category, '附件': attachments or [], '文件名': filename,
                   '整页': not (content or '').strip()}
    title = f'{pg["title"]}' + (f'-{item}' if item else '')
    files, saved = [], []
    doc_md = None  # 正文里图片引用相对「需求/」目录的版本
    want_all = attachments == 'all' or attachments == ['all']
    if pg.get('embedded') and (want_all or 'embedded' in (attachments or [])):
        import base64
        tmp = SYS / 'tmp'
        tmp.mkdir(exist_ok=True)
        stem = safe_name(pg['title'])
        raw = pg['md']
        doc_md = raw
        for n, (alt, ext, b64) in enumerate(pg['embedded'], 1):
            p = tmp / f'{stem}-图{n:02d}.{ext}'
            p.write_bytes(base64.b64decode(b64))
            add_material(d.name, p, '需求', f'原型图，来自 {pg["url"]}', sub=PROTO_DIR, reindex=False)
            ph = f'](嵌入图片{n})'
            doc_ref = f'{PROTO_DIR}/{p.name}' if category == '需求' else f'../需求/{PROTO_DIR}/{p.name}'
            pg['md'] = pg['md'].replace(ph, f'](../需求/{PROTO_DIR}/{p.name})')   # 快照在 来源快照/ 下
            doc_md = doc_md.replace(ph, f']({doc_ref})')
            content = (content or '').replace(ph, f']({doc_ref})')
            files.append(f'需求/{PROTO_DIR}/{p.name}')
        _auto_notes(d, pg, stem, raw)
        saved.append(f'页面内嵌图片 {len(pg["embedded"])} 张 → 需求/{PROTO_DIR}/{stem}-图01…（原型图，仅供参考；已按章节和图注自动写说明）')
        attachments = None if not want_all else attachments
    snap = _save_snapshot(d, pg)
    head = [f'# {title}', ''] + [f'> {x}' for x in _page_header(pg)]
    if item:
        head.append(f'> 条目：{item}')
    head += [f'> 简介：{summary.strip()}', f'> 原文快照：{SRC_DIR}/{snap.name}', '']
    body = content.strip() if (content or '').strip() else (doc_md or pg['md'])
    note = f'来自 {pg["url"]}'
    saved.insert(0, write_doc(d.name, category, filename or title, '\n'.join(head) + '\n' + body + '\n', note).split('\n')[0])
    fn = safe_name(filename or title)
    files.insert(0, f'{category}/{fn}' + ('' if Path(fn).suffix.lower() in DOC_EXT else '.md'))
    # 附件
    wanted = []
    if want_all:
        wanted = pg['attachments']
    elif attachments:
        names = set(attachments) - {'embedded'}
        wanted = [a for a in pg['attachments'] if a['name'] in names or a['url'] in names]
        missing = names - {a['name'] for a in wanted} - {a['url'] for a in wanted}
        wanted += [{'name': x, 'url': x} for x in missing if re.match(r'https?://', x)]
        missing = {x for x in missing if not re.match(r'https?://', x)}
        if missing:
            saved.append(f'未找到附件：{"、".join(missing)}')
    f = _fetch()
    tmp = SYS / 'tmp'
    tmp.mkdir(exist_ok=True)
    for a in wanted:
        try:
            name, data = f.download(a['url'])
        except f.FetchError as e:
            saved.append(f'附件下载失败 {a["name"]}：{e}')
            continue
        p = tmp / safe_name(a.get('name') or name)
        p.write_bytes(data)
        cat = guess_category(p)
        cat = category if cat == '其他资料' else cat
        saved.append(add_material(d.name, p, cat, f'附件，来自 {pg["url"]}').split('\n')[0])
        files.append(f'{cat}/{p.name}')
    sid, again = _register_source(d, pg, item, summary, files, f'{SRC_DIR}/{snap.name}')
    return (f'已{"重新" if again else ""}导入 {sid}：《{pg["title"]}》{item}\n来源：{pg["url"]}\n简介：{summary.strip()}\n'
            + '\n'.join(f'- {x}' for x in saved) + f'\n- 原文快照：{snap}\n'
            + '请用户在网页这一期「资料 → 来源核对」里核对后标记。')


def _register_source(d, pg, item, summary, files, snapshot, kind='资料'):
    m = load_meta(d)
    srcs = m.setdefault('来源', [])
    entry = {'类型': kind, '标题': pg['title'], '地址': pg['url'], '条目': item, '简介': summary.strip(),
             '页面版本': pg.get('version'), '最后修改': f'{pg.get("updated_by", "")} {pg.get("updated_at", "")}'.strip(),
             '抓取时间': now(), '文件': files, '快照': snapshot, '核对': '待核对', '核对备注': '',
             '指纹': pg.get('指纹'), '导入参数': pg.get('导入参数'), '检查时间': now(), '检查结果': '已导入'}
    old = next((x for x in srcs if x['地址'] == pg['url'] and x.get('条目', '') == item), None)
    if old:
        sid = old['编号']
        if old.pop('待更新', None):
            for c in reversed(old.get('变更记录') or []):
                if c.get('处理') == '条目待更新':
                    c.update(处理='已更新', 更新时间=now())
                    break
        old.update(entry)
    else:
        sid = f'S{len(srcs) + 1:03d}'
        srcs.append({'编号': sid, **entry})
    save_meta(d, m)
    log(d, '重新导入' if old else '导入来源', f'{sid}《{pg["title"]}》{item} → {"、".join(files)} ｜ {pg["url"]}')
    index_docs()
    return sid, bool(old)


def import_design(iteration, url, item='', summary=''):
    """导入设计稿（要实现的产品图）：Figma 逐个画板导出 PNG + 设计规格（文字、字号、颜色、尺寸）；蓝湖暂只登记链接。"""
    d = period_dir(iteration)
    f = _fetch()
    if not f.is_design_url(url):
        raise KBError('这不是 Figma / 蓝湖 的设计稿链接；普通网页用 kb_import_url')
    host = urlparse(url).hostname or ''
    if 'figma.com' not in host:
        pg = {'title': f'蓝湖设计稿{("-" + item) if item else ""}', 'url': url}
        doc = (f'# {pg["title"]}\n\n> 来源：[{url}]({url})\n> 登记时间：{now()}\n'
               + (f'> 条目：{item}\n' if item else '') + f'> 简介：{summary or "蓝湖设计稿"}\n\n'
               '蓝湖没有开放接口，暂不能自动抓取。请在蓝湖里「下载全部画板」或导出切图，'
               '把文件拖进网页这一期的「设计图」（或放进收件箱让 Claude 归档）。\n')
        name = safe_name(pg['title']) + '.md'
        write_doc(d.name, '设计图', name, doc, f'蓝湖链接 {url}')
        sid, _ = _register_source(d, pg, item, summary or '蓝湖设计稿（仅登记链接，待手动导出画板）',
                                  [f'设计图/{name}'], '', kind='设计稿')
        return f'已登记 {sid}（蓝湖，仅链接）：{url}\n蓝湖暂不能自动抓取，请导出画板后拖进网页「设计图」。'
    try:
        ds = f.figma_design(url)
    except f.FetchError as e:
        raise KBError(str(e))
    folder = safe_name(ds['title'] + (f'-{ds["root_name"]}' if ds['node'] and ds['root_name'] else ''))
    tmp = SYS / 'tmp' / uuid_hex()
    tmp.mkdir(parents=True)
    files, failed = [], []
    spec = [f'# 设计规格：{ds["title"]}' + (f' › {ds["root_name"]}' if ds['node'] else ''), '',
            f'> 来源：[Figma]({url})', f'> 文件版本：{ds.get("version")}（最后修改 {ds.get("updated_at")}）',
            f'> 抓取时间：{now()}'] + ([f'> 条目：{item}'] if item else []) + [
            f'> 画板：{len(ds["frames"])} 个' + (f'（共 {ds["total_frames"]} 个，只取前 {len(ds["frames"])} 个）'
                                               if ds['total_frames'] > len(ds['frames']) else ''),
            '> 【这是要实现的设计稿，UI 以此为准；尺寸为设计稿像素，导出图为 2 倍图】', '']
    used = set()
    for i, fr in enumerate(ds['frames'], 1):
        base = safe_name(f'{i:02d}-{fr["name"]}')[:80]
        while base in used:
            base += '_'
        used.add(base)
        img_url = ds['images'].get(fr['id'])
        img_name = f'{base}.png'
        if img_url:
            try:
                _, data = f.download(img_url)
                (tmp / img_name).write_bytes(data)
                add_material(d.name, tmp / img_name, '设计图', f'Figma 画板 {fr["name"]}', sub=folder, reindex=False)
                files.append(f'设计图/{folder}/{img_name}')
            except f.FetchError as e:
                failed.append(f'{fr["name"]}：{e}')
                img_name = ''
        else:
            failed.append(f'{fr["name"]}：Figma 没有返回图片')
            img_name = ''
        lines = [f'## {i:02d}. {fr["name"]}', f'- 尺寸：{fr["w"]} × {fr["h"]}　节点：{fr["id"]}']
        if img_name:
            lines.append(f'- 图：{img_name}')
        if fr['colors']:
            lines.append('- 主要颜色：' + '、'.join(f'{c}（{n}）' for c, n in fr['colors']))
        if fr['texts']:
            lines += ['', '| 文案 | 字体 | 字号 | 字重 | 颜色 |', '|---|---|---|---|---|']
            for t in fr['texts'][:120]:
                txt = t['text'].replace('\n', ' / ').replace('|', '\\|')[:80]
                lines.append(f'| {txt} | {t["font"]} | {t["size"] or ""} | {t["weight"] or ""} | {t["color"]} |')
        spec += lines + ['']
        if img_name:
            note = (f'【设计稿，UI 以此为准】Figma《{ds["title"]}》画板「{fr["name"]}」，{fr["w"]}×{fr["h"]}\n\n文案：'
                    + '；'.join(t['text'].replace('\n', ' ') for t in fr['texts'][:40]))
            side = d / '设计图' / folder / (img_name + NOTE_SUFFIX)
            side.write_text(f'# 图片说明：{img_name}\n\n{note}\n', 'utf-8')
    if failed:
        spec += ['## 导出失败', ''] + [f'- {x}' for x in failed]
    spec_name = '设计规格.md'
    (tmp / spec_name).write_text('\n'.join(spec) + '\n', 'utf-8')
    add_material(d.name, tmp / spec_name, '设计图', f'Figma 设计规格 {url}', sub=folder, reindex=False)
    files.insert(0, f'设计图/{folder}/{spec_name}')
    shutil.rmtree(tmp, ignore_errors=True)
    pg = {'title': ds['title'] + (f' › {ds["root_name"]}' if ds['node'] else ''), 'url': url,
          'version': ds.get('version'), 'updated_at': ds.get('updated_at', '')}
    summ = summary.strip() or f'Figma 设计稿 {len(ds["frames"])} 个画板（含设计规格）'
    sid, again = _register_source(d, pg, item, summ, files, f'设计图/{folder}/{spec_name}', kind='设计稿')
    return (f'已{"重新" if again else ""}导入设计稿 {sid}：《{pg["title"]}》\n'
            f'- 画板 {len(ds["frames"])} 个 → 设计图/{folder}/\n- 设计规格 → 设计图/{folder}/{spec_name}'
            + (f'\n- 导出失败 {len(failed)} 个：' + '；'.join(failed[:5]) if failed else '')
            + '\n请用户在网页这一期「资料 → 来源核对」里核对。')


def verify_source(iteration, sid, status, note=''):
    d = period_dir(iteration)
    if status not in ('待核对', '已核对', '有问题'):
        raise KBError('核对状态只能是：待核对 / 已核对 / 有问题')
    m = load_meta(d)
    for s in m.get('来源', []):
        if s['编号'] == sid:
            s['核对'], s['核对备注'], s['核对时间'] = status, note, now()
            save_meta(d, m)
            log(d, '核对来源', f'{sid}《{s["标题"]}》{s.get("条目", "")} → {status}' + (f'（{note}）' if note else ''))
            return f'{sid} → {status}'
    raise KBError(f'没有这条来源：{sid}')
