# From 大大王.DT
"""Sentry（sentry.io / 自建）适配器。"""
import re
import time
from datetime import datetime
from urllib.parse import urlencode
from kblib.bugs.adapters.base import SourceError, http, local_time
from kblib.bugs.adapters.crash import java_stack, native_stack, anr_stack, CrashSource


class SentrySource(CrashSource):
    adapter = 'Sentry'
    guess = ('sentry',)
    fields = '地址（sentry.io 可空；自建填 https://sentry.公司.com）、令牌〔机密，组织令牌或个人令牌，要 event:read 权限〕'
    options = [('组织', '组织 slug（网址里 /organizations/xxx/ 那段，必填）', ''),
               ('项目', '项目 ID 或 slug，逗号隔开（空 = 全部）', ''),
               ('环境', '如 production（空 = 不限）', ''),
               ('查询', 'Sentry 搜索语法', 'is:unresolved'),
               ('天数', '只看最近几天出现过的', '14'),
               ('上限', '最多同步多少个问题（按次数排）', '200')]

    @property
    def base(self):
        return (self.cred.get('地址', '网址', 'URL', 'url') or 'https://sentry.io').rstrip('/')

    def _hdr(self):
        tok = next((n for n in ('令牌', 'Token', 'token', 'API令牌', 'Auth Token') if self.cred.has(n)), '')
        if not tok:
            raise SourceError(f'{self.cred.entry.get("编号")} 缺少「令牌」字段')
        return {'Authorization': 'Bearer ' + self.cred.secret(tok)}

    def _org(self):
        o = self.o('组织')
        if not o:
            raise SourceError('Sentry 要填「组织」选项（组织 slug）')
        return o

    def _get(self, path, params=None, full_url=''):
        url = full_url or self.base + path + ('?' + urlencode(params, doseq=True) if params else '')
        for i in range(3):
            try:
                return http('GET', url, self._hdr(), what='Sentry')
            except SourceError as e:
                if getattr(e, 'code', 0) == 429 and i < 2:
                    rs = (e.headers or {}).get('X-Sentry-Rate-Limit-Reset')
                    time.sleep(max(1, min(30, int(float(rs) - time.time()) if rs else 5)))
                    continue
                raise

    def _projects(self):
        ps = [x.strip() for x in str(self.o('项目')).split(',') if x.strip()]
        if not ps or all(p.isdigit() for p in ps):
            return ps
        allp = self._get(f'/api/0/organizations/{self._org()}/projects/')[2] or []
        m = {p.get('slug'): str(p.get('id')) for p in allp}
        miss = [p for p in ps if not p.isdigit() and p not in m]
        if miss:
            raise SourceError(f'Sentry 组织里没有项目：{"、".join(miss)}（有：{"、".join(m)}）')
        return [p if p.isdigit() else m[p] for p in ps]

    def account(self):
        return ''

    def test(self):
        org = self._org()
        _, _, r = self._get(f'/api/0/organizations/{org}/projects/')
        out = [f'✓ 已连上 {self.base}，组织 {org}，项目 {len(r)} 个：' + '、'.join(f'{p.get("slug")}({p.get("id")})' for p in r[:30])]
        items = list(self._issues(limit=5))
        out.append('例：' + ('；'.join(f'{x.get("shortId")} {x.get("title", "")[:40]}（{x.get("count")} 次）' for x in items) or '没有符合条件的问题'))
        return '\n'.join(out)

    def _issues(self, limit=0):
        params = {'query': self.o('查询'), 'statsPeriod': f'{int(self.o("天数") or 14)}d', 'sort': 'freq', 'limit': 100,
                  'project': self._projects() or None, 'environment': self.o('环境') or None}
        params = {k: v for k, v in params.items() if v is not None}
        url, n = '', 0
        while True:
            _, h, r = self._get(f'/api/0/organizations/{self._org()}/issues/', params, url)
            for x in r or []:
                yield x
                n += 1
                if limit and n >= limit:
                    return
            nxt = re.search(r'<([^>]+)>;\s*rel="next";\s*results="true"', h.get('Link') or h.get('link') or '')
            if not nxt:
                return
            url = nxt.group(1)

    def _stack(self, iid):
        _, _, ev = self._get(f'/api/0/organizations/{self._org()}/issues/{iid}/events/latest/')
        vals = []
        for en in ev.get('entries') or []:
            if en.get('type') == 'exception':
                vals = (en.get('data') or {}).get('values') or []
        if not vals:
            return '', ''
        top = vals[-1]
        mech = top.get('mechanism') or {}
        frames = lambda v: list(reversed((v.get('stacktrace') or {}).get('frames') or []))     # Sentry 是调用先后顺序，崩溃点在最后
        if (mech.get('type') or '').lower() in ('signalhandler', 'minidump', 'native') or (mech.get('meta') or {}).get('signal'):
            sig = (mech.get('meta') or {}).get('signal') or {}
            sname = f'{sig.get("number", "")} ({sig.get("name") or top.get("type") or "SIG?"})'
            return native_stack(sname, [(f.get('instructionAddr'), f.get('package') or f.get('filename'), f.get('function')) for f in frames(top)]), 'Native崩溃'
        fr = lambda v: [((f.get('module') + '.' if f.get('module') else '') + (f.get('function') or '?'), f.get('filename'), f.get('lineNo')) for f in frames(v)]
        if 'ApplicationNotResponding' in (top.get('type') or '') or 'ANR' in (top.get('type') or ''):
            return anr_stack(fr(top), top.get('value') or ''), 'ANR'
        excs = [((v.get('module') + '.' if v.get('module') else '') + (v.get('type') or ''), v.get('value') or '', fr(v)) for v in reversed(vals)]
        return java_stack(excs), 'Java崩溃'

    def sync(self, state, ctx):
        got = state.setdefault('已取堆栈', {})
        n_detail = 0
        lim = int(self.o('上限') or 200)
        for x in self._issues(limit=lim):
            iid = str(x.get('id'))
            md = x.get('metadata') or {}
            item = {'外部ID': x.get('shortId') or iid, '标题': x.get('title') or '', '原因': f'{md.get("type") or ""}: {md.get("value") or ""}'.strip(': '),
                    '次数': x.get('count') or 1, '用户数': x.get('userCount') or 0, '首次': local_time(x.get('firstSeen')), '最近': local_time(x.get('lastSeen')),
                    '链接': x.get('permalink') or '', '状态': x.get('status') or '', '版本': '', '堆栈': None}
            if got.get(iid) != x.get('firstSeen') and n_detail < self.MAX_DETAIL:
                try:
                    item['堆栈'], kind = self._stack(iid)
                    item['类型'] = kind or 'Java崩溃'
                    got[iid] = x.get('firstSeen')
                    n_detail += 1
                except SourceError:
                    pass
            if item['堆栈'] is None and iid not in got:
                continue                     # 堆栈还没取到的新问题：下次再同步进来
            yield item
        state['同步'] = {'Sentry': f'{datetime.now():%Y-%m-%d %H:%M} 取了 {n_detail} 个新问题的堆栈'}
