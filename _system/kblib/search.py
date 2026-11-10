# From 大大王.DT
"""全文索引（SQLite FTS）和检索 / 阅读。"""
import re
import sqlite3
from pathlib import Path
from .common import (
    BASE,
    CATS,
    CHUNK_CHARS,
    DB,
    DOC_EXT,
    HIST,
    IMG_EXT,
    KBError,
    MAX_CODE_BYTES,
    NOTE_SUFFIX,
    PERIODS,
    ROOT,
    SYS,
    read_text,
)
from .textx import extract
from .periods import load_meta, period_dir, period_names
from .repos import code_wanted, load_repos, repo_files
from . import lazy
_baseinfo = lazy('kblib.baseinfo')      # 上层模块：用到时才 import（不形成循环）


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
        if p.is_file() and p.suffix.lower() in DOC_EXT and p != _baseinfo.BASE_FILE and not p.name.startswith('.') and HIST not in p.parts:
            wanted[str(p)] = (p, p.stat(), '', '基础')
    zmd = ROOT / 'Bug' / 'Bug索引.md'
    if zmd.exists():
        wanted[str(zmd)] = (zmd, zmd.stat(), '', 'Bug')
    amd = ROOT / 'ANR崩溃' / 'ANR崩溃索引.md'
    if amd.exists():
        wanted[str(amd)] = (amd, amd.stat(), '', 'ANR')
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
