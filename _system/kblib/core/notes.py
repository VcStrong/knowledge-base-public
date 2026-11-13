# From 大大王.DT
"""文字资料（产品说的几句话、分支、链接…）。"""
import re
from urllib.parse import urlparse
from kblib.core.common import CATS, DESIGN_HOSTS, HIST, NOTE_SUFFIX, KBError, now
from kblib.core.periods import load_meta, log, period_dir, save_meta
from kblib import lazy
_search = lazy('kblib.core.search')      # 上层模块：用到时才 import（不形成循环）


NOTE_KINDS = ['文字', '链接', '分支', '其他']
NOTES_FILE = '文字资料.md'
URL_RE = re.compile(r'https?://[^\s<>"\'）)】」，。]+')
BRANCH_RE = re.compile(r'(?<![\w/.-])[A-Za-z][\w.-]*/[\w./-]*\w')


def notes_of(d, cat=None, m=None):
    ns = (m or load_meta(d)).get('文字资料') or []
    return [n for n in ns if not cat or n['分类'] == cat]


def _guess_kind(content, url):
    t = content.strip()
    if re.search(r'分支|branch', t, re.I) or re.fullmatch(r'(feature|feat|release|hotfix|bugfix|fix|dev)/\S+', t):
        return '分支'
    if url or (URL_RE.search(t) and len(URL_RE.sub('', t).strip()) < 40):
        return '链接'
    return '文字'


def note_title(n):
    if n.get('标题'):
        return n['标题']
    if n['类型'] == '分支':  # 标题直接用分支名
        b = BRANCH_RE.search(URL_RE.sub(' ', n.get('内容') or ''))
        if b:
            return b.group(0)
    if not n.get('内容'):
        return n.get('链接') or ''
    return re.sub(r'\s+', ' ', n['内容'])[:40]


def note_md(n):
    out = [f'## {n["编号"]} ［{n["类型"]}］{note_title(n)}', '',
           f'- 记录时间：{n["时间"]}' + (f'（更新 {n["更新时间"]}）' if n.get('更新时间') else '')]
    if n.get('来自'):
        out.append(f'- 来自：{n["来自"]}')
    if n.get('链接'):
        out.append(f'- 链接：{n["链接"]}')
    if (n.get('内容') or '').strip():
        out += ['', n['内容'].strip()]
    return '\n'.join(out)


def _sync_notes(d, m):
    for c in CATS:
        ns = notes_of(d, c, m)
        f = d / c / NOTES_FILE
        if not ns:
            f.unlink(missing_ok=True)
            continue
        f.parent.mkdir(exist_ok=True)
        f.write_text(f'# {d.name} · {c} · 文字资料\n\n> 自动生成，请勿手改（用网页、kb note 或 kb_add_note / kb_update_note 修改）。\n\n'
                     + '\n\n'.join(note_md(n) for n in ns) + '\n', 'utf-8')
    _search.index_docs()


def _note_hint(n):
    if n['类型'] != '链接' or not n.get('链接'):
        return ''
    host = urlparse(n['链接']).hostname or ''
    if any(h in host for h in DESIGN_HOSTS):
        return '\n提示：这是设计稿链接，确认是要实现的设计稿后可用 kb_import_design 导入画板。'
    return '\n提示：链接已登记。能访问时可 kb_fetch_url 读原文、kb_import_url 正式导入；需要登录则请用户 kb login。'


def _note_fields(category, kind, content, url):
    if category not in CATS:
        raise KBError(f'分类只能是：{" / ".join(CATS)}')
    if not content and not url:
        raise KBError('内容和链接至少填一项')
    kind = kind or _guess_kind(content, url)
    if kind not in NOTE_KINDS:
        raise KBError(f'类型只能是：{" / ".join(NOTE_KINDS)}')
    if kind == '链接' and not url:
        u = URL_RE.search(content)
        url = u.group(0) if u else ''
    return kind, url


def add_note(period, content='', category='', kind='', title='', url='', source=''):
    d = period_dir(period)
    content, url = (content or '').strip(), (url or '').strip()
    kind = kind or (_guess_kind(content, url) if content or url else '')
    category = category or ('需求' if kind == '文字' else '其他资料')  # 未指定时：口述内容多半是需求
    kind, url = _note_fields(category, kind, content, url)
    m = load_meta(d)
    ns = m.setdefault('文字资料', [])
    seq = m['文字资料序号'] = max([m.get('文字资料序号', 0)] + [int(n['编号'][1:]) for n in ns]) + 1  # 删除后编号不复用
    nid = f'T{seq:03d}'
    n = {'编号': nid, '类型': kind, '分类': category, '标题': (title or '').strip(), '内容': content,
         '链接': url, '来自': (source or '').strip(), '时间': now()}
    ns.append(n)
    save_meta(d, m)
    log(d, '文字资料', f'{nid} ［{kind}］{category}：{note_title(n)}')
    _sync_notes(d, m)
    return f'已记下 {nid}（{category} · {kind}）：{note_title(n)}\n文件：{d / category / NOTES_FILE}' + _note_hint(n)


def update_note(period, nid, delete=False, **fields):
    """fields 可含 内容/链接/标题/来自/类型/分类，传 None 表示不改。"""
    d = period_dir(period)
    m = load_meta(d)
    ns = m.get('文字资料') or []
    n = next((x for x in ns if x['编号'] == nid), None)
    if not n:
        raise KBError(f'没有这条文字资料：{nid}')
    if delete:
        ns.remove(n)
        save_meta(d, m)
        log(d, '删除文字资料', f'{nid} ［{n["类型"]}］{n["分类"]}：{note_title(n)}')
        _sync_notes(d, m)
        return f'已删除 {nid}'
    new = {**n, **{k: (v or '').strip() for k, v in fields.items() if v is not None}}
    new['类型'], new['链接'] = _note_fields(new['分类'], new['类型'], new['内容'], new['链接'])
    if new == n:
        return f'{nid} 没有变化'
    n.update(new, 更新时间=now())
    save_meta(d, m)
    log(d, '修改文字资料', f'{nid} ［{n["类型"]}］{n["分类"]}：{note_title(n)}')
    _sync_notes(d, m)
    return f'已更新 {nid}（{n["分类"]} · {n["类型"]}）：{note_title(n)}' + _note_hint(n)


def _materials(d):
    """这一期各分类下的资料文件（不含历史版本、文字资料清单、图片说明）。"""
    res = {}
    for c in CATS:
        items = []
        for p in sorted((d / c).iterdir()) if (d / c).exists() else []:
            if p.name in (HIST, NOTES_FILE) or p.name.startswith('.') or p.name.endswith(NOTE_SUFFIX):
                continue
            items.append(p)
        res[c] = items
    return res
