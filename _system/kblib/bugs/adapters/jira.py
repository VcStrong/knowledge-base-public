# From 大大王.DT
"""Jira（Cloud / Server / Data Center）适配器。"""
import base64
import json
import re
import time
from datetime import datetime
from urllib.parse import quote
from urllib.parse import urlencode
from .base import (
    Source,
    SourceError,
    brief,
    entry,
    http,
    jenkins,
    local_time,
    online,
    platform_of,
    safe_file,
    save_download,
)


# ---------------------------------------------------------------- Jira（Cloud / Server / Data Center，REST v2）
# Cloud：/rest/api/2/search/jql（nextPageToken 翻页；老的 /search 已下线）；Server / DC：/rest/api/2/search（startAt 翻页）。
# 认证：Cloud = 邮箱 + API 令牌（Basic）；DC = 个人访问令牌（Bearer），或用户名 + 密码（Basic）。
# v2 的 description / 评论是 wiki 文本，直接当正文；Sprint 字段 id 各站不同，从 /rest/api/2/field 找 gh-sprint。

JIRA_PRI = {'highest': '1', 'blocker': '1', '最高': '1', 'high': '2', 'critical': '2', '高': '2', 'medium': '3', 'major': '3', '中': '3',
            'low': '4', 'minor': '4', '低': '4', 'lowest': '4', 'trivial': '4', '最低': '4'}


def _jira_wiki(t):
    """wiki 标记去掉最常见的几种，留给人和 AI 读。"""
    t = t or ''
    t = re.sub(r'\{(code|noformat)(:[^}]*)?\}', '\n', t)
    t = re.sub(r'!([^!\s|]+)(\|[^!]*)?!', r'[图片 \1]', t)
    t = re.sub(r'\[([^|\]]+)\|([^\]]+)\]', r'\1 \2', t)
    t = re.sub(r'(?m)^h[1-6]\.\s*', '', t)
    t = re.sub(r'\{color(:[^}]*)?\}', '', t)
    return re.sub(r'\*([^*\n]+)\*', r'\1', t).strip()


def _adf_text(n):
    """v3 的 ADF（万一站点只给 v3 格式）→ 纯文本。"""
    if isinstance(n, str):
        return n
    if isinstance(n, list):
        return ''.join(_adf_text(x) for x in n)
    if not isinstance(n, dict):
        return ''
    t = n.get('text') or ''
    body = _adf_text(n.get('content') or [])
    return t + body + ('\n' if n.get('type') in ('paragraph', 'heading', 'listItem', 'codeBlock', 'blockquote', 'rule') else '')


class JiraSource(Source):
    adapter = 'Jira'
    guess = ('jira', 'atlassian')
    fields = '地址（如 https://xxx.atlassian.net 或公司 Jira 地址）、用户名（Cloud 填邮箱；DC 用个人访问令牌时可空）、令牌〔机密，Cloud 的 API 令牌 / DC 的个人访问令牌〕或 密码〔机密〕'
    options = [('JQL', '附加筛选条件，如 project = APP AND component = Android（空 = 不加）', ''),
               ('问题类型', '只同步这些类型，逗号隔开（空 = 不限）', 'Bug,缺陷,故障'),
               ('已解决状态', '这些状态算「已解决」（其余完成类状态算「已关闭」），逗号隔开', 'Resolved,Fixed,已解决,待验证,Ready for Test')]
    id_pattern = r'[A-Z][A-Z0-9_]+-\d+'

    @property
    def base(self):
        u = self.cred.get('地址', '网址', 'URL', 'url')
        if not u:
            raise SourceError(f'{self.cred.entry.get("编号")} {self.cred.entry.get("名称")} 缺少「地址」字段')
        return re.sub(r'/(browse/.*|secure/.*|jira/.*|projects/.*)?$', '', u.strip().rstrip('/'))

    @property
    def cloud(self):
        return '.atlassian.net' in self.base or self.o('部署') == 'Cloud'

    def _auth(self):
        if getattr(self, '_hdr', None):
            return self._hdr
        user = self.cred.get('用户名', '邮箱', '账号', 'email')
        tok = next((n for n in ('令牌', 'API令牌', 'API Token', 'Token', 'token', 'PAT') if self.cred.has(n)), '')
        if tok and (user and self.cloud):
            v = 'Basic ' + base64.b64encode(f'{user}:{self.cred.secret(tok)}'.encode()).decode()
        elif tok and not user:
            v = 'Bearer ' + self.cred.secret(tok)
        elif self.cred.has('密码') and user:
            v = 'Basic ' + base64.b64encode(f'{user}:{self.cred.secret("密码")}'.encode()).decode()
        elif tok:
            v = 'Bearer ' + self.cred.secret(tok)
        else:
            raise SourceError(f'{self.cred.entry.get("编号")} 缺少令牌或密码字段（{self.fields}）')
        self._hdr = v
        return v

    def _get(self, path, raw=False, **params):
        url = self.base + path + ('?' + urlencode({k: v for k, v in params.items() if v not in (None, '')}) if params else '')
        for i in range(4):
            try:
                return http('GET', url, {'Authorization': self._auth()}, raw=raw, what='Jira')[2]
            except SourceError as e:
                if getattr(e, 'code', 0) == 429 and i < 3:            # Cloud 限流：按 Retry-After 等一下
                    time.sleep(min(30, int((e.headers or {}).get('Retry-After') or 5)))
                    continue
                if getattr(e, 'code', 0) == 401:
                    raise SourceError(f'Jira 登录失败（401）：检查账号条目里的用户名 / 令牌。{e}')
                raise

    def _me(self):
        if not getattr(self, '_myself', None):
            self._myself = self._get('/rest/api/2/myself')
        return self._myself

    def account(self):
        m = self._me()
        return m.get('accountId') or m.get('name') or m.get('key') or ''

    def _sprint_field(self, state):
        if 'Sprint字段' not in state:
            try:
                fs = self._get('/rest/api/2/field')
                state['Sprint字段'] = next((f['id'] for f in fs if (f.get('schema') or {}).get('custom') == 'com.pyxis.greenhopper.jira:gh-sprint'), '')
                state['Epic字段'] = next((f['id'] for f in fs if (f.get('schema') or {}).get('custom') == 'com.pyxis.greenhopper.jira:gh-epic-link'), '')
            except SourceError:
                state['Sprint字段'], state['Epic字段'] = '', ''
        return state['Sprint字段'], state.get('Epic字段', '')

    def test(self):
        m = self._me()
        out = [f'✓ 已登录 {self.base}（{"Cloud" if self.cloud else "Server / Data Center"}；{m.get("displayName")}，账号 {self.account()}，时区 {m.get("timeZone")}）']
        st = {}
        sf, ef = self._sprint_field(st)
        out.append(f'Sprint 字段：{sf or "没找到（没装 Jira Software？）"}；Epic 字段：{ef or "无（新版用 parent）"}')
        jql = self._jql(set(), '', first=True)
        r = list(self._search(jql, st, limit=5))
        out.append(f'JQL：{jql}\n例：' + ('；'.join(f'{x["编号"]} {x["标题"][:30]}（{x["状态"]}）' for x in r) or '没有匹配的问题'))
        return '\n'.join(out)

    def _jql(self, people, since, first=False):
        q = []
        if self.o('JQL'):
            q.append(f'({self.o("JQL")})')
        types = [x.strip() for x in str(self.o('问题类型')).split(',') if x.strip()]
        if types and not getattr(self, '_types_off', False):
            q.append('issuetype in (' + ', '.join(json.dumps(t, ensure_ascii=False) for t in types) + ')')
        if people:
            ps = ', '.join(json.dumps(p) for p in sorted(people))
            q.append(f'(assignee in ({ps}) OR assignee was in ({ps}) OR status changed by ({ps}))'
                     if people != {self.account()} else '(assignee = currentUser() OR assignee was currentUser() OR status changed by currentUser())')
        if since:
            q.append(f'updated >= "{since}"')
        elif first:
            q.append('(statusCategory != Done OR updated >= -30d)')
        return ' AND '.join(q) + ' ORDER BY updated DESC'

    def _fields(self, state, full=False):
        sf, ef = self._sprint_field(state)
        f = ['summary', 'status', 'priority', 'assignee', 'reporter', 'created', 'updated', 'description', 'environment', 'labels',
             'components', 'fixVersions', 'versions', 'project', 'resolution', 'issuetype', 'parent'] + [x for x in (sf, ef) if x]
        return f + (['comment', 'attachment'] if full else [])

    def _search(self, jql, state, limit=0, changelog=True):
        params = {'jql': jql, 'fields': ','.join(self._fields(state)), 'maxResults': 100}
        if changelog:
            params['expand'] = 'changelog'
        n = 0
        if self.cloud:
            tok, seen = None, set()
            while True:
                r = self._get('/rest/api/2/search/jql', **dict(params, nextPageToken=tok))
                for it in r.get('issues') or []:
                    yield self._entry(it, state)
                    n += 1
                    if limit and n >= limit:
                        return
                tok = r.get('nextPageToken')
                if r.get('isLast', True) or not tok or tok in seen:
                    return
                seen.add(tok)
        else:
            start = 0
            while True:
                r = self._get('/rest/api/2/search', **dict(params, startAt=start))
                its = r.get('issues') or []
                for it in its:
                    yield self._entry(it, state)
                    n += 1
                    if limit and n >= limit:
                        return
                start += len(its)
                if not its or start >= int(r.get('total') or 0):
                    return

    @staticmethod
    def _uid(u):
        return (u.get('accountId') or u.get('name') or u.get('key') or '') if isinstance(u, dict) else ''

    def _status(self, st):
        cat = ((st or {}).get('statusCategory') or {}).get('key')
        name = (st or {}).get('name') or ''
        if cat != 'done':
            return '激活'
        res = [x.strip().lower() for x in str(self.o('已解决状态')).split(',') if x.strip()]
        return '已解决' if name.lower() in res else '已关闭'

    @staticmethod
    def _sprints(v):
        out = []
        for x in v or []:
            if isinstance(x, dict):
                out.append({'ID': str(x.get('id')), '名': x.get('name') or '', '状态': (x.get('state') or '').lower()})
            elif isinstance(x, str):                         # 老 DC：「…Sprint@1a2b[id=37,rapidViewId=1,state=ACTIVE,name=Sprint 5,…]」
                g = lambda k: (re.search(rf'\b{k}=([^,\]]*)', x) or [None, ''])[1]
                out.append({'ID': g('id'), '名': g('name'), '状态': g('state').lower()})
        return out

    def _entry(self, it, state):
        f = it.get('fields') or {}
        sf, ef = state.get('Sprint字段'), state.get('Epic字段')
        desc = f.get('description')
        text = _jira_wiki(desc if isinstance(desc, str) else _adf_text(desc))
        envt = f.get('environment')
        envt = envt if isinstance(envt, str) else _adf_text(envt)
        full = text + (f'\n环境：{envt}' if envt and '环境' not in text else '')
        jurl, job = jenkins(full)
        title = f.get('summary') or ''
        proj = (f.get('project') or {})
        comps = [c.get('name') or '' for c in f.get('components') or []]
        labels = f.get('labels') or []
        groups = []
        sp = self._sprints(f.get(sf)) if sf else []
        if sp:                                               # 一个问题可能跨多个 Sprint：取进行中的，否则最后一个
            s = next((x for x in sp if x['状态'] == 'active'), sp[-1])
            groups.append({'类型': 'Sprint', 'ID': s['ID'], '名': s['名'], '强': 1})
        par = f.get('parent') or {}
        if par and ((par.get('fields') or {}).get('issuetype') or {}).get('name', '').lower() in ('epic', '史诗'):
            groups.append({'类型': 'Epic', 'ID': par.get('key'), '名': (par.get('fields') or {}).get('summary') or '', '强': 0})
        elif ef and f.get(ef):
            groups.append({'类型': 'Epic', 'ID': str(f[ef]), '名': str(f[ef]), '强': 0})
        for v in f.get('fixVersions') or []:
            groups.append({'类型': '版本', 'ID': str(v.get('id')), '名': v.get('name') or '', '强': 0})
        resolver = ''
        for h in reversed((it.get('changelog') or {}).get('histories') or []):
            if any(x.get('field') == 'resolution' and x.get('toString') for x in h.get('items') or []):
                resolver = h.get('author') or {}
                break
        pri = (f.get('priority') or {}).get('name') or ''
        online_ = online(full) or any(re.search(r'线上|生产|online|prod', x, re.I) for x in labels) or bool(re.search(r'线上|生产|prod', envt or '', re.I))
        return entry(self, 原编号=it['key'], 链接=f'{self.base}/browse/{it["key"]}', 标题=title, 简介=brief(full, title),
                     状态=self._status(f.get('status')), 平台状态=(f.get('status') or {}).get('name') or '',
                     严重=JIRA_PRI.get(pri.lower(), ''), 优先级=pri, 产品=proj.get('name') or '', 产品ID=proj.get('key') or '',
                     版本=','.join(v.get('name') or '' for v in f.get('versions') or []),
                     平台=platform_of(proj.get('name') or '', ' '.join(comps), ' '.join(labels), job, title), 线上=online_,
                     Jenkins=jurl, Jenkins任务=job,
                     指派给=(f.get('assignee') or {}).get('displayName') or '', 指派账号=self._uid(f.get('assignee')),
                     解决人=(resolver or {}).get('displayName') or '' if resolver else '', 解决账号=self._uid(resolver),
                     创建人=(f.get('reporter') or {}).get('displayName') or '', 创建时间=local_time(f.get('created')),
                     修改时间=local_time(f.get('updated')), 修改原值=str(f.get('updated') or ''), 分组=groups,
                     模块=' / '.join(comps), 标签=labels, 正文=full)

    def _since(self, iso):
        """上次见过的最大修改时间 → JQL 时间（按 Jira 账号的时区；往前多留 2 分钟，宁可重复不漏）。"""
        try:
            t = datetime.fromisoformat(re.sub(r'([+-]\d\d)(\d\d)$', r'\1:\2', re.sub(r'\.\d+', '', iso)))
        except ValueError:
            return ''
        try:
            from zoneinfo import ZoneInfo
            t = t.astimezone(ZoneInfo(self._me().get('timeZone') or 'UTC'))
        except Exception:
            t = t.astimezone()
        return datetime.fromtimestamp(t.timestamp() - 120, t.tzinfo).strftime('%Y/%m/%d %H:%M')

    def sync(self, state, ctx):
        cur = state.get('游标') or {}
        since = '' if ctx.get('全量') else self._since(cur.get('修改', '')) if cur.get('修改') else ''
        jql = self._jql(set(ctx.get('人员') or []), since, first=not since)
        top = cur.get('修改', '')
        n = 0
        try:
            items = list(self._search(jql, state))
        except SourceError as e:
            if 'issuetype' in str(e) and getattr(e, 'code', 0) == 400:      # 站点里没有这些类型名：去掉类型条件再来
                self._types_off = True
                items = list(self._search(self._jql(set(ctx.get('人员') or []), since, first=not since), state))
            else:
                raise
        for e in items:
            n += 1
            e.pop('正文', None)
            if e['修改原值'] > top:
                top = e['修改原值']
            yield e
        state['游标'] = {'修改': top}
        state['同步'] = {'Jira': f'{datetime.now():%Y-%m-%d %H:%M} 检查 {n} 条'}

    def get(self, key, download=True):
        st = {}
        it = self._get(f'/rest/api/2/issue/{quote(key)}', fields=','.join(self._fields(st, True)), expand='changelog')
        e = self._entry(it, st)
        text = e.pop('正文', '')
        f = it.get('fields') or {}
        info = [f'类型：{(f.get("issuetype") or {}).get("name") or ""}　平台上状态：{e.get("平台状态")}　项目：{e["产品"]}　模块：{e.get("模块") or "无"}　'
                f'标签：{"、".join(e.get("标签") or []) or "无"}　分组：{"；".join(g["类型"] + " " + g["名"] for g in e["分组"]) or "无"}']
        cm = (f.get('comment') or {})
        cs = cm.get('comments') or []
        if int(cm.get('total') or 0) > len(cs):
            try:
                cs = self._get(f'/rest/api/2/issue/{quote(key)}/comment', maxResults=200).get('comments') or cs
            except SourceError:
                pass
        comments = [(local_time(c.get('created')), (c.get('author') or {}).get('displayName') or '', '',
                     _jira_wiki(c.get('body') if isinstance(c.get('body'), str) else _adf_text(c.get('body')))) for c in cs]
        files = []
        atts = f.get('attachment') or []
        if download and atts:
            tmp = self.tmpdir(key)
            for a in atts[:30]:
                url = f'{self.base}/rest/api/2/attachment/content/{a["id"]}?redirect=false' if self.cloud else a.get('content')
                dest = tmp / safe_file(a.get('filename') or f'附件{a["id"]}')
                try:
                    if int(a.get('size') or 0) > 50 << 20:
                        files.append(f'{dest.name}：超过 50MB 没下载，原地址 {a.get("content")}')
                        continue
                    _, h, body = http('GET', url, {'Authorization': self._auth()}, raw=True, what='Jira 附件')
                    files.append(save_download(body, h.get('Content-Type', ''), dest, a.get('content')))
                except Exception as ex:
                    files.append(f'{dest.name}：下载失败（{ex}），原地址 {a.get("content")}')
        for k in ('模块', '标签', '平台状态'):
            e.pop(k, None)
        return {'条目': e, '正文': text, '信息': info, '评论': comments, '附件': files}
