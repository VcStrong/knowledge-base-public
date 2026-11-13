# From 大大王.DT
"""开发会话：启动 / 停止、待确认问题、网页对话。"""
from .infra import devlock
import json
import os
import re
import signal
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from .common import DEV_OK, KBError, ROOT, now, sess_env
from .periods import load_meta, log, period_dir, period_names, save_meta, set_status
from .flows import flow_done, flow_for, flow_text, get_flow, period_flow
from .engines import engine_bin, engine_popen, period_engine
from .plugins import _sources_prompt, run_plugins
from .devprep import _dev_target, _git, _git_root, _no_flow_msg, _sdd_repo
from . import hosts
from . import lazy
_talk = lazy('kblib.talk')
_devices = lazy('kblib.devices')      # 上层模块：用到时才 import（不形成循环）


# 网页「开始开发」= 用户本人批准 + 在目标仓库后台启动 Claude Code（claude -p，auto 权限）跑 /sdd* 流程。
# 需要人确认的地方走 kb_ask → 网页回答 → kb_wait_answer；开启免打扰后由 AI 按自己的建议决策。
DEV_DIR = '开发会话'
_PROCS = {}  # 期名 → Popen（只在启动它的网页进程里有）
_TRACK = {}              # 期名 → {pid: 启动时间}：后台会话派生过的所有进程（含已脱离进程组的后台命令）
MAX_RESUME = 30          # 会话没做完就退出时，最多自动续跑几次
_NO_BG = """
【重要】你运行在无人值守的单次运行模式（如 claude -p / codex exec）：你一结束回复，进程就退出，后台运行的子 agent 和后台命令会被一起终止。
所以不要用 run_in_background 启动子 agent 或命令后就结束回复；开发流程要求后台运行的，也改为前台运行并等它完成，
或启动后持续等待（查看输出、sleep 轮询）直到完成再继续。只有全部完成、或在 kb_wait_answer 里等待用户时才可以停。"""


def _notify(title, text):
    esc = lambda x: re.sub(r'\s+', ' ', x).replace('\\', '\\\\').replace('"', '\\"')
    try:
        subprocess.Popen(['osascript', '-e', f'display notification "{esc(text)[:120]}" with title "{esc(title)[:60]}" sound name "Glass"'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def set_dnd(period, on, by='用户'):
    d = period_dir(period)
    m = load_meta(d)
    m['免打扰'] = bool(on)
    if on:  # 正在等的问题按 AI 建议收掉
        for q in m.get('待确认') or []:
            if q['状态'] == '待回答':
                q.update(状态='AI决策', 回答=q.get('AI建议') or '（AI 自行决策）', 回答人='AI（免打扰）', 回答时间=now())
    save_meta(d, m)
    log(d, '免打扰', f'{"开启" if on else "关闭"}（{by}）')
    return f'{d.name} 免打扰已{"开启：后续需要确认的地方由 AI 自行决策" if on else "关闭：需要确认时会在网页等你回答"}'


def ask(period, question, context='', options=None, recommend='', files=None, stage=''):
    d = period_dir(period)
    m = load_meta(d)
    if not (question or '').strip():
        raise KBError('问题不能为空')
    qs = m.setdefault('待确认', [])
    qid = f'Q{len(qs) + 1:03d}'
    q = {'编号': qid, '时间': now(), '阶段': (stage or '').strip(), '问题': question.strip(),
         '背景': (context or '').strip(), '选项': [str(x).strip() for x in options or [] if str(x).strip()],
         'AI建议': (recommend or '').strip(), '文件': [str(x) for x in files or []],
         '状态': '待回答', '回答': '', '回答人': '', '回答时间': ''}
    dnd = bool(m.get('免打扰'))
    if dnd:
        q.update(状态='AI决策', 回答=q['AI建议'] or '（AI 自行决策）', 回答人='AI（免打扰）', 回答时间=now())
    qs.append(q)
    save_meta(d, m)
    log(d, '待确认' if not dnd else '免打扰决策', f'{qid} {q["问题"][:80]}' + (f' → {q["回答"][:60]}' if dnd else ''))
    if dnd:
        return (f'{qid}：免打扰已开启，不用等待。按你的建议执行：{q["AI建议"] or "（未给建议，自行选最稳妥的方案）"}；'
                '并用 kb_log 记录理由。')
    _notify(f'知识库 · {d.name} 需要确认', q['问题'])
    return (f'{qid} 已发到网页，等待用户确认。现在调用 kb_wait_answer(iteration="{d.name}", id="{qid}") 等待；'
            '拿到回答前不要继续做依赖它的事，也不要自行决定。')


def wait_answer(period, qid, timeout=240):
    end = time.time() + min(max(int(timeout or 240), 10), 600)
    while True:
        d = period_dir(period)
        m = load_meta(d)
        q = next((x for x in m.get('待确认') or [] if x['编号'] == qid), None)
        if not q:
            raise KBError(f'没有这个待确认问题：{qid}')
        if q['状态'] == '待回答' and m.get('免打扰'):
            q.update(状态='AI决策', 回答=q.get('AI建议') or '（AI 自行决策）', 回答人='AI（免打扰）', 回答时间=now())
            save_meta(d, m)
            log(d, '免打扰决策', f'{qid} → {q["回答"][:60]}')
        if q['状态'] == '已回答':
            return (f'{qid} 用户已回答（{q["回答时间"]}）：{q["回答"]}\n'
                    '按回答执行；需要时把回答写回对应的流程文档（如待确认表的确认备注），再继续流程。')
        if q['状态'] == 'AI决策':
            return f'{qid}：免打扰已开启，按你的建议执行（{q["回答"]}），并用 kb_log 记录理由。'
        if q['状态'] == '已撤回':
            return f'{qid} 已撤回（用户停止了开发）。停止当前工作，不要再继续。'
        if _pending_chat(m):
            return f'{qid} 用户还没回答，但先发来了别的消息（见下方），请先处理，处理完再调用 kb_wait_answer 继续等 {qid}。'
        if time.time() >= end:
            return f'{qid} 用户还没回答。再次调用 kb_wait_answer 继续等待，不要自行决定。'
        time.sleep(3)


def answer(period, qid, text, by='用户'):
    """只给网页用（用户本人回答），不作为 MCP 工具提供。"""
    d = period_dir(period)
    m = load_meta(d)
    q = next((x for x in m.get('待确认') or [] if x['编号'] == qid), None)
    if not q:
        raise KBError(f'没有这个待确认问题：{qid}')
    if not (text or '').strip():
        raise KBError('回答不能为空')
    q.update(状态='已回答', 回答=text.strip(), 回答人=by, 回答时间=now())
    save_meta(d, m)
    log(d, '确认', f'{qid} {q["问题"][:40]} → {text.strip()[:80]}')
    return f'已回答 {qid}'


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _result_of(text, fmt='', limit=2000):
    """从引擎输出里取最后结果：Claude / Hermes 的 result 行、Codex 最后一条 agent_message，纯文本取末尾。"""
    last_text, failed, plain = '', False, []
    for line in (text or '').splitlines():
        try:
            j = json.loads(line)
        except ValueError:
            if line.strip():
                plain.append(line)
            continue
        if not isinstance(j, dict):
            continue
        t = j.get('type')
        if t == 'result' and 'exit_code' not in j:            # Claude
            return {'结果': (j.get('result') or '')[:limit], '出错': bool(j.get('is_error')),
                    '轮数': j.get('num_turns'), '费用': j.get('total_cost_usd')}
        if t == 'result':                                      # Hermes
            return {'结果': (j.get('result') or j.get('text') or last_text)[:limit], '出错': j.get('exit_code') not in (0, None)}
        if t == 'text' and j.get('text'):
            last_text = j['text']
        elif t == 'item.completed' and (j.get('item') or {}).get('type') == 'agent_message':
            last_text, failed = j['item'].get('text') or '', False
        elif t in ('turn.failed', 'error'):
            failed = True
            last_text = last_text or str((j.get('error') or {}).get('message') or j.get('message') or '')
    if last_text or failed:
        return {'结果': last_text[:limit], '出错': failed}
    if fmt == '纯文本' and plain:
        return {'结果': '\n'.join(plain[-30:])[-limit:], '出错': False}
    return {}


def _dev_result(logf):
    """日志里的最后结果：结束原因、轮数、费用（按各引擎的输出格式）。"""
    try:
        with open(logf, 'rb') as fh:
            head = fh.readline().decode('utf-8', 'ignore')
            fh.seek(max(0, Path(logf).stat().st_size - 400000))
            tail = fh.read().decode('utf-8', 'ignore')
    except OSError:
        return {}
    try:
        fmt = json.loads(head).get('format', '') if head.startswith('{"type": "kb.engine"') else ''
    except ValueError:
        fmt = ''
    return _result_of(tail, fmt)


def _session_id(logf):
    """会话号：Claude / Hermes 的 session_id，Codex 的 thread_id。"""
    try:
        with open(logf, encoding='utf-8', errors='ignore') as fh:
            for line in fh:
                if '"session_id"' in line or '"thread_id"' in line:
                    j = json.loads(line)
                    sid = j.get('session_id') or j.get('thread_id')
                    if sid:
                        return sid
    except (OSError, ValueError):
        pass
    return ''


def _ps():
    try:
        out = subprocess.run(['ps', '-axo', 'pid=,ppid=,pgid=,lstart='], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    rows = {}
    for line in out.splitlines():
        x = line.split(None, 3)
        if len(x) == 4 and x[0].isdigit():
            rows[int(x[0])] = (int(x[1]), int(x[2]), x[3].strip())
    return rows


def _track(roots, known=None):
    """把 roots 的子孙进程（按父进程、以及已知进程所在的进程组）并入 known。父进程退出后被孤立的也能通过进程组找回。"""
    rows, known = _ps(), dict(known or {})
    found = {p for p in roots if p in rows} | {p for p, st in known.items() if p in rows and rows[p][2] == st}
    groups = {rows[p][1] for p in found}
    grow = True
    while grow:
        grow = False
        for pid, (pp, pg, _) in rows.items():
            if pid not in found and pid != os.getpid() and (pp in found or pg in groups):
                found.add(pid)
                groups.add(pg)
                grow = True
    for p in found:
        known[p] = rows[p][2]
    return known


def _kill_tracked(known):
    """结束记录过的进程（启动时间对得上才杀，防止 pid 被系统复用）。返回没杀掉的。"""
    known = _track([], known)
    rows = _ps()
    pids = [p for p, st in known.items() if p in rows and rows[p][2] == st and p != os.getpid()]
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in pids:
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
        time.sleep(1.5)
        pids = [p for p in pids if _alive(p)]
        if not pids:
            break
    return pids


def _want_resume(d, m, s, code, res):
    """会话退出了但活没干完：自动续跑。用户停止、出错退出、已完成、流程已走完、次数用完都不续。"""
    retest = s.get('类型') == '复测'
    if code != 0 or s.get('停止中') or s.get('仅对话') or (not retest and m.get('状态') not in DEV_OK):
        return ''
    if s.get('已汇报') if retest else flow_done(session_flow(m), m.get('SDD目录')):
        return ''
    if s.get('续跑次数', 0) >= MAX_RESUME:
        return f'已自动续跑 {MAX_RESUME} 次，不再续跑'
    if s.get('连续空转', 0) >= 3:
        return '连续 3 次很快就退出、没有进展，不再续跑'
    if res.get('出错') and s.get('连续出错', 0) >= 2:
        return '连续出错，不再续跑'
    return 'resume'


def _dev_finish(name, code=None):
    d = period_dir(name)
    m = load_meta(d)
    s = m.get('开发会话') or {}
    if s.get('状态') != '运行中':
        return
    res = _dev_result(s.get('日志', ''))
    if s.get('插话'):       # 用户在网页选了「打断并立即处理」：带着消息接着这次对话续跑
        try:
            # 打断 = 你在指挥正在做的事：处理完接着被打断的工作做，之后照常自动续跑到做完（不再是「答完就结束」）
            _dev_spawn(d, Path(s['仓库']), s.get('分支', ''), _chat_prompt(s['插话'], True),
                       _session_id(s.get('日志', '')), 续跑次数=s.get('续跑次数', 0))
            return
        except (KBError, OSError, KeyError) as e:
            log(d, '对话', f'打断后续跑失败：{e}')
    left = _pending_chat(m)
    if left and not s.get('停止中'):      # 这一轮结束时还有没送到的补充：带着它接着这次对话做，不让补充落空
        for x in left:
            x.update(状态='已送达', 送达时间=now())
        save_meta(d, m)
        try:
            _dev_spawn(d, Path(s['仓库']), s.get('分支', ''), _chat_prompt('\n'.join(x['内容'] for x in left), True),
                       _session_id(s.get('日志', '')), 续跑次数=s.get('续跑次数', 0), 仅对话=s.get('仅对话', False))
            log(d, '对话', f'会话这一轮结束时还有 {len(left)} 条补充没送到，已带着它接着做')
            return
        except (KBError, OSError, KeyError) as e:
            log(d, '对话', f'带着补充续跑失败：{e}')
        m = load_meta(d)
    if code is None and res.get('结果') is not None and not res.get('出错'):
        code = 0       # 不是本进程启动的（服务重启后接管），拿不到退出码：日志里有正常结果就当正常退出
    why = _want_resume(d, m, s, code, res)
    if why == 'resume':
        sid = _session_id(s.get('日志', ''))
        try:
            started = datetime.strptime(s.get('本轮开始') or s.get('开始时间'), '%Y-%m-%d %H:%M')
            quick = (datetime.now() - started).total_seconds() < 120
        except (TypeError, ValueError):
            quick = False
        n = s.get('续跑次数', 0) + 1
        log(d, '自动续跑', f'会话退出但开发还没完成，第 {n} 次自动续跑' + (f'（上一轮：{res.get("结果", "")[:80]}）' if res.get('结果') else ''))
        try:
            prompt = (_devices._retest_resume_prompt(d.name) if s.get('类型') == '复测'
                      else _resume_prompt(d.name, session_flow(m), m.get('SDD目录', '')))
            _dev_spawn(d, Path(s['仓库']), s.get('分支', ''), prompt, sid,
                       续跑次数=n, 连续空转=(s.get('连续空转', 0) + 1) if quick else 0,
                       连续出错=(s.get('连续出错', 0) + 1) if res.get('出错') else 0)
            return
        except (KBError, OSError, KeyError) as e:
            why = f'自动续跑失败：{e}'
    m = load_meta(d)
    s = m.get('开发会话') or {}
    s.update(状态='已结束', 结束时间=now(), 退出码=code, **res)
    if why:
        s['未续跑原因'] = why
    m['开发会话'] = s
    save_meta(d, m)
    log(d, '开发会话结束', f'退出码 {code}' + (f'；{s.get("结果", "")[:100]}' if s.get('结果') else '')
        + (f'；{why}' if why else ''))
    _after_session(d, s)
    _notify(f'知识库 · {d.name}', '后台开发会话已结束' + ('（有错误）' if code else ''))
    try:
        _talk.talk_queue_tick(d.name)          # 排队的跟进内容：会话都结束了就开始处理
    except Exception as e:
        log(d, '排队处理', f'出错：{e}')


# ---- 网页对话：开发面板「最近动作」下的输入框，遇到问题直接跟后台 AI 说
def _pending_chat(m):
    return [x for x in m.get('对话') or [] if x['状态'] == '待送达' and x.get('会话', 'dev') == 'dev']   # an:… 是发给 Bug 会话的


def _take_chat(d, m):
    """把排队的消息交给正在运行的后台会话（附在它下一次调用知识库工具的结果后面）。m 由调用方保存。"""
    if sess_env('KB_PERIOD', d.name) != d.name or sess_env('KB_SESSION', 'dev') != 'dev':
        return ''        # 同一期的 Bug 修复会话也带着 KB_PERIOD，靠 KB_SESSION 区分
    xs = _pending_chat(m)
    if not xs:
        return ''
    for x in xs:
        x.update(状态='已送达', 送达时间=now())
    return ('\n\n【用户在网页发来消息】\n' + '\n'.join(f'- （{x["时间"]}）{x["内容"]}' for x in xs)
            + '\n请先处理：要回答的直接在回复里回答（网页会显示），要做的就去做；处理完接着原来的工作推进。')


def _chat_prompt(text, cont):
    return (f'用户在知识库网页「开发」面板给你发来消息（{now()}）：\n{text}\n\n'
            '请先处理这条消息：要回答的直接在回复里回答（网页会显示你的回复），要做的就去做（规则同前：需要确认用 kb_ask，'
            '不改不该改的状态）。' + ('处理完接着刚才被打断的工作推进，直到做完（复测做完要 kb_test_report）。' if cont
                                    else '用户让你做的事要做完（比如让你接着复测，就测完并 kb_test_report）；'
                                         '只是提问就回答。做完简短说明结果后结束，不要自行开始用户没提到的开发。')
            + _NO_BG)


def dev_chat(period, text, interrupt=False):
    """网页对话。会话在跑：默认排队（下一次调用知识库工具时送达，等待确认时立刻送达），interrupt 则打断当前这一轮、带着消息续跑；
    会话没在跑：接着上一次的对话（保留上下文）回答，答完就结束。不作为 MCP 工具提供。"""
    d = period_dir(period)
    text = (text or '').strip()
    if not text:
        raise KBError('消息不能为空')
    s = dev_session(d.name)
    if not s or not s.get('日志'):
        raise KBError('这一期还没有后台会话，先「开始开发」')
    m = load_meta(d)
    run = s.get('状态') == '运行中'
    msg = {'时间': now(), '内容': text, '方式': '打断' if run and interrupt else '排队' if run else '继续会话', '状态': '待送达'}
    if not run:
        if m.get('状态') == '收集中':
            raise KBError('这一期还在收集中，没有开发会话可以对话')
        sid = _session_id(s['日志'])
        if not sid:
            raise KBError('上一次会话没有会话号，接不上；请点「开始开发」/「继续开发」')
        msg.update(状态='已送达', 送达时间=now())
        m.setdefault('对话', []).append(msg)
        m['开发会话'] = dict(s, 仅对话=True)
        save_meta(d, m)
        proc = _dev_spawn(d, Path(s['仓库']), s.get('分支', ''), _chat_prompt(text, False), sid, 续跑次数=0, 仅对话=True)
        log(d, '对话', f'接着上次的会话回答（pid {proc.pid}）：{text[:100]}')
        return '已接着上一次的会话发给 AI，回复会显示在「最近动作」里'
    m.setdefault('对话', []).append(msg)
    if interrupt:
        msg.update(状态='已送达', 送达时间=now())
        m['开发会话']['插话'] = text
        save_meta(d, m)
        log(d, '对话', f'打断当前步骤：{text[:100]}')
        try:
            os.killpg(s['pid'], signal.SIGTERM)
        except ProcessLookupError:
            try:
                os.kill(s['pid'], signal.SIGTERM)
            except ProcessLookupError:
                pass
        return '已打断当前这一轮，AI 会带着你的消息接着这次对话继续（几秒后在「最近动作」里看到）'
    save_meta(d, m)
    log(d, '对话', f'排队：{text[:100]}')
    return 'AI 下一次调用知识库工具时会收到（正在等你确认时立刻收到），不打断当前步骤'


def _after_session(d, s):
    """会话结束 / 停止后：释放手机，同步测试报告里的问题，开发会话还要看要不要提示复测。"""
    try:
        _devices.device_release(d.name, by='会话结束')
        _devices.sync_test_issues(d)
        if s.get('类型') != '复测':
            _devices._suggest_retest(d)
    except (KBError, OSError, ValueError) as e:
        log(d, '会话收尾', f'出错：{e}')


def dev_session(name):
    """当前/上一次后台开发会话；进程已不在但还标着运行中的，补记为已结束。"""
    d = period_dir(name)
    s = load_meta(d).get('开发会话')
    if s and s.get('状态') == '运行中' and d.name not in _PROCS and d.name not in _WATCH and not _alive(s.get('pid', 0)):
        _dev_finish(d.name)
        s = load_meta(d).get('开发会话')
    return s


def _dev_prompt(name, root, branch, f, docs):
    v = dict(期名=name, 仓库=str(root), 分支=branch, 文档目录=str(docs),
             资料目录=str(Path(docs) / (f.get('资料目录名') or 'kb-materials')))
    steps = flow_text(f, '开发步骤', **v).strip()
    return f"""你是由知识库网页启动的【后台无人值守】开发会话：期「{name}」，仓库 {root}，分支 {branch}，开发流程「{f['名称']}」，文档目录 {docs}。
终端里没有人，不要在回复里提问，也不要用 AskUserQuestion。按下面做，直到全部完成：

【准备】kb_refresh_sources 检查需求来源有没有更新（有「条目待更新」的按提示先更新条目）；kb_dev_package 读取开发包；
kb_set_status 改为「开发中」（已是开发中则跳过）。工具结果里出现【需求来源有更新】时按提示处理。

【开发流程：{f['名称']}】
{steps}

【需要人确认时】{flow_text(f, '确认点', **v) or '方案取舍、与需求不一致、缺少账号或环境、操作被权限拦截等'}：
调用 kb_ask（问题、背景、选项、你的建议 recommend、相关文件绝对路径），再反复调用 kb_wait_answer 直到拿到回答；
需要时把回答写回对应的流程文档，然后继续。kb_ask 若提示免打扰，直接按你的建议执行。
【基础信息】测试账号、Wi-Fi / 代理 / VPN、环境配置等先查基础知识库（kb_base）；密码等机密在真正要用时才 kb_base_secret 读取，
不要写进代码、文档、提交、日志或回复。缺少需要的账号或配置时用 kb_ask 向用户要。
【手机】要在手机上装包、测试前先 kb_devices 看、kb_device_claim 申请（要几台申请几台），只在申请到的手机上操作
（adb -s <序列号> / agent-device --serial），别动别的期占着的手机；测完 kb_device_release。
【不阻断的问题】手机不够或没连（如 case 要多台手机而只连了一台）、缺测试账号、环境不满足等，让某些验证做不了、但不影响继续开发的：
不要停下等，也不要悄悄跳过——马上用 kb_issue 记下（写清要什么，如「需要 3 台手机：主持 + 2 个麦上用户」），能做的先做，
测不了的 case 如实记 BLOCKED，然后继续。用户会在网页看到并收到通知，条件具备后点「复测」补测。
【记录】每完成一个阶段或一个任务，用 kb_log 记一句进度；关键决定、接口变更、与需求不一致之处也 kb_log。
【完成】全部完成后 kb_set_status 改为「已完成」，并 kb_log 记录分支和提交。
【停止】kb_wait_answer 返回「已撤回」时立即停止。遇到无法继续的错误，用 kb_ask 说明情况并等待指示，不要放弃退出。""" + _NO_BG


def _resume_prompt(name, f=None, docs=''):
    f = f or get_flow()
    tip = flow_text(f, '续跑提示', 期名=name, 文档目录=str(docs)) or '先看文档目录和 git 改动确认实际进度：没完成的步骤重新执行（用前台方式）'
    return f"""继续期「{name}」的开发（开发流程「{f['名称']}」）。上一轮你结束了回复，进程随之退出，当时在后台运行的子 agent 和命令都已经被终止，不会再有结果。
{tip}，然后按原来的要求继续推进，需要人确认时照旧用 kb_ask + kb_wait_answer。
用手机前照旧 kb_device_claim；手机不够等不影响继续开发的问题用 kb_issue 记下后接着做。""" + _NO_BG


def session_flow(m):
    """开发会话用的流程：会话里记的 > 这一期选定的 > 默认。"""
    fid = (m.get('开发会话') or {}).get('流程')
    if fid:
        try:
            return get_flow(fid)
        except KBError:
            pass
    return period_flow(m)


def _dev_env(name, branch, root):
    """后台会话的环境：PATH 最前面是 adb 守卫（不往别的期占着的手机装包），再补上 adb 所在目录。
    网页服务由 launchd 启动，PATH 里没有 ~/.zshrc 加的 Android SDK，后台会话的 shell 也不读 .zshrc，
    不补的话会话里找不到 adb，手机插着也会报「没有设备」。"""
    path = [str(devlock.BIN)]
    adb = _devices._adb()
    if adb:
        path.append(str(Path(adb).parent))
    env = {'PATH': os.pathsep.join(path + [os.environ.get('PATH', '')]), 'KB_ROOT': str(ROOT), 'KB_PERIOD': name,
           'KB_BRANCH': branch, 'KB_REPO': str(root)}
    sdk = Path(adb).parent.parent if adb and Path(adb).parent.name == 'platform-tools' else None
    if sdk and not os.environ.get('ANDROID_HOME'):
        env['ANDROID_HOME'] = env['ANDROID_SDK_ROOT'] = str(sdk)
    return env


def _dev_spawn(d, root, branch, prompt, resume_id='', **extra):
    """启动（或用 --resume 接着上一轮对话续跑）后台会话；进程退出后自动 _dev_finish。"""
    eng = period_engine(load_meta(d))
    (d / DEV_DIR).mkdir(exist_ok=True)
    ts = f'{datetime.now():%Y%m%d-%H%M%S}'
    logf = d / DEV_DIR / f'{ts}.jsonl'
    proc = engine_popen(eng, prompt, f'kb·{d.name}', logf, root, resume_id, dict(_dev_env(d.name, branch, root), KB_SESSION='dev'))
    _PROCS[d.name] = proc
    m = load_meta(d)
    old = m.get('开发会话') or {}
    s = {'pid': proc.pid, '状态': '运行中', '开始时间': old.get('开始时间') if resume_id else now(), '本轮开始': now(),
         '仓库': str(root), '分支': branch, '日志': str(logf), '权限': eng['名称'], '备注': old.get('备注', ''),
         '流程': old.get('流程', ''), '引擎': eng['id'], '类型': old.get('类型', ''), '范围': old.get('范围', ''), **extra}
    if resume_id:
        s['历史日志'] = (old.get('历史日志') or []) + [old.get('日志')]
        if old.get('已汇报'):
            s['已汇报'] = True
        s['开始时间'] = old.get('开始时间') or now()
    m['开发会话'] = s
    save_meta(d, m)

    threading.Thread(target=_watch_dev, args=(d, proc.pid, proc), daemon=True).start()
    return proc


_WATCH = set()   # 正在被本进程盯着的期


def _watch_dev(d, pid, proc=None, known=None):
    """盯住后台会话：记录它派生的进程；退出后清理残留，再交给 _dev_finish（判断是否续跑）。"""
    _WATCH.add(d.name)
    try:
        known, saved = dict(known or {}), -1
        while (proc.poll() is None) if proc else _alive(pid):
            known = _track([pid], known)
            _TRACK[d.name] = known
            if len(known) != saved:      # 记进期信息，网页服务重启后也能清理
                saved = len(known)
                mm = load_meta(d)
                if (mm.get('开发会话') or {}).get('pid') == pid:
                    mm['开发会话']['子进程'] = {str(k): v for k, v in known.items()}
                    save_meta(d, mm)
            time.sleep(5)
        code = proc.returncode if proc else None
        if proc and _PROCS.get(d.name) is proc:
            _PROCS.pop(d.name, None)
        if not (load_meta(d).get('开发会话') or {}).get('停止中'):
            left = _kill_tracked(known)   # 主会话退出后残留的后台命令：续跑会重新执行，别让两份同时写
            _TRACK.pop(d.name, None)
            if left:
                log(d, '清理残留进程', f'未能结束：{left}')
    finally:
        _WATCH.discard(d.name)
    _dev_finish(d.name, code)


def dev_reattach():
    """网页服务启动时接管还在跑的后台会话（服务重启过，原来盯着它的线程没了）。"""
    for name in period_names():
        d = period_dir(name)
        s = load_meta(d).get('开发会话') or {}
        if s.get('状态') == '运行中' and name not in _WATCH and _alive(s.get('pid', 0)):
            known = {int(k): v for k, v in (s.get('子进程') or {}).items()}
            threading.Thread(target=_watch_dev, args=(d, s['pid'], None, known), daemon=True).start()


def pull_rebase(root):
    """git pull --rebase 拉最新代码；没有上游分支就跳过。失败（冲突等）会撤销这次 rebase，保持原样。"""
    root = Path(root)
    br = _git(root, 'branch', '--show-current').stdout.strip()
    up = _git(root, 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}')
    if up.returncode:
        return f'{br} 没有上游分支，跳过拉取'
    old = _git(root, 'rev-parse', '--short', 'HEAD').stdout.strip()
    r = _git(root, 'pull', '--rebase', timeout=300)
    if r.returncode:
        git_dir = Path(_git(root, 'rev-parse', '--absolute-git-dir').stdout.strip() or root / '.git')
        aborted = (git_dir / 'rebase-merge').exists() or (git_dir / 'rebase-apply').exists()
        if aborted:
            _git(root, 'rebase', '--abort')
        raise KBError(f'在 {br} 上 git pull --rebase 失败' + ('（已撤销这次 rebase，代码保持原样）' if aborted else '')
                      + f'：\n{(r.stderr or r.stdout).strip()[:800]}')
    new = _git(root, 'rev-parse', '--short', 'HEAD').stdout.strip()
    return f'{br} 已是最新（{new}）' if old == new else f'{br} 已拉取 {old} → {new}'


def switch_branch(root, branch):
    """用户在网页上确认「切到开发分支」后执行：切换前在当前分支 git pull --rebase，切换后在新分支再 git pull --rebase。
    已跟踪的文件有改动不切（未跟踪文件不影响）；本地没有的分支从 origin 拉；
    本地和远端都没有时不替用户新建（基线分支说不准），请用户自己建好或重新输入。返回每一步的结果。"""
    root = Path(root)
    if not re.fullmatch(r'[A-Za-z0-9][\w./-]*', branch or '') or '..' in branch:
        raise KBError(f'分支名不合法：{branch}')
    dirty = [x for x in _git(root, 'status', '--porcelain', '--untracked-files=no').stdout.splitlines() if x.strip()]
    if dirty:
        raise KBError(f'{root.name} 有 {len(dirty)} 个未提交的改动，先提交或 stash 后再切分支：\n' + '\n'.join(dirty[:10]))
    local = _git(root, 'rev-parse', '--verify', '--quiet', f'refs/heads/{branch}').returncode == 0
    remote = not local and _git(root, 'ls-remote', '--exit-code', '--heads', 'origin', branch, timeout=30).returncode == 0
    if not local and not remote:
        raise KBError(f'{root.name} 本地和 origin 都没有分支「{branch}」。请先在仓库里从正确的基线分支建好（如 git switch -c {branch} origin/<基线>），'
                      '或重新输入分支名')
    steps = ['切换前：' + pull_rebase(root)]
    if local:
        r = _git(root, 'switch', branch)
    else:
        f = _git(root, 'fetch', 'origin', f'{branch}:refs/remotes/origin/{branch}', timeout=120)
        r = f if f.returncode else _git(root, 'switch', '--track', f'origin/{branch}')
    if r.returncode:
        raise KBError(f'切换分支失败：{(r.stderr or r.stdout).strip()[:500]}')
    steps.append(f'已切换到 {branch}' + ('' if local else '（从 origin 拉取）'))
    steps.append('切换后：' + pull_rebase(root))
    return steps


def dev_start(period, note='', repo='', branch='', keep_branch=False):
    """网页「开始开发」：用户本人批准 + 后台启动开发会话。不作为 MCP 工具提供。
    仓库、分支自动从本期资料判断；判断不了时抛 KBNeed，网页弹窗让用户选仓库（repo）、
    切到开发分支（branch）或确认就用当前分支（keep_branch），再带着选择重新调用。"""
    d = period_dir(period)
    m = load_meta(d)
    s = dev_session(d.name)
    if s and s.get('状态') == '运行中':
        raise KBError('后台开发会话已经在运行')
    if m.get('状态') == '已完成':
        raise KBError('这一期已完成；如要继续开发，先把状态改为「已暂停」再开始')
    if repo:
        root = _git_root(repo)
        if not root:
            raise KBError(f'不是本机的 git 仓库：{repo}')
        if not flow_for(m, root):
            raise KBError(_no_flow_msg(m, root))
        repo = str(root)
    steps = []
    if branch or keep_branch:
        root = Path(repo) if repo else _sdd_repo(d, m, '')
        steps = switch_branch(root, branch) if branch else ['拉取：' + pull_rebase(root)]
        cur = _git(root, 'branch', '--show-current').stdout.strip()
        repo = str(root)
        m['开发分支'] = cur
        save_meta(d, m)
        log(d, '确认开发分支', f'{root.name} · {cur}' + (f'（网页确认切换：{"；".join(steps)}）' if branch else f'（沿用当前分支；{steps[0]}）'))
    root, branch, f, docs = _dev_target(d, m, repo)
    if not steps:                                       # 开发前更新代码（刚切过分支的已经拉过）
        up = hosts.sync(str(root), 'git')
        log(d, '更新代码', f'开发前：{up}')
    eng = period_engine(dict(m, 开发会话={}))
    engine_bin(eng)
    if m.get('状态') not in DEV_OK:
        set_status(d.name, '已批准开发', note or '网页「开始开发」批准', by_human=True)
    m = load_meta(d)
    if m.get('开发仓库') != str(root):
        log(d, '确认开发仓库', str(root))
    m['开发仓库'] = str(root)
    m['SDD目录'] = str(docs)
    m['开发会话'] = {'备注': note, '流程': f['id'], '引擎': eng['id']}
    save_meta(d, m)
    plug = run_plugins('开发开始', d, root, branch, docs)
    prompt = _dev_prompt(d.name, root, branch, f, docs) + _sources_prompt(m)
    if note and note not in ('网页「开始开发」批准', '网页「分析推动」'):
        prompt += f'\n\n【用户这次的要求】{note}\n（按这个要求推进；和流程冲突时以用户要求为准，拿不准用 kb_ask 问）'
    if plug:
        prompt += f'\n\n【开发开始时已运行的插件】（知识库自动运行，结果供参考）\n{plug}'
    proc = _dev_spawn(d, root, branch, prompt, '', 续跑次数=0)
    log(d, '开始开发', f'后台会话 pid {proc.pid}（{eng["名称"]} · {f["名称"]} · {root.name} · {branch}）' + (f'；{note}' if note else ''))
    return (f'已开始开发「{d.name}」：后台会话 pid {proc.pid}，{eng["名称"]}，流程「{f["名称"]}」，仓库 {root.name}（{branch}）'
            + (''.join(f'\n{x}' for x in steps) if steps else '') + (f'\n\n{plug}' if plug else ''))


def dev_stop(period, by='用户'):
    """网页「停止开发」：结束后台会话，状态改为已暂停，撤回未回答的问题。不作为 MCP 工具提供。"""
    d = period_dir(period)
    s = dev_session(d.name)
    if not s or s.get('状态') != '运行中':
        raise KBError('没有正在运行的后台开发会话')
    pid = s['pid']
    m = load_meta(d)
    m['开发会话']['停止中'] = True       # 别让 _dev_finish 把它当成「没做完」自动续跑
    save_meta(d, m)
    try:
        os.killpg(pid, signal.SIGTERM)
        for _ in range(25):
            if not _alive(pid) or (d.name in _PROCS and _PROCS[d.name].poll() is not None):
                break
            time.sleep(0.2)
        else:
            os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    left = _kill_tracked(_TRACK.pop(d.name, None) or {int(k): v for k, v in (s.get('子进程') or {}).items()})
    m = load_meta(d)
    s = m['开发会话']
    s.pop('停止中', None)
    s.update(状态='已停止', 结束时间=now(), 停止人=by, **_dev_result(s.get('日志', '')))
    if left:
        s['未能结束的进程'] = left
    for q in m.get('待确认') or []:
        if q['状态'] == '待回答':
            q.update(状态='已撤回', 回答时间=now())
    save_meta(d, m)
    log(d, '停止开发', f'后台会话 pid {pid} 已停止（{by}）')
    _after_session(d, s)
    if s.get('类型') == '复测':
        return f'已停止「{d.name}」的复测'
    if m.get('状态') in DEV_OK:
        set_status(d.name, '已暂停', '网页「停止开发」', by_human=True)
    return f'已停止「{d.name}」的后台开发，状态改为已暂停'
