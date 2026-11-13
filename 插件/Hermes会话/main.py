"""知识库工具插件：按会话编号拉取 Hermes Agent 的对话。
账号由知识库通过 KB_PLUGIN_BASE 传入（基础信息条目），这里不存任何密码。
标准输出给 AI 看：会话信息 + 对话（用户 / 助手全文，工具调用和结果只留摘要）；完整内容另存系统临时目录。"""
import json, math, os, re, sys, tempfile, time, urllib.parse, urllib.request, http.cookiejar

MAX_OUT = 80000          # 标准输出上限（字符），超了先压缩工具结果，再截中间的助手消息
TOOL_RES = 400           # 默认每个工具结果保留的字符
TOOL_ARG = 240


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(2)


def conf():
    c = json.loads(os.environ.get('KB_PLUGIN_CONFIG') or '{}')
    b = (json.loads(os.environ.get('KB_PLUGIN_BASE') or '{}')).get('账号') or {}
    pick = lambda *ks: next((b[k] for k in ks if b.get(k)), '')
    base = (c.get('地址') or pick('地址', '网址', 'URL', 'url')).strip().rstrip('/')
    user, pw = pick('账号', '用户名', 'username', '用户'), pick('密码', 'password')
    if not base or not user or not pw:
        die('Hermes 插件没配好：在知识库「⚙ 设置 → 插件 → Hermes 会话 → 配置」选存 Hermes 账号的基础信息条目（要有 账号、密码、地址）')
    if urllib.parse.urlparse(base).path not in ('', '/'):
        base = '{0.scheme}://{0.netloc}'.format(urllib.parse.urlparse(base))
    return base, user, pw


class Hermes:
    def __init__(self, base, user, pw):
        self.base = base
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        try:
            self.req('/auth/password-login', {'provider': 'basic', 'username': user, 'password': pw, 'next': ''})
        except urllib.error.HTTPError as e:
            die(f'Hermes 登录失败（{e.code}）：' + ('账号或密码不对' if e.code == 401 else '请稍后再试'))

    def req(self, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.base + path, data, {'Content-Type': 'application/json'} if data else {})
        try:
            with self.op.open(r, timeout=60) as f:
                return json.loads(f.read().decode('utf-8'))
        except urllib.error.URLError as e:
            if isinstance(e, urllib.error.HTTPError):
                raise
            die(f'连不上 Hermes（{self.base}）：{e.reason}')


def sid_of(arg):
    m = re.search(r'resume=([\w.-]+)', arg)
    s = urllib.parse.unquote(m.group(1)) if m else arg.strip()
    if not re.fullmatch(r'[\w.-]{6,}', s):
        die(f'看不出会话编号：{arg}（要 resume=20261106_101910_703257 这样的）')
    return s


def ts(x):
    try:
        return time.strftime('%Y-%m-%d %H:%M', time.localtime(float(x)))
    except (TypeError, ValueError):
        return ''


def calls(m):
    tc = m.get('tool_calls')
    if isinstance(tc, str):
        try:
            tc = json.loads(tc)
        except ValueError:
            return []
    return [c.get('function') or {} for c in tc or [] if isinstance(c, dict)]


def short(s, n):
    s = re.sub(r'\s+', ' ', str(s or '')).strip()
    return s if len(s) <= n else s[:n] + f'…（共 {len(s)} 字）'


def render(meta, ms, tool_res, full=False):
    who = ''
    try:
        o = json.loads(meta.get('origin_json') or 'null') or {}
        who = '、'.join(x for x in (o.get('user_name'), o.get('chat_name')) if x)
    except ValueError:
        pass
    out = [f'## {meta.get("title") or "（无标题）"}',
           f'- 会话：{meta["id"]}（来源 {meta.get("source")}' + (f'，提问人 {who}' if who else '') + '）',
           f'- 时间：{ts(meta.get("started_at"))} 开始，最近活动 {ts(meta.get("last_activity_at") or meta.get("ended_at"))}'
           + ('，进行中' if not meta.get('ended_at') else ''),
           f'- 消息 {meta.get("message_count")} 条，工具调用 {meta.get("tool_call_count")} 次；模型 {meta.get("model")}']
    if meta.get('parent_session_id'):
        out.append(f'- 接着上一个会话：{meta["parent_session_id"]}（上下文压缩前的部分）')
    out.append('')
    for m in ms:
        role, c = m.get('role'), (m.get('content') or '').strip()
        if role == 'user':
            if c.startswith('[CONTEXT COMPACTION'):
                out.append(f'### [压缩前的摘要] {ts(m.get("timestamp"))}\n{c if full else short(c, 3000)}\n')
            else:
                out.append(f'### 👤 用户 {ts(m.get("timestamp"))}\n{c}\n')
        elif role == 'assistant':
            if c:
                out.append(f'### 🤖 Hermes {ts(m.get("timestamp"))}\n{c}\n')
            for f in calls(m):
                out.append(f'- 🔧 {f.get("name")}：{short(f.get("arguments"), 100000 if full else TOOL_ARG)}')
        elif role == 'tool' and tool_res:
            out.append(f'  - ↳ {m.get("tool_name") or "结果"}：{c if full else short(c, tool_res)}')
    return '\n'.join(out)


def _items(h):
    out = []
    for off in range(0, 5000, 100):
        r = h.req(f'/api/sessions?limit=100&offset={off}')
        ss = r.get('sessions') or []
        out += ss
        if len(ss) < 100:
            break
    return out


def _cand(x, score=0.0, why=''):
    who = ''
    try:
        o = json.loads(x.get('origin_json') or 'null') or {}
        who = o.get('user_name') or ''
    except ValueError:
        pass
    return {'编号': x['id'], '标题': x.get('title') or '（无标题）', '摘要': re.sub(r'\s+', ' ', x.get('preview') or '')[:160],
            '来源': x.get('source') or '', '提问人': who, '时间': ts(x.get('last_activity_at') or x.get('started_at')),
            '消息数': x.get('message_count') or 0, '匹配': why, '分数': round(score, 3)}


def _grams(t):
    """中文按二字组（英文、数字另按整词算）。"""
    out = set()
    for run in re.findall(r'[\u4e00-\u9fff]+', t):
        out |= {run[i:i + 2] for i in range(len(run) - 1)} if len(run) > 1 else {run}
    return out


def _words(t):
    return {w.lower() for w in re.findall(r'[A-Za-z_][\w.]{2,}|\d{3,}', t)}


def resolve(h, text):
    """输入 → 候选会话：带 resume= / 会话编号就精确取；否则按内容模糊找。
    在所有会话的标题和开头的提问里比对：中文按二字组、英文和数字按整词，越少见的词权重越高（IDF）；
    英文词再用 Hermes 的全文检索查对话正文（它对中文不分词，中文只能比标题和开头）。"""
    text = text.strip()
    ids = re.findall(r'resume=([\w.-]+)', text) or ([text] if re.fullmatch(r'\d{8}_\d{6}_[0-9a-f]+', text) else [])
    if ids:
        out = []
        for sid in ids:
            try:
                out.append(_cand(h.req(f'/api/sessions/{urllib.parse.quote(sid)}'), 1, '会话编号'))
            except urllib.error.HTTPError:
                out.append({'编号': sid, '标题': '（Hermes 上没有这个会话）', '错误': True})
        return out
    qg, qw = _grams(text), _words(text)
    if not qg and not qw:
        return []
    ss = _items(h)
    n = len(ss) or 1
    docs = {x['id']: (_grams((x.get('title') or '') + ' ' + (x.get('preview') or '')),
                      _words((x.get('title') or '') + ' ' + (x.get('preview') or '')),
                      _grams(x.get('title') or '') | _words(x.get('title') or '')) for x in ss}
    df = {}
    for g, w, _ in docs.values():
        for k in g | w:
            df[k] = df.get(k, 0) + 1
    body = {}                                   # 英文词在对话正文里出现的会话（Hermes 全文检索）
    for w in list(qw)[:8]:
        try:
            hit = {r.get('session_id') or r.get('id') for r in
                   h.req('/api/sessions/search?' + urllib.parse.urlencode({'q': w})).get('results') or []}
        except urllib.error.HTTPError:
            hit = set()
        body[w] = hit
        df[w] = max(df.get(w, 0), len(hit))
    idf = lambda k: math.log((n + 1) / (df.get(k, 0) + 1)) + 0.1
    total = sum(idf(k) for k in qg | qw) or 1
    out = []
    for sid, (g, w, title) in docs.items():
        got, why = 0.0, []
        mg = qg & g
        mw = {k for k in qw if k in w or sid in body.get(k, ())}
        got = sum(idf(k) for k in mg | mw) + 0.5 * sum(idf(k) for k in (qg | qw) & title)
        if not got:
            continue
        if mg:
            why.append('标题 / 开头的提问相近')
        if mw:
            why.append('提到 ' + '、'.join(sorted(mw)))
        out.append((got / total, sid, '；'.join(why)))
    out.sort(reverse=True)
    by = {x['id']: x for x in ss}
    best = out[0][0] if out else 0
    return [_cand(by[sid], sc, why) for sc, sid, why in out[:15] if sc >= max(0.12, best * 0.35)]


def content(h, sid):
    """给网页展示的原始内容：按会话顺序列出消息，工具调用和结果配对。"""
    chain = h.req(f'/api/sessions/{urllib.parse.quote(sid)}/latest-descendant').get('path') or [sid]
    out = {'编号': sid, '会话': []}
    for x in chain:
        meta = h.req(f'/api/sessions/{urllib.parse.quote(x)}')
        ms = h.req(f'/api/sessions/{urllib.parse.quote(x)}/messages').get('messages') or []
        res = {m.get('tool_call_id'): m for m in ms if m.get('role') == 'tool'}
        items = []
        for m in ms:
            role, c = m.get('role'), (m.get('content') or '').strip()
            if role == 'user':
                items.append({'角色': '摘要' if c.startswith('[CONTEXT COMPACTION') else '用户', '时间': ts(m.get('timestamp')), '内容': c})
            elif role == 'assistant':
                tools = []
                tc = m.get('tool_calls')
                if isinstance(tc, str):
                    try:
                        tc = json.loads(tc)
                    except ValueError:
                        tc = []
                for t in tc or []:
                    f = t.get('function') or {}
                    r = res.get(t.get('id')) or res.get(t.get('call_id')) or {}
                    rc = r.get('content') or ''
                    tools.append({'工具': f.get('name') or '', '参数': short(f.get('arguments'), 600),
                                  '结果': rc[:3000] + (f'…（共 {len(rc)} 字）' if len(rc) > 3000 else '')})
                if c or tools:
                    items.append({'角色': 'Hermes', '时间': ts(m.get('timestamp')), '内容': c, '工具': tools})
        c = _cand(meta)
        c.update(地址=f'{h.base}/chat?resume={urllib.parse.quote(x)}', 消息=items)
        out['会话'].append(c)
    out['标题'] = out['会话'][0]['标题']
    out['地址'] = out['会话'][-1]['地址']
    return out


def main():
    args = sys.argv[1:]
    if args and args[0] in ('resolve', 'content'):          # 知识库网页入口用：输出 JSON
        if len(args) < 2:
            die(f'{args[0]} 要带参数')
        h = Hermes(*conf())
        r = resolve(h, ' '.join(args[1:])) if args[0] == 'resolve' else content(h, sid_of(args[1]))
        print(json.dumps(r, ensure_ascii=False))
        return
    full = any(a.lower() in ('full', '--full', '完整') for a in args)
    ids = [sid_of(a) for a in args if a.lower() not in ('full', '--full', '完整')]
    if not ids:
        die('要给会话编号：resume=20261106_101910_703257')
    base, user, pw = conf()
    h = Hermes(base, user, pw)
    tmp = os.path.join(tempfile.gettempdir(), 'kb-hermes')
    os.makedirs(tmp, exist_ok=True)
    parts = []
    for sid in ids:
        try:
            chain = h.req(f'/api/sessions/{urllib.parse.quote(sid)}/latest-descendant').get('path') or [sid]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                die(f'Hermes 上没有这个会话：{sid}')
            chain = [sid]
        sess = []
        for x in chain:                         # 上下文压缩后会接着开新会话：一起拉
            meta = h.req(f'/api/sessions/{urllib.parse.quote(x)}')
            ms = h.req(f'/api/sessions/{urllib.parse.quote(x)}/messages').get('messages') or []
            sess.append((meta, ms))
        whole = '\n\n'.join(render(m, ms, 10 ** 9, full=True) for m, ms in sess)
        path = os.path.join(tmp, f'{sid}.md')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(whole)
        if full:
            text = whole
        else:
            text = ''
            for lim in (TOOL_RES, 150, 0):      # 太长：工具结果越留越少
                text = '\n\n'.join(render(m, ms, lim) for m, ms in sess)
                if len(text) <= MAX_OUT:
                    break
            if len(text) > MAX_OUT:
                text = text[:MAX_OUT // 2] + f'\n\n…（中间省略 {len(text) - MAX_OUT} 字，完整内容见 {path}）…\n\n' + text[-MAX_OUT // 2:]
        link = f'{base}/chat?resume={urllib.parse.quote(chain[-1])}'
        parts.append(f'# Hermes 会话 {sid}\n地址：{link}\n完整内容（含全部工具结果）：{path}\n'
                     + (f'会话后来接续到：{" → ".join(chain[1:])}\n' if len(chain) > 1 else '') + '\n' + text)
    print('\n\n---\n\n'.join(parts))
    print('\n---\n以上是 Hermes 上的实时内容（不是知识库存的）。推动解决：先 kb_search 看有没有相关的期 / 事项；'
          '没有就用 kb_create_task 建事项，用 kb_add_note 记下会话编号、地址和一句话问题，不要把整段对话存进知识库；之后处理时重新调用本插件拉最新内容。')


if __name__ == '__main__':
    main()
