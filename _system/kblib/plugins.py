# From 大大王.DT
"""插件：挂时机的、按需调用的工具插件、插件入口。"""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from .common import KBError, PERIODS, ROOT, load_settings, now, read_text, safe_name, save_settings
from .periods import create_task, is_task, load_meta, log, period_dir, period_names, save_meta, set_status
from .notes import add_note
from .baseinfo import base_load, base_secret
from . import lazy
_devprep = lazy('kblib.devprep')      # 上层模块：用到时才 import（不形成循环）
_devsession = lazy('kblib.devsession')      # 上层模块：用到时才 import（不形成循环）
_devices = lazy('kblib.devices')      # 上层模块：用到时才 import（不形成循环）
_bug_index = lazy('kblib.bugs.index')      # 上层模块：用到时才 import（不形成循环）


# 插件不是知识库的一部分：放在知识库根目录「插件/<名称>/」（不进 git），或在设置里添加其他目录。
# 每个插件一个 plugin.json（名称、说明、命令、默认时机、识别文件、超时、配置项、提交说明＝手动「运行一次」后提交用的说明），在网页「⚙ 设置 → 插件」挂载并选时机。
# 运行时 cwd 是插件目录，环境变量带上期名、仓库、分支、文档目录和配置；退出码非 0 算失败（记成非阻断问题，不拦截开发）。
PLUGIN_DIR = ROOT / '插件'
PLUGIN_EVENTS = {'开发开始': '网页点「开始开发 / 继续开发」后、启动后台 AI 之前',
                 '开发完成': '期状态改为「已完成」时（AI 用 kb_set_status 标完成，或在网页 / 终端修改）'}
PLUGIN_ENV = {'KB_EVENT': '时机（开发开始 / 开发完成）', 'KB_PERIOD': '期名', 'KB_PERIOD_DIR': '这一期的资料目录',
              'KB_REPO': '代码仓库绝对路径', 'KB_BRANCH': '当前分支', 'KB_DOCS': '开发流程的文档目录（可能为空）',
              'KB_PLUGIN_CONFIG': '设置里填的配置项（JSON）', 'KB_ROOT': '知识库根目录', 'KB_PYTHON': '知识库用的 Python',
              'KB_PLUGIN_BASE': '「基础信息」类配置项选中的条目（JSON：键 → {字段: 值}，含机密，只在运行时给）'}
PLUGIN_TOOL = '工具'      # plugin.json「类型」：工具 = 不挂时机，由你 / AI 按需调用（kb_plugin_call、kb plugin call）


def _plugin_dirs():
    out = []
    if PLUGIN_DIR.is_dir():
        out += [p for p in sorted(PLUGIN_DIR.iterdir()) if (p / 'plugin.json').is_file()]
    for x in load_settings().get('插件目录', []):
        p = Path(x).expanduser()
        if p not in out:
            out.append(p)
    return out


def plugins():
    """全部插件：plugin.json 的内容 + id、目录、是否外部目录、挂载情况（启用、时机、配置）。"""
    conf = load_settings().get('插件', {})
    out = []
    for p in _plugin_dirs():
        pid = p.name
        base = {'id': pid, '目录': str(p), '外部': p.parent != PLUGIN_DIR}
        try:
            man = json.loads(read_text(p / 'plugin.json'))
            if not isinstance(man.get('命令'), list) or not man['命令']:
                raise ValueError('「命令」要写成数组，如 ["{python}", "main.py"]')
        except (OSError, ValueError) as e:
            out.append(dict(base, 名称=pid, 错误=f'plugin.json 读取失败：{e}', 启用=False, 时机=[], 配置={}))
            continue
        c = conf.get(pid, {})
        tool = man.get('类型') == PLUGIN_TOOL
        bsrc = man.get('类型') == _bug_index.BUG_PLUGIN              # Bug 平台适配器：在「🐞 Bug → 平台」里接入，不挂时机
        dft = {x['键']: (x.get('默认') or (x.get('类型', '').split(':', 1)[1].split('|')[0]
                                            if x.get('类型', '').startswith('select:') else ''))
               for x in man.get('配置项', [])}
        out.append(dict(man, **base, 启用=bool(c.get('启用')) or bsrc, 工具=tool, Bug平台=bsrc,
                        时机=[] if tool or bsrc else [e for e in c.get('时机', man.get('默认时机', [])) if e in PLUGIN_EVENTS],
                        配置=dict(dft, **c.get('配置', {}))))
    return out


def get_plugin(pid):
    p = next((x for x in plugins() if x['id'] == pid), None)
    if not p:
        raise KBError(f'没有这个插件：{pid}')
    return p


def save_plugin(pid, enabled, events, config=None):
    """网页「⚙ 设置 → 插件」：挂载 / 卸下，选时机，填配置。"""
    p = get_plugin(pid)
    bad = [e for e in events if e not in PLUGIN_EVENTS]
    if bad:
        raise KBError(f'不支持的时机：{"、".join(bad)}；可选 {" / ".join(PLUGIN_EVENTS)}')
    if p.get('工具') or p.get('Bug平台'):
        events = []
    elif enabled and not events:
        raise KBError('挂载插件至少要选一个时机')
    s = load_settings()
    s.setdefault('插件', {})[pid] = {'启用': bool(enabled), '时机': list(events),
                                   '配置': {k: str(v) for k, v in (config or {}).items()
                                            if k in {x['键'] for x in p.get('配置项', [])}}}
    save_settings(s)
    return f'插件「{p["名称"]}」' + ((f'已挂载：{"、".join(events)}' if events else '已挂载（按需调用）') if enabled else '已卸下')


def add_plugin_dir(path):
    p = Path(path).expanduser().resolve()
    if not (p / 'plugin.json').is_file():
        raise KBError(f'{p} 下没有 plugin.json')
    s = load_settings()
    ds = s.setdefault('插件目录', [])
    if p.parent == PLUGIN_DIR or str(p) in ds:
        return f'已经有这个插件：{p.name}'
    if p.name in {x.name for x in _plugin_dirs()}:
        raise KBError(f'已有同名插件「{p.name}」，请改目录名后再添加')
    ds.append(str(p))
    save_settings(s)
    return f'已添加插件目录：{p}（在列表里点「挂载」后才会运行）'


def remove_plugin_dir(pid):
    p = get_plugin(pid)
    if not p['外部']:
        raise KBError(f'「{p["名称"]}」在知识库的插件目录里，删除请直接删文件夹：{p["目录"]}')
    s = load_settings()
    s['插件目录'] = [x for x in s.get('插件目录', []) if Path(x).expanduser() != Path(p['目录'])]
    s.get('插件', {}).pop(pid, None)
    save_settings(s)
    return f'已移除插件「{p["名称"]}」（文件没动：{p["目录"]}）'


def _git_changed(root):
    """仓库里有改动的文件 → 内容摘要（插件运行前后对比，找出插件改了哪些文件）。"""
    r = _devprep._git(root, 'status', '--porcelain', '-uall')
    out = {}
    for ln in r.stdout.splitlines() if r.returncode == 0 else []:
        f = ln[3:].split(' -> ')[-1].strip('"')
        try:
            out[f] = hashlib.md5((Path(root) / f).read_bytes()).hexdigest()
        except OSError:
            out[f] = ''
    return out


def _plugin_base(p, by):
    """配置项里「类型: base」的项填的是基础信息编号（如 B019）：运行时把那条的字段（含钥匙串里的机密）交给插件，插件里不用写账号密码。"""
    out = {}
    for c in p.get('配置项', []):
        if c.get('类型') != 'base':
            continue
        bid = (p['配置'].get(c['键']) or '').strip()
        if not bid:
            continue
        e = next((x for x in base_load()['条目'] if x['编号'] == bid), None)
        if not e:
            raise KBError(f'插件「{p.get("名称") or p["id"]}」的「{c.get("标题") or c["键"]}」填的 {bid} 在基础信息里找不到')
        out[c['键']] = {f['名']: base_secret(bid, f['名'], by=by, purpose=f'插件「{p.get("名称") or p["id"]}」') if f.get('机密') else f.get('值', '')
                        for f in e['字段']}
    return out


def _plugin_env(p, by, **kw):
    env = dict(os.environ, KB_ROOT=str(ROOT), KB_PYTHON=sys.executable,
               KB_PLUGIN_CONFIG=json.dumps(p['配置'], ensure_ascii=False))
    b = _plugin_base(p, by)
    if b:
        env['KB_PLUGIN_BASE'] = json.dumps(b, ensure_ascii=False)
    env.update({k: str(v) for k, v in kw.items()})
    return env


def tool_plugins():
    return [p for p in plugins() if p.get('工具') and not p.get('错误')]


def call_plugin(pid='', args=(), period='', by='Claude'):
    """按需调用「工具」插件（如按会话编号拉取外部系统的会话）。不带插件名时列出已挂载的工具插件。"""
    ts = tool_plugins()
    if not pid:
        on = [p for p in ts if p['启用']]
        if not on:
            return '没有挂载的工具插件（网页「⚙ 设置 → 插件」挂载）' + (
                f'；未挂载的：{"、".join(p["名称"] for p in ts)}' if ts else '')
        return '可调用的工具插件：\n' + '\n'.join(
            f'- {p["id"]}：{p.get("说明") or ""}' + (f'\n  参数：{p["参数"]}' if p.get('参数') else '') for p in on)
    p = next((x for x in ts if pid in (x['id'], x.get('名称'))), None)
    if not p:
        raise KBError(f'没有这个工具插件：{pid}（{"、".join(x["id"] for x in ts) or "还没有工具插件"}）')
    if not p['启用']:
        raise KBError(f'插件「{p["名称"]}」还没挂载：在网页「⚙ 设置 → 插件」点「挂载」并填好配置')
    d = period_dir(period) if period else None
    env = _plugin_env(p, by, KB_EVENT='调用', KB_PERIOD=d.name if d else '', KB_PERIOD_DIR=str(d) if d else '')
    cmd = [sys.executable if x == '{python}' else x for x in p['命令']] + [str(a) for a in args]
    try:
        r = subprocess.run(cmd, cwd=p['目录'], env=env, capture_output=True, text=True, timeout=int(p.get('超时') or 300))
    except subprocess.TimeoutExpired:
        raise KBError(f'插件「{p["名称"]}」超时（{p.get("超时") or 300} 秒）')
    except OSError as e:
        raise KBError(f'插件「{p["名称"]}」启动失败：{e}')
    out = (r.stdout + ('\n' + r.stderr if r.stderr.strip() and r.returncode else '')).strip()
    if d:
        log(d, '插件', f'调用插件「{p["名称"]}」{" ".join(map(str, args))}：{"完成" if r.returncode == 0 else "失败"}')
    if r.returncode:
        raise KBError(f'插件「{p["名称"]}」失败（退出码 {r.returncode}）：{out[-3000:]}')
    return out


# ---- 工具插件的网页入口（plugin.json 写了「入口」）：输入 → 候选列表 → 加入事项；事项页实时展示原始内容
# 约定：命令后加 `resolve <输入>` 输出候选 JSON 列表（编号、标题、摘要、来源、提问人、时间、匹配）；
#       `content <编号>` 输出原始内容 JSON（标题、地址、会话[{…, 消息[{角色, 时间, 内容, 工具[{工具, 参数, 结果}]}]}]）。
_PC = {}                 # (插件, 编号) → (时间, 内容)：事项页反复打开时少拉几次


def _plugin_json(pid, args, by):
    out = call_plugin(pid, args, by=by)
    try:
        return json.loads(out.strip().splitlines()[-1] if out.strip() else 'null')
    except ValueError:
        raise KBError(f'插件输出不是 JSON：{out[-500:]}')


def plugin_entries():
    return [{'id': p['id'], '名称': p['入口'].get('名称') or p['名称'], '图标': p['入口'].get('图标') or '🔌',
             '提示': p['入口'].get('提示', ''), '说明': p['入口'].get('说明', '')}
            for p in tool_plugins() if p['启用'] and isinstance(p.get('入口'), dict)]


def plugin_resolve(pid, text, by='用户（网页）'):
    if not text.strip():
        raise KBError('先输入内容')
    items = _plugin_json(pid, ['resolve', text], by) or []
    linked = {}
    for n in period_names():
        for x in load_meta(PERIODS / n).get('外部来源') or []:
            if x.get('插件') == pid:
                linked.setdefault(x.get('编号'), []).append(n)
    for it in items:
        it['事项'] = linked.get(it.get('编号'), [])
    return items


def plugin_content(pid, item, fresh=False, by='用户（网页）'):
    k = (pid, item)
    if not fresh and k in _PC and time.time() - _PC[k][0] < 120:
        return _PC[k][1]
    data = _plugin_json(pid, ['content', item], by)
    _PC[k] = (time.time(), data)
    return data


def plugin_to_task(pid, item, task='', name='', title='', url='', by='用户（网页）'):
    """把插件找到的条目（如一段 Hermes 会话）加入事项：task 空 / ＋新建 = 新建事项（名称默认用条目标题），否则归到已有事项。
    知识库只记来源指针（插件、编号、标题、地址），原始内容每次实时拉取。"""
    p = next((x for x in tool_plugins() if x['id'] == pid), None)
    if not p:
        raise KBError(f'没有这个工具插件：{pid}')
    label = (p.get('入口') or {}).get('名称') or p['名称']
    if not title or not url:
        c = plugin_content(pid, item, by=by)
        title, url = title or c.get('标题') or item, url or c.get('地址') or ''
    out = []
    if not task or task == '＋新建':
        name = safe_name(name or title)
        if (PERIODS / name).exists():
            raise KBError(f'已经有「{name}」，换个名称，或选择归到这个事项')
        out.append(create_task(name, f'{label}：{title}', '', f'{label} {item}', '', by=by).splitlines()[0])
        task = name
    d = period_dir(task)
    m = load_meta(d)
    if not is_task(m):
        raise KBError(f'「{d.name}」不是事项')
    src = m.setdefault('外部来源', [])
    if any(x.get('插件') == pid and x.get('编号') == item for x in src):
        return {'msg': f'「{d.name}」里已经有 {label} {item}', 'name': d.name}
    src.append({'插件': pid, '名称': label, '编号': item, '标题': title, '地址': url, '加入时间': now(), '加入人': by})
    save_meta(d, m)
    add_note(d.name, content=f'{label} {item}：{title}\n原始内容不存知识库，处理时用 kb_plugin_call {pid} {item} 实时拉取。',
             category='其他资料', kind='链接', title=f'{label}：{title}', url=url, source=label)
    log(d, '加入来源', f'{label} {item}「{title}」（{by}）')
    out.append(f'已把 {label}「{title}」加入事项「{d.name}」')
    return {'msg': '；'.join(out), 'name': d.name}


def _sources_prompt(m):
    src = m.get('外部来源') or []
    if not src:
        return ''
    return ('\n\n【本事项的原始内容在外部系统，不在知识库里】先逐个用 kb_plugin_call 实时拉取，以拉到的内容为准'
            '（工具结果太多时，输出里有完整内容的临时文件路径，用 Read / grep 看）：\n'
            + '\n'.join(f'- kb_plugin_call(plugin="{x["插件"]}", args=["{x["编号"]}"])　{x.get("名称", "")}「{x.get("标题", "")}」{x.get("地址", "")}'
                         for x in src)
            + '\n拉到的内容里别人已经做过的分析可以参考，但结论要在本地代码里核实（代码位置、提交、分支），不要照搬；不要把整段原文存进知识库。')


def task_push(period, text='', by='用户（网页）'):
    """事项页「分析推动」：你本人点按钮 = 批准处理。会话在跑就把输入发给它；没在跑就带着输入启动（已完成的先重新打开）。"""
    d = period_dir(period)
    m = load_meta(d)
    text = (text or '').strip()
    s = _devsession.dev_session(d.name)
    if s and s.get('状态') == '运行中':
        if not text:
            raise KBError('后台会话正在处理；要补充什么写在输入框里再点')
        return _devsession.dev_chat(d.name, text)
    log(d, '分析推动', (text or '（没有补充说明）') + f'（{by}）')
    if m.get('状态') == '已完成':
        set_status(d.name, '已暂停', '网页「分析推动」重新打开', by_human=True)
    return _devsession.dev_start(d.name, note=text or '网页「分析推动」')


def run_plugins(event, d, root='', branch='', docs='', only=''):
    """在某个时机运行挂载的插件（only：手动运行指定插件，不看挂载和时机）。返回给人 / AI 看的结果，没有插件运行时为空。"""
    res = []
    for p in plugins():
        if only and p['id'] != only:
            continue
        if not only and not (p['启用'] and event in p['时机']) or p.get('工具') or p.get('Bug平台'):
            continue
        name = p.get('名称') or p['id']
        if p.get('错误'):
            res.append(f'插件「{name}」没有运行：{p["错误"]}')
            continue
        if not root or not Path(root).is_dir():
            res.append(f'插件「{name}」没有运行：{"这一期" if d else ""}还没有确定代码仓库')
            continue
        root = Path(root)
        miss = [x for x in p.get('识别文件', []) if not (root / x).exists()]
        if miss:
            if only:
                res.append(f'插件「{name}」没有运行：仓库 {root.name} 里没有 {"、".join(miss)}')
            continue
        before = _git_changed(root)
        try:
            env = _plugin_env(p, f'插件 {event}', KB_EVENT=event, KB_PERIOD=d.name if d else '', KB_PERIOD_DIR=str(d or ''), KB_REPO=str(root),
                              KB_BRANCH=branch or '', KB_DOCS=str(docs or ''))
        except KBError as e:
            res.append(f'插件「{name}」没有运行：{e}')
            continue
        cmd = [sys.executable if x == '{python}' else x for x in p['命令']]
        t0 = time.time()
        try:
            r = subprocess.run(cmd, cwd=p['目录'], env=env, capture_output=True, text=True,
                               timeout=int(p.get('超时') or 300))
            ok, out = r.returncode == 0, (r.stdout + ('\n' + r.stderr if r.stderr.strip() else '')).strip()
        except subprocess.TimeoutExpired:
            ok, out = False, f'超时（{p.get("超时") or 300} 秒）'
        except OSError as e:
            ok, out = False, f'启动失败：{e}'
        after = _git_changed(root)
        changed = sorted(f for f in set(before) | set(after) if before.get(f) != after.get(f))
        head = (f'插件「{name}」（{event}）{"完成" if ok else "失败"}，用时 {time.time() - t0:.0f} 秒，'
                + (f'仓库 {root.name} 有 {len(changed)} 个文件改动' if changed else '没有文件改动'))
        if d:
            log(d, '插件', f'{head}：{out[-1500:]}')
        if not ok and d:
            _devices._add_issue(d, f'插件「{name}」运行失败（{event}）', out[-2000:], kind='工具链', source='插件',
                       key=f'插件:{p["id"]}:{event}')
        res.append(head + (f'\n{out[-3000:]}' if out else ''))
    return '\n\n'.join(res)


def run_plugin_now(pid, period, event='开发开始'):
    """手动运行一次（网页「运行一次」/ kb plugin run），用这一期的开发仓库。"""
    d = period_dir(period)
    m = load_meta(d)
    root = m.get('开发仓库') or ''
    if not root:
        raise KBError(f'「{d.name}」还没有确定开发仓库（开始开发时会确定）')
    cur = _devprep._git(Path(root), 'branch', '--show-current').stdout.strip() if Path(root).is_dir() else ''
    return run_plugins(event, d, root, cur, m.get('SDD目录', ''), only=get_plugin(pid)['id']) or '没有运行'
