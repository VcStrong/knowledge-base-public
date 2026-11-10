# From 大大王.DT
"""手机占用记录：kb.py 和 bin/adb（知识库 adb 守卫）共用，不依赖 kb.py，启动要快。

多个期（不同分支）的后台会话可能同时在测试，同一台手机被两边装包会互相覆盖、打断测试。
记录放在 知识库/设备占用.json：序列号 → {期, 分支, 仓库, 方式, 开始, 最后使用}。
方式：申请（kb_device_claim）、自动（会话第一次往空闲手机装包 / 操作时记下）、本人（网页上标「我在用」）。
"""
import fcntl
import json
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

SYS = Path(__file__).resolve().parents[2]      # kblib/infra/devlock.py → _system
ROOT = Path(os.environ.get('KB_ROOT') or SYS.parent)
FILE = ROOT / '设备占用.json'
LOCK = ROOT / '.设备占用.lock'
BIN = SYS / 'bin'
IDLE = {'自动': 30 * 60, '申请': 12 * 3600, '本人': 4 * 3600}   # 多久没用自动释放
LOOSE = 2 * 3600       # 不是知识库后台会话（终端里手动开发）申请的，没人释放时最多保留这么久


def stamp(t=None):
    return time.strftime('%Y-%m-%d %H:%M', time.localtime(t or time.time()))


def load():
    try:
        return json.loads(FILE.read_text('utf-8'))
    except (OSError, ValueError):
        return {}


def _save(data):
    tmp = FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), 'utf-8')
    tmp.replace(FILE)


@contextmanager
def locked():
    """加锁读改写：with locked() as data: 修改 data，退出时保存。"""
    with open(LOCK, 'a') as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        data = load()
        yield data
        _save(data)


def session_alive(period):
    """这一期的知识库后台会话是否在运行。"""
    try:
        s = json.loads((ROOT / '期' / period / '期信息.json').read_text('utf-8')).get('开发会话') or {}
        pid = int(s.get('pid') or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return False
    if s.get('状态') != '运行中' or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def valid(c, now=None):
    """占用是否还有效：没超过闲置时间，且占用它的会话还在（本人标的、终端里申请的除外）。"""
    idle = (now or time.time()) - float(c.get('最后使用') or 0)
    if idle > IDLE.get(c.get('方式'), IDLE['自动']):
        return False
    if c.get('方式') == '本人':
        return True
    return session_alive(c.get('期', '')) or (c.get('方式') == '申请' and idle < LOOSE)


def holders():
    """当前有效的占用：序列号 → 记录。"""
    now = time.time()
    return {k: v for k, v in load().items() if valid(v, now)}


def real_adb():
    """真正的 adb（跳过守卫自己所在的目录）。"""
    for p in os.environ.get('PATH', '').split(os.pathsep):
        if not p or Path(p).resolve() == BIN:
            continue
        f = Path(p) / 'adb'
        if f.is_file() and os.access(f, os.X_OK):
            return str(f)
    for h in (os.environ.get('ANDROID_HOME'), os.environ.get('ANDROID_SDK_ROOT'), Path.home() / 'Library/Android/sdk'):
        if h and (Path(h) / 'platform-tools/adb').is_file():
            return str(Path(h) / 'platform-tools/adb')
    return ''


def online(adb):
    """[(序列号, 状态, 型号)]"""
    try:
        r = subprocess.run([adb, 'devices', '-l'], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return []
    out = []
    for line in r.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            model = next((x[6:] for x in parts[2:] if x.startswith('model:')), '')
            out.append((parts[0], parts[1], model.replace('_', ' ')))
    return out
