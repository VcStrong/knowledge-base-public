# From 大大王.DT
"""整站导航数据（GET /api/site）：界面模板做导航要的东西一次给齐。

各期 / 事项（状态、当前步骤、下一步、待确认、没解决的 Bug、是否在跑）、Bug / ANR 计数、手机、基础信息条数、
工具插件入口、文档列表、当前界面模板。数据都从 web.py 的 api_overview 结果里取，不重复算；
这里只补「下一步」（guide.period_guide）和基础信息条数，再整理成中文字段。只读。
"""
from kblib.core.baseinfo import base_load
from kblib.steward.brief import ui_dir, ui_template, ui_templates
from kblib.stack.guide import period_guide


def _site_step(p):
    """期的当前步骤和下一步；事项没有步骤条（返回空）。"""
    if p.get('kind') == '事项':
        return {}
    try:
        g = period_guide(p['name'])
    except Exception:
        return {}
    if not g:
        return {}
    cur = next((s['名称'] for s in g['步骤'] if s['状态'] == 'cur'), '')
    return {'流程': g['流程'], '步骤': g['步骤'], '当前步骤': cur, '下一步': g['下一步']}


def site_nav(ov, docs=(), full=False):
    """ov：api_overview() 的结果；docs：[{name, path, mtime}]；full=True 时把 ov 原样带在 overview 里（网页 core 用它更新内部状态）。"""
    ps = []
    for p in ov['periods']:
        b = p.get('batch') or {}
        ps.append({'名称': p['name'], '状态': p.get('status') or '', '事项': p.get('kind') == '事项',
                   '事项类型': p.get('taskKind', ''), '优先级': p.get('priority', ''), '说明': p.get('summary', ''),
                   '更新时间': p.get('updated', ''), '待确认': p.get('pendingQ', 0), '问题': p.get('issues', 0),
                   '没解决Bug': p.get('openBugs', 0), 'Bug': p.get('bugs', 0), '在跑': bool(p.get('running')),
                   '免打扰': bool(p.get('dnd')), '侧栏隐藏': bool(p.get('navHidden')), '插件': p.get('plugins') or [],
                   '批次': {'来源': b.get('来源', ''), '总数': b.get('总数', 0), '已处理': b.get('已处理', 0),
                          '待确认': b.get('待确认', 0), '侧栏': b.get('侧栏')} if b else None,
                   '链接': '#/p/' + p['name'], **_site_step(p)})
    tools = []
    for x in ov.get('entries') or []:
        ts = [p for p in ov['periods'] if x['id'] in (p.get('plugins') or []) and p.get('status') != '已完成']
        tools.append({'id': x['id'], '名称': x['名称'], '图标': x['图标'], '说明': x.get('说明', ''), '提示': x.get('提示', ''),
                      '待解决': len(ts), '待确认': sum(p.get('pendingQ', 0) for p in ts), '链接': '#/tool/' + x['id']})
    zt = ov.get('zentao') or {}
    anr = ov.get('anr') or {}
    ph = ov.get('phones')
    try:
        base_n = len(base_load()['条目'])
    except Exception:
        base_n = 0
    cur = ui_template()
    nav = [{'名称': '总览', '图标': '▦', '链接': '#/'},
           *([{'名称': '手机', '图标': '▯', '链接': '#/phones', '数': f"{ph['free']}/{ph['total']}"}] if ph else []),
           {'名称': 'Bug', '图标': '🐞', '链接': '#/bugs', '数': zt.get('pending', 0), '提示': '待归纳（未关闭）'},
           {'名称': 'ANR / 崩溃', '图标': '💥', '链接': '#/anr', '数': anr.get('todo', 0), '提示': '待处理'},
           *[{'名称': t['名称'], '图标': t['图标'], '链接': t['链接'], '数': t['待确认'] or t['待解决'], '提示': t['说明']} for t in tools],
           {'名称': '基础信息', '图标': '◈', '链接': '#/base', '数': base_n},
           {'名称': '设置', '图标': '⚙', '链接': '#/settings'},
           {'名称': '帮助', '图标': '?', '链接': '#/d/'}]
    out = {'期': ps,
           '待你': sum(p['待确认'] for p in ps),
           '在跑': sum(1 for p in ps if p['在跑']),
           'Bug': {'未关闭': zt.get('open', 0), '待归纳': zt.get('pending', 0), '链接': '#/bugs'},
           'ANR': {'待处理': anr.get('todo', 0), '总数': anr.get('total', 0), '链接': '#/anr'},
           '手机': {'空闲': ph['free'], '总数': ph['total'], '链接': '#/phones'} if ph else None,
           '基础信息': {'条数': base_n, '链接': '#/base'},
           '工具': tools,
           '文档': [{'名称': d['name'], '链接': '#/d/' + d['name']} for d in docs],
           '导航': nav,
           '界面模板': {'名称': cur, '目录': (ui_dir(cur) or {}).get('目录', 'classic'),
                    '列表': [{k: x[k] for k in ('名称', '说明', '目录')} for x in ui_templates()]},
           '登录': bool(ov.get('auth'))}
    if full:
        out['overview'] = ov
    return out
