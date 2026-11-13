"""全栈：一期挂多个端的仓库（服务端 / Web / iOS / Android / 鸿蒙），AI 先出「需求规格 + 设计对照 + 影响分析 + 接口契约」，你拍板后各端再开工。

一人全栈的第一道关卡（拍板 1）：
  1. 各端仓库：期信息「各端」{端: {仓库, 分支}}；仓库从基础信息里的本地路径、登记的仓库、各期用过的开发仓库里选，按仓库里的文件自动认端。
  2. 出方案：后台只读会话读这一期资料和各端代码，用 kb_stack_plan 交回「方案」（涉及哪些端、各端改什么、接口、待确认）
     和接口契约草案（OpenAPI YAML）。存在 期/<名>/全栈/方案.json、全栈/api/openapi.yaml。
  3. 拍板（只能你在网页上点）：契约锁成 api/openapi.v<N>.yaml，之后各端按这个版本开发；要改就提意见重出方案。
各端用什么开发流程仍按「⚙ 设置 → 开发流程」的识别文件自动匹配；服务端自己的 SDD 以后作为一套流程接入，现在先按仓库现有约定。
"""
import json
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path

from .common import PERIODS, KBError, now
from . import hosts
from .periods import design_previews, load_meta, log, period_dir, period_names, save_meta
from .repos import load_repos
from .devsession import _alive, _dev_result, _notify
from .engines import engine_popen, role_engine
from .flows import flow_for
from .pluginrun import base_repo_paths
from . import lazy
_stackdev = lazy('kblib.stackdev')      # 上层模块：用到时才 import
_fix = lazy('kblib.bugs.fix')

ENDS = ('服务端', 'Web', 'iOS', 'Android', '鸿蒙')
STACK_DIR = '全栈'
_PROCS = {}

_WEB_DEPS = ('react', 'vue', 'next', 'nuxt', 'svelte', '@angular/core', 'vite', 'umi')
_SRV_DEPS = ('express', 'koa', '@nestjs/core', 'egg', 'fastify', 'hapi', 'midway')
_PATS = {'鸿蒙': ['oh-package.json5', 'build-profile.json5', 'AppScope/app.json5'],
         'Android': ['*/src/main/AndroidManifest.xml', 'src/main/AndroidManifest.xml'],
         'iOS': ['*.xcodeproj', '*.xcworkspace', 'Podfile', '*/*.xcodeproj', 'Package.swift'],
         '服务端': ['pom.xml', 'go.mod', 'Cargo.toml', 'composer.json', 'pyproject.toml', 'requirements.txt', 'manage.py',
                  'src/main/java', 'src/main/kotlin', 'src/main/resources/application.yml', 'src/main/resources/application.properties']}


def detect_ends(loc):
    """按仓库里的文件认是哪个端（可能不止一个，如前后端同仓）；本机、远程一样。"""
    try:
        have, files = hosts.probe(loc, [x for v in _PATS.values() for x in v], cat=['package.json'])
    except KBError:
        return []
    try:
        pj = json.loads(files.get('package.json') or '{}')
        deps = {**(pj.get('dependencies') or {}), **(pj.get('devDependencies') or {})}
    except ValueError:
        deps = {}
    hit = lambda e: any(x in have for x in _PATS[e])
    out = [e for e in ('鸿蒙', 'Android', 'iOS') if hit(e)]
    if 'react-native' not in deps and any(k in deps for k in _WEB_DEPS):
        out.append('Web')
    srv = [x for x in _PATS['服务端'] if x in have and not ('Android' in out and x.startswith('src/main/'))]
    if srv or any(k in deps for k in _SRV_DEPS):
        out.append('服务端')
    return out


def stack_repos():
    """可选的本地仓库：基础信息里的本地路径 + 登记的仓库 + 各期用过的开发仓库，附认出的端、当前分支。"""
    seen = {}
    for r in base_repo_paths():
        seen.setdefault(r['路径'], r['名称'])
    for nm, r in load_repos().items():
        seen.setdefault(str(Path(r['路径'] if isinstance(r, dict) else r).expanduser()), nm)
    for n in period_names():
        m = load_meta(PERIODS / n)
        for x in [m.get('开发仓库')] + [v.get('仓库') for v in (m.get('各端') or {}).values()]:
            if x:
                seen.setdefault(x, Path(x).name)
    out = []
    for pth, nm in seen.items():
        if hosts.is_remote(pth):          # 远程的不在这里逐个连（慢），选了再校验
            out.append({'路径': pth, '名称': nm, '端': [], '分支': '', '远程': True})
            continue
        kind = 'git' if (Path(pth) / '.git').exists() else 'svn' if (Path(pth) / '.svn').exists() else ''
        if not kind:
            continue
        out.append({'路径': pth, '名称': nm, '端': detect_ends(pth), '版本库': kind, '分支': hosts.branch_of(pth, kind)})
    return sorted(out, key=lambda x: (ENDS.index(x['端'][0]) if x['端'] else 9, x['名称']))


def period_ends(d, m=None):
    """这一期的各端；老的单仓库期（只有「开发仓库」）按认出的端补上。"""
    m = m or load_meta(d)
    ends = dict(m.get('各端') or {})
    if not ends and m.get('开发仓库'):
        e = (detect_ends(m['开发仓库']) or ['Android'])[0]
        ends[e] = {'仓库': m['开发仓库'], '分支': (m.get('开发会话') or {}).get('分支', ''), '来自': '开发仓库'}
    return ends


def stack_set_end(name, end, repo='', branch='', by='用户（网页）'):
    """设这一期某个端的仓库和分支；repo 为空 = 这一期不涉及这个端。"""
    if end not in ENDS:
        raise KBError(f'端只能是：{"、".join(ENDS)}')
    d = period_dir(name)
    m = load_meta(d)
    ends = period_ends(d, m)
    repo = (repo or '').strip()
    if repo:
        rp = hosts.check_repo(repo)          # 路径不存在 / 不是 git 仓库或 svn 工作副本 / 远程连不上 都在这里报
        kind = hosts.vcs(rp)
        branch = (branch or '').strip()
        if kind == 'svn' and branch:
            branch = hosts.svn_branch(rp, branch)        # feat-x → branches/feat-x（服务器上没有就报错）
        ends[end] = {'仓库': rp, '分支': branch, '版本库': kind}
        msg = f'{end}：{hosts.label(rp)}' + ('（svn：AI 只改工作副本，你验收后由知识库提交）' if kind == 'svn' else '') + (f'，分支 {branch}' if branch else '')
    else:
        ends.pop(end, None)
        msg = f'{end}：不涉及'
    for v in ends.values():
        v.pop('来自', None)
    m['各端'] = ends
    save_meta(d, m)
    log(d, '各端', f'{msg}（{by}）')
    dev = m.get('各端开发') or {}
    if repo and dev and end not in dev and end in ((m.get('全栈') or {}).get('涉及') or []):   # 变更后要做、之前缺仓库的端：选好就开工
        msg += '；' + _stackdev.stack_dev_start(d.name, end, by)
    return msg


# ---------------------------------------------------------------- 方案（影响分析 + 接口契约）

def _sdir(d):
    return d / STACK_DIR


def _last_approved(d):
    vs = sorted(_sdir(d).glob('方案.v*.json'), key=lambda p: int(p.stem.split('.v')[-1]) if p.stem.split('.v')[-1].isdigit() else 0)
    return vs[-1] if vs else None


def _incr_rule(d):
    p = _last_approved(d)
    if not p:
        return ''
    return (f'这一期已经拍板过方案（{p}），现在是【增量修改】：在它的基础上改，已有需求的编号不要变，新需求接着往后编号；'
            '改了或新增的需求、各端改动、接口，在描述后面注明（变更 CR-xxx）。原来不涉及、现在因为变更必须做的端，把「涉及」改成 true 并写清原因；'
            f'接口契约在已锁定版本（{_sdir(d) / "api"} 下最新的 openapi.vN.yaml）上改，没变就原样交回。'
            '在 plan 里加 "变更": [{"编号": "CR-001", "处理": "纳入 / 不需要改 / 建议驳回", "说明": "影响了哪些端、哪些需求"}]。')


def _plan_prompt(d, ends, note):
    rows = '\n'.join(f'- {e}：{v["仓库"]}' + (f'（分支 {v["分支"]}）' if v.get('分支') else '')
                     + ('　← 在远程机器上：用 kb_repo_read（repo 填这个地址）列目录、读文件、搜索' if hosts.is_remote(v['仓库']) else '')
                     for e, v in ends.items())
    old = _sdir(d) / '方案.json'
    return f"""你是由知识库网页启动的【后台无人值守、只读】全栈方案会话。终端里没有人，不要提问，不要改任何文件、不要切分支、不要提交。
用户一个人做全栈，所有端都由 AI 开发、用户拍板。现在要出「需求规格 + 设计稿对照 + 影响分析 + 接口契约」，给用户做第一次拍板。

这一期：「{d.name}」。用 kb_period（name=「{d.name}」）看需求、设计图、接口文档等资料，必要时 kb_read 读全文；kb_search 可搜资料和代码。
各端仓库（只读，用来判断现有接口、数据结构、模块位置）：
{rows}
{f'用户的意见 / 这次要处理的变更：{note}' if note else ''}
{_incr_rule(d)}

要做的事（一次做完，用户只拍板一次）：
1. 需求规格化：把资料里的需求拆成一条条可验收的需求，编号 REQ-001 起；每条写清验收标准（「当…时，应…」，可测、不含糊），标出涉及哪些端。
   资料里没写、但做的时候必须定的（空态、加载、报错、无网、权限、上限、时区、多语言…）也补成需求或放进待确认。
2. 设计稿对照：看这一期「设计图」里的图（kb_period 里有路径，图片直接读；PSD 已转成同名 .png 预览；蓝湖只有链接的看不到，记进「无法核对」）。
   如果你能用 Figma 的 MCP 工具，也可以直接看资料里的 Figma 链接。逐条需求找对应的画板，列出：需求有、设计没画的；设计画了、需求没写的；
   页面缺的状态（空态 / 加载 / 报错 / 无网 / 权限等）；各端设计不一致的地方。没有设计稿就在「无法核对」里写明。
3. 影响分析：判断每个端是否涉及、为什么、要改什么（落到模块 / 页面 / 类，基于读到的代码，不要泛泛而谈）。上面没列出仓库的端也要判断是否需要（需要的话在待确认里提出来）。
4. 接口契约：需要新增或修改服务端接口时，先在服务端仓库里找现有接口的写法（路由、鉴权、返回包装、错误码、分页），按同样的约定写 OpenAPI 3 YAML。
   客户端已有接口复用的也列出来（标「复用」）。不需要接口就不写 openapi。接口的说明里写上对应的需求编号。
5. 待确认：需求说不清、设计和需求对不上、要用户拍板的点，每条给出你的建议（用户开了免打扰时会直接按建议走）。

最后调用一次 kb_stack_plan 交回（只交一次，交完就结束）：
- iteration=「{d.name}」
- plan：JSON 字符串，格式：
  {{"摘要": "一两句话：做什么、涉及哪几端",
   "需求": [{{"编号": "REQ-001", "标题": "…", "描述": "…", "验收": ["当…时，应…", …], "端": ["Android", "服务端"], "设计": ["对应的画板 / 图片文件名"], "来源": "资料里的出处（文件名或链接）"}}],
   "设计对照": {{"缺设计": ["REQ-003：…"], "设计多出": ["画板 xx 里的 …，需求没写"], "缺状态": [{{"页面": "…", "缺": "空态 / 加载 / 报错 / 无网 / 权限…"}}],
              "端不一致": ["…"], "无法核对": "没有设计稿 / 蓝湖只有链接 等（都核对了就留空）"}},
   "各端": [{{"端": "服务端/Web/iOS/Android/鸿蒙", "涉及": true, "原因": "…", "改动": ["模块或文件：改什么（REQ-001）", …], "工作量": "小/中/大", "风险": "…"}}],
   "接口": [{{"方法": "GET", "路径": "/api/…", "说明": "…（REQ-001）", "类型": "新增/修改/复用", "调用端": ["iOS", "Android"]}}],
   "数据": ["表 / 字段 / 缓存 / 配置的变化"],
   "待确认": [{{"问题": "…", "建议": "…"}}]}}
- openapi：OpenAPI 3 YAML 全文（只含新增和修改的接口；没有就留空）。
"""


def spec_md(name, plan):
    """方案里的需求写成 spec.md：各端开发、审查、验收都按它（需求编号贯穿到提交和测试）。"""
    out = [f'# {name} · 需求规格', '', f'> 由知识库全栈方案生成（{plan.get("时间", "")}），拍板后作为各端开发和验收的依据。', '',
           plan.get('摘要', ''), '']
    for r in plan.get('需求') or []:
        out += [f'## {r["编号"]} {r.get("标题", "")}', '', r.get('描述', ''), '',
                f'- 端：{"、".join(r.get("端") or []) or "—"}', f'- 设计：{"、".join(r.get("设计") or []) or "—"}',
                f'- 来源：{r.get("来源") or "—"}', '', '验收标准：', ''] + [f'- [ ] {a}' for a in r.get('验收') or []] + ['']
    dc = plan.get('设计对照') or {}
    if any(dc.get(k) for k in ('缺设计', '设计多出', '缺状态', '端不一致', '无法核对')):
        out += ['## 设计对照', '']
        for k in ('缺设计', '设计多出', '端不一致'):
            out += [f'- {k}：{x}' for x in dc.get(k) or []]
        out += [f'- 缺状态：{x.get("页面", "")} 缺 {x.get("缺", "")}' for x in dc.get('缺状态') or []]
        if dc.get('无法核对'):
            out.append(f'- 无法核对：{dc["无法核对"]}')
        out.append('')
    return '\n'.join(out)


def stack_plan_start(name, note='', by='用户（网页）'):
    """网页「出方案」：起一个只读后台会话，读资料和各端代码，交回影响分析和接口契约。"""
    d = period_dir(name)
    m = load_meta(d)
    s = m.get('全栈会话') or {}
    if s.get('状态') == '运行中' and _alive(s.get('pid', 0)):
        raise KBError('方案正在出，等它结束')
    ends = period_ends(d, m)
    if not ends:
        raise KBError('先选至少一个端的仓库')
    for e, v in ends.items():
        hosts.check_repo(v['仓库'])
    crs = [x for x in m.get('全栈变更') or [] if x['状态'] in ('待评估', '评估中')]
    if crs:
        note = ((note or '').strip() + '\n' if (note or '').strip() else '') + '\n'.join(
            f'- {x["编号"]}（{x["来源"]}，{x["时间"]}）{x["标题"]}：{x.get("说明", "")}' + (f'（可能影响：{"、".join(x["影响端"])}）' if x.get('影响端') else '')
            for x in crs)
        for x in crs:
            x['状态'] = '评估中'
        save_meta(d, m)
    dev = m.get('各端开发') or {}
    for e, v in ends.items():             # 分析代码前更新：这一端有会话在改就只 fetch，不动它的工作区
        busy = dev.get(e, {}).get('状态') in ('开发中', '审查中') or (not hosts.is_remote(v['仓库']) and _fix._repo_busy(v['仓库']))
        log(d, '更新代码', f'{e} 出方案前：' + hosts.sync(v['仓库'], v.get('版本库', ''), branch=v.get('分支', ''), fetch_only=bool(busy)))
    design_previews(d)                    # PSD 等先转好 PNG 预览，AI 才看得到
    eng = role_engine('方案', m)
    _sdir(d).mkdir(exist_ok=True)
    logf = _sdir(d) / f'方案会话-{datetime.now():%Y%m%d-%H%M%S}.jsonl'
    extra = []
    if eng.get('id') == 'claude' or Path(eng.get('命令') or '').name == 'claude':
        extra = ['--disallowedTools', 'Edit', 'Write', 'MultiEdit', 'NotebookEdit']
        for v in ends.values():
            if not hosts.is_remote(v['仓库']):
                extra += ['--add-dir', v['仓库']]
    proc = engine_popen(eng, _plan_prompt(d, ends, (note or '').strip()), f'kb·全栈方案·{d.name}', logf, str(d),
                        env_extra={'KB_SESSION': 'stack:' + d.name}, extra_args=extra)
    _PROCS[d.name] = proc
    m = load_meta(d)
    m['全栈会话'] = {'状态': '运行中', 'pid': proc.pid, '开始时间': now(), '日志': str(logf), '引擎': eng['名称'], '意见': (note or '').strip()}
    st = m.setdefault('全栈', {})
    st['状态'] = '出方案中'
    save_meta(d, m)
    log(d, '全栈', f'出方案：{"、".join(ends)}' + (f'；意见：{note.strip()}' if (note or '').strip() else '') + f'（{by}，{eng["名称"]}）')

    def wait():
        code = proc.wait()
        _PROCS.pop(d.name, None)
        _plan_finish(d.name, code)
    threading.Thread(target=wait, daemon=True).start()
    return f'已交给 {eng["名称"]} 出方案（只读），几分钟后在这里看结果'


def _plan_finish(name, code=None):
    d = period_dir(name)
    m = load_meta(d)
    s = m.get('全栈会话') or {}
    if s.get('状态') != '运行中':
        return
    res = _dev_result(s.get('日志', ''))
    s.update(状态='已结束', 结束时间=now(), 退出码=code, 结果=(res.get('结果') or '')[:1500], 费用=res.get('费用'))
    st = m.setdefault('全栈', {})
    if st.get('状态') == '出方案中':          # 没交方案就结束了
        st['状态'] = '出方案失败'
        for x in m.get('全栈变更') or []:
            if x['状态'] == '评估中':
                x['状态'] = '待评估'
        log(d, '全栈', f'方案会话结束但没有交回方案（退出码 {code}）：{s["结果"][:300]}')
    m['全栈会话'] = s
    save_meta(d, m)
    _notify('知识库 · 全栈方案', f'「{d.name}」' + ('方案出好了，等你拍板' if st.get('状态') == '待拍板' else '方案没出来，看记录'))


def stack_plan_submit(name, plan, openapi='', by='Claude'):
    """kb_stack_plan：方案会话交回影响分析和接口契约草案。"""
    d = period_dir(name)
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except ValueError as e:
            raise KBError(f'plan 不是合法 JSON：{e}')
    if not isinstance(plan, dict) or not isinstance(plan.get('各端'), list):
        raise KBError('plan 至少要有「各端」列表')
    bad = [x.get('端') for x in plan['各端'] if x.get('端') not in ENDS]
    if bad:
        raise KBError(f'端只能是：{"、".join(ENDS)}；不认识：{bad}')
    openapi = (openapi or '').strip()
    if openapi and not re.search(r'^\s*(openapi|swagger)\s*:', openapi, re.M):
        raise KBError('openapi 要是 OpenAPI 3 的 YAML（开头 openapi: 3.x）')
    sd = _sdir(d)
    (sd / 'api').mkdir(parents=True, exist_ok=True)
    plan['时间'], plan['提交人'] = now(), by
    reqs = plan.get('需求') or []
    ids = [x.get('编号') for x in reqs]
    if any(not re.fullmatch(r'REQ-\d{3,}', str(i or '')) for i in ids) or len(set(ids)) != len(ids):
        raise KBError('需求编号要是 REQ-001 这样、且不重复')
    (sd / '方案.json').write_text(json.dumps(plan, ensure_ascii=False, indent=1), 'utf-8')
    (sd / 'spec.md').write_text(spec_md(d.name, plan), 'utf-8')
    api = sd / 'api' / 'openapi.yaml'
    if openapi:
        api.write_text(openapi + '\n', 'utf-8')
    elif api.exists():
        api.unlink()
    m = load_meta(d)
    st = m.setdefault('全栈', {})
    st.update(状态='待拍板', 方案时间=now())
    for x in m.get('全栈变更') or []:
        if x['状态'] == '评估中':
            x['状态'] = '待拍板'
    save_meta(d, m)
    ends = [x['端'] for x in plan['各端'] if x.get('涉及')]
    dc = plan.get('设计对照') or {}
    gaps = sum(len(dc.get(k) or []) for k in ('缺设计', '设计多出', '缺状态', '端不一致'))
    log(d, '全栈', f'方案交回：需求 {len(reqs)} 条，设计问题 {gaps} 处，涉及 {"、".join(ends) or "（无）"}，接口 {len(plan.get("接口") or [])} 个，待确认 {len(plan.get("待确认") or [])} 条（{by}）')
    return f'已收到方案：涉及 {"、".join(ends)}；等用户在网页上拍板'


def stack_approve(name, by='用户（网页）'):
    """拍板 1（只能本人在网页上点）：方案定下来，接口契约锁成一个版本。"""
    d = period_dir(name)
    m = load_meta(d)
    st = m.get('全栈') or {}
    if st.get('状态') != '待拍板':
        raise KBError('现在没有待拍板的方案')
    sd = _sdir(d)
    plan = json.loads((sd / '方案.json').read_text('utf-8'))
    prev = _last_approved(d)
    old = json.loads(prev.read_text('utf-8')) if prev else None
    api = sd / 'api' / 'openapi.yaml'
    ver, newver = st.get('契约版本', ''), False
    if api.exists():
        locked = sd / 'api' / f'openapi.{ver}.yaml' if ver else None
        if not (locked and locked.exists() and locked.read_text('utf-8') == api.read_text('utf-8')):   # 契约没变就不升版本
            n = 1 + max([int(x.stem.split('.v')[-1]) for x in (sd / 'api').glob('openapi.v*.yaml') if x.stem.split('.v')[-1].isdigit()] + [0])
            ver, newver = f'v{n}', True
            shutil.copy2(api, sd / 'api' / f'openapi.{ver}.yaml')
    pn = 1 + (int(prev.stem.split('.v')[-1]) if prev and prev.stem.split('.v')[-1].isdigit() else 0)
    shutil.copy2(sd / '方案.json', sd / f'方案.v{pn}.json')
    crs = [x for x in m.get('全栈变更') or [] if x['状态'] == '待拍板']
    for x in crs:
        x.update(状态='已纳入', 纳入方案=f'v{pn}', 纳入时间=now())
    st.update(状态='已拍板', 拍板时间=now(), 拍板人=by, 契约版本=ver, 方案版本=f'v{pn}',
              涉及=[x['端'] for x in plan['各端'] if x.get('涉及')])
    m['全栈'] = st
    save_meta(d, m)
    log(d, '全栈', f'拍板方案 v{pn}：涉及 {"、".join(st["涉及"])}' + (f'，接口契约 {ver}{"（新版本）" if newver else ""}' if ver else '，不涉及接口')
        + (f'；纳入变更 {"、".join(x["编号"] for x in crs)}' if crs else '') + f'（{by}）')
    out = '已拍板' + (f'，接口契约{"锁定为" if newver else "仍是"} {ver}' if ver else '')
    if m.get('各端开发') and old:           # 开发中又拍板（变更 / 重出方案）：算出各端要补什么
        out += '；' + _stackdev.plan_changed(d, old, plan, ver if newver else '')
    if any(x['状态'] == '待评估' for x in load_meta(d).get('全栈变更') or []):
        stack_plan_start(d.name, by='自动（还有没评估的变更）')
    return out


# ---------------------------------------------------------------- 变更：做的过程中发现要改需求、要别的端配合、要改契约
def stack_change_add(name, title, detail='', ends=None, by='用户（网页）'):
    """提一个变更（你在网页上，或某一端的开发会话用 kb_stack_change）。已经有方案的，自动起增量方案会话评估，评估完你拍板。"""
    d = period_dir(name)
    title = (title or '').strip()
    if not title:
        raise KBError('变更要写一句是什么')
    ends = [e for e in (ends if isinstance(ends, list) else [x for x in re.split(r'[、,，\s]+', ends or '') if x]) if e]
    bad = [e for e in ends if e not in ENDS]
    if bad:
        raise KBError(f'端只能是：{"、".join(ENDS)}')
    m = load_meta(d)
    xs = m.setdefault('全栈变更', [])
    cid = f'CR-{len(xs) + 1:03d}'
    xs.append({'编号': cid, '标题': title, '说明': (detail or '').strip(), '影响端': ends, '来源': by, '时间': now(), '状态': '待评估'})
    save_meta(d, m)
    log(d, '全栈变更', f'{cid} {title}' + (f'（可能影响 {"、".join(ends)}）' if ends else '') + f'（{by}）')
    s = m.get('全栈会话') or {}
    if (m.get('全栈') or {}).get('状态') in ('已拍板', '开发中', '各端完成') and not (s.get('状态') == '运行中' and _alive(s.get('pid', 0))):
        try:
            stack_plan_start(d.name, by=f'自动（变更 {cid}）')
            return f'已记下 {cid}，正在出增量方案，出好后等用户拍板'
        except KBError as e:
            return f'已记下 {cid}；自动评估没起来：{e}'
    return f'已记下 {cid}，下次出方案时一起评估'


def stack_change_reject(name, cid, by='用户（网页）'):
    d = period_dir(name)
    m = load_meta(d)
    x = next((x for x in m.get('全栈变更') or [] if x['编号'] == cid), None)
    if not x:
        raise KBError(f'没有变更 {cid}')
    if x['状态'] in ('已纳入',):
        raise KBError(f'{cid} 已经纳入方案了；要撤回就再提一个变更')
    x.update(状态='已驳回', 驳回时间=now(), 驳回人=by)
    save_meta(d, m)
    log(d, '全栈变更', f'{cid} 驳回（{by}）')
    return f'已驳回 {cid}'


def stack_get(name):
    """网页「全栈」板块。"""
    d = period_dir(name)
    m = load_meta(d)
    s = m.get('全栈会话') or {}
    if s.get('状态') == '运行中' and d.name not in _PROCS and not _alive(s.get('pid', 0)):
        _plan_finish(d.name)
        m = load_meta(d)
        s = m.get('全栈会话') or {}
    sd = _sdir(d)
    plan = None
    spec = sd / 'spec.md'
    if (sd / '方案.json').exists():
        try:
            plan = json.loads((sd / '方案.json').read_text('utf-8'))
        except ValueError:
            plan = None
    api = sd / 'api' / 'openapi.yaml'
    ends = period_ends(d, m)
    rows = []
    for e in ENDS:
        v = ends.get(e)
        if v:
            remote = hosts.is_remote(v['仓库'])
            f = None if remote else flow_for(m, v['仓库']) if Path(v['仓库']).is_dir() else None
            kind = v.get('版本库') or 'git'
            cur = '' if remote else hosts.branch_of(v['仓库'], kind) if Path(v['仓库']).is_dir() else ''
            rows.append({'端': e, '仓库': v['仓库'], '显示': hosts.label(v['仓库']), '远程': remote, '分支': v.get('分支', ''), '当前分支': cur,
                         '版本库': kind,
                         '流程': '（远程：开工时在那台机器上匹配）' if remote else f['名称'] if f else '（没有匹配的流程）', '来自': v.get('来自', '')})
        else:
            rows.append({'端': e})
    return {'各端': rows, '状态': (m.get('全栈') or {}).get('状态', ''), '全栈': m.get('全栈') or {},
            '会话': {k: s.get(k) for k in ('状态', '开始时间', '结束时间', '引擎', '结果', '意见')} if s else None,
            '方案': plan, '契约': api.read_text('utf-8') if api.exists() else '', '契约路径': str(api) if api.exists() else '',
            '规格路径': str(spec) if spec.exists() else '', '开发': _stackdev.stack_dev_view(d, m),
            '变更': m.get('全栈变更') or [], '证据': _stackdev.evidence(d, m, plan),
            '并行上限': _stackdev.MAX_PAR, '审查轮数': _stackdev.MAX_ROUNDS}
