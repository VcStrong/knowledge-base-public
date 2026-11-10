# From 大大王.DT
"""腾讯 Bugly 适配器（网页接口，非官方）。"""
import os
import re
from datetime import datetime
from urllib.parse import urlencode
from .base import SourceError, http, local_time
from .crash import native_stack, anr_stack, CrashSource


class BuglySource(CrashSource):
    """腾讯 Bugly。官方 OpenAPI（专业版）目前不开放崩溃列表，这里用的是网页版自己调的接口（非官方）：
    要把浏览器里登录后的 Cookie 和 x-token 存进基础信息，失效后（code 100006）重新复制。接口随时可能变，变了按报错调整「接口前缀」选项。"""
    adapter = 'Bugly'
    guess = ('bugly',)
    fields = '地址（空 = https://bugly.qq.com）、Cookie〔机密，浏览器登录后复制〕、x-token〔机密〕'
    options = [('AppID', 'Bugly 应用的 App ID（必填）', ''),
               ('平台ID', '1 = 安卓，2 = iOS', '1'),
               ('异常类型', '逗号隔开', 'Crash,Native,ExtensionCrash'),
               ('ANR类型', 'ANR / 卡顿在 Bugly 里的类型名（空 = 不同步 ANR）', 'ANR'),
               ('版本', '只看某个版本（空 = 全部）', ''),
               ('接口前缀', '网页接口路径前缀（Bugly 改版时调整）', '/v2'),
               ('上限', '最多同步多少个问题', '200')]

    @property
    def base(self):
        return (self.cred.get('地址', '网址', 'URL', 'url') or 'https://bugly.qq.com').rstrip('/')

    def _hdr(self):
        if not self.cred.has('Cookie'):
            raise SourceError(f'{self.cred.entry.get("编号")} 缺少「Cookie」字段')
        h = {'Cookie': self.cred.secret('Cookie'), 'x-csrf-token': 'undefined', 'Referer': self.base + '/v2/'}
        tf = next((n for n in ('x-token', 'X-Token', 'token') if self.cred.has(n)), '')
        if tf:
            h['x-token'] = self.cred.secret(tf)
        return h

    def _app(self):
        a = self.o('AppID')
        if not a:
            raise SourceError('Bugly 要填「AppID」选项')
        return a, self.o('平台ID') or '1'

    def _get(self, path, **params):
        url = self.base + self.o('接口前缀') + path + ('?' + urlencode({k: v for k, v in params.items() if v not in (None, '')}) if params else '')
        _, _, r = http('GET', url, self._hdr(), what='Bugly')
        code = str(r.get('code') if isinstance(r, dict) else '')
        if code == '100006':
            raise SourceError('Bugly 登录已失效（code 100006）：重新登录网页版，把 Cookie 和 x-token 更新到基础信息')
        if isinstance(r, dict) and r.get('status') not in (None, 200, '200') and code not in ('', '100000', '200'):
            raise SourceError(f'Bugly 接口 {path} 返回 {r.get("status")} / {code}：{str(r.get("msg") or r)[:200]}')
        return r

    def account(self):
        return ''

    def _list(self, types, limit):
        app, pid = self._app()
        start, n = 0, 0
        while True:
            r = self._get('/issueList', sortOrder='desc', sortField='uploadTime', appId=app, platformId=pid, version=self.o('版本'),
                          start=start, rows=50, exceptionTypeList=types, fsn=os.urandom(8).hex())
            ret = r.get('ret') or r.get('data') or {}
            its = ret.get('issueList') or []
            for x in its:
                yield x
                n += 1
                if n >= limit:
                    return
            start += len(its)
            if not its or start >= int(ret.get('numFound') or 0):
                return

    def _callstack(self, iid):
        app, pid = self._app()
        r = self._get(f'/lastCrashInfo/appId/{app}/platformId/{pid}/issues/{iid}/crashDataType/null', offsetTop=56)
        return ((r.get('data') or r.get('ret') or {}).get('callStack') or '').strip()

    def test(self):
        app, pid = self._app()
        its = list(self._list(self.o('异常类型'), 5))
        return f'✓ Bugly 网页接口可用（App {app}，平台 {pid}；非官方接口）\n例：' + (
            '；'.join(f'{x.get("issueId")} {x.get("exceptionName")}（{x.get("count")} 次）' for x in its) or '没有问题')

    @staticmethod
    def _as_stack(name, msg, key):
        lines = [l.strip() for l in (key or '').splitlines() if l.strip()]
        if lines and re.match(r'^#\d+\s+pc', lines[0]) or re.search(r'SIG[A-Z]+', name or ''):
            return native_stack(name, [(m.group(1), m.group(2), m.group(3)) for m in
                                       (re.match(r'^#\d+\s+pc\s+(\S+)\s+(\S+)\s*(?:\((.*)\))?', l) for l in lines) if m]), 'Native崩溃'
        fr = [l if l.startswith('at ') else f'at {l}' for l in lines if not l.startswith(('Caused by', name or '\0'))]
        return '\n'.join([f'{name}: {msg}' if msg else name] + ['\t' + f for f in fr]), 'Java崩溃'

    def sync(self, state, ctx):
        got = state.setdefault('已取堆栈', {})
        app, pid = self._app()
        lim = int(self.o('上限') or 200)
        n_detail = 0
        kinds = [(self.o('异常类型'), False)] + ([(self.o('ANR类型'), True)] if self.o('ANR类型') else [])
        for types, is_anr in kinds:
            try:
                its = list(self._list(types, lim))
            except SourceError:
                if is_anr:
                    continue                 # ANR 类型名猜错了不影响崩溃
                raise
            for x in its:
                iid = str(x.get('issueId'))
                name, msg = x.get('exceptionName') or '', x.get('exceptionMessage') or ''
                item = {'外部ID': iid, '标题': f'{name}: {msg}'[:120] if msg else name, '原因': msg[:200], '次数': x.get('count') or 1,
                        '用户数': x.get('imeiCount') or 0, '版本': x.get('version') or '', '最近': local_time(x.get('lastestUploadTime')),
                        '链接': f'{self.base}/v2/crash-reporting/{"blocks" if is_anr else "crashes"}/{app}/{iid}?pid={pid}',
                        '状态': str(x.get('status') or ''), '堆栈': None}
                if iid not in got:
                    stack = x.get('keyStack') or ''
                    if n_detail < self.MAX_DETAIL:
                        try:
                            stack = self._callstack(iid) or stack
                            n_detail += 1
                        except SourceError:
                            pass
                    if is_anr:
                        fr = [re.match(r'^(?:at\s+)?([\w$.<>-]+)(?:\(([^:()]*)(?::(\d+))?\))?', l.strip()) for l in stack.splitlines() if l.strip()]
                        item['堆栈'], item['类型'] = anr_stack([m.groups() for m in fr if m], msg), 'ANR'
                    else:
                        item['堆栈'], item['类型'] = self._as_stack(name, msg, stack)
                    got[iid] = 1
                yield item
        state['同步'] = {'Bugly': f'{datetime.now():%Y-%m-%d %H:%M} 取了 {n_detail} 个新问题的堆栈'}
