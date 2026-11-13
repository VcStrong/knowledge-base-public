"""部署：知识库可以装在本机（Mac，只给自己用，默认只听 127.0.0.1），也可以装在远端服务器上用浏览器访问。

  访问密码：kb passwd 设置（存 PBKDF2 哈希，在「设置.json」部署.密码）。设了密码，网页要先登录；
            网页监听的不是本机地址（kb web --host 0.0.0.0）时必须先设密码，否则不启动。
  登录会话：浏览器登录后发 Cookie（HttpOnly、SameSite=Strict，经 HTTPS 反向代理时带 Secure），30 天有效，存 .网页会话.json（只存哈希）。
  访问令牌：kb token add <名称> 生成（只显示一次，只存哈希），给远处的 Claude Code 连知识库 MCP 用：
            claude mcp add --transport http kb https://<地址>/mcp --header "Authorization: Bearer <令牌>"
放在公网时建议前面加 HTTPS 反向代理（nginx / Caddy），反向代理要保留 Host 头。
"""
import hashlib
import hmac
import json
import os
import secrets
import time

from .common import KBError, ROOT, load_settings, now, save_settings

SESS_FILE = ROOT / '.网页会话.json'
SESS_DAYS = 30
LOOPBACK = ('127.0.0.1', 'localhost', '::1')


def _hash_pw(pw, salt=None, it=200_000):
    salt = salt or secrets.token_hex(16)
    return f'pbkdf2_sha256${it}${salt}${hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), it).hex()}'


def _check_pw(pw, h):
    try:
        _, it, salt, _hex = h.split('$')
    except ValueError:
        return False
    return hmac.compare_digest(_hash_pw(pw, salt, int(it)), h)


def _tok_hash(t):
    return hashlib.sha256(t.encode()).hexdigest()


def _dep():
    return load_settings().get('部署') or {}


def _save_dep(d):
    st = load_settings()
    st['部署'] = d
    save_settings(st)


# ---------------------------------------------------------------- 访问密码、登录
def auth_required():
    return bool(_dep().get('密码'))


def set_password(pw):
    d = _dep()
    if pw:
        if len(pw) < 8:
            raise KBError('访问密码至少 8 位')
        d['密码'] = _hash_pw(pw)
        d['密码时间'] = now()
        msg = '已设置网页访问密码：之后打开网页要先登录'
    else:
        d.pop('密码', None)
        msg = '已取消网页访问密码（只在本机 127.0.0.1 使用时才这样做）'
    _save_dep(d)
    _sess_save({})                     # 改密码后所有已登录的浏览器都要重新登录
    return msg


def _sess_load():
    try:
        return json.loads(SESS_FILE.read_text('utf-8'))
    except (OSError, ValueError):
        return {}


def _sess_save(d):
    tmp = SESS_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(d), 'utf-8')
    os.chmod(tmp, 0o600)
    tmp.replace(SESS_FILE)


def web_login(pw):
    """校验访问密码，成功返回新的登录会话令牌。"""
    h = _dep().get('密码')
    if not h or not _check_pw(pw or '', h):
        time.sleep(1)                  # 拖慢暴力猜密码
        raise KBError('密码不对')
    t = secrets.token_urlsafe(32)
    d = {k: v for k, v in _sess_load().items() if v > time.time()}
    d[_tok_hash(t)] = time.time() + SESS_DAYS * 86400
    _sess_save(d)
    return t


def web_logout(t):
    d = _sess_load()
    if d.pop(_tok_hash(t or ''), None):
        _sess_save(d)


def check_session(t):
    return bool(t) and _sess_load().get(_tok_hash(t), 0) > time.time()


# ---------------------------------------------------------------- 访问令牌（远处的 Claude Code 连 MCP）
def token_add(name):
    name = (name or '').strip()
    if not name:
        raise KBError('给令牌起个名字，如「家里的 Mac」')
    d = _dep()
    ts = d.setdefault('令牌', [])
    if any(x['名称'] == name for x in ts):
        raise KBError(f'已经有叫「{name}」的令牌；先 kb token del {name}')
    t = 'kb_' + secrets.token_urlsafe(32)
    ts.append({'名称': name, '哈希': _tok_hash(t), '时间': now()})
    _save_dep(d)
    return t


def token_list():
    return [{'名称': x['名称'], '时间': x['时间'], '最近使用': x.get('最近使用', '')} for x in _dep().get('令牌') or []]


def token_del(name):
    d = _dep()
    ts = d.get('令牌') or []
    if not any(x['名称'] == name for x in ts):
        raise KBError(f'没有叫「{name}」的令牌')
    d['令牌'] = [x for x in ts if x['名称'] != name]
    _save_dep(d)
    return f'已删除令牌「{name}」，用它连接的地方会断开'


def check_token(t):
    if not t or not t.startswith('kb_'):
        return False
    h = _tok_hash(t)
    d = _dep()
    for x in d.get('令牌') or []:
        if hmac.compare_digest(x['哈希'], h):
            if x.get('最近使用', '')[:13] != now()[:13]:      # 一小时最多记一次，少写设置文件
                x['最近使用'] = now()
                _save_dep(d)
            return True
    return False


def check_bind(host):
    """监听非本机地址必须先设访问密码。"""
    if host not in LOOPBACK and not auth_required():
        raise KBError(f'要监听 {host}（别的机器能访问），先运行 kb passwd 设网页访问密码')
