# From 大大王.DT
"""手机占用、非阻断问题、复测。"""
from .infra import devlock
import json
import os
import re
import subprocess
import time
from pathlib import Path
from .common import KBError, PERIODS, now, read_text
from .periods import load_meta, log, period_dir, period_names, save_meta
from .flows import BUILTIN_FLOWS, flow_progress, flow_text, flows, get_flow
from .engines import engine_bin, engines, get_engine, period_engine
from .devprep import _git
from .devsession import DEV_DIR, _NO_BG, _dev_spawn, _notify, _result_of, dev_session, session_flow


# 多个期可能同时在后台测试：手机占用记在 设备占用.json（devlock.py），后台会话 PATH 最前面是 adb 守卫（bin/adb），
# 不让一期往别的期占着的手机装包、操作。手机不够、缺账号等不影响继续开发的问题记成「非阻断问题」，网页列出并通知；
# 识别到测试用例 / 自动化测试文件时开发面板有「复测」，条件具备后补测，也可以设成空闲手机够了自动复测。
_ADB = {}
_DEVS = {'t': 0, 'v': []}


def _adb():
    if 'path' not in _ADB:
        p = devlock.real_adb()
        if not p:       # 网页服务由 launchd 启动，PATH 里常常没有 adb：问一下登录 shell
            try:
                out = subprocess.run(['zsh', '-lic', 'command -v adb'], capture_output=True, text=True, timeout=10,
                                     stdin=subprocess.DEVNULL).stdout.strip().splitlines()
                p = out[-1] if out and Path(out[-1]).is_file() else ''
            except (OSError, subprocess.TimeoutExpired):
                p = ''
        _ADB['path'] = p
    return _ADB['path']


def _agent_device_claims():
    """agent-device 自己记的设备会话：序列号 → 会话名、工作目录。"""
    out = {}
    for f in (Path.home() / '.agent-device' / 'device-claims').glob('*.json'):
        try:
            c = json.loads(read_text(f))
            pid = int(c.get('ownerPid') or 0)
            if pid <= 0:
                continue
            os.kill(pid, 0)
            out[(c.get('device') or {})['id']] = {'会话': c.get('session', ''), '目录': c.get('workspace', ''),
                                                   '更新': devlock.stamp((c.get('updatedAtMs') or 0) / 1000)}
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return out


def _period_of_path(p):
    metas = [(n, load_meta(PERIODS / n)) for n in period_names()]
    for k in ('SDD目录', '开发仓库'):
        for n, m in metas:
            if m.get(k) and str(p).startswith(m[k]):
                return n
    return ''


def devices(period=''):
    """连着的手机和占用情况（占着但没连的也列出）。"""
    if time.time() - _DEVS['t'] > 3:
        adb = _adb()
        _DEVS.update(t=time.time(), v=devlock.online(adb) if adb else [])
    hold, ad = devlock.holders(), _agent_device_claims()
    sns = [x[0] for x in _DEVS['v']]
    out = []
    for sn, st, model in _DEVS['v'] + [(k, '未连接', '') for k in hold if k not in sns]:
        c, a = hold.get(sn), ad.get(sn)
        if a:
            a = dict(a, 期=_period_of_path(a['目录']))
        out.append({'序列号': sn, '型号': model or (c or {}).get('型号', ''),
                    '状态': {'device': '在线', 'unauthorized': '未授权', 'offline': '离线'}.get(st, st),
                    '占用': dict(c, 最后使用=devlock.stamp(c.get('最后使用'))) if c else None,
                    '本期': bool(c and period and c.get('期') == period and c.get('方式') != '本人'),
                    '空闲': st == 'device' and not c, 'agent-device': a})
    return out


def _who(c):
    if c.get('方式') == '本人':
        return '本人在用（网页上标的）'
    return f'被「{c.get("期", "")}」占用（分支 {c.get("分支") or "—"}，最后使用 {c.get("最后使用", "")}）'


def devices_text(period):
    if not _adb():
        return '本机找不到 adb，查不了手机。'
    name = period_dir(period).name
    ds = devices(name)
    if not ds:
        return ('没有连着的手机（adb devices 为空）。要用真机测试的先做别的部分，用 kb_issue 记下需要几台手机，继续开发；'
                '用户接好手机后会在网页「复测」补测。')
    lines = []
    for x in ds:
        c, a = x['占用'], x['agent-device']
        st = '空闲' if x['空闲'] else '本期占用' if x['本期'] else _who(c) if c else x['状态']
        if x['状态'] != '在线' and c:
            st += f'，{x["状态"]}'
        lines.append(f'- {x["序列号"]} {x["型号"]}：{st}' + (f'；agent-device 会话 {a["会话"]}' + (f'（{a["期"]}）' if a['期'] else '')
                                                            if a else ''))
    return (f'手机 {len(ds)} 台，空闲 {sum(x["空闲"] for x in ds)} 台：\n' + '\n'.join(lines)
            + '\n要用时 kb_device_claim 申请，只在申请到的手机上装包、操作（adb -s <序列号> / agent-device --serial）。')


def device_claim(period, count=1, serials=None, reason=''):
    """申请手机：优先本期已占着的，再挑空闲的；不够时记成非阻断问题并通知用户。"""
    d = period_dir(period)
    m = load_meta(d)
    count = max(1, min(int(count or 1), 10))
    ds = {x['序列号']: x for x in devices(d.name)}
    branch = (m.get('开发会话') or {}).get('分支') or m.get('开发分支', '')
    got, why = [], []
    with devlock.locked() as data:
        t = time.time()
        for k in [k for k, v in data.items() if not devlock.valid(v, t)]:
            data.pop(k)

        def usable(sn):
            c = data.get(sn)
            return ds.get(sn, {}).get('状态') == '在线' and (not c or (c.get('期') == d.name and c.get('方式') != '本人'))
        if serials:
            for sn in serials:
                if usable(sn):
                    got.append(sn)
                else:
                    why.append(f'{sn} ' + ('没连着' if sn not in ds else _who(ds[sn]['占用']) if ds[sn]['占用'] else ds[sn]['状态']))
        else:
            mine = [sn for sn in ds if usable(sn) and sn in data]
            other = sorted((sn for sn in ds if usable(sn) and sn not in data),
                           key=lambda sn: bool((ds[sn]['agent-device'] or {}).get('期') not in ('', d.name, None)))
            got = (mine + other)[:count]
        for sn in got:
            old = data.get(sn) or {}
            data[sn] = {'期': d.name, '方式': '申请', '开始': old.get('开始') or devlock.stamp(), '分支': branch,
                        '仓库': m.get('开发仓库', ''), '型号': ds[sn]['型号'], '用途': (reason or '').strip()[:200], '最后使用': t}
    need = len(serials) if serials else count
    if got:
        log(d, '申请手机', '、'.join(got) + (f'（{reason}）' if reason else ''))
    msg = (f'已为「{d.name}」占用 {len(got)} 台：' + '、'.join(f'{sn}（{ds[sn]["型号"]}）' for sn in got)
           + '。只在这些手机上装包、操作（adb -s <序列号> / agent-device --serial），测完 kb_device_release。') if got else '没有能用的手机。'
    if len(got) < need:
        iid, _ = _add_issue(d, f'需要 {need} 台手机，现在只能用 {len(got)} 台' + (f'：{reason}' if reason else ''),
                            devices_text(d.name) + (f'\n\n不可用：{"；".join(why)}' if why else ''), '设备不足', f'{need} 台手机',
                            'kb_device_claim', key=f'设备不足|{need}|{reason}')
        msg += (f'\n手机不够（需要 {need} 台，能用 {len(got)} 台' + (f'；{"；".join(why)}' if why else '') + f'）：已记为非阻断问题 {iid} 并通知用户。'
                '能测的先测；测不了的 case 按流程如实记 BLOCKED（ENV_BLOCKED，写明缺几台手机），继续开发，不要等待。'
                '用户接好手机后会在网页「复测」补测。')
    return msg


def device_release(period, serials=None, by='AI'):
    name = period_dir(period).name
    with devlock.locked() as data:
        ks = [k for k, v in data.items() if v.get('期') == name and v.get('方式') != '本人' and (not serials or k in serials)]
        for k in ks:
            data.pop(k)
    return f'已释放 {len(ks)} 台手机：{"、".join(ks)}' if ks else '这一期没有占着的手机'


def device_mark(serial, action):
    """网页：释放任何人的占用（release），或标成本人在用（mine）。"""
    with devlock.locked() as data:
        if action == 'release':
            c = data.pop(serial, None)
            return f'已释放 {serial}' + (f'（原来{_who(dict(c, 最后使用=devlock.stamp(c.get("最后使用"))))}）' if c else '')
        if action == 'mine':
            data[serial] = {'期': '', '方式': '本人', '开始': devlock.stamp(), '最后使用': time.time()}
            return f'已把 {serial} 标成本人在用：4 小时内后台会话不会往它装包、操作（用完点「释放」）'
    raise KBError('未知操作')


ISSUE_KINDS = ['设备不足', '账号', '环境', '未验证', '待排查', '工具链', '其他']
_URGENT = ('设备不足', '账号', '环境')     # 用户能动手解决的，新出现时弹通知


def _issue_kind(cat, text):
    if '工具链' in cat:
        return '工具链'
    if '疑点' in cat or '排查' in cat:
        return '待排查'
    if re.search(r'设备|手机|真机|\d\s*台', text):
        return '设备不足'
    if re.search(r'账号|登录', text):
        return '账号'
    if re.search(r'ENV|环境|网络|SIM|服务端|注入|构造|权限', text):
        return '环境'
    return '未验证'


def _add_issue(d, title, detail='', kind='', need='', source='AI', key='', notify=True):
    """记一条非阻断问题；同一问题（键相同）还没处理的只更新。返回 (编号, 是否新记)。"""
    m = load_meta(d)
    items = m.setdefault('非阻断问题', [])
    key = key or title.strip()
    old = next((x for x in items if x.get('键') == key and (x['状态'] == '待处理' or source == 'SDD 报告')), None)
    if old:
        if old['状态'] == '待处理' and detail and detail != old.get('详情'):
            old.update(详情=detail, 更新=now())
            save_meta(d, m)
        return old['编号'], False
    kind = kind if kind in ISSUE_KINDS else _issue_kind('', f'{title} {need}')
    iid = f'I{len(items) + 1:03d}'
    items.append({'编号': iid, '时间': now(), '类型': kind, '标题': title.strip()[:200], '详情': (detail or '').strip(),
                  '需要': (need or '').strip(), '来源': source, '键': key, '状态': '待处理', '处理时间': ''})
    save_meta(d, m)
    log(d, '非阻断问题', f'{iid} [{kind}] {title[:100]}')
    if notify:
        _notify(f'知识库 · {d.name} 需要你处理（不阻断开发）', title)
    return iid, True


def add_issue(period, title, detail='', kind='', need=''):
    if not (title or '').strip():
        raise KBError('问题标题不能为空')
    iid, new = _add_issue(period_dir(period), title, detail, kind, need)
    return (f'{iid} 已{"记下并通知用户" if new else "更新（这个问题之前记过）"}。这是非阻断问题：不用等回答，继续开发；'
            '因此没测成的 case 如实记 BLOCKED，用户条件具备后会在网页「复测」补测。')


def set_issue(period, iid, status, by='用户（网页）'):
    d = period_dir(period)
    if status not in ('待处理', '已处理', '已忽略'):
        raise KBError('状态只能是 待处理 / 已处理 / 已忽略')
    m = load_meta(d)
    q = next((x for x in m.get('非阻断问题') or [] if x['编号'] == iid), None)
    if not q:
        raise KBError(f'没有这个问题：{iid}')
    q.update(状态=status, 处理时间=now() if status != '待处理' else '', 处理人=by)
    save_meta(d, m)
    log(d, '非阻断问题', f'{iid} → {status}（{by}）')
    return f'{iid} 已标为「{status}」'


def _num(p):
    x = re.search(r'(\d+)', p.name)
    return int(x.group(1)) if x else 0


_SYNCED = {}


def sync_test_issues(d, m=None):
    """SDD：把 agentdevice-task-*.md「未闭环项」同步成非阻断问题（手机不够、缺账号等新出现时通知）。"""
    m = m or load_meta(d)
    docs = Path(m.get('SDD目录') or '')
    if not m.get('SDD目录') or not docs.is_dir():
        return 0
    fs = sorted(docs.glob('agentdevice-task-*.md'), key=_num)
    sig = [(f.name, f.stat().st_mtime) for f in fs]
    if _SYNCED.get(d.name) == sig:
        return 0
    new = []
    for f in fs:
        part = re.split(r'^##\s*未闭环项\s*$', read_text(f), maxsplit=1, flags=re.M)
        if len(part) < 2:
            continue
        sec = re.split(r'^##\s', part[1], maxsplit=1, flags=re.M)[0]
        for line in re.findall(r'^\s*[-*]\s+(.+)$', sec, re.M):
            cols = [x.strip() for x in line.split('|')]
            if len(cols) < 3:
                continue
            cat, case, what = cols[:3]
            ev, need = (cols + ['', ''])[3:5]
            kind = _issue_kind(cat, f'{what} {need}')
            title = f'TASK-{_num(f)} {case}：{need or what}'[:160]
            iid, isnew = _add_issue(d, title, f'类别：{cat}\n说明：{what}' + (f'\n证据：{ev}' if ev and ev != '无' else '')
                                    + (f'\n需要：{need}' if need else '') + f'\n报告：{f}', kind, need, 'SDD 报告',
                                    key=f'{f.name}|{cat}|{case}', notify=False)
            if isnew and kind in _URGENT:
                new.append(title)
    _SYNCED[d.name] = sig
    if new:
        _notify(f'知识库 · {d.name} 有 {len(new)} 个问题需要你处理（不阻断开发）', new[0] + (f' 等 {len(new)} 项' if len(new) > 1 else ''))
    return len(new)


_CASE_RE = re.compile(r'^#{2,4}\s+([A-Z]{1,6}-\d+(?:\s*[/、,，~]\s*[A-Z]{0,6}-?\d+)*)\s*[:：]\s*(PASS|FAIL|BLOCKED|ERROR|SKIP)\b(.*)$', re.M)


def test_files(f, docs):
    """按流程的「测试文件」在文档目录里找测试用例 / 自动化测试文件。"""
    if not docs or not Path(docs).is_dir():
        return []
    out = set()
    for g in f.get('测试文件') or []:
        p = Path(g).expanduser()
        base, pat = (Path(p.anchor), str(p.relative_to(p.anchor))) if p.is_absolute() else (Path(docs), g)
        try:
            out |= {x for x in base.glob(pat) if x.is_file() and not x.name.startswith('.')}
        except (ValueError, OSError):
            pass
    return sorted(out, key=lambda x: (str(x.parent), _num(x), x.name))[:500]


def test_summary(f, docs):
    """测试文件数和 case 结果（「### 编号: 状态」，后出现的覆盖前面的，复测结果追加在后面即可）。"""
    fs = test_files(f, docs)
    if not fs:
        return None
    cases = {}
    for p in fs:
        if p.suffix.lower() not in ('.md', '.markdown', '.txt'):
            continue
        text = read_text(p)
        for mm in _CASE_RE.finditer(text):
            env = 'ENV_BLOCKED' in mm.group(3) or 'ENV_BLOCKED' in text[mm.end():mm.end() + 300].split('\n###')[0]
            for cid in re.findall(r'[A-Z]{1,6}-\d+', mm.group(1)):
                cases[cid] = (mm.group(2), env)
    count = {}
    for st, _ in cases.values():
        count[st] = count.get(st, 0) + 1
    return {'文件数': len(fs), '文件': [str(x) for x in fs[:30]], '用例': len(cases), '统计': count,
            '环境阻塞': sum(1 for st, env in cases.values() if st == 'BLOCKED' and env),
            '未通过': [c for c, (st, _) in cases.items() if st != 'PASS'][:80]}


def need_devices(m):
    """补测要几台手机：没处理的「设备不足」问题里写的台数，取最大。"""
    n = 1
    for q in m.get('非阻断问题') or []:
        if q['状态'] == '待处理' and q['类型'] == '设备不足':
            nums = [int(x) for x in re.findall(r'(\d+)\s*台', f'{q["需要"]} {q["标题"]} {q["详情"]}') if 0 < int(x) <= 10]
            n = max([n, 2] + nums)
    return n


def retest_info(d, m):
    return {'测试': test_summary(session_flow(m), m.get('SDD目录')), '待复测': m.get('待复测'),
            '记录': (m.get('复测记录') or [])[-5:], '需要手机': need_devices(m)}


_SCOPE = {'未通过': '只测上次没通过的 case（BLOCKED、FAIL、ERROR、没执行 / 未验证的）', '全部': '全部 case 重新测一遍'}


def _retest_prompt(name, root, branch, f, docs, scope, note):
    v = dict(期名=name, 仓库=str(root), 分支=branch, 文档目录=str(docs), 范围=_SCOPE[scope],
             资料目录=str(Path(docs) / (f.get('资料目录名') or 'kb-materials')))
    steps = flow_text(f, '复测步骤', **v).strip() or flow_text(BUILTIN_FLOWS['generic'], '复测步骤', **v)
    return f"""你是由知识库网页启动的【后台无人值守】复测会话：期「{name}」，仓库 {root}，分支 {branch}，开发流程「{f['名称']}」，文档目录 {docs}。
开发时因为手机不够、没连手机、账号或环境不满足，有些测试没测成；用户点了「复测」{f'（{note}）' if note else ''}，请补测。
终端里没有人，不要在回复里提问，也不要用 AskUserQuestion。不要改这一期的状态，不要开发新功能。

【复测步骤】
{steps}

【手机】先 kb_devices 看；kb_device_claim 申请要用的台数（多台场景一次申请够），只在申请到的手机上装包、操作，别动别的期占着的手机。
手机还是不够、账号或环境仍不满足的 case：如实记 BLOCKED，用 kb_issue 记下还缺什么，然后接着测其余的。
【发现缺陷】复测发现代码缺陷时，用 kb_ask 说明现象、证据和修改建议，kb_wait_answer 等用户回答后照做（同意了才改代码，按仓库惯例提交）。
【基础信息】测试账号等先查 kb_base；机密只在真正要用时 kb_base_secret 读取，不写进任何文件、日志或回复。
【结束】全部测完：kb_device_release 释放手机，再调用 kb_test_report 汇报（通过 / 失败 / 仍阻塞的数量、小结、还缺什么条件），然后结束。
【停止】kb_wait_answer 返回「已撤回」时立即停止。""" + _NO_BG


def _retest_resume_prompt(name):
    return f"""继续期「{name}」的复测。上一轮你结束了回复，进程随之退出，当时在后台运行的子 agent 和命令都已经被终止，不会再有结果。
先看测试报告里已追加的「复测」结果确认做到哪了，没测完的接着测（手机照旧先 kb_device_claim）；全部测完后 kb_device_release、kb_test_report。""" + _NO_BG


def retest_start(period, scope='未通过', note='', by='用户（网页）'):
    """网页「复测」：后台启动复测会话（不改期状态）。不作为 MCP 工具提供。"""
    d = period_dir(period)
    m = load_meta(d)
    s = dev_session(d.name)
    if s and s.get('状态') == '运行中':
        raise KBError('后台会话正在运行，等它结束或先停止再复测')
    if m.get('状态') == '收集中' or not m.get('开发仓库') or not m.get('SDD目录'):
        raise KBError('这一期还没开发过，没有可复测的内容')
    root, docs, f = Path(m['开发仓库']), m['SDD目录'], session_flow(m)
    if not test_files(f, docs):
        raise KBError(f'文档目录里没有识别到测试文件（开发流程「{f["名称"]}」的「测试文件」设置）：{docs}')
    branch = _git(root, 'branch', '--show-current').stdout.strip()
    if m.get('开发分支') and branch != m['开发分支']:
        raise KBError(f'{root.name} 现在在分支 {branch or "（游离）"}，不是这一期的开发分支 {m["开发分支"]}，'
                      '复测会测错代码。先切回开发分支（或点「继续开发」按提示切换）再复测')
    scope = scope if scope in _SCOPE else '未通过'
    eng = period_engine(m)
    engine_bin(eng)
    m['开发会话'] = {'备注': note, '流程': f['id'], '引擎': eng['id'], '类型': '复测', '范围': scope}
    if m.get('待复测'):
        m['待复测']['自动'] = False
    save_meta(d, m)
    proc = _dev_spawn(d, root, branch, _retest_prompt(d.name, root, branch, f, docs, scope, note), '', 续跑次数=0)
    log(d, '开始复测', f'后台会话 pid {proc.pid}（{eng["名称"]} · {scope} · {branch}；{by}）' + (f'；{note}' if note else ''))
    return f'已开始复测「{d.name}」：后台会话 pid {proc.pid}，{_SCOPE[scope]}'


def retest_plan(period, auto, phones=1, scope='未通过', by='用户（网页）'):
    """网页：条件满足（空闲手机够了）时自动复测，或取消。"""
    d = period_dir(period)
    m = load_meta(d)
    p = m.get('待复测') or {}
    if auto:
        n = max(1, min(int(phones or 1), 10))
        m['待复测'] = dict(p, 自动=True, 手机=n, 范围=scope if scope in _SCOPE else '未通过', 设置时间=now(), 设置人=by)
        m['待复测'].pop('失败', None)
        msg = f'空闲手机够 {n} 台时会自动开始复测（每分钟检查一次），开始时弹通知'
    else:
        if p:
            p['自动'] = False
        m['待复测'] = p or None
        msg = '已取消自动复测'
    save_meta(d, m)
    log(d, '自动复测', msg)
    return msg


def test_report(period, summary, passed=0, failed=0, blocked=0, need=''):
    """复测（或开发中的测试）结束时汇报结果。"""
    d = period_dir(period)
    m = load_meta(d)
    s = m.get('开发会话') or {}
    rec = {'时间': now(), '通过': int(passed or 0), '失败': int(failed or 0), '阻塞': int(blocked or 0),
           '小结': (summary or '').strip(), '还缺': (need or '').strip(), '类型': s.get('类型') or '开发'}
    m.setdefault('复测记录', []).append(rec)
    if s.get('状态') == '运行中':
        s['已汇报'] = True
    if rec['阻塞']:
        m['待复测'] = dict(m.get('待复测') or {}, 自动=False, 原因=rec['还缺'] or rec['小结'][:200], 设置时间=now(), 设置人='复测汇报')
    else:
        m.pop('待复测', None)
    save_meta(d, m)
    log(d, '测试结果', f'通过 {rec["通过"]} / 失败 {rec["失败"]} / 阻塞 {rec["阻塞"]}：{rec["小结"][:150]}')
    if rec['阻塞'] and rec['还缺']:
        _add_issue(d, f'还有 {rec["阻塞"]} 个 case 没测成：{rec["还缺"][:80]}', rec['小结'], '', rec['还缺'], 'kb_test_report',
                   key=f'复测|{rec["还缺"]}')
    device_release(d.name, by='测试汇报')
    _notify(f'知识库 · {d.name} 测试结果', f'通过 {rec["通过"]}，失败 {rec["失败"]}，阻塞 {rec["阻塞"]}')
    return '已记录测试结果，手机已释放' + ('；复测会话可以结束了' if s.get('类型') == '复测' else '')


def _suggest_retest(d):
    """开发会话结束后：有因为环境没测成的 case 或手机不够的问题，就标成「待复测」，开发面板提示。"""
    m = load_meta(d)
    if m.get('待复测'):
        return
    ts = test_summary(session_flow(m), m.get('SDD目录'))
    open_ = [q for q in m.get('非阻断问题') or [] if q['状态'] == '待处理' and q['类型'] in _URGENT]
    if (ts and ts['环境阻塞']) or open_:
        m['待复测'] = {'自动': False, '手机': need_devices(m), '范围': '未通过', '设置时间': now(), '设置人': '自动发现',
                     '原因': (f'{ts["环境阻塞"]} 个 case 因环境没测成' if ts and ts['环境阻塞'] else '')
                     + (f'{"；" if ts and ts["环境阻塞"] else ""}{len(open_)} 个手机 / 账号 / 环境问题待处理' if open_ else '')}
        save_meta(d, m)


def dev_tick():
    """网页服务每分钟调用：同步测试报告里的非阻断问题；设了自动复测的期，空闲手机够了就开始复测。"""
    for n in period_names():
        d = PERIODS / n
        try:
            m = load_meta(d)
            if m.get('SDD目录') and session_flow(m).get('进度类型') == 'SDD':
                sync_test_issues(d, m)
            p = m.get('待复测') or {}
            s = dev_session(n)
            if not p.get('自动') or (s and s.get('状态') == '运行中'):
                continue
            free = sum(1 for x in devices(n) if x['空闲'] or x['本期'])
            if free < int(p.get('手机') or 1):
                continue
            try:
                retest_start(n, p.get('范围') or '未通过', f'空闲手机够了（{free} 台），自动复测', by='自动复测')
                _notify(f'知识库 · {n}', f'空闲手机够了（{free} 台），已自动开始复测')
            except KBError as e:
                m = load_meta(d)
                m['待复测'] = dict(m.get('待复测') or {}, 自动=False, 失败=str(e))
                save_meta(d, m)
                log(d, '自动复测', f'没能开始：{e}')
                _notify(f'知识库 · {n}', f'自动复测没能开始：{e}')
        except Exception as e:      # 某一期出错不影响其他期
            print('dev_tick:', n, repr(e), flush=True)


def _brief_tool(name, inp):
    inp = inp or {}
    if not isinstance(inp, dict):
        return str(inp)[:160]
    if name == 'Bash':
        return inp.get('description') or inp.get('command', '')[:160]
    if name in ('Read', 'Edit', 'Write', 'NotebookEdit'):
        return inp.get('file_path', '')
    if name == 'Skill':
        return f'/{inp.get("skill", "")} {inp.get("args", "")}'.strip()
    if name in ('Agent', 'Task'):
        return inp.get('description') or inp.get('subagent_type', '')
    if name.startswith('mcp__kb__'):
        return inp.get('question') or inp.get('note') or inp.get('status') or inp.get('id') or ''
    return json.dumps(inp, ensure_ascii=False)[:160]


_ACT = {}   # 日志路径 → [已读到的字节位置, 动作列表]：增量解析，日志再大也不漏前面的动作


def _parse_act(line):
    if line.startswith('{"type":"user"') or line.startswith('{"type":"system"') or line.startswith('{"type": "kb.engine"'):
        return []          # 工具返回、系统事件：又大又不用展示，不解析
    try:
        j = json.loads(line)
    except ValueError:
        return [{'类型': '输出', '内容': line[:300]}] if line.strip() and len(line) < 2000 else []
    if not isinstance(j, dict):
        return []
    out, t = [], j.get('type')
    if t == 'assistant':                                         # Claude
        sub = bool(j.get('parent_tool_use_id'))
        for c in (j.get('message') or {}).get('content') or []:
            if c.get('type') == 'text' and c.get('text', '').strip():
                out.append({'类型': '说明', '内容': c['text'].strip()[:600], '子任务': sub})
            elif c.get('type') == 'tool_use':
                nm = c.get('name', '')
                out.append({'类型': '工具', '工具': nm.replace('mcp__kb__', 'kb:'), '内容': _brief_tool(nm, c.get('input')),
                            '子任务': sub})
    elif t == 'result':                                          # Claude / Hermes
        r = _result_of(line)
        out.append({'类型': '结束', '内容': (r.get('结果') or '')[:600], '出错': bool(r.get('出错'))})
    elif t == 'item.completed':                                  # Codex
        it = j.get('item') or {}
        k = it.get('type')
        if k == 'agent_message' and (it.get('text') or '').strip():
            out.append({'类型': '说明', '内容': it['text'].strip()[:600]})
        elif k == 'command_execution':
            out.append({'类型': '工具', '工具': 'shell', '内容': str(it.get('command') or '')[:200]})
        elif k == 'mcp_tool_call':
            nm = f'{it.get("server") or ""}:{it.get("tool") or ""}'
            out.append({'类型': '工具', '工具': nm.replace('kb:', 'kb:'), '内容': _brief_tool(it.get('tool') or '', it.get('arguments'))})
        elif k == 'file_change':
            fs = [c.get('path', '') for c in it.get('changes') or [] if isinstance(c, dict)]
            out.append({'类型': '工具', '工具': '改文件', '内容': '、'.join(fs)[:200]})
    elif t in ('turn.failed', 'error'):                          # Codex
        out.append({'类型': '结束', '内容': str((j.get('error') or {}).get('message') or j.get('message') or '出错')[:600],
                    '出错': True})
    elif t == 'text' and (j.get('text') or '').strip():          # Hermes
        out.append({'类型': '说明', '内容': j['text'].strip()[:600]})
    elif t == 'tool_use':                                        # Hermes
        nm = j.get('name') or j.get('tool') or ''
        out.append({'类型': '工具', '工具': re.sub(r'^mcp_kb_', 'kb:', nm), '内容': _brief_tool(nm, j.get('input') or j.get('args'))})
    return out


def dev_activity(logf, n=30, full=False):
    """从 stream-json 日志里取动作：说了什么、调了什么工具（子 agent 的标为子任务）、最后结果。"""
    p = Path(logf or '')
    if not p.is_file():
        return []
    key = str(p)
    pos, acts = _ACT.get(key) or [0, []]
    size = p.stat().st_size
    if size < pos:
        pos, acts = 0, []
    if size > pos:
        with p.open('rb') as fh:
            fh.seek(pos)
            data = fh.read()
        cut = data.rfind(b'\n') + 1          # 只处理完整的行，没写完的下次再读
        for line in data[:cut].decode('utf-8', 'ignore').splitlines():
            acts += _parse_act(line)
        pos += cut
        _ACT[key] = [pos, acts[-5000:]]
    return list(acts) if full or not n else acts[-n:]


def session_activity(s, n=30):
    """当前会话（含自动续跑的几轮）最近的动作。"""
    s = s or {}
    out = []
    for f in (s.get('历史日志') or []) + [s.get('日志')]:
        out += dev_activity(f, n)
    return out[-n:]


def _sdd_status(docs):
    f = Path(docs) / 'sdd-status.md'
    res = {}
    if f.exists():
        for line in read_text(f).splitlines():
            mm = re.match(r'^([a-z0-9_]+):\s*(.*)$', line.strip())
            if mm:
                res[mm.group(1)] = mm.group(2).strip()
    return res


def sdd_progress(docs):
    """从 SDD 文档目录解析开发进度与测试进度。"""
    docs = Path(docs or '')
    if not docs.is_dir():
        return None
    st = _sdd_status(docs)
    steps = []
    for label, key, doc in (('需求分析', 'step1_pm', 'prd.md'), ('接口规格', 'step1_api', 'api-spec.md'),
                            ('技术规划', 'step2', 'arch_dev_plan.md'), ('代码实现', 'step3', '')):
        steps.append({'名称': label, '状态': st.get(key, 'pending') or 'pending',
                      '修订': st.get(key + '_revisions', ''), '文档': str(docs / doc) if doc and (docs / doc).exists() else ''})
    idx, total = st.get('step3_current_index', ''), st.get('step3_task_total', '')
    task = {'当前': st.get('step3_current_task', ''), '序号': int(idx) if idx.isdigit() else 0,
            '总数': int(total) if total.isdigit() else 0, '阶段': st.get('step3_task_phase', ''),
            '审查轮次': st.get('step3_task_review_round', ''), '设备修复轮次': st.get('step3_device_fix_round', ''),
            '阻塞': st.get('step3_task_blocked_reason', '') or st.get('step3_device_block_reason', ''),
            '待决策': st.get('step3_pending_decision', ''),
            '审查发现': st.get('step3_review_findings', ''), '设备发现': st.get('step3_device_findings', '')}
    tests = {'用例': 0, '优先级': {}, '统计': {}, '报告': []}
    at = docs / 'agent-test.json'
    if at.exists():
        try:
            cs = json.loads(read_text(at)).get('cases') or []
            tests['用例'] = len(cs)
            for c in cs:
                k = c.get('priority') or '其他'
                tests['优先级'][k] = tests['优先级'].get(k, 0) + 1
        except (ValueError, AttributeError):
            pass
    summ = docs / 'agentdevice-summary.md'
    if summ.exists():
        part = read_text(summ).split('## 按 TASK', 1)[0]
        for k, v in re.findall(r'\|\s*\S*\s*(PASS|FAIL|BLOCKED|ERROR)\s*\|\s*(\d+)\s*\|', part):
            tests['统计'][k] = int(v)
        tests['报告'].append(str(summ))
    bb = docs / 'tests' / 'blackbox' / 'blackbox-test.md'
    if bb.exists():
        tests['黑盒用例'] = str(bb)
    key = lambda x: int(re.search(r'(\d+)', x.name).group(1)) if re.search(r'(\d+)', x.name) else 0
    tests['报告'] += [str(x) for x in sorted(docs.glob('agentdevice-task-*.md'), key=key)]
    reviews = [str(x) for x in sorted(docs.glob('review-task-*.md'), key=key)]
    return {'目录': str(docs), '步骤': steps, '任务': task, '测试': tests, '审查报告': reviews,
            '状态文件': str(docs / 'sdd-status.md') if (docs / 'sdd-status.md').exists() else ''}


def dev_activity_all(period, limit=3000):
    """这一期所有后台会话（含自动续跑、来源更新）的动作，按时间顺序，每个日志前加一行分隔。"""
    d = period_dir(period)
    out = []
    for f in sorted((d / DEV_DIR).glob('*.jsonl')) if (d / DEV_DIR).exists() else []:
        acts = dev_activity(f, 100000, full=True)
        if acts:
            t = re.sub(r'^(?:(.+)-)?(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)(\d\d)$', r'\2-\3-\4 \5:\6:\7 \1', f.stem).strip()
            out.append({'类型': '会话', '内容': f'{t}（{len(acts)} 个动作）'})
            out += acts
    return out[-limit:]


def dev_overview(period):
    d = period_dir(period)
    s = dev_session(d.name)
    sync_test_issues(d)
    m = load_meta(d)
    return {'状态': m.get('状态'), '免打扰': bool(m.get('免打扰')), '会话': s,
            '会话记录': sorted((x.name for x in (d / DEV_DIR).glob('*.jsonl')), reverse=True) if (d / DEV_DIR).exists() else [],
            '动作': session_activity(s), '进度': flow_progress(session_flow(m), m.get('SDD目录')),
            '流程': m.get('开发流程', ''), '当前流程': session_flow(m)['名称'], '默认流程': get_flow()['名称'],
            '流程列表': [{'id': x['id'], '名称': x['名称']} for x in flows()],
            '引擎': m.get('AI引擎', ''), '默认引擎': get_engine()['名称'],
            '引擎列表': [{'id': x['id'], '名称': x['名称']} for x in engines()],
            '待确认': m.get('待确认') or [], '对话': (m.get('对话') or [])[-8:], '设备': devices(d.name) if _adb() else None,
            '非阻断问题': m.get('非阻断问题') or [], '复测': retest_info(d, m)}
