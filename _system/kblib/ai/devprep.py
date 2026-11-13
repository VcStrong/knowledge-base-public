# From 大大王.DT
"""开发准备：定仓库、分支、拷资料、生成开发提示。"""
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote
from urllib.parse import urlparse
from kblib.core.common import CATS, DEV_OK, HIST, KBError, KBNeed, NOTE_SUFFIX, PROTO_DIR, now, read_text
from kblib.core.periods import load_meta, log, period_dir, save_meta
from kblib.core.notes import BRANCH_RE, NOTES_FILE, URL_RE, note_md, note_title, notes_of
from kblib.core.repos import load_repos
from kblib.core.baseinfo import BASE_MD, base_load
from kblib.ai.flows import flow_docs, flow_for, flow_text, flows, get_flow
from kblib import lazy
_urlimport = lazy('kblib.sources.urlimport')      # 上层模块：用到时才 import（不形成循环）
_fixlink = lazy('kblib.sources.fixlink')      # 上层模块：用到时才 import（不形成循环）


PATH_RE = re.compile(r'(?:~|/(?:Users|Volumes|home|opt|private|data|srv))/[^\s，。；;、()（）【】「」"\'<>]+')


def _git(root, *args, timeout=15):
    try:
        return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 1, '', 'timeout')


def _git_root(p):
    p = Path(p).expanduser()
    if not p.is_dir():
        return None
    r = _git(p, 'rev-parse', '--show-toplevel')
    return Path(r.stdout.strip()).resolve() if r.returncode == 0 and r.stdout.strip() else None


def want_branches(d, m):
    """本期登记的开发分支：「分支」类文字资料，或标题 / 内容写了「分支」的文字资料里的分支名；网页确认过的排最前。"""
    out = [m['开发分支']] if m.get('开发分支') else []
    for n in notes_of(d, m=m):
        title, body = n.get('标题') or '', URL_RE.sub(' ', n.get('内容') or '')
        if n['类型'] != '分支' and '分支' not in title + body and 'branch' not in (title + body).lower():
            continue
        out += BRANCH_RE.findall(body)
        for f in flows():
            if f.get('分支规则'):
                try:
                    out += [x if isinstance(x, str) else x[0] for x in
                            re.findall(r'(?<![\w/.-])(?:' + f['分支规则'] + r')(?![\w/.-])', body)]
                except re.error:
                    pass
        rest = re.sub(r'^.*?(?:分支|branch)\s*[:：]?\s*', '', body.strip(), flags=re.I) if re.search(r'分支|branch', body, re.I) else body.strip()
        if re.fullmatch(r'[A-Za-z][\w./-]{2,}', rest):     # 整条就是一个分支名
            out.append(rest)
    return [x for x in dict.fromkeys(out) if not PATH_RE.fullmatch(x)]


def _match_words(t):
    """比对用的词：英文 / 数字按整词（去掉末尾数字，如 app001 → app），中文按二字组。"""
    t = t.lower()
    out = {re.sub(r'\d+$', '', w) for w in re.findall(r'[a-z][a-z0-9_]{2,}', t)}
    for run in re.findall(r'[\u4e00-\u9fff]{2,}', t):
        out |= {run[i:i + 2] for i in range(len(run) - 1)}
    return {w for w in out if len(w) >= 2} - {'工程', '本地', '路径', '代码', '项目', '仓库', '开发', '测试', '运行', '用户', 'users', 'admin', 'documents', 'android', 'androidspace'}


def repo_candidates(d, m):
    """开发仓库候选（都是本机 git 仓库）：网页确认过的、关联的已登记仓库、文字资料里写的本地路径。"""
    out = {}

    def add(p, why, hint):
        root = _git_root(p)
        if not root:
            return
        x = out.setdefault(str(root), {'路径': str(root), '依据': [], '明确': False})
        x['依据'].append(why)
        x['明确'] = x['明确'] or hint
    if m.get('开发仓库'):
        add(m['开发仓库'], '网页上确认过', True)
    repos = load_repos()
    for r in m.get('关联仓库') or []:
        if r in repos:
            add(repos[r]['路径'], f'关联仓库 {r}', True)
    for n in notes_of(d, m=m):
        title, body = n.get('标题') or '', n.get('内容') or ''
        hint = bool(re.search(r'代码|工程|仓库|项目|repo', title, re.I)
                    or re.search(r'(代码|工程|仓库|项目)(路径|目录|地址)', body))
        for x in PATH_RE.findall(URL_RE.sub(' ', f'{title} {body} {n.get("链接") or ""}')):
            add(x.rstrip('.,:：'), f'文字资料 {n["编号"]}「{note_title(n)}」', hint)
    # 基础信息里登记的本机工程路径（如「xx工程本地路径」）：所有期共用。条目名 / 适用 / 目录名和这一期的内容对得上时算明确
    me = _match_words(' '.join([d.name, m.get('说明', ''), m.get('来自', '')]
                               + [f'{x.get("标题", "")} {x.get("编号", "")}' for x in m.get('外部来源') or []]
                               + [note_title(n) for n in notes_of(d, m=m)]))
    try:
        bes = base_load()['条目']
    except Exception:
        bes = []
    for e in bes:
        for fd in e.get('字段') or []:
            if fd.get('机密'):
                continue
            for x in PATH_RE.findall(str(fd.get('值') or '')):
                x = x.rstrip('.,:：')
                if not Path(x).expanduser().is_dir():
                    continue
                words = _match_words(f'{e.get("名称", "")} {e.get("适用", "")} {Path(x).name}')
                add(str(Path(x).expanduser()), f'基础信息 {e["编号"]}「{e.get("名称", "")}」', bool(words & me))
                r = out.get(str(_git_root(str(Path(x).expanduser())) or ''))
                if r is not None and not (words & me) and len(r['依据']) == 1:
                    r['只供选择'] = True          # 和这一期对不上的公共路径：弹窗里给你选，不自动用
    want = want_branches(d, m)
    for x in out.values():
        root = Path(x['路径'])
        f = flow_for(m, root)
        x['可用'], x['流程'] = bool(f), f['名称'] if f else ''
        x['当前分支'] = _git(root, 'branch', '--show-current').stdout.strip()
        x['有开发分支'] = any(_git(root, 'rev-parse', '--verify', '--quiet', b).returncode == 0 for b in want)
    return list(out.values())


def _pick_repo(cands, m):
    """候选里能确定是哪个就返回，不能就返回 None（交给用户选）。"""
    c = [x for x in cands if x['可用'] and not x.get('只供选择')]
    for x in c:
        if '网页上确认过' in x['依据']:
            return x
    for test in (lambda x: x['明确'], lambda x: True):
        hit = [x for x in c if test(x)]
        if len(hit) == 1:
            return hit[0]
        if len(hit) > 1:          # 再按开发分支挑：当前就在开发分支上 / 有开发分支的
            for t2 in (lambda x: x['有开发分支'] and x['当前分支'] in (m.get('_want') or []), lambda x: x['有开发分支']):
                h2 = [x for x in hit if t2(x)]
                if len(h2) == 1:
                    return h2[0]
            return None
    return None


def _sdd_repo(d, m, repo):
    if repo:
        root = _git_root(repo)
        if not root:
            repos = load_repos()
            if repo not in repos:
                raise KBError(f'不是本机的 git 仓库，也没有登记这个仓库名：{repo}')
            root = Path(repos[repo]['路径'])
        return root
    cands = repo_candidates(d, m)
    m = dict(m, _want=want_branches(d, m))
    x = _pick_repo(cands, m)
    if x:
        return Path(x['路径'])
    tip = '；'.join(f'{x["路径"]}（{"、".join(x["依据"])}{"，流程 " + x["流程"] if x["可用"] else "，没有匹配的开发流程"}）' for x in cands)
    if cands and not any(x['可用'] for x in cands):
        why = (f'找到了代码仓库，但都不符合开发流程（{"这一期选定「" + get_flow(m["开发流程"])["名称"] + "」" if m.get("开发流程") else "自动匹配"}）：'
               '请在开发面板为这一期选择流程（如「通用模板」），或在「⚙ 设置」里新建本组的流程')
        raise KBNeed(why + f'。候选：{tip}', {'需要': '仓库', '候选': cands, '分支': m['_want'], '说明': why})
    raise KBNeed('确定不了开发用哪个代码仓库，请用 repo 指定（仓库名或绝对路径）' +
                 (f'，候选：{tip}' if cands else '；本期文字资料里没有找到本机代码路径'),
                 {'需要': '仓库', '候选': cands, '分支': m['_want']})


def _sdd_sections(text):
    """sdd-start.md 的二级栏目 → 是否已填（去掉注释和模板自带的「前端框架:」这类空键）。"""
    res, cur = {}, None
    for line in re.sub(r'<!--.*?-->', '', text, flags=re.S).splitlines():
        if line.startswith('## '):
            cur = line[3:].strip()
            res[cur] = False
        elif cur and line.strip() and not re.fullmatch(r'\s*[^:：]+[:：]\s*', line):
            res[cur] = True
    return res


def _sdd_slot(url, cat, has_new_doc):
    host = urlparse(url).hostname or ''
    low = unquote(url).lower()
    if 'figma.com' in host:
        return 'Figma 设计稿'
    if 'lanhu' in host:
        return '备注（蓝湖，SDD 不能下载）'
    if re.search(r'\.(mp4|mov|zip|rar|apk|pdf|docx?|xlsx?)(\?|$)', low):
        return '备注（参考文件）'
    if cat == '接口文档':
        return '服务端接口'
    if 'axure' in host:
        if 'prd' in low:
            return '新版产品文档链接' if has_new_doc else '内网文档链接（Axure）'
        return '内网文档链接（Axure）'
    if 'confluence' in host or 'wiki' in host:
        return 'Confluence PRD 链接（需求总表 / 入口页按需取舍）'
    return '备注'


def _no_flow_msg(m, root):
    if m.get('开发流程'):
        f = get_flow(m['开发流程'])
        return f'{root} 不符合这一期选定的开发流程「{f["名称"]}」（缺少：{"、".join(x for x in f["识别文件"] if not (Path(root) / x).exists())}），请换仓库或在开发面板换流程'
    return f'{root} 没有匹配的开发流程，请在开发面板为这一期选择流程，或在「⚙ 设置」里新建本组的流程'


def _dev_target(d, m, repo='', store=''):
    """目标仓库、当前分支、开发流程、文档目录。"""
    root = _sdd_repo(d, m, repo)
    f = flow_for(m, root)
    if not f:
        raise KBNeed(_no_flow_msg(m, root), {'需要': '仓库', '候选': repo_candidates(d, m), '分支': want_branches(d, m),
                                              '说明': _no_flow_msg(m, root)})
    branch = _git(root, 'branch', '--show-current').stdout.strip()
    want = want_branches(d, m)
    if want and branch not in want:
        dirty = [x for x in _git(root, 'status', '--porcelain', '--untracked-files=no').stdout.splitlines() if x.strip()]
        raise KBNeed(f'{root.name} 当前分支是「{branch}」，本期登记的开发分支是「{"、".join(want)}」。'
                     '文档目录按分支生成，请先切到开发分支（AI 不要替用户切分支）',
                     {'需要': '分支', '仓库': str(root), '当前分支': branch, '分支': want,
                      '未提交': dirty[:30], '未提交数': len(dirty)})
    return root, branch, f, flow_docs(f, root, branch, d.name, store)


def dev_prepare(name, repo='', store=''):
    """开发前准备：按开发流程定位文档目录，把本期资料拷过去，整理候选链接；SDD 流程另外准备 sdd-start.md。"""
    d = period_dir(name)
    m = load_meta(d)
    if m.get('状态') not in DEV_OK:
        raise KBError(f'「{d.name}」当前状态是「{m.get("状态")}」，用户尚未批准开发。'
                      f'请提醒用户确认材料齐全后，在终端运行 kb approve "{d.name}"，或在知识库网页点「开始开发」')
    root, branch, f, docs = _dev_target(d, m, repo, store)
    if m.get('SDD目录') != str(docs):
        m = load_meta(d)
        m['SDD目录'] = str(docs)
        save_meta(d, m)
    sdd = f.get('准备方式') == 'SDD'
    KB_DIR = f.get('资料目录名') or 'kb-materials'
    docs.mkdir(parents=True, exist_ok=True)
    created = []
    if sdd:
        for sub in ('cache', 'tests/automation', 'tests/blackbox'):
            (docs / sub).mkdir(parents=True, exist_ok=True)
        tpl = root / '.claude' / 'sdd-templates'
        for fn, t in (('sdd-start.md', 'sdd-start-config-template.md'), ('sdd-status.md', 'sdd-status-template.md')):
            if not (docs / fn).exists() and (tpl / t).exists():
                shutil.copyfile(tpl / t, docs / fn)
                created.append(fn)
        start = docs / 'sdd-start.md'
        if not start.exists():
            raise KBError(f'{tpl} 里没有 sdd-start 模板，请先在仓库里运行 /sdd-start 生成 {start} 后再调用')

    # 资料副本：每次重建；不进 git（图片多，而文档目录一般是入库的）
    out = docs / KB_DIR
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    for c in CATS + [_urlimport.SRC_DIR]:
        if (d / c).exists():
            shutil.copytree(d / c, out / c, ignore=shutil.ignore_patterns(HIST, '.*'))
    if BASE_MD.exists():
        shutil.copyfile(BASE_MD, out / '基础信息.md')
    (out / '.gitignore').write_text('*\n', 'utf-8')
    n_files = sum(1 for x in out.rglob('*') if x.is_file()) - 1

    srcs = m.get('来源') or []
    idx = [f'# 知识库资料：{d.name}', '',
           f'> 自动生成（{now()}，kb_dev_prepare），请勿手改；知识库更新后重新调用会覆盖。本目录不进 git。',
           f'> 期说明：{m.get("说明") or "无"}', '',
           '| 目录 | 用途 |', '|---|---|',
           '| 需求/ | 需求原文（PRD、需求表条目、口述需求）；需求/原型图/ 只用于理解交互，UI 不以它为准 |',
           '| 设计图/ | 要实现的设计稿（Figma 画板 PNG + 设计规格.md），UI 以此为准 |',
           '| 接口文档/ | 接口文档、协议说明 |', '| 其他资料/ | 分支、链接、环境等零散资料 |',
           f'| {_urlimport.SRC_DIR}/ | 导入时的整页原文快照 |',
           '| 基础信息.md | 所有期共用的账号、测试账号、代理 / VPN、环境配置（机密只显示掩码，用 kb_base_secret 读取） |',
           '', '## 来源', '']
    for x in srcs:
        fs = x.get('文件') or []
        n_proto = sum(PROTO_DIR in f for f in fs)
        idx += [f'### {x["编号"]} ［{x.get("类型", "资料")}］{x["标题"]}' + (f' · {x["条目"]}' if x.get('条目') else ''),
                f'- 地址：{x["地址"]}', f'- 简介：{x.get("简介") or ""}',
                '- 文件：' + '、'.join(f for f in fs if PROTO_DIR not in f)
                + (f'（另有原型图 {n_proto} 张）' if n_proto else ''), '']
    ns = notes_of(d, m=m)
    if ns:
        idx += ['## 文字资料', ''] + [note_md(n).replace('## ', f'### ［{n["分类"]}］', 1) + '\n' for n in ns]
    (out / 'README.md').write_text('\n'.join(idx) + '\n', 'utf-8')

    secs, has_new = {}, False
    if sdd:
        secs, has_new = _sdd_note_ref(start, KB_DIR)

    links = {}

    def add(url, cat, what):
        url = url.rstrip('.,;')
        if url not in links:
            links[url] = (_sdd_slot(url, cat, has_new) if sdd else _plain_slot(url, cat), what)
    for x in srcs:
        if x.get('作废'):
            continue
        cat = next((c for c in CATS if any(f.startswith(c + '/') for f in x.get('文件') or [])), '')
        add(x['地址'], cat, f'来源 {x["编号"]}《{x["标题"]}》{x.get("条目") or ""}：{(x.get("简介") or "")[:80]}')
    for n in ns:
        for u in ([n['链接']] if n.get('链接') else []) + _fixlink._urls(n.get('内容') or ''):
            add(u, n['分类'], f'文字资料 {n["编号"]} {note_title(n)}')
    for fp in sorted((d / '设计图').rglob('*.md')) if (d / '设计图').exists() else []:
        if HIST in fp.parts or fp.name.endswith(NOTE_SUFFIX) or fp.name == NOTES_FILE:
            continue
        for u in _fixlink._urls(read_text(fp)):
            add(u, '设计图', f'设计图/{fp.relative_to(d / "设计图")}')
    by = {}
    for u, (slot, what) in links.items():
        by.setdefault(slot, []).append(f'  - {u}\n    {what}')

    log(d, '开发准备', f'{f["名称"]} · {root.name}（{branch}）→ {docs}；资料 {n_files} 个文件 → {KB_DIR}/')
    if not sdd:
        v = dict(期名=d.name, 仓库=str(root), 分支=branch, 文档目录=str(docs), 资料目录=str(out))
        res = [f'已按开发流程「{f["名称"]}」准备好资料：{root.name}（分支 {branch}）',
               f'- 文档目录：{docs}', f'- 资料副本：{out}/（{n_files} 个文件，不进 git），索引 {KB_DIR}/README.md',
               '', '# 本期链接（按资料分类）']
        for slot, items in by.items():
            res += [f'- {slot}'] + items
        if not links:
            res.append('（本期没有登记链接）')
        res += ['', f'# 接下来按开发流程「{f["名称"]}」推进', flow_text(f, '开发步骤', **v)]
        return '\n'.join(res)
    return _sdd_prepare_result(d, root, branch, docs, start, created, out, n_files, secs, by, links, KB_DIR)


def _plain_slot(url, cat):
    host = urlparse(url).hostname or ''
    if 'figma.com' in host or 'lanhu' in host:
        return '设计稿'
    return cat or '其他资料'


def _sdd_note_ref(start, KB_DIR):
    """在 sdd-start.md「备注」里引用资料副本；返回栏目填写情况、是否有新版产品文档栏。"""
    text = start.read_text('utf-8')
    ref = f'知识库资料：{KB_DIR}/README.md（本期需求、设计稿、接口、文字资料的本地副本，SDD 下载失败或需要补充时参考）'
    if f'知识库资料：{KB_DIR}/' not in text:
        lines = text.rstrip('\n').split('\n')
        at = next((i for i, l in enumerate(lines) if l.startswith('## ') and '备注' in l), None)
        if at is None:
            lines += ['', '## 备注（可选）', '', ref]
        else:
            end = next((i for i in range(at + 1, len(lines)) if lines[i].startswith('## ')), len(lines))
            lines.insert(end, ref)
        text = '\n'.join(lines) + '\n'
        start.write_text(text, 'utf-8')
    secs = _sdd_sections(text)
    return secs, any('新版产品文档' in k for k in secs)


def _sdd_prepare_result(d, root, branch, docs, start, created, out, n_files, secs, by, links, KB_DIR):
    res = [f'已为 SDD 准备好资料：{root.name}（分支 {branch}）',
           f'- PROJECT_DOCS：{docs}',
           f'- sdd-start.md：{start}' + ('（按仓库模板新建）' if 'sdd-start.md' in created else '（已存在，保留原内容）'),
           f'- 资料副本：{out}/（{n_files} 个文件，不进 git），索引 {KB_DIR}/README.md，已写进 sdd-start.md「备注」',
           '- sdd-start.md 栏目：已填 ' + ('、'.join(k for k, v in secs.items() if v) or '无')
           + '；空 ' + ('、'.join(k for k, v in secs.items() if not v) or '无'),
           '', '# 候选链接（按 SDD 栏目建议，最终按 sdd-start.md 各栏注释判断）']
    for slot, items in by.items():
        res += [f'- {slot}'] + items
    if not links:
        res.append('（本期没有登记链接）')
    res += ['', '# 接下来由你完成（不用问用户）',
            '1. 读 sdd-start.md，按每栏注释里的格式要求把上面的链接填进对应的【空】栏；已填的栏不改，和知识库不一致的列给用户。',
            '2. 功能名称用本期需求名；负责范围按需求和文字资料写本端（如 Android 客户端）负责的部分；'
            '接口相关的文字资料（协议、字段）写进「服务端接口」作为 API 修改描述；拿不准的放「备注」，不要编造链接。',
            '3. 填完运行 /sdd-next 推进（物料由 SDD 自己的 /sdd-material 下载）；SDD 下载失败（如 Confluence 需登录）时，'
            f'用 {KB_DIR}/ 里的同名资料补充，并用 kb_log 记录。']
    return '\n'.join(res)


sdd_prepare = dev_prepare      # 旧名，开发中的会话可能还在用
