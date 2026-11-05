#!/usr/bin/env python3
# From 大大王.DT
"""本地知识库：按「期」管理需求 / 设计图 / 接口文档 / 其他资料，索引本地代码仓库。

同一份代码提供两种入口：
  - 命令行：kb new / add / search / approve ...（给人用）
  - MCP（stdio）：kb serve（给 Claude Code 用）

开发闸门：一期的状态只有人能改成「已批准开发」（kb approve，必须在真实终端里敲）；
AI 只有在「已批准开发 / 开发中」时才能通过 kb_dev_package 拿到开发包。
"""
import argparse
import filecmp
import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import signal
import subprocess
import sys
import threading
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import devlock

ROOT = Path(os.environ.get('KB_ROOT') or Path(__file__).resolve().parent.parent)
SYS = ROOT / '_system'
PERIODS = ROOT / '期'
INBOX = ROOT / '收件箱'
REPOS_FILE = ROOT / '代码仓库.json'
BASE = ROOT / '基础'
DB = SYS / 'index.db'

CATS = ['需求', '设计图', '接口文档', '其他资料']
STATUSES = ['收集中', '已批准开发', '开发中', '已完成', '已暂停']
DEV_OK = ('已批准开发', '开发中')
HIST = '_历史版本'
PROTO_DIR = '原型图'   # 需求/原型图：PRD 里的原型图、参考图，只用于理解交互；UI 以「设计图」里的设计稿为准
DESIGN_HOSTS = ('figma.com', 'lanhuapp.com', 'lanhu.com')
NOTE_SUFFIX = '.说明.md'

IMG_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.heic', '.tif', '.tiff'}
TEXT_EXT = {'.md', '.txt', '.json', '.yaml', '.yml', '.csv', '.tsv', '.sql', '.xml', '.proto',
            '.log', '.ini', '.properties', '.svg', '.har'}
OFFICE_EXT = {'.docx', '.doc', '.rtf', '.odt', '.webarchive'}
DOC_EXT = TEXT_EXT | OFFICE_EXT | IMG_EXT | {'.html', '.htm', '.pdf', '.xlsx', '.pptx'}
CODE_EXT = {'.java', '.kt', '.kts', '.gradle', '.xml', '.json', '.md', '.py', '.js', '.ts', '.tsx',
            '.jsx', '.vue', '.swift', '.m', '.mm', '.h', '.c', '.cc', '.cpp', '.hpp', '.go', '.rs',
            '.proto', '.sql', '.yaml', '.yml', '.properties', '.sh', '.dart', '.cmake', '.toml',
            '.html', '.css', '.scss', '.aidl', '.pro', '.cfg', '.txt'}
SKIP_DIRS = {'.git', 'build', '.gradle', '.idea', 'node_modules', 'dist', 'out', 'Pods', '.cxx',
             'intermediates', '.venv', 'venv', '__pycache__', 'target', '.next', 'DerivedData',
             '.dart_tool', 'generated', '.externalNativeBuild'}
MAX_CODE_BYTES = 400_000
CHUNK_CHARS = 1500


class KBError(Exception):
    pass


class KBNeed(KBError):
    """需要用户在网页上选一下（开发仓库、分支）：data 交给网页弹窗，文字说明给 AI / 命令行。"""
    def __init__(self, msg, data):
        super().__init__(msg)
        self.data = data


def uuid_hex():
    return uuid.uuid4().hex


def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M')


def safe_name(s):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', '-', (s or '').strip()).strip('.- ')
    if not s:
        raise KBError('名称不能为空')
    return s


# ---------------------------------------------------------------- 期 / 记录

def init():
    for p in (SYS, PERIODS, INBOX):
        p.mkdir(parents=True, exist_ok=True)
    if not REPOS_FILE.exists():
        REPOS_FILE.write_text('{}', 'utf-8')
    db().close()


def period_names():
    if not PERIODS.exists():
        return []
    ds = [p for p in PERIODS.iterdir() if p.is_dir()]
    return [p.name for p in sorted(ds, key=lambda p: load_meta(p).get('创建时间', ''))]


def period_dir(name):
    if not name:
        raise KBError('请指定期名')
    d = PERIODS / safe_name(name)
    if d.is_dir():
        return d
    cands = [n for n in period_names() if name in n]
    if len(cands) == 1:
        return PERIODS / cands[0]
    if not cands:
        raise KBError(f'没有这一期：{name}。现有：{"、".join(period_names()) or "（空）"}')
    raise KBError(f'「{name}」匹配到多期：{"、".join(cands)}，请写全名')


def load_meta(d):
    f = d / '期信息.json'
    if f.exists():
        return json.loads(f.read_text('utf-8'))
    return {'名称': d.name, '说明': '', '状态': '收集中', '创建时间': now(), '关联仓库': [], '状态历史': []}


def save_meta(d, m):
    m['更新时间'] = now()
    (d / '期信息.json').write_text(json.dumps(m, ensure_ascii=False, indent=2), 'utf-8')


def log(d, action, content):
    f = d / '记录.md'
    if not f.exists():
        f.write_text(f'# {d.name} · 记录\n\n> 知识库自动追加：本期所有材料变动、状态变化、开发中的关键决定。\n\n', 'utf-8')
    with f.open('a', encoding='utf-8') as fp:
        fp.write(f'- {now()} ｜ {action} ｜ {content}\n')


def create_period(name, summary=''):
    init()
    d = PERIODS / safe_name(name)
    if d.exists():
        raise KBError(f'已存在：{d.name}')
    for c in CATS:
        (d / c).mkdir(parents=True)
    save_meta(d, {'名称': d.name, '说明': summary, '状态': '收集中', '创建时间': now(), '关联仓库': [],
                  '状态历史': [{'时间': now(), '状态': '收集中', '备注': '创建'}]})
    log(d, '创建', '说明：' + (summary or '无'))
    return f'已创建一期：{d.name}\n目录：{d}\n状态：收集中（开发需你本人运行 kb approve "{d.name}"）'


def guess_category(p: Path):
    n = p.name.lower()
    ext = p.suffix.lower()
    word = lambda w: re.search(rf'(^|[^a-z]){w}([^a-z]|$)', n)
    if re.search(r'接口|swagger|openapi|postman|协议|字段|错误码', n) or word('api'):
        return '接口文档'
    if ext == '.rp' or re.search(r'原型|axure|交互稿|线框', n):
        return '需求'  # 原型属于需求，设计稿才进设计图
    if p.is_dir() and ((p / 'resources').exists() or (p / 'start.html').exists()):
        return '需求'  # Axure 导出目录
    if (ext in IMG_EXT or ext in {'.fig', '.sketch', '.xd', '.psd'}
            or re.search(r'设计|视觉|切图|标注|高保真|figma|蓝湖|lanhu', n) or word('ui')):
        return '设计图'
    if re.search(r'需求|prd|功能|产品|story', n):
        return '需求'
    return '其他资料'


def _same(a: Path, b: Path):
    if a.is_file() and b.is_file():
        return filecmp.cmp(a, b, shallow=False)
    return False


def add_material(period, src, category=None, note='', sub='', reindex=True):
    d = period_dir(period)
    src = Path(src).expanduser().resolve()
    if not src.exists():
        raise KBError(f'文件不存在：{src}')
    if src == d or d in src.parents:
        raise KBError(f'{src} 已经在这一期里了')
    if src.name == NOTES_FILE:
        raise KBError(f'「{NOTES_FILE}」是文字资料自动生成的文件名，请改个文件名再放入')
    cat = category or guess_category(src)
    if cat not in CATS:
        raise KBError(f'分类只能是：{" / ".join(CATS)}')
    folder = d / cat / sub if sub else d / cat
    folder.mkdir(parents=True, exist_ok=True)
    rel = f'{cat}/{sub}/' if sub else f'{cat}/'
    dest = folder / src.name
    move = INBOX.resolve() in src.parents or SYS.resolve() in src.parents
    extra = ''
    if dest.exists():
        if _same(src, dest):
            if move:
                src.unlink()
            return f'{rel}{src.name} 内容相同，未变动'
        h = folder / HIST
        h.mkdir(exist_ok=True)
        old = h / f'{dest.stem}.{datetime.now():%Y%m%d-%H%M%S}{dest.suffix}'
        shutil.move(str(dest), str(old))
        extra = f'，旧版移至 {rel}{HIST}/{old.name}'
    if move:
        shutil.move(str(src), str(dest))
    elif src.is_dir():
        shutil.copytree(src, dest)
    else:
        shutil.copy2(src, dest)
    action = '更新材料' if extra else '新增材料'
    log(d, action, f'{rel}{src.name}{extra}' + (f'（{note}）' if note else ''))
    stats = index_docs() if reindex else ''
    hint = ''
    if cat == '设计图' and not sub and dest.suffix.lower() in IMG_EXT:
        hint = f'\n提示：图片还没有文字说明，可用 Read 看图后 kb_annotate_image 补说明，便于检索。'
    return f'{action}：{d.name}/{rel}{src.name}{extra}\n路径：{dest}\n{stats}{hint}'


def write_doc(period, category, filename, content, note=''):
    period_dir(period)
    if category not in CATS:
        raise KBError(f'分类只能是：{" / ".join(CATS)}')
    name = safe_name(filename)
    if Path(name).suffix.lower() not in DOC_EXT:  # 「4.32」「v1.0」这类不是扩展名
        name += '.md'
    tmp = SYS / 'tmp'
    tmp.mkdir(exist_ok=True)
    f = tmp / name
    f.write_text(content, 'utf-8')
    return add_material(period, f, category, note)


def annotate_image(path, description):
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise KBError(f'文件不存在：{p}')
    if p.suffix.lower() not in IMG_EXT:
        raise KBError('只能给图片写说明')
    side = p.with_name(p.name + NOTE_SUFFIX)
    side.write_text(f'# 图片说明：{p.name}\n\n{description.strip()}\n', 'utf-8')
    try:
        rel = p.relative_to(PERIODS.resolve())
        log(PERIODS / rel.parts[0], '图片说明', '/'.join(rel.parts[1:]))
    except ValueError:
        pass
    index_docs()
    return f'已保存说明：{side}'


def set_status(period, status, note='', by_human=False):
    d = period_dir(period)
    m = load_meta(d)
    cur = m.get('状态', '收集中')
    if status not in STATUSES:
        raise KBError(f'状态只能是：{" / ".join(STATUSES)}')
    if not by_human:
        if status == '已批准开发':
            raise KBError('「已批准开发」只能由用户本人在终端运行 kb approve 设置，AI 不能代为批准。')
        allowed = {'开发中': ('已批准开发', '开发中'), '已完成': ('开发中',)}
        if status in allowed and cur not in allowed[status]:
            raise KBError(f'当前状态是「{cur}」，不能直接改为「{status}」。')
    m['状态'] = status
    m.setdefault('状态历史', []).append({'时间': now(), '状态': status, '备注': note,
                                       '操作人': '用户' if by_human else 'AI'})
    save_meta(d, m)
    log(d, '状态', f'{cur} → {status}' + (f'（{note}）' if note else '') + ('' if by_human else '［AI］'))
    msg = f'{d.name}：{cur} → {status}'
    if status == '已完成' and cur != '已完成':
        root = m.get('开发仓库') or ''
        branch = _git(Path(root), 'branch', '--show-current').stdout.strip() if root and Path(root).is_dir() else ''
        plug = run_plugins('开发完成', d, root, branch, m.get('SDD目录', ''))
        if plug:
            msg += f'\n\n【开发完成时已运行的插件】\n{plug}'
            if '个文件改动' in plug:
                msg += '\n插件改动了仓库里的文件：请检查后按仓库惯例提交（如单独一个提交）。'
    return msg


def add_log(period, note):
    d = period_dir(period)
    log(d, '记录', note)
    return f'已记录到 {d.name}/记录.md'


# ---------------------------------------------------------------- 文字资料（不是文件的资料）
# 产品随口说的几句话、要开发的分支、别的小组给的文档地址……不必是能一步到位的原料。
# 真源在 期信息.json 的「文字资料」；每个分类下自动生成 文字资料.md 供检索和开发包使用。

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
    index_docs()


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


# ---------------------------------------------------------------- 代码仓库

def load_repos():
    return json.loads(REPOS_FILE.read_text('utf-8')) if REPOS_FILE.exists() else {}


def add_repo(path, name=None):
    init()
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        raise KBError(f'目录不存在：{p}')
    name = safe_name(name or p.name)
    repos = load_repos()
    repos[name] = {'路径': str(p), '加入时间': now()}
    REPOS_FILE.write_text(json.dumps(repos, ensure_ascii=False, indent=2), 'utf-8')
    return f'已登记代码仓库：{name} → {p}\n' + index_repo(name)


def link_repo(period, repo):
    d = period_dir(period)
    if repo not in load_repos():
        raise KBError(f'没有登记这个仓库：{repo}。已登记：{"、".join(load_repos()) or "（空）"}')
    m = load_meta(d)
    if repo not in m.setdefault('关联仓库', []):
        m['关联仓库'].append(repo)
        save_meta(d, m)
        log(d, '关联仓库', repo)
    return f'{d.name} 已关联仓库：{"、".join(m["关联仓库"])}'


def repo_files(root: Path):
    if (root / '.git').exists():
        try:
            out = subprocess.run(['git', '-C', str(root), 'ls-files', '-z', '--recurse-submodules'],
                                 capture_output=True, timeout=120, check=True).stdout
            for rel in out.decode('utf-8', 'replace').split('\0'):
                if rel:
                    yield root / rel
            return
        except Exception:
            pass
    for dp, dns, fns in os.walk(root):
        dns[:] = [x for x in dns if x not in SKIP_DIRS and not x.startswith('.')]
        for fn in fns:
            yield Path(dp) / fn


def code_wanted(p: Path):
    if p.suffix.lower() not in CODE_EXT:
        return False
    if any(part in SKIP_DIRS for part in p.parts):
        return False
    if p.parent.name.startswith('values-') and p.parent.name != 'values-night':
        return False  # 多语言翻译，重复噪音
    return True


# ---------------------------------------------------------------- 文本提取

def read_text(p: Path):
    b = p.read_bytes()
    for enc in ('utf-8', 'gb18030'):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode('utf-8', 'replace')


def html_text(s):
    s = re.sub(r'(?is)<(script|style|noscript)\b.*?</\1>', ' ', s)
    s = re.sub(r'(?i)<br\s*/?>|</(p|div|tr|li|h[1-6]|table|section)>', '\n', s)
    s = html.unescape(re.sub(r'<[^>]+>', ' ', s))
    s = re.sub(r'[ \t ]+', ' ', s)
    return re.sub(r'\n\s*\n+', '\n\n', s).strip()


def xml_texts(data, tag):
    return [t.text or '' for t in ET.fromstring(data).iter() if t.tag.endswith('}' + tag)]


def xlsx_text(p: Path):
    out = []
    with zipfile.ZipFile(p) as z:
        shared = []
        if 'xl/sharedStrings.xml' in z.namelist():
            for si in ET.fromstring(z.read('xl/sharedStrings.xml')):
                shared.append(''.join(t.text or '' for t in si.iter() if t.tag.endswith('}t')))
        sheets = sorted((n for n in z.namelist() if re.match(r'xl/worksheets/sheet\d+\.xml$', n)),
                        key=lambda n: int(re.findall(r'\d+', n)[-1]))
        for n in sheets:
            out.append(f'## {Path(n).stem}')
            for row in ET.fromstring(z.read(n)).iter():
                if not row.tag.endswith('}row'):
                    continue
                vals = []
                for c in row:
                    v = next((x.text for x in c.iter() if x.tag.endswith('}v')), None)
                    if c.get('t') == 's' and v is not None:
                        v = shared[int(v)]
                    elif c.get('t') == 'inlineStr':
                        v = ''.join(x.text or '' for x in c.iter() if x.tag.endswith('}t'))
                    vals.append(v or '')
                if any(vals):
                    out.append(' | '.join(vals))
    return '\n'.join(out)


def pptx_text(p: Path):
    out = []
    with zipfile.ZipFile(p) as z:
        slides = sorted((n for n in z.namelist() if re.match(r'ppt/slides/slide\d+\.xml$', n)),
                        key=lambda n: int(re.findall(r'\d+', n)[-1]))
        for i, n in enumerate(slides, 1):
            out.append(f'## 第 {i} 页\n' + '\n'.join(t for t in xml_texts(z.read(n), 't') if t.strip()))
    return '\n\n'.join(out)


def pdf_text(p: Path):
    try:
        from pypdf import PdfReader
    except ImportError:
        return f'[PDF 未解析：未安装 pypdf] {p.name}'
    pages = PdfReader(str(p)).pages
    return '\n\n'.join(f'## 第 {i} 页\n{pg.extract_text() or ""}' for i, pg in enumerate(pages, 1))


def extract(p: Path):
    ext = p.suffix.lower()
    try:
        if ext in IMG_EXT:
            note = p.with_name(p.name + NOTE_SUFFIX)
            return f'[图片] {p.name}' + ('（有说明）' if note.exists() else '（暂无说明）')
        if ext in ('.html', '.htm'):
            return html_text(read_text(p))
        if ext in OFFICE_EXT:
            return subprocess.run(['textutil', '-convert', 'txt', '-stdout', str(p)],
                                  capture_output=True, timeout=60).stdout.decode('utf-8', 'replace')
        if ext == '.pdf':
            return pdf_text(p)
        if ext == '.xlsx':
            return xlsx_text(p)
        if ext == '.pptx':
            return pptx_text(p)
        if ext in TEXT_EXT or ext in CODE_EXT:
            return read_text(p)
    except Exception as e:
        return f'[无法解析 {p.name}：{e}]'
    return None


# ---------------------------------------------------------------- 索引

def db():
    SYS.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    c.execute('pragma journal_mode=wal')
    c.executescript('''
    create table if not exists files(path text primary key, mtime real, size integer, kind text,
                                     period text, cat text, repo text);
    create table if not exists chunk(id integer primary key, path text, kind text, period text,
                                     cat text, repo text, start integer, end integer, content text);
    create index if not exists chunk_path on chunk(path);
    create virtual table if not exists fts using fts5(content, content='chunk', content_rowid='id',
                                                      tokenize='trigram');
    create trigger if not exists chunk_ai after insert on chunk begin
      insert into fts(rowid, content) values (new.id, new.content); end;
    create trigger if not exists chunk_ad after delete on chunk begin
      insert into fts(fts, rowid, content) values('delete', old.id, old.content); end;
    ''')
    return c


def chunks_of(text):
    out, buf, size, start, last = [], [], 0, 1, 1
    for i, line in enumerate(text.splitlines(), 1):
        for piece in [line[j:j + CHUNK_CHARS] for j in range(0, len(line), CHUNK_CHARS)] or ['']:
            if buf and size + len(piece) > CHUNK_CHARS:
                out.append((start, last, '\n'.join(buf)))
                buf, size = [], 0
            if not buf:
                start = i
            buf.append(piece)
            size += len(piece) + 1
            last = i
    if buf:
        out.append((start, last, '\n'.join(buf)))
    return [x for x in out if x[2].strip()]


def _drop(c, path):
    c.execute('delete from chunk where path=?', (path,))
    c.execute('delete from files where path=?', (path,))


def _index_one(c, p: Path, st, kind, period='', cat='', repo=''):
    path = str(p)
    _drop(c, path)
    text = extract(p)
    if text is None:
        text = f'[未解析的文件] {p.name}'
    rows = [(path, kind, period, cat, repo, s, e, body + (f'\n［文件］{p.name}' if n == 0 else ''))
            for n, (s, e, body) in enumerate(chunks_of(text) or [(1, 1, '')])]
    c.executemany('insert into chunk(path,kind,period,cat,repo,start,end,content) values (?,?,?,?,?,?,?,?)', rows)
    c.execute('insert into files values (?,?,?,?,?,?,?)', (path, st.st_mtime, st.st_size, kind, period, cat, repo))


def _sync(c, wanted, kind, repo=None):
    """wanted: {path: (Path, stat, period, cat)}；增量更新，返回 (新增/更新, 删除)。"""
    q = 'select path, mtime, size from files where kind=?' + (' and repo=?' if repo else '')
    known = {r[0]: (r[1], r[2]) for r in c.execute(q, (kind, repo) if repo else (kind,))}
    changed = 0
    for path, (p, st, period, cat) in wanted.items():
        if known.get(path) != (st.st_mtime, st.st_size):
            _index_one(c, p, st, kind, period, cat, repo or '')
            changed += 1
            if changed % 500 == 0:
                c.commit()
    removed = [p for p in known if p not in wanted]
    for p in removed:
        _drop(c, p)
    c.commit()
    return changed, len(removed)


def index_docs():
    init_dirs = PERIODS.exists()
    if not init_dirs:
        return '索引：无文档'
    wanted = {}
    for p in PERIODS.rglob('*'):
        rel = p.relative_to(PERIODS).parts
        if not p.is_file() or HIST in rel or p.name == '期信息.json' or p.name.startswith('.'):
            continue
        if p.suffix.lower() not in DOC_EXT:
            continue
        cat = rel[1] if len(rel) > 2 and rel[1] in CATS + ['来源快照'] else ('记录' if p.name == '记录.md' else '')
        wanted[str(p)] = (p, p.stat(), rel[0], cat)
    for p in BASE.rglob('*') if BASE.exists() else []:
        if p.is_file() and p.suffix.lower() in DOC_EXT and p != BASE_FILE and not p.name.startswith('.') and HIST not in p.parts:
            wanted[str(p)] = (p, p.stat(), '', '基础')
    with db() as c:
        changed, removed = _sync(c, wanted, 'doc')
    return f'索引：文档 {len(wanted)} 个（本次更新 {changed}，移除 {removed}）'


def index_repo(name):
    repos = load_repos()
    if name not in repos:
        raise KBError(f'没有登记这个仓库：{name}')
    root = Path(repos[name]['路径'])
    if not root.is_dir():
        raise KBError(f'仓库目录不存在：{root}')
    wanted = {}
    for p in repo_files(root):
        if not code_wanted(p.relative_to(root)):
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        if p.is_file() and st.st_size <= MAX_CODE_BYTES:
            wanted[str(p)] = (p, st, '', '')
    with db() as c:
        changed, removed = _sync(c, wanted, 'code', name)
    return f'索引：仓库 {name} 文件 {len(wanted)} 个（本次更新 {changed}，移除 {removed}）'


def reindex(target='all'):
    out = []
    if target in ('all', 'docs'):
        out.append(index_docs())
    for name in load_repos():
        if target in ('all', 'code', name):
            out.append(index_repo(name))
    if not out:
        raise KBError(f'不认识的目标：{target}（可用 all / docs / code / 仓库名）')
    return '\n'.join(out)


# ---------------------------------------------------------------- 检索 / 阅读

def _snippet(content, terms, start):
    low = content.lower()
    idx = min([i for i in (low.find(t.lower()) for t in terms) if i >= 0] or [0])
    a = max(0, idx - 120)
    line = start + content[:idx].count('\n')
    s = content[a:idx + 220].replace('\n', ' ⏎ ')
    return line, ('…' if a else '') + s + ('…' if idx + 220 < len(content) else '')


def _query(c, terms, filters, args, limit):
    long_ = [t for t in terms if len(t) >= 3]
    short = [t for t in terms if len(t) < 3]
    where = list(filters)
    params = []
    if long_:
        base = 'select chunk.path, kind, period, cat, repo, start, end, chunk.content from fts join chunk on chunk.id=fts.rowid'
        where.insert(0, 'fts match ?')
        params.append(' AND '.join('"' + t.replace('"', '""') + '"' for t in long_))
        order = "order by (kind='doc') desc, (cat='记录'), bm25(fts)"
    else:
        base = 'select path, kind, period, cat, repo, start, end, content from chunk'
        order = "order by (kind='doc') desc, (cat='记录'), chunk.id desc"
    for t in short:
        where.append('chunk.content like ?')
        params.append(f'%{t}%')
    sql = f'{base} where {" and ".join(where)} {order} limit ?'
    return c.execute(sql, params + list(args) + [limit]).fetchall()


def search_hits(query, period=None, category=None, scope='all', repo=None, limit=10):
    terms = [t for t in re.split(r'\s+', (query or '').strip()) if t]
    if not terms:
        raise KBError('查询词为空')
    index_docs()
    filters, args = [], []
    if scope in ('docs', 'code'):
        filters.append('kind=?')
        args.append('doc' if scope == 'docs' else 'code')
    if period:
        filters.append('period=?')
        args.append(period_dir(period).name)
    if category:
        filters.append('cat=?')
        args.append(category)
    if repo:
        filters.append('repo=?')
        args.append(repo)
    limit = max(1, min(int(limit or 10), 50))
    with db() as c:
        rows = _query(c, terms, filters, args, limit)
        mode = '全部词'
        if not rows and len(terms) > 1:
            seen, rows = set(), []
            for t in terms:
                for r in _query(c, [t], filters, args, limit):
                    if (r[0], r[5]) not in seen:
                        seen.add((r[0], r[5]))
                        rows.append(r)
            rows, mode = rows[:limit], '任一词'
    hits = []
    for path, kind, per, cat, repo_, start, end, content in rows:
        line, snip = _snippet(content, terms, start)
        hits.append({'path': path, 'kind': kind, 'period': per, 'cat': cat, 'repo': repo_,
                     'line': line, 'snippet': snip})
    return hits, mode


def search(query, period=None, category=None, scope='all', repo=None, limit=10):
    hits, mode = search_hits(query, period, category, scope, repo, limit)
    if not hits:
        return f'没有找到「{query}」。可换个说法、缩短关键词，或先 kb_reindex。'
    out = [f'找到 {len(hits)} 条（匹配{mode}）：']
    for i, h in enumerate(hits, 1):
        tag = f'代码·{h["repo"]}' if h['kind'] == 'code' else f'{h["period"]}·{h["cat"] or "其他"}'
        out.append(f'\n[{i}] {tag}  {h["path"]}:{h["line"]}\n    {h["snippet"]}')
    return '\n'.join(out)


def _allowed(p: Path):
    roots = [ROOT.resolve()] + [Path(v['路径']).resolve() for v in load_repos().values()]
    roots += [Path(x).resolve() for x in (load_meta(PERIODS / n).get('SDD目录') for n in period_names()) if x]
    return any(p == r or r in p.parents for r in roots)


def read_file(path, start=1, max_lines=300):
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise KBError(f'文件不存在：{p}')
    if not _allowed(p):
        raise KBError('只能读取知识库和已登记仓库里的文件')
    if p.suffix.lower() in IMG_EXT:
        note = p.with_name(p.name + NOTE_SUFFIX)
        desc = read_text(note) if note.exists() else '（暂无说明）'
        return f'这是图片，请用 Read 工具直接查看：{p}\n\n{desc}'
    text = extract(p)
    if text is None:
        return f'不支持解析这种文件：{p.name}'
    lines = text.splitlines()
    start = max(1, int(start or 1))
    end = min(len(lines), start + max(1, int(max_lines or 300)) - 1)
    body = '\n'.join(f'{i:>5}  {lines[i - 1]}' for i in range(start, end + 1))
    more = f'\n…（共 {len(lines)} 行，继续读请用 start={end + 1}）' if end < len(lines) else ''
    return f'{p}（第 {start}-{end} 行）\n{body}{more}'


# ---------------------------------------------------------------- 总览 / 详情 / 开发包

def _materials(d):
    res = {}
    for c in CATS:
        items = []
        for p in sorted((d / c).iterdir()) if (d / c).exists() else []:
            if p.name in (HIST, NOTES_FILE) or p.name.startswith('.') or p.name.endswith(NOTE_SUFFIX):
                continue
            items.append(p)
        res[c] = items
    return res


def overview():
    init()
    out = [f'知识库：{ROOT}']
    nb = len(base_load()['条目'])
    out.append(f'基础知识库：{nb} 条（账号、测试账号、代理 / VPN、环境配置等，所有期共用；用 kb_base 查看）')
    names = period_names()
    out.append(f'\n期（{len(names)}）：' if names else '\n期：（空，先 kb_create_iteration）')
    for n in names:
        d = PERIODS / n
        m = load_meta(d)
        mats = _materials(d)
        cnt = ' · '.join(f'{c} {len(v) + len(notes_of(d, c, m))}' for c, v in mats.items())
        repos = '、'.join(m.get('关联仓库') or []) or '无'
        out.append(f'- {n} ｜ {m.get("状态")} ｜ {cnt} ｜ 仓库：{repos} ｜ 更新 {m.get("更新时间", "")}')
    repos = load_repos()
    out.append('\n代码仓库：' + ('' if repos else '（未登记）'))
    with db() as c:
        for k, v in repos.items():
            n = c.execute("select count(*) from files where kind='code' and repo=?", (k,)).fetchone()[0]
            out.append(f'- {k} → {v["路径"]}（已索引 {n} 个文件）')
        nd = c.execute("select count(*) from files where kind='doc'").fetchone()[0]
    inbox = [p.name for p in INBOX.iterdir() if not p.name.startswith('.')] if INBOX.exists() else []
    out.append(f'\n收件箱待整理：{len(inbox)} 个' + (f'（{"、".join(inbox[:20])}）路径 {INBOX}' if inbox else ''))
    out.append(f'文档索引：{nd} 个文件')
    return '\n'.join(out)


def period_detail(name, log_lines=20):
    d = period_dir(name)
    m = load_meta(d)
    out = [f'# {d.name}', f'状态：{m.get("状态")}　创建：{m.get("创建时间")}　更新：{m.get("更新时间", "")}',
           f'说明：{m.get("说明") or "无"}', f'关联仓库：{"、".join(m.get("关联仓库") or []) or "无"}', f'目录：{d}']
    branches = [n for n in notes_of(d, m=m) if n['类型'] == '分支']
    if branches:
        out.append('开发分支：' + '；'.join(f'{n["编号"]} {note_title(n)}' for n in branches))
    for c, items in _materials(d).items():
        ns = notes_of(d, c, m)
        out.append(f'\n## {c}（文件 {len(items)}' + (f' · 文字 {len(ns)}）' if ns else '）'))
        for n in ns:
            out.append(f'- {n["编号"]} ［{n["类型"]}］{note_title(n)}'
                       + (f'　{n["链接"]}' if n.get('链接') and n['链接'] != note_title(n) else '')
                       + (f'　（来自 {n["来自"]}）' if n.get('来自') else ''))
        for p in items:
            if p.is_dir():
                out.append(f'- {p.name}/（目录，{sum(1 for _ in p.rglob("*") if _.is_file())} 个文件）')
            else:
                flag = ''
                if p.suffix.lower() in IMG_EXT:
                    flag = '［有说明］' if p.with_name(p.name + NOTE_SUFFIX).exists() else '［无说明］'
                out.append(f'- {p.name} {flag}')
        hist = d / c / HIST
        if hist.exists():
            out.append(f'  （历史版本 {sum(1 for _ in hist.iterdir())} 个）')
    srcs = m.get('来源') or []
    if srcs:
        out.append(f'\n## 来源（{len(srcs)}，待核对 {sum(1 for s in srcs if s.get("核对") == "待核对")}）')
        for s in srcs:
            out.append(f'- {s["编号"]} ［{s.get("核对")}］《{s["标题"]}》{s.get("条目", "")} → {"、".join(s.get("文件", []))}\n'
                       f'  {s["地址"]}\n  简介：{s.get("简介", "")}' + (f'\n  核对备注：{s["核对备注"]}' if s.get('核对备注') else '')
                       + (f'\n  上次检查：{s["检查时间"]} {s.get("检查结果", "")}' if s.get('检查时间') else '')
                       + ('\n  ⚠ 原文已变化，条目文档待更新' if s.get('待更新') else '')
                       + ''.join(f'\n  变更 {c["时间"]}：{c["版本"]}，{c["改动"]}，{c["处理"]}，差异 {c["差异"]}'
                                 for c in (s.get('变更记录') or [])[-3:]))
    f = d / '记录.md'
    if f.exists():
        lines = [x for x in read_text(f).splitlines() if x.startswith('- ')]
        out.append(f'\n## 最近记录（共 {len(lines)} 条）')
        out += lines[-log_lines:]
    return '\n'.join(out)


def dev_package(name, max_chars=60000):
    d = period_dir(name)
    m = load_meta(d)
    if m.get('状态') not in DEV_OK:
        raise KBError(f'「{d.name}」当前状态是「{m.get("状态")}」，用户尚未批准开发。'
                      f'请提醒用户确认材料齐全后，在终端运行 kb approve "{d.name}"，或在知识库网页点「开始开发」')
    repos = load_repos()
    out = [period_detail(name, log_lines=30), '\n# 关联仓库']
    for r in m.get('关联仓库') or []:
        if r in repos:
            out.append(f'- {r} → {repos[r]["路径"]}　' + index_repo(r))
    if not m.get('关联仓库'):
        out.append('（未关联，开发前请让用户确认目标仓库，再用 kb_link_repo 关联）')
    budget = max_chars
    ns = sorted(notes_of(d, m=m), key=lambda n: (n['类型'] != '分支', CATS.index(n['分类'])))
    if ns:
        out.append('\n# 文字资料（口述需求、开发分支、外部链接等原样记录；链接未导入的可用 kb_fetch_url 查看）')
        for n in ns:
            part = '\n' + note_md(n).replace('## ', f'## ［{n["分类"]}］', 1)
            budget -= len(part)
            out.append(part)
    mats = _materials(d)
    for c in ('需求', '接口文档', '其他资料'):
        for p in mats[c]:
            if p.name == PROTO_DIR:
                continue
            files = [x for x in p.rglob('*') if x.is_file()] if p.is_dir() else [p]
            for f in files:
                if (f.suffix.lower() not in DOC_EXT or f.suffix.lower() in IMG_EXT or HIST in f.parts
                        or f.name.endswith(NOTE_SUFFIX)):
                    continue
                text = extract(f) or ''
                if budget <= 0:
                    out.append(f'\n## [{c}] {f}\n（篇幅已满，用 kb_read 读取）')
                    continue
                part = text[:min(12000, budget)]
                budget -= len(part)
                more = f'\n…（已截断，全文用 kb_read 读取）' if len(part) < len(text) else ''
                out.append(f'\n## [{c}] {f}\n{part}{more}')
    out.append('\n# 设计稿（要实现的产品图，UI 以此为准；请用 Read 逐张查看）')
    n_design = 0
    for p in mats['设计图']:
        if p.is_dir():
            for f in sorted(p.rglob('*')):
                if HIST in f.parts or not f.is_file():
                    continue
                if f.suffix.lower() in IMG_EXT:
                    n_design += 1
                    out.append(f'- {f}')
                elif f.suffix.lower() == '.md' and not f.name.endswith(NOTE_SUFFIX):
                    part = read_text(f)[:min(15000, max(budget, 0))]
                    budget -= len(part)
                    out.append(f'\n## [设计规格] {f}\n{part}' if part else f'- {f}（设计规格，用 kb_read 读取）')
        elif p.suffix.lower() in IMG_EXT:
            n_design += 1
            note = p.with_name(p.name + NOTE_SUFFIX)
            out.append(f'- {p}' + (f'\n  说明：{read_text(note).split(chr(10), 2)[-1].strip()[:300]}' if note.exists() else ''))
        else:
            out.append(f'- {p}（用 kb_read 读取）')
    if not n_design:
        out.append('⚠️ 还没有设计稿图片。请先用 kb_import_design 导入需求表里的「设计稿地址」，或让用户导出设计稿放进「设计图」；不要按原型图臆造 UI。')
    proto = d / '需求' / PROTO_DIR
    if proto.exists():
        imgs = sorted(x for x in proto.iterdir() if x.suffix.lower() in IMG_EXT)
        out.append(f'\n# 原型图 / 参考图（{len(imgs)} 张，仅用于理解交互逻辑，UI 以设计稿为准）')
        for f in imgs[:80]:
            note = f.with_name(f.name + NOTE_SUFFIX)
            desc = re.sub(r'\s+', ' ', read_text(note).split('\n', 2)[-1])[:160] if note.exists() else ''
            out.append(f'- {f}' + (f'　{desc}' if desc else ''))
    bc = base_context()
    if bc:
        out.append('\n# 基础知识库（所有期共用：账号、测试账号、代理 / VPN、环境配置；机密用 kb_base_secret 读取，不要写进代码、文档、提交或日志）\n' + bc)
    fl = period_flow(m)
    out.append('\n# 开发约定\n- 状态是「已批准开发」时，开始写代码前调用 kb_set_status 改为「开发中」\n'
               f'- 开发流程：{fl["名称"]}（{fl.get("说明") or "见知识库网页「⚙ 设置」"}）\n'
               + flow_text(fl, '开发约定', 期名=d.name, **({'文档目录': m['SDD目录']} if m.get('SDD目录') else {})).rstrip() + '\n'
               '- 需要用户确认时用 kb_ask 发到网页，再用 kb_wait_answer 等回答；'
               + ('本期已开启免打扰：自行决策并 kb_log 记录理由\n' if m.get('免打扰') else '本期未开启免打扰：拿到回答前不要自行决定\n')
               + 
               '- 关键决定、接口变更、与需求不一致之处用 kb_log 记录\n'
               '- 完成后 kb_set_status 改为「已完成」，并记录改动摘要（分支、提交）')
    return '\n'.join(out)



# ---------------------------------------------------------------- 开发流程（设置）
# 「开始开发」后后台会话按哪套流程干活：怎么认仓库、文档目录在哪、提示词、进度怎么看、什么算做完。
# 内置「通用模板」；网页「⚙ 设置」里可修改（内置的改了能恢复默认）、新建、复制、导入导出，
# 方便其他研发组按自己的流程接入。每一期可单独选流程，不选就按仓库自动匹配、匹配不上用默认流程。
SETTINGS_FILE = ROOT / '设置.json'
FLOW_VARS = {'期名': '期名', '仓库': '代码仓库绝对路径', '分支': '当前分支', '文档目录': '流程文档目录绝对路径',
             '资料目录': '本期资料副本目录绝对路径（文档目录/资料目录名）'}
FLOW_FIELDS = [   # 网页表单：键、标题、类型、说明
    ('名称', '名称', 'text', '如：iOS SDD、前端 Vibe 流程'),
    ('说明', '说明', 'textarea', '给人看的：适用哪个组、哪个端'),
    ('识别文件', '识别文件（每行一个，相对仓库根目录）', 'lines',
     '仓库里这些文件都存在才算用这套流程，用于自动匹配仓库；留空 = 任何 git 仓库都能用'),
    ('分支规则', '分支名规则（正则，可空）', 'text',
     '从文字资料里认出开发分支；带「/」的分支名（如 feature/xxx）总能认出，这里补充本组的命名，如 -stable 结尾'),
    ('文档目录方式', '文档目录怎么定', 'select:模板|命令', '开发文档、资料副本放在哪：按模板拼路径，或运行仓库里的脚本算出来'),
    ('文档目录模板', '文档目录模板', 'text', '相对仓库根目录或绝对路径，可用 {分支}、{分支目录}（「/」换成「_」）、{期名}、{仓库}'),
    ('文档目录命令', '文档目录命令', 'text', '在仓库根目录运行，输出路径；输出 JSON 时填下面的 JSON 键'),
    ('文档目录JSON键', '命令输出的 JSON 键', 'text', '如 PROJECT_DOCS；命令直接输出路径时留空'),
    ('资料目录名', '资料副本目录名', 'text', '本期资料拷到 文档目录/这个名字/（自动加 .gitignore，不进 git）'),
    ('准备方式', '准备方式', 'select:通用|SDD',
     '通用：拷资料 + 列候选链接；SDD：另外按仓库模板建 sdd-start.md / sdd-status.md，链接按 SDD 栏目分组'),
    ('流程配置文件', '流程配置文件（相对文档目录，可空）', 'text', '写着需求链接的配置文件（如 sdd-start.md）；更正链接时会一起改'),
    ('开发步骤', '开发步骤（后台会话按此推进）', 'textarea', '写清用什么命令、推进到什么状态算完成；可用变量见下方'),
    ('确认点', '需要人确认的地方', 'textarea', '流程里哪些地方要停下来让人确认（会用 kb_ask 发到网页）'),
    ('续跑提示', '自动续跑时的提示', 'textarea', '会话中途退出后续跑时，怎么确认实际进度'),
    ('开发约定', '开发约定（写进开发包）', 'textarea', '终端里手动开发时 Claude 也会看到'),
    ('需求变更提示', '需求有变化 / 链接更正时', 'textarea', '开发中需求来源更新或链接更正后，怎么同步到流程里'),
    ('进度类型', '进度怎么看', 'select:无|任务清单|SDD',
     '无：只看动作流水；任务清单：读文档目录下 Markdown 勾选框；SDD：读 sdd-status.md'),
    ('任务清单文件', '任务清单文件（相对文档目录）', 'text', '进度类型为「任务清单」时：- [x] 已完成、- [ ] 未完成；全部勾完算开发完成'),
    ('测试文件', '测试用例 / 自动化测试文件（每行一个，相对文档目录，可用通配符）', 'lines',
     '识别到这些文件，开发面板就出现「🔁 复测」：开发时手机不够、没连手机没测成的 case，条件具备后补测。'
     '用例写成「### 编号: PASS / FAIL / BLOCKED」能统计结果'),
    ('复测步骤', '复测步骤（点「复测」后后台会话按此执行）', 'textarea', '可用变量同上，另有 {范围}（只测没通过的 / 全部）'),
]
BUILTIN_FLOWS = {
    'generic': {
        '名称': '通用模板', '说明': '不依赖仓库里的特定脚本，任何 git 仓库都能用；其他研发组可以复制这一套改成自己的流程',
        '识别文件': [], '分支规则': '',
        '文档目录方式': '模板', '文档目录模板': 'docs/kb/{分支目录}', '文档目录命令': '', '文档目录JSON键': '',
        '资料目录名': 'kb-materials', '准备方式': '通用', '流程配置文件': '',
        '开发步骤': """1. kb_dev_prepare 准备资料（拷到 {资料目录}），通读需求、设计稿、接口文档和仓库相关代码。
2. 在 {文档目录}/plan.md 写技术方案（改哪些模块、接口、风险），在 {文档目录}/tasks.md 用「- [ ] 任务」列出任务清单；用 kb_ask 请用户确认方案后再写代码。
3. 按任务清单逐条开发：改代码 → 编译 / 运行相关测试 → 在 tasks.md 勾上「- [x]」→ 按仓库惯例提交；直到全部勾完。""",
        '确认点': '技术方案、与需求 / 设计稿不一致的地方、方案取舍、缺少账号或环境、操作被权限拦截等',
        '续跑提示': '先看 {文档目录}/tasks.md 的勾选情况和 git status / git log 确认实际进度，没做完的任务接着做',
        '开发约定': '- 先 kb_dev_prepare 拷贝资料，方案写在 {文档目录}/plan.md，任务清单写在 {文档目录}/tasks.md，做完一条勾一条',
        '需求变更提示': '先 kb_dev_prepare 同步资料副本，对照差异更新 plan.md / tasks.md；影响已写代码的用 kb_ask 确认，并 kb_log 记录',
        '进度类型': '任务清单', '任务清单文件': 'tasks.md',
        '测试文件': ['test-cases.md', 'tests/**/*'],
        '复测步骤': """1. 读 {文档目录} 下的测试用例和自动化测试脚本：{范围}。
2. 要用手机时 kb_devices 看、kb_device_claim 申请，只在申请到的手机上装包、测试（adb -s <序列号>）；有自动化测试脚本的直接运行脚本。
3. 结果追加到用例文件末尾的「## 复测（日期）」小节，每条写「### 编号: PASS / FAIL / BLOCKED（原因）」，不改原来的记录。""",
    },
}
DEFAULT_FLOW = 'generic'


def load_settings():
    try:
        s = json.loads(read_text(SETTINGS_FILE)) if SETTINGS_FILE.exists() else {}
    except ValueError:
        s = {}
    s.setdefault('默认流程', DEFAULT_FLOW)
    s.setdefault('流程', {})       # id → 自定义流程，或对内置流程的修改
    return s


def save_settings(s):
    tmp = SETTINGS_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=1), 'utf-8')
    tmp.replace(SETTINGS_FILE)


def flows():
    """全部开发流程（内置的在前），每个带 id、内置、已修改、默认。"""
    s = load_settings()
    out = []
    for fid, base in BUILTIN_FLOWS.items():
        f = dict(base, **(s['流程'].get(fid) or {}))
        out.append(dict(f, id=fid, 内置=True, 已修改=fid in s['流程']))
    for fid, f in s['流程'].items():
        if fid not in BUILTIN_FLOWS:
            out.append(dict(BUILTIN_FLOWS['generic'], **f, id=fid, 内置=False, 已修改=False))
    for f in out:
        f['默认'] = f['id'] == s['默认流程']
    return out


def get_flow(fid=''):
    fs = flows()
    fid = fid or load_settings()['默认流程']
    f = next((x for x in fs if x['id'] == fid), None)
    if not f:
        if fid == load_settings()['默认流程']:
            return next(x for x in fs if x['id'] == DEFAULT_FLOW)
        raise KBError(f'没有这个开发流程：{fid}')
    return f


def save_flow(data, by='用户（网页）'):
    """新建 / 修改开发流程。data 带 id 是修改（内置的存为修改项），不带是新建。"""
    s = load_settings()
    keys = [k for k, *_ in FLOW_FIELDS]
    f = {k: data[k] for k in keys if k in data}
    for k, _, typ, _ in FLOW_FIELDS:
        if typ == 'lines' and isinstance(f.get(k), str):
            f[k] = [x.strip() for x in f[k].splitlines() if x.strip()]
    for k, _, typ, _ in FLOW_FIELDS:
        if typ.startswith('select:') and k in f and f[k] not in typ[7:].split('|'):
            raise KBError(f'「{k}」只能是：{typ[7:].replace("|", " / ")}')
    if f.get('分支规则'):
        try:
            re.compile(f['分支规则'])
        except re.error as e:
            raise KBError(f'分支名规则不是合法的正则：{e}')
    if not (f.get('名称') or '').strip():
        raise KBError('流程名称不能为空')
    fid = (data.get('id') or '').strip()
    if not fid:
        fid = 'flow-' + uuid.uuid4().hex[:6]
    elif fid not in BUILTIN_FLOWS and fid not in s['流程']:
        raise KBError(f'没有这个开发流程：{fid}')
    if any(x['名称'] == f['名称'] and x['id'] != fid for x in flows()):
        raise KBError(f'已经有叫「{f["名称"]}」的流程了')
    s['流程'][fid] = f
    save_settings(s)
    return f'已保存开发流程「{f["名称"]}」（{by}）', fid


def delete_flow(fid):
    """自定义的删除；内置的恢复默认。"""
    s = load_settings()
    if fid not in s['流程']:
        raise KBError('内置流程没有修改过，不用恢复' if fid in BUILTIN_FLOWS else f'没有这个开发流程：{fid}')
    name = get_flow(fid)['名称']
    s['流程'].pop(fid)
    if fid not in BUILTIN_FLOWS:
        if s['默认流程'] == fid:
            s['默认流程'] = DEFAULT_FLOW
        for n in period_names():
            d = PERIODS / n
            m = load_meta(d)
            if m.get('开发流程') == fid:
                m.pop('开发流程')
                save_meta(d, m)
    save_settings(s)
    return f'已恢复内置流程「{name}」的默认设置' if fid in BUILTIN_FLOWS else f'已删除开发流程「{name}」'


def set_default_flow(fid):
    f = get_flow(fid)
    s = load_settings()
    s['默认流程'] = f['id']
    save_settings(s)
    return f'默认开发流程改为「{f["名称"]}」'


def set_period_flow(period, fid):
    """某一期用哪套开发流程；空 = 自动（按仓库匹配，匹配不上用默认）。"""
    d = period_dir(period)
    f = get_flow(fid) if fid else None
    m = load_meta(d)
    if (m.get('开发流程') or '') == (fid or ''):
        return '没有变化'
    if f:
        m['开发流程'] = f['id']
    else:
        m.pop('开发流程', None)
    save_meta(d, m)
    log(d, '开发流程', f['名称'] if f else '自动（按仓库匹配）')
    return f'「{d.name}」的开发流程改为「{f["名称"] if f else "自动"}」'


def flow_matches(f, root):
    return all((Path(root) / x).exists() for x in f.get('识别文件') or [])


def flow_for(m, root):
    """这个仓库用哪套流程：这一期选定的 > 识别文件对得上的（默认流程优先）> 不要求识别文件的默认流程。对不上返回 None。"""
    if m.get('开发流程'):
        f = get_flow(m['开发流程'])
        return f if flow_matches(f, root) else None
    fs = sorted(flows(), key=lambda x: not x['默认'])
    for f in fs:
        if f.get('识别文件') and flow_matches(f, root):
            return f
    f = fs[0]
    return f if not f.get('识别文件') else None


def period_flow(m):
    """还没定仓库时用的流程（开发包、需求变更提醒）：这一期选定的 > 上次开发用的 > 默认。"""
    for fid in (m.get('开发流程'), (m.get('开发会话') or {}).get('流程')):
        if fid:
            try:
                return get_flow(fid)
            except KBError:
                pass
    return get_flow()


def flow_text(f, key, **v):
    """流程里的文字，替换 {期名} 等变量；不认识的 {xxx} 原样保留。"""
    class Keep(dict):
        def __missing__(self, k):
            return '{' + k + '}'
    try:
        return (f.get(key) or '').format_map(Keep(v))
    except (ValueError, IndexError):
        return f.get(key) or ''


def flow_docs(f, root, branch, period, store=''):
    """按流程算文档目录。"""
    root = Path(root)
    v = dict(仓库=str(root), 分支=branch, 分支目录=branch.replace('/', '_'), 期名=period)
    if f.get('文档目录方式') == '命令':
        cmd = flow_text(f, '文档目录命令', **v) + (f' {store}' if store else '')
        try:
            r = subprocess.run(cmd, shell=True, cwd=root, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            raise KBError(f'取文档目录超时：{cmd}')
        out = r.stdout.strip()
        try:
            p = json.loads(out)[f['文档目录JSON键']] if f.get('文档目录JSON键') else out.splitlines()[-1]
        except (ValueError, KeyError, IndexError, TypeError):
            raise KBError(f'取文档目录失败（{cmd}）：{(r.stderr or out).strip()[:500]}')
    else:
        p = flow_text(f, '文档目录模板', **v).strip()
        if not p:
            raise KBError(f'开发流程「{f["名称"]}」没有设置文档目录')
    p = Path(p).expanduser()
    return p if p.is_absolute() else (root / p).resolve()


def task_progress(f, docs):
    """任务清单进度：Markdown 勾选框。"""
    p = Path(docs or '') / (f.get('任务清单文件') or 'tasks.md')
    if not docs or not p.is_file():
        return None
    items = re.findall(r'^\s*[-*+]\s+\[([ xX])\]\s+(.+)$', read_text(p), re.M)
    done = sum(1 for x, _ in items if x.lower() == 'x')
    cur = next((t.strip() for x, t in items if x == ' '), '')
    return {'类型': '任务清单', '文件': str(p), '完成': done, '总数': len(items), '当前': cur[:200]}


def flow_progress(f, docs):
    if not f or not docs:
        return None
    if f.get('进度类型') == 'SDD':
        pg = sdd_progress(docs)
        return dict(pg, 类型='SDD') if pg else None
    if f.get('进度类型') == '任务清单':
        return task_progress(f, docs)
    return None


def flow_done(f, docs):
    if not f or not docs:
        return False
    if f.get('进度类型') == 'SDD':
        return _sdd_status(docs).get('step3') == 'done'
    if f.get('进度类型') == '任务清单':
        t = task_progress(f, docs)
        return bool(t and t['总数'] and t['完成'] == t['总数'])
    return False


# ---------------------------------------------------------------- AI 引擎（设置）
# 后台会话用哪个编程 AI 跑：Claude Code / Codex CLI / Hermes Agent，或自定义命令。
# 开发会话按这一期选的引擎（不选用默认），模糊添加、来源更新、生成流程用默认引擎。
# 引擎要能无人值守运行、并接入知识库 MCP（kb_ask 等工具），否则没法在网页上确认。
# 内置预设只用各引擎的常规权限模式，不默认跳过审批或沙箱；要放宽由用户在设置里自己改参数。
ENGINE_VARS = {'提示词': '本次任务的完整提示词', '标题': '会话标题，如 kb·期名', '会话ID': '续跑时上一轮的会话号'}
ENGINE_FIELDS = [
    ('名称', '名称', 'text', '如：Codex CLI、自研 Agent'),
    ('说明', '说明', 'textarea', '给人看的'),
    ('命令', '可执行命令', 'text', '命令名或绝对路径，如 claude、codex、hermes'),
    ('启动参数', '启动参数（每行一个）', 'lines', '无人值守跑一次任务的参数；{提示词} 单独占一行。权限相关参数决定 AI 能在仓库里做什么，请按团队安全要求填写'),
    ('续跑参数', '续跑参数（每行一个，可空）', 'lines', '接着上一轮会话继续的参数，可用 {会话ID}；留空 = 每次新开会话，用续跑提示接着做'),
    ('输出格式', '输出格式', 'select:Claude stream-json|Codex JSONL|Hermes stream-json|纯文本',
     '用来在网页上显示动作、取最后结果和会话号；不确定选「纯文本」'),
    ('接入命令', '接入知识库的命令（可空）', 'text', '把知识库 MCP 服务注册给这个引擎；可用 {kb} 代表「python kb.py serve」的完整命令'),
    ('接入配置', '手动接入说明（可空）', 'textarea', '没有接入命令时，告诉用户把什么写进哪个配置文件；可用 {python}、{kbpy}'),
]
BUILTIN_ENGINES = {
    'claude': {
        '名称': 'Claude Code', '说明': 'Anthropic 的 Claude Code（claude -p 无人值守，auto 权限模式）',
        '命令': 'claude',
        '启动参数': ['-p', '{提示词}', '--permission-mode', 'auto', '--output-format', 'stream-json', '--verbose', '-n', '{标题}'],
        '续跑参数': ['-p', '{提示词}', '--permission-mode', 'auto', '--output-format', 'stream-json', '--verbose', '-n', '{标题}',
                    '--resume', '{会话ID}'],
        '输出格式': 'Claude stream-json', '接入命令': 'claude mcp add kb -s user -- {kb}', '接入配置': '',
    },
    'codex': {
        '名称': 'Codex CLI', '说明': 'OpenAI 的 Codex CLI（codex exec 无人值守，workspace-write 沙箱）。'
                                    '如果知识库工具调用被审批拦住，按团队安全要求调整启动参数',
        '命令': 'codex',
        '启动参数': ['exec', '--json', '--sandbox', 'workspace-write', '--skip-git-repo-check', '{提示词}'],
        '续跑参数': ['exec', 'resume', '{会话ID}', '--json', '--sandbox', 'workspace-write', '--skip-git-repo-check', '{提示词}'],
        '输出格式': 'Codex JSONL', '接入命令': 'codex mcp add kb -- {kb}', '接入配置': '',
    },
    'hermes': {
        '名称': 'Hermes Agent', '说明': 'Nous Research 的 Hermes Agent（hermes chat --oneshot 无人值守）。'
                                       '危险命令默认要审批，无人值守时会被拒绝；需要放宽时按团队安全要求调整启动参数',
        '命令': 'hermes',
        '启动参数': ['chat', '--oneshot', '--format', 'stream-json', '-q', '{提示词}'],
        '续跑参数': ['chat', '--resume', '{会话ID}', '--oneshot', '--format', 'stream-json', '-q', '{提示词}'],
        '输出格式': 'Hermes stream-json', '接入命令': '',
        '接入配置': '在 ~/.hermes/config.yaml 里加上（已有 mcp_servers: 就只加 kb 这一段），然后重启 hermes：\n'
                    'mcp_servers:\n  kb:\n    command: "{python}"\n    args: ["{kbpy}", "serve"]\n    timeout: 900',
    },
}
DEFAULT_ENGINE = 'claude'


def _kb_cmd():
    py = SYS / '.venv' / 'bin' / 'python'
    return str(py if py.exists() else sys.executable), str(SYS / 'kb.py')


def engines():
    s = load_settings()
    over = s.get('引擎') or {}
    dft = s.get('默认引擎') or DEFAULT_ENGINE
    out = [dict(base, **(over.get(eid) or {}), id=eid, 内置=True, 已修改=eid in over) for eid, base in BUILTIN_ENGINES.items()]
    out += [dict(BUILTIN_ENGINES['claude'], **e, id=eid, 内置=False, 已修改=False) for eid, e in over.items()
            if eid not in BUILTIN_ENGINES]
    for e in out:
        e['默认'] = e['id'] == dft
    return out


def get_engine(eid=''):
    eid = eid or load_settings().get('默认引擎') or DEFAULT_ENGINE
    e = next((x for x in engines() if x['id'] == eid), None)
    if not e:
        raise KBError(f'没有这个 AI 引擎：{eid}')
    return e


def engine_bin(e):
    c = os.path.expanduser(e.get('命令') or '')
    found = shutil.which(c) if c and '/' not in c else (c if c and os.access(c, os.X_OK) else '')
    if not found and c and '/' not in c:
        found = next((x for x in (f'/opt/homebrew/bin/{c}', f'/usr/local/bin/{c}', str(Path.home() / '.local/bin' / c),
                                  str(Path.home() / '.npm-global/bin' / c)) if Path(x).exists()), '')
    if not found:
        raise KBError(f'找不到 {e["名称"]} 的命令「{e.get("命令")}」：请先安装，或在「⚙ 设置 · AI 引擎」里填可执行文件的绝对路径')
    return found


def engine_cmd(e, prompt, title='kb', resume_id=''):
    """拼出运行命令（参数逐个替换变量，不经过 shell）。"""
    args = e.get('续跑参数') if resume_id and e.get('续跑参数') else e.get('启动参数')
    v = {'提示词': prompt, '标题': title, '会话ID': resume_id}
    return [engine_bin(e)] + [re.sub(r'\{(提示词|标题|会话ID)\}', lambda mm: v[mm.group(1)], a) for a in args or []]


def engine_status(e):
    """装没装、版本、有没有接入知识库 MCP（读各自的配置文件判断，判断不了为 None）。"""
    try:
        b = engine_bin(e)
    except KBError:
        return {'已安装': False, '版本': '', '已接入': None}
    try:
        r = subprocess.run([b, '--version'], capture_output=True, text=True, timeout=15)
        out = (r.stdout or r.stderr).strip()
        ver = out.splitlines()[0][:80] if out else ''
    except (OSError, subprocess.TimeoutExpired):
        ver = ''
    name = Path(b).name
    linked = None
    try:
        if name == 'claude':
            linked = 'kb' in (json.loads(read_text(Path.home() / '.claude.json')).get('mcpServers') or {})
        elif name == 'codex':
            linked = bool(re.search(r'^\[mcp_servers\.kb\]', read_text(Path.home() / '.codex' / 'config.toml'), re.M))
        elif name == 'hermes':
            t = read_text(Path.home() / '.hermes' / 'config.yaml')
            linked = bool(re.search(r'^mcp_servers:\s*\n(?:[ \t].*\n)*?[ \t]+kb:', t + '\n', re.M))
    except (OSError, ValueError):
        linked = False if name in ('claude', 'codex', 'hermes') else None
    return {'已安装': True, '版本': ver, '已接入': linked}


def engine_link(eid):
    """网页「接入知识库」：运行引擎的接入命令，把知识库 MCP 注册给它。"""
    import shlex
    e = get_engine(eid)
    if not e.get('接入命令'):
        raise KBError(f'{e["名称"]} 没有接入命令，请按说明手动接入')
    py, kbpy = _kb_cmd()
    argv = shlex.split(e['接入命令'].replace('{kb}', f'"{py}" "{kbpy}" serve'))
    if argv and argv[0] == e.get('命令'):
        argv[0] = engine_bin(e)
    r = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    if r.returncode and 'already' not in (r.stderr + r.stdout).lower():
        raise KBError(f'接入失败：{(r.stderr or r.stdout).strip()[:500]}')
    return f'已把知识库接入 {e["名称"]}' + (f'：{r.stdout.strip()[:200]}' if r.stdout.strip() else '')


def engine_link_help(e):
    py, kbpy = _kb_cmd()
    return (e.get('接入配置') or '').replace('{python}', py).replace('{kbpy}', kbpy)


def save_engine(data):
    s = load_settings()
    over = s.setdefault('引擎', {})
    e = {k: data[k] for k, *_ in ENGINE_FIELDS if k in data}
    for k in ('启动参数', '续跑参数'):
        if isinstance(e.get(k), str):
            e[k] = [x.strip() for x in e[k].splitlines() if x.strip()]
    if e.get('输出格式') and e['输出格式'] not in ENGINE_FIELDS[5][2][7:].split('|'):
        raise KBError('输出格式不对')
    if not (e.get('名称') or '').strip() or not (e.get('命令') or '').strip():
        raise KBError('名称和命令不能为空')
    if '{提示词}' not in ' '.join(e.get('启动参数') or []):
        raise KBError('启动参数里要有 {提示词}')
    eid = (data.get('id') or '').strip()
    if not eid:
        eid = 'engine-' + uuid.uuid4().hex[:6]
    elif eid not in BUILTIN_ENGINES and eid not in over:
        raise KBError(f'没有这个 AI 引擎：{eid}')
    if any(x['名称'] == e['名称'] and x['id'] != eid for x in engines()):
        raise KBError(f'已经有叫「{e["名称"]}」的引擎了')
    over[eid] = e
    save_settings(s)
    return f'已保存 AI 引擎「{e["名称"]}」', eid


def delete_engine(eid):
    s = load_settings()
    over = s.setdefault('引擎', {})
    if eid not in over:
        raise KBError('内置引擎没有修改过，不用恢复' if eid in BUILTIN_ENGINES else f'没有这个 AI 引擎：{eid}')
    name = get_engine(eid)['名称']
    over.pop(eid)
    if eid not in BUILTIN_ENGINES:
        if s.get('默认引擎') == eid:
            s['默认引擎'] = DEFAULT_ENGINE
        for n in period_names():
            d = PERIODS / n
            m = load_meta(d)
            if m.get('AI引擎') == eid:
                m.pop('AI引擎')
                save_meta(d, m)
    save_settings(s)
    return f'已恢复「{name}」的默认设置' if eid in BUILTIN_ENGINES else f'已删除 AI 引擎「{name}」'


def set_default_engine(eid):
    e = get_engine(eid)
    s = load_settings()
    s['默认引擎'] = e['id']
    save_settings(s)
    return f'默认 AI 引擎改为「{e["名称"]}」'


def set_period_engine(period, eid):
    d = period_dir(period)
    e = get_engine(eid) if eid else None
    m = load_meta(d)
    if (m.get('AI引擎') or '') == (eid or ''):
        return '没有变化'
    if e:
        m['AI引擎'] = e['id']
    else:
        m.pop('AI引擎', None)
    save_meta(d, m)
    log(d, 'AI 引擎', e['名称'] if e else f'默认（{get_engine()["名称"]}）')
    return f'「{d.name}」的 AI 引擎改为「{e["名称"] if e else "默认"}」'


def period_engine(m):
    """开发会话用的引擎：会话里记的 > 这一期选的 > 默认。"""
    for eid in ((m.get('开发会话') or {}).get('引擎'), m.get('AI引擎')):
        if eid:
            try:
                return get_engine(eid)
            except KBError:
                pass
    return get_engine()


_CLEAN_ENV = ('CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT', 'CLAUDE_CODE_SSE_PORT')


def engine_popen(e, prompt, title, logf, cwd, resume_id='', env_extra=None):
    """后台启动引擎，输出写进日志文件（第一行记下用的引擎和输出格式，解析日志时用）。"""
    cmd = engine_cmd(e, prompt, title, resume_id)
    env = {k: v for k, v in os.environ.items() if k not in _CLEAN_ENV}
    env.update(env_extra or {})
    with open(logf, 'ab') as fh:
        fh.write((json.dumps({'type': 'kb.engine', 'engine': e['id'], 'format': e.get('输出格式')}, ensure_ascii=False)
                  + '\n').encode())
        fh.flush()
        return subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                                start_new_session=True, env=env)


def engine_run(e, prompt, cwd, timeout=300):
    """前台跑一次，返回 (退出码, 解析出的结果)。"""
    env = {k: v for k, v in os.environ.items() if k not in _CLEAN_ENV}
    try:
        r = subprocess.run(engine_cmd(e, prompt, 'kb·单次'), cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise KBError(f'{e["名称"]} {timeout // 60} 分钟没有返回')
    res = _result_of(r.stdout, e.get('输出格式'), limit=200000)
    if not res.get('结果'):
        res['结果'] = (r.stdout.strip() or r.stderr.strip())[-2000:]
    return r.returncode, res


def engine_test(eid):
    """网页「测试」：让引擎调用一次 kb_overview 并回复，验证能运行、能用知识库工具。"""
    e = get_engine(eid)
    t0 = time.time()
    code, res = engine_run(e, '这是知识库的连通性测试。请调用知识库 MCP 工具 kb_overview（在你的工具列表里可能叫 '
                              'mcp__kb__kb_overview、mcp_kb_kb_overview 之类），然后只回复一行：「测试成功：共 N 期」。'
                              '调用不到就回复「测试失败：」加原因。', ROOT)
    return {'成功': code == 0 and '测试成功' in (res.get('结果') or ''), '退出码': code,
            '结果': (res.get('结果') or '').strip()[:1500], '耗时': round(time.time() - t0)}


def _front_desc(text):
    """SKILL.md / 命令 md 头部的 description（支持 >- 多行）。"""
    m = re.match(r'^---\n(.*?)\n---', text, re.S)
    if not m:
        line = next((x.strip('# ').strip() for x in text.splitlines() if x.strip()), '')
        return line[:200]
    fm = m.group(1)
    d = re.search(r'^description:\s*(.*?)(?=^\S[^\n]*:|\Z)', fm, re.S | re.M)
    if not d:
        return ''
    v = re.sub(r'^[>|]-?\s*', '', d.group(1).strip())
    return re.sub(r'\s+', ' ', v).strip(' "\'')[:300]


def list_commands():
    """本机可用的技能和斜杠命令（个人的 + 各期开发仓库、已登记仓库里的），给「从命令 / 技能添加流程」选。"""
    home = Path.home() / '.claude'
    roots = {}
    for n in period_names():
        r = load_meta(PERIODS / n).get('开发仓库')
        if r and Path(r).is_dir():
            roots[r] = Path(r).name
    for k, v in load_repos().items():
        if Path(v['路径']).is_dir():
            roots.setdefault(v['路径'], k)
    out, seen = [], set()

    def add(p, kind, base=None):
        name = '/' + (p.parent.name if p.name == 'SKILL.md' else p.stem)
        key = (name, str(base or ''))
        if key in seen:
            return
        seen.add(key)
        try:
            desc = _front_desc(read_text(p))
        except OSError:
            desc = ''
        out.append({'名称': name, '类型': kind, '路径': str(p), '说明': desc,
                    '仓库': str(base) if base else '', '相对路径': str(p.relative_to(base)) if base else ''})
    for p in sorted((home / 'skills').glob('*/SKILL.md')):
        add(p, '个人技能')
    for p in sorted((home / 'commands').glob('*.md')):
        add(p, '个人命令')
    for r, nm in roots.items():
        base = Path(r)
        for p in sorted((base / '.claude' / 'skills').glob('*/SKILL.md')):
            add(p, f'仓库技能（{nm}）', base)
        for p in sorted((base / '.claude' / 'commands').glob('*.md')):
            add(p, f'仓库命令（{nm}）', base)
    return out


def _quick_flow(c):
    name = c['名称']
    return dict(
        BUILTIN_FLOWS['generic'], 名称=name, 说明=(c.get('说明') or '')[:200] or f'按 {name} 开发',
        识别文件=[c['相对路径']] if c.get('相对路径') else [],
        文档目录方式='模板', 文档目录模板='claude_project_memory/{分支目录}', 准备方式='通用', 流程配置文件='',
        开发步骤=f"""1. kb_dev_prepare 准备资料（本期需求、设计稿、接口文档的本地副本在 {{资料目录}}）。
2. 用 {name} 推进：反复执行 {name}，直到它报告全部完成。{name} 需要的物料优先填 {{资料目录}} 里的本地文件路径和本期登记的链接。
3. {name} 停下来等人填写 / 回答 / 确认文档时，不要干等：把要确认的内容用 kb_ask 发到网页，拿到回答后写回对应文档，再继续执行 {name}。""",
        确认点=f'{name} 停下来等人填写或确认的地方（待确认问题、方案确认等）、方案取舍、缺少账号或环境、操作被权限拦截等',
        续跑提示=f'先看 {name} 的产物文档确认实际进度，然后接着执行 {name}',
        开发约定=f'- 开发流程用 {name}：反复执行 {name} 推进，需要人确认时用 kb_ask 发到网页',
        需求变更提示=f'先 kb_dev_prepare 同步资料副本，再按 {name} 的规则补充物料、更新方案和任务；影响已写代码的用 kb_ask 确认，并 kb_log 记录',
        进度类型='无', 任务清单文件='')


def flow_draft(path, use_ai=False):
    """从技能 / 命令生成开发流程草稿（不保存）：快速模板，或让 Claude 读说明后填写。"""
    c = next((x for x in list_commands() if x['路径'] == path), None)
    if not c:
        raise KBError(f'没有找到这个技能 / 命令：{path}')
    draft = _quick_flow(c)
    if not use_ai:
        return draft
    p = Path(path)
    files = []
    if p.name == 'SKILL.md':
        files = [str(x.relative_to(p.parent)) for x in sorted(p.parent.rglob('*'))
                 if x.is_file() and '__pycache__' not in x.parts][:80]
    fields = '\n'.join(f'- {k}（{typ}）：{help}' for k, _, typ, help in FLOW_FIELDS)
    example = {k: v for k, v in BUILTIN_FLOWS['generic'].items()}
    prompt = f"""请为「本地知识库」生成一套开发流程配置。知识库网页点「开始开发」后，会在代码仓库里后台无人值守地启动 Claude Code，按这套配置开发；
人不在终端前，需要人确认的地方必须用 kb_ask 发到网页、kb_wait_answer 等回答（原流程里「等用户填写 / 回答文档再执行下一步」都要改成这样）。
开发前 kb_dev_prepare 会把本期资料（需求、设计稿、接口文档、文字资料）拷到 {{资料目录}}，可以直接当物料用。

要接入的流程是 {c['名称']}（{c['类型']}），它的说明文件 {path} 内容如下：
<<<
{read_text(p)[:40000]}
>>>
{('同目录文件：' + '、'.join(files)) if files else ''}

配置项（类型 select:A|B 表示只能取其中之一；lines 用 JSON 数组）：
{fields}
可用变量：{json.dumps(FLOW_VARS, ensure_ascii=False)}；文档目录模板 / 命令里还可用 {{分支目录}}（分支名的 / 换成 _）。

参考：通用模板的配置是
{json.dumps(example, ensure_ascii=False, indent=1)}

要求：
- 文档目录要和该流程实际产物目录一致（从说明里找，例如工作目录按分支名生成就用 {{分支目录}}），能用模板就用模板，不要编造脚本。
- 个人技能 / 个人命令任何仓库都能用，识别文件留空数组；仓库命令填它在仓库里的相对路径：{c['相对路径'] or '（不是仓库命令）'}。
- 进度类型：流程有逐条勾选的任务清单（- [ ] / - [x]）就用「任务清单」，任务清单文件填相对文档目录的文件名；否则「无」。准备方式用「通用」，除非流程本身就是 SDD（有 sdd-start.md 模板）。
- 开发步骤写成编号步骤，写清用什么命令推进、推进到什么状态算完成、停下等人时怎么用 kb_ask。
- 只输出一个 JSON 对象，键为上面的配置项名称，不要输出其他文字，不要调用任何工具。"""
    eng = get_engine()
    code, res = engine_run(eng, prompt, ROOT)
    try:
        got = json.loads(re.search(r'\{.*\}', res.get('结果') or '', re.S).group(0))
    except (ValueError, AttributeError):
        raise KBError(f'{eng["名称"]} 没有返回可用的配置，可以先用「快速生成」再手动改：{(res.get("结果") or "")[:300]}')
    for k, _, typ, _ in FLOW_FIELDS:
        v = got.get(k)
        if v is None:
            continue
        if typ == 'lines':
            v = [str(x) for x in v] if isinstance(v, list) else [x.strip() for x in str(v).splitlines() if x.strip()]
        elif typ.startswith('select:') and v not in typ[7:].split('|'):
            continue
        else:
            v = str(v)
        draft[k] = v
    draft['名称'] = draft.get('名称') or c['名称']
    return draft


# ---------------------------------------------------------------- 开发准备（仓库、分支、文档目录、资料副本）
# 按这一期的开发流程：认出代码仓库和分支、算出文档目录，把本期资料拷过去并整理候选链接（SDD 还会准备 sdd-start.md）。


PATH_RE = re.compile(r'(?:~|/(?:Users|Volumes|home|opt|private|data|srv))/[^\s，。；;、()（）【】「」"\'<>]+')


def _git(root, *args, timeout=15):
    try:
        return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 1, '', 'timeout')


def _git_root(p):
    p = Path(p).expanduser()
    if not p.is_dir():
        return None
    r = _git(p, 'rev-parse', '--show-toplevel')
    return Path(r.stdout.strip()).resolve() if r.returncode == 0 and r.stdout.strip() else None


def want_branches(d, m):
    """本期登记的开发分支：「分支」类文字资料，或标题 / 内容写了「分支」的文字资料里的分支名；网页确认过的排最前。"""
    out = [m['开发分支']] if m.get('开发分支') else []
    for n in notes_of(d, m=m):
        title, body = n.get('标题') or '', URL_RE.sub(' ', n.get('内容') or '')
        if n['类型'] != '分支' and '分支' not in title + body and 'branch' not in (title + body).lower():
            continue
        out += BRANCH_RE.findall(body)
        for f in flows():
            if f.get('分支规则'):
                try:
                    out += [x if isinstance(x, str) else x[0] for x in
                            re.findall(r'(?<![\w/.-])(?:' + f['分支规则'] + r')(?![\w/.-])', body)]
                except re.error:
                    pass
        rest = re.sub(r'^.*?(?:分支|branch)\s*[:：]?\s*', '', body.strip(), flags=re.I) if re.search(r'分支|branch', body, re.I) else body.strip()
        if re.fullmatch(r'[A-Za-z][\w./-]{2,}', rest):     # 整条就是一个分支名
            out.append(rest)
    return [x for x in dict.fromkeys(out) if not PATH_RE.fullmatch(x)]


def repo_candidates(d, m):
    """开发仓库候选（都是本机 git 仓库）：网页确认过的、关联的已登记仓库、文字资料里写的本地路径。"""
    out = {}

    def add(p, why, hint):
        root = _git_root(p)
        if not root:
            return
        x = out.setdefault(str(root), {'路径': str(root), '依据': [], '明确': False})
        x['依据'].append(why)
        x['明确'] = x['明确'] or hint
    if m.get('开发仓库'):
        add(m['开发仓库'], '网页上确认过', True)
    repos = load_repos()
    for r in m.get('关联仓库') or []:
        if r in repos:
            add(repos[r]['路径'], f'关联仓库 {r}', True)
    for n in notes_of(d, m=m):
        title, body = n.get('标题') or '', n.get('内容') or ''
        hint = bool(re.search(r'代码|工程|仓库|项目|repo', title, re.I)
                    or re.search(r'(代码|工程|仓库|项目)(路径|目录|地址)', body))
        for x in PATH_RE.findall(URL_RE.sub(' ', f'{title} {body} {n.get("链接") or ""}')):
            add(x.rstrip('.,:：'), f'文字资料 {n["编号"]}「{note_title(n)}」', hint)
    want = want_branches(d, m)
    for x in out.values():
        root = Path(x['路径'])
        f = flow_for(m, root)
        x['可用'], x['流程'] = bool(f), f['名称'] if f else ''
        x['当前分支'] = _git(root, 'branch', '--show-current').stdout.strip()
        x['有开发分支'] = any(_git(root, 'rev-parse', '--verify', '--quiet', b).returncode == 0 for b in want)
    return list(out.values())


def _pick_repo(cands, m):
    """候选里能确定是哪个就返回，不能就返回 None（交给用户选）。"""
    c = [x for x in cands if x['可用']]
    for x in c:
        if '网页上确认过' in x['依据']:
            return x
    for test in (lambda x: x['明确'], lambda x: True):
        hit = [x for x in c if test(x)]
        if len(hit) == 1:
            return hit[0]
        if len(hit) > 1:          # 再按开发分支挑：当前就在开发分支上 / 有开发分支的
            for t2 in (lambda x: x['有开发分支'] and x['当前分支'] in (m.get('_want') or []), lambda x: x['有开发分支']):
                h2 = [x for x in hit if t2(x)]
                if len(h2) == 1:
                    return h2[0]
            return None
    return None


def _sdd_repo(d, m, repo):
    if repo:
        root = _git_root(repo)
        if not root:
            repos = load_repos()
            if repo not in repos:
                raise KBError(f'不是本机的 git 仓库，也没有登记这个仓库名：{repo}')
            root = Path(repos[repo]['路径'])
        return root
    cands = repo_candidates(d, m)
    m = dict(m, _want=want_branches(d, m))
    x = _pick_repo(cands, m)
    if x:
        return Path(x['路径'])
    tip = '；'.join(f'{x["路径"]}（{"、".join(x["依据"])}{"，流程 " + x["流程"] if x["可用"] else "，没有匹配的开发流程"}）' for x in cands)
    if cands and not any(x['可用'] for x in cands):
        why = (f'找到了代码仓库，但都不符合开发流程（{"这一期选定「" + get_flow(m["开发流程"])["名称"] + "」" if m.get("开发流程") else "自动匹配"}）：'
               '请在开发面板为这一期选择流程（如「通用模板」），或在「⚙ 设置」里新建本组的流程')
        raise KBNeed(why + f'。候选：{tip}', {'需要': '仓库', '候选': cands, '分支': m['_want'], '说明': why})
    raise KBNeed('确定不了开发用哪个代码仓库，请用 repo 指定（仓库名或绝对路径）' +
                 (f'，候选：{tip}' if cands else '；本期文字资料里没有找到本机代码路径'),
                 {'需要': '仓库', '候选': cands, '分支': m['_want']})


def _sdd_sections(text):
    """sdd-start.md 的二级栏目 → 是否已填（去掉注释和模板自带的「前端框架:」这类空键）。"""
    res, cur = {}, None
    for line in re.sub(r'<!--.*?-->', '', text, flags=re.S).splitlines():
        if line.startswith('## '):
            cur = line[3:].strip()
            res[cur] = False
        elif cur and line.strip() and not re.fullmatch(r'\s*[^:：]+[:：]\s*', line):
            res[cur] = True
    return res


def _sdd_slot(url, cat, has_new_doc):
    host = urlparse(url).hostname or ''
    low = unquote(url).lower()
    if 'figma.com' in host:
        return 'Figma 设计稿'
    if 'lanhu' in host:
        return '备注（蓝湖，SDD 不能下载）'
    if re.search(r'\.(mp4|mov|zip|rar|apk|pdf|docx?|xlsx?)(\?|$)', low):
        return '备注（参考文件）'
    if cat == '接口文档':
        return '服务端接口'
    if 'axure' in host:
        if 'prd' in low:
            return '新版产品文档链接' if has_new_doc else '内网文档链接（Axure）'
        return '内网文档链接（Axure）'
    if 'confluence' in host or 'wiki' in host:
        return 'Confluence PRD 链接（需求总表 / 入口页按需取舍）'
    return '备注'


def _no_flow_msg(m, root):
    if m.get('开发流程'):
        f = get_flow(m['开发流程'])
        return f'{root} 不符合这一期选定的开发流程「{f["名称"]}」（缺少：{"、".join(x for x in f["识别文件"] if not (Path(root) / x).exists())}），请换仓库或在开发面板换流程'
    return f'{root} 没有匹配的开发流程，请在开发面板为这一期选择流程，或在「⚙ 设置」里新建本组的流程'


def _dev_target(d, m, repo='', store=''):
    """目标仓库、当前分支、开发流程、文档目录。"""
    root = _sdd_repo(d, m, repo)
    f = flow_for(m, root)
    if not f:
        raise KBNeed(_no_flow_msg(m, root), {'需要': '仓库', '候选': repo_candidates(d, m), '分支': want_branches(d, m),
                                              '说明': _no_flow_msg(m, root)})
    branch = _git(root, 'branch', '--show-current').stdout.strip()
    want = want_branches(d, m)
    if want and branch not in want:
        dirty = [x for x in _git(root, 'status', '--porcelain', '--untracked-files=no').stdout.splitlines() if x.strip()]
        raise KBNeed(f'{root.name} 当前分支是「{branch}」，本期登记的开发分支是「{"、".join(want)}」。'
                     '文档目录按分支生成，请先切到开发分支（AI 不要替用户切分支）',
                     {'需要': '分支', '仓库': str(root), '当前分支': branch, '分支': want,
                      '未提交': dirty[:30], '未提交数': len(dirty)})
    return root, branch, f, flow_docs(f, root, branch, d.name, store)


def dev_prepare(name, repo='', store=''):
    """开发前准备：按开发流程定位文档目录，把本期资料拷过去，整理候选链接；SDD 流程另外准备 sdd-start.md。"""
    d = period_dir(name)
    m = load_meta(d)
    if m.get('状态') not in DEV_OK:
        raise KBError(f'「{d.name}」当前状态是「{m.get("状态")}」，用户尚未批准开发。'
                      f'请提醒用户确认材料齐全后，在终端运行 kb approve "{d.name}"，或在知识库网页点「开始开发」')
    root, branch, f, docs = _dev_target(d, m, repo, store)
    if m.get('SDD目录') != str(docs):
        m = load_meta(d)
        m['SDD目录'] = str(docs)
        save_meta(d, m)
    sdd = f.get('准备方式') == 'SDD'
    KB_DIR = f.get('资料目录名') or 'kb-materials'
    docs.mkdir(parents=True, exist_ok=True)
    created = []
    if sdd:
        for sub in ('cache', 'tests/automation', 'tests/blackbox'):
            (docs / sub).mkdir(parents=True, exist_ok=True)
        tpl = root / '.claude' / 'sdd-templates'
        for fn, t in (('sdd-start.md', 'sdd-start-config-template.md'), ('sdd-status.md', 'sdd-status-template.md')):
            if not (docs / fn).exists() and (tpl / t).exists():
                shutil.copyfile(tpl / t, docs / fn)
                created.append(fn)
        start = docs / 'sdd-start.md'
        if not start.exists():
            raise KBError(f'{tpl} 里没有 sdd-start 模板，请先在仓库里运行 /sdd-start 生成 {start} 后再调用')

    # 资料副本：每次重建；不进 git（图片多，而文档目录一般是入库的）
    out = docs / KB_DIR
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    for c in CATS + [SRC_DIR]:
        if (d / c).exists():
            shutil.copytree(d / c, out / c, ignore=shutil.ignore_patterns(HIST, '.*'))
    if BASE_MD.exists():
        shutil.copyfile(BASE_MD, out / '基础信息.md')
    (out / '.gitignore').write_text('*\n', 'utf-8')
    n_files = sum(1 for x in out.rglob('*') if x.is_file()) - 1

    srcs = m.get('来源') or []
    idx = [f'# 知识库资料：{d.name}', '',
           f'> 自动生成（{now()}，kb_dev_prepare），请勿手改；知识库更新后重新调用会覆盖。本目录不进 git。',
           f'> 期说明：{m.get("说明") or "无"}', '',
           '| 目录 | 用途 |', '|---|---|',
           '| 需求/ | 需求原文（PRD、需求表条目、口述需求）；需求/原型图/ 只用于理解交互，UI 不以它为准 |',
           '| 设计图/ | 要实现的设计稿（Figma 画板 PNG + 设计规格.md），UI 以此为准 |',
           '| 接口文档/ | 接口文档、协议说明 |', '| 其他资料/ | 分支、链接、环境等零散资料 |',
           f'| {SRC_DIR}/ | 导入时的整页原文快照 |',
           '| 基础信息.md | 所有期共用的账号、测试账号、代理 / VPN、环境配置（机密只显示掩码，用 kb_base_secret 读取） |',
           '', '## 来源', '']
    for x in srcs:
        fs = x.get('文件') or []
        n_proto = sum(PROTO_DIR in f for f in fs)
        idx += [f'### {x["编号"]} ［{x.get("类型", "资料")}］{x["标题"]}' + (f' · {x["条目"]}' if x.get('条目') else ''),
                f'- 地址：{x["地址"]}', f'- 简介：{x.get("简介") or ""}',
                '- 文件：' + '、'.join(f for f in fs if PROTO_DIR not in f)
                + (f'（另有原型图 {n_proto} 张）' if n_proto else ''), '']
    ns = notes_of(d, m=m)
    if ns:
        idx += ['## 文字资料', ''] + [note_md(n).replace('## ', f'### ［{n["分类"]}］', 1) + '\n' for n in ns]
    (out / 'README.md').write_text('\n'.join(idx) + '\n', 'utf-8')

    secs, has_new = {}, False
    if sdd:
        secs, has_new = _sdd_note_ref(start, KB_DIR)

    links = {}

    def add(url, cat, what):
        url = url.rstrip('.,;')
        if url not in links:
            links[url] = (_sdd_slot(url, cat, has_new) if sdd else _plain_slot(url, cat), what)
    for x in srcs:
        if x.get('作废'):
            continue
        cat = next((c for c in CATS if any(f.startswith(c + '/') for f in x.get('文件') or [])), '')
        add(x['地址'], cat, f'来源 {x["编号"]}《{x["标题"]}》{x.get("条目") or ""}：{(x.get("简介") or "")[:80]}')
    for n in ns:
        for u in ([n['链接']] if n.get('链接') else []) + _urls(n.get('内容') or ''):
            add(u, n['分类'], f'文字资料 {n["编号"]} {note_title(n)}')
    for fp in sorted((d / '设计图').rglob('*.md')) if (d / '设计图').exists() else []:
        if HIST in fp.parts or fp.name.endswith(NOTE_SUFFIX) or fp.name == NOTES_FILE:
            continue
        for u in _urls(read_text(fp)):
            add(u, '设计图', f'设计图/{fp.relative_to(d / "设计图")}')
    by = {}
    for u, (slot, what) in links.items():
        by.setdefault(slot, []).append(f'  - {u}\n    {what}')

    log(d, '开发准备', f'{f["名称"]} · {root.name}（{branch}）→ {docs}；资料 {n_files} 个文件 → {KB_DIR}/')
    if not sdd:
        v = dict(期名=d.name, 仓库=str(root), 分支=branch, 文档目录=str(docs), 资料目录=str(out))
        res = [f'已按开发流程「{f["名称"]}」准备好资料：{root.name}（分支 {branch}）',
               f'- 文档目录：{docs}', f'- 资料副本：{out}/（{n_files} 个文件，不进 git），索引 {KB_DIR}/README.md',
               '', '# 本期链接（按资料分类）']
        for slot, items in by.items():
            res += [f'- {slot}'] + items
        if not links:
            res.append('（本期没有登记链接）')
        res += ['', f'# 接下来按开发流程「{f["名称"]}」推进', flow_text(f, '开发步骤', **v)]
        return '\n'.join(res)
    return _sdd_prepare_result(d, root, branch, docs, start, created, out, n_files, secs, by, links, KB_DIR)


def _plain_slot(url, cat):
    host = urlparse(url).hostname or ''
    if 'figma.com' in host or 'lanhu' in host:
        return '设计稿'
    return cat or '其他资料'


def _sdd_note_ref(start, KB_DIR):
    """在 sdd-start.md「备注」里引用资料副本；返回栏目填写情况、是否有新版产品文档栏。"""
    text = start.read_text('utf-8')
    ref = f'知识库资料：{KB_DIR}/README.md（本期需求、设计稿、接口、文字资料的本地副本，SDD 下载失败或需要补充时参考）'
    if f'知识库资料：{KB_DIR}/' not in text:
        lines = text.rstrip('\n').split('\n')
        at = next((i for i, l in enumerate(lines) if l.startswith('## ') and '备注' in l), None)
        if at is None:
            lines += ['', '## 备注（可选）', '', ref]
        else:
            end = next((i for i in range(at + 1, len(lines)) if lines[i].startswith('## ')), len(lines))
            lines.insert(end, ref)
        text = '\n'.join(lines) + '\n'
        start.write_text(text, 'utf-8')
    secs = _sdd_sections(text)
    return secs, any('新版产品文档' in k for k in secs)


def _sdd_prepare_result(d, root, branch, docs, start, created, out, n_files, secs, by, links, KB_DIR):
    res = [f'已为 SDD 准备好资料：{root.name}（分支 {branch}）',
           f'- PROJECT_DOCS：{docs}',
           f'- sdd-start.md：{start}' + ('（按仓库模板新建）' if 'sdd-start.md' in created else '（已存在，保留原内容）'),
           f'- 资料副本：{out}/（{n_files} 个文件，不进 git），索引 {KB_DIR}/README.md，已写进 sdd-start.md「备注」',
           '- sdd-start.md 栏目：已填 ' + ('、'.join(k for k, v in secs.items() if v) or '无')
           + '；空 ' + ('、'.join(k for k, v in secs.items() if not v) or '无'),
           '', '# 候选链接（按 SDD 栏目建议，最终按 sdd-start.md 各栏注释判断）']
    for slot, items in by.items():
        res += [f'- {slot}'] + items
    if not links:
        res.append('（本期没有登记链接）')
    res += ['', '# 接下来由你完成（不用问用户）',
            '1. 读 sdd-start.md，按每栏注释里的格式要求把上面的链接填进对应的【空】栏；已填的栏不改，和知识库不一致的列给用户。',
            '2. 功能名称用本期需求名；负责范围按需求和文字资料写本端（如 Android 客户端）负责的部分；'
            '接口相关的文字资料（协议、字段）写进「服务端接口」作为 API 修改描述；拿不准的放「备注」，不要编造链接。',
            '3. 填完运行 /sdd-next 推进（物料由 SDD 自己的 /sdd-material 下载）；SDD 下载失败（如 Confluence 需登录）时，'
            f'用 {KB_DIR}/ 里的同名资料补充，并用 kb_log 记录。']
    return '\n'.join(res)





sdd_prepare = dev_prepare      # 旧名，开发中的会话可能还在用


# ---------------------------------------------------------------- 基础知识库
# 所有期共用的基础信息：网站账号、测试账号、Wi-Fi / 代理 / VPN、环境配置等。
# 机密字段（密码、令牌）只存 macOS 钥匙串（服务名 kb-base），json / md / 索引 / 网页默认都只显示掩码。
BASE_FILE = BASE / '基础信息.json'
BASE_MD = BASE / '基础信息.md'
BASE_LOG = BASE / '记录.md'
BASE_CATS = ['账号密码', '测试账号', '网络代理', 'VPN', '环境配置', '其他']
KC_SERVICE = os.environ.get('KB_KC_SERVICE', 'kb-base')
MASK = '●●●●●●'


def _kc(*args, check=True):
    r = subprocess.run(['security', *args], capture_output=True, text=True)
    if check and r.returncode:
        raise KBError(f'钥匙串操作失败：{(r.stderr or r.stdout).strip()[:200]}')
    return r


def _kc_set(acct, value):
    _kc('add-generic-password', '-U', '-s', KC_SERVICE, '-a', acct, '-w', value)


def _kc_get(acct):
    r = _kc('find-generic-password', '-s', KC_SERVICE, '-a', acct, '-w', check=False)
    return r.stdout.rstrip('\n') if r.returncode == 0 else None


def _kc_del(acct):
    _kc('delete-generic-password', '-s', KC_SERVICE, '-a', acct, check=False)


def _base_log(action, content):
    BASE.mkdir(exist_ok=True)
    if not BASE_LOG.exists():
        BASE_LOG.write_text('# 基础知识库 · 记录\n\n', 'utf-8')
    with BASE_LOG.open('a', encoding='utf-8') as f:
        f.write(f'- {now()} ｜ {action} ｜ {content}\n')


def base_load():
    return json.loads(BASE_FILE.read_text('utf-8')) if BASE_FILE.exists() else {'条目': [], '序号': 0}


def _field_md(fd):
    return f'{fd["名"]}：{MASK}（钥匙串）' if fd.get('机密') else f'{fd["名"]}：{fd.get("值", "")}'


def base_entry_md(e, head='##'):
    out = [f'{head} {e["编号"]} ［{e["分类"]}］{e["名称"]}']
    if e.get('适用'):
        out.append(f'- 适用：{e["适用"]}')
    out += [f'- {_field_md(fd)}' for fd in e.get('字段') or []]
    if e.get('附件'):
        out.append('- 附件：' + '、'.join(e['附件']))
    if e.get('备注'):
        out += ['', e['备注'].strip()]
    return '\n'.join(out)


def _base_save_all(data):
    BASE.mkdir(exist_ok=True)
    BASE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), 'utf-8')
    es = data['条目']
    md = ['# 基础知识库', '', '> 自动生成，请勿手改（用网页「🗂 基础信息」或让 Claude 修改）。所有期共用；机密字段只存钥匙串，这里只显示掩码。', '']
    for c in BASE_CATS:
        part = [e for e in es if e['分类'] == c]
        if part:
            md += [f'# {c}', ''] + [base_entry_md(e) + '\n' for e in part]
    BASE_MD.write_text('\n'.join(md) + '\n', 'utf-8')
    index_docs()


def base_save(id='', category='', name='', fields=None, scope='', note='', file='', delete=False, by='Claude'):
    """新增 / 修改 / 删除一条基础信息。fields：[{名, 值, 机密}]；修改时机密字段值留空表示不改。"""
    data = base_load()
    es = data['条目']
    e = next((x for x in es if x['编号'] == id), None) if id else None
    if id and not e:
        raise KBError(f'没有这条基础信息：{id}')
    if delete:
        for fd in e.get('字段') or []:
            if fd.get('机密'):
                _kc_del(f'{e["编号"]}/{fd["名"]}')
        es.remove(e)
        _base_save_all(data)
        _base_log('删除', f'{e["编号"]} {e["名称"]}（{by}）')
        return f'已删除基础信息 {e["编号"]} {e["名称"]}'
    if not e:
        if not (name or '').strip():
            raise KBError('名称不能为空')
        data['序号'] = data.get('序号', 0) + 1
        e = {'编号': f'B{data["序号"]:03d}', '分类': '其他', '名称': '', '适用': '', '字段': [], '备注': '', '附件': [],
             '创建时间': now()}
        es.append(e)
        action = '新增'
    else:
        action = '修改'
    if category:
        if category not in BASE_CATS:
            raise KBError(f'分类只能是：{" / ".join(BASE_CATS)}')
        e['分类'] = category
    for k, v in (('名称', name), ('适用', scope), ('备注', note)):
        if v is not None and (v or k != '名称'):
            e[k] = (v or '').strip()
    if fields is not None:
        old = {fd['名']: fd for fd in e.get('字段') or []}
        new = []
        for fd in fields:
            nm = str(fd.get('名') or fd.get('name') or '').strip()
            if not nm:
                continue
            val = str(fd.get('值') if fd.get('值') is not None else fd.get('value') or '')
            secret = bool(fd.get('机密') if '机密' in fd else fd.get('secret'))
            acct = f'{e["编号"]}/{nm}'
            if secret:
                if val:
                    _kc_set(acct, val)
                elif not (old.get(nm, {}).get('机密') and _kc_get(acct) is not None):
                    raise KBError(f'机密字段「{nm}」还没有值')
                new.append({'名': nm, '值': '', '机密': True})
            else:
                if old.get(nm, {}).get('机密'):
                    _kc_del(acct)
                new.append({'名': nm, '值': val, '机密': False})
        for nm, fd in old.items():  # 删掉的机密字段同时清钥匙串
            if fd.get('机密') and nm not in {x['名'] for x in new}:
                _kc_del(f'{e["编号"]}/{nm}')
        e['字段'] = new
    if file:
        src = Path(file).expanduser()
        if not src.is_file():
            raise KBError(f'附件不存在：{src}')
        (BASE / '附件').mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, BASE / '附件' / src.name)
        if f'附件/{src.name}' not in e['附件']:
            e['附件'].append(f'附件/{src.name}')
    e['更新时间'] = now()
    _base_save_all(data)
    _base_log(action, f'{e["编号"]} ［{e["分类"]}］{e["名称"]}（{by}）')
    return f'已{action}基础信息：\n' + base_entry_md(e)


def base_list(query='', category=''):
    es = base_load()['条目']
    if category:
        es = [e for e in es if e['分类'] == category]
    if query:
        norm = lambda x: re.sub(r'[\s\-_./]', '', x.lower())
        terms = [norm(t) for t in query.split()]
        es = [e for e in es if all(t in norm(base_entry_md(e)) for t in terms)]
    if not es:
        return '基础知识库里没有匹配的条目。' + ('' if query or category else '（用 kb_base_save 添加）')
    return ('\n\n'.join(base_entry_md(e) for e in es)
            + f'\n\n（机密字段显示为 {MASK}；执行时确实要用，再用 kb_base_secret 读取）')


def base_secret(id, field, by='Claude', purpose=''):
    e = next((x for x in base_load()['条目'] if x['编号'] == id), None)
    if not e:
        raise KBError(f'没有这条基础信息：{id}')
    fd = next((x for x in e['字段'] if x['名'] == field), None)
    if not fd:
        raise KBError(f'{id} 没有字段「{field}」，有：{"、".join(x["名"] for x in e["字段"])}')
    if not fd.get('机密'):
        return fd.get('值', '')
    v = _kc_get(f'{id}/{field}')
    if v is None:
        raise KBError(f'钥匙串里找不到 {id} 的「{field}」')
    _base_log('读取机密', f'{id} {e["名称"]} · {field}（{by}）' + (f'：{purpose}' if purpose else ''))
    return v


def base_context():
    """给开发包 / SDD 资料用的基础信息摘要（机密只显示掩码）。"""
    es = base_load()['条目']
    if not es:
        return ''
    return '\n\n'.join(base_entry_md(e, '###') for e in es)


# ---------------------------------------------------------------- 插件（挂载到开发的某个时机自动运行）
# 插件不是知识库的一部分：放在知识库根目录「插件/<名称>/」（不进 git），或在设置里添加其他目录。
# 每个插件一个 plugin.json（名称、说明、命令、默认时机、识别文件、超时、配置项），在网页「⚙ 设置 → 插件」挂载并选时机。
# 运行时 cwd 是插件目录，环境变量带上期名、仓库、分支、文档目录和配置；退出码非 0 算失败（记成非阻断问题，不拦截开发）。
PLUGIN_DIR = ROOT / '插件'
PLUGIN_EVENTS = {'开发开始': '网页点「开始开发 / 继续开发」后、启动后台 AI 之前',
                 '开发完成': '期状态改为「已完成」时（AI 用 kb_set_status 标完成，或在网页 / 终端修改）'}
PLUGIN_ENV = {'KB_EVENT': '时机（开发开始 / 开发完成）', 'KB_PERIOD': '期名', 'KB_PERIOD_DIR': '这一期的资料目录',
              'KB_REPO': '代码仓库绝对路径', 'KB_BRANCH': '当前分支', 'KB_DOCS': '开发流程的文档目录（可能为空）',
              'KB_PLUGIN_CONFIG': '设置里填的配置项（JSON）', 'KB_ROOT': '知识库根目录', 'KB_PYTHON': '知识库用的 Python'}


def _plugin_dirs():
    out = []
    if PLUGIN_DIR.is_dir():
        out += [p for p in sorted(PLUGIN_DIR.iterdir()) if (p / 'plugin.json').is_file()]
    for x in load_settings().get('插件目录', []):
        p = Path(x).expanduser()
        if p not in out:
            out.append(p)
    return out


def plugins():
    """全部插件：plugin.json 的内容 + id、目录、是否外部目录、挂载情况（启用、时机、配置）。"""
    conf = load_settings().get('插件', {})
    out = []
    for p in _plugin_dirs():
        pid = p.name
        base = {'id': pid, '目录': str(p), '外部': p.parent != PLUGIN_DIR}
        try:
            man = json.loads(read_text(p / 'plugin.json'))
            if not isinstance(man.get('命令'), list) or not man['命令']:
                raise ValueError('「命令」要写成数组，如 ["{python}", "main.py"]')
        except (OSError, ValueError) as e:
            out.append(dict(base, 名称=pid, 错误=f'plugin.json 读取失败：{e}', 启用=False, 时机=[], 配置={}))
            continue
        c = conf.get(pid, {})
        dft = {x['键']: (x.get('默认') or (x.get('类型', '').split(':', 1)[1].split('|')[0]
                                            if x.get('类型', '').startswith('select:') else ''))
               for x in man.get('配置项', [])}
        out.append(dict(man, **base, 启用=bool(c.get('启用')),
                        时机=[e for e in c.get('时机', man.get('默认时机', [])) if e in PLUGIN_EVENTS],
                        配置=dict(dft, **c.get('配置', {}))))
    return out


def get_plugin(pid):
    p = next((x for x in plugins() if x['id'] == pid), None)
    if not p:
        raise KBError(f'没有这个插件：{pid}')
    return p


def save_plugin(pid, enabled, events, config=None):
    """网页「⚙ 设置 → 插件」：挂载 / 卸下，选时机，填配置。"""
    p = get_plugin(pid)
    bad = [e for e in events if e not in PLUGIN_EVENTS]
    if bad:
        raise KBError(f'不支持的时机：{"、".join(bad)}；可选 {" / ".join(PLUGIN_EVENTS)}')
    if enabled and not events:
        raise KBError('挂载插件至少要选一个时机')
    s = load_settings()
    s.setdefault('插件', {})[pid] = {'启用': bool(enabled), '时机': list(events),
                                   '配置': {k: str(v) for k, v in (config or {}).items()
                                            if k in {x['键'] for x in p.get('配置项', [])}}}
    save_settings(s)
    return f'插件「{p["名称"]}」' + (f'已挂载：{"、".join(events)}' if enabled else '已卸下')


def add_plugin_dir(path):
    p = Path(path).expanduser().resolve()
    if not (p / 'plugin.json').is_file():
        raise KBError(f'{p} 下没有 plugin.json')
    s = load_settings()
    ds = s.setdefault('插件目录', [])
    if p.parent == PLUGIN_DIR or str(p) in ds:
        return f'已经有这个插件：{p.name}'
    if p.name in {x.name for x in _plugin_dirs()}:
        raise KBError(f'已有同名插件「{p.name}」，请改目录名后再添加')
    ds.append(str(p))
    save_settings(s)
    return f'已添加插件目录：{p}（在列表里点「挂载」后才会运行）'


def remove_plugin_dir(pid):
    p = get_plugin(pid)
    if not p['外部']:
        raise KBError(f'「{p["名称"]}」在知识库的插件目录里，删除请直接删文件夹：{p["目录"]}')
    s = load_settings()
    s['插件目录'] = [x for x in s.get('插件目录', []) if Path(x).expanduser() != Path(p['目录'])]
    s.get('插件', {}).pop(pid, None)
    save_settings(s)
    return f'已移除插件「{p["名称"]}」（文件没动：{p["目录"]}）'


def _git_changed(root):
    """仓库里有改动的文件 → 内容摘要（插件运行前后对比，找出插件改了哪些文件）。"""
    r = _git(root, 'status', '--porcelain', '-uall')
    out = {}
    for ln in r.stdout.splitlines() if r.returncode == 0 else []:
        f = ln[3:].split(' -> ')[-1].strip('"')
        try:
            out[f] = hashlib.md5((Path(root) / f).read_bytes()).hexdigest()
        except OSError:
            out[f] = ''
    return out


def run_plugins(event, d, root='', branch='', docs='', only=''):
    """在某个时机运行挂载的插件（only：手动运行指定插件，不看挂载和时机）。返回给人 / AI 看的结果，没有插件运行时为空。"""
    res = []
    for p in plugins():
        if only and p['id'] != only:
            continue
        if not only and not (p['启用'] and event in p['时机']):
            continue
        name = p.get('名称') or p['id']
        if p.get('错误'):
            res.append(f'插件「{name}」没有运行：{p["错误"]}')
            continue
        if not root or not Path(root).is_dir():
            res.append(f'插件「{name}」没有运行：这一期还没有确定代码仓库')
            continue
        root = Path(root)
        miss = [x for x in p.get('识别文件', []) if not (root / x).exists()]
        if miss:
            if only:
                res.append(f'插件「{name}」没有运行：仓库 {root.name} 里没有 {"、".join(miss)}')
            continue
        before = _git_changed(root)
        env = dict(os.environ, KB_EVENT=event, KB_PERIOD=d.name, KB_PERIOD_DIR=str(d), KB_REPO=str(root),
                   KB_BRANCH=branch or '', KB_DOCS=str(docs or ''), KB_ROOT=str(ROOT), KB_PYTHON=sys.executable,
                   KB_PLUGIN_CONFIG=json.dumps(p['配置'], ensure_ascii=False))
        cmd = [sys.executable if x == '{python}' else x for x in p['命令']]
        t0 = time.time()
        try:
            r = subprocess.run(cmd, cwd=p['目录'], env=env, capture_output=True, text=True,
                               timeout=int(p.get('超时') or 300))
            ok, out = r.returncode == 0, (r.stdout + ('\n' + r.stderr if r.stderr.strip() else '')).strip()
        except subprocess.TimeoutExpired:
            ok, out = False, f'超时（{p.get("超时") or 300} 秒）'
        except OSError as e:
            ok, out = False, f'启动失败：{e}'
        after = _git_changed(root)
        changed = sorted(f for f in set(before) | set(after) if before.get(f) != after.get(f))
        head = (f'插件「{name}」（{event}）{"完成" if ok else "失败"}，用时 {time.time() - t0:.0f} 秒，'
                + (f'仓库 {root.name} 有 {len(changed)} 个文件改动' if changed else '没有文件改动'))
        log(d, '插件', f'{head}：{out[-1500:]}')
        if not ok:
            _add_issue(d, f'插件「{name}」运行失败（{event}）', out[-2000:], kind='工具链', source='插件',
                       key=f'插件:{p["id"]}:{event}')
        res.append(head + (f'\n{out[-3000:]}' if out else ''))
    return '\n\n'.join(res)


def run_plugin_now(pid, period, event='开发开始'):
    """手动运行一次（网页「运行一次」/ kb plugin run），用这一期的开发仓库。"""
    d = period_dir(period)
    m = load_meta(d)
    root = m.get('开发仓库') or ''
    if not root:
        raise KBError(f'「{d.name}」还没有确定开发仓库（开始开发时会确定）')
    cur = _git(Path(root), 'branch', '--show-current').stdout.strip() if Path(root).is_dir() else ''
    return run_plugins(event, d, root, cur, m.get('SDD目录', ''), only=get_plugin(pid)['id']) or '没有运行'


# ---------------------------------------------------------------- 开发会话 / 待确认 / 免打扰 / 进度
# 网页「开始开发」= 用户本人批准 + 在目标仓库后台启动 Claude Code（claude -p，auto 权限）跑 /sdd* 流程。
# 需要人确认的地方走 kb_ask → 网页回答 → kb_wait_answer；开启免打扰后由 AI 按自己的建议决策。
DEV_DIR = '开发会话'
_PROCS = {}  # 期名 → Popen（只在启动它的网页进程里有）
_TRACK = {}              # 期名 → {pid: 启动时间}：后台会话派生过的所有进程（含已脱离进程组的后台命令）
MAX_RESUME = 30          # 会话没做完就退出时，最多自动续跑几次
_NO_BG = """
【重要】你运行在无人值守的单次运行模式（如 claude -p / codex exec）：你一结束回复，进程就退出，后台运行的子 agent 和后台命令会被一起终止。
所以不要用 run_in_background 启动子 agent 或命令后就结束回复；开发流程要求后台运行的，也改为前台运行并等它完成，
或启动后持续等待（查看输出、sleep 轮询）直到完成再继续。只有全部完成、或在 kb_wait_answer 里等待用户时才可以停。"""


def _notify(title, text):
    esc = lambda x: re.sub(r'\s+', ' ', x).replace('\\', '\\\\').replace('"', '\\"')
    try:
        subprocess.Popen(['osascript', '-e', f'display notification "{esc(text)[:120]}" with title "{esc(title)[:60]}" sound name "Glass"'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def set_dnd(period, on, by='用户'):
    d = period_dir(period)
    m = load_meta(d)
    m['免打扰'] = bool(on)
    if on:  # 正在等的问题按 AI 建议收掉
        for q in m.get('待确认') or []:
            if q['状态'] == '待回答':
                q.update(状态='AI决策', 回答=q.get('AI建议') or '（AI 自行决策）', 回答人='AI（免打扰）', 回答时间=now())
    save_meta(d, m)
    log(d, '免打扰', f'{"开启" if on else "关闭"}（{by}）')
    return f'{d.name} 免打扰已{"开启：后续需要确认的地方由 AI 自行决策" if on else "关闭：需要确认时会在网页等你回答"}'


def ask(period, question, context='', options=None, recommend='', files=None, stage=''):
    d = period_dir(period)
    m = load_meta(d)
    if not (question or '').strip():
        raise KBError('问题不能为空')
    qs = m.setdefault('待确认', [])
    qid = f'Q{len(qs) + 1:03d}'
    q = {'编号': qid, '时间': now(), '阶段': (stage or '').strip(), '问题': question.strip(),
         '背景': (context or '').strip(), '选项': [str(x).strip() for x in options or [] if str(x).strip()],
         'AI建议': (recommend or '').strip(), '文件': [str(x) for x in files or []],
         '状态': '待回答', '回答': '', '回答人': '', '回答时间': ''}
    dnd = bool(m.get('免打扰'))
    if dnd:
        q.update(状态='AI决策', 回答=q['AI建议'] or '（AI 自行决策）', 回答人='AI（免打扰）', 回答时间=now())
    qs.append(q)
    save_meta(d, m)
    log(d, '待确认' if not dnd else '免打扰决策', f'{qid} {q["问题"][:80]}' + (f' → {q["回答"][:60]}' if dnd else ''))
    if dnd:
        return (f'{qid}：免打扰已开启，不用等待。按你的建议执行：{q["AI建议"] or "（未给建议，自行选最稳妥的方案）"}；'
                '并用 kb_log 记录理由。')
    _notify(f'知识库 · {d.name} 需要确认', q['问题'])
    return (f'{qid} 已发到网页，等待用户确认。现在调用 kb_wait_answer(iteration="{d.name}", id="{qid}") 等待；'
            '拿到回答前不要继续做依赖它的事，也不要自行决定。')


def wait_answer(period, qid, timeout=240):
    end = time.time() + min(max(int(timeout or 240), 10), 600)
    while True:
        d = period_dir(period)
        m = load_meta(d)
        q = next((x for x in m.get('待确认') or [] if x['编号'] == qid), None)
        if not q:
            raise KBError(f'没有这个待确认问题：{qid}')
        if q['状态'] == '待回答' and m.get('免打扰'):
            q.update(状态='AI决策', 回答=q.get('AI建议') or '（AI 自行决策）', 回答人='AI（免打扰）', 回答时间=now())
            save_meta(d, m)
            log(d, '免打扰决策', f'{qid} → {q["回答"][:60]}')
        if q['状态'] == '已回答':
            return (f'{qid} 用户已回答（{q["回答时间"]}）：{q["回答"]}\n'
                    '按回答执行；需要时把回答写回对应的流程文档（如待确认表的确认备注），再继续流程。')
        if q['状态'] == 'AI决策':
            return f'{qid}：免打扰已开启，按你的建议执行（{q["回答"]}），并用 kb_log 记录理由。'
        if q['状态'] == '已撤回':
            return f'{qid} 已撤回（用户停止了开发）。停止当前工作，不要再继续。'
        if _pending_chat(m):
            return f'{qid} 用户还没回答，但先发来了别的消息（见下方），请先处理，处理完再调用 kb_wait_answer 继续等 {qid}。'
        if time.time() >= end:
            return f'{qid} 用户还没回答。再次调用 kb_wait_answer 继续等待，不要自行决定。'
        time.sleep(3)


def answer(period, qid, text, by='用户'):
    """只给网页用（用户本人回答），不作为 MCP 工具提供。"""
    d = period_dir(period)
    m = load_meta(d)
    q = next((x for x in m.get('待确认') or [] if x['编号'] == qid), None)
    if not q:
        raise KBError(f'没有这个待确认问题：{qid}')
    if not (text or '').strip():
        raise KBError('回答不能为空')
    q.update(状态='已回答', 回答=text.strip(), 回答人=by, 回答时间=now())
    save_meta(d, m)
    log(d, '确认', f'{qid} {q["问题"][:40]} → {text.strip()[:80]}')
    return f'已回答 {qid}'


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _result_of(text, fmt='', limit=2000):
    """从引擎输出里取最后结果：Claude / Hermes 的 result 行、Codex 最后一条 agent_message，纯文本取末尾。"""
    last_text, failed, plain = '', False, []
    for line in (text or '').splitlines():
        try:
            j = json.loads(line)
        except ValueError:
            if line.strip():
                plain.append(line)
            continue
        if not isinstance(j, dict):
            continue
        t = j.get('type')
        if t == 'result' and 'exit_code' not in j:            # Claude
            return {'结果': (j.get('result') or '')[:limit], '出错': bool(j.get('is_error')),
                    '轮数': j.get('num_turns'), '费用': j.get('total_cost_usd')}
        if t == 'result':                                      # Hermes
            return {'结果': (j.get('result') or j.get('text') or last_text)[:limit], '出错': j.get('exit_code') not in (0, None)}
        if t == 'text' and j.get('text'):
            last_text = j['text']
        elif t == 'item.completed' and (j.get('item') or {}).get('type') == 'agent_message':
            last_text, failed = j['item'].get('text') or '', False
        elif t in ('turn.failed', 'error'):
            failed = True
            last_text = last_text or str((j.get('error') or {}).get('message') or j.get('message') or '')
    if last_text or failed:
        return {'结果': last_text[:limit], '出错': failed}
    if fmt == '纯文本' and plain:
        return {'结果': '\n'.join(plain[-30:])[-limit:], '出错': False}
    return {}


def _dev_result(logf):
    """日志里的最后结果：结束原因、轮数、费用（按各引擎的输出格式）。"""
    try:
        with open(logf, 'rb') as fh:
            head = fh.readline().decode('utf-8', 'ignore')
            fh.seek(max(0, Path(logf).stat().st_size - 400000))
            tail = fh.read().decode('utf-8', 'ignore')
    except OSError:
        return {}
    try:
        fmt = json.loads(head).get('format', '') if head.startswith('{"type": "kb.engine"') else ''
    except ValueError:
        fmt = ''
    return _result_of(tail, fmt)


def _session_id(logf):
    """会话号：Claude / Hermes 的 session_id，Codex 的 thread_id。"""
    try:
        with open(logf, encoding='utf-8', errors='ignore') as fh:
            for line in fh:
                if '"session_id"' in line or '"thread_id"' in line:
                    j = json.loads(line)
                    sid = j.get('session_id') or j.get('thread_id')
                    if sid:
                        return sid
    except (OSError, ValueError):
        pass
    return ''


def _ps():
    try:
        out = subprocess.run(['ps', '-axo', 'pid=,ppid=,pgid=,lstart='], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    rows = {}
    for line in out.splitlines():
        x = line.split(None, 3)
        if len(x) == 4 and x[0].isdigit():
            rows[int(x[0])] = (int(x[1]), int(x[2]), x[3].strip())
    return rows


def _track(roots, known=None):
    """把 roots 的子孙进程（按父进程、以及已知进程所在的进程组）并入 known。父进程退出后被孤立的也能通过进程组找回。"""
    rows, known = _ps(), dict(known or {})
    found = {p for p in roots if p in rows} | {p for p, st in known.items() if p in rows and rows[p][2] == st}
    groups = {rows[p][1] for p in found}
    grow = True
    while grow:
        grow = False
        for pid, (pp, pg, _) in rows.items():
            if pid not in found and pid != os.getpid() and (pp in found or pg in groups):
                found.add(pid)
                groups.add(pg)
                grow = True
    for p in found:
        known[p] = rows[p][2]
    return known


def _kill_tracked(known):
    """结束记录过的进程（启动时间对得上才杀，防止 pid 被系统复用）。返回没杀掉的。"""
    known = _track([], known)
    rows = _ps()
    pids = [p for p, st in known.items() if p in rows and rows[p][2] == st and p != os.getpid()]
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in pids:
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
        time.sleep(1.5)
        pids = [p for p in pids if _alive(p)]
        if not pids:
            break
    return pids


def _want_resume(d, m, s, code, res):
    """会话退出了但活没干完：自动续跑。用户停止、出错退出、已完成、流程已走完、次数用完都不续。"""
    retest = s.get('类型') == '复测'
    if code != 0 or s.get('停止中') or s.get('仅对话') or (not retest and m.get('状态') not in DEV_OK):
        return ''
    if s.get('已汇报') if retest else flow_done(session_flow(m), m.get('SDD目录')):
        return ''
    if s.get('续跑次数', 0) >= MAX_RESUME:
        return f'已自动续跑 {MAX_RESUME} 次，不再续跑'
    if s.get('连续空转', 0) >= 3:
        return '连续 3 次很快就退出、没有进展，不再续跑'
    if res.get('出错') and s.get('连续出错', 0) >= 2:
        return '连续出错，不再续跑'
    return 'resume'


def _dev_finish(name, code=None):
    d = period_dir(name)
    m = load_meta(d)
    s = m.get('开发会话') or {}
    if s.get('状态') != '运行中':
        return
    res = _dev_result(s.get('日志', ''))
    if s.get('插话'):       # 用户在网页选了「打断并立即处理」：带着消息接着这次对话续跑
        try:
            # 打断 = 你在指挥正在做的事：处理完接着被打断的工作做，之后照常自动续跑到做完（不再是「答完就结束」）
            _dev_spawn(d, Path(s['仓库']), s.get('分支', ''), _chat_prompt(s['插话'], True),
                       _session_id(s.get('日志', '')), 续跑次数=s.get('续跑次数', 0))
            return
        except (KBError, OSError, KeyError) as e:
            log(d, '对话', f'打断后续跑失败：{e}')
    if code is None and res.get('结果') is not None and not res.get('出错'):
        code = 0       # 不是本进程启动的（服务重启后接管），拿不到退出码：日志里有正常结果就当正常退出
    why = _want_resume(d, m, s, code, res)
    if why == 'resume':
        sid = _session_id(s.get('日志', ''))
        try:
            started = datetime.strptime(s.get('本轮开始') or s.get('开始时间'), '%Y-%m-%d %H:%M')
            quick = (datetime.now() - started).total_seconds() < 120
        except (TypeError, ValueError):
            quick = False
        n = s.get('续跑次数', 0) + 1
        log(d, '自动续跑', f'会话退出但开发还没完成，第 {n} 次自动续跑' + (f'（上一轮：{res.get("结果", "")[:80]}）' if res.get('结果') else ''))
        try:
            prompt = (_retest_resume_prompt(d.name) if s.get('类型') == '复测'
                      else _resume_prompt(d.name, session_flow(m), m.get('SDD目录', '')))
            _dev_spawn(d, Path(s['仓库']), s.get('分支', ''), prompt, sid,
                       续跑次数=n, 连续空转=(s.get('连续空转', 0) + 1) if quick else 0,
                       连续出错=(s.get('连续出错', 0) + 1) if res.get('出错') else 0)
            return
        except (KBError, OSError, KeyError) as e:
            why = f'自动续跑失败：{e}'
    m = load_meta(d)
    s = m.get('开发会话') or {}
    s.update(状态='已结束', 结束时间=now(), 退出码=code, **res)
    if why:
        s['未续跑原因'] = why
    m['开发会话'] = s
    save_meta(d, m)
    log(d, '开发会话结束', f'退出码 {code}' + (f'；{s.get("结果", "")[:100]}' if s.get('结果') else '')
        + (f'；{why}' if why else ''))
    _after_session(d, s)
    _notify(f'知识库 · {d.name}', '后台开发会话已结束' + ('（有错误）' if code else ''))


# ---- 网页对话：开发面板「最近动作」下的输入框，遇到问题直接跟后台 AI 说
def _pending_chat(m):
    return [x for x in m.get('对话') or [] if x['状态'] == '待送达']


def _take_chat(d, m):
    """把排队的消息交给正在运行的后台会话（附在它下一次调用知识库工具的结果后面）。m 由调用方保存。"""
    if os.environ.get('KB_PERIOD', d.name) != d.name:
        return ''
    xs = _pending_chat(m)
    if not xs:
        return ''
    for x in xs:
        x.update(状态='已送达', 送达时间=now())
    return ('\n\n【用户在网页发来消息】\n' + '\n'.join(f'- （{x["时间"]}）{x["内容"]}' for x in xs)
            + '\n请先处理：要回答的直接在回复里回答（网页会显示），要做的就去做；处理完接着原来的工作推进。')


def _chat_prompt(text, cont):
    return (f'用户在知识库网页「开发」面板给你发来消息（{now()}）：\n{text}\n\n'
            '请先处理这条消息：要回答的直接在回复里回答（网页会显示你的回复），要做的就去做（规则同前：需要确认用 kb_ask，'
            '不改不该改的状态）。' + ('处理完接着刚才被打断的工作推进，直到做完（复测做完要 kb_test_report）。' if cont
                                    else '用户让你做的事要做完（比如让你接着复测，就测完并 kb_test_report）；'
                                         '只是提问就回答。做完简短说明结果后结束，不要自行开始用户没提到的开发。')
            + _NO_BG)


def dev_chat(period, text, interrupt=False):
    """网页对话。会话在跑：默认排队（下一次调用知识库工具时送达，等待确认时立刻送达），interrupt 则打断当前这一轮、带着消息续跑；
    会话没在跑：接着上一次的对话（保留上下文）回答，答完就结束。不作为 MCP 工具提供。"""
    d = period_dir(period)
    text = (text or '').strip()
    if not text:
        raise KBError('消息不能为空')
    s = dev_session(d.name)
    if not s or not s.get('日志'):
        raise KBError('这一期还没有后台会话，先「开始开发」')
    m = load_meta(d)
    run = s.get('状态') == '运行中'
    msg = {'时间': now(), '内容': text, '方式': '打断' if run and interrupt else '排队' if run else '继续会话', '状态': '待送达'}
    if not run:
        if m.get('状态') == '收集中':
            raise KBError('这一期还在收集中，没有开发会话可以对话')
        sid = _session_id(s['日志'])
        if not sid:
            raise KBError('上一次会话没有会话号，接不上；请点「开始开发」/「继续开发」')
        msg.update(状态='已送达', 送达时间=now())
        m.setdefault('对话', []).append(msg)
        m['开发会话'] = dict(s, 仅对话=True)
        save_meta(d, m)
        proc = _dev_spawn(d, Path(s['仓库']), s.get('分支', ''), _chat_prompt(text, False), sid, 续跑次数=0, 仅对话=True)
        log(d, '对话', f'接着上次的会话回答（pid {proc.pid}）：{text[:100]}')
        return '已接着上一次的会话发给 AI，回复会显示在「最近动作」里'
    m.setdefault('对话', []).append(msg)
    if interrupt:
        msg.update(状态='已送达', 送达时间=now())
        m['开发会话']['插话'] = text
        save_meta(d, m)
        log(d, '对话', f'打断当前步骤：{text[:100]}')
        try:
            os.killpg(s['pid'], signal.SIGTERM)
        except ProcessLookupError:
            try:
                os.kill(s['pid'], signal.SIGTERM)
            except ProcessLookupError:
                pass
        return '已打断当前这一轮，AI 会带着你的消息接着这次对话继续（几秒后在「最近动作」里看到）'
    save_meta(d, m)
    log(d, '对话', f'排队：{text[:100]}')
    return 'AI 下一次调用知识库工具时会收到（正在等你确认时立刻收到），不打断当前步骤'


def _after_session(d, s):
    """会话结束 / 停止后：释放手机，同步测试报告里的问题，开发会话还要看要不要提示复测。"""
    try:
        device_release(d.name, by='会话结束')
        sync_test_issues(d)
        if s.get('类型') != '复测':
            _suggest_retest(d)
    except (KBError, OSError, ValueError) as e:
        log(d, '会话收尾', f'出错：{e}')


def dev_session(name):
    """当前/上一次后台开发会话；进程已不在但还标着运行中的，补记为已结束。"""
    d = period_dir(name)
    s = load_meta(d).get('开发会话')
    if s and s.get('状态') == '运行中' and d.name not in _PROCS and d.name not in _WATCH and not _alive(s.get('pid', 0)):
        _dev_finish(d.name)
        s = load_meta(d).get('开发会话')
    return s


def _dev_prompt(name, root, branch, f, docs):
    v = dict(期名=name, 仓库=str(root), 分支=branch, 文档目录=str(docs),
             资料目录=str(Path(docs) / (f.get('资料目录名') or 'kb-materials')))
    steps = flow_text(f, '开发步骤', **v).strip()
    return f"""你是由知识库网页启动的【后台无人值守】开发会话：期「{name}」，仓库 {root}，分支 {branch}，开发流程「{f['名称']}」，文档目录 {docs}。
终端里没有人，不要在回复里提问，也不要用 AskUserQuestion。按下面做，直到全部完成：

【准备】kb_refresh_sources 检查需求来源有没有更新（有「条目待更新」的按提示先更新条目）；kb_dev_package 读取开发包；
kb_set_status 改为「开发中」（已是开发中则跳过）。工具结果里出现【需求来源有更新】时按提示处理。

【开发流程：{f['名称']}】
{steps}

【需要人确认时】{flow_text(f, '确认点', **v) or '方案取舍、与需求不一致、缺少账号或环境、操作被权限拦截等'}：
调用 kb_ask（问题、背景、选项、你的建议 recommend、相关文件绝对路径），再反复调用 kb_wait_answer 直到拿到回答；
需要时把回答写回对应的流程文档，然后继续。kb_ask 若提示免打扰，直接按你的建议执行。
【基础信息】测试账号、Wi-Fi / 代理 / VPN、环境配置等先查基础知识库（kb_base）；密码等机密在真正要用时才 kb_base_secret 读取，
不要写进代码、文档、提交、日志或回复。缺少需要的账号或配置时用 kb_ask 向用户要。
【手机】要在手机上装包、测试前先 kb_devices 看、kb_device_claim 申请（要几台申请几台），只在申请到的手机上操作
（adb -s <序列号> / agent-device --serial），别动别的期占着的手机；测完 kb_device_release。
【不阻断的问题】手机不够或没连（如 case 要多台手机而只连了一台）、缺测试账号、环境不满足等，让某些验证做不了、但不影响继续开发的：
不要停下等，也不要悄悄跳过——马上用 kb_issue 记下（写清要什么，如「需要 3 台手机：主持 + 2 个麦上用户」），能做的先做，
测不了的 case 如实记 BLOCKED，然后继续。用户会在网页看到并收到通知，条件具备后点「复测」补测。
【记录】每完成一个阶段或一个任务，用 kb_log 记一句进度；关键决定、接口变更、与需求不一致之处也 kb_log。
【完成】全部完成后 kb_set_status 改为「已完成」，并 kb_log 记录分支和提交。
【停止】kb_wait_answer 返回「已撤回」时立即停止。遇到无法继续的错误，用 kb_ask 说明情况并等待指示，不要放弃退出。""" + _NO_BG


def _resume_prompt(name, f=None, docs=''):
    f = f or get_flow()
    tip = flow_text(f, '续跑提示', 期名=name, 文档目录=str(docs)) or '先看文档目录和 git 改动确认实际进度：没完成的步骤重新执行（用前台方式）'
    return f"""继续期「{name}」的开发（开发流程「{f['名称']}」）。上一轮你结束了回复，进程随之退出，当时在后台运行的子 agent 和命令都已经被终止，不会再有结果。
{tip}，然后按原来的要求继续推进，需要人确认时照旧用 kb_ask + kb_wait_answer。
用手机前照旧 kb_device_claim；手机不够等不影响继续开发的问题用 kb_issue 记下后接着做。""" + _NO_BG


def session_flow(m):
    """开发会话用的流程：会话里记的 > 这一期选定的 > 默认。"""
    fid = (m.get('开发会话') or {}).get('流程')
    if fid:
        try:
            return get_flow(fid)
        except KBError:
            pass
    return period_flow(m)


def _dev_env(name, branch, root):
    """后台会话的环境：PATH 最前面是 adb 守卫（不往别的期占着的手机装包），再补上 adb 所在目录。
    网页服务由 launchd 启动，PATH 里没有 ~/.zshrc 加的 Android SDK，后台会话的 shell 也不读 .zshrc，
    不补的话会话里找不到 adb，手机插着也会报「没有设备」。"""
    path = [str(devlock.BIN)]
    adb = _adb()
    if adb:
        path.append(str(Path(adb).parent))
    env = {'PATH': os.pathsep.join(path + [os.environ.get('PATH', '')]), 'KB_ROOT': str(ROOT), 'KB_PERIOD': name,
           'KB_BRANCH': branch, 'KB_REPO': str(root)}
    sdk = Path(adb).parent.parent if adb and Path(adb).parent.name == 'platform-tools' else None
    if sdk and not os.environ.get('ANDROID_HOME'):
        env['ANDROID_HOME'] = env['ANDROID_SDK_ROOT'] = str(sdk)
    return env


def _dev_spawn(d, root, branch, prompt, resume_id='', **extra):
    """启动（或用 --resume 接着上一轮对话续跑）后台会话；进程退出后自动 _dev_finish。"""
    eng = period_engine(load_meta(d))
    (d / DEV_DIR).mkdir(exist_ok=True)
    ts = f'{datetime.now():%Y%m%d-%H%M%S}'
    logf = d / DEV_DIR / f'{ts}.jsonl'
    proc = engine_popen(eng, prompt, f'kb·{d.name}', logf, root, resume_id, _dev_env(d.name, branch, root))
    _PROCS[d.name] = proc
    m = load_meta(d)
    old = m.get('开发会话') or {}
    s = {'pid': proc.pid, '状态': '运行中', '开始时间': old.get('开始时间') if resume_id else now(), '本轮开始': now(),
         '仓库': str(root), '分支': branch, '日志': str(logf), '权限': eng['名称'], '备注': old.get('备注', ''),
         '流程': old.get('流程', ''), '引擎': eng['id'], '类型': old.get('类型', ''), '范围': old.get('范围', ''), **extra}
    if resume_id:
        s['历史日志'] = (old.get('历史日志') or []) + [old.get('日志')]
        if old.get('已汇报'):
            s['已汇报'] = True
        s['开始时间'] = old.get('开始时间') or now()
    m['开发会话'] = s
    save_meta(d, m)

    threading.Thread(target=_watch_dev, args=(d, proc.pid, proc), daemon=True).start()
    return proc


_WATCH = set()   # 正在被本进程盯着的期


def _watch_dev(d, pid, proc=None, known=None):
    """盯住后台会话：记录它派生的进程；退出后清理残留，再交给 _dev_finish（判断是否续跑）。"""
    _WATCH.add(d.name)
    try:
        known, saved = dict(known or {}), -1
        while (proc.poll() is None) if proc else _alive(pid):
            known = _track([pid], known)
            _TRACK[d.name] = known
            if len(known) != saved:      # 记进期信息，网页服务重启后也能清理
                saved = len(known)
                mm = load_meta(d)
                if (mm.get('开发会话') or {}).get('pid') == pid:
                    mm['开发会话']['子进程'] = {str(k): v for k, v in known.items()}
                    save_meta(d, mm)
            time.sleep(5)
        code = proc.returncode if proc else None
        if proc and _PROCS.get(d.name) is proc:
            _PROCS.pop(d.name, None)
        if not (load_meta(d).get('开发会话') or {}).get('停止中'):
            left = _kill_tracked(known)   # 主会话退出后残留的后台命令：续跑会重新执行，别让两份同时写
            _TRACK.pop(d.name, None)
            if left:
                log(d, '清理残留进程', f'未能结束：{left}')
    finally:
        _WATCH.discard(d.name)
    _dev_finish(d.name, code)


def dev_reattach():
    """网页服务启动时接管还在跑的后台会话（服务重启过，原来盯着它的线程没了）。"""
    for name in period_names():
        d = period_dir(name)
        s = load_meta(d).get('开发会话') or {}
        if s.get('状态') == '运行中' and name not in _WATCH and _alive(s.get('pid', 0)):
            known = {int(k): v for k, v in (s.get('子进程') or {}).items()}
            threading.Thread(target=_watch_dev, args=(d, s['pid'], None, known), daemon=True).start()


def pull_rebase(root):
    """git pull --rebase 拉最新代码；没有上游分支就跳过。失败（冲突等）会撤销这次 rebase，保持原样。"""
    root = Path(root)
    br = _git(root, 'branch', '--show-current').stdout.strip()
    up = _git(root, 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}')
    if up.returncode:
        return f'{br} 没有上游分支，跳过拉取'
    old = _git(root, 'rev-parse', '--short', 'HEAD').stdout.strip()
    r = _git(root, 'pull', '--rebase', timeout=300)
    if r.returncode:
        git_dir = Path(_git(root, 'rev-parse', '--absolute-git-dir').stdout.strip() or root / '.git')
        aborted = (git_dir / 'rebase-merge').exists() or (git_dir / 'rebase-apply').exists()
        if aborted:
            _git(root, 'rebase', '--abort')
        raise KBError(f'在 {br} 上 git pull --rebase 失败' + ('（已撤销这次 rebase，代码保持原样）' if aborted else '')
                      + f'：\n{(r.stderr or r.stdout).strip()[:800]}')
    new = _git(root, 'rev-parse', '--short', 'HEAD').stdout.strip()
    return f'{br} 已是最新（{new}）' if old == new else f'{br} 已拉取 {old} → {new}'


def switch_branch(root, branch):
    """用户在网页上确认「切到开发分支」后执行：切换前在当前分支 git pull --rebase，切换后在新分支再 git pull --rebase。
    已跟踪的文件有改动不切（未跟踪文件不影响）；本地没有的分支从 origin 拉；
    本地和远端都没有时不替用户新建（基线分支说不准），请用户自己建好或重新输入。返回每一步的结果。"""
    root = Path(root)
    if not re.fullmatch(r'[A-Za-z0-9][\w./-]*', branch or '') or '..' in branch:
        raise KBError(f'分支名不合法：{branch}')
    dirty = [x for x in _git(root, 'status', '--porcelain', '--untracked-files=no').stdout.splitlines() if x.strip()]
    if dirty:
        raise KBError(f'{root.name} 有 {len(dirty)} 个未提交的改动，先提交或 stash 后再切分支：\n' + '\n'.join(dirty[:10]))
    local = _git(root, 'rev-parse', '--verify', '--quiet', f'refs/heads/{branch}').returncode == 0
    remote = not local and _git(root, 'ls-remote', '--exit-code', '--heads', 'origin', branch, timeout=30).returncode == 0
    if not local and not remote:
        raise KBError(f'{root.name} 本地和 origin 都没有分支「{branch}」。请先在仓库里从正确的基线分支建好（如 git switch -c {branch} origin/<基线>），'
                      '或重新输入分支名')
    steps = ['切换前：' + pull_rebase(root)]
    if local:
        r = _git(root, 'switch', branch)
    else:
        f = _git(root, 'fetch', 'origin', f'{branch}:refs/remotes/origin/{branch}', timeout=120)
        r = f if f.returncode else _git(root, 'switch', '--track', f'origin/{branch}')
    if r.returncode:
        raise KBError(f'切换分支失败：{(r.stderr or r.stdout).strip()[:500]}')
    steps.append(f'已切换到 {branch}' + ('' if local else '（从 origin 拉取）'))
    steps.append('切换后：' + pull_rebase(root))
    return steps


def dev_start(period, note='', repo='', branch='', keep_branch=False):
    """网页「开始开发」：用户本人批准 + 后台启动开发会话。不作为 MCP 工具提供。
    仓库、分支自动从本期资料判断；判断不了时抛 KBNeed，网页弹窗让用户选仓库（repo）、
    切到开发分支（branch）或确认就用当前分支（keep_branch），再带着选择重新调用。"""
    d = period_dir(period)
    m = load_meta(d)
    s = dev_session(d.name)
    if s and s.get('状态') == '运行中':
        raise KBError('后台开发会话已经在运行')
    if m.get('状态') == '已完成':
        raise KBError('这一期已完成；如要继续开发，先把状态改为「已暂停」再开始')
    if repo:
        root = _git_root(repo)
        if not root:
            raise KBError(f'不是本机的 git 仓库：{repo}')
        if not flow_for(m, root):
            raise KBError(_no_flow_msg(m, root))
        repo = str(root)
    steps = []
    if branch or keep_branch:
        root = Path(repo) if repo else _sdd_repo(d, m, '')
        steps = switch_branch(root, branch) if branch else ['拉取：' + pull_rebase(root)]
        cur = _git(root, 'branch', '--show-current').stdout.strip()
        repo = str(root)
        m['开发分支'] = cur
        save_meta(d, m)
        log(d, '确认开发分支', f'{root.name} · {cur}' + (f'（网页确认切换：{"；".join(steps)}）' if branch else f'（沿用当前分支；{steps[0]}）'))
    root, branch, f, docs = _dev_target(d, m, repo)
    eng = period_engine(dict(m, 开发会话={}))
    engine_bin(eng)
    if m.get('状态') not in DEV_OK:
        set_status(d.name, '已批准开发', note or '网页「开始开发」批准', by_human=True)
    m = load_meta(d)
    if m.get('开发仓库') != str(root):
        log(d, '确认开发仓库', str(root))
    m['开发仓库'] = str(root)
    m['SDD目录'] = str(docs)
    m['开发会话'] = {'备注': note, '流程': f['id'], '引擎': eng['id']}
    save_meta(d, m)
    plug = run_plugins('开发开始', d, root, branch, docs)
    prompt = _dev_prompt(d.name, root, branch, f, docs)
    if plug:
        prompt += f'\n\n【开发开始时已运行的插件】（知识库自动运行，结果供参考）\n{plug}'
    proc = _dev_spawn(d, root, branch, prompt, '', 续跑次数=0)
    log(d, '开始开发', f'后台会话 pid {proc.pid}（{eng["名称"]} · {f["名称"]} · {root.name} · {branch}）' + (f'；{note}' if note else ''))
    return (f'已开始开发「{d.name}」：后台会话 pid {proc.pid}，{eng["名称"]}，流程「{f["名称"]}」，仓库 {root.name}（{branch}）'
            + (''.join(f'\n{x}' for x in steps) if steps else '') + (f'\n\n{plug}' if plug else ''))


def dev_stop(period, by='用户'):
    """网页「停止开发」：结束后台会话，状态改为已暂停，撤回未回答的问题。不作为 MCP 工具提供。"""
    d = period_dir(period)
    s = dev_session(d.name)
    if not s or s.get('状态') != '运行中':
        raise KBError('没有正在运行的后台开发会话')
    pid = s['pid']
    m = load_meta(d)
    m['开发会话']['停止中'] = True       # 别让 _dev_finish 把它当成「没做完」自动续跑
    save_meta(d, m)
    try:
        os.killpg(pid, signal.SIGTERM)
        for _ in range(25):
            if not _alive(pid) or (d.name in _PROCS and _PROCS[d.name].poll() is not None):
                break
            time.sleep(0.2)
        else:
            os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    left = _kill_tracked(_TRACK.pop(d.name, None) or {int(k): v for k, v in (s.get('子进程') or {}).items()})
    m = load_meta(d)
    s = m['开发会话']
    s.pop('停止中', None)
    s.update(状态='已停止', 结束时间=now(), 停止人=by, **_dev_result(s.get('日志', '')))
    if left:
        s['未能结束的进程'] = left
    for q in m.get('待确认') or []:
        if q['状态'] == '待回答':
            q.update(状态='已撤回', 回答时间=now())
    save_meta(d, m)
    log(d, '停止开发', f'后台会话 pid {pid} 已停止（{by}）')
    _after_session(d, s)
    if s.get('类型') == '复测':
        return f'已停止「{d.name}」的复测'
    if m.get('状态') in DEV_OK:
        set_status(d.name, '已暂停', '网页「停止开发」', by_human=True)
    return f'已停止「{d.name}」的后台开发，状态改为已暂停'


# ---------------------------------------------------------------- 手机占用、非阻断问题、复测
# 多个期可能同时在后台测试：手机占用记在 设备占用.json（devlock.py），后台会话 PATH 最前面是 adb 守卫（bin/adb），
# 不让一期往别的期占着的手机装包、操作。手机不够、缺账号等不影响继续开发的问题记成「非阻断问题」，网页列出并通知；
# 识别到测试用例 / 自动化测试文件时开发面板有「复测」，条件具备后补测，也可以设成空闲手机够了自动复测。
_ADB = {}
_DEVS = {'t': 0, 'v': []}


def _adb():
    if 'path' not in _ADB:
        p = devlock.real_adb()
        if not p:       # 网页服务由 launchd 启动，PATH 里常常没有 adb：问一下登录 shell
            try:
                out = subprocess.run(['zsh', '-lic', 'command -v adb'], capture_output=True, text=True, timeout=10,
                                     stdin=subprocess.DEVNULL).stdout.strip().splitlines()
                p = out[-1] if out and Path(out[-1]).is_file() else ''
            except (OSError, subprocess.TimeoutExpired):
                p = ''
        _ADB['path'] = p
    return _ADB['path']


def _agent_device_claims():
    """agent-device 自己记的设备会话：序列号 → 会话名、工作目录。"""
    out = {}
    for f in (Path.home() / '.agent-device' / 'device-claims').glob('*.json'):
        try:
            c = json.loads(read_text(f))
            pid = int(c.get('ownerPid') or 0)
            if pid <= 0:
                continue
            os.kill(pid, 0)
            out[(c.get('device') or {})['id']] = {'会话': c.get('session', ''), '目录': c.get('workspace', ''),
                                                   '更新': devlock.stamp((c.get('updatedAtMs') or 0) / 1000)}
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return out


def _period_of_path(p):
    metas = [(n, load_meta(PERIODS / n)) for n in period_names()]
    for k in ('SDD目录', '开发仓库'):
        for n, m in metas:
            if m.get(k) and str(p).startswith(m[k]):
                return n
    return ''


def devices(period=''):
    """连着的手机和占用情况（占着但没连的也列出）。"""
    if time.time() - _DEVS['t'] > 3:
        adb = _adb()
        _DEVS.update(t=time.time(), v=devlock.online(adb) if adb else [])
    hold, ad = devlock.holders(), _agent_device_claims()
    sns = [x[0] for x in _DEVS['v']]
    out = []
    for sn, st, model in _DEVS['v'] + [(k, '未连接', '') for k in hold if k not in sns]:
        c, a = hold.get(sn), ad.get(sn)
        if a:
            a = dict(a, 期=_period_of_path(a['目录']))
        out.append({'序列号': sn, '型号': model or (c or {}).get('型号', ''),
                    '状态': {'device': '在线', 'unauthorized': '未授权', 'offline': '离线'}.get(st, st),
                    '占用': dict(c, 最后使用=devlock.stamp(c.get('最后使用'))) if c else None,
                    '本期': bool(c and period and c.get('期') == period and c.get('方式') != '本人'),
                    '空闲': st == 'device' and not c, 'agent-device': a})
    return out


def _who(c):
    if c.get('方式') == '本人':
        return '本人在用（网页上标的）'
    return f'被「{c.get("期", "")}」占用（分支 {c.get("分支") or "—"}，最后使用 {c.get("最后使用", "")}）'


def devices_text(period):
    if not _adb():
        return '本机找不到 adb，查不了手机。'
    name = period_dir(period).name
    ds = devices(name)
    if not ds:
        return ('没有连着的手机（adb devices 为空）。要用真机测试的先做别的部分，用 kb_issue 记下需要几台手机，继续开发；'
                '用户接好手机后会在网页「复测」补测。')
    lines = []
    for x in ds:
        c, a = x['占用'], x['agent-device']
        st = '空闲' if x['空闲'] else '本期占用' if x['本期'] else _who(c) if c else x['状态']
        if x['状态'] != '在线' and c:
            st += f'，{x["状态"]}'
        lines.append(f'- {x["序列号"]} {x["型号"]}：{st}' + (f'；agent-device 会话 {a["会话"]}' + (f'（{a["期"]}）' if a['期'] else '')
                                                            if a else ''))
    return (f'手机 {len(ds)} 台，空闲 {sum(x["空闲"] for x in ds)} 台：\n' + '\n'.join(lines)
            + '\n要用时 kb_device_claim 申请，只在申请到的手机上装包、操作（adb -s <序列号> / agent-device --serial）。')


def device_claim(period, count=1, serials=None, reason=''):
    """申请手机：优先本期已占着的，再挑空闲的；不够时记成非阻断问题并通知用户。"""
    d = period_dir(period)
    m = load_meta(d)
    count = max(1, min(int(count or 1), 10))
    ds = {x['序列号']: x for x in devices(d.name)}
    branch = (m.get('开发会话') or {}).get('分支') or m.get('开发分支', '')
    got, why = [], []
    with devlock.locked() as data:
        t = time.time()
        for k in [k for k, v in data.items() if not devlock.valid(v, t)]:
            data.pop(k)

        def usable(sn):
            c = data.get(sn)
            return ds.get(sn, {}).get('状态') == '在线' and (not c or (c.get('期') == d.name and c.get('方式') != '本人'))
        if serials:
            for sn in serials:
                if usable(sn):
                    got.append(sn)
                else:
                    why.append(f'{sn} ' + ('没连着' if sn not in ds else _who(ds[sn]['占用']) if ds[sn]['占用'] else ds[sn]['状态']))
        else:
            mine = [sn for sn in ds if usable(sn) and sn in data]
            other = sorted((sn for sn in ds if usable(sn) and sn not in data),
                           key=lambda sn: bool((ds[sn]['agent-device'] or {}).get('期') not in ('', d.name, None)))
            got = (mine + other)[:count]
        for sn in got:
            old = data.get(sn) or {}
            data[sn] = {'期': d.name, '方式': '申请', '开始': old.get('开始') or devlock.stamp(), '分支': branch,
                        '仓库': m.get('开发仓库', ''), '型号': ds[sn]['型号'], '用途': (reason or '').strip()[:200], '最后使用': t}
    need = len(serials) if serials else count
    if got:
        log(d, '申请手机', '、'.join(got) + (f'（{reason}）' if reason else ''))
    msg = (f'已为「{d.name}」占用 {len(got)} 台：' + '、'.join(f'{sn}（{ds[sn]["型号"]}）' for sn in got)
           + '。只在这些手机上装包、操作（adb -s <序列号> / agent-device --serial），测完 kb_device_release。') if got else '没有能用的手机。'
    if len(got) < need:
        iid, _ = _add_issue(d, f'需要 {need} 台手机，现在只能用 {len(got)} 台' + (f'：{reason}' if reason else ''),
                            devices_text(d.name) + (f'\n\n不可用：{"；".join(why)}' if why else ''), '设备不足', f'{need} 台手机',
                            'kb_device_claim', key=f'设备不足|{need}|{reason}')
        msg += (f'\n手机不够（需要 {need} 台，能用 {len(got)} 台' + (f'；{"；".join(why)}' if why else '') + f'）：已记为非阻断问题 {iid} 并通知用户。'
                '能测的先测；测不了的 case 按流程如实记 BLOCKED（ENV_BLOCKED，写明缺几台手机），继续开发，不要等待。'
                '用户接好手机后会在网页「复测」补测。')
    return msg


def device_release(period, serials=None, by='AI'):
    name = period_dir(period).name
    with devlock.locked() as data:
        ks = [k for k, v in data.items() if v.get('期') == name and v.get('方式') != '本人' and (not serials or k in serials)]
        for k in ks:
            data.pop(k)
    return f'已释放 {len(ks)} 台手机：{"、".join(ks)}' if ks else '这一期没有占着的手机'


def device_mark(serial, action):
    """网页：释放任何人的占用（release），或标成本人在用（mine）。"""
    with devlock.locked() as data:
        if action == 'release':
            c = data.pop(serial, None)
            return f'已释放 {serial}' + (f'（原来{_who(dict(c, 最后使用=devlock.stamp(c.get("最后使用"))))}）' if c else '')
        if action == 'mine':
            data[serial] = {'期': '', '方式': '本人', '开始': devlock.stamp(), '最后使用': time.time()}
            return f'已把 {serial} 标成本人在用：4 小时内后台会话不会往它装包、操作（用完点「释放」）'
    raise KBError('未知操作')


ISSUE_KINDS = ['设备不足', '账号', '环境', '未验证', '待排查', '工具链', '其他']
_URGENT = ('设备不足', '账号', '环境')     # 用户能动手解决的，新出现时弹通知


def _issue_kind(cat, text):
    if '工具链' in cat:
        return '工具链'
    if '疑点' in cat or '排查' in cat:
        return '待排查'
    if re.search(r'设备|手机|真机|\d\s*台', text):
        return '设备不足'
    if re.search(r'账号|登录', text):
        return '账号'
    if re.search(r'ENV|环境|网络|SIM|服务端|注入|构造|权限', text):
        return '环境'
    return '未验证'


def _add_issue(d, title, detail='', kind='', need='', source='AI', key='', notify=True):
    """记一条非阻断问题；同一问题（键相同）还没处理的只更新。返回 (编号, 是否新记)。"""
    m = load_meta(d)
    items = m.setdefault('非阻断问题', [])
    key = key or title.strip()
    old = next((x for x in items if x.get('键') == key and (x['状态'] == '待处理' or source == 'SDD 报告')), None)
    if old:
        if old['状态'] == '待处理' and detail and detail != old.get('详情'):
            old.update(详情=detail, 更新=now())
            save_meta(d, m)
        return old['编号'], False
    kind = kind if kind in ISSUE_KINDS else _issue_kind('', f'{title} {need}')
    iid = f'I{len(items) + 1:03d}'
    items.append({'编号': iid, '时间': now(), '类型': kind, '标题': title.strip()[:200], '详情': (detail or '').strip(),
                  '需要': (need or '').strip(), '来源': source, '键': key, '状态': '待处理', '处理时间': ''})
    save_meta(d, m)
    log(d, '非阻断问题', f'{iid} [{kind}] {title[:100]}')
    if notify:
        _notify(f'知识库 · {d.name} 需要你处理（不阻断开发）', title)
    return iid, True


def add_issue(period, title, detail='', kind='', need=''):
    if not (title or '').strip():
        raise KBError('问题标题不能为空')
    iid, new = _add_issue(period_dir(period), title, detail, kind, need)
    return (f'{iid} 已{"记下并通知用户" if new else "更新（这个问题之前记过）"}。这是非阻断问题：不用等回答，继续开发；'
            '因此没测成的 case 如实记 BLOCKED，用户条件具备后会在网页「复测」补测。')


def set_issue(period, iid, status, by='用户（网页）'):
    d = period_dir(period)
    if status not in ('待处理', '已处理', '已忽略'):
        raise KBError('状态只能是 待处理 / 已处理 / 已忽略')
    m = load_meta(d)
    q = next((x for x in m.get('非阻断问题') or [] if x['编号'] == iid), None)
    if not q:
        raise KBError(f'没有这个问题：{iid}')
    q.update(状态=status, 处理时间=now() if status != '待处理' else '', 处理人=by)
    save_meta(d, m)
    log(d, '非阻断问题', f'{iid} → {status}（{by}）')
    return f'{iid} 已标为「{status}」'


def _num(p):
    x = re.search(r'(\d+)', p.name)
    return int(x.group(1)) if x else 0


_SYNCED = {}


def sync_test_issues(d, m=None):
    """SDD：把 agentdevice-task-*.md「未闭环项」同步成非阻断问题（手机不够、缺账号等新出现时通知）。"""
    m = m or load_meta(d)
    docs = Path(m.get('SDD目录') or '')
    if not m.get('SDD目录') or not docs.is_dir():
        return 0
    fs = sorted(docs.glob('agentdevice-task-*.md'), key=_num)
    sig = [(f.name, f.stat().st_mtime) for f in fs]
    if _SYNCED.get(d.name) == sig:
        return 0
    new = []
    for f in fs:
        part = re.split(r'^##\s*未闭环项\s*$', read_text(f), maxsplit=1, flags=re.M)
        if len(part) < 2:
            continue
        sec = re.split(r'^##\s', part[1], maxsplit=1, flags=re.M)[0]
        for line in re.findall(r'^\s*[-*]\s+(.+)$', sec, re.M):
            cols = [x.strip() for x in line.split('|')]
            if len(cols) < 3:
                continue
            cat, case, what = cols[:3]
            ev, need = (cols + ['', ''])[3:5]
            kind = _issue_kind(cat, f'{what} {need}')
            title = f'TASK-{_num(f)} {case}：{need or what}'[:160]
            iid, isnew = _add_issue(d, title, f'类别：{cat}\n说明：{what}' + (f'\n证据：{ev}' if ev and ev != '无' else '')
                                    + (f'\n需要：{need}' if need else '') + f'\n报告：{f}', kind, need, 'SDD 报告',
                                    key=f'{f.name}|{cat}|{case}', notify=False)
            if isnew and kind in _URGENT:
                new.append(title)
    _SYNCED[d.name] = sig
    if new:
        _notify(f'知识库 · {d.name} 有 {len(new)} 个问题需要你处理（不阻断开发）', new[0] + (f' 等 {len(new)} 项' if len(new) > 1 else ''))
    return len(new)


_CASE_RE = re.compile(r'^#{2,4}\s+([A-Z]{1,6}-\d+(?:\s*[/、,，~]\s*[A-Z]{0,6}-?\d+)*)\s*[:：]\s*(PASS|FAIL|BLOCKED|ERROR|SKIP)\b(.*)$', re.M)


def test_files(f, docs):
    """按流程的「测试文件」在文档目录里找测试用例 / 自动化测试文件。"""
    if not docs or not Path(docs).is_dir():
        return []
    out = set()
    for g in f.get('测试文件') or []:
        p = Path(g).expanduser()
        base, pat = (Path(p.anchor), str(p.relative_to(p.anchor))) if p.is_absolute() else (Path(docs), g)
        try:
            out |= {x for x in base.glob(pat) if x.is_file() and not x.name.startswith('.')}
        except (ValueError, OSError):
            pass
    return sorted(out, key=lambda x: (str(x.parent), _num(x), x.name))[:500]


def test_summary(f, docs):
    """测试文件数和 case 结果（「### 编号: 状态」，后出现的覆盖前面的，复测结果追加在后面即可）。"""
    fs = test_files(f, docs)
    if not fs:
        return None
    cases = {}
    for p in fs:
        if p.suffix.lower() not in ('.md', '.markdown', '.txt'):
            continue
        text = read_text(p)
        for mm in _CASE_RE.finditer(text):
            env = 'ENV_BLOCKED' in mm.group(3) or 'ENV_BLOCKED' in text[mm.end():mm.end() + 300].split('\n###')[0]
            for cid in re.findall(r'[A-Z]{1,6}-\d+', mm.group(1)):
                cases[cid] = (mm.group(2), env)
    count = {}
    for st, _ in cases.values():
        count[st] = count.get(st, 0) + 1
    return {'文件数': len(fs), '文件': [str(x) for x in fs[:30]], '用例': len(cases), '统计': count,
            '环境阻塞': sum(1 for st, env in cases.values() if st == 'BLOCKED' and env),
            '未通过': [c for c, (st, _) in cases.items() if st != 'PASS'][:80]}


def need_devices(m):
    """补测要几台手机：没处理的「设备不足」问题里写的台数，取最大。"""
    n = 1
    for q in m.get('非阻断问题') or []:
        if q['状态'] == '待处理' and q['类型'] == '设备不足':
            nums = [int(x) for x in re.findall(r'(\d+)\s*台', f'{q["需要"]} {q["标题"]} {q["详情"]}') if 0 < int(x) <= 10]
            n = max([n, 2] + nums)
    return n


def retest_info(d, m):
    return {'测试': test_summary(session_flow(m), m.get('SDD目录')), '待复测': m.get('待复测'),
            '记录': (m.get('复测记录') or [])[-5:], '需要手机': need_devices(m)}


_SCOPE = {'未通过': '只测上次没通过的 case（BLOCKED、FAIL、ERROR、没执行 / 未验证的）', '全部': '全部 case 重新测一遍'}


def _retest_prompt(name, root, branch, f, docs, scope, note):
    v = dict(期名=name, 仓库=str(root), 分支=branch, 文档目录=str(docs), 范围=_SCOPE[scope],
             资料目录=str(Path(docs) / (f.get('资料目录名') or 'kb-materials')))
    steps = flow_text(f, '复测步骤', **v).strip() or flow_text(BUILTIN_FLOWS['generic'], '复测步骤', **v)
    return f"""你是由知识库网页启动的【后台无人值守】复测会话：期「{name}」，仓库 {root}，分支 {branch}，开发流程「{f['名称']}」，文档目录 {docs}。
开发时因为手机不够、没连手机、账号或环境不满足，有些测试没测成；用户点了「复测」{f'（{note}）' if note else ''}，请补测。
终端里没有人，不要在回复里提问，也不要用 AskUserQuestion。不要改这一期的状态，不要开发新功能。

【复测步骤】
{steps}

【手机】先 kb_devices 看；kb_device_claim 申请要用的台数（多台场景一次申请够），只在申请到的手机上装包、操作，别动别的期占着的手机。
手机还是不够、账号或环境仍不满足的 case：如实记 BLOCKED，用 kb_issue 记下还缺什么，然后接着测其余的。
【发现缺陷】复测发现代码缺陷时，用 kb_ask 说明现象、证据和修改建议，kb_wait_answer 等用户回答后照做（同意了才改代码，按仓库惯例提交）。
【基础信息】测试账号等先查 kb_base；机密只在真正要用时 kb_base_secret 读取，不写进任何文件、日志或回复。
【结束】全部测完：kb_device_release 释放手机，再调用 kb_test_report 汇报（通过 / 失败 / 仍阻塞的数量、小结、还缺什么条件），然后结束。
【停止】kb_wait_answer 返回「已撤回」时立即停止。""" + _NO_BG


def _retest_resume_prompt(name):
    return f"""继续期「{name}」的复测。上一轮你结束了回复，进程随之退出，当时在后台运行的子 agent 和命令都已经被终止，不会再有结果。
先看测试报告里已追加的「复测」结果确认做到哪了，没测完的接着测（手机照旧先 kb_device_claim）；全部测完后 kb_device_release、kb_test_report。""" + _NO_BG


def retest_start(period, scope='未通过', note='', by='用户（网页）'):
    """网页「复测」：后台启动复测会话（不改期状态）。不作为 MCP 工具提供。"""
    d = period_dir(period)
    m = load_meta(d)
    s = dev_session(d.name)
    if s and s.get('状态') == '运行中':
        raise KBError('后台会话正在运行，等它结束或先停止再复测')
    if m.get('状态') == '收集中' or not m.get('开发仓库') or not m.get('SDD目录'):
        raise KBError('这一期还没开发过，没有可复测的内容')
    root, docs, f = Path(m['开发仓库']), m['SDD目录'], session_flow(m)
    if not test_files(f, docs):
        raise KBError(f'文档目录里没有识别到测试文件（开发流程「{f["名称"]}」的「测试文件」设置）：{docs}')
    branch = _git(root, 'branch', '--show-current').stdout.strip()
    if m.get('开发分支') and branch != m['开发分支']:
        raise KBError(f'{root.name} 现在在分支 {branch or "（游离）"}，不是这一期的开发分支 {m["开发分支"]}，'
                      '复测会测错代码。先切回开发分支（或点「继续开发」按提示切换）再复测')
    scope = scope if scope in _SCOPE else '未通过'
    eng = period_engine(m)
    engine_bin(eng)
    m['开发会话'] = {'备注': note, '流程': f['id'], '引擎': eng['id'], '类型': '复测', '范围': scope}
    if m.get('待复测'):
        m['待复测']['自动'] = False
    save_meta(d, m)
    proc = _dev_spawn(d, root, branch, _retest_prompt(d.name, root, branch, f, docs, scope, note), '', 续跑次数=0)
    log(d, '开始复测', f'后台会话 pid {proc.pid}（{eng["名称"]} · {scope} · {branch}；{by}）' + (f'；{note}' if note else ''))
    return f'已开始复测「{d.name}」：后台会话 pid {proc.pid}，{_SCOPE[scope]}'


def retest_plan(period, auto, phones=1, scope='未通过', by='用户（网页）'):
    """网页：条件满足（空闲手机够了）时自动复测，或取消。"""
    d = period_dir(period)
    m = load_meta(d)
    p = m.get('待复测') or {}
    if auto:
        n = max(1, min(int(phones or 1), 10))
        m['待复测'] = dict(p, 自动=True, 手机=n, 范围=scope if scope in _SCOPE else '未通过', 设置时间=now(), 设置人=by)
        m['待复测'].pop('失败', None)
        msg = f'空闲手机够 {n} 台时会自动开始复测（每分钟检查一次），开始时弹通知'
    else:
        if p:
            p['自动'] = False
        m['待复测'] = p or None
        msg = '已取消自动复测'
    save_meta(d, m)
    log(d, '自动复测', msg)
    return msg


def test_report(period, summary, passed=0, failed=0, blocked=0, need=''):
    """复测（或开发中的测试）结束时汇报结果。"""
    d = period_dir(period)
    m = load_meta(d)
    s = m.get('开发会话') or {}
    rec = {'时间': now(), '通过': int(passed or 0), '失败': int(failed or 0), '阻塞': int(blocked or 0),
           '小结': (summary or '').strip(), '还缺': (need or '').strip(), '类型': s.get('类型') or '开发'}
    m.setdefault('复测记录', []).append(rec)
    if s.get('状态') == '运行中':
        s['已汇报'] = True
    if rec['阻塞']:
        m['待复测'] = dict(m.get('待复测') or {}, 自动=False, 原因=rec['还缺'] or rec['小结'][:200], 设置时间=now(), 设置人='复测汇报')
    else:
        m.pop('待复测', None)
    save_meta(d, m)
    log(d, '测试结果', f'通过 {rec["通过"]} / 失败 {rec["失败"]} / 阻塞 {rec["阻塞"]}：{rec["小结"][:150]}')
    if rec['阻塞'] and rec['还缺']:
        _add_issue(d, f'还有 {rec["阻塞"]} 个 case 没测成：{rec["还缺"][:80]}', rec['小结'], '', rec['还缺'], 'kb_test_report',
                   key=f'复测|{rec["还缺"]}')
    device_release(d.name, by='测试汇报')
    _notify(f'知识库 · {d.name} 测试结果', f'通过 {rec["通过"]}，失败 {rec["失败"]}，阻塞 {rec["阻塞"]}')
    return '已记录测试结果，手机已释放' + ('；复测会话可以结束了' if s.get('类型') == '复测' else '')


def _suggest_retest(d):
    """开发会话结束后：有因为环境没测成的 case 或手机不够的问题，就标成「待复测」，开发面板提示。"""
    m = load_meta(d)
    if m.get('待复测'):
        return
    ts = test_summary(session_flow(m), m.get('SDD目录'))
    open_ = [q for q in m.get('非阻断问题') or [] if q['状态'] == '待处理' and q['类型'] in _URGENT]
    if (ts and ts['环境阻塞']) or open_:
        m['待复测'] = {'自动': False, '手机': need_devices(m), '范围': '未通过', '设置时间': now(), '设置人': '自动发现',
                     '原因': (f'{ts["环境阻塞"]} 个 case 因环境没测成' if ts and ts['环境阻塞'] else '')
                     + (f'{"；" if ts and ts["环境阻塞"] else ""}{len(open_)} 个手机 / 账号 / 环境问题待处理' if open_ else '')}
        save_meta(d, m)


def dev_tick():
    """网页服务每分钟调用：同步测试报告里的非阻断问题；设了自动复测的期，空闲手机够了就开始复测。"""
    for n in period_names():
        d = PERIODS / n
        try:
            m = load_meta(d)
            if m.get('SDD目录') and session_flow(m).get('进度类型') == 'SDD':
                sync_test_issues(d, m)
            p = m.get('待复测') or {}
            s = dev_session(n)
            if not p.get('自动') or (s and s.get('状态') == '运行中'):
                continue
            free = sum(1 for x in devices(n) if x['空闲'] or x['本期'])
            if free < int(p.get('手机') or 1):
                continue
            try:
                retest_start(n, p.get('范围') or '未通过', f'空闲手机够了（{free} 台），自动复测', by='自动复测')
                _notify(f'知识库 · {n}', f'空闲手机够了（{free} 台），已自动开始复测')
            except KBError as e:
                m = load_meta(d)
                m['待复测'] = dict(m.get('待复测') or {}, 自动=False, 失败=str(e))
                save_meta(d, m)
                log(d, '自动复测', f'没能开始：{e}')
                _notify(f'知识库 · {n}', f'自动复测没能开始：{e}')
        except Exception as e:      # 某一期出错不影响其他期
            print('dev_tick:', n, repr(e), flush=True)


def _brief_tool(name, inp):
    inp = inp or {}
    if not isinstance(inp, dict):
        return str(inp)[:160]
    if name == 'Bash':
        return inp.get('description') or inp.get('command', '')[:160]
    if name in ('Read', 'Edit', 'Write', 'NotebookEdit'):
        return inp.get('file_path', '')
    if name == 'Skill':
        return f'/{inp.get("skill", "")} {inp.get("args", "")}'.strip()
    if name in ('Agent', 'Task'):
        return inp.get('description') or inp.get('subagent_type', '')
    if name.startswith('mcp__kb__'):
        return inp.get('question') or inp.get('note') or inp.get('status') or inp.get('id') or ''
    return json.dumps(inp, ensure_ascii=False)[:160]


_ACT = {}   # 日志路径 → [已读到的字节位置, 动作列表]：增量解析，日志再大也不漏前面的动作


def _parse_act(line):
    if line.startswith('{"type":"user"') or line.startswith('{"type":"system"') or line.startswith('{"type": "kb.engine"'):
        return []          # 工具返回、系统事件：又大又不用展示，不解析
    try:
        j = json.loads(line)
    except ValueError:
        return [{'类型': '输出', '内容': line[:300]}] if line.strip() and len(line) < 2000 else []
    if not isinstance(j, dict):
        return []
    out, t = [], j.get('type')
    if t == 'assistant':                                         # Claude
        sub = bool(j.get('parent_tool_use_id'))
        for c in (j.get('message') or {}).get('content') or []:
            if c.get('type') == 'text' and c.get('text', '').strip():
                out.append({'类型': '说明', '内容': c['text'].strip()[:600], '子任务': sub})
            elif c.get('type') == 'tool_use':
                nm = c.get('name', '')
                out.append({'类型': '工具', '工具': nm.replace('mcp__kb__', 'kb:'), '内容': _brief_tool(nm, c.get('input')),
                            '子任务': sub})
    elif t == 'result':                                          # Claude / Hermes
        r = _result_of(line)
        out.append({'类型': '结束', '内容': (r.get('结果') or '')[:600], '出错': bool(r.get('出错'))})
    elif t == 'item.completed':                                  # Codex
        it = j.get('item') or {}
        k = it.get('type')
        if k == 'agent_message' and (it.get('text') or '').strip():
            out.append({'类型': '说明', '内容': it['text'].strip()[:600]})
        elif k == 'command_execution':
            out.append({'类型': '工具', '工具': 'shell', '内容': str(it.get('command') or '')[:200]})
        elif k == 'mcp_tool_call':
            nm = f'{it.get("server") or ""}:{it.get("tool") or ""}'
            out.append({'类型': '工具', '工具': nm.replace('kb:', 'kb:'), '内容': _brief_tool(it.get('tool') or '', it.get('arguments'))})
        elif k == 'file_change':
            fs = [c.get('path', '') for c in it.get('changes') or [] if isinstance(c, dict)]
            out.append({'类型': '工具', '工具': '改文件', '内容': '、'.join(fs)[:200]})
    elif t in ('turn.failed', 'error'):                          # Codex
        out.append({'类型': '结束', '内容': str((j.get('error') or {}).get('message') or j.get('message') or '出错')[:600],
                    '出错': True})
    elif t == 'text' and (j.get('text') or '').strip():          # Hermes
        out.append({'类型': '说明', '内容': j['text'].strip()[:600]})
    elif t == 'tool_use':                                        # Hermes
        nm = j.get('name') or j.get('tool') or ''
        out.append({'类型': '工具', '工具': re.sub(r'^mcp_kb_', 'kb:', nm), '内容': _brief_tool(nm, j.get('input') or j.get('args'))})
    return out


def dev_activity(logf, n=30, full=False):
    """从 stream-json 日志里取动作：说了什么、调了什么工具（子 agent 的标为子任务）、最后结果。"""
    p = Path(logf or '')
    if not p.is_file():
        return []
    key = str(p)
    pos, acts = _ACT.get(key) or [0, []]
    size = p.stat().st_size
    if size < pos:
        pos, acts = 0, []
    if size > pos:
        with p.open('rb') as fh:
            fh.seek(pos)
            data = fh.read()
        cut = data.rfind(b'\n') + 1          # 只处理完整的行，没写完的下次再读
        for line in data[:cut].decode('utf-8', 'ignore').splitlines():
            acts += _parse_act(line)
        pos += cut
        _ACT[key] = [pos, acts[-5000:]]
    return list(acts) if full or not n else acts[-n:]


def session_activity(s, n=30):
    """当前会话（含自动续跑的几轮）最近的动作。"""
    s = s or {}
    out = []
    for f in (s.get('历史日志') or []) + [s.get('日志')]:
        out += dev_activity(f, n)
    return out[-n:]


def _sdd_status(docs):
    f = Path(docs) / 'sdd-status.md'
    res = {}
    if f.exists():
        for line in read_text(f).splitlines():
            mm = re.match(r'^([a-z0-9_]+):\s*(.*)$', line.strip())
            if mm:
                res[mm.group(1)] = mm.group(2).strip()
    return res


def sdd_progress(docs):
    """从 SDD 文档目录解析开发进度与测试进度。"""
    docs = Path(docs or '')
    if not docs.is_dir():
        return None
    st = _sdd_status(docs)
    steps = []
    for label, key, doc in (('需求分析', 'step1_pm', 'prd.md'), ('接口规格', 'step1_api', 'api-spec.md'),
                            ('技术规划', 'step2', 'arch_dev_plan.md'), ('代码实现', 'step3', '')):
        steps.append({'名称': label, '状态': st.get(key, 'pending') or 'pending',
                      '修订': st.get(key + '_revisions', ''), '文档': str(docs / doc) if doc and (docs / doc).exists() else ''})
    idx, total = st.get('step3_current_index', ''), st.get('step3_task_total', '')
    task = {'当前': st.get('step3_current_task', ''), '序号': int(idx) if idx.isdigit() else 0,
            '总数': int(total) if total.isdigit() else 0, '阶段': st.get('step3_task_phase', ''),
            '审查轮次': st.get('step3_task_review_round', ''), '设备修复轮次': st.get('step3_device_fix_round', ''),
            '阻塞': st.get('step3_task_blocked_reason', '') or st.get('step3_device_block_reason', ''),
            '待决策': st.get('step3_pending_decision', ''),
            '审查发现': st.get('step3_review_findings', ''), '设备发现': st.get('step3_device_findings', '')}
    tests = {'用例': 0, '优先级': {}, '统计': {}, '报告': []}
    at = docs / 'agent-test.json'
    if at.exists():
        try:
            cs = json.loads(read_text(at)).get('cases') or []
            tests['用例'] = len(cs)
            for c in cs:
                k = c.get('priority') or '其他'
                tests['优先级'][k] = tests['优先级'].get(k, 0) + 1
        except (ValueError, AttributeError):
            pass
    summ = docs / 'agentdevice-summary.md'
    if summ.exists():
        part = read_text(summ).split('## 按 TASK', 1)[0]
        for k, v in re.findall(r'\|\s*\S*\s*(PASS|FAIL|BLOCKED|ERROR)\s*\|\s*(\d+)\s*\|', part):
            tests['统计'][k] = int(v)
        tests['报告'].append(str(summ))
    bb = docs / 'tests' / 'blackbox' / 'blackbox-test.md'
    if bb.exists():
        tests['黑盒用例'] = str(bb)
    key = lambda x: int(re.search(r'(\d+)', x.name).group(1)) if re.search(r'(\d+)', x.name) else 0
    tests['报告'] += [str(x) for x in sorted(docs.glob('agentdevice-task-*.md'), key=key)]
    reviews = [str(x) for x in sorted(docs.glob('review-task-*.md'), key=key)]
    return {'目录': str(docs), '步骤': steps, '任务': task, '测试': tests, '审查报告': reviews,
            '状态文件': str(docs / 'sdd-status.md') if (docs / 'sdd-status.md').exists() else ''}


def dev_activity_all(period, limit=3000):
    """这一期所有后台会话（含自动续跑、来源更新）的动作，按时间顺序，每个日志前加一行分隔。"""
    d = period_dir(period)
    out = []
    for f in sorted((d / DEV_DIR).glob('*.jsonl')) if (d / DEV_DIR).exists() else []:
        acts = dev_activity(f, 100000, full=True)
        if acts:
            t = re.sub(r'^(?:(.+)-)?(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)(\d\d)$', r'\2-\3-\4 \5:\6:\7 \1', f.stem).strip()
            out.append({'类型': '会话', '内容': f'{t}（{len(acts)} 个动作）'})
            out += acts
    return out[-limit:]


def dev_overview(period):
    d = period_dir(period)
    s = dev_session(d.name)
    sync_test_issues(d)
    m = load_meta(d)
    return {'状态': m.get('状态'), '免打扰': bool(m.get('免打扰')), '会话': s,
            '会话记录': sorted((x.name for x in (d / DEV_DIR).glob('*.jsonl')), reverse=True) if (d / DEV_DIR).exists() else [],
            '动作': session_activity(s), '进度': flow_progress(session_flow(m), m.get('SDD目录')),
            '流程': m.get('开发流程', ''), '当前流程': session_flow(m)['名称'], '默认流程': get_flow()['名称'],
            '流程列表': [{'id': x['id'], '名称': x['名称']} for x in flows()],
            '引擎': m.get('AI引擎', ''), '默认引擎': get_engine()['名称'],
            '引擎列表': [{'id': x['id'], '名称': x['名称']} for x in engines()],
            '待确认': m.get('待确认') or [], '对话': (m.get('对话') or [])[-8:], '设备': devices(d.name) if _adb() else None,
            '非阻断问题': m.get('非阻断问题') or [], '复测': retest_info(d, m)}


# ---------------------------------------------------------------- 网址导入（Confluence / 网页）

SRC_DIR = '来源快照'


def _fetch():
    import fetch
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
    pg['指纹'] = _fingerprint(pg)
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


# ---------------------------------------------------------------- 来源刷新（按登记的网址重新抓取）

CHANGE_DIR = '变更'          # 来源快照/变更/：每次原文变化的差异
REFRESH_STATUSES = ('收集中', '已批准开发', '开发中')   # 自动检查只管这些状态的期
_UPD = {}                    # 期名 -> 「Claude 更新条目」后台进程


def _fingerprint(pg):
    import hashlib
    h = hashlib.sha256((pg.get('md') or '').encode())
    for e in pg.get('embedded') or []:
        h.update(str(e[2]).encode())
    return h.hexdigest()[:16]


def _doc_body(text):
    """去掉文档 / 快照顶部的标题和「> 」元信息，只留正文。"""
    lines = text.splitlines()
    i = 1 if lines and lines[0].startswith('# ') else 0
    while i < len(lines) and (not lines[i].strip() or lines[i].startswith('> ')):
        i += 1
    return '\n'.join(lines[i:]).strip()


def _norm(text):
    # 内嵌图片的引用路径导入时会改写，比较时统一成「图N」
    text = re.sub(r'\]\(嵌入图片(\d+)\)', lambda x: f'](图{int(x.group(1))})', text)
    text = re.sub(r'\]\([^)]*-图(\d+)\.\w+\)', lambda x: f'](图{int(x.group(1))})', text)
    return '\n'.join(x.rstrip() for x in text.strip().splitlines())


def _src_params(d, s):
    """重新导入要用的参数；老来源没存的，从登记的文件推出来。"""
    p = dict(s.get('导入参数') or {})
    files = s.get('文件') or []
    if files:
        p.setdefault('分类', files[0].split('/')[0])
        p.setdefault('文件名', Path(files[0]).name)
        p.setdefault('附件', (['embedded'] if any(f'/{PROTO_DIR}/' in f for f in files) else [])
                     + [Path(f).name for f in files[1:] if f'/{PROTO_DIR}/' not in f])
    if '整页' not in p:
        doc, snap = d / files[0] if files else None, d / (s.get('快照') or '_')
        a = _doc_body(read_text(doc)) if doc and doc.exists() else ''
        b = _doc_body(read_text(snap)) if snap.is_file() else ''
        p['整页'] = bool(b) and len(a) >= 0.8 * len(b)
    return p


def _item_hit(old, new, doc):
    """条目内容是否落在原文变化的地方。找不到条目位置时按「受影响」处理。"""
    import difflib
    ol = old.splitlines()
    want = {x.strip() for x in doc.splitlines() if len(x.strip()) >= 6}
    pos = [i for i, x in enumerate(ol) if x.strip() in want]
    if not want or len(pos) < 0.3 * len(want):
        return True
    lo, hi = min(pos) - 3, max(pos) + 3
    for tag, i1, i2, _, _ in difflib.SequenceMatcher(None, ol, new.splitlines(), autojunk=False).get_opcodes():
        if tag != 'equal' and i1 <= hi and i2 >= lo:
            return True
    return False


def _save_change(d, s, old, new, why):
    import difflib
    cd = d / SRC_DIR / CHANGE_DIR
    cd.mkdir(parents=True, exist_ok=True)
    f = cd / f'{s["编号"]}-{datetime.now():%Y%m%d-%H%M%S}.md'
    n = 2
    while f.exists():
        f = cd / f'{s["编号"]}-{datetime.now():%Y%m%d-%H%M%S}-{n}.md'
        n += 1
    diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(), '旧版', '新版', n=2, lineterm=''))
    add = sum(1 for x in diff if x.startswith('+') and not x.startswith('+++'))
    rm = sum(1 for x in diff if x.startswith('-') and not x.startswith('---'))
    body = diff[:1500] + (['…（差异太长，已截断）'] if len(diff) > 1500 else [])
    f.write_text(f'# {s["编号"]}《{s["标题"]}》{s.get("条目") or ""} 原文变化\n\n> 来源：{s["地址"]}\n> 发现时间：{now()}\n'
                 f'> {why}\n> 新增 {add} 行，删除 {rm} 行\n\n```diff\n' + '\n'.join(body) + '\n```\n', 'utf-8')
    return f, f'+{add} / -{rm} 行'


def _notice(d, text):
    """给正在开发这一期的会话留话：下次它调用 kb_log / kb_wait_answer / kb_dev_package 时会看到。"""
    m = load_meta(d)
    if m.get('状态') in DEV_OK or m.get('开发会话'):   # 暂停中的也留着，继续开发时会看到
        m.setdefault('变更通知', []).append(f'[{now()}] {text}')
        save_meta(d, m)


def take_notices(period):
    try:
        d = period_dir(period)
    except KBError:
        return ''
    m = load_meta(d)
    chat = _take_chat(d, m)
    ns = m.pop('变更通知', None)
    if not ns:
        if chat:
            save_meta(d, m)
        return chat
    save_meta(d, m)
    return chat + ('\n\n【需求来源有更新】（含链接更正）\n' + '\n'.join(f'- {x}' for x in ns)
            + '\n请 kb_read 差异文件，评估对已完成 / 进行中任务的影响：'
            + (flow_text(session_flow(m), '需求变更提示', 期名=d.name, 文档目录=m.get('SDD目录') or '')
               or '先 kb_dev_prepare 同步资料副本，需要取舍时用 kb_ask 确认，并 kb_log 记录') + '。')


def _refresh_one(d, s):
    """返回 (结果, 说明)。结果：无变化 / 已更新 / 条目待更新 / 跳过 / 失败。"""
    f = _fetch()
    url, sid = s['地址'], s['编号']
    if s.get('类型') == '设计稿':
        if 'figma.com' not in (urlparse(url).hostname or ''):
            return '跳过', '蓝湖没有开放接口，不能自动刷新；请在蓝湖导出画板后拖进网页「设计图」'
        try:
            ver, at = f.figma_version(url)
        except f.FetchError as e:
            return '失败', str(e)
        if ver and str(ver) == str(s.get('页面版本')):
            return '无变化', f'Figma 版本 {ver}'
        old = s.get('页面版本')
        import_design(d.name, url, s.get('条目', ''), s.get('简介', ''))
        return '已更新', f'Figma 版本 {old} → {ver}（{at}），画板和设计规格已重新导出'
    f.drop_cache(url)
    try:
        pg = f.get_page(url)
    except f.FetchError as e:
        return '失败', str(e)
    fp = _fingerprint(pg)
    if s.get('指纹'):
        same = fp == s['指纹']
    elif pg.get('version') and s.get('页面版本'):
        same = str(pg['version']) == str(s['页面版本'])
    else:
        snap = d / (s.get('快照') or '_')
        same = snap.is_file() and _norm(_doc_body(read_text(snap))) == _norm(pg['md'])
    if same:
        if not s.get('指纹'):
            _set_src(d, sid, 指纹=fp)
        return '无变化', (f'页面版本 v{pg["version"]}' if pg.get('version') else '内容一致')
    snap = d / (s.get('快照') or '_')
    old_md = _norm(_doc_body(read_text(snap))) if snap.is_file() else ''
    ver = (f'v{s.get("页面版本")} → v{pg["version"]}' if pg.get('version') else f'最后修改 {pg.get("updated_at") or "未知"}')
    p = _src_params(d, s)
    if not p['整页']:
        doc = d / s['文件'][0] if s.get('文件') else None
        doc_text = _doc_body(read_text(doc)) if doc and doc.exists() else ''
        if old_md and doc_text and not _item_hit(old_md, _norm(pg['md']), _norm(doc_text)):
            chg, stat = _save_change(d, s, old_md, _norm(pg['md']), f'页面 {ver}；改动不在条目「{s.get("条目")}」范围内')
            _save_snapshot(d, pg)
            _set_src(d, sid, 指纹=fp, 页面版本=pg.get('version'), 抓取时间=now(),
                     最后修改=f'{pg.get("updated_by", "")} {pg.get("updated_at", "")}'.strip())
            _add_change(d, sid, ver, stat, chg, '条目未受影响')
            return '无变化', f'页面 {ver} 有改动（{stat}），但不在条目「{s.get("条目")}」范围内，条目文档不用改'
    chg, stat = _save_change(d, s, old_md, _norm(pg['md']), f'页面 {ver}')
    if p['整页']:
        att = p.get('附件') or []
        import_url(d.name, url, p['分类'], s.get('条目', ''), s.get('简介', ''), '', att or None, p.get('文件名', ''))
        _set_src(d, sid, 导入参数=p)
        _add_change(d, sid, ver, stat, chg, '已自动更新')
        _notice(d, f'{sid}《{s["标题"]}》原文更新（{ver}，{stat}），已重新导入；差异：{chg}')
        return '已更新', f'{ver}（{stat}），已重新导入整页；差异见 {chg.relative_to(d)}'
    _save_snapshot(d, pg)
    _set_src(d, sid, 待更新=True, 导入参数=p)
    _add_change(d, sid, ver, stat, chg, '条目待更新')
    _notice(d, f'{sid}《{s["标题"]}》条目「{s.get("条目")}」原文有变化（{ver}，{stat}），条目文档待更新；差异：{chg}')
    return '条目待更新', (f'{ver}（{stat}），条目「{s.get("条目")}」的原文有变化；快照已更新，'
                      f'条目文档需要重新整理（网页点「交给 Claude 更新」，或让 Claude 处理）。差异见 {chg.relative_to(d)}')


def _set_src(d, sid, **kv):
    m = load_meta(d)
    s = next(x for x in m['来源'] if x['编号'] == sid)
    s.update(kv)
    save_meta(d, m)
    return s


def _add_change(d, sid, ver, stat, chg, how):
    m = load_meta(d)
    s = next(x for x in m['来源'] if x['编号'] == sid)
    s.setdefault('变更记录', []).append({'时间': now(), '版本': ver, '改动': stat,
                                       '差异': str(chg.relative_to(d)), '处理': how})
    s['核对'] = '待核对' if how != '条目未受影响' else s.get('核对', '待核对')
    save_meta(d, m)


def refresh_sources(period, sid='', by='Claude'):
    """按登记的网址重新抓取来源：没变就记一下检查时间；整页 / 设计稿自动重新导入；只导了条目的标记待更新。"""
    d = period_dir(period)
    srcs = load_meta(d).get('来源') or []
    if sid:
        srcs = [x for x in srcs if x['编号'] == sid]
        if not srcs:
            raise KBError(f'没有这条来源：{sid}')
    if not srcs:
        return f'「{d.name}」还没有登记来源（网址导入的资料）'
    out, todo = [], []
    for s in srcs:
        try:
            r, why = _refresh_one(d, s)
        except KBError as e:
            r, why = '失败', str(e)
        _set_src(d, s['编号'], 检查时间=now(), 检查结果=r, **({'检查说明': why} if r != '无变化' else {'检查说明': ''}))
        if r != '无变化':
            log(d, '刷新来源', f'{s["编号"]}《{s["标题"]}》{s.get("条目") or ""} → {r}：{why}（{by}）')
        out.append(f'- {s["编号"]}《{s["标题"]}》{s.get("条目") or ""}：{r}　{why}')
        if r == '条目待更新':
            todo.append(s['编号'])
    head = f'「{d.name}」检查了 {len(srcs)} 条来源：'
    tail = ''
    if todo:
        tail = ('\n\n只导入了条目的来源原文有变化，需要重新整理条目文档：' + '、'.join(todo) +
                '\n做法：kb_read 差异文件和新快照，找到条目的新内容，用 kb_import_url 以同样的 url、item、category、filename '
                '重新导入（content 放更新后的条目原文，summary 写明这次改了什么），然后 kb_log 记录变化要点。')
    return head + '\n' + '\n'.join(out) + tail


def refresh_all(by='自动检查'):
    """所有未完成的期都检查一遍（网页服务定时调用）。返回有变化的条目说明。"""
    changed = []
    for name in period_names():
        d = period_dir(name)
        m = load_meta(d)
        if m.get('状态') not in REFRESH_STATUSES or not m.get('来源'):
            continue
        r = refresh_sources(name, by=by)
        hits = [x for x in r.splitlines() if x.startswith('- ') and ('已更新' in x or '待更新' in x)]
        if hits:
            changed.append((name, hits))
            _notify(f'知识库 · {name} 需求有更新', f'{len(hits)} 条来源有变化，请在网页「来源」里查看')
    return changed


def _update_prompt(name, sids):
    return f"""你是由知识库网页启动的【后台无人值守】知识库维护会话，只做一件事：更新期「{name}」里原文已变化的来源条目 {"、".join(sids)}。
终端里没有人，不要提问，不要改代码仓库，也不要改期的状态。对每个来源：
1. kb_iteration 查看「{name}」的来源清单，找到该来源的地址、条目、本地文件、快照和最新一条变更记录（差异文件）。
2. kb_read 读差异文件、新快照和现有条目文档，找出条目在新原文里的完整内容（表格行、章节，连同必要的表头和上下文）。
3. 用 kb_import_url 以同样的 url、item、category、filename 重新导入：content 放更新后的条目原文（保持原意、不改写），
   summary 在原简介基础上写明这次改了什么；条目关联的附件或设计稿地址变了，按知识库规则一并导入。
4. 用 kb_log 记录这次需求变化的要点（改了什么、可能影响哪些功能），然后结束。"""


def update_session(name):
    d = period_dir(name)
    s = load_meta(d).get('更新会话')
    if s and s.get('状态') == '运行中' and d.name not in _UPD and not _alive(s.get('pid', 0)):
        _upd_finish(d.name)
        s = load_meta(d).get('更新会话')
    return s


def _upd_finish(name, code=None):
    d = period_dir(name)
    m = load_meta(d)
    s = m.get('更新会话') or {}
    if s.get('状态') != '运行中':
        return
    s.update(状态='已结束', 结束时间=now(), 退出码=code, **_dev_result(s.get('日志', '')))
    save_meta(d, m)
    left = [x['编号'] for x in m.get('来源') or [] if x.get('待更新')]
    log(d, '条目更新会话结束', f'退出码 {code}' + (f'；仍待更新：{"、".join(left)}' if left else '；条目已全部更新'))
    _notify(f'知识库 · {d.name}', '来源条目已更新' if not left else f'还有 {len(left)} 条来源待更新')


def claude_update(period):
    """网页「交给 Claude 更新」：后台启动 Claude 重新整理原文已变化的条目。不作为 MCP 工具提供。"""
    d = period_dir(period)
    s = update_session(d.name)
    if s and s.get('状态') == '运行中':
        raise KBError('Claude 正在更新这一期的来源条目')
    sids = [x['编号'] for x in load_meta(d).get('来源') or [] if x.get('待更新')]
    if not sids:
        raise KBError('没有待更新的来源条目')
    eng = get_engine()
    (d / DEV_DIR).mkdir(exist_ok=True)
    logf = d / DEV_DIR / f'更新来源-{datetime.now():%Y%m%d-%H%M%S}.jsonl'
    proc = engine_popen(eng, _update_prompt(d.name, sids), f'kb·更新·{d.name}', logf, ROOT)
    _UPD[d.name] = proc
    m = load_meta(d)
    m['更新会话'] = {'pid': proc.pid, '状态': '运行中', '开始时间': now(), '来源': sids, '日志': str(logf)}
    save_meta(d, m)
    log(d, '更新来源条目', f'后台会话 pid {proc.pid}：{"、".join(sids)}')

    def wait():
        code = proc.wait()
        _UPD.pop(d.name, None)
        _upd_finish(d.name, code)
    threading.Thread(target=wait, daemon=True).start()
    return f'已交给 {eng["名称"]} 在后台更新 {"、".join(sids)}，完成后会通知你'


# ---------------------------------------------------------------- 模糊添加（网页随手粘贴，交给 Claude 判断归档）

ADD_FILE = SYS / '模糊添加.json'
ADD_DIR = SYS / '模糊添加'
_ADD = {}                    # 编号 -> 「模糊添加」后台进程
_ADD_LOCK = threading.Lock()


def _add_prompt(text, period):
    where = (f'用户指定放进期「{period}」。' if period else
             '用户没有指定期：按需求名、版本号（如「综合版26」）、主题匹配已有的期；都对不上再 kb_create_iteration 新建一期，期名参照已有期的命名（如「综合版26-聊天室语音麦播放歌曲权限」）。')
    return f"""你是由知识库网页启动的【后台无人值守】知识库整理会话。用户在网页「模糊添加」里随手粘贴了下面的内容，请按知识库规则把它加进知识库。
终端里没有人，不要提问；不要改代码仓库，不要改期的状态，不要批准或开始开发。

用户输入：
<<<
{text}
>>>

做法：
1. 先 kb_overview 看已有的期。{where}
2. 按内容处理（细则见知识库 MCP 说明的规则 2、6、7、8），一段输入里有几件事就逐件处理：
   - 网址 + 条目（如「编号8」）：kb_fetch_url 读原文定位条目，条目链接的需求页、PRD 也读；kb_import_url 导入条目原文和 PRD（PRD 的页面内嵌图片用 attachments ["embedded"]）；条目带设计稿地址的用 kb_import_design。
   - 只有网址：kb_fetch_url 看是什么，按内容整页导入，或用 kb_add_note 登记为链接。
   - 成篇需求、会议纪要：kb_write_doc；零散文字、分支、链接：kb_add_note。
   - 网站账号、测试账号、Wi-Fi、代理、VPN、环境配置等通用信息：kb_base_save（密码、令牌等标机密），不放进期。
3. 需要人操作才能继续的（抓取要登录、缺 Figma 令牌等）：把链接用 kb_add_note 登记下来，接着做别的，不要卡住。
4. 看不出条目指哪一项、或判断不了归属时：不要猜，也不要新建期，直接结束，在回复里列出候选，请用户补充后重新提交。
5. 最后的回复会原样显示在网页上：简短列出放进了哪一期、导入 / 记下了什么（来源编号、文件名）、需要用户做的事（来源核对、登录命令等）。回复里绝不能出现机密明文。"""


def _add_load():
    try:
        return json.loads(read_text(ADD_FILE)) if ADD_FILE.exists() else []
    except ValueError:
        return []


def _add_save(items):
    tmp = ADD_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(items[-50:], ensure_ascii=False, indent=1), 'utf-8')
    tmp.replace(ADD_FILE)


def _add_finish(aid, code=None):
    with _ADD_LOCK:
        items = _add_load()
        x = next((i for i in items if i['编号'] == aid), None)
        if not x or x.get('状态') != '运行中':
            return
        x.update(状态='已结束', 结束时间=now(), 退出码=code, **_dev_result(x.get('日志', '')))
        _add_save(items)
    _notify('知识库 · 模糊添加', (x.get('结果') or '已结束').splitlines()[0])


def add_sessions(n=20):
    """最近的模糊添加记录（新的在前），运行中的带最近动作。"""
    for x in _add_load():
        if x.get('状态') == '运行中' and x['编号'] not in _ADD and not _alive(x.get('pid', 0)):
            _add_finish(x['编号'])
    out = []
    for x in reversed(_add_load()[-n:]):
        x = dict(x)
        if x.get('状态') == '运行中':
            x['动作'] = dev_activity(x.get('日志'), 8)
        out.append(x)
    return out


def claude_add(text, period=''):
    """网页「模糊添加」：用户随手粘贴（网址 + 编号、几句需求、账号……），后台启动 Claude 按知识库规则判断归属并导入。不作为 MCP 工具提供。"""
    text = (text or '').strip()
    if not text:
        raise KBError('请粘贴要添加的内容')
    if period:
        period = period_dir(period).name
    eng = get_engine()
    ADD_DIR.mkdir(exist_ok=True)
    aid = f'A{datetime.now():%Y%m%d%H%M%S}{uuid.uuid4().hex[:4]}'
    logf = ADD_DIR / f'{aid}.jsonl'
    proc = engine_popen(eng, _add_prompt(text, period), f'kb·模糊添加·{aid}', logf, ROOT)
    _ADD[aid] = proc
    with _ADD_LOCK:
        items = _add_load()
        items.append({'编号': aid, '输入': text[:4000], '期': period, 'pid': proc.pid, '状态': '运行中', '引擎': eng['名称'],
                      '开始时间': now(), '日志': str(logf)})
        _add_save(items)

    def wait():
        code = proc.wait()
        _ADD.pop(aid, None)
        _add_finish(aid, code)
    threading.Thread(target=wait, daemon=True).start()
    return f'已交给 {eng["名称"]} 在后台整理，完成后会通知你'


# ---------------------------------------------------------------- 更正链接（设计稿 / 文档地址给错了）

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


# ---------------------------------------------------------------- MCP

INSTRUCTIONS = """本地知识库（按「期」管理需求 / 设计图 / 接口文档 / 其他资料，并索引本地代码仓库）。
规则：
1. 回答与业务、需求、接口、历史决策有关的问题前，先 kb_search。
2. 用户给出资料文件时，用 kb_add_material 归档到对应的期；用户粘贴的成篇需求、会议纪要，用 kb_write_doc 存成文档，保证每期有完整记录。
   零散的文字资料用 kb_add_note 原样记下（不必是完整原料）：产品说的几句话、要开发的分支、其他小组给的文档地址、账号/环境等。
   分类按内容选（产品说的需求 → 需求，接口相关 → 接口文档，分支/链接/其他 → 其他资料）；能看出是谁说的就填「来自」。
   链接只登记、不强求抓取；之后能访问再按规则 6 导入。内容有变化用 kb_update_note 修改，不要重复新增。
3. 设计图没有文字说明时，用 Read 查看图片后调用 kb_annotate_image 写说明（页面、模块、交互、文案），便于以后检索。
4. 开发必须由用户批准：只有期状态是「已批准开发」或「开发中」时才能写代码，入口是 kb_dev_package。
   批准只能由用户本人操作：终端运行 kb approve <期名>，或在知识库网页点「开始开发」（输入期名确认）。
   你绝不能代为执行 kb approve、调用知识库网页的接口（开始/停止开发、回答待确认问题等），或用其他方式绕过。
5. 开发按这一期的「开发流程」执行（用户在知识库网页「⚙ 设置」里配置，默认是「通用模板」），不要自行换用别的流程，除非这一期选的就是它。
   具体命令写在 kb_dev_package 的「开发约定」里。开发开始时先调用 kb_dev_prepare：它按流程定位文档目录、把本期资料拷过去并列出候选链接
   （SDD 流程：随即按 sdd-start.md 各栏注释把链接、负责范围、接口说明填进空栏，不覆盖已填内容，不用问用户，再用 /sdd-next 推进）。
   开发中需要用户确认时（等人审阅方案 / 接口、待确认问题、方案取舍、操作被拦截等），
   用 kb_ask 发到网页（写清问题、背景、选项、你的建议 recommend），再用 kb_wait_answer 等回答并照做，拿到回答前不要自行决定。
   这一期开了「免打扰」时 kb_ask 会直接返回：按你的建议执行，并用 kb_log 记录理由。免打扰由用户在网页随时开关。
8. 基础知识库（所有期共用的基础上下文）：用户给出网站账号密码、测试某功能用的账号、Wi-Fi / 代理 / VPN、环境配置等通用信息时，
   用 kb_base_save 存进去（密码、令牌、密钥等字段标记 机密=true，只存钥匙串）；回答问题、开发、测试前先用 kb_base 查。
   机密明文只在真正执行时用 kb_base_secret 读取，绝不写进代码、文档、提交、知识库记录或回复里；只属于某一期的信息仍记在那一期。
   开发中的关键决定、接口变更用 kb_log 记录；完成后用 kb_set_status 标为「已完成」。
6. 用户给出网址（Confluence 等）并说「把 XX 加到知识库」时：先 kb_fetch_url 读原文，找到对应条目（如「编号6」所在的表格行或章节）及其关联的链接页面和附件；
   条目里链接到的其他 Confluence 页面也要 kb_fetch_url 看一下，相关的一并导入。然后用 kb_import_url 导入：content 放该条目的原文（保持原意，可带表头），
   summary 写清楚讲了什么，attachments 选相关附件。导入后向用户逐条汇报来源地址和简介，提醒其在网页这一期「资料 → 来源核对」里核对。
   不确定条目指的是哪一项时，把候选列出来问用户，不要猜。抓取提示需要登录时，请用户在终端运行 kb login <主机> <用户名>，不要索要密码。
   用户说需求 / 设计改了、要更新资料时，用 kb_refresh_sources 按登记的网址重新抓取；返回「条目待更新」的，读差异和新快照，
   用 kb_import_url 以同样的 url、item、category、filename 重新导入更新后的条目原文，并向用户汇报改了什么。
   工具结果末尾出现【需求来源有更新】时，按其提示评估对开发的影响。
   用户说某个链接（设计稿、文档地址）给错了时，用 kb_fix_link 更正，不要只改一处；开发中也可以改，会提醒开发会话重新下载物料。
7. 原型图和设计稿要分清：PRD / Axure 里的图是原型图或参考图（存在 需求/原型图/），只用来理解交互和逻辑；
   要实现的产品图是「设计稿地址」那一项（Figma 或蓝湖链接），用 kb_import_design 导入到「设计图」。
   导入需求条目时，若条目带设计稿地址，必须一并导入设计稿。开发时 UI（布局、尺寸、颜色、文案、字号）以设计稿为准，原型与设计稿冲突时以设计稿为准并用 kb_log 记录。
9. 手机是多个期共用的：在手机上装包、测试前先 kb_devices 看、kb_device_claim 申请，只在申请到的手机上操作（adb -s <序列号>），
   不要往别的期占着的手机装包（会覆盖对方的包、打断对方测试），测完 kb_device_release。
   手机不够或没连、缺测试账号、环境不满足等让部分验证做不了、但不影响继续开发的问题，用 kb_issue 记下（写清要什么），然后继续，不要停下等；
   用户会在网页看到并收到通知，条件具备后在网页点「复测」补测。复测会话测完用 kb_test_report 汇报。"""

S = lambda **props: {'type': 'object', 'properties': props}
STR = lambda d: {'type': 'string', 'description': d}
CAT = {'type': 'string', 'enum': CATS, 'description': '分类'}

TOOLS = [
    ('kb_overview', '知识库总览：每期状态与材料数、代码仓库、收件箱待整理文件。', S(), []),
    ('kb_iteration', '查看一期的详情：状态、说明、各分类材料清单、关联仓库、最近记录。',
     S(name=STR('期名（可写部分，唯一匹配即可）')), ['name']),
    ('kb_create_iteration', '新建一期（需求批次/版本），生成 需求/设计图/接口文档/其他资料 目录和记录文件。',
     S(name=STR('期名，建议「日期-主题」，如 2026-11-签到活动v2'), summary=STR('这一期的简介')), ['name']),
    ('kb_add_material', '把本地文件或目录（含收件箱里的）归档到某一期；同名文件自动保留旧版本。不传分类会按文件名自动判断。',
     S(iteration=STR('期名'), path=STR('源文件或目录的绝对路径'), category=CAT, note=STR('备注，写进记录')),
     ['iteration', 'path']),
    ('kb_write_doc', '把文字内容（粘贴的需求、会议纪要、接口说明等）保存为某期下的文档。',
     S(iteration=STR('期名'), category=CAT, filename=STR('文件名，默认 .md'), content=STR('文档内容（Markdown）'),
       note=STR('备注')), ['iteration', 'category', 'filename', 'content']),
    ('kb_add_note', '给某期记一条文字资料（不是文件）：产品说的几句话、要开发的分支、其他小组给的文档地址等，原样保存、可检索，开发包会带上。'
                    '不传分类时：文字 → 需求，分支 / 链接 → 其他资料。',
     S(iteration=STR('期名'), content=STR('文字内容，原样记录；只有链接时可空'), category=CAT,
       kind={'type': 'string', 'enum': NOTE_KINDS, 'description': '类型：文字 / 链接 / 分支 / 其他；不传自动判断'},
       title=STR('简短标题，可空'), url=STR('链接地址（类型为链接时）'), source=STR('来自谁 / 哪个小组，如「产品 小王」')),
     ['iteration']),
    ('kb_update_note', '修改或删除某期的一条文字资料（编号如 T001，见 kb_iteration）。只传要改的字段。',
     S(iteration=STR('期名'), id=STR('编号，如 T001'), content=STR('新内容'), category=CAT,
       kind={'type': 'string', 'enum': NOTE_KINDS}, title=STR('新标题'), url=STR('新链接'), source=STR('来自'),
       delete={'type': 'boolean', 'description': 'true 表示删除这条'}), ['iteration', 'id']),
    ('kb_search', '全文检索知识库文档和已登记代码。多个关键词用空格分隔（同时命中优先）。',
     S(query=STR('关键词'), iteration=STR('限定某一期'), category=CAT,
       scope={'type': 'string', 'enum': ['all', 'docs', 'code'], 'description': '范围，默认 all'},
       repo=STR('限定某个代码仓库'), limit={'type': 'integer', 'description': '条数，默认 10，最多 50'}), ['query']),
    ('kb_read', '读取知识库或已登记仓库中的文件文本（自动解析 docx/pdf/xlsx/pptx/html），支持分段。',
     S(path=STR('文件绝对路径'), start={'type': 'integer', 'description': '起始行，默认 1'},
       max_lines={'type': 'integer', 'description': '最多行数，默认 300'}), ['path']),
    ('kb_annotate_image', '给设计图写文字说明（保存为同目录 <图片名>.说明.md 并建索引）。',
     S(path=STR('图片绝对路径'), description=STR('图片说明：页面、模块、交互、文案、状态')), ['path', 'description']),
    ('kb_add_repo', '登记本地代码文件夹并建立代码索引（大仓库首次可能需要几分钟）。',
     S(path=STR('代码目录绝对路径'), name=STR('仓库名，默认目录名')), ['path']),
    ('kb_link_repo', '把已登记的代码仓库关联到某一期（开发包会带上它）。',
     S(iteration=STR('期名'), repo=STR('仓库名')), ['iteration', 'repo']),
    ('kb_reindex', '重建/增量更新索引。', S(target=STR('all / docs / code / 仓库名，默认 all')), []),
    ('kb_dev_prepare', '开发前准备（已批准开发后、按流程推进前调用）：按这一期的开发流程认出目标仓库和分支、定位文档目录，'
                       '把本期全部资料拷到 文档目录/资料目录名/（不进 git），返回候选链接和接下来的步骤。'
                       'SDD 流程还会按仓库模板新建 sdd-start.md / sdd-status.md，链接按 SDD 栏目分组，供你按 sdd-start.md 注释填写空栏。',
     S(iteration=STR('期名'), repo=STR('目标仓库名或绝对路径；文字资料写了代码路径时可空'),
       store=STR('SDD：多人协作时的子目录名（同 /sdd-start nameB），一般留空')), ['iteration']),
    ('kb_sdd_prepare', '旧名，同 kb_dev_prepare。',
     S(iteration=STR('期名'), repo=STR('目标仓库名或绝对路径'), store=STR('一般留空')), ['iteration']),
    ('kb_base', '查看 / 搜索基础知识库（所有期共用：网站账号、测试账号、Wi-Fi / 代理 / VPN、环境配置等）。机密字段只显示掩码。',
     S(query=STR('关键词，可空（空 = 全部）'), category={'type': 'string', 'enum': BASE_CATS, 'description': '分类，可空'}), []),
    ('kb_base_save', '新增 / 修改 / 删除基础知识库条目。密码、令牌、密钥等字段务必 机密=true（只存 macOS 钥匙串）。'
                     '修改时只传要改的项；fields 传入后整体替换字段列表，机密字段值留空表示保持原值。',
     S(id=STR('编号，如 B001；新增时不传'), category={'type': 'string', 'enum': BASE_CATS, 'description': '分类'},
       name=STR('名称，如「测试账号（国内）」「办公室 Wi-Fi」'), scope=STR('适用产品 / 场景，如「签到功能测试」'),
       fields={'type': 'array', 'description': '字段列表',
               'items': {'type': 'object', 'properties': {'名': {'type': 'string'}, '值': {'type': 'string'},
                                                           '机密': {'type': 'boolean'}}, 'required': ['名']}},
       note=STR('备注（Markdown）'), file=STR('附件文件绝对路径（如 VPN 配置文件），会复制到 基础/附件/'),
       delete={'type': 'boolean', 'description': 'true 表示删除这条'}), []),
    ('kb_base_secret', '读取基础知识库里某个机密字段的明文（会记录读取）。只在真正执行时用（如测试时登录），'
                       '读到的值不要写进代码、文档、提交、日志或回复。',
     S(id=STR('编号，如 B001'), field=STR('字段名，如「密码」'), purpose=STR('用途，如「设备测试登录」')), ['id', 'field']),
    ('kb_ask', '开发中向用户提一个待确认问题（显示在知识库网页并弹系统通知）。之后用 kb_wait_answer 等回答；'
               '本期开了免打扰时直接返回，按你的建议执行。',
     S(iteration=STR('期名'), question=STR('要确认的问题，一句话说清'), context=STR('背景：为什么要问、影响什么（Markdown）'),
       options={'type': 'array', 'items': {'type': 'string'}, 'description': '可选方案（用户可点选，也可自己写）'},
       recommend=STR('你的建议方案（免打扰时按它执行）'), stage=STR('阶段，如 需求分析 / 技术规划 / TASK-3'),
       files={'type': 'array', 'items': {'type': 'string'}, 'description': '相关文件绝对路径（如 prd.md），网页上可点开'}),
     ['iteration', 'question']),
    ('kb_wait_answer', '等待用户在网页回答 kb_ask 提的问题（每次最多等几分钟，没回答就再调一次）。',
     S(iteration=STR('期名'), id=STR('问题编号，如 Q001'), timeout={'type': 'integer', 'description': '本次最多等多少秒，默认 240'}),
     ['iteration', 'id']),
    ('kb_devices', '查看连着的手机和占用情况：哪台空闲、哪台被哪一期（哪个分支）占着。手机是多个期共用的，装包测试前先看。',
     S(iteration=STR('期名')), ['iteration']),
    ('kb_device_claim', '申请手机给这一期测试（优先本期已占着的，再挑空闲的）：返回能用的序列号，只在这些手机上装包、操作'
                        '（adb -s <序列号> / agent-device --serial）。不够时自动记成非阻断问题并通知用户，你继续开发。',
     S(iteration=STR('期名'), count={'type': 'integer', 'description': '要几台，默认 1（多台场景一次申请够）'},
       serials={'type': 'array', 'items': {'type': 'string'}, 'description': '指定序列号（可空）'},
       reason=STR('用途，如「TASK-5 多人送礼：主持 + 2 个麦上用户」')), ['iteration']),
    ('kb_device_release', '释放这一期占着的手机（测完就释放，别的期才能用）。',
     S(iteration=STR('期名'), serials={'type': 'array', 'items': {'type': 'string'}, 'description': '只释放这些；空 = 全部'}),
     ['iteration']),
    ('kb_issue', '记一个不阻断开发、但要用户知道并处理的问题（显示在网页并弹通知，不用等回答）：手机不够或没连、缺测试账号、'
                 '环境不满足导致某些验证做不了等。记下后继续开发；用户条件具备后会点「复测」补测。',
     S(iteration=STR('期名'), title=STR('一句话：缺什么、影响什么，如「需要 3 台手机：多人送礼 case 只测了 2 人」'),
       detail=STR('详情：涉及哪些 case / 任务、现在的情况、证据路径（Markdown）'),
       kind={'type': 'string', 'enum': ISSUE_KINDS, 'description': '类型，不传自动判断'},
       need=STR('要用户提供什么，如「3 台手机」「第 2 个测试账号」')), ['iteration', 'title']),
    ('kb_test_report', '测试 / 复测结束时汇报结果（记进这一期、释放手机、通知用户；仍有阻塞时保留「待复测」）。',
     S(iteration=STR('期名'), summary=STR('小结：测了哪些、结果、发现的问题'),
       passed={'type': 'integer', 'description': '通过数'}, failed={'type': 'integer', 'description': '失败数'},
       blocked={'type': 'integer', 'description': '仍然阻塞（没测成）数'}, need=STR('还缺什么条件，如「第 3 台手机」')),
     ['iteration', 'summary']),
    ('kb_set_dnd', '开关某期的免打扰（用户明确要求时才用）：开启后需要确认的地方由 AI 自行决策并记录。',
     S(iteration=STR('期名'), on={'type': 'boolean', 'description': 'true 开启，false 关闭'}), ['iteration', 'on']),
    ('kb_dev_package', '获取某期的开发包（全部需求、接口文档正文，设计图路径，关联仓库）。仅当用户已批准开发时可用。',
     S(iteration=STR('期名')), ['iteration']),
    ('kb_set_status', '修改某期状态。AI 只能设为 开发中（需已批准）/ 已完成（需开发中）/ 收集中 / 已暂停；「已批准开发」只能由用户本人操作。',
     S(iteration=STR('期名'), status={'type': 'string', 'enum': [s for s in STATUSES if s != '已批准开发']},
       note=STR('备注')), ['iteration', 'status']),
    ('kb_log', '往某期的 记录.md 追加一条记录（关键决定、变更、结论）。',
     S(iteration=STR('期名'), note=STR('记录内容')), ['iteration', 'note']),
    ('kb_fetch_url', '读取网页或 Confluence 页面（不保存）：返回正文（Markdown，含表格、链接、图片地址）、附件清单、子页面。'
                     '用于先看原文、定位用户说的条目（如「编号6」）。Confluence 需用户先 kb login。',
     S(url=STR('网址'), start={'type': 'integer', 'description': '正文起始字符位置，长页面分段读'}), ['url']),
    ('kb_import_url', '把网页 / Confluence 页面或其中某个条目导入一期：保存为文档（顶部写明来源地址、页面版本、条目、简介）、'
                      '保存整页原文快照、按需下载附件，并登记到「来源」清单供用户核对。'
                      '只导某个条目时，把该条目的原文内容（及相关上下文）整理后放进 content，不要改写原意。',
     S(iteration=STR('期名'), url=STR('网址'), category=CAT, item=STR('条目，如「编号6」；整页导入可空'),
       summary=STR('简介：这份资料讲了什么、对应哪个条目、包含哪些附件，用户据此核对'),
       content=STR('只导条目时：该条目的原文内容（Markdown）；空则导入整页'),
       attachments={'type': 'array', 'items': {'type': 'string'},
                    'description': '要下载的附件名或图片/文件网址；"embedded" 表示页面内嵌图片（Axure 导出 PRD 常见）；["all"] 表示全部'},
       filename=STR('保存的文件名，默认「页面标题-条目」')), ['iteration', 'url', 'category', 'summary']),
    ('kb_refresh_sources', '按登记的网址重新抓取某期的来源（产品改了需求时用）：原文没变只记检查时间；整页导入的资料和 Figma 设计稿'
                           '自动重新导入（旧版进历史版本，差异存到 来源快照/变更/）；只导入了条目的，改动落在条目上时标记「待更新」，'
                           '你要按返回的提示重新整理条目。',
     S(iteration=STR('期名'), sid=STR('来源编号如 S001；空则检查全部')), ['iteration']),
    ('kb_fix_link', '更正某期里给错的链接（设计稿、需求文档地址等）：文档、文字资料、来源、SDD 的 sdd-start.md 一起换成新链接，'
                    '旧内容进历史版本，按新链接重新导入，并提醒开发会话重新下载物料 / 修订。用户说「设计稿链接错了，应该是 XX」时用。',
     S(iteration=STR('期名'), old=STR('错误的旧链接（Figma 只要文件和 node-id 对得上即可）'), new=STR('正确的新链接'),
       reason=STR('原因，如「设计稿给错了版本」')), ['iteration', 'old', 'new']),
    ('kb_import_design', '导入设计稿（要实现的产品图，Figma / 蓝湖链接，通常是需求表里的「设计稿地址」）：'
                         'Figma 逐个画板导出 PNG 并生成设计规格（文案、字体字号、颜色、尺寸），存进「设计图」；蓝湖暂只登记链接。',
     S(iteration=STR('期名'), url=STR('Figma / 蓝湖 链接（保留 node-id 参数）'), item=STR('条目，如「编号6」'),
       summary=STR('简介：这是哪个需求的设计稿、包含哪些页面')), ['iteration', 'url']),
]


_NOTICED = ('kb_dev_package', 'kb_wait_answer', 'kb_log')   # 这几个自己带上了提醒


def call_tool(name, a):
    """调用工具；带期名的，结果后面附上这一期的提醒（需求来源更新、用户在网页发来的消息）。"""
    res = _call_tool(name, a)
    if a.get('iteration') and name not in _NOTICED and isinstance(res, str):
        res += take_notices(a['iteration'])
    return res


def _call_tool(name, a):
    g = a.get
    if name == 'kb_overview':
        return overview()
    if name == 'kb_iteration':
        return period_detail(g('name'))
    if name == 'kb_create_iteration':
        return create_period(g('name'), g('summary') or '')
    if name == 'kb_add_material':
        return add_material(g('iteration'), g('path'), g('category'), g('note') or '')
    if name == 'kb_write_doc':
        return write_doc(g('iteration'), g('category'), g('filename'), g('content') or '', g('note') or '')
    if name == 'kb_add_note':
        return (add_note(g('iteration'), g('content'), g('category'), g('kind'), g('title'), g('url'), g('source'))
                + _conflict_hint(g('iteration'), f'{g("url") or ""} {g("content") or ""}'))
    if name == 'kb_update_note':
        return update_note(g('iteration'), g('id'), bool(g('delete')), 内容=g('content'), 分类=g('category'),
                           类型=g('kind'), 标题=g('title'), 链接=g('url'), 来自=g('source'))
    if name == 'kb_search':
        return search(g('query'), g('iteration'), g('category'), g('scope') or 'all', g('repo'), g('limit') or 10)
    if name == 'kb_read':
        return read_file(g('path'), g('start') or 1, g('max_lines') or 300)
    if name == 'kb_annotate_image':
        return annotate_image(g('path'), g('description') or '')
    if name == 'kb_add_repo':
        return add_repo(g('path'), g('name'))
    if name == 'kb_link_repo':
        return link_repo(g('iteration'), g('repo'))
    if name == 'kb_reindex':
        return reindex(g('target') or 'all')
    if name == 'kb_dev_package':
        return dev_package(g('iteration')) + take_notices(g('iteration'))
    if name in ('kb_dev_prepare', 'kb_sdd_prepare'):
        return dev_prepare(g('iteration'), g('repo') or '', g('store') or '')
    if name == 'kb_base':
        return base_list(g('query') or '', g('category') or '')
    if name == 'kb_base_save':
        return base_save(g('id') or '', g('category') or '', g('name'), g('fields'), g('scope'), g('note'),
                         g('file') or '', bool(g('delete')))
    if name == 'kb_base_secret':
        return base_secret(g('id'), g('field'), purpose=g('purpose') or '')
    if name == 'kb_ask':
        return ask(g('iteration'), g('question'), g('context') or '', g('options'), g('recommend') or '',
                   g('files'), g('stage') or '')
    if name == 'kb_wait_answer':
        return wait_answer(g('iteration'), g('id'), g('timeout') or 240) + take_notices(g('iteration'))
    if name == 'kb_devices':
        return devices_text(g('iteration'))
    if name == 'kb_device_claim':
        return device_claim(g('iteration'), g('count') or 1, g('serials'), g('reason') or '')
    if name == 'kb_device_release':
        return device_release(g('iteration'), g('serials'))
    if name == 'kb_issue':
        return add_issue(g('iteration'), g('title'), g('detail') or '', g('kind') or '', g('need') or '')
    if name == 'kb_test_report':
        return test_report(g('iteration'), g('summary'), g('passed'), g('failed'), g('blocked'), g('need') or '')
    if name == 'kb_set_dnd':
        return set_dnd(g('iteration'), bool(g('on')), by='Claude（用户要求）')
    if name == 'kb_set_status':
        return set_status(g('iteration'), g('status'), g('note') or '', by_human=False)
    if name == 'kb_log':
        return add_log(g('iteration'), g('note') or '') + take_notices(g('iteration'))
    if name == 'kb_fetch_url':
        return fetch_url(g('url'), g('start') or 0)
    if name == 'kb_fix_link':
        return fix_link(g('iteration'), g('old'), g('new'), g('reason') or '')
    if name == 'kb_refresh_sources':
        return refresh_sources(g('iteration'), g('sid') or '')
    if name == 'kb_import_design':
        return import_design(g('iteration'), g('url'), g('item') or '', g('summary') or '')
    if name == 'kb_import_url':
        return import_url(g('iteration'), g('url'), g('category'), g('item') or '', g('summary') or '',
                          g('content') or '', g('attachments'), g('filename') or '')
    raise KBError(f'未知工具：{name}')


def serve():
    init()
    tools = [{'name': n, 'description': d, 'inputSchema': {**s, 'required': r}} for n, d, s, r in TOOLS]

    def send(obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + '\n')
        sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        mid, method = msg.get('id'), msg.get('method')
        if mid is None:
            continue
        params = msg.get('params') or {}
        if method == 'initialize':
            res = {'protocolVersion': params.get('protocolVersion', '2025-06-18'),
                   'capabilities': {'tools': {}}, 'serverInfo': {'name': 'kb', 'version': '1.0.0'},
                   'instructions': INSTRUCTIONS}
        elif method == 'tools/list':
            res = {'tools': tools}
        elif method == 'tools/call':
            try:
                text, err = call_tool(params.get('name'), params.get('arguments') or {}), False
            except KBError as e:
                text, err = str(e), True
            except Exception as e:
                text, err = f'内部错误：{e!r}', True
            res = {'content': [{'type': 'text', 'text': text}], 'isError': err}
        elif method == 'ping':
            res = {}
        else:
            send({'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': f'未实现：{method}'}})
            continue
        send({'jsonrpc': '2.0', 'id': mid, 'result': res})


# ---------------------------------------------------------------- 命令行

def approve(name):
    d = period_dir(name)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise KBError('批准开发必须由你本人在终端窗口里运行（防止 AI 代为批准）。')
    print(period_detail(d.name, log_lines=5))
    ans = input(f'\n确认批准「{d.name}」开始开发？请输入期名确认：').strip()
    if ans != d.name:
        raise KBError('输入不一致，已取消。')
    note = input('备注（可空）：').strip()
    return set_status(d.name, '已批准开发', note or '用户批准', by_human=True)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='kb', description='本地知识库（需求 / 设计图 / 接口文档 / 其他资料 / 代码）')
    sp = ap.add_subparsers(dest='cmd')
    sp.add_parser('init', help='初始化目录')
    sp.add_parser('list', help='总览')
    x = sp.add_parser('new', help='新建一期')
    x.add_argument('name')
    x.add_argument('summary', nargs='?', default='')
    x = sp.add_parser('show', help='查看一期')
    x.add_argument('name')
    x = sp.add_parser('add', help='归档文件到某期')
    x.add_argument('name')
    x.add_argument('files', nargs='+')
    x.add_argument('-c', '--category', choices=CATS)
    x.add_argument('-m', '--note', default='')
    x = sp.add_parser('note', help='记一条文字资料：kb note <期名> "内容" [-c 分类] [-k 类型] [-u 链接]；--rm T001 删除')
    x.add_argument('name')
    x.add_argument('content', nargs='?', default='')
    x.add_argument('-c', '--category', choices=CATS)
    x.add_argument('-k', '--kind', choices=NOTE_KINDS)
    x.add_argument('-t', '--title', default='')
    x.add_argument('-u', '--url', default='')
    x.add_argument('-f', '--source', default='', help='来自谁')
    x.add_argument('--rm', metavar='编号', help='删除这条文字资料')
    x = sp.add_parser('inbox', help='把收件箱里的文件全部归档到某期（自动分类）')
    x.add_argument('name')
    x = sp.add_parser('search', help='检索')
    x.add_argument('query', nargs='+')
    x.add_argument('-p', '--period')
    x.add_argument('-s', '--scope', choices=['all', 'docs', 'code'], default='all')
    x.add_argument('-n', '--limit', type=int, default=10)
    x = sp.add_parser('repo', help='登记代码仓库：kb repo <路径> [名称]')
    x.add_argument('path')
    x.add_argument('repo_name', nargs='?')
    x = sp.add_parser('link', help='关联仓库到某期')
    x.add_argument('name')
    x.add_argument('repo')
    x = sp.add_parser('index', help='更新索引：all / docs / code / 仓库名')
    x.add_argument('target', nargs='?', default='all')
    x = sp.add_parser('approve', help='批准某期开始开发（只能本人在终端执行）')
    x.add_argument('name')
    x = sp.add_parser('status', help='修改状态')
    x.add_argument('name')
    x.add_argument('status', choices=STATUSES)
    x.add_argument('-m', '--note', default='')
    x = sp.add_parser('log', help='追加记录')
    x.add_argument('name')
    x.add_argument('note')
    x = sp.add_parser('login', help='保存某网站的登录凭据到钥匙串：kb login confluence.example.com 用户名')
    x.add_argument('host')
    x.add_argument('user')
    x = sp.add_parser('fetch', help='预览网页 / Confluence 页面')
    x.add_argument('url')
    x = sp.add_parser('verify', help='核对来源：kb verify <期名> S001 已核对|有问题|待核对 [-m 备注]')
    x.add_argument('name')
    x.add_argument('sid')
    x.add_argument('status', choices=['已核对', '有问题', '待核对'])
    x.add_argument('-m', '--note', default='')
    x = sp.add_parser('fixlink', help='更正链接：kb fixlink <期名> <旧链接> <新链接> [-m 原因]')
    x.add_argument('name')
    x.add_argument('old')
    x.add_argument('new')
    x.add_argument('-m', '--reason', default='')
    x = sp.add_parser('refresh', help='按登记的网址刷新来源：kb refresh <期名> [S001]；kb refresh --all 检查所有未完成的期')
    x.add_argument('name', nargs='?', default='')
    x.add_argument('sid', nargs='?', default='')
    x.add_argument('--all', action='store_true')
    x = sp.add_parser('plugin', help='插件：kb plugin（列出）；kb plugin run <插件> <期名> [开发开始|开发完成]（手动运行一次）')
    x.add_argument('action', nargs='?', default='list', choices=['list', 'run'])
    x.add_argument('plugin', nargs='?', default='')
    x.add_argument('name', nargs='?', default='')
    x.add_argument('event', nargs='?', default='开发开始')
    sp.add_parser('serve', help='以 MCP（stdio）方式运行')
    x = sp.add_parser('web', help='启动本地网页（默认 http://127.0.0.1:11555）')
    x.add_argument('--port', type=int, default=11555)
    a = ap.parse_args(argv)
    if a.cmd == 'serve':
        return serve()
    if a.cmd == 'web':
        import web
        return web.main(a.port)
    try:
        if a.cmd == 'init':
            init()
            r = f'已初始化：{ROOT}'
        elif a.cmd in (None, 'list'):
            r = overview()
        elif a.cmd == 'new':
            r = create_period(a.name, a.summary)
        elif a.cmd == 'show':
            r = period_detail(a.name)
        elif a.cmd == 'add':
            r = '\n\n'.join(add_material(a.name, f, a.category, a.note) for f in a.files)
        elif a.cmd == 'note':
            r = (update_note(a.name, a.rm, delete=True) if a.rm else
                 add_note(a.name, a.content, a.category, a.kind, a.title, a.url, a.source))
        elif a.cmd == 'inbox':
            fs = [p for p in INBOX.iterdir() if not p.name.startswith('.')]
            r = '\n\n'.join(add_material(a.name, f) for f in fs) if fs else '收件箱是空的'
        elif a.cmd == 'search':
            r = search(' '.join(a.query), a.period, None, a.scope, None, a.limit)
        elif a.cmd == 'repo':
            r = add_repo(a.path, a.repo_name)
        elif a.cmd == 'link':
            r = link_repo(a.name, a.repo)
        elif a.cmd == 'index':
            r = reindex(a.target)
        elif a.cmd == 'approve':
            r = approve(a.name)
        elif a.cmd == 'login':
            host = re.sub(r'^https?://', '', a.host).split('/')[0]
            what = 'Figma 个人访问令牌' if 'figma' in host else f'{a.user}@{host} 的密码'
            print(f'请输入{what}（由 macOS 钥匙串接收，知识库和 AI 看不到明文）')
            _fetch().save_cred(host, a.user)
            r = f'已保存到钥匙串（服务名 kb:{host}）'
        elif a.cmd == 'fetch':
            r = fetch_url(a.url)
        elif a.cmd == 'verify':
            r = verify_source(a.name, a.sid, a.status, a.note)
        elif a.cmd == 'fixlink':
            r = fix_link(a.name, a.old, a.new, a.reason, by='终端')
        elif a.cmd == 'refresh':
            if a.all or not a.name:
                ch = refresh_all(by='终端')
                r = '\n'.join(f'{n}：\n' + '\n'.join(h) for n, h in ch) or '所有未完成的期，来源都没有变化'
            else:
                r = refresh_sources(a.name, a.sid, by='终端')
        elif a.cmd == 'status':
            if a.status == '已批准开发':
                raise KBError('批准开发请用：kb approve <期名>')
            r = set_status(a.name, a.status, a.note, by_human=True)
        elif a.cmd == 'log':
            r = add_log(a.name, a.note)
        elif a.cmd == 'plugin':
            if a.action == 'run':
                if not a.plugin or not a.name:
                    raise KBError('用法：kb plugin run <插件> <期名> [开发开始|开发完成]')
                r = run_plugin_now(a.plugin, a.name, a.event)
            else:
                r = '\n'.join(f'{p["id"]}：{p.get("名称", "")} · ' + (p.get('错误') or (f'已挂载（{"、".join(p["时机"])}）' if p['启用'] else '未挂载'))
                              + f' · {p["目录"]}' for p in plugins()) or f'没有插件（放到 {PLUGIN_DIR}/<名称>/plugin.json）'
        print(r)
    except KBError as e:
        print(f'✗ {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main() or 0)
