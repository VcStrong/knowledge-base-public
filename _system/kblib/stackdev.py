"""全栈 P3：拍板后各端并行开发 + AI 互审。

  你点「▶ 各端开工」（= 本人批准开发）→ 拍板方案里涉及、选了仓库的端排队；
  同时最多 MAX_PAR 个端在跑（本机编译吃资源），仓库被别的会话占着的先等；
  每个端一个后台会话：在自己的仓库里按自己的开发流程（「⚙ 设置 → 开发流程」按识别文件匹配；服务端 SDD 以后接入）做这个端的需求，
    客户端在服务端接口没好之前按契约 mock；做完用 kb_stack_report 汇报（覆盖了哪些需求、提交、自测证据）；
  汇报后起一个只读审查会话（不看开发过程，只拿需求规格、接口契约、设计稿和这次的改动挑错），用 kb_stack_review 给结论；
  打回 → 接着原会话改（最多 MAX_ROUNDS 轮），还不过就停下等你看；全部通过 → 等你看证据包（拍板 2，P4）。
期信息「各端开发」：{端: {状态, 轮次, 起点, 会话, 日志, 审查日志, 开始, 结束, 汇报, 审查, 引擎, 待办}}
状态：排队中 / 开发中 / 待审查 / 审查中 / 打回修改 / 审查通过 / 要你看 / 失败 / 已停止
svn 的端：svn 一提交就进服务器，所以 AI 只改工作副本、不提交；审查看 svn diff；你验收时知识库只提交这次改的文件
  （开工前工作副本里原有的改动不碰），各端开发记「已提交」= 版本号。git 的端：AI 在本地提交、不推送，你验收时知识库推送开发分支（记「已推送」）。
"""
import json
import os
import random
import secrets
import shlex
import signal
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from .common import PERIODS, KBError, now
from .periods import load_meta, log, period_dir, period_names, save_meta, set_status
from . import hosts
from .devsession import DEV_DIR, _NO_BG, _alive, _dev_env, _dev_result, _notify, _session_id
from .engines import engine_cmd, engine_popen, role_engine
from .flows import flow_for, flow_text
from .stack import ENDS, _sdir, period_ends

MAX_PAR = 2              # 同时开发的端（审查是只读的，不占这个名额）
MAX_ROUNDS = 2           # 审查打回后自动改的轮数
RUNNING = ('开发中', '审查中')
_PROCS = {}              # (期, 端, 开发/审查) → Popen
_LOCK = threading.RLock()


def _plan(d):
    try:
        return json.loads((_sdir(d) / '方案.json').read_text('utf-8'))
    except (OSError, ValueError):
        raise KBError('还没有方案')


def _contract(d, m):
    ver = (m.get('全栈') or {}).get('契约版本')
    p = _sdir(d) / 'api' / f'openapi.{ver}.yaml' if ver else None
    return (ver, p) if p and p.exists() else ('', None)


def _readonly(eng):
    return ['--disallowedTools', 'Edit', 'Write', 'MultiEdit', 'NotebookEdit'] \
        if eng.get('id') == 'claude' or Path(eng.get('命令') or '').name == 'claude' else []


def _kill(pid):
    try:
        os.killpg(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass


# ---------------------------------------------------------------- 开工、排队
def stack_dev_start(name, only='', by='用户（网页）'):
    """「▶ 各端开工」：本人批准开发。only = 只开工 / 重新开工某一端。"""
    d = period_dir(name)
    m = load_meta(d)
    st = m.get('全栈') or {}
    if st.get('状态') not in ('已拍板', '开发中', '各端完成'):
        raise KBError('方案还没拍板')
    plan = _plan(d)
    ends = period_ends(d, m)
    want = [x['端'] for x in plan['各端'] if x.get('涉及')]
    if only:
        if only not in want:
            raise KBError(f'拍板的方案里 {only} 不涉及')
        want = [only]
    dev = m.setdefault('各端开发', {})
    out, skip = [], []
    for e in want:
        cur = dev.get(e) or {}
        if cur.get('状态') in RUNNING and _alive(cur.get('pid', 0)):
            skip.append(f'{e}（正在跑）')
            continue
        if e not in ends:
            skip.append(f'{e}（没选仓库）')
            continue
        dev[e] = {'状态': '排队中', '轮次': 0, '排队时间': now(), '仓库': ends[e]['仓库'], '分支': ends[e].get('分支', ''), '版本库': ends[e].get('版本库', ''),
                  '会话': cur.get('会话', '') if only else '',
                  '起点': cur.get('起点', '') if only and not (cur.get('已推送') or cur.get('已提交')) else ''}
        out.append(e)
    if not out:
        raise KBError('没有可开工的端：' + '；'.join(skip))
    st['状态'] = '开发中'
    m['全栈'] = st
    save_meta(d, m)
    if m.get('状态') not in ('开发中',):
        set_status(d.name, '开发中', f'各端开工：{"、".join(out)}（本人批准）', by_human=True)
    log(d, '各端开发', f'开工：{"、".join(out)}' + (f'；跳过 {"、".join(skip)}' if skip else '') + f'（{by}）')
    stack_tick(d.name)
    return f'已开工：{"、".join(out)}（同时最多 {MAX_PAR} 个端在跑，其余排队）' + (f'；跳过 {"、".join(skip)}' if skip else '')


def stack_dev_stop(name, end, by='用户（网页）'):
    d = period_dir(name)
    m = load_meta(d)
    x = (m.get('各端开发') or {}).get(end)
    if not x:
        raise KBError(f'{end} 没有开工')
    if x.get('pid') and x.get('状态') in RUNNING:
        _kill(x['pid'])
    x.update(状态='已停止', 结束时间=now())
    save_meta(d, m)
    log(d, '各端开发', f'{end} 停止（{by}）')
    return f'{end} 已停止'


def _repo_free(d, end, root, dev):
    """同一仓库同一时间只让一个会话改：别的端、期的开发会话、修复会话占着就等。"""
    for e, x in dev.items():
        if e != end and x.get('仓库') == root and x.get('状态') == '开发中' and _alive(x.get('pid', 0)):
            return f'{e} 正在这个仓库里开发'
    if hosts.is_remote(root):
        return ''
    from .bugs.fix import _repo_busy
    return _repo_busy(root)


def stack_tick(only=''):
    """收尾死掉的会话、按名额启动排队的端和审查。网页每分钟跑一次，会话结束时也跑。"""
    with _LOCK:
        for n in [only] if only else period_names():
            try:
                d = period_dir(n)
            except KBError:
                continue
            m = load_meta(d)
            dev = m.get('各端开发') or {}
            if not dev:
                continue
            for e, x in dev.items():                     # 进程没了但还标着在跑（网页重启过）
                if x.get('状态') in RUNNING and not _alive(x.get('pid', 0)) and (d.name, e, x['状态']) not in _PROCS:
                    _finish(d.name, e, x['状态'])
            m = load_meta(d)
            dev = m.get('各端开发') or {}
            for e in [e for e in ENDS if (dev.get(e) or {}).get('状态') == '待审查']:
                _start_review(d, e)
            m = load_meta(d)
            dev = m.get('各端开发') or {}
            busy = sum(1 for x in dev.values() if x.get('状态') == '开发中')
            for e in [e for e in ENDS if (dev.get(e) or {}).get('状态') in ('排队中', '打回修改')]:
                if busy >= MAX_PAR:
                    break
                why = _repo_free(d, e, dev[e]['仓库'], dev)
                if why:
                    if dev[e].get('等待') != why:
                        m = load_meta(d)
                        m['各端开发'][e]['等待'] = why
                        save_meta(d, m)
                    continue
                _start_dev(d, e)
                busy += 1


# ---------------------------------------------------------------- 开发会话
def _dev_prompt(d, m, end, x, plan, issues=None, todo=''):
    ver, cp = _contract(d, m)
    mine = next((p for p in plan['各端'] if p['端'] == end), {})
    reqs = [r for r in plan.get('需求') or [] if end in (r.get('端') or [])]
    root, branch = x['仓库'], x.get('分支', '')
    svn = x.get('版本库') == 'svn'
    f = flow_for(m, root) if not hosts.is_remote(root) else None
    steps = flow_text(f, '开发步骤', 期名=d.name, 仓库=root, 分支=branch, 文档目录='', 资料目录='') if f else ''
    server_ok = (m.get('各端开发') or {}).get('服务端', {}).get('状态') == '审查通过' or x.get('联调')
    if issues is not None:
        return (f'审查会话把 {end} 这一轮打回了（第 {x["轮次"]} 轮），问题如下，逐条改完、自测、{"留在 svn 工作副本里（不要 svn commit）" if svn else "提交"}，再用 kb_stack_report 重新汇报：\n'
                + '\n'.join(f'- [{i.get("严重度", "")}] {i.get("需求", "")} {i.get("问题", "")}（{i.get("位置", "")}）' for i in issues)
                + ('\n有不同意见的，在汇报的 summary 里说明理由，不要硬改。' ) + _NO_BG)
    return f"""你是由知识库网页启动的【后台无人值守】{end} 开发会话：期「{d.name}」。终端里没有人，不要在回复里提问，也不要用 AskUserQuestion；
要问用户用 kb_ask（iteration=「{d.name}」），再 kb_wait_answer 等回答（提示免打扰就按你的建议做）。

用户一个人做全栈，各端由不同的 AI 会话并行开发，你只负责 {end}。方案已经由用户拍板：
- 需求规格：{_sdir(d) / 'spec.md'}（需求编号 REQ-xxx，验收标准逐条要满足）
- 接口契约：{cp or '本期不涉及接口'}{f'（{ver}，已锁定；和它不一致的地方不要自己改契约，用 kb_ask 提出）' if cp else ''}
- 设计稿：kb_period（name=「{d.name}」）里的设计图（PSD 看同名 .png 预览）
{_vcs_lines(root, branch) if svn else f"""- 仓库：{root}，分支：{branch or '（用仓库当前分支；要新建就按仓库惯例从主干拉，先 kb_ask 确认分支名）'}
  先确认在这个分支上：本地没有就从远端拉；有别人未提交的改动不要 reset / stash，用 kb_ask 问。"""}
{('- 待办：' + todo) if todo else ''}
你这个端要做的（拍板方案里的改动）：
{chr(10).join('- ' + c for c in mine.get('改动') or []) or '- （方案没列具体改动，按需求自己定）'}
涉及你这个端的需求：{'、'.join(r['编号'] + ' ' + r.get('标题', '') for r in reqs) or '（看 spec.md）'}

开发方式：{('按这个仓库的开发流程「' + f['名称'] + '」：' + chr(10) + steps) if f else '按仓库现有约定（看仓库里的 AGENTS.md / CLAUDE.md / README）'}
约定：
- {'服务端已经做完并通过审查，客户端可以直接接真实接口。' if server_ok or end == '服务端' else '服务端接口可能还没做好：客户端先按接口契约写 mock（优先用项目已有的 mock 方式），做成一键切换，联调时再切真实接口。'}
- 服务端：按契约实现接口和数据变更，写接口测试（至少覆盖契约里的每个接口的成功和主要错误码）。
{_SVN_RULE if svn else '- 提交按仓库惯例，提交说明里带需求编号（如 feat(xxx): … REQ-001）；不要 push；只改这个端的仓库。'}
- 做的过程中发现：需求得改、别的端也必须配合 / 兼容、接口契约得改、方案漏了东西——不要自己去改别的端或契约，
  用 kb_stack_change（iteration=「{d.name}」，from_end={end}）提出来（说清为什么、影响哪些端），然后继续做不受影响的部分；
  用户拍板后你会收到要补做的内容。
- 做完自测：能编译、相关测试能跑过；有界面的截图留证据（放仓库外的临时目录，路径写进汇报）。
最后用 kb_stack_report 汇报一次（iteration=「{d.name}」，end={end}）：status 完成 / 卡住；summary 做了什么；
reqs 每个需求的完成度（完成 / 部分 / 没做 + 原因）；evidence 自测证据（编译、测试结果、截图路径）；commits {'留空（svn 不提交），在 summary 里列改了哪些文件' if svn else '提交号'}。""" + _NO_BG


_SVN_RULE = ('- 这是 svn 工作副本：【不要 svn commit】（svn 一提交就直接进服务器，要等审查通过、用户验收后由知识库统一提交）；'
             '新文件 svn add、删文件 svn delete、改名 svn move，让 svn status 能看到全部改动；不要 svn revert 不是你改的文件；只改这个端的仓库。')


def _vcs_lines(root, branch):
    return (f'- 仓库：{root}（svn 工作副本），分支：{branch or "（工作副本当前对应的目录）"}\n'
            f'  先 svn update；{"不在这个分支就 svn switch ^/" + branch + "（分支目录不存在就 kb_ask，不要自己 svn copy 建分支）" if branch else "不要 svn switch"}；'
            '工作副本里有别人没提交的改动，不要 revert，用 kb_ask 问。')


def _spawn(d, end, kind, prompt, root, resume='', readonly=False):
    m = load_meta(d)
    eng = role_engine('开发' if kind == '开发' else '审查', m, end)
    (d / DEV_DIR).mkdir(exist_ok=True)
    logf = d / DEV_DIR / f'{end}{kind}-{datetime.now():%Y%m%d-%H%M%S}.jsonl'
    x = m['各端开发'][end]
    if hosts.is_remote(root):
        proc = _remote_popen(d, end, root, eng, prompt, f'kb·{d.name}·{end}{kind}', logf, resume, readonly)
    else:
        env = dict(_dev_env(d.name, x.get('分支', ''), root), KB_SESSION=f'end:{end}')
        proc = engine_popen(eng, prompt, f'kb·{d.name}·{end}{kind}', logf, root, resume_id=resume, env_extra=env,
                            extra_args=_readonly(eng) if readonly else None)
    _PROCS[(d.name, end, '开发中' if kind == '开发' else '审查中')] = proc

    def wait():
        code = proc.wait()
        _PROCS.pop((d.name, end, '开发中' if kind == '开发' else '审查中'), None)
        _finish(d.name, end, '开发中' if kind == '开发' else '审查中', code)
        try:
            stack_tick(d.name)
        except Exception:      # noqa: BLE001 — 后台线程
            pass
    threading.Thread(target=wait, daemon=True).start()
    return proc, logf, eng


def _start_dev(d, end):
    m = load_meta(d)
    x = m['各端开发'][end]
    root = x['仓库']
    plan = _plan(d)
    issues = (x.get('审查') or {}).get('问题') if x['状态'] == '打回修改' else None
    if not x.get('版本库'):
        x['版本库'] = hosts.vcs(root) or 'git'
    if not x.get('起点'):
        x['起点'] = hosts.head(root, x['版本库'])
        if x['版本库'] == 'svn':           # 开工前工作副本里原有的改动：验收提交时不碰
            ch, new = hosts.svn_changes(root)
            x['原有改动'] = [pth for _, pth in ch] + new
    resume = x.get('会话', '') if issues is not None else ''
    prompt = _dev_prompt(d, m, end, x, plan, issues if resume else None, x.pop('待办', ''))
    if issues is not None and not resume:          # 会话号丢了：新开，带上打回的问题
        prompt += '\n\n上一轮审查打回的问题：\n' + '\n'.join(f'- {i.get("需求", "")} {i.get("问题", "")}' for i in issues)
    srv = next((p for p in plan['各端'] if p['端'] == '服务端' and p.get('涉及')), None)
    if end != '服务端' and srv and (m.get('各端开发') or {}).get('服务端', {}).get('状态') != '审查通过' and not x.get('联调'):
        x['用mock'] = True                 # 服务端还没过：这一轮按契约 mock，服务端通过后再排一轮联调
    x.update(状态='开发中', 开始时间=now(), 结束时间='')
    x.pop('等待', None)
    save_meta(d, m)
    proc, logf, eng = _spawn(d, end, '开发', prompt, root, resume)
    m = load_meta(d)
    m['各端开发'][end].update(pid=proc.pid, 日志=str(logf), 引擎=eng['名称'])
    save_meta(d, m)
    log(d, '各端开发', f'{end} 开始{"按审查意见修改（第 " + str(x["轮次"]) + " 轮）" if issues is not None else "开发"}（{eng["名称"]}，{root}）')


# ---------------------------------------------------------------- 审查会话（只读）
def _review_prompt(d, m, end, x, plan):
    ver, cp = _contract(d, m)
    rep = x.get('汇报') or {}
    return f"""你是由知识库网页启动的【后台无人值守、只读】{end} 代码审查会话：期「{d.name}」。不要改任何文件、不要提交、不要提问。
另一个 AI 会话刚做完 {end} 这个端，你要独立挑错（不要相信它的自述，以代码为准）。
- 需求规格：{_sdir(d) / 'spec.md'}（逐条看涉及 {end} 的需求和验收标准）
- 接口契约：{cp or '本期不涉及接口'}{f'（{ver}）' if cp else ''}
- 设计稿：kb_period（name=「{d.name}」）里的设计图
{_review_diff(x)}
- 开发会话的汇报：{rep.get('总结', '')}；自测证据：{rep.get('证据', '')}

逐项检查：
1. 需求覆盖：涉及 {end} 的每条需求、每条验收标准，代码里有没有实现；漏的、做偏的。
2. 契约一致：接口路径、方法、参数、字段名和类型、错误码，服务端实现 / 客户端调用是否和契约一致（客户端的 mock 也要和契约一致）。
3. 设计一致（有界面的端）：页面元素、文案、状态（空态 / 加载 / 报错 / 无网）是否和设计稿、需求一致。
4. 明显的缺陷：空指针、线程、泄漏、异常没处理、安全（鉴权、注入、敏感信息）、改了不该改的地方。
5. 证据：说编译过 / 测试过的，能不能在仓库里找到对应的测试；没有证据的标出来。
只报真实问题，不报风格偏好。严重度：高 = 需求没做到 / 会出错；中 = 做偏了 / 缺状态；低 = 可以以后再改。
最后用 kb_stack_review 交回一次（iteration=「{d.name}」，end={end}）：verdict 通过（没有「高」和「中」）/ 打回；
issues：[{{"需求": "REQ-001", "严重度": "高/中/低", "问题": "…", "位置": "文件:行"}}]；summary 一两句。""" + _NO_BG


def _review_diff(x):
    if x.get('版本库') != 'svn':
        return f"- 这次的改动：仓库 {x['仓库']}，git diff {x.get('起点') or 'HEAD~1'}..HEAD（先 git log --oneline {x.get('起点') or 'HEAD~1'}..HEAD 看提交）"
    pre = x.get('原有改动') or []
    return (f"- 这次的改动：svn 工作副本 {x['仓库']} 里还没提交的改动（开工时是 r{x.get('起点') or '?'}，改动都没提交）："
            "先 svn status 看改了哪些文件，再 svn diff 看内容；「?」开头的是没 svn add 的新文件，也要看，并作为问题指出（没加入版本控制就提交不上）。"
            + (f"\n  这些是开工前就有的改动，不算这次的：{'、'.join(pre[:30])}" if pre else '')
            + '\n  不要 svn commit / update / revert / switch。')


def _start_review(d, end):
    m = load_meta(d)
    x = m['各端开发'][end]
    x.update(状态='审查中', 审查开始=now())
    save_meta(d, m)
    proc, logf, eng = _spawn(d, end, '审查', _review_prompt(d, m, end, x, _plan(d)), x['仓库'], readonly=True)
    m = load_meta(d)
    m['各端开发'][end].update(pid=proc.pid, 审查日志=str(logf))
    save_meta(d, m)
    log(d, '各端开发', f'{end} 开始审查（只读，{eng["名称"]}）')


# ---------------------------------------------------------------- 汇报、审查结论、收尾
def stack_report(name, end, status, summary='', reqs=None, evidence='', commits='', by='Claude'):
    """kb_stack_report：开发会话做完汇报。"""
    d = period_dir(name)
    m = load_meta(d)
    x = (m.get('各端开发') or {}).get(end)
    if not x:
        raise KBError(f'{end} 没有开工')
    if status not in ('完成', '卡住'):
        raise KBError('status 只能是 完成 / 卡住')
    if isinstance(reqs, str):
        try:
            reqs = json.loads(reqs) if reqs.strip() else {}
        except ValueError:
            reqs = {'说明': reqs}
    x['汇报'] = {'状态': status, '总结': (summary or '').strip(), '需求': reqs or {}, '证据': (evidence or '').strip(),
               '提交': (commits or '').strip(), '时间': now()}
    x['汇报结果'] = status
    save_meta(d, m)
    log(d, '各端开发', f'{end} 汇报：{status}；{(summary or "")[:200]}（{by}）')
    return '已收到汇报；' + ('结束这次会话后会有独立的审查会话检查' if status == '完成' else '会停下等用户看')


def stack_review(name, end, verdict, issues=None, summary='', by='Claude'):
    """kb_stack_review：审查会话的结论。"""
    d = period_dir(name)
    m = load_meta(d)
    x = (m.get('各端开发') or {}).get(end)
    if not x:
        raise KBError(f'{end} 没有开工')
    if verdict not in ('通过', '打回'):
        raise KBError('verdict 只能是 通过 / 打回')
    if isinstance(issues, str):
        try:
            issues = json.loads(issues) if issues.strip() else []
        except ValueError:
            issues = [{'问题': issues, '严重度': '中'}]
    issues = issues or []
    x['审查'] = {'结论': verdict, '问题': issues, '总结': (summary or '').strip(), '时间': now(), '轮次': x.get('轮次', 0)}
    save_meta(d, m)
    log(d, '各端开发', f'{end} 审查：{verdict}，问题 {len(issues)} 个；{(summary or "")[:160]}（{by}）')
    return '已记下审查结论'


def _finish(name, end, phase, code=None):
    """会话结束：开发 → 有汇报就待审查；审查 → 按结论打回 / 通过 / 要你看。"""
    d = period_dir(name)
    m = load_meta(d)
    x = (m.get('各端开发') or {}).get(end)
    if not x or x.get('状态') != phase:
        return
    res = _dev_result(x.get('日志' if phase == '开发中' else '审查日志', ''))
    if phase == '开发中':
        sid = _session_id(x.get('日志', ''))
        if sid:
            x['会话'] = sid
        rep = x.pop('汇报结果', '')
        if rep == '完成':
            x['状态'] = '待审查'
        else:
            x.update(状态='要你看' if rep == '卡住' else '失败', 结束时间=now(), 结果=(res.get('结果') or '')[:800] or f'退出码 {code}')
    else:
        rv = x.get('审查') or {}
        if rv.get('时间', '') < x.get('审查开始', ''):        # 审查会话没交结论
            x.update(状态='要你看', 结束时间=now(), 结果='审查会话没有交回结论：' + (res.get('结果') or '')[:500])
        elif rv['结论'] == '通过':
            x.update(状态='审查通过', 结束时间=now())
        elif x.get('轮次', 0) < MAX_ROUNDS:
            x.update(状态='打回修改', 轮次=x.get('轮次', 0) + 1)
        else:
            x.update(状态='要你看', 结束时间=now(), 结果=f'审查打回 {MAX_ROUNDS} 轮还没过')
    if end == '服务端' and x['状态'] == '审查通过':
        _queue_integration(d, m)
    save_meta(d, m)
    log(d, '各端开发', f'{end} {"开发" if phase == "开发中" else "审查"}会话结束 → {x["状态"]}')
    dev = m.get('各端开发') or {}
    if dev and all(v.get('状态') in ('审查通过', '要你看', '失败', '已停止') for v in dev.values()):
        st = m.get('全栈') or {}
        if st.get('状态') == '开发中':
            st['状态'] = '各端完成'
            m['全栈'] = st
            save_meta(d, m)
            ok = [e for e, v in dev.items() if v['状态'] == '审查通过']
            log(d, '全栈', f'各端都结束了：通过 {"、".join(ok) or "无"}；其余要你看')
            _notify('知识库 · 全栈', f'「{d.name}」各端都结束了，通过 {len(ok)}/{len(dev)}')
    elif x['状态'] in ('要你看', '失败'):
        _notify('知识库 · 全栈', f'「{d.name}」{end}：{x["状态"]}')


def _queue_integration(d, m):
    """服务端审查通过：之前按 mock 做的客户端排一轮联调（切真实接口，按验收标准跑通）。m 由调用方保存。"""
    note = ('服务端已经做完并通过审查：把这个端的 mock 切成真实接口联调，按 spec.md 里涉及这个端的验收标准逐条跑通'
            '（服务端怎么在本机 / 测试环境起来，看服务端仓库的 README，或 kb_base 里的环境信息，找不到用 kb_ask）；有问题按约定修、提交，再汇报')
    for e, x in (m.get('各端开发') or {}).items():
        if e == '服务端' or not x.get('用mock'):
            continue
        x.update(用mock=False, 联调=True)
        if x.get('状态') in RUNNING and _alive(x.get('pid', 0)):
            m.setdefault('对话', []).append({'时间': now(), '内容': note, '方式': '联调', '状态': '待送达', '会话': f'end:{e}',
                                            '目标': f'{e}开发', '显示': '服务端已通过：切真实接口联调'})
        else:
            x.update(状态='排队中', 待办=note, 排队时间=now(), 轮次=0)
        log(d, '各端开发', f'{e} 排上联调（服务端已通过审查）')


def _end_reqs(plan, e):
    return {r['编号']: json.dumps(r, sort_keys=True, ensure_ascii=False) for r in plan.get('需求') or [] if e in (r.get('端') or [])}


def plan_changed(d, old, new, ver=''):
    """开发中又拍板了方案（变更、重出方案）：新加入的端开工；需求 / 改动 / 契约有变化的端补做（在跑的发消息，结束的重新排队）。"""
    m = load_meta(d)
    dev = m.setdefault('各端开发', {})
    ends = period_ends(d, m)
    pv = (m.get('全栈') or {}).get('方案版本', '')
    oldI = {x['端']: x for x in old.get('各端') or [] if x.get('涉及')}
    newI = {x['端']: x for x in new.get('各端') or [] if x.get('涉及')}
    out = []
    for e, x in newI.items():
        ro, rn = _end_reqs(old, e), _end_reqs(new, e)
        add = [k for k in rn if k not in ro]
        chg = [k for k in rn if k in ro and rn[k] != ro[k]]
        newc = [c for c in x.get('改动') or [] if c not in (oldI.get(e) or {}).get('改动', [])]
        uses = e == '服务端' or any(e in (a.get('调用端') or []) for a in new.get('接口') or [])
        parts = ([f'新需求 {"、".join(add)}'] if add else []) + ([f'改了的需求 {"、".join(chg)}'] if chg else []) \
            + (['新改动：' + '；'.join(newc)] if newc else []) \
            + ([f'接口契约更新到 {ver}（{_sdir(d) / "api" / f"openapi.{ver}.yaml"}），和上一版对比后调整实现 / 调用 / mock'] if ver and uses else [])
        if e not in dev:
            if e not in ends:
                out.append(f'{e} 要做但还没选仓库（选好后自动开工）')
                continue
            dev[e] = {'状态': '排队中', '轮次': 0, '排队时间': now(), '仓库': ends[e]['仓库'], '分支': ends[e].get('分支', ''), '版本库': ends[e].get('版本库', ''),
                      '待办': f'方案 {pv} 变更后这个端新加入：' + ('；'.join(parts) or '按 spec.md 里涉及这个端的需求做')}
            out.append(f'{e} 新加入，排队开工')
            continue
        if not parts:
            continue
        todo = f'方案变更（{pv}）：' + '；'.join(parts) + '。看 spec.md 里对应的需求，补做、自测、提交，再汇报'
        cur = dev[e]
        if cur.get('状态') in RUNNING and _alive(cur.get('pid', 0)):
            m.setdefault('对话', []).append({'时间': now(), '内容': todo, '方式': '方案变更', '状态': '待送达', '会话': f'end:{e}',
                                            '目标': f'{e}开发', '显示': f'方案 {pv} 变更：{"；".join(parts)[:40]}'})
            out.append(f'{e}（在跑）已通知')
        else:
            if cur.get('已推送') or cur.get('已提交'):       # 验收送上服务器之后又改：重新记起点，下次验收再推送 / 提交
                for k in ('已推送', '已提交', '起点', '原有改动'):
                    cur.pop(k, None)
            cur.update(状态='排队中', 待办=todo, 排队时间=now(), 轮次=0)
            out.append(f'{e} 重新排队补做')
    for e in oldI:
        if e not in newI and e in dev and dev[e].get('状态') in RUNNING and _alive(dev[e].get('pid', 0)):
            m.setdefault('对话', []).append({'时间': now(), '内容': '方案变更后这个端不再涉及：停下手头的事，提交已完成的部分，用 kb_stack_report 汇报现状',
                                            '方式': '方案变更', '状态': '待送达', '会话': f'end:{e}', '目标': f'{e}开发', '显示': '不再涉及，停下汇报'})
            out.append(f'{e} 不再涉及，已通知停下')
    st = m.get('全栈') or {}
    if any(x.get('状态') not in ('审查通过', '要你看', '失败', '已停止') for x in dev.values()):
        st['状态'] = '开发中'
    m['全栈'] = st
    save_meta(d, m)
    log(d, '各端开发', f'方案 {pv} 变更：' + ('；'.join(out) or '各端都不用补做'))
    stack_tick(d.name)
    return '；'.join(out) or '各端都不用补做'


def contract_changed(d, ver):          # 兼容旧调用
    m = load_meta(d)
    p = _plan(d)
    return plan_changed(d, p, p, ver)


# ---------------------------------------------------------------- 证据包、验收（拍板 2）
def evidence(d, m, plan):
    """需求 × 端：完成度（开发会话的汇报）、审查结论、问题数。"""
    if not plan:
        return None
    dev = m.get('各端开发') or {}
    rows = []
    for r in plan.get('需求') or []:
        cells = {}
        for e in r.get('端') or []:
            x = dev.get(e) or {}
            rep = ((x.get('汇报') or {}).get('需求') or {})
            rv = x.get('审查') or {}
            iss = [i for i in rv.get('问题') or [] if i.get('需求') == r['编号']]
            cells[e] = {'完成度': rep.get(r['编号'], '') if isinstance(rep, dict) else '', '审查': rv.get('结论', ''),
                        '问题': len(iss), '高': sum(1 for i in iss if i.get('严重度') == '高'), '状态': x.get('状态', '未开工')}
        rows.append({'编号': r['编号'], '标题': r.get('标题', ''), '验收': len(r.get('验收') or []), '端': cells})
    ok = all(c['审查'] == '通过' and str(c['完成度']).startswith('完成') for row in rows for c in row['端'].values())
    return {'需求': rows, '全部通过': ok and bool(rows), '可验收': (m.get('全栈') or {}).get('状态') == '各端完成'}


def stack_accept(name, by='用户（网页）'):
    """拍板 2（只能本人在网页点）：看过证据包，验收通过，这一期进入提测 / Bug 阶段。"""
    d = period_dir(name)
    m = load_meta(d)
    st = m.get('全栈') or {}
    if st.get('状态') != '各端完成':
        raise KBError('各端还没都结束')
    plan = _plan(d)
    ev = evidence(d, m, plan) or {}
    done = _publish_ends(d, m, plan)               # 验收才进服务器：git 推送、svn 提交（失败就不验收，处理后再点）
    st.update(状态='已验收', 验收时间=now(), 验收人=by, 验收时全部通过=ev.get('全部通过', False))
    m['全栈'] = st
    save_meta(d, m)
    log(d, '全栈', f'验收（拍板 2）' + ('' if ev.get('全部通过') else '：有没完全通过的需求，带着问题验收') + f'（{by}）')
    if m.get('状态') != '已完成':
        set_status(d.name, '已完成', '全栈验收通过（本人）', by_human=True)
    return '已验收，这一期标为已完成' + (f'；{"；".join(done)}' if done else '') + '；后续 Bug 照常同步、分析、修复'


def _git_push_end(d, e, x):
    """git 的端：把开发分支推到远端（只推这一个分支）。→ 一句结果；推不上抛错。"""
    root = x['仓库']
    g = lambda *a, t=60: hosts.git(root, *a, timeout=t)
    b = x.get('分支') or g('branch', '--show-current').stdout.strip()
    if not b:
        raise KBError(f'{e}：仓库不在任何分支上（游离 HEAD），不知道推哪个分支；切到开发分支后再验收')
    if g('rev-parse', '--verify', '--quiet', f'refs/heads/{b}').returncode:
        raise KBError(f'{e}：本地没有分支 {b}')
    n = g('rev-list', '--count', f'{x["起点"]}..refs/heads/{b}').stdout.strip() if x.get('起点') else '1'
    if n == '0':
        x['已推送'] = '无改动'
        return f'{e}（git）分支 {b} 没有新提交，不用推送'
    rs = g('remote').stdout.split()
    remote = 'origin' if 'origin' in rs else (rs[0] if rs else '')
    if not remote:
        x['已推送'] = '没有远端'
        return f'{e}（git）仓库没有远端，没推送（{n} 个提交留在本地 {b}）'
    r = hosts.run(root, f'GIT_TERMINAL_PROMPT=0 git push -u {remote} refs/heads/{b}:refs/heads/{b}', timeout=300)
    if r.returncode:
        err = (r.stderr or r.stdout).strip()[-600:]
        hint = ('远端有别人的新提交：先在仓库里 git pull --rebase，解决冲突后再验收' if any(k in err for k in ('rejected', 'fetch first', 'non-fast-forward'))
                else '没有推送权限或要登录：先在那台机器上手动 git push 一次' if any(k in err.lower() for k in ('denied', 'authentication', 'could not read', 'permission')) else '')
        raise KBError(f'{e}：git push 失败' + (f'（{hint}）' if hint else '') + f'：{err}')
    sha = g('rev-parse', '--short', f'refs/heads/{b}').stdout.strip()
    x.update(已推送=f'{remote}/{b}@{sha}', 推送时间=now())
    dirty = g('status', '--porcelain', '--untracked-files=no').stdout.strip()
    log(d, '各端开发', f'{e} 验收后推送 {remote}/{b}（{n} 个提交，{sha}）')
    return f'{e}（git）已推送 {remote}/{b}，{n} 个提交' + ('；工作区还有没提交的改动，没推送' if dirty else '')


def _publish_ends(d, m, plan):
    """验收时把审查通过的各端送上服务器：git 推送开发分支；svn 只提交这次改的文件（开工前原有的改动不碰）。
    逐端保存，失败后重点验收会跳过已推送 / 已提交的。"""
    out = []
    for e, x in (m.get('各端开发') or {}).items():
        if x.get('版本库') != 'svn':
            if x.get('已推送'):
                continue
            if x.get('状态') != '审查通过':
                out.append(f'{e}（git）没通过审查，没有推送，提交留在本地')
                continue
            out.append(_git_push_end(d, e, x))
            save_meta(d, m)
            continue
        if x.get('已提交'):
            continue
        if x.get('状态') != '审查通过':
            out.append(f'{e}（svn）没通过审查，没有提交，改动留在工作副本里')
            continue
        ch, new = hosts.svn_changes(x['仓库'])
        pre = set(x.get('原有改动') or [])
        bad = [pth for st, pth in ch if st in 'C!~']
        if bad:
            raise KBError(f'{e} 的 svn 工作副本有冲突或丢失的文件：{"、".join(bad[:10])}；处理好后再点验收')
        mine = [pth for _, pth in ch if pth not in pre]
        mixed = [q for q in pre if any(q.startswith(pth + '/') for pth in mine)]
        if mixed:
            raise KBError(f'{e}：要提交的目录下有开工前就有的改动（{"、".join(mixed[:5])}），自动提交会把它们混进去；先手动处理再验收')
        loose = [pth for pth in new if pth not in pre]
        if not mine:
            x['已提交'] = '无改动'
            out.append(f'{e}（svn）工作副本没有改动，不用提交')
        else:
            reqs = [r['编号'] for r in plan.get('需求') or [] if e in (r.get('端') or [])]
            rev = hosts.svn_commit(x['仓库'], mine, f'{d.name}（{e}）' + (f'：{"、".join(reqs)}' if reqs else ''))
            x.update(已提交=rev, 提交文件=len(mine), 提交时间=now())
            out.append(f'{e}（svn）已提交 r{rev}，{len(mine)} 个文件')
            log(d, '各端开发', f'{e} 验收后 svn 提交 r{rev}（{len(mine)} 个文件）')
        if loose:
            out.append(f'{e} 还有 {len(loose)} 个新文件没 svn add、没提交：{"、".join(loose[:5])}')
        save_meta(d, m)
    return out


# ---------------------------------------------------------------- 远程机器上的会话：ssh 起 claude，反向通道接本机知识库
KB_WEB_PORT = int(os.environ.get('KB_WEB_PORT') or 11555)
REMOTE_TOKENS = {}          # 令牌 → 会话身份（KB_PERIOD / KB_SESSION）；只在网页服务内存里，重启后远程会话要重新开工


def stackdev_port(port):
    global KB_WEB_PORT
    KB_WEB_PORT = int(port)


def remote_session(token):
    return REMOTE_TOKENS.get(token)


def _remote_popen(d, end, root, eng, prompt, title, logf, resume, readonly):
    if not (eng.get('id') == 'claude' or Path(eng.get('命令') or '').name == 'claude'):
        raise KBError('远程机器上的开发会话目前只支持 Claude Code 引擎')
    r = hosts.parse(root)
    tok = secrets.token_hex(16)
    REMOTE_TOKENS[tok] = {'KB_PERIOD': d.name, 'KB_SESSION': f'end:{end}', '时间': now(), '端': end}
    rport = random.randint(21000, 29000)
    cfg = json.dumps({'mcpServers': {'kb': {'type': 'http', 'url': f'http://127.0.0.1:{rport}/mcp',
                                            'headers': {'Authorization': f'Bearer {tok}'}}}})
    args = engine_cmd(eng, prompt, title, resume)[1:] + ['--mcp-config', cfg] + (_readonly(eng) if readonly else [])
    remote = f'cd {shlex.quote(r["路径"])} && claude ' + ' '.join(shlex.quote(a) for a in args)
    cmd = ['ssh', *hosts.SSH_OPTS, *(['-p', r['端口']] if r['端口'] else []), '-o', 'ExitOnForwardFailure=yes',
           '-R', f'{rport}:127.0.0.1:{KB_WEB_PORT}', r['主机'], 'bash -lc ' + shlex.quote(remote)]
    with open(logf, 'ab') as fh:
        fh.write((json.dumps({'type': 'kb.engine', 'engine': eng['id'], 'format': eng.get('输出格式'), 'remote': r['主机']},
                             ensure_ascii=False) + '\n').encode())
        fh.flush()
        return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)


def stack_dev_view(d, m):
    dev = m.get('各端开发') or {}
    out = []
    for e in ENDS:
        x = dev.get(e)
        if not x:
            continue
        out.append({'端': e, **{k: x.get(k) for k in ('状态', '轮次', '开始时间', '结束时间', '引擎', '等待', '结果', '汇报', '审查', '仓库', '分支', '版本库', '已提交', '已推送')},
                    '在跑': x.get('状态') in RUNNING and _alive(x.get('pid', 0))})
    return out


def sessions_of(d):
    """给「跟这一期说」：在跑的各端会话。"""
    m = load_meta(d)
    return [{'键': f'end:{e}', '名称': f'{e}{"审查" if x["状态"] == "审查中" else "开发"}', '开始': x.get('开始时间', ''), '可打断': False}
            for e, x in (m.get('各端开发') or {}).items() if x.get('状态') in RUNNING and _alive(x.get('pid', 0))]
