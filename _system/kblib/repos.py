# From 大大王.DT
"""登记的本地代码仓库。"""
import json
import os
import subprocess
from pathlib import Path
from .common import CODE_EXT, KBError, REPOS_FILE, SKIP_DIRS, now, safe_name
from .periods import init, load_meta, log, period_dir, save_meta
from . import lazy
_search = lazy('kblib.search')      # 上层模块：用到时才 import（不形成循环）


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
    return f'已登记代码仓库：{name} → {p}\n' + _search.index_repo(name)


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
