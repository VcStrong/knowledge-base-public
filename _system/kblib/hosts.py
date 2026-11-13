"""仓库在哪台机器：本机路径，或远程（ssh）。全栈的各端工程可能分在不同机器上，每台都装了 claude 等 AI 工具。

仓库地址就是一个字符串：
  /Users/me/app                       本机
  user@host:/home/me/server           远程（scp 写法）
  ssh://user@host:2222/home/me/server 远程，带端口
远程只用 ssh 密钥登录（BatchMode，不会弹密码）；没配好时报错提示 ssh-copy-id。知识库不存远程机器的密码。
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


def check_repo(loc):
    """路径存在、是 git 仓库；返回仓库根（同一台机器上的地址）。"""
    p = git(loc, 'rev-parse', '--show-toplevel')
    if p.returncode != 0:
        raise KBError(f'{label(loc)} 不是 git 仓库')
    r = parse(loc)
    top = p.stdout.strip()
    if not r['远程']:
        return top
    return (f'ssh://{r["主机"]}:{r["端口"]}{top}' if r['端口'] else f'{r["主机"]}:{top}')


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
    'tree': lambda a: f'find {shlex.quote(a or ".")} -maxdepth 3 -not -path "*/.git*" -not -path "*/node_modules*" -not -path "*/build/*" | head -400',
    'cat': lambda a: f'head -c 120000 {shlex.quote(a)}',
    'grep': lambda a: (f'(command -v rg >/dev/null && rg -n --max-count 20 --max-columns 300 -e {shlex.quote(a)} . || '
                       f'grep -rn --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=build -e {shlex.quote(a)} . ) | head -300'),
    'find': lambda a: f'find . -not -path "*/.git/*" -not -path "*/node_modules/*" -name {shlex.quote(a)} | head -200',
    'git-log': lambda a: f'git log --oneline -n 40 {("-- " + shlex.quote(a)) if a else ""}',
    'git-show': lambda a: f'git show --stat {shlex.quote(a or "HEAD")} | head -200',
}


def repo_read(loc, op, arg=''):
    """只读查看仓库（本机或远程）：ls / tree / cat / grep / find / git-log / git-show。"""
    if op not in READ_OPS:
        raise KBError(f'op 只能是：{"、".join(READ_OPS)}')
    if op in ('cat',) and not arg:
        raise KBError('cat 要给文件路径（相对仓库根目录）')
    if arg and ('..' in Path(arg).parts) and op in ('ls', 'tree', 'cat'):
        raise KBError('只能看仓库里面的文件')
    p = run(loc, READ_OPS[op](arg or ''), timeout=60)
    out = (p.stdout or '') + (('\n' + p.stderr.strip()) if p.returncode and p.stderr.strip() else '')
    return out.strip() or '（没有输出）'
