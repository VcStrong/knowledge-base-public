# From 大大王.DT
"""禅道（REST /api.php/v1）适配器。"""
import html
import json
import os
import re
import time
from datetime import datetime
from urllib.parse import urljoin
from kblib.bugs.adapters.base import (
    Source,
    SourceError,
    bracket_sections,
    brief,
    entry,
    html_text,
    http,
    jenkins,
    local_time,
    online,
    platform_of,
    platform_tags,
    safe_file,
    save_download,
)


# ---------------------------------------------------------------- 禅道（REST /api.php/v1，18 以上自带）

ZT_STATUS = {'active': '激活', 'resolved': '已解决', 'closed': '已关闭'}


class ZentaoSource(Source):
    adapter = '禅道'
    guess = ('禅道', 'zentao')
    fields = '地址（如 http://bug.example.com/zentao）、用户名、密码〔机密〕'
    id_pattern = r'\d+'
    _clients = {}

    def key(self, num):
        return str(num) if self.id == '禅道' else super().key(num)     # 最早只接禅道：编号不加前缀，老数据不用迁移

    def num(self, key):
        return str(key) if self.id == '禅道' else super().num(key)

    @property
    def zt(self):
        from kblib.bugs.adapters import zentao_api as zentao
        url = self.cred.get('地址', '网址', 'URL', 'url')
        user = self.cred.get('用户名', '账号', '帐号')
        if not url or not user or not self.cred.has('密码'):
            raise SourceError(f'{self.cred.entry.get("编号")} {self.cred.entry.get("名称")} 缺少 地址 / 用户名 / 密码 字段')
        url = re.sub(r'/(index\.php|my)?[^/]*\.html?$|/+$', '', url.strip())
        k = (url, user)
        if k not in self._clients:
            self._clients.clear()
            self._clients[k] = zentao.Zentao(url, user, self.cred.secret('密码'))
        return self._clients[k]

    def _call(self, fn, *a, **kw):
        from kblib.bugs.adapters import zentao_api as zentao
        try:
            return fn(*a, **kw)
        except zentao.ZentaoError as e:
            raise SourceError(str(e))

    def account(self):
        return self.zt.account

    def test(self):
        from kblib.bugs.adapters import zentao_api as zentao
        zt = self.zt
        out = []
        self._call(zt.login)
        out.append(f'✓ 已登录 {zt.base}（账号 {zt.account}）')
        prods = self._call(zt.products)
        out.append(f'产品 {len(prods)} 个：' + '；'.join(f'{p.get("id")} {p.get("name")}' for p in prods[:60]))
        for path, key in (('projects', 'projects'), ('executions', 'executions')):
            try:
                r = zt.get(path, limit=5)
                items = r.get(key) or []
                out.append(f'{path}：共 {r.get("total")}，例：' + '；'.join(f'{x.get("id")} {x.get("name")}' for x in items))
            except zentao.ZentaoError as e:
                out.append(f'{path}：{e}')
        sample = None
        for p in prods:
            try:
                r = zt.get(f'products/{p["id"]}/bugs', limit=5, status='all')
            except zentao.ZentaoError as e:
                out.append(f'产品 {p["id"]} 的 Bug 列表：{e}')
                continue
            bugs = r.get('bugs') or []
            if bugs:
                out.append(f'\n产品「{p.get("name")}」Bug 列表：共 {r.get("total")}，列表字段：{", ".join(sorted(bugs[0]))}')
                for b in bugs:
                    out.append('  ' + json.dumps({k: b.get(k) for k in ('id', 'title', 'status', 'severity', 'type', 'os', 'module', 'project',
                                                                       'execution', 'openedBuild', 'assignedTo', 'lastEditedDate')}, ensure_ascii=False)[:600])
                sample = bugs[0]
                break
        if sample:
            b = self._call(zt.bug, sample['id'])
            out.append(f'\nBug {sample["id"]} 详情字段：{", ".join(sorted(b))}')
            out.append(f'  正文前 300 字：{html_text(b.get("steps") or "")[:300]}')
            out.append(f'  附件 {len(b.get("files") or [])} 个；历史 {len(b.get("actions") or [])} 条')
        return '\n'.join(out)

    # ---- 条目
    @staticmethod
    def _user(u):
        return (u.get('realname') or u.get('account') or '') if isinstance(u, dict) else (u or '')

    @staticmethod
    def _acct(u):
        return (u.get('account') or '') if isinstance(u, dict) else (u or '')

    @staticmethod
    def _text(steps):
        return bracket_sections(html_text(steps or ''))

    def _names(self, names, b):
        """补齐产品 / 项目 / 执行的名称（缓存在来源状态里）。"""
        from kblib.bugs.adapters import zentao_api as zentao
        for kind, path, fld in (('产品', 'products', 'product'), ('项目', 'projects', 'project'), ('执行', 'executions', 'execution')):
            i = str(b.get(fld) or '0')
            k = f'{kind}/{i}'
            if i != '0' and k not in names:
                try:
                    names[k] = (self.zt.get(f'{path}/{i}') or {}).get('name') or ''
                except zentao.ZentaoError:
                    names[k] = ''
        return names

    def _entry(self, b, names):
        text = self._text(b.get('steps'))
        jurl, job = jenkins(text)
        g = lambda k: names.get(k) or ''
        prod, proj, exe = g(f'产品/{b.get("product")}'), g(f'项目/{b.get("project")}'), g(f'执行/{b.get("execution")}')
        ob = b.get('openedBuild')
        return entry(self, 原编号=str(b['id']), 链接=self.zt.bug_url(b['id']), 标题=b.get('title') or '', 简介=brief(text, b.get('title') or ''),
                     状态=ZT_STATUS.get(b.get('status'), b.get('status') or ''), 严重=str(b.get('severity') or ''), 优先级=str(b.get('pri') or ''),
                     产品=prod, 产品ID=str(b.get('product') or ''), 项目=proj, 项目ID=str(b.get('project') or '0'), 执行=exe, 执行ID=str(b.get('execution') or '0'),
                     版本=','.join(x.get('id', '') if isinstance(x, dict) else str(x) for x in ob) if isinstance(ob, list) else str(ob or ''),
                     平台=platform_of(prod, str(b.get('os') or ''), proj, exe, job, b.get('title') or ''), 线上=online(text), Jenkins=jurl, Jenkins任务=job,
                     指派给=self._user(b.get('assignedTo')), 指派账号=self._acct(b.get('assignedTo')) if isinstance(b.get('assignedTo'), dict) else '',
                     解决人=self._user(b.get('resolvedBy')), 解决账号=self._acct(b.get('resolvedBy')),
                     创建人=self._user(b.get('openedBy')), 创建时间=local_time(b.get('openedDate')),
                     修改时间=local_time(b.get('lastEditedDate') or b.get('openedDate')), 修改原值=str(b.get('lastEditedDate') or b.get('openedDate') or ''),
                     分组=[{'类型': '执行', 'ID': str(b.get('execution') or '0'), '名': exe, '强': 1},
                           {'类型': '项目', 'ID': str(b.get('project') or '0'), '名': proj, '强': 0}])

    def _products(self):
        prods = self._call(self.zt.products)
        pf = self.conf.get('平台') or '安卓'
        if self.conf.get('产品'):
            ids = {str(x) for x in self.conf['产品']}
            return [p for p in prods if str(p['id']) in ids], prods
        if pf == '全部':
            return prods, prods
        sel = [p for p in prods if pf in platform_tags(p.get('name')) or not platform_tags(p.get('name'))]   # 本平台的 + 没分平台的混合产品
        return sel, prods

    def sync(self, state, ctx):
        from kblib.bugs.adapters import zentao_api as zentao
        zt = self.zt
        names = state.setdefault('名称', {})
        cur = state.setdefault('游标', {})
        done = state.setdefault('同步', {})
        sel, allp = self._products()
        for p in allp:
            names[f'产品/{p["id"]}'] = p.get('name') or ''
        try:
            for x in zt.pages('executions', 'executions', limit=500, max_pages=5):
                names[f'执行/{x["id"]}'] = x.get('name') or ''
        except zentao.ZentaoError:
            pass
        first_cut = datetime.fromtimestamp(time.time() - ctx.get('首次天数', 30) * 86400).strftime('%Y-%m-%dT%H:%M:%S')
        full = ctx.get('全量')
        known = ctx.get('已有') or {}       # 键 → 修改原值：没变的不用再取名称、建条目

        def one(b):
            if str(b.get('deleted')) in ('1', 'true', 'True'):
                return {'删除': self.key(b['id'])}
            t = str(b.get('lastEditedDate') or b.get('openedDate') or '')
            if not full and known.get(self.key(b['id'])) == t:
                return None
            self._names(names, b)
            return self._entry(b, names)

        for p in sel:
            pid = str(p['id'])
            c = {} if full else (cur.get(pid) or {})
            if isinstance(c, str):
                c = {}
            path, seen = f'products/{pid}/bugs', 0
            try:
                if not c:                                   # 第一次：未关闭的全部 + 最近 N 天改过的
                    for b in zt.pages(path, 'bugs', limit=100, max_pages=100, status='unclosed'):
                        seen += 1
                        e = one(b)
                        if e:
                            yield e
                    since = first_cut
                else:
                    since = c.get('修改', '')
                top_t, top_id = c.get('修改', ''), int(c.get('编号') or 0)
                # 改过的：按修改时间倒序，翻到 since 之前就停（从没改过的新 Bug 修改时间为空，排在最后，下面按编号补）
                for b in zt.pages(path, 'bugs', limit=100, max_pages=100, status='all', order='lastEditedDate_desc',
                                  stop=lambda b: not b.get('lastEditedDate') or str(b['lastEditedDate'])[:19] < since[:19]):
                    seen += 1
                    top_t = max(top_t, str(b['lastEditedDate']))
                    e = one(b)
                    if e:
                        yield e
                # 新建的：按编号倒序，翻到上次见过的最大编号就停（第一次：翻到 N 天前创建的）
                # 停止条件要用上次的编号（old_id）：top_id 在循环里会变大，拿它判断会只取到最新一条就停，两次同步之间新建的其他 Bug 全漏
                old_id = top_id
                for b in zt.pages(path, 'bugs', limit=100, max_pages=50, status='all', order='id_desc',
                                  stop=lambda b: int(b['id']) <= old_id if old_id else str(b.get('openedDate') or '')[:19] < first_cut[:19]):
                    seen += 1
                    top_id = max(top_id, int(b['id']))
                    e = one(b)
                    if e:
                        yield e
                cur[pid] = {'修改': top_t or since, '编号': top_id}
                done[pid] = f'{datetime.now():%Y-%m-%d %H:%M} 产品「{p.get("name")}」检查 {seen} 条'
            except zentao.ZentaoError as ex:
                done[pid] = f'产品「{p.get("name")}」失败：{ex}'

    def get(self, key, download=True, names=None):
        zt = self.zt
        b = self._call(zt.bug, self.num(key))
        if not isinstance(b, dict) or not b.get('id'):
            raise SourceError(f'禅道里找不到 Bug {key}')
        names = names if names is not None else {}
        for k, f, i in (('产品', 'productName', 'product'), ('项目', 'projectName', 'project'), ('执行', 'executionName', 'execution')):
            fid = str(b.get(i) or '0')
            if fid != '0' and b.get(f):
                names[f'{k}/{fid}'] = b[f]
        self._names(names, b)
        e = self._entry(b, names)
        info = [f'类型：{b.get("type") or ""}　模块：{b.get("moduleTitle") or ""}　产品：{e["产品"]}　项目：{e["项目"] or "无"}　执行：{e["执行"] or "无"}',
                f'关联需求：{b["storyTitle"]}' if b.get('storyTitle') else '']
        comments = [(local_time(a.get('date')), self._user(a.get('actor')), a.get('action', ''), html_text(a['comment']))
                    for a in (b.get('actions') or []) if (a.get('comment') or '').strip()]
        files = []
        imgs = re.findall(r'<img[^>]+src="([^"]+)"', b.get('steps') or '')
        fl = b.get('files') or []
        if isinstance(fl, dict):
            fl = list(fl.values())
        if download and (fl or imgs):
            tmp = self.tmpdir(key)
            for i, f in enumerate(fl):
                nm = safe_file(f.get('title') or f'附件{i + 1}') + ('' if '.' in (f.get('title') or '') else f'.{f.get("extension") or "bin"}')
                files.append(self._download(zt.file_url(f.get('id')), tmp / nm))
            for i, src in enumerate(imgs):
                src = html.unescape(src)
                mm = re.search(r'(?:fileID=|file-read-)(\d+)', src)
                url = zt.file_url(mm.group(1)) if mm else (src if src.startswith('http') else urljoin(zt.base + '/', src))
                files.append(self._download(url, tmp / f'正文图{i + 1}.png'))
        return {'条目': e, '正文': html_text(b.get('steps') or ''), '信息': info, '评论': comments, '附件': files}

    def _download(self, url, dest):
        zt = self.zt
        try:
            if not zt.token:
                zt.login()
            _, h, body = http('GET', url, {'Token': zt.token}, raw=True, what='禅道')
            return save_download(body, h.get('Content-Type', ''), dest, url)
        except Exception as ex:
            return f'{dest.name}：下载失败（{ex}），原地址 {url}'
