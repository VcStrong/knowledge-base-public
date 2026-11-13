# From 大大王.DT
"""更正给错的链接。"""
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from kblib.core.common import CATS, DEV_OK, HIST, KBError, read_text
from kblib.core.periods import load_meta, log, period_dir, save_meta
from kblib.core.notes import NOTES_FILE, URL_RE, _sync_notes
from kblib.ai.flows import flow_text
from kblib.ai.devsession import DEV_DIR, session_flow
from kblib.sources.urlimport import _fetch, import_design, import_url
from kblib.sources.refresh import _notice, _set_src, _src_params


def _urls(text):
    """文本里的网址；「[地址](地址)」这种 Markdown 链接拆成两个，去掉末尾标点。"""
    out = []
    for u in URL_RE.findall(text or ''):
        for x in re.split(r'\]\(|[\[\]]', u):
            x = x.rstrip('.,;:')
            if re.match(r'https?://', x) and '/xxx' not in x and 'example.com' not in x:   # SDD 模板里的示例链接
                out.append(x)
    return out


def _link_key(url):
    """同一个链接的不同写法算一个：Figma 看文件 + 节点，其他去掉 # 和末尾斜杠。"""
    u = urlparse(url)
    if 'figma.com' in (u.hostname or ''):
        try:
            k, node = _fetch().parse_figma_url(url)
            return f'figma:{k}:{node}'
        except Exception:
            pass
    return url.split('#')[0].rstrip('/')


def _link_files(d, m):
    """这一期里会写到链接的文本：各分类下的文档（不含历史版本、原文快照）和 SDD 的 sdd-start.md。"""
    fs = [p for c in CATS if (d / c).exists() for p in (d / c).rglob('*.md')
          if HIST not in p.parts and p.name != NOTES_FILE]
    cfg = session_flow(m).get('流程配置文件')
    if m.get('SDD目录') and cfg and (Path(m['SDD目录']) / cfg).is_file():
        fs.append(Path(m['SDD目录']) / cfg)
    return fs


def period_links(period):
    """这一期出现过的所有链接及出处，给「更正链接」选。"""
    d = period_dir(period)
    m = load_meta(d)
    out = {}

    def add(url, where):
        x = out.setdefault(_link_key(url), {'链接': url, '出处': []})
        if where not in x['出处']:
            x['出处'].append(where)
    for s in m.get('来源') or []:
        if not s.get('作废'):
            add(s['地址'], f'来源 {s["编号"]}')
    for n in m.get('文字资料') or []:
        for u in _urls(f'{n.get("链接") or ""} {n.get("内容") or ""}'):
            add(u, f'文字资料 {n["编号"]}')
    for f in _link_files(d, m):
        for u in _urls(read_text(f)):
            add(u, f'流程配置 {f.name}' if d not in f.parents else str(f.relative_to(d)))
    return sorted(out.values(), key=lambda x: ('figma' not in x['链接'], x['链接']))


def design_conflicts(period, text):
    """新加的设计稿链接之外，这一期里还有哪些别的设计稿链接（可能是要被替换的旧链接）。"""
    f = _fetch()
    new = [u for u in _urls(text) if f.is_design_url(u)]
    if not new:
        return '', []
    keys = {_link_key(u) for u in new}
    return new[0], [x['链接'] for x in period_links(period) if f.is_design_url(x['链接']) and _link_key(x['链接']) not in keys]


def _conflict_hint(period, text):
    new, olds = design_conflicts(period, text)
    if not olds:
        return ''
    return ('\n注意：这一期还有别的设计稿链接：' + '、'.join(olds)
            + '\n如果新链接是用来替换旧的，问用户确认后用 kb_fix_link 把旧链接更正为新链接（文档、流程配置文件会一起改）。')


def fix_link(period, old, new, reason='', by='Claude'):
    """把这一期里给错的链接换成正确的：文档、文字资料、来源、流程配置文件一起改，旧内容进历史版本，并通知开发会话。"""
    d = period_dir(period)
    m = load_meta(d)
    old, new = (old or '').strip(), (new or '').strip()
    if not re.match(r'https?://', new):
        raise KBError('新链接不是有效网址')
    key = _link_key(old)
    if key == _link_key(new):
        raise KBError('新旧链接指向同一个地址；如果是对方改了内容，用「检查更新」重新抓取')
    hit = lambda u: _link_key(u) == key
    done, todo = [], []
    ts = f'{datetime.now():%Y%m%d-%H%M%S}'
    # 1. 文档和流程配置文件：每种写法都替换，旧版留底
    for f in _link_files(d, m):
        text = read_text(f)
        vs = {u for u in _urls(text) if hit(u)}
        if not vs:
            continue
        new_text = text
        for v in sorted(vs, key=len, reverse=True):
            new_text = new_text.replace(v, new)
        if d in f.parents:
            h = f.parent / HIST
            h.mkdir(exist_ok=True)
            shutil.copy2(f, h / f'{f.stem}.{ts}{f.suffix}')
            done.append(f'{f.relative_to(d)}（旧版进 {HIST}/）')
        else:   # 流程配置文件在仓库里，备份放回这一期
            (d / DEV_DIR).mkdir(exist_ok=True)
            shutil.copy2(f, d / DEV_DIR / f'{f.stem}.{ts}{f.suffix}')
            done.append(f'流程配置 {f}（旧版备份到 {DEV_DIR}/{f.stem}.{ts}{f.suffix}）')
        f.write_text(new_text, 'utf-8')
    # 2. 文字资料
    m = load_meta(d)
    for n in m.get('文字资料') or []:
        changed = False
        for k in ('链接', '内容'):
            for u in _urls(n.get(k) or ''):
                if hit(u):
                    n[k] = n[k].replace(u, new)
                    changed = True
        if changed:
            done.append(f'文字资料 {n["编号"]}')
    save_meta(d, m)
    _sync_notes(d, m)
    # 3. 来源：旧的作废（文件进历史版本），按新链接重新导入
    for s in [x for x in load_meta(d).get('来源') or [] if not x.get('作废') and hit(x['地址'])]:
        for rel in s.get('文件') or []:
            p = d / rel
            if p.exists():
                h = p.parent / HIST
                h.mkdir(exist_ok=True)
                shutil.move(str(p), str(h / f'{p.stem}.{ts}.作废{p.suffix}'))
        _set_src(d, s['编号'], 作废=True, 核对='有问题', 核对备注=f'链接有误，已换成 {new}' + (f'（{reason}）' if reason else ''))
        done.append(f'来源 {s["编号"]} 作废，文件进历史版本')
        p = _src_params(d, s)
        try:
            if s.get('类型') == '设计稿':
                r = import_design(d.name, new, s.get('条目', ''), s.get('简介', ''))
            elif p['整页']:
                r = import_url(d.name, new, p['分类'], s.get('条目', ''), s.get('简介', ''), '', p.get('附件') or None,
                               p.get('文件名', ''))
            else:
                r = None
                todo.append(f'{s["编号"]} 只导入了条目「{s.get("条目")}」：用 kb_fetch_url 读新链接，再 kb_import_url 导入该条目')
            if r:
                done.append(r.split('\n')[0])
        except KBError as e:
            todo.append(f'按新链接重新导入失败：{e}')
    # 4. 新链接是设计稿、之前又没导入过：试着导入
    if _fetch().is_design_url(new) and not any(not x.get('作废') and x['地址'] == new for x in load_meta(d).get('来源') or []):
        try:
            done.append(import_design(d.name, new, '', reason or '更正后的设计稿').split('\n')[0])
        except KBError as e:
            todo.append(f'新设计稿还没导入（{e}）')
    if not done:
        raise KBError(f'这一期里没有找到这个链接：{old}')
    log(d, '更正链接', f'{old} → {new}' + (f'；原因：{reason}' if reason else '') + f'（{by}）')
    m = load_meta(d)
    if m.get('SDD目录'):
        tip = (flow_text(session_flow(m), '需求变更提示', 期名=d.name, 文档目录=m['SDD目录'])
               or '先 kb_dev_prepare 同步资料副本，影响已写代码的用 kb_ask 确认')
    else:
        tip = '开发开始时 kb_dev_prepare 会带上新链接'
    _notice(d, f'链接更正：{old} → {new}' + (f'（{reason}）' if reason else '') + f'。{tip}')
    return (f'已把「{d.name}」里的链接更正为 {new}：\n' + '\n'.join(f'- {x}' for x in done)
            + (('\n还需处理：\n' + '\n'.join(f'- {x}' for x in todo)) if todo else '')
            + (f'\n开发会话会收到提醒：{tip}' if m.get('状态') in DEV_OK or m.get('SDD目录') else ''))
