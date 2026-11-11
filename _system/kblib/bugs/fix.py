# From 大大王.DT
"""Bug 修复：审核通过后的独立修复会话和修复队列；只在知识库标记。"""
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from ..common import KBError, PERIODS, now, uuid_hex
from ..periods import load_meta, log, period_dir, period_names
from ..engines import engine_popen, get_engine
from ..devprep import _git
from ..devsession import _alive, _dev_env
from ..devices import dev_activity
from ..bugs.index import ZT_DIR, _zt_recheck, an_skip, zt_load, zt_save
from ..bugs.analysis import _AN, _an_finish, _an_load, _an_md, _an_save, _bug_repo, _fx_heal, an_sessions


FX_MAX_BUGS = 5
FIX_STATES = ('排队中', '修复中', '已修复', '未完成')


def _repo_busy(root):
    """这个仓库有没有别的会话在改：期 / 事项的开发会话，或别的修复会话。"""
    r = str(Path(root).resolve())
    for n in period_names():
        m = load_meta(PERIODS / n)
        sx = m.get('开发会话') or {}
        if sx.get('状态') == '运行中' and _alive(sx.get('pid', 0)) and m.get('开发仓库') and str(Path(m['开发仓库']).resolve()) == r:
            return f'「{n}」的开发会话正在这个仓库里运行'
    for x in an_sessions():
        if x.get('类型') == '修复' and x.get('状态') == '运行中' and str(Path(x['仓库']).resolve()) == r:
            return f'修复会话 {x["编号"]}（Bug {"、".join(x["Bug"])}）正在这个仓库里运行'
    return ''


def _fx_prompt(root, branch, items):
    out = [f"""你是由知识库网页启动的【后台无人值守】Bug 修复会话。用户已在网页审核通过了下面每个 Bug 的分析，并点了「修复」（等同批准改代码）。终端里没有人，不要提问。
代码仓库：{root}，分支 {branch}（已检出，工作区干净）。不要切换分支、不要 push、不要改和这些 Bug 无关的代码。不要改 Bug 平台（知识库从不回写）。
"""]
    for e in items:
        a = e['分析']
        locs = '\n'.join(f'    · {x["路径"]}:{x["行"]} {x["说明"]}' for x in a.get('代码位置') or [])
        out.append(f"""## Bug {e["编号"]}：{e["标题"]}
  {e["链接"]}
  审核通过的分析（{a.get("时间")}，置信度 {a.get("置信度") or "?"}）：{a["摘要"]}
  代码位置：
{locs or "    （无）"}
  原因：{a.get("原因") or "（无）"}
  修复思路：{a.get("思路") or "（无）"}
  影响范围：{a.get("影响") or "（无）"}
  自测要点：{a.get("自测") or "（无）"}""" + (f'\n  用户审核意见（最新，以这条为准；和上面的修复思路冲突时按意见改）：{a["意见"]}' if a.get('意见') else '')
                   + _fx_last(e))
    out.append("""
每个 Bug 依次做：
1. kb_bug_get 实时拉取，确认 Bug 还要修（平台上已关闭、或内容跟分析时不一样了，就不改，直接 kb_bug_fixed 报告 done=false 并写明原因）。
2. 按审核通过的修复思路改，改动尽量小；思路在代码里走不通时，不要自己换一套大改，kb_bug_fixed 报告 done=false 写明卡在哪。
3. 编译（构建命令看仓库根目录的 AGENTS.md / README；安卓一般是 ./gradlew :模块:compileXxxJavaWithJavac 或 assembleXxx），有相关单测就跑。
4. 只 git add 这次改的文件，提交一次，提交信息：「fix: Bug <编号> <一句话>」（仓库有提交规范就按规范，带上 Bug 编号）。
5. kb_bug_fixed 标记：id、done=true、commits=[提交号]、note（改了什么、怎么验证的、还要人工确认什么）。
   要上手机验证的：kb_devices 看、kb_device_claim 申请，只在申请到的手机上装包测试，测完 kb_device_release；没有手机就在 note 里写「待真机验证」，不要卡住。
全部处理完后结束，最后用中文回复每个 Bug 的结果。""")
    return '\n'.join(out)


def _fx_last(e):
    """上一次没修成的原因：带给这次的修复会话，免得再走同一条走不通的路。"""
    p = (e.get('修复') or {}).get('上次')
    if not p:
        return ''
    return f'\n  上一次修复没修成（{p.get("时间")}）：{p.get("说明")}\n  这次按最新的审核意见改，不要重复上次走不通的做法。'


def set_fix_note(e, note, by):
    """点「修复」时意见框里写的就是最新审核意见：替换当前意见，旧的进历史（不再给修复会话）。"""
    note = (note or '').strip()
    a = e.get('分析') or {}
    if not note or note == (a.get('意见') or '').strip():
        return False
    if a.get('意见'):
        a.setdefault('意见历史', []).append({'意见': a['意见'], '时间': a.get('审核时间') or a.get('时间') or '', '人': a.get('审核人') or ''})
    a.update(意见=note, 审核时间=now(), 审核人=by)
    return True


def bug_fix(ids, by='用户（网页）', note=None):
    """网页「🔧 修复」= 本人批准修：加入修复队列，能开始的立刻开始；仓库忙就排队，分支不对 / 有未提交改动就标「阻塞」等你处理。
    note：意见框里写的审核意见（只修一个 Bug 时），替换之前的意见，修复会话以它为准。不作为 MCP 工具提供。"""
    ids = [str(i).strip() for i in (ids if isinstance(ids, (list, tuple)) else [ids]) if str(i).strip()]
    ids, skipped = _zt_recheck(ids, '修复前核对')        # 已经转给别人的直接移除，不进队列
    added = []
    if not ids:
        raise KBError('没有加入修复队列：' + '；'.join(skipped))
    with _FX_LOCK:
        data = zt_load()
        for bid in ids:
            e = data['Bug'].get(bid)
            a = (e or {}).get('分析') or {}
            f = (e or {}).get('修复') or {}
            if not e:
                skipped.append(f'{bid}：索引里没有')
            elif a.get('状态') != '已通过':
                skipped.append(f'{bid}：分析还没审核通过')
            elif a.get('过时'):
                skipped.append(f'{bid}：分析之后平台上又改过，先重新分析')
            elif f.get('状态') in ('修复中', '排队中'):
                skipped.append(f'{bid}：已经在{f["状态"][:-1]}')
            else:
                root = a.get('仓库') or _bug_repo(e)[0]
                if not root:
                    skipped.append(f'{bid}：不知道在哪个仓库修')
                    continue
                last = {'时间': f.get('时间') or '', '说明': f.get('说明') or ''} if f.get('状态') == '未完成' and f.get('说明') else f.get('上次')
                if note is not None and len(ids) == 1 and set_fix_note(e, note, by):
                    _fx_log(e, f'审核意见改为：{a["意见"]}（{by}）')
                    _an_md(e)
                e['修复'] = {'状态': '排队中', '排队时间': now(), '排队序号': time.time() + len(added) * 1e-3, '仓库': root, '分支': a.get('分支') or _bug_repo(e)[1], '发起': by,
                             **({'上次': last} if last else {})}
                _fx_log(e, f'加入修复队列（{by}）')
                added.append(bid)
        zt_save(data)
    if not added:
        raise KBError('没有加入修复队列：' + '；'.join(skipped))
    started = fix_queue_tick()
    out = [f'已加入修复队列：Bug {"、".join(added)}'] + started
    q = {b: (e.get('修复') or {}) for b, e in zt_load()['Bug'].items() if b in added}
    wait = [f'{b}：{f.get("等待")}' for b, f in q.items() if f.get('状态') == '排队中' and f.get('等待')]
    if wait:
        out.append('还在排队：' + '；'.join(wait))
    if skipped:
        out.append('没加入：' + '；'.join(skipped))
    return '\n'.join(out)


_FX_LOCK = threading.RLock()


def fix_queue():
    """修复队列和异常：排队中（等待 / 阻塞原因）、修复中（进度）、没修成的。给网页顶部展示。"""
    _fx_heal()
    data = zt_load()
    sess = {x['编号']: x for x in an_sessions() if x.get('类型') == '修复'}
    out = {'修复中': [], '排队中': [], '阻塞': [], '未完成': []}
    for e in data['Bug'].values():
        f = e.get('修复') or {}
        item = {'编号': e['编号'], '标题': e['标题'], '链接': e.get('链接', ''), '仓库': f.get('仓库', ''), '分支': f.get('分支', '')}
        if f.get('状态') == '修复中':
            x = sess.get(f.get('会话')) or {}
            item.update(开始时间=f.get('开始时间', ''), 会话=f.get('会话', ''),
                        动作=[a.get('内容', '')[:160] for a in dev_activity(x.get('日志'), 3)], 同批=x.get('Bug') or [])
            out['修复中'].append(item)
        elif f.get('状态') == '排队中':
            item.update(排队时间=f.get('排队时间', ''), 序号=f.get('排队序号') or 0, 原因=f.get('等待', ''))
            out['阻塞' if f.get('阻塞') else '排队中'].append(item)
        elif f.get('状态') == '未完成' and e.get('状态') != '已关闭':
            item.update(时间=f.get('时间', ''), 原因=f.get('说明', ''))
            out['未完成'].append(item)
    for k in out:
        out[k].sort(key=lambda i: (i.get('序号') or 0, i.get('排队时间') or i.get('开始时间') or i.get('时间') or ''))
    out['警告'] = [{'会话': x['编号'], 'Bug': x['Bug'], '警告': x['警告']} for x in sess.values() if x.get('警告')]
    return out


def fix_queue_tick():
    """处理修复队列：按 仓库 + 分支 分组，仓库空闲、分支对、工作区干净就起修复会话（每次最多 FX_MAX_BUGS 个 Bug）。
    修复会话结束、网页每分钟都会调一次，所以阻塞解除（切好分支、提交了改动）后会自动开始。"""
    out = []
    with _FX_LOCK:
        _fx_heal()
        data = zt_load()
        q = sorted((e for e in data['Bug'].values() if (e.get('修复') or {}).get('状态') == '排队中'),
                   key=lambda e: (e['修复'].get('排队序号') or 0, e['修复'].get('排队时间', '')))
        groups, changed = {}, False
        for e in q:
            f, a = e['修复'], e.get('分析') or {}
            if e.get('状态') == '已关闭' or a.get('状态') != '已通过' or a.get('过时'):
                why = '平台上已关闭' if e.get('状态') == '已关闭' else '分析之后平台上又改过，需重新分析' if a.get('过时') else '分析不再是「已通过」'
                e['修复'] = {**f, '状态': '未完成', '时间': now(), '说明': f'排队期间{why}，没有修'}
                _fx_log(e, f'移出修复队列：{why}')
                changed = True
                continue
            groups.setdefault((f['仓库'], f.get('分支') or ''), []).append(e)
        starts = []
        busy_now = set()
        for (root, branch), items in groups.items():
            rp = Path(root)
            block = wait = ''
            if not rp.is_dir():
                block = f'仓库目录不存在：{root}'
            else:
                wait = _repo_busy(root) or ('本轮已在这个仓库起了修复会话' if str(rp.resolve()) in busy_now else '')
                if not wait:
                    cur = _git(rp, 'branch', '--show-current').stdout.strip()
                    if branch and cur != branch:
                        block = f'仓库当前在分支 {cur or "（游离）"}，这些 Bug 要在 {branch} 上修：切到 {branch} 后自动开始'
                    elif _git(rp, 'status', '--porcelain', '--untracked-files=no').stdout.strip():
                        block = '仓库有未提交的改动：提交或 stash 后自动开始（修复会话每个 Bug 单独提交，不混进别的改动）'
            for e in items:
                f = e['修复']
                new = {'等待': block or wait, '阻塞': bool(block)}
                if {k: f.get(k, '' if k == '等待' else False) for k in new} != new:
                    f.update(new)
                    changed = True
            if not block and not wait:
                busy_now.add(str(rp.resolve()))
                starts.append((root, branch or _git(rp, 'branch', '--show-current').stdout.strip(), items[:FX_MAX_BUGS]))
        if changed:
            zt_save(data)
        for root, branch, items in starts:
            keep, gone = _zt_recheck([e['编号'] for e in items], '修复前核对')   # 排队期间转给别人的不修
            out += gone
            items = [e for e in items if e['编号'] in keep]
            if items:
                out.append(_fx_start(root, branch, items))
    return out


def _fx_start(root, branch, part, by='修复队列'):
    eng = get_engine()
    rp = Path(root)
    sid = datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid_hex()[:4]
    (ZT_DIR / '分析会话').mkdir(parents=True, exist_ok=True)
    logf = ZT_DIR / '分析会话' / f'修复-{sid}.jsonl'
    head = _git(rp, 'rev-parse', 'HEAD').stdout.strip()
    o = part[0].get('归属') or {}
    proc = engine_popen(eng, _fx_prompt(root, branch, part), f'kb·修复·Bug {"、".join(e["编号"] for e in part)}', logf, root,
                        env_extra=dict(_dev_env(o.get('名称') or 'Bug 修复', branch, root), KB_SESSION='an:' + sid))
    _AN[sid] = proc
    rec = {'编号': sid, '类型': '修复', 'pid': proc.pid, '状态': '运行中', '开始时间': now(), '仓库': root, '分支': branch,
           '起点': head, 'Bug': [e['编号'] for e in part], '日志': str(logf), '引擎': eng['名称'], '发起': by}
    allx = _an_load()
    allx.append(rec)
    _an_save(allx)
    data = zt_load()
    for e in part:
        old = data['Bug'][e['编号']].get('修复') or {}
        data['Bug'][e['编号']]['修复'] = {'状态': '修复中', '开始时间': now(), '会话': sid, '分支': branch, '仓库': root,
                                          '排队时间': old.get('排队时间', ''), '发起': old.get('发起', '')}
        _fx_log(data['Bug'][e['编号']], f'开始修复（会话 {sid}）')
    zt_save(data)

    def wait(sid=sid, proc=proc):
        code = proc.wait()
        _AN.pop(sid, None)
        _an_finish(sid, code)
    threading.Thread(target=wait, daemon=True).start()
    return f'已开始：{eng["名称"]} 在 {root}（{branch}）修复 Bug {"、".join(rec["Bug"])}'


def _fx_log(e, text):
    o = e.get('归属') or {}
    if o.get('类型') in ('期', '事项') and o.get('名称'):
        try:
            log(period_dir(o['名称']), 'Bug 修复', f'Bug {e["编号"]} {e["标题"]}：{text}')
        except KBError:
            pass


def bug_fixed(bid, done=True, commits=None, note='', by='Claude'):
    """标记 Bug 修好了（或没修成）：只记在知识库，不改 Bug 平台。修复会话、对话里的 AI 或用户在网页上手动标记都用它。"""
    data = zt_load()
    e = data['Bug'].get(str(bid))
    if not e:
        raise KBError(f'Bug 索引里没有 {bid}')
    old = e.get('修复') or {}
    root = old.get('仓库') or (e.get('分析') or {}).get('仓库') or _bug_repo(e)[0]
    if isinstance(commits, str):
        commits = [x for x in re.split(r'[\s,，]+', commits) if x]
    ok, bad = [], []
    for c in commits or []:
        r = _git(Path(root), 'rev-parse', '--verify', '--quiet', f'{c}^{{commit}}') if root else None
        if r is not None and r.returncode == 0:
            full = r.stdout.strip()
            subj = _git(Path(root), 'log', '-1', '--format=%s', full).stdout.strip()
            ok.append({'提交': full[:12], '说明': subj})
        else:
            bad.append(c)
    if done and bad:
        raise KBError(f'这些提交在 {root or "仓库"} 里找不到：{"、".join(bad)}，确认后重新标记')
    e['修复'] = {**old, '状态': '已修复' if done else '未完成', '时间': now(), '提交': ok or old.get('提交', []),
                 '说明': note or '', '标记': by, '修改时间': e.get('修改时间', '')}
    e['修复'].pop('结果', None)
    a = e.get('分析') or {}
    if done:
        an_skip(e)
    elif a.get('状态') == '无需审核':
        a['状态'] = a.pop('跳过前', '待审核')
    zt_save(data)
    _fx_log(e, ('已修复' if done else '未修成') + (f'，提交 {"、".join(x["提交"][:8] for x in ok)}' if ok else '') + (f'：{note}' if note else '') + f'（{by}）')
    return f'Bug {bid} 已在知识库标记为「{"已修复" if done else "未完成"}」（不改 Bug 平台）'


def bug_unfix(bid, by='用户（网页）'):
    data = zt_load()
    e = data['Bug'].get(str(bid))
    if not e or not e.get('修复'):
        raise KBError(f'Bug {bid} 没有修复标记')
    if e['修复'].get('状态') == '修复中':
        raise KBError(f'Bug {bid} 正在修复，等会话结束再撤销')
    queued = e['修复'].get('状态') == '排队中'
    e.pop('修复')
    a = e.get('分析') or {}
    if a.get('状态') == '无需审核':
        a['状态'] = a.pop('跳过前', '待审核')      # 撤销已修复：分析回到原来的审核状态
    zt_save(data)
    _fx_log(e, f'{"移出修复队列" if queued else "撤销修复标记"}（{by}）')
    return f'已把 Bug {bid} 移出修复队列' if queued else f'已撤销 Bug {bid} 的修复标记'
