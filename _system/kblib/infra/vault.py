"""机密存放（基础信息里的密码、kb login 的网站凭据）：本机 Mac 用钥匙串，远端服务器用加密文件。

后端（环境变量 KB_SECRET_BACKEND 可强制指定）：
  keychain：macOS 钥匙串（security 命令），Mac 上默认；
  file：知识库目录下 .机密/store.enc，用 openssl（AES-256-CBC + PBKDF2）加密；Linux 等默认。
        主密钥取环境变量 KB_MASTER_KEY，没有就读 KB_MASTER_KEY_FILE（默认 ~/.config/kb/master.key，第一次自动生成、权限 600）。
        主密钥和 store.enc 不要放在一起备份；丢了主密钥，存的机密就打不开了。
不依赖 kblib 其他模块（和 devlock 一样放在 infra），启动快。
"""
import fcntl
import getpass
import json
import os
import secrets as _rand
import shutil
import subprocess
import sys
from pathlib import Path

SYS = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get('KB_ROOT') or SYS.parent)
BACKEND = os.environ.get('KB_SECRET_BACKEND') or ('keychain' if sys.platform == 'darwin' and shutil.which('security') else 'file')
LABEL = '钥匙串' if BACKEND == 'keychain' else '加密文件'
STORE = ROOT / '.机密' / 'store.enc'
KEYFILE = Path(os.environ.get('KB_MASTER_KEY_FILE') or Path.home() / '.config' / 'kb' / 'master.key').expanduser()
_ITER = '200000'


class VaultError(Exception):
    pass


# ---------------------------------------------------------------- 钥匙串
def _sec(*args):
    return subprocess.run(['security', *args], capture_output=True, text=True, timeout=15)


# ---------------------------------------------------------------- 加密文件
def _master():
    k = os.environ.get('KB_MASTER_KEY', '').strip()
    if k:
        return k
    if not KEYFILE.exists():
        KEYFILE.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(KEYFILE), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as fh:
            fh.write(_rand.token_hex(32) + '\n')
    return KEYFILE.read_text().strip()


def _openssl(args, data):
    if not shutil.which('openssl'):
        raise VaultError('没有 openssl 命令：装上 openssl，或在 Mac 上用钥匙串（KB_SECRET_BACKEND=keychain）')
    env = dict(os.environ, KB_VAULT_PASS=_master())
    r = subprocess.run(['openssl', 'enc', *args, '-aes-256-cbc', '-pbkdf2', '-iter', _ITER, '-pass', 'env:KB_VAULT_PASS'],
                       input=data, capture_output=True, env=env, timeout=30)
    if r.returncode:
        raise VaultError('机密文件解不开：主密钥不对，或 store.enc 损坏' if '-d' in args else f'加密失败：{r.stderr.decode()[:200]}')
    return r.stdout


def _load():
    if not STORE.exists():
        return {}
    return json.loads(_openssl(['-d'], STORE.read_bytes()).decode('utf-8') or '{}')


def _save(data):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(STORE.parent, 0o700)
    tmp = STORE.with_suffix('.tmp')
    tmp.write_bytes(_openssl(['-salt'], json.dumps(data, ensure_ascii=False).encode('utf-8')))
    os.chmod(tmp, 0o600)
    tmp.replace(STORE)


class _Locked:
    def __enter__(self):
        STORE.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(STORE.parent / '.lock', 'w')
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


# ---------------------------------------------------------------- 接口
def get(service, acct):
    if BACKEND == 'keychain':
        r = _sec('find-generic-password', '-s', service, '-a', acct, '-w')
        return r.stdout.rstrip('\n') if r.returncode == 0 else None
    with _Locked():
        return (_load().get(service) or {}).get(acct, {}).get('值')


def put(service, acct, value, label=''):
    if BACKEND == 'keychain':
        r = _sec('add-generic-password', '-U', '-s', service, '-a', acct, '-w', value, *(['-l', label] if label else []))
        if r.returncode:
            raise VaultError(f'钥匙串操作失败：{(r.stderr or r.stdout).strip()[:200]}')
        return
    with _Locked():
        d = _load()
        d.setdefault(service, {})[acct] = {'值': value, '说明': label}
        _save(d)


def delete(service, acct):
    if BACKEND == 'keychain':
        _sec('delete-generic-password', '-s', service, '-a', acct)
        return
    with _Locked():
        d = _load()
        if acct in (d.get(service) or {}):
            del d[service][acct]
            if not d[service]:
                del d[service]
            _save(d)


def find(service):
    """这个服务存的第一条（kb login 的网站凭据只存一条）→ (账号, 密码) 或 None。"""
    if BACKEND == 'keychain':
        pw = _sec('find-generic-password', '-s', service, '-w')
        if pw.returncode:
            return None
        import re
        m = re.search(r'"acct"<blob>="([^"]*)"', _sec('find-generic-password', '-s', service).stdout)
        return (m.group(1) if m else '', pw.stdout.rstrip('\n'))
    with _Locked():
        items = _load().get(service) or {}
    if not items:
        return None
    acct, v = next(iter(items.items()))
    return acct, v.get('值', '')


def put_interactive(service, acct, label=''):
    """终端里输入密码存进去：钥匙串由 security 自己提示（本程序拿不到明文）；加密文件用 getpass。"""
    if BACKEND == 'keychain':
        subprocess.run(['security', 'add-generic-password', '-U', '-a', acct, '-s', service, '-l', label or service, '-w'], check=True)
        return
    pw = getpass.getpass(f'{acct} 的密码（不回显）：')
    if not pw:
        raise VaultError('没有输入密码')
    put(service, acct, pw, label)
