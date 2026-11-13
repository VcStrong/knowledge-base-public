# From 大大王.DT
"""网页 / Confluence 抓取：凭据从 macOS 钥匙串读取（服务名 kb:<主机名>），不落盘、不打印。"""
import base64
import re
import subprocess
import urllib.error
import urllib.request
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse
from kblib.infra import vault

UA = 'kb-local/1.0'
MAX_DOWNLOAD = 100 * 1024 * 1024


class FetchError(Exception):
    pass


# ---------------------------------------------------------------- 凭据

def keychain_service(host):
    return f'kb:{host}'


def cred(host):
    try:
        return vault.find(keychain_service(host))
    except Exception:
        return None


def save_cred(host, user):
    """交互式输入密码：Mac 上由 security 自己提示（本程序拿不到明文），远端服务器存加密文件。"""
    vault.put_interactive(keychain_service(host), user, f'知识库抓取 {host}')


def login_hint(host):
    return f'需要登录 {host}：请在终端运行  kb login {host} <用户名>  （密码存入{vault.LABEL}）'


# ---------------------------------------------------------------- HTTP

def http_get(url, max_bytes=MAX_DOWNLOAD):
    host = urlparse(url).hostname or ''
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'X-Atlassian-Token': 'no-check'})
    c = cred(host)
    if c:
        token = base64.b64encode(f'{c[0]}:{c[1]}'.encode()).decode()
        req.add_header('Authorization', f'Basic {token}')
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise FetchError(f'文件超过 {max_bytes // 1048576} MB：{url}')
            return data, r.headers, r.geturl()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403) or (e.code == 404 and not c):
            raise FetchError(login_hint(host) if not c else f'{host} 拒绝访问（{e.code}），请确认账号权限或重新 kb login')
        raise FetchError(f'请求失败 {e.code}：{url}')
    except urllib.error.URLError as e:
        raise FetchError(f'连不上 {host}：{e.reason}（是否需要 VPN？）')


CACHE = Path(__file__).resolve().parents[2] / 'cache'      # _system/cache
CACHE_TTL = 1800


def http_get_cached(url):
    """大页面（如 Axure 导出的几十 MB 单页 PRD）先预览再导入时不重复下载。"""
    import hashlib
    import json
    import time
    CACHE.mkdir(exist_ok=True)
    k = hashlib.sha1(url.encode()).hexdigest()
    body, meta = CACHE / k, CACHE / (k + '.json')
    if body.exists() and meta.exists() and time.time() - body.stat().st_mtime < CACHE_TTL:
        m = json.loads(meta.read_text())
        return body.read_bytes(), m['headers'], m['final']
    for old in CACHE.iterdir():
        if time.time() - old.stat().st_mtime > CACHE_TTL:
            old.unlink(missing_ok=True)
    data, headers, final = http_get(url)
    h = {k2: headers.get(k2, '') for k2 in ('Content-Type', 'Last-Modified')}
    body.write_bytes(data)
    meta.write_text(json.dumps({'headers': h, 'final': final}))
    return data, h, final


def drop_cache(url):
    """刷新来源时丢掉缓存，保证拿到最新内容。"""
    import hashlib
    k = hashlib.sha1(url.split('#')[0].encode()).hexdigest()
    for x in (CACHE / k, CACHE / (k + '.json')):
        x.unlink(missing_ok=True)


def get_json(url):
    import json
    data, _, _ = http_get(url)
    return json.loads(data)


# ---------------------------------------------------------------- HTML → Markdown

class _MD(HTMLParser):
    BLOCK = {'p', 'div', 'section', 'article', 'header', 'footer', 'blockquote', 'dl', 'dt', 'dd'}

    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.out = []
        self.tables = []  # 栈：每个 {'rows': [[cell,...]], 'row': None, 'cell': None}
        self.lists = []
        self.skip = 0
        self.pre = 0
        self.href = []
        self.embedded = []  # (alt, mime, base64)

    def _sink(self):
        t = self.tables[-1] if self.tables else None
        return t['cell'] if t and t['cell'] is not None else self.out

    def _w(self, s):
        self._sink().append(s)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('script', 'style', 'noscript'):
            self.skip += 1
        elif self.skip:
            return
        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self._w('\n\n' + '#' * int(tag[1]) + ' ')
        elif tag in self.BLOCK:
            self._w('\n')
        elif tag == 'br':
            self._w('\n' if not (self.tables and self.tables[-1]['cell'] is not None) else ' / ')
        elif tag in ('ul', 'ol'):
            self.lists.append(0 if tag == 'ol' else -1)
            self._w('\n')
        elif tag == 'li':
            n = ''
            if self.lists and self.lists[-1] >= 0:
                self.lists[-1] += 1
                n = f'{self.lists[-1]}. '
            self._w('\n' + '  ' * max(0, len(self.lists) - 1) + (n or '- '))
        elif tag == 'pre':
            self.pre += 1
            self._w('\n```\n')
        elif tag == 'table':
            self.tables.append({'rows': [], 'row': None, 'cell': None})
        elif tag == 'tr' and self.tables:
            self.tables[-1]['row'] = []
        elif tag in ('td', 'th') and self.tables:
            t = self.tables[-1]
            if t['row'] is None:
                t['row'] = []
            t['cell'] = []
        elif tag == 'a':
            self.href.append(a.get('href') or '')
            self._w('[')
        elif tag == 'img':
            cls = a.get('class') or ''
            if 'emoticon' in cls:
                return
            src = a.get('data-image-src') or a.get('src') or ''
            m = re.match(r'data:image/(png|jpe?g|gif|webp);base64,', src)
            if m and len(src) > 4000:  # 跳过小图标
                self.embedded.append((a.get('alt') or '', m.group(1).replace('jpeg', 'jpg'), src[m.end():]))
                self._w(f'![{a.get("alt") or ""}](嵌入图片{len(self.embedded)})')
            elif src and not src.startswith('data:'):
                self._w(f'![{a.get("alt") or ""}]({urljoin(self.base, src)})')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.skip = max(0, self.skip - 1)
        elif self.skip:
            return
        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self._w('\n')
        elif tag in self.BLOCK:
            self._w('\n')
        elif tag in ('ul', 'ol'):
            if self.lists:
                self.lists.pop()
            self._w('\n')
        elif tag == 'pre':
            self.pre = max(0, self.pre - 1)
            self._w('\n```\n')
        elif tag in ('td', 'th') and self.tables:
            t = self.tables[-1]
            if t['cell'] is not None and t['row'] is not None:
                text = re.sub(r'\s*\n\s*', ' / ', ''.join(t['cell']).strip())
                t['row'].append(re.sub(r'\s+', ' ', text).replace('|', '\\|'))
            t['cell'] = None
        elif tag == 'tr' and self.tables:
            t = self.tables[-1]
            if t['row']:
                t['rows'].append(t['row'])
            t['row'] = None
        elif tag == 'table' and self.tables:
            t = self.tables.pop()
            rows = t['rows']
            if rows:
                w = max(len(r) for r in rows)
                rows = [r + [''] * (w - len(r)) for r in rows]
                md = ['| ' + ' | '.join(rows[0]) + ' |', '|' + '---|' * w]
                md += ['| ' + ' | '.join(r) + ' |' for r in rows[1:]]
                self._w('\n\n' + '\n'.join(md) + '\n\n')
        elif tag == 'a' and self.href:
            href = self.href.pop()
            if href and not href.startswith(('#', 'javascript:')):
                self._w(f']({urljoin(self.base, href)})')
            else:
                self._w(']')

    def handle_data(self, data):
        if self.skip:
            return
        self._w(data if self.pre else re.sub(r'\s+', ' ', data))

    def result(self):
        s = ''.join(self.out)
        s = re.sub(r'(?<!!)\[\s*\]\([^)]*\)', '', s)   # 空链接（不动图片）
        s = re.sub(r'\[([^\]]*)\]\(\)', r'\1', s)
        s = re.sub(r'\[\s*(!\[[^\]]*\]\([^)]*\))\s*\]\([^)]*\)', r'\1', s)  # 图片外包的链接
        s = re.sub(r'[ \t]+\n', '\n', s)
        return re.sub(r'\n{3,}', '\n\n', s).strip()


def html_to_md(html, base, embedded=None):
    p = _MD(base)
    p.feed(html)
    p.close()
    if embedded is not None:
        embedded.extend(p.embedded)
    return p.result()


# ---------------------------------------------------------------- 页面

def _confluence_id(url, base):
    u = urlparse(url)
    q = parse_qs(u.query)
    if 'pageId' in q:
        return q['pageId'][0]
    m = re.match(r'/display/([^/]+)/(.+)', u.path)
    space, title = (m.group(1), unquote(m.group(2)).replace('+', ' ')) if m else (
        (q.get('spaceKey') or [None])[0], (q.get('title') or [None])[0])
    if space and title:
        r = get_json(f'{base}/rest/api/content?spaceKey={quote(space)}&title={quote(title)}')
        if r.get('results'):
            return r['results'][0]['id']
    html, _, _ = http_get(url)
    m = re.search(rb'name="ajs-page-id" content="(\d+)"', html)
    return m.group(1).decode() if m else None


def is_confluence(url):
    return 'confluence' in (urlparse(url).hostname or '')


def confluence_page(url):
    u = urlparse(url)
    base = f'{u.scheme}://{u.netloc}'
    pid = _confluence_id(url, base)
    if not pid:
        raise FetchError(f'没认出 Confluence 页面 ID：{url}')
    exp = 'body.view,version,space,history,ancestors,children.page'
    try:
        d = get_json(f'{base}/rest/api/content/{pid}?expand={exp}')
    except FetchError as e:
        raise FetchError(f'{e}（页面 {pid}）')
    atts = []
    start = 0
    while True:
        r = get_json(f'{base}/rest/api/content/{pid}/child/attachment?limit=100&start={start}')
        for a in r.get('results', []):
            atts.append({'name': a['title'], 'url': base + a['_links']['download'],
                         'size': (a.get('extensions') or {}).get('fileSize'),
                         'type': (a.get('extensions') or {}).get('mediaType', '')})
        if r.get('size', 0) < 100:
            break
        start += 100
    v = d.get('version') or {}
    page_url = f'{base}/pages/viewpage.action?pageId={pid}'
    return {
        'kind': 'confluence', 'id': pid, 'title': d.get('title', ''), 'url': page_url,
        'space': (d.get('space') or {}).get('name', ''),
        'version': v.get('number'), 'updated_by': (v.get('by') or {}).get('displayName', ''),
        'updated_at': (v.get('when') or '')[:16].replace('T', ' '),
        'created_by': ((d.get('history') or {}).get('createdBy') or {}).get('displayName', ''),
        'path': ' / '.join(a.get('title', '') for a in d.get('ancestors') or []),
        'md': html_to_md(((d.get('body') or {}).get('view') or {}).get('value', ''), base + '/'),
        'attachments': atts, 'embedded': [],
        'children': [{'title': c['title'], 'url': f'{base}/pages/viewpage.action?pageId={c["id"]}'}
                     for c in ((d.get('children') or {}).get('page') or {}).get('results', [])],
    }


def generic_page(url):
    data, headers, final = http_get_cached(url.split('#')[0])
    ctype = headers.get('Content-Type', '')
    if 'html' not in ctype and not data[:200].lstrip().lower().startswith((b'<!doctype', b'<html')):
        raise FetchError(f'这不是网页（{ctype}），请把它作为附件下载：{url}')
    m = re.search(r'charset=([\w-]+)', ctype)
    enc = m.group(1) if m else 'utf-8'
    html = data.decode(enc, 'replace')
    t = re.search(r'(?is)<title[^>]*>(.*?)</title>', html)
    embedded = []
    md = html_to_md(html, final, embedded)
    links = re.findall(r'\]\((https?://[^)\s]+)\)', md)
    return {'kind': 'web', 'id': '', 'title': unescape(t.group(1).strip()) if t else final, 'url': final,
            'space': '', 'version': None, 'updated_by': '', 'updated_at': headers.get('Last-Modified', ''),
            'created_by': '', 'path': '', 'md': md, 'children': [], 'embedded': embedded,
            'attachments': [{'name': unquote(urlparse(x).path.rsplit('/', 1)[-1]) or x, 'url': x, 'size': None, 'type': ''}
                            for x in dict.fromkeys(links)
                            if re.search(r'\.(png|jpe?g|gif|webp|pdf|docx?|xlsx?|pptx?|zip|json|ya?ml)$', urlparse(x).path, re.I)]}


def get_page(url):
    if not re.match(r'https?://', url or ''):
        raise FetchError(f'不是有效网址：{url}')
    return confluence_page(url) if is_confluence(url) else generic_page(url)


def download(url):
    data, headers, final = http_get(url)
    cd = headers.get('Content-Disposition', '')
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd) or re.search(r'filename="?([^";]+)', cd)
    name = unquote(m.group(1)) if m else unquote(urlparse(final).path.rsplit('/', 1)[-1])
    return name or 'download', data


# ---------------------------------------------------------------- 设计稿：Figma（个人访问令牌）/ 蓝湖

FIGMA_API = 'https://api.figma.com/v1'
MAX_FRAMES = 60


def is_design_url(url):
    h = urlparse(url).hostname or ''
    return any(h == x or h.endswith('.' + x) for x in ('figma.com', 'lanhuapp.com', 'lanhu.com'))


def _figma_get(path):
    import json
    c = cred('figma.com')
    if not c:
        raise FetchError('需要 Figma 个人访问令牌：Figma → 头像 → Settings → Security → Personal access tokens 生成'
                         '（勾选 File content 只读），然后在终端运行  kb login figma.com token  粘贴令牌')
    req = urllib.request.Request(FIGMA_API + path, headers={'X-Figma-Token': c[1], 'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise FetchError(f'Figma 拒绝访问（{e.code}）：令牌无效、过期，或你的账号没有这个文件的查看权限')
        if e.code == 404:
            raise FetchError('Figma 找不到这个文件或节点（链接是否正确、是否有权限）')
        if e.code == 429:
            raise FetchError('Figma 接口限流，请稍后再试')
        raise FetchError(f'Figma 请求失败 {e.code}')
    except urllib.error.URLError as e:
        raise FetchError(f'连不上 Figma：{e.reason}')


def parse_figma_url(url):
    u = urlparse(url)
    parts = [x for x in u.path.split('/') if x]
    if len(parts) < 2 or parts[0] not in ('design', 'file', 'proto', 'board'):
        raise FetchError(f'没认出 Figma 链接：{url}')
    key = parts[3] if len(parts) >= 4 and parts[2] == 'branch' else parts[1]
    node = (parse_qs(u.query).get('node-id') or [''])[0].replace('-', ':')
    return key, node


def _hex(c, opacity=1):
    if not c:
        return ''
    r, g, b = (round(c.get(k, 0) * 255) for k in 'rgb')
    a = c.get('a', 1) * opacity
    return f'#{r:02X}{g:02X}{b:02X}' + (f' {a:.0%}' if a < 0.999 else '')


def _solid(fills):
    for f in fills or []:
        if f.get('type') == 'SOLID' and f.get('visible', True):
            return _hex(f.get('color'), f.get('opacity', 1))
    return ''


def _frame_spec(node):
    texts, colors = [], {}

    def walk(n):
        if n.get('visible') is False:
            return
        col = _solid(n.get('fills'))
        if col and n.get('type') != 'TEXT':
            colors[col] = colors.get(col, 0) + 1
        if n.get('type') == 'TEXT':
            st = n.get('style') or {}
            texts.append({'text': (n.get('characters') or '').strip(), 'font': st.get('fontFamily', ''),
                          'size': st.get('fontSize'), 'weight': st.get('fontWeight'), 'color': col,
                          'name': n.get('name', '')})
        for ch in n.get('children') or []:
            walk(ch)

    walk(node)
    box = node.get('absoluteBoundingBox') or {}
    return {'id': node['id'], 'name': node.get('name', ''), 'type': node.get('type'),
            'w': round(box.get('width', 0)), 'h': round(box.get('height', 0)),
            'texts': [t for t in texts if t['text']],
            'colors': sorted(colors.items(), key=lambda x: -x[1])[:12]}


def _pick_frames(node):
    """链接指向页面 / 分区时取其中的画板；指向画板时就取它自己。"""
    t = node.get('type')
    if t in ('FRAME', 'COMPONENT', 'COMPONENT_SET', 'INSTANCE', 'GROUP') and node.get('id') != '0:1':
        return [node]
    out = []
    for ch in node.get('children') or []:
        if ch.get('visible') is False:
            continue
        if ch.get('type') == 'SECTION':
            out += [x for x in ch.get('children') or [] if x.get('type') in ('FRAME', 'COMPONENT', 'COMPONENT_SET')]
        elif ch.get('type') in ('FRAME', 'COMPONENT', 'COMPONENT_SET'):
            out.append(ch)
    return out


def figma_version(url):
    """只取文件版本号（便宜），用来判断设计稿有没有改。"""
    key, _ = parse_figma_url(url)
    meta = _figma_get(f'/files/{key}?depth=1')
    return meta.get('version'), (meta.get('lastModified') or '')[:16].replace('T', ' ')


def figma_design(url):
    key, node_id = parse_figma_url(url)
    meta = _figma_get(f'/files/{key}?depth=1')
    if node_id:
        r = _figma_get(f'/files/{key}/nodes?ids={quote(node_id)}')
        nd = ((r.get('nodes') or {}).get(node_id) or {}).get('document')
        if not nd:
            raise FetchError(f'Figma 文件里没有节点 {node_id}')
        roots = [nd]
    else:
        pages = (meta.get('document') or {}).get('children') or []
        if not pages:
            raise FetchError('Figma 文件是空的')
        r = _figma_get(f'/files/{key}/nodes?ids={quote(pages[0]["id"])}')
        roots = [r['nodes'][pages[0]['id']]['document']]
    frames = []
    for rt in roots:
        frames += _pick_frames(rt)
    total = len(frames)
    frames = frames[:MAX_FRAMES]
    if not frames:
        raise FetchError('这个链接下没有找到画板（Frame）')
    images = {}
    ids = [f['id'] for f in frames]
    for i in range(0, len(ids), 20):
        r = _figma_get(f'/images/{key}?ids={quote(",".join(ids[i:i + 20]))}&format=png&scale=2')
        images.update(r.get('images') or {})
    return {'kind': 'figma', 'key': key, 'node': node_id, 'title': meta.get('name', key), 'url': url,
            'version': meta.get('version'), 'updated_at': (meta.get('lastModified') or '')[:16].replace('T', ' '),
            'root_name': roots[0].get('name', ''), 'frames': [_frame_spec(f) for f in frames],
            'images': images, 'total_frames': total}
