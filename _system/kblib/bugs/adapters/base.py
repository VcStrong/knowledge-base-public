# From 大大王.DT
"""适配器共用：文本整理（简介、栏目、Jenkins）、时间、HTTP、账号（Cred）、适配器基类和统一的 Bug 条目。
本包不 import kb / kblib 其他部分：凭据由调用方经 Cred 交进来。"""
import html
import json
import re
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote
from urllib.parse import urlencode


UA = 'kb-local/1.0'


class SourceError(Exception):
    pass

# ---------------------------------------------------------------- 通用小工具

def html_text(s):
    s = re.sub(r'(?is)<(script|style|noscript)\b.*?</\1>', ' ', s or '')
    s = re.sub(r'(?i)<br\s*/?>|</(p|div|tr|li|h[1-6]|table|section)>', '\n', s)
    s = html.unescape(re.sub(r'<[^>]+>', ' ', s))
    s = re.sub(r'[ \t ]+', ' ', s)
    return re.sub(r'\n\s*\n+', '\n\n', s).strip()


def safe_file(s):
    return re.sub(r'[\\/:*?"<>|\r\n\t]+', '-', (s or '').strip()).strip('.- ') or 'file'


def local_time(iso):
    """接口时间（UTC 带 Z / 带时区 / 本地无时区 / 毫秒时间戳）→ 本地「YYYY-MM-DD HH:MM」。"""
    if iso in (None, ''):
        return ''
    if isinstance(iso, (int, float)) or re.fullmatch(r'\d{10,13}', str(iso)):
        v = float(iso)
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v).strftime('%Y-%m-%d %H:%M')
    s = str(iso).strip().replace(' ', 'T', 1)
    try:
        t = datetime.fromisoformat(re.sub(r'Z$', '+00:00', re.sub(r'(\.\d{6})\d+', r'\1', re.sub(r'([+-]\d\d)(\d\d)$', r'\1:\2', s))))
        if t.tzinfo:
            t = t.astimezone().replace(tzinfo=None)
        return t.strftime('%Y-%m-%d %H:%M')
    except ValueError:
        return str(iso)[:16].replace('T', ' ')


def norm(s):
    return re.sub(r'[\s_\-—–·｜|/\\()（）【】\[\]「」:：,，。.、!！?？]+', '', (s or '').lower())


PLATFORMS = ['全部', '安卓', 'iOS', '服务端', '前端']
SIGNS = {'安卓': r'android|安卓|\bapk\b|_android_', 'iOS': r'\bios\b|iphone|ipad|苹果|_ios_',
         '服务端': r'java|服务端|后端|server|接口', '前端': r'\bfe\b|前端|\bh5\b|\bpc\b|\bweb\b'}


def platform_of(primary, *others):
    """先看 primary（产品名 / 项目名，本身常常分了平台），再看其他线索；只命中一个平台才算数（多个取第一个）。"""
    for k, pat in SIGNS.items():
        if re.search(pat, primary or '', re.I):
            return k
    hay = ' '.join(x or '' for x in others)
    hits = [k for k, pat in SIGNS.items() if re.search(pat, hay, re.I)]
    return hits[0] if hits else ''


def platform_tags(name):
    return [k for k, pat in SIGNS.items() if re.search(pat, name or '', re.I)]


_HEAD = re.compile(r'^\s*([^\n：:，。,;；]{1,24})[：:]\s*(.*)$')


def sections(text):
    """按行切成 [(栏目, 内容)]：一行以「短标题：」开头就是新栏目（测试常用的 Bug 模板都适用）。"""
    out, cur = [], None
    for line in (text or '').splitlines():
        mm = _HEAD.match(line)
        if mm and not re.match(r'https?$', mm.group(1).strip(), re.I):
            cur = [mm.group(1).strip(), [mm.group(2)]]
            out.append(cur)
        elif cur:
            cur[1].append(line)
    return [(h, re.sub(r'\s+', ' ', ' '.join(b)).strip()) for h, b in out]


def section(text, *names):
    secs = sections(text)
    for n in names:
        for h, b in secs:
            if h.lower().startswith(n.lower()) and b:
                return b
    return ''


def bracket_sections(t):
    """「[结果] … [环境\\测试\\线上] …」这种方括号栏目统一成「结果：」，两种模板一起解析。"""
    return re.sub(r'\[([^\]\n]{1,24})\]\s*', lambda mm: '\n' + mm.group(1) + '：\n', t or '')


def brief(text, title=''):
    """一两句简介：实际结果（和标题重复就换成期望）+ 环境 + 复现概率；没有模板栏目就取正文开头。正文本身不存。"""
    t = text or ''
    nt = norm(title)
    dup = lambda x: norm(x) and nt and (norm(x) in nt or nt in norm(x))
    act = section(t, '实际结果', '结果', '现象', 'Actual')
    if not act or dup(act):
        exp = section(t, '期望结果', '期望', '预期结果', '预计', 'Expected')
        act = f'期望：{exp}' if exp else ''
    if not act:
        desc = section(t, '问题描述', '描述', 'Description')
        act = '' if dup(desc) else desc
    if not act and not sections(t):
        first = re.sub(r'\s+', ' ', t).strip()
        act = '' if dup(first) else first
    act = act[:90] + ('…' if len(act) > 90 else '')
    env = section(t, '环境', 'Environment')
    rate = section(t, '复现概率', '复现几率', '复现', 'Reproducibility')
    return '；'.join(x for x in (act, f'环境：{env[:12]}' if env else '', f'复现：{rate[:8]}' if rate else '') if x)


def online(text):
    env = section(text, '环境', 'Environment')
    return bool(env and re.search(r'线上|正式|生产|prod', env, re.I))


JENKINS_RE = re.compile(r'https?://[^\s<>"\']*/jenkins/(?:job/[^/\s<>"\']+/?)+(?:\d+/?)?', re.I)


def jenkins(text):
    """正文里的 Jenkins 地址 → (地址, 任务名)。安卓的任务名 = 前缀 + 分支名，如 app_android_new_feature-xxx-stable。"""
    mm = JENKINS_RE.search(text or '')
    if not mm:      # 只写了任务名：「Jenkins： mvbox_android_new_feature-xxx-stable #7」
        sec = section(text or '', 'Jenkins', 'jenkis')
        jm = re.match(r'([A-Za-z][\w.-]{5,})', sec)
        return ('', jm.group(1)) if jm else ('', '')
    jobs = re.findall(r'/job/([^/\s]+)', mm.group(0))
    return mm.group(0), unquote(jobs[-1]) if jobs else ''


def http(method, url, headers=None, body=None, timeout=30, raw=False, what='接口'):
    """→ (状态码, 响应头, JSON 或 bytes)。HTTP 错误抛 SourceError，带上状态码和响应开头。"""
    data = body if isinstance(body, (bytes, type(None))) else (
        urlencode(body).encode() if isinstance(body, dict) and (headers or {}).get('Content-Type') == 'application/x-www-form-urlencoded'
        else json.dumps(body).encode())
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('User-Agent', UA)
    req.add_header('Accept', 'application/json')
    if data is not None and 'Content-Type' not in (headers or {}):
        req.add_header('Content-Type', 'application/json')
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code, hdr, b = r.status, dict(r.headers), r.read(60 << 20)
    except urllib.error.HTTPError as e:
        b = e.read()[:400].decode('utf-8', 'replace')
        err = SourceError(f'{what} {method} {url.split("?")[0]} 返回 {e.code}：{b}')
        err.code = e.code
        err.headers = dict(e.headers or {})
        raise err
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SourceError(f'连不上{what}（{url.split("?")[0]}）：{e}')
    if raw:
        return code, hdr, b
    try:
        return code, hdr, json.loads(b.decode('utf-8', 'replace')) if b.strip() else {}
    except ValueError:
        raise SourceError(f'{what} {url.split("?")[0]} 返回的不是 JSON：{b[:200].decode("utf-8", "replace")}')


def save_download(body, ctype, dest, url):
    if 'text/html' in (ctype or '') and b'<html' in body[:500].lower():
        return f'{dest.name}：下载失败（需要网页登录，打开 {url} 查看）'
    dest.write_bytes(body)
    return str(dest)


class Cred:
    """基础知识库条目里的账号字段：普通字段直接给；机密字段用到时才经 secret(字段) 读钥匙串。"""

    def __init__(self, entry, secret=None):
        self.entry = entry or {'编号': '', '名称': '', '字段': []}
        self._secret = secret
        self.fields = {x['名']: x for x in self.entry.get('字段') or []}

    def get(self, *names, default=''):
        for n in names:
            f = self.fields.get(n)
            if f and not f.get('机密') and str(f.get('值') or '').strip():
                return str(f['值']).strip()
        low = {k.lower(): v for k, v in self.fields.items()}
        for n in names:
            f = low.get(n.lower())
            if f and not f.get('机密') and str(f.get('值') or '').strip():
                return str(f['值']).strip()
        return default

    def has(self, *names):
        return any(n in self.fields for n in names)

    def secret(self, *names):
        for n in names:
            if n in self.fields:
                if self.fields[n].get('机密'):
                    if not self._secret:
                        raise SourceError('没有读取机密的方式')
                    return self._secret(n)
                return str(self.fields[n].get('值') or '')
        raise SourceError(f'{self.entry.get("编号")} {self.entry.get("名称")} 缺少字段：{" / ".join(names)}')



# ---------------------------------------------------------------- 适配器基类

class Source:
    """一个平台实例。conf = 设置里这一个来源（ID、适配器、范围、平台、选项…），cred = 账号。"""
    kind = '缺陷'                 # 缺陷 → Bug 页；崩溃 → ANR / 崩溃页
    adapter = ''
    guess = ()                   # 基础信息里自动找账号用的关键字
    fields = ''                  # 账号条目需要的字段（给人看的说明）
    options = []                 # 这个平台特有的选项：[(名, 说明, 默认)]
    id_pattern = r'.+'           # 用户直接给编号时，判断像不像这个平台的

    def __init__(self, conf, cred):
        self.conf = conf
        self.id = conf.get('ID') or self.adapter
        self.cred = cred
        self.opt = dict(conf.get('选项') or {})

    def o(self, k, default=''):
        v = self.opt.get(k)
        if v in (None, ''):
            v = next((d for n, _, d in self.options if n == k), default)
        return v

    # 编号 = 索引的键：同一知识库里接多个平台时不能撞。默认纯数字的加上来源前缀
    def key(self, num):
        num = str(num)
        return f'{self.id}-{num}' if num.isdigit() else num

    def num(self, key):
        key = str(key)
        return key[len(self.id) + 1:] if key.startswith(self.id + '-') and key[len(self.id) + 1:].isdigit() else key

    def account(self):
        """当前登录账号（「我的」范围按它筛）。"""
        return ''

    def test(self):
        raise NotImplementedError

    def sync(self, state, ctx):
        """增量拉取，yield 统一格式的条目（缺陷：Bug 条目；崩溃：问题）；yield {'删除': 键} 表示平台上删了。
        state 是这个来源自己的持久状态（游标、名称缓存、各分组的同步结果），直接改它就行。
        ctx：全量、人员（集合，空 = 不按人）、平台、首次天数。"""
        raise NotImplementedError

    def get(self, key, download=True):
        """实时拉一条：{'条目': 统一条目, '正文': 文本, '信息': [补充行], '评论': [(时间, 人, 动作, 内容)], '附件': [本地路径或说明]}"""
        raise NotImplementedError

    def tmpdir(self, key):
        import shutil
        d = Path(tempfile.gettempdir()) / 'kb-bug' / safe_file(f'{self.id}-{key}')
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)
        return d


def entry(src, **kw):
    """统一的 Bug 条目（缺陷类）。分组 = 平台里能把 Bug 归到期的东西：禅道的执行 / 项目、Jira 的 Sprint / Epic / 版本…
    强 = 一个分组基本只对应一期（执行、Sprint），先于分支线索判断；弱的（项目、版本）在分支之后。"""
    e = {'来源': src.id, '编号': '', '原编号': '', '链接': '', '标题': '', '简介': '', '状态': '', '严重': '', '优先级': '',
         '产品': '', '产品ID': '', '版本': '', '平台': '', '线上': False, 'Jenkins': '', 'Jenkins任务': '',
         '指派给': '', '指派账号': '', '解决人': '', '解决账号': '', '创建人': '', '创建时间': '', '修改时间': '', '修改原值': '',
         '分组': []}
    e.update(kw)
    e['编号'] = src.key(e.get('原编号') or e['编号'])
    e['分组'] = [g for g in e['分组'] if str(g.get('ID') or '') not in ('', '0')]
    return e
