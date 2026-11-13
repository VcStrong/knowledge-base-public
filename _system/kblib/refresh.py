# From 大大王.DT
"""来源刷新：按登记的网址重新抓取、对比。"""
import re
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from .common import DEV_OK, KBError, PROTO_DIR, ROOT, now, read_text
from .periods import load_meta, log, period_dir, period_names, save_meta
from .flows import flow_text
from .engines import engine_popen, role_engine
from .devsession import DEV_DIR, _alive, _dev_result, _notify, _take_chat, session_flow
from .urlimport import SRC_DIR, _fetch, _save_snapshot, import_design, import_url


CHANGE_DIR = '变更'          # 来源快照/变更/：每次原文变化的差异
REFRESH_STATUSES = ('收集中', '已批准开发', '开发中')   # 自动检查只管这些状态的期
_UPD = {}                    # 期名 -> 「Claude 更新条目」后台进程


def _fingerprint(pg):
    import hashlib
    h = hashlib.sha256((pg.get('md') or '').encode())
    for e in pg.get('embedded') or []:
        h.update(str(e[2]).encode())
    return h.hexdigest()[:16]


def _doc_body(text):
    """去掉文档 / 快照顶部的标题和「> 」元信息，只留正文。"""
    lines = text.splitlines()
    i = 1 if lines and lines[0].startswith('# ') else 0
    while i < len(lines) and (not lines[i].strip() or lines[i].startswith('> ')):
        i += 1
    return '\n'.join(lines[i:]).strip()


def _norm(text):
    # 内嵌图片的引用路径导入时会改写，比较时统一成「图N」
    text = re.sub(r'\]\(嵌入图片(\d+)\)', lambda x: f'](图{int(x.group(1))})', text)
    text = re.sub(r'\]\([^)]*-图(\d+)\.\w+\)', lambda x: f'](图{int(x.group(1))})', text)
    return '\n'.join(x.rstrip() for x in text.strip().splitlines())


def _src_params(d, s):
    """重新导入要用的参数；老来源没存的，从登记的文件推出来。"""
    p = dict(s.get('导入参数') or {})
    files = s.get('文件') or []
    if files:
        p.setdefault('分类', files[0].split('/')[0])
        p.setdefault('文件名', Path(files[0]).name)
        p.setdefault('附件', (['embedded'] if any(f'/{PROTO_DIR}/' in f for f in files) else [])
                     + [Path(f).name for f in files[1:] if f'/{PROTO_DIR}/' not in f])
    if '整页' not in p:
        doc, snap = d / files[0] if files else None, d / (s.get('快照') or '_')
        a = _doc_body(read_text(doc)) if doc and doc.exists() else ''
        b = _doc_body(read_text(snap)) if snap.is_file() else ''
        p['整页'] = bool(b) and len(a) >= 0.8 * len(b)
    return p


def _item_hit(old, new, doc):
    """条目内容是否落在原文变化的地方。找不到条目位置时按「受影响」处理。"""
    import difflib
    ol = old.splitlines()
    want = {x.strip() for x in doc.splitlines() if len(x.strip()) >= 6}
    pos = [i for i, x in enumerate(ol) if x.strip() in want]
    if not want or len(pos) < 0.3 * len(want):
        return True
    lo, hi = min(pos) - 3, max(pos) + 3
    for tag, i1, i2, _, _ in difflib.SequenceMatcher(None, ol, new.splitlines(), autojunk=False).get_opcodes():
        if tag != 'equal' and i1 <= hi and i2 >= lo:
            return True
    return False


def _save_change(d, s, old, new, why):
    import difflib
    cd = d / SRC_DIR / CHANGE_DIR
    cd.mkdir(parents=True, exist_ok=True)
    f = cd / f'{s["编号"]}-{datetime.now():%Y%m%d-%H%M%S}.md'
    n = 2
    while f.exists():
        f = cd / f'{s["编号"]}-{datetime.now():%Y%m%d-%H%M%S}-{n}.md'
        n += 1
    diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(), '旧版', '新版', n=2, lineterm=''))
    add = sum(1 for x in diff if x.startswith('+') and not x.startswith('+++'))
    rm = sum(1 for x in diff if x.startswith('-') and not x.startswith('---'))
    body = diff[:1500] + (['…（差异太长，已截断）'] if len(diff) > 1500 else [])
    f.write_text(f'# {s["编号"]}《{s["标题"]}》{s.get("条目") or ""} 原文变化\n\n> 来源：{s["地址"]}\n> 发现时间：{now()}\n'
                 f'> {why}\n> 新增 {add} 行，删除 {rm} 行\n\n```diff\n' + '\n'.join(body) + '\n```\n', 'utf-8')
    return f, f'+{add} / -{rm} 行'


def _notice(d, text):
    """给正在开发这一期的会话留话：下次它调用 kb_log / kb_wait_answer / kb_dev_package 时会看到。"""
    m = load_meta(d)
    if m.get('状态') in DEV_OK or m.get('开发会话'):   # 暂停中的也留着，继续开发时会看到
        m.setdefault('变更通知', []).append(f'[{now()}] {text}')
        save_meta(d, m)


def take_notices(period):
    try:
        d = period_dir(period)
    except KBError:
        return ''
    m = load_meta(d)
    chat = _take_chat(d, m)
    ns = m.pop('变更通知', None)
    if not ns:
        if chat:
            save_meta(d, m)
        return chat
    save_meta(d, m)
    return chat + ('\n\n【需求来源有更新】（含链接更正）\n' + '\n'.join(f'- {x}' for x in ns)
            + '\n请 kb_read 差异文件，评估对已完成 / 进行中任务的影响：'
            + (flow_text(session_flow(m), '需求变更提示', 期名=d.name, 文档目录=m.get('SDD目录') or '')
               or '先 kb_dev_prepare 同步资料副本，需要取舍时用 kb_ask 确认，并 kb_log 记录') + '。')


def _refresh_one(d, s):
    """返回 (结果, 说明)。结果：无变化 / 已更新 / 条目待更新 / 跳过 / 失败。"""
    f = _fetch()
    url, sid = s['地址'], s['编号']
    if s.get('类型') == '设计稿':
        if 'figma.com' not in (urlparse(url).hostname or ''):
            return '跳过', '蓝湖没有开放接口，不能自动刷新；请在蓝湖导出画板后拖进网页「设计图」'
        try:
            ver, at = f.figma_version(url)
        except f.FetchError as e:
            return '失败', str(e)
        if ver and str(ver) == str(s.get('页面版本')):
            return '无变化', f'Figma 版本 {ver}'
        old = s.get('页面版本')
        import_design(d.name, url, s.get('条目', ''), s.get('简介', ''))
        return '已更新', f'Figma 版本 {old} → {ver}（{at}），画板和设计规格已重新导出'
    f.drop_cache(url)
    try:
        pg = f.get_page(url)
    except f.FetchError as e:
        return '失败', str(e)
    fp = _fingerprint(pg)
    if s.get('指纹'):
        same = fp == s['指纹']
    elif pg.get('version') and s.get('页面版本'):
        same = str(pg['version']) == str(s['页面版本'])
    else:
        snap = d / (s.get('快照') or '_')
        same = snap.is_file() and _norm(_doc_body(read_text(snap))) == _norm(pg['md'])
    if same:
        if not s.get('指纹'):
            _set_src(d, sid, 指纹=fp)
        return '无变化', (f'页面版本 v{pg["version"]}' if pg.get('version') else '内容一致')
    snap = d / (s.get('快照') or '_')
    old_md = _norm(_doc_body(read_text(snap))) if snap.is_file() else ''
    ver = (f'v{s.get("页面版本")} → v{pg["version"]}' if pg.get('version') else f'最后修改 {pg.get("updated_at") or "未知"}')
    p = _src_params(d, s)
    if not p['整页']:
        doc = d / s['文件'][0] if s.get('文件') else None
        doc_text = _doc_body(read_text(doc)) if doc and doc.exists() else ''
        if old_md and doc_text and not _item_hit(old_md, _norm(pg['md']), _norm(doc_text)):
            chg, stat = _save_change(d, s, old_md, _norm(pg['md']), f'页面 {ver}；改动不在条目「{s.get("条目")}」范围内')
            _save_snapshot(d, pg)
            _set_src(d, sid, 指纹=fp, 页面版本=pg.get('version'), 抓取时间=now(),
                     最后修改=f'{pg.get("updated_by", "")} {pg.get("updated_at", "")}'.strip())
            _add_change(d, sid, ver, stat, chg, '条目未受影响')
            return '无变化', f'页面 {ver} 有改动（{stat}），但不在条目「{s.get("条目")}」范围内，条目文档不用改'
    chg, stat = _save_change(d, s, old_md, _norm(pg['md']), f'页面 {ver}')
    if p['整页']:
        att = p.get('附件') or []
        import_url(d.name, url, p['分类'], s.get('条目', ''), s.get('简介', ''), '', att or None, p.get('文件名', ''))
        _set_src(d, sid, 导入参数=p)
        _add_change(d, sid, ver, stat, chg, '已自动更新')
        _notice(d, f'{sid}《{s["标题"]}》原文更新（{ver}，{stat}），已重新导入；差异：{chg}')
        return '已更新', f'{ver}（{stat}），已重新导入整页；差异见 {chg.relative_to(d)}'
    _save_snapshot(d, pg)
    _set_src(d, sid, 待更新=True, 导入参数=p)
    _add_change(d, sid, ver, stat, chg, '条目待更新')
    _notice(d, f'{sid}《{s["标题"]}》条目「{s.get("条目")}」原文有变化（{ver}，{stat}），条目文档待更新；差异：{chg}')
    return '条目待更新', (f'{ver}（{stat}），条目「{s.get("条目")}」的原文有变化；快照已更新，'
                      f'条目文档需要重新整理（网页点「交给 Claude 更新」，或让 Claude 处理）。差异见 {chg.relative_to(d)}')


def _set_src(d, sid, **kv):
    m = load_meta(d)
    s = next(x for x in m['来源'] if x['编号'] == sid)
    s.update(kv)
    save_meta(d, m)
    return s


def _add_change(d, sid, ver, stat, chg, how):
    m = load_meta(d)
    s = next(x for x in m['来源'] if x['编号'] == sid)
    s.setdefault('变更记录', []).append({'时间': now(), '版本': ver, '改动': stat,
                                       '差异': str(chg.relative_to(d)), '处理': how})
    s['核对'] = '待核对' if how != '条目未受影响' else s.get('核对', '待核对')
    save_meta(d, m)


def refresh_sources(period, sid='', by='Claude'):
    """按登记的网址重新抓取来源：没变就记一下检查时间；整页 / 设计稿自动重新导入；只导了条目的标记待更新。"""
    d = period_dir(period)
    srcs = load_meta(d).get('来源') or []
    if sid:
        srcs = [x for x in srcs if x['编号'] == sid]
        if not srcs:
            raise KBError(f'没有这条来源：{sid}')
    if not srcs:
        return f'「{d.name}」还没有登记来源（网址导入的资料）'
    out, todo = [], []
    for s in srcs:
        try:
            r, why = _refresh_one(d, s)
        except KBError as e:
            r, why = '失败', str(e)
        _set_src(d, s['编号'], 检查时间=now(), 检查结果=r, **({'检查说明': why} if r != '无变化' else {'检查说明': ''}))
        if r != '无变化':
            log(d, '刷新来源', f'{s["编号"]}《{s["标题"]}》{s.get("条目") or ""} → {r}：{why}（{by}）')
        out.append(f'- {s["编号"]}《{s["标题"]}》{s.get("条目") or ""}：{r}　{why}')
        if r == '条目待更新':
            todo.append(s['编号'])
    head = f'「{d.name}」检查了 {len(srcs)} 条来源：'
    tail = ''
    if todo:
        tail = ('\n\n只导入了条目的来源原文有变化，需要重新整理条目文档：' + '、'.join(todo) +
                '\n做法：kb_read 差异文件和新快照，找到条目的新内容，用 kb_import_url 以同样的 url、item、category、filename '
                '重新导入（content 放更新后的条目原文，summary 写明这次改了什么），然后 kb_log 记录变化要点。')
    return head + '\n' + '\n'.join(out) + tail


def refresh_all(by='自动检查'):
    """所有未完成的期都检查一遍（网页服务定时调用）。返回有变化的条目说明。"""
    changed = []
    for name in period_names():
        d = period_dir(name)
        m = load_meta(d)
        if m.get('状态') not in REFRESH_STATUSES or not m.get('来源'):
            continue
        r = refresh_sources(name, by=by)
        hits = [x for x in r.splitlines() if x.startswith('- ') and ('已更新' in x or '待更新' in x)]
        if hits:
            changed.append((name, hits))
            _notify(f'知识库 · {name} 需求有更新', f'{len(hits)} 条来源有变化，请在网页「来源」里查看')
    return changed


def _update_prompt(name, sids):
    return f"""你是由知识库网页启动的【后台无人值守】知识库维护会话，只做一件事：更新期「{name}」里原文已变化的来源条目 {"、".join(sids)}。
终端里没有人，不要提问，不要改代码仓库，也不要改期的状态。对每个来源：
1. kb_iteration 查看「{name}」的来源清单，找到该来源的地址、条目、本地文件、快照和最新一条变更记录（差异文件）。
2. kb_read 读差异文件、新快照和现有条目文档，找出条目在新原文里的完整内容（表格行、章节，连同必要的表头和上下文）。
3. 用 kb_import_url 以同样的 url、item、category、filename 重新导入：content 放更新后的条目原文（保持原意、不改写），
   summary 在原简介基础上写明这次改了什么；条目关联的附件或设计稿地址变了，按知识库规则一并导入。
4. 用 kb_log 记录这次需求变化的要点（改了什么、可能影响哪些功能），然后结束。"""


def update_session(name):
    d = period_dir(name)
    s = load_meta(d).get('更新会话')
    if s and s.get('状态') == '运行中' and d.name not in _UPD and not _alive(s.get('pid', 0)):
        _upd_finish(d.name)
        s = load_meta(d).get('更新会话')
    return s


def _upd_finish(name, code=None):
    d = period_dir(name)
    m = load_meta(d)
    s = m.get('更新会话') or {}
    if s.get('状态') != '运行中':
        return
    s.update(状态='已结束', 结束时间=now(), 退出码=code, **_dev_result(s.get('日志', '')))
    save_meta(d, m)
    left = [x['编号'] for x in m.get('来源') or [] if x.get('待更新')]
    log(d, '条目更新会话结束', f'退出码 {code}' + (f'；仍待更新：{"、".join(left)}' if left else '；条目已全部更新'))
    _notify(f'知识库 · {d.name}', '来源条目已更新' if not left else f'还有 {len(left)} 条来源待更新')


def claude_update(period):
    """网页「交给 Claude 更新」：后台启动 Claude 重新整理原文已变化的条目。不作为 MCP 工具提供。"""
    d = period_dir(period)
    s = update_session(d.name)
    if s and s.get('状态') == '运行中':
        raise KBError('Claude 正在更新这一期的来源条目')
    sids = [x['编号'] for x in load_meta(d).get('来源') or [] if x.get('待更新')]
    if not sids:
        raise KBError('没有待更新的来源条目')
    eng = role_engine('整理')
    (d / DEV_DIR).mkdir(exist_ok=True)
    logf = d / DEV_DIR / f'更新来源-{datetime.now():%Y%m%d-%H%M%S}.jsonl'
    proc = engine_popen(eng, _update_prompt(d.name, sids), f'kb·更新·{d.name}', logf, ROOT)
    _UPD[d.name] = proc
    m = load_meta(d)
    m['更新会话'] = {'pid': proc.pid, '状态': '运行中', '开始时间': now(), '来源': sids, '日志': str(logf)}
    save_meta(d, m)
    log(d, '更新来源条目', f'后台会话 pid {proc.pid}：{"、".join(sids)}')

    def wait():
        code = proc.wait()
        _UPD.pop(d.name, None)
        _upd_finish(d.name, code)
    threading.Thread(target=wait, daemon=True).start()
    return f'已交给 {eng["名称"]} 在后台更新 {"、".join(sids)}，完成后会通知你'
