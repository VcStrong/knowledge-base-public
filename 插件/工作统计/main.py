"""工作统计插件：读知识库给的事实（标准输入 JSON），算出总览上的统计卡片和各期进度。

  main.py stats <范围>      知识库调用：标准输入是事实，输出一行结果 JSON
  main.py [范围]            终端 / AI（kb_plugin_call）调用：自己运行 kb stats --facts 取事实，输出文字
范围：今天 / 本周 / 本月 / 近7天 / 近30天 / 全部。想统计别的，改这个文件或照着写一个新插件（plugin.json 写「能力: ["统计"]」）。
"""
import datetime as dt
import json
import os
import subprocess
import sys

RANGES = ('今天', '本周', '本月', '近7天', '近30天', '全部')


def start_of(rng, today=None):
    t = today or dt.date.today()
    return {'今天': t, '本周': t - dt.timedelta(days=t.weekday()), '本月': t.replace(day=1),
            '近7天': t - dt.timedelta(days=6), '近30天': t - dt.timedelta(days=29)}.get(rng)


def facts_from_stdin_or_kb():
    if not sys.stdin.isatty():
        raw = sys.stdin.read()
        if raw.strip():
            return json.loads(raw)
    cli = os.environ.get('KB_CLI')
    if not cli:
        raise SystemExit('要由知识库调用（kb stats / kb_plugin_call），或设好 KB_CLI')
    r = subprocess.run([os.environ.get('KB_PYTHON') or sys.executable, cli, 'stats', '--facts'], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise SystemExit(r.stderr.strip() or '取事实失败')
    return json.loads(r.stdout)


def compute(f, rng):
    s = start_of(rng)
    since = s.isoformat() if s else ''
    inr = lambda t: bool(t) and t[:10] >= since           # 时间都是「YYYY-MM-DD HH:MM」，比字符串就行
    pct = lambda p: round(100 * p['完成'] / p['总数']) if p and p.get('总数') else None

    def done_at(x):                                          # 最后一次标「已完成」的时间（之后又重开的不算）
        h = x.get('状态历史') or []
        return h[-1]['时间'] if h and h[-1]['状态'] == '已完成' else ''

    periods = [x for x in f['期'] if x['类型'] == '期']
    tasks = [x for x in f['期'] if x['类型'] == '事项']
    doing = [x for x in periods if x['状态'] != '已完成']
    avg = [pct(x['进度']) for x in doing if pct(x['进度']) is not None]

    bugs = f.get('Bug') or []
    kb_fixed = {b['编号'] for b in bugs if b['修复状态'] == '已修复' and inr(b['修复时间'])}
    pf_fixed = {b['编号'] for b in bugs if b['平台状态'] in ('已解决', '已关闭') and inr(b['修改时间'])}
    open_bugs = [b for b in bugs if b['平台状态'] == '激活' and b['修复状态'] != '已修复']
    new_bugs = [b for b in bugs if inr(b['创建时间'])]

    anr = [a for a in f.get('ANR') or [] if a['状态'] != '忽略']
    anr_ok = [a for a in anr if a['结论'] == '已解决' and inr(a['结论时间']) and not a['修复后又出现']]
    anr_back = [a for a in anr if a['修复后又出现']]
    anr_todo = [a for a in anr if not a['事项'] or a['结论'] not in ('已解决', '没解决')]

    sess = [(x['名称'], t) for x in f['期'] for t in x.get('AI会话') or [] if inr(t)]
    when = {'全部': '累计'}.get(rng, rng)
    cards = [
        {'标题': f'{when}完成需求', '值': sum(1 for x in periods if inr(done_at(x))), '单位': '期',
         '说明': f'进行中 {len(doing)} 期' + (f'，平均进度 {round(sum(avg) / len(avg))}%' if avg else ''), '链接': '#/'},
        {'标题': f'{when}解决 Bug', '值': len(kb_fixed | pf_fixed), '单位': '个',
         '说明': f'知识库标修复 {len(kb_fixed)} · 平台已解决 {len(pf_fixed)}{"" if rng == "全部" else f" · 新增 {len(new_bugs)}"} · 还没解决 {len(open_bugs)}', '链接': '#/bugs'},
        {'标题': f'{when}解决 ANR / 崩溃', '值': len(anr_ok), '单位': '个',
         '说明': f'共 {len(anr)} 个问题 · 待处理 {len(anr_todo)}' + (f' · 修复后又出现 {len(anr_back)}' if anr_back else ''), '链接': '#/anr'},
        {'标题': f'{when}完成事项', '值': sum(1 for x in tasks if inr(done_at(x))), '单位': '个',
         '说明': f'进行中 {sum(1 for x in tasks if x["状态"] != "已完成")} 个', '链接': '#/'},
        {'标题': f'{when} AI 会话', '值': len(sess), '单位': '次',
         '说明': f'涉及 {len({n for n, _ in sess})} 个期 / 事项', '链接': ''},
    ]

    fixed_by = {}
    for b in bugs:
        if b['编号'] in kb_fixed | pf_fixed and b['期']:
            fixed_by[b['期']] = fixed_by.get(b['期'], 0) + 1
    open_by = {}
    for b in open_bugs:
        open_by[b['期']] = open_by.get(b['期'], 0) + 1
    order = {'开发中': 0, '已批准开发': 1, '已暂停': 2, '收集中': 3}
    prog = []
    for x in sorted((x for x in periods if x['状态'] != '已完成' or inr(done_at(x))),
                    key=lambda x: (order.get(x['状态'], 4), x['名称'])):
        p = x['进度'] or ({'完成': 1, '总数': 1, '说明': '已完成'} if x['状态'] == '已完成' else None)
        extra = [s for s in (f'{when}解决 Bug {fixed_by[x["名称"]]}' if fixed_by.get(x['名称']) else '',
                             f'Bug 没解决 {open_by[x["名称"]]}' if open_by.get(x['名称']) else '',
                             f'{x["待确认"]} 个待确认' if x.get('待确认') else '') if s]
        prog.append({'名称': x['名称'], '状态': x['状态'], '完成': (p or {}).get('完成', 0), '总数': (p or {}).get('总数', 0),
                     '说明': '；'.join([(p or {}).get('说明') or '还看不出进度'] + extra), '链接': '#/p/' + x['名称']})
    return {'范围': rng, '起': since, '卡片': cards, '进度': prog}


def main():
    a = sys.argv[1:]
    kb_call = bool(a) and a[0] == 'stats'
    if kb_call:
        a = a[1:]
    rng = a[0] if a and a[0] in RANGES else (json.loads(os.environ.get('KB_PLUGIN_CONFIG') or '{}').get('默认范围') or '本周')
    r = compute(facts_from_stdin_or_kb(), rng)
    if kb_call:
        print(json.dumps(r, ensure_ascii=False))
        return
    print(f'工作统计（{r["范围"]}' + (f'，{r["起"]} 起' if r['起'] else '') + '）')
    for c in r['卡片']:
        print(f'- {c["标题"]}：{c["值"]} {c["单位"]}（{c["说明"]}）')
    for p in r['进度']:
        print(f'- {p["名称"]}（{p["状态"]}）{p["完成"]}/{p["总数"]}：{p["说明"]}')


if __name__ == '__main__':
    main()
