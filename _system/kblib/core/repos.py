# From 大大王.DT
"""登记的本地代码仓库。"""
import json
import os
import subprocess
from pathlib import Path
from kblib.core.common import CODE_EXT, KBError, REPOS_FILE, SKIP_DIRS, load_settings, now, safe_name, save_settings
from kblib.core.periods import init, load_meta, log, period_dir, save_meta
from kblib import lazy
_search = lazy('kblib.core.search')      # 上层模块：用到时才 import（不形成循环）


def load_repos():
    return json.loads(REPOS_FILE.read_text('utf-8')) if REPOS_FILE.exists() else {}


# 各端：工程（代码仓库）属于哪一端。这里是「常用平台」（全栈添加端时的候选、排序、设置里的下拉）；
# 一期也可以加自定义端（Unity、嵌入式、脚本…），见 stack/plan.py end_name
REPO_ENDS = ('服务端', 'Web', 'iOS', 'Android', '鸿蒙', '小程序', '桌面端')


def _repo_key(path):
    p = str(path or '').strip()
    return p if ':' in p.split('/')[0] else str(Path(p).expanduser())       # 远程 user@主机:/路径 原样


def repo_prefs():
    """每个工程手动指定的「端」和「默认流程」：设置.json「工程」{路径: {端, 默认流程}}。路径不必在代码仓库.json 里登记。"""
    return load_settings().get('工程') or {}


def repo_pref(path):
    return repo_prefs().get(_repo_key(path)) or {} if path else {}


def save_repo_pref(path, **kv):
    """改某个工程的偏好；值为空 = 去掉这一项（端回到按文件识别，流程跟随全局默认）。校验由调用方做。"""
    if not (path or '').strip():
        raise KBError('没有工程路径')
    s = load_settings()
    allp = s.setdefault('工程', {})
    x = allp.setdefault(_repo_key(path), {})
    for k, v in kv.items():
        if v:
            x[k] = v
        else:
            x.pop(k, None)
    if not x:
        allp.pop(_repo_key(path), None)
    save_settings(s)
    return x


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
