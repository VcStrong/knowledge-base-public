"""仓库在哪台机器：本机路径，或远程（ssh）。全栈的各端工程可能分在不同机器上，每台都装了 claude 等 AI 工具。

仓库地址就是一个字符串：
  /Users/me/app                       本机
  user@host:/home/me/server           远程（scp 写法）
  ssh://user@host:2222/home/me/server 远程，带端口
远程只用 ssh 密钥登录（BatchMode，不会弹密码）；没配好时报错提示 ssh-copy-id。知识库不存远程机器的密码。

版本库：git 或 svn（工作副本）。svn 的提交直接进服务器、没有「本地提交」这一步，所以全栈里 AI 只改工作副本、不提交，
审查看工作副本的改动（svn diff），你验收后由知识库 svn commit（svn_commit）。svn 用 --non-interactive，
账号密码要先在那台机器上 svn update 一次让 svn 自己记住，知识库不存。
"""
import re
import shlex
import subprocess
from pathlib import Path

from .common import KBError

_SSH_URL = re.compile(r'^ssh://(?P<host>[^/:]+(?:@[^/:]+)?)(?::(?P<port>\d+))?(?P<path>/.*)$')
_SCP = re.compile(r'^(?P<host>[\w.-]+@[\w.-]+|[\w.-]+):(?P<path>[/~].*)$')
SSH_OPTS = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=30']


def parse(loc):
    """→ {'远程': bool, '主机': 'user@host', '端口': '', '路径': '/…', '地址': 原样}。"""
    loc = (loc or '').strip()
    if '://' in loc and not loc.startswith('ssh://'):          # http(s):// 等网址不是仓库地址
        return {'远程': False, '主机': '', '端口': '', '路径': '', '地址': loc, '网址': True}
    m = _SSH_URL.match(loc) or (_SCP.match(loc) if not loc.startswith(('/', '~')) else None)
    if m:
        return {'远程': True, '主机': m['host'], '端口': (m.groupdict().get('port') or ''), '路径': m['path'], '地址': loc}
    return {'远程': False, '主机': '', '端口': '', '路径': str(Path(loc).expanduser()) if loc else '', '地址': loc}


def is_remote(loc):
    return parse(loc)['远程']


def is_location(loc):
    """像不像仓库地址（本机路径或远程），网址不算。"""
    r = parse(loc)
    return r['远程'] or (not r.get('网址') and (loc or '').strip().startswith(('/', '~')))


def label(loc):
    r = parse(loc)
    return f'{r["主机"]}:{r["路径"]}' if r['远程'] else r['路径']


def ssh_cmd(loc, script, tty=False):
    """在仓库所在机器上跑一段 sh 脚本（本机直接 sh）。"""
    r = parse(loc)
    if not r['远程']:
        return ['sh', '-c', script]
    return ['ssh', *SSH_OPTS, *(['-p', r['端口']] if r['端口'] else []), *(['-t'] if tty else []), r['主机'], script]


def run(loc, script, timeout=30):
    """在仓库目录里跑 sh 脚本，返回 CompletedProcess；ssh 连不上转成清楚的报错。"""
    r = parse(loc)
    full = f'cd {shlex.quote(r["路径"])} 2>/dev/null || {{ echo "__KB_NODIR__" >&2; exit 97; }}; {script}'
    try:
        p = subprocess.run(ssh_cmd(loc, full), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise KBError(f'{label(loc)}：执行超时（{timeout} 秒）')
    if p.returncode == 97 and '__KB_NODIR__' in p.stderr:
        raise KBError(f'路径错误：{label(loc)} 不存在')
    if r['远程'] and p.returncode == 255:
        raise KBError(f'连不上 {r["主机"]}：{p.stderr.strip()[-300:]}\n先配好免密登录：ssh-copy-id {r["主机"]}，再在终端 ssh {r["主机"]} 试一次')
    return p


def git(loc, *args, timeout=60):
    return run(loc, 'git ' + ' '.join(shlex.quote(a) for a in args), timeout=timeout)


SVN = 'svn --non-interactive'


def svn(loc, *args, timeout=120):
    return run(loc, SVN + ' ' + ' '.join(shlex.quote(a) for a in args), timeout=timeout)


def _top(loc):
    """→ (版本库, 仓库根)；都不是 → ('', '')。"""
    p = run(loc, 't=$(git rev-parse --show-toplevel 2>/dev/null) && echo "git $t"; '
                 f't=$({SVN} info --show-item wc-root 2>/dev/null) && echo "svn $t"; true')
    found = [ln.split(' ', 1) for ln in p.stdout.splitlines() if ln.startswith(('git ', 'svn '))]
    if not found:
        return '', ''
    kind, top = max(found, key=lambda x: len(x[1].strip()))      # 套在一起时取更里面的那个
    return kind, top.strip()


def vcs(loc):
    """git / svn / ''。"""
    return _top(loc)[0]


def check_repo(loc):
    """路径存在、是 git 仓库或 svn 工作副本；返回仓库根（同一台机器上的地址）。"""
    kind, top = _top(loc)
    if not kind:
        raise KBError(f'{label(loc)} 不是 git 仓库，也不是 svn 工作副本（svn 要先 svn checkout 到这台机器上）')
    r = parse(loc)
    if not r['远程']:
        return top
    return (f'ssh://{r["主机"]}:{r["端口"]}{top}' if r['端口'] else f'{r["主机"]}:{top}')


def head(loc, kind=''):
    """当前版本：git 提交号 / svn 工作副本版本号。"""
    kind = kind or vcs(loc)
    if kind == 'svn':
        return svn(loc, 'info', '--show-item', 'revision').stdout.strip()
    return git(loc, 'rev-parse', 'HEAD').stdout.strip()


def branch_of(loc, kind=''):
    """当前分支：git 分支名；svn 是工作副本对应的目录（trunk、branches/xxx）。"""
    kind = kind or vcs(loc)
    if kind == 'svn':
        rel = svn(loc, 'info', '--show-item', 'relative-url').stdout.strip()
        return rel[2:] if rel.startswith('^/') else rel
    return git(loc, 'branch', '--show-current').stdout.strip()


def svn_branch(loc, name):
    """分支名 → svn 仓库里的目录（trunk、branches/xxx）：原样、branches/<名> 依次试，服务器上有的那个。"""
    name = (name or '').strip().strip('/')
    name = name[2:] if name.startswith('^/') else name
    for c in [name] + ([f'branches/{name}'] if not name.startswith(('trunk', 'branches/', 'tags/')) else []):
        if svn(loc, 'info', '--show-item', 'kind', f'^/{c}').stdout.strip() == 'dir':
            return c
    raise KBError(f'svn 服务器上没有 {name}（也没有 branches/{name}）')


def svn_changes(loc):
    """svn 工作副本里没提交的改动 → (已纳入版本控制的改动 [(状态, 路径)], 没 svn add 的新文件 [路径])。"""
    p = svn(loc, 'status')
    if p.returncode:
        raise KBError(f'{label(loc)}：svn status 失败：{(p.stderr or p.stdout).strip()[-300:]}')
    ch, new = [], []
    for ln in p.stdout.splitlines():
        if len(ln) < 9 or ln.startswith(('Performing', '--- ')):
            continue
        st, path = ln[0], ln[8:].strip()
        if st == '?':
            new.append(path)
        elif st in 'AMDRC!~' and st != ' ':
            ch.append((st, path))
        elif ln[1] == 'M':                      # 只改了属性
            ch.append(('M', path))
    return ch, new


def svn_commit(loc, paths, msg):
    """只提交给定的路径（不混进工作副本里别人原有的改动）→ 新版本号。"""
    if not paths:
        return ''
    paths = sorted(set(paths))
    paths = [x for x in paths if not any(x.startswith(y + '/') for y in paths)]     # 目录已在列表里，下面的不用重复
    p = svn(loc, 'commit', '-m', msg, *paths, timeout=600)
    if p.returncode:
        err = (p.stderr or p.stdout).strip()[-600:]
        hint = '（先在那台机器上手动 svn update 一次，让 svn 记住账号密码）' if 'uthenticat' in err or 'password' in err.lower() else \
               '（服务器上有更新的版本：先 svn update 解决冲突再验收）' if 'out of date' in err.lower() or '过时' in err else ''
        raise KBError(f'svn commit 失败{hint}：{err}')
    import re
    m = re.findall(r'(?:Committed revision|提交后的版本为)\s*(\d+)', p.stdout)
    return m[-1] if m else head(loc, 'svn')


def probe(loc, patterns, cat=()):
    """一次调用看一组通配路径哪些存在，顺便取几个小文件的内容（认端用）。→ (存在的模式集合, {文件: 内容})。"""
    pats = ' '.join(shlex.quote(x) for x in patterns)
    cats = ' '.join(shlex.quote(x) for x in cat)
    script = (f'for g in {pats}; do set -- $g; [ -e "$1" ] && echo "P:$g"; done; '
              f'for f in {cats}; do [ -f "$f" ] && {{ echo "C:$f"; head -c 20000 "$f"; echo; echo "C:END"; }}; done; true')
    p = run(loc, script)
    have, files, cur, buf = set(), {}, None, []
    for ln in p.stdout.splitlines():
        if cur is None and ln.startswith('P:'):
            have.add(ln[2:])
        elif cur is None and ln.startswith('C:'):
            cur, buf = ln[2:], []
        elif cur is not None and ln == 'C:END':
            files[cur], cur = '\n'.join(buf), None
        elif cur is not None:
            buf.append(ln)
    return have, files


# ---------------------------------------------------------------- 给方案会话读远程代码（只读，固定几种操作）
READ_OPS = {
    'ls': lambda a: f'ls -la {shlex.quote(a or ".")}',
    'tree': lambda a: f'find {shlex.quote(a or ".")} -maxdepth 3 -not -path "*/.git*" -not -path "*/.svn*" -not -path "*/node_modules*" -not -path "*/build/*" | head -400',
    'cat': lambda a: f'head -c 120000 {shlex.quote(a)}',
    'grep': lambda a: (f'(command -v rg >/dev/null && rg -n --max-count 20 --max-columns 300 -e {shlex.quote(a)} . || '
                       f'grep -rn --exclude-dir=.git --exclude-dir=.svn --exclude-dir=node_modules --exclude-dir=build -e {shlex.quote(a)} . ) | head -300'),
    'find': lambda a: f'find . -not -path "*/.git/*" -not -path "*/.svn/*" -not -path "*/node_modules/*" -name {shlex.quote(a)} | head -200',
    'git-log': lambda a: (f'if [ -d .svn ] || ! git rev-parse 2>/dev/null; then {SVN} log -l 40 {shlex.quote(a or ".")}; '
                          f'else git log --oneline -n 40 {("-- " + shlex.quote(a)) if a else ""}; fi'),
    'git-show': lambda a: (f'if [ -d .svn ] || ! git rev-parse 2>/dev/null; then {SVN} log -v -r {shlex.quote(a or "BASE")} | head -200; '
                           f'else git show --stat {shlex.quote(a or "HEAD")} | head -200; fi'),
}


def repo_read(loc, op, arg=''):
    """只读查看仓库（本机或远程）：ls / tree / cat / grep / find / git-log / git-show（svn 工作副本自动换成 svn log）。"""
    if op not in READ_OPS:
        raise KBError(f'op 只能是：{"、".join(READ_OPS)}')
    if op in ('cat',) and not arg:
        raise KBError('cat 要给文件路径（相对仓库根目录）')
    if arg and ('..' in Path(arg).parts) and op in ('ls', 'tree', 'cat'):
        raise KBError('只能看仓库里面的文件')
    p = run(loc, READ_OPS[op](arg or ''), timeout=60)
    out = (p.stdout or '') + (('\n' + p.stderr.strip()) if p.returncode and p.stderr.strip() else '')
    return out.strip() or '（没有输出）'
