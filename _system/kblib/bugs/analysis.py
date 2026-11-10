# From 大大王.DT
"""Bug 只读分析：后台会话给出代码位置和修复思路，等人审核。"""
import json
import re
import sys
import threading
from datetime import datetime
from pathlib import Path
from ..common import KBError, KBNeed, load_settings, now, read_text, save_settings, uuid_hex
from ..periods import load_meta, log, period_dir
from ..repos import load_repos
from ..search import index_docs
from ..engines import engine_popen, get_engine
from ..devprep import _git, _git_root, repo_candidates, want_branches
from ..devsession import _alive, _dev_result, _notify
from ..bugs.sources import bug_sources
from ..bugs.index import ZT_DIR, _zt_recheck, zt_load, zt_save
from .. import lazy
_bug_fix = lazy('kblib.bugs.fix')      # 上层模块：用到时才 import（不形成循环）


AN_DIR = ZT_DIR / '分析'
AN_SESS = ZT_DIR / '分析会话.json'
AN_STATES = ('待审核', '已通过', '需重分析')
AN_MAX_BUGS = 6           # 一个会话最多分析几条
AN_MAX_RUN = 3            # 同时最多几个分析会话
_AN = {}                  # 会话编号 → Popen


def _readonly_args(e):
    """只读会话：Claude Code 直接禁用改文件的工具；其他引擎靠提示词约束 + 前后 git status 对比。"""
    if e.get('id') == 'claude' or Path(e.get('命令') or '').name == 'claude':
        return ['--disallowedTools', 'Edit', 'Write', 'MultiEdit', 'NotebookEdit']
    return []


def _an_load():
    try:
        return json.loads(AN_SESS.read_text('utf-8'))
    except (OSError, ValueError):
        return []


def _an_save(items):
    ZT_DIR.mkdir(exist_ok=True)
    tmp = AN_SESS.with_suffix('.tmp')
    tmp.write_text(json.dumps(items[-100:], ensure_ascii=False, indent=1), 'utf-8')
    tmp.replace(AN_SESS)


def an_sessions():
    items = _an_load()
    changed = False
    for x in items:
        if x.get('状态') == '运行中' and x['编号'] not in _AN and not _alive(x.get('pid', 0)):
            _an_finish(x['编号'])
            changed = True
    return _an_load() if changed else items


def _fx_heal():
    """以修复会话进程为准校正状态：会话还在跑，它的 Bug 就是「修复中」（防止被别的写入冲掉后显示成待修复）。"""
    run = [x for x in an_sessions() if x.get('类型') == '修复' and x.get('状态') == '运行中' and _alive(x.get('pid', 0))]
    if not run:
        return
    data = zt_load()
    fixed = []
    for x in run:
        for b in x['Bug']:
            e = data['Bug'].get(b)
            f = (e or {}).get('修复') or {}
            if e and f.get('会话') == x['编号'] and f.get('状态') in ('修复中', '已修复', '未完成'):
                continue                   # 已是这个会话的状态（会话一次修几个，修好的先标了已修复）
            if e:
                e['修复'] = {**{k: v for k, v in f.items() if k in ('排队时间', '发起')}, '状态': '修复中', '开始时间': x.get('开始时间', ''),
                            '会话': x['编号'], '分支': x.get('分支', ''), '仓库': x.get('仓库', '')}
                fixed.append(b)
    if fixed:
        zt_save(data)


def _bug_repo(e):
    """分析用哪个仓库、哪个分支：归属的期 / 事项确认过的开发仓库 > 关联仓库 > 文字资料里的路径 > 同产品以前用过的仓库。"""
    o = e.get('归属') or {}
    branch = ''
    if o.get('类型') in ('期', '事项') and o.get('名称'):
        try:
            d = period_dir(o['名称'])
        except KBError:
            d = None
        if d:
            m = load_meta(d)
            wb = want_branches(d, m)
            branch = wb[0] if wb else ''
            cands = repo_candidates(d, m)
            pick = next((c for c in cands if c['明确']), None) or (cands[0] if len(cands) == 1 else None)
            if pick:
                _an_learn(e, pick['路径'])
                return pick['路径'], branch, f'{o["类型"]}「{o["名称"]}」的仓库'
    mp = (load_settings().get('Bug仓库') or {}).get(f'{e.get("来源") or "禅道"}/{e.get("产品ID", "")}')
    if mp and _git_root(mp):
        return str(_git_root(mp)), branch, f'产品「{e.get("产品")}」以前用过的仓库'
    return '', branch, ''


def _an_learn(e, root):
    """记住 产品 → 仓库，待归纳的 Bug 以后也知道去哪个仓库找。"""
    if not e.get('产品ID'):
        return
    pid = f'{e.get("来源") or "禅道"}/{e["产品ID"]}'
    bug_sources()                      # 先完成老设置的迁移，免得这里写的被迁移覆盖
    st = load_settings()
    if (st.get('Bug仓库') or {}).get(pid) != str(root):
        st.setdefault('Bug仓库', {})[pid] = str(root)
        save_settings(st)


def _an_prompt(root, items, cur_branch):
    out = [f"""你是由知识库网页启动的【后台无人值守、只读】Bug 分析会话。终端里没有人，不要提问。
代码仓库：{root}（当前检出分支 {cur_branch or '未知'}）

【只读】不许修改、新建、删除任何文件，不许 git commit / checkout / switch / stash / reset / pull，不许装包、不许操作手机。
只做：读代码、grep / rg、git log / show / blame / diff / grep、kb_* 知识库工具。
要看的分支不是当前检出的分支时，不要切换：用 git show <分支>:<路径>、git grep <内容> <分支>、git log <分支> 读。

要分析的 Bug："""]
    for e, branch, why, note in items:
        o = e.get('归属') or {}
        out.append(f'- Bug {e["编号"]}：{e["标题"]}（{e["链接"]}）\n  归属：{o.get("类型")} {o.get("名称") or ""}'
                   + (f'；开发分支：{branch}' if branch else '') + (f'\n  用户的审核意见（上次分析被打回，这次要针对性改正）：{note}' if note else ''))
    out.append(f"""
每个 Bug 依次做：
1. kb_bug_get 实时拉取正文、评论、截图（截图用 Read 看）——以平台最新内容为准，不要只看标题。
2. 有归属的期 / 事项：kb_iteration 看需求、开发分支和记录。本期分支上的改动是首要线索：
   用 git log --oneline <开发分支> 和 git merge-base 找出本期的提交，git show / git diff 看相关改动。
3. kb_search 看以前事项的结论、别的 Bug 分析里有没有同类问题。
4. 在代码里定位（kb_search scope=code、grep、读文件），找出最可能出问题的位置。每个位置都要亲自读过，确认路径（相对仓库根目录）和行号真实存在；
   代码在开发分支上而不在当前检出分支上的，路径照写，并在说明里注明「在分支 xxx」。
5. 调 kb_bug_analysis 提交，字段：
   - summary：一句话结论
   - locations：[{{"path": "相对路径", "line": 行号, "note": "这里为什么可疑"}}]，按可能性从高到低，最多 5 个
   - cause：原因推测（引用代码 / 日志 / 提交作为证据）
   - fix：修复思路（改哪里、怎么改，可给备选；不写完整代码）
   - impact：影响范围（还有哪些地方用到、要注意什么）
   - selftest：自测要点
   - confidence：高 / 中 / 低
   - missing：还缺什么信息才能确定（复现步骤、日志、机型……），没有就空
   看不出原因就如实写低置信度和缺少的信息，不要编造代码位置。
全部提交后结束，最后用中文回复一句汇总（每个 Bug 的结论和置信度）。""")
    return '\n'.join(out)


def bug_analyze(ids, by='用户（网页）'):
    """网页「分析」：按仓库分组，各起一个后台只读会话。不作为 MCP 工具提供（对话里的 AI 直接自己分析，用 kb_bug_analysis 提交）。"""
    ids = [str(i).strip() for i in (ids if isinstance(ids, (list, tuple)) else [ids]) if str(i).strip()]
    if not ids:
        raise KBError('没有要分析的 Bug')
    ids, gone = _zt_recheck(ids, '分析前核对')        # 已经转给别人的直接移除，不分析
    if not ids:
        raise KBError('没有要分析的 Bug：' + '；'.join(gone))
    data = zt_load()
    running = [x for x in an_sessions() if x.get('状态') == '运行中' and x.get('类型') != '修复']
    busy = {b for x in running for b in x.get('Bug', [])}
    groups, skipped, need = {}, list(gone), []
    for bid in ids:
        e = data['Bug'].get(bid)
        if not e:
            skipped.append(f'{bid}（索引里没有）')
            continue
        if bid in busy:
            skipped.append(f'{bid}（正在分析）')
            continue
        root, branch, why = _bug_repo(e)
        if not root:
            need.append(e)
            continue
        note = (e.get('分析') or {}).get('意见', '') if (e.get('分析') or {}).get('状态') == '需重分析' else ''
        groups.setdefault(root, []).append((e, branch, why, note))
    if need and not groups:
        raise KBNeed(f'不知道 Bug {"、".join(e["编号"] for e in need)} 该在哪个代码仓库里分析：先把它归到有开发仓库的期 / 事项，或选一个仓库',
                     {'需要': '分析仓库', 'Bug': [e['编号'] for e in need], '产品': need[0].get('产品', ''),
                      '候选': sorted({str(v) for v in (load_settings().get('Bug仓库') or {}).values()}
                                     | {v['路径'] for v in load_repos().values()})})
    out = []
    eng = get_engine()
    for root, items in groups.items():
        for i in range(0, len(items), AN_MAX_BUGS):
            if len(running) >= AN_MAX_RUN:
                skipped += [f'{x[0]["编号"]}（同时分析的会话已满 {AN_MAX_RUN} 个，稍后再点）' for x in items[i:]]
                break
            part = items[i:i + AN_MAX_BUGS]
            sid = datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid_hex()[:4]
            (ZT_DIR / '分析会话').mkdir(parents=True, exist_ok=True)
            logf = ZT_DIR / '分析会话' / f'{sid}.jsonl'
            cur = _git(Path(root), 'branch', '--show-current').stdout.strip()
            git0 = _git(Path(root), 'status', '--porcelain').stdout
            proc = engine_popen(eng, _an_prompt(root, part, cur), f'kb·分析·Bug {"、".join(x[0]["编号"] for x in part)}', logf, root,
                                extra_args=_readonly_args(eng))
            _AN[sid] = proc
            rec = {'编号': sid, 'pid': proc.pid, '状态': '运行中', '开始时间': now(), '仓库': root, '分支': cur,
                   'Bug': [x[0]['编号'] for x in part], '日志': str(logf), '引擎': eng['名称'], '发起': by, 'git前': git0}
            items_all = _an_load()
            items_all.append(rec)
            _an_save(items_all)
            running.append(rec)

            def wait(sid=sid, proc=proc):
                code = proc.wait()
                _AN.pop(sid, None)
                _an_finish(sid, code)
            threading.Thread(target=wait, daemon=True).start()
            out.append(f'已交给 {eng["名称"]} 在 {root} 只读分析 Bug {"、".join(rec["Bug"])}')
    if need:
        out.append(f'Bug {"、".join(e["编号"] for e in need)}：不知道在哪个仓库分析，先把它归到有开发仓库的期 / 事项')
    if skipped:
        out.append('跳过：' + '；'.join(skipped))
    return '\n'.join(out) or '没有可分析的 Bug'


def bug_analyze_in(ids, root, by='用户（网页）'):
    """网页弹窗选了仓库：记住 产品 → 仓库，再分析。"""
    r = _git_root(root)
    if not r:
        raise KBError(f'不是 git 仓库：{root}')
    data = zt_load()
    for bid in ids:
        e = data['Bug'].get(str(bid))
        if e:
            _an_learn(e, r)
    return bug_analyze(ids, by)


def _an_finish(sid, code=None):
    items = _an_load()
    x = next((i for i in items if i['编号'] == sid), None)
    if not x or x.get('状态') != '运行中':
        return
    res = _dev_result(x.get('日志', ''))
    git1 = _git(Path(x['仓库']), 'status', '--porcelain').stdout if Path(x['仓库']).exists() else ''
    x.update(状态='已结束', 结束时间=now(), 退出码=code, 结果=(res.get('结果') or '')[:1500], 费用=res.get('费用'))
    if x.get('类型') == '修复':
        data = zt_load()
        done, left = [], []
        for b in x['Bug']:
            e = data['Bug'].get(b)
            f = (e or {}).get('修复') or {}
            if f.get('会话') == x['编号'] and f.get('状态') == '修复中':      # 会话没标记就结束了
                f.update(状态='未完成', 时间=now(), 说明='修复会话结束时没有标记结果，看会话日志', 结果=x['结果'][:500])
                left.append(b)
            elif f.get('状态') == '已修复':
                done.append(b)
            else:
                left.append(b)
        zt_save(data)
        x['完成'] = done
        new = _git(Path(x['仓库']), 'log', '--format=%h %s', f'{x.get("起点", "HEAD")}..HEAD').stdout.strip().splitlines() if x.get('起点') else []
        x['新提交'] = new[:20]
        _an_save(items)
        _notify('知识库 · Bug 修复', f'修好 {len(done)} 条' + (f'，未完成 {"、".join(left)}' if left else '') + f'；新提交 {len(new)} 个')
        try:
            _bug_fix.fix_queue_tick()          # 队列里还有的接着修
        except Exception as ex:
            print('fix_queue_tick:', repr(ex), file=sys.stderr)
        return
    if git1 != x.get('git前', git1):
        x['警告'] = '分析前后仓库的 git status 不一样：只读会话可能改了文件，请检查'
    x.pop('git前', None)
    data = zt_load()
    done = [b for b in x['Bug'] if (data['Bug'].get(b, {}).get('分析') or {}).get('会话') == sid]
    x['完成'] = done
    _an_save(items)
    left = [b for b in x['Bug'] if b not in done]
    _notify('知识库 · Bug 分析', f'分析完成 {len(done)} 条' + (f'，未提交 {"、".join(left)}' if left else '') + ('；⚠ 仓库有改动' if x.get('警告') else ''))


def _an_check(root, branch, locs):
    """核对 AI 给的代码位置：文件在当前检出 / 开发分支上存在吗，行号在范围内吗。"""
    out = []
    for l in locs or []:
        path = str(l.get('path') or l.get('路径') or '').strip().lstrip('./')
        try:
            line = int(l.get('line') or l.get('行') or 0)
        except (TypeError, ValueError):
            line = 0
        item = {'路径': path, '行': line, '说明': l.get('note') or l.get('说明') or '', '核对': ''}
        if root and path:
            f = Path(root) / path
            n = None
            if f.is_file():
                n = sum(1 for _ in open(f, 'rb'))
            elif branch:
                r = _git(Path(root), 'show', f'{branch}:{path}')
                if r.returncode == 0:
                    n, item['分支'] = r.stdout.count('\n') + 1, branch
            if n is None:
                item['核对'] = '⚠ 文件不存在'
            elif line and line > n:
                item['核对'] = f'⚠ 行号超出（文件共 {n} 行）'
            else:
                item['核对'] = '✓'
        out.append(item)
    return out


def bug_analysis(bid, summary, locations=None, cause='', fix='', impact='', selftest='', confidence='', missing='', by='Claude'):
    """提交一个 Bug 的分析结论（后台分析会话或对话里的 AI 用）。审核只能用户在网页上做。"""
    data = zt_load()
    e = data['Bug'].get(str(bid))
    if not e:
        raise KBError(f'Bug 索引里没有 {bid}')
    if not (summary or '').strip():
        raise KBError('summary 不能为空')
    if isinstance(locations, str):
        try:
            locations = json.loads(locations)
        except ValueError:
            locations = [{'path': x.split(':')[0], 'line': (x.split(':') + ['0'])[1], 'note': ''} for x in re.split(r'[\s,，]+', locations) if x]
    sess = next((x for x in reversed(an_sessions()) if x.get('状态') == '运行中' and str(bid) in x.get('Bug', [])), None)
    root, branch = (sess['仓库'], '') if sess else ('', '')
    if not root:
        root, branch, _ = _bug_repo(e)
    else:
        _, branch, _ = _bug_repo(e)
    old = e.get('分析') or {}
    a = {'摘要': summary.strip(), '代码位置': _an_check(root, branch, locations), '原因': cause or '', '思路': fix or '',
         '影响': impact or '', '自测': selftest or '', '置信度': confidence or '', '缺少': missing or '',
         '仓库': root, '分支': branch, '时间': now(), '基于修改': e.get('修改原值', ''), '修改时间': e.get('修改时间', ''),
         '状态': '待审核', '过时': False, '提交者': by, '会话': sess['编号'] if sess else '',
         '历史': (old.get('历史') or [])[-4:] + ([{k: old.get(k) for k in ('时间', '摘要', '状态', '意见')}] if old.get('摘要') else [])}
    e['分析'] = a
    zt_save(data)
    _an_md(e)
    index_docs()
    bad = [f'{x["路径"]}:{x["行"]} {x["核对"]}' for x in a['代码位置'] if x['核对'].startswith('⚠')]
    return f'已记录 Bug {bid} 的分析（待用户审核）' + (f'\n⚠ 这些位置核对不过，请确认后用正确的路径 / 行号重新提交：{"；".join(bad)}' if bad else '')


def _an_md(e):
    a = e.get('分析') or {}
    AN_DIR.mkdir(parents=True, exist_ok=True)
    f = AN_DIR / f'Bug{e["编号"]}.md'
    if not a:
        f.unlink(missing_ok=True)
        return
    locs = '\n'.join(f'- `{x["路径"]}:{x["行"]}`{" （分支 " + x["分支"] + "）" if x.get("分支") else ""} {x["说明"]} {x["核对"]}' for x in a['代码位置']) or '- （没有给出）'
    f.write_text(f"""# Bug {e["编号"]} 分析：{e["标题"]}

> {e["链接"]}　分析 {a["时间"]}（{a["提交者"]}）　状态：{a["状态"]}　置信度：{a["置信度"] or "?"}　依据 Bug 修改时间 {a.get("修改时间") or a.get("禅道修改") or ""}
> 这是 AI 的分析结论，不是 Bug 平台原文；原文以平台为准。

**结论**：{a["摘要"]}

## 代码位置（仓库 {a["仓库"] or "?"}）
{locs}

## 原因
{a["原因"] or "（无）"}

## 修复思路
{a["思路"] or "（无）"}

## 影响范围
{a["影响"] or "（无）"}

## 自测要点
{a["自测"] or "（无）"}
""" + (f'\n## 还缺的信息\n{a["缺少"]}\n' if a.get('缺少') else '') + (f'\n## 审核意见\n{a["意见"]}\n' if a.get('意见') else ''), 'utf-8')


def bug_review(bid, action, note='', by='用户（网页）'):
    """审核分析：通过 / 打回（写意见，下次重新分析时带上）。只能用户在网页上操作。"""
    data = zt_load()
    e = data['Bug'].get(str(bid))
    if not e or not e.get('分析'):
        raise KBError(f'Bug {bid} 还没有分析')
    a = e['分析']
    if action == '通过':
        a.update(状态='已通过', 审核时间=now(), 审核人=by, 意见=note or a.get('意见', ''))
    elif action == '打回':
        if not (note or '').strip():
            raise KBError('打回要写意见：哪里不对、希望往哪个方向查')
        a.update(状态='需重分析', 审核时间=now(), 审核人=by, 意见=note.strip())
    else:
        raise KBError('只能「通过」或「打回」')
    zt_save(data)
    _an_md(e)
    o = e.get('归属') or {}
    if o.get('类型') in ('期', '事项') and o.get('名称'):
        try:
            log(period_dir(o['名称']), 'Bug 分析审核', f'Bug {bid} {action}' + (f'：{note}' if note else '') + f'（{by}）')
        except KBError:
            pass
    return f'Bug {bid} 的分析已{"通过" if action == "通过" else "打回，重新分析时会带上你的意见"}'


def bug_analysis_view(bid, ctx=6):
    """网页审核用：分析 + 每个代码位置附近的代码。"""
    e = zt_load()['Bug'].get(str(bid))
    if not e or not e.get('分析'):
        raise KBError(f'Bug {bid} 还没有分析')
    a = json.loads(json.dumps(e['分析']))
    root = a.get('仓库') or ''
    for x in a['代码位置']:
        x['代码'] = ''
        if not root or x['核对'].startswith('⚠') or not x['路径']:
            continue
        try:
            if x.get('分支'):
                text = _git(Path(root), 'show', f'{x["分支"]}:{x["路径"]}').stdout
            else:
                f = (Path(root) / x['路径']).resolve()
                if Path(root).resolve() not in f.parents:
                    continue
                text = read_text(f)
        except OSError:
            continue
        lines = text.splitlines()
        ln = x['行'] or 1
        lo, hi = max(1, ln - ctx), min(len(lines), ln + ctx)
        x['代码'] = '\n'.join(f'{i:>5}{"▶" if i == ln else " "} {lines[i - 1]}' for i in range(lo, hi + 1))
        x['起始行'] = lo
    return {'bug': {k: v for k, v in e.items() if k != '分析'}, 'analysis': a}
