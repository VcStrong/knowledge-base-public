# From 大大王.DT
"""网页总览 / 期详情的数据。"""
import re
from .common import (
    CATS,
    DEV_OK,
    DOC_EXT,
    HIST,
    IMG_EXT,
    INBOX,
    KBError,
    NOTE_SUFFIX,
    PERIODS,
    PROTO_DIR,
    ROOT,
    read_text,
)
from .textx import extract
from .periods import init, is_task, load_meta, period_dir, period_names
from .notes import NOTES_FILE, note_md, note_title, notes_of
from .repos import load_repos
from .search import db, index_repo
from .baseinfo import base_context, base_load
from .flows import flow_text, period_flow
from . import lazy
_bug_index = lazy('kblib.bugs.index')      # 上层模块：用到时才 import（不形成循环）
_anr_store = lazy('kblib.anr.store')      # 上层模块：用到时才 import（不形成循环）


def _materials(d):
    res = {}
    for c in CATS:
        items = []
        for p in sorted((d / c).iterdir()) if (d / c).exists() else []:
            if p.name in (HIST, NOTES_FILE) or p.name.startswith('.') or p.name.endswith(NOTE_SUFFIX):
                continue
            items.append(p)
        res[c] = items
    return res


def overview():
    init()
    out = [f'知识库：{ROOT}']
    nb = len(base_load()['条目'])
    out.append(f'基础知识库：{nb} 条（账号、测试账号、代理 / VPN、环境配置等，所有期共用；用 kb_base 查看）')
    names = period_names()
    tasks = [n for n in names if is_task(load_meta(PERIODS / n))]
    names = [n for n in names if n not in tasks]
    out.append(f'\n期（{len(names)}）：' if names else '\n期：（空，先 kb_create_iteration）')
    for n in names + ['__事项__'] + tasks:
        if n == '__事项__':
            out.append(f'\n事项（{len(tasks)}，不是产品需求的工作：ANR、埋点、线上问题…；kb_create_task 新建）：' if tasks else '\n事项：（无）')
            continue
        d = PERIODS / n
        m = load_meta(d)
        if is_task(m):
            out.append(f'- {n} ｜ {m.get("状态")} ｜ {m.get("事项类型")}·优先级{m.get("优先级", "中")}'
                       + (f' ｜ 来自 {m["来自"]}' if m.get('来自') else '') + f' ｜ 更新 {m.get("更新时间", "")}')
            continue
        mats = _materials(d)
        cnt = ' · '.join(f'{c} {len(v) + len(notes_of(d, c, m))}' for c, v in mats.items())
        repos = '、'.join(m.get('关联仓库') or []) or '无'
        out.append(f'- {n} ｜ {m.get("状态")} ｜ {cnt} ｜ 仓库：{repos} ｜ 更新 {m.get("更新时间", "")}')
    repos = load_repos()
    out.append('\n代码仓库：' + ('' if repos else '（未登记）'))
    with db() as c:
        for k, v in repos.items():
            n = c.execute("select count(*) from files where kind='code' and repo=?", (k,)).fetchone()[0]
            out.append(f'- {k} → {v["路径"]}（已索引 {n} 个文件）')
        nd = c.execute("select count(*) from files where kind='doc'").fetchone()[0]
    inbox = [p.name for p in INBOX.iterdir() if not p.name.startswith('.')] if INBOX.exists() else []
    out.append(f'\n收件箱待整理：{len(inbox)} 个' + (f'（{"、".join(inbox[:20])}）路径 {INBOX}' if inbox else ''))
    out.append(f'文档索引：{nd} 个文件')
    return '\n'.join(out)


def _period_bugs_md(name):
    """这一期的 Bug（只是索引）；没有就返回空。"""
    try:
        es = [e for e in _bug_index.zt_load()['Bug'].values() if (e.get('归属') or {}).get('名称') == name]
    except Exception:
        return ''
    if not es:
        return ''
    op = [e for e in es if e['状态'] != '已关闭']
    out = [f'\n## Bug（未关闭 {len(op)} / 共 {len(es)}；只是索引，处理前用 kb_bug_get 实时拉取）']
    out += [f'- Bug {e["编号"]} ［{e["状态"]}·严重{e["严重"]}］{e["标题"]}　{e["链接"]}' + (f'\n  {e["简介"]}' if e.get('简介') else '')
            for e in sorted(op, key=lambda e: (e['状态'] != '激活', e['严重'], e['编号']))]
    return '\n'.join(out)


def period_detail(name, log_lines=20):
    d = period_dir(name)
    m = load_meta(d)
    out = [f'# {d.name}' + (f'（事项 · {m.get("事项类型")} · 优先级 {m.get("优先级", "中")}' + (f' · 来自 {m["来自"]}' if m.get('来自') else '') + '）' if is_task(m) else ''),
           f'状态：{m.get("状态")}　创建：{m.get("创建时间")}　更新：{m.get("更新时间", "")}',
           f'说明：{m.get("说明") or "无"}', f'关联仓库：{"、".join(m.get("关联仓库") or []) or "无"}', f'目录：{d}']
    branches = [n for n in notes_of(d, m=m) if n['类型'] == '分支']
    if branches:
        out.append('开发分支：' + '；'.join(f'{n["编号"]} {note_title(n)}' for n in branches))
    for c, items in _materials(d).items():
        ns = notes_of(d, c, m)
        out.append(f'\n## {c}（文件 {len(items)}' + (f' · 文字 {len(ns)}）' if ns else '）'))
        for n in ns:
            out.append(f'- {n["编号"]} ［{n["类型"]}］{note_title(n)}'
                       + (f'　{n["链接"]}' if n.get('链接') and n['链接'] != note_title(n) else '')
                       + (f'　（来自 {n["来自"]}）' if n.get('来自') else ''))
        for p in items:
            if p.is_dir():
                out.append(f'- {p.name}/（目录，{sum(1 for _ in p.rglob("*") if _.is_file())} 个文件）')
            else:
                flag = ''
                if p.suffix.lower() in IMG_EXT:
                    flag = '［有说明］' if p.with_name(p.name + NOTE_SUFFIX).exists() else '［无说明］'
                out.append(f'- {p.name} {flag}')
        hist = d / c / HIST
        if hist.exists():
            out.append(f'  （历史版本 {sum(1 for _ in hist.iterdir())} 个）')
    srcs = m.get('来源') or []
    if srcs:
        out.append(f'\n## 来源（{len(srcs)}，待核对 {sum(1 for s in srcs if s.get("核对") == "待核对")}）')
        for s in srcs:
            out.append(f'- {s["编号"]} ［{s.get("核对")}］《{s["标题"]}》{s.get("条目", "")} → {"、".join(s.get("文件", []))}\n'
                       f'  {s["地址"]}\n  简介：{s.get("简介", "")}' + (f'\n  核对备注：{s["核对备注"]}' if s.get('核对备注') else '')
                       + (f'\n  上次检查：{s["检查时间"]} {s.get("检查结果", "")}' if s.get('检查时间') else '')
                       + ('\n  ⚠ 原文已变化，条目文档待更新' if s.get('待更新') else '')
                       + ''.join(f'\n  变更 {c["时间"]}：{c["版本"]}，{c["改动"]}，{c["处理"]}，差异 {c["差异"]}'
                                 for c in (s.get('变更记录') or [])[-3:]))
    bl = _period_bugs_md(d.name)
    if bl:
        out.append(bl)
    al = _anr_store._period_anr_md(d.name)
    if al:
        out.append(al)
    f = d / '记录.md'
    if f.exists():
        lines = [x for x in read_text(f).splitlines() if x.startswith('- ')]
        out.append(f'\n## 最近记录（共 {len(lines)} 条）')
        out += lines[-log_lines:]
    return '\n'.join(out)


def dev_package(name, max_chars=60000):
    d = period_dir(name)
    m = load_meta(d)
    if m.get('状态') not in DEV_OK:
        raise KBError(f'「{d.name}」当前状态是「{m.get("状态")}」，用户尚未批准开发。'
                      f'请提醒用户确认材料齐全后，在终端运行 kb approve "{d.name}"，或在知识库网页点「开始开发」')
    repos = load_repos()
    out = [period_detail(name, log_lines=30), '\n# 关联仓库']
    for r in m.get('关联仓库') or []:
        if r in repos:
            out.append(f'- {r} → {repos[r]["路径"]}　' + index_repo(r))
    if not m.get('关联仓库'):
        out.append('（未关联，开发前请让用户确认目标仓库，再用 kb_link_repo 关联）')
    budget = max_chars
    ns = sorted(notes_of(d, m=m), key=lambda n: (n['类型'] != '分支', CATS.index(n['分类'])))
    if ns:
        out.append('\n# 文字资料（口述需求、开发分支、外部链接等原样记录；链接未导入的可用 kb_fetch_url 查看）')
        for n in ns:
            part = '\n' + note_md(n).replace('## ', f'## ［{n["分类"]}］', 1)
            budget -= len(part)
            out.append(part)
    mats = _materials(d)
    for c in ('需求', '接口文档', '其他资料'):
        for p in mats[c]:
            if p.name == PROTO_DIR:
                continue
            files = [x for x in p.rglob('*') if x.is_file()] if p.is_dir() else [p]
            for f in files:
                if (f.suffix.lower() not in DOC_EXT or f.suffix.lower() in IMG_EXT or HIST in f.parts
                        or f.name.endswith(NOTE_SUFFIX)):
                    continue
                text = extract(f) or ''
                if budget <= 0:
                    out.append(f'\n## [{c}] {f}\n（篇幅已满，用 kb_read 读取）')
                    continue
                part = text[:min(12000, budget)]
                budget -= len(part)
                more = f'\n…（已截断，全文用 kb_read 读取）' if len(part) < len(text) else ''
                out.append(f'\n## [{c}] {f}\n{part}{more}')
    out.append('\n# 设计稿（要实现的产品图，UI 以此为准；请用 Read 逐张查看）')
    n_design = 0
    for p in mats['设计图']:
        if p.is_dir():
            for f in sorted(p.rglob('*')):
                if HIST in f.parts or not f.is_file():
                    continue
                if f.suffix.lower() in IMG_EXT:
                    n_design += 1
                    out.append(f'- {f}')
                elif f.suffix.lower() == '.md' and not f.name.endswith(NOTE_SUFFIX):
                    part = read_text(f)[:min(15000, max(budget, 0))]
                    budget -= len(part)
                    out.append(f'\n## [设计规格] {f}\n{part}' if part else f'- {f}（设计规格，用 kb_read 读取）')
        elif p.suffix.lower() in IMG_EXT:
            n_design += 1
            note = p.with_name(p.name + NOTE_SUFFIX)
            out.append(f'- {p}' + (f'\n  说明：{read_text(note).split(chr(10), 2)[-1].strip()[:300]}' if note.exists() else ''))
        else:
            out.append(f'- {p}（用 kb_read 读取）')
    if not n_design:
        out.append('⚠️ 还没有设计稿图片。请先用 kb_import_design 导入需求表里的「设计稿地址」，或让用户导出设计稿放进「设计图」；不要按原型图臆造 UI。')
    proto = d / '需求' / PROTO_DIR
    if proto.exists():
        imgs = sorted(x for x in proto.iterdir() if x.suffix.lower() in IMG_EXT)
        out.append(f'\n# 原型图 / 参考图（{len(imgs)} 张，仅用于理解交互逻辑，UI 以设计稿为准）')
        for f in imgs[:80]:
            note = f.with_name(f.name + NOTE_SUFFIX)
            desc = re.sub(r'\s+', ' ', read_text(note).split('\n', 2)[-1])[:160] if note.exists() else ''
            out.append(f'- {f}' + (f'　{desc}' if desc else ''))
    bc = base_context()
    if bc:
        out.append('\n# 基础知识库（所有期共用：账号、测试账号、代理 / VPN、环境配置；机密用 kb_base_secret 读取，不要写进代码、文档、提交或日志）\n' + bc)
    fl = period_flow(m)
    out.append('\n# 开发约定\n- 状态是「已批准开发」时，开始写代码前调用 kb_set_status 改为「开发中」\n'
               f'- 开发流程：{fl["名称"]}（{fl.get("说明") or "见知识库网页「⚙ 设置」"}）\n'
               + flow_text(fl, '开发约定', 期名=d.name, **({'文档目录': m['SDD目录']} if m.get('SDD目录') else {})).rstrip() + '\n'
               '- 需要用户确认时用 kb_ask 发到网页，再用 kb_wait_answer 等回答；'
               + ('本期已开启免打扰：自行决策并 kb_log 记录理由\n' if m.get('免打扰') else '本期未开启免打扰：拿到回答前不要自行决定\n')
               + 
               '- 关键决定、接口变更、与需求不一致之处用 kb_log 记录\n'
               '- 完成后 kb_set_status 改为「已完成」，并记录改动摘要（分支、提交）')
    return '\n'.join(out)
