# From 大大王.DT
"""命令行（kb …）。"""
import argparse
import json
import os
import re
import sys
from .common import CATS, INBOX, KBError, ROOT, STATUSES
from .periods import (
    TASK_KINDS,
    TASK_PRI,
    add_log,
    add_material,
    create_period,
    create_task,
    init,
    period_dir,
    set_status,
)
from .notes import NOTE_KINDS, add_note, update_note
from .repos import add_repo, link_repo
from .search import reindex, search
from .plugins import PLUGIN_DIR, call_plugin, plugins, run_plugin_now
from .overview import overview, period_detail
from .urlimport import _fetch, fetch_url, verify_source
from .refresh import refresh_all, refresh_sources
from .fixlink import fix_link
from .bugs.sources import bug_sources, bug_test
from .bugs.index import bug_assign, bug_get, bug_list, bug_sync, save_zentao_settings
from .bugs.analysis import bug_analyze
from .bugs.fix import bug_fixed
from .anr.store import anr_add, anr_link, anr_list, anr_mapping, anr_set_version, anr_show
from .mcp import serve
from .stats import stats_facts, stats_text
from .steward import steward_text, steward_tick


def approve(name):
    d = period_dir(name)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise KBError('批准开发必须由你本人在终端窗口里运行（防止 AI 代为批准）。')
    print(period_detail(d.name, log_lines=5))
    ans = input(f'\n确认批准「{d.name}」开始开发？请输入期名确认：').strip()
    if ans != d.name:
        raise KBError('输入不一致，已取消。')
    note = input('备注（可空）：').strip()
    return set_status(d.name, '已批准开发', note or '用户批准', by_human=True)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='kb', description='本地知识库（需求 / 设计图 / 接口文档 / 其他资料 / 代码）')
    sp = ap.add_subparsers(dest='cmd')
    sp.add_parser('init', help='初始化目录')
    sp.add_parser('list', help='总览')
    x = sp.add_parser('new', help='新建一期')
    x.add_argument('name')
    x.add_argument('summary', nargs='?', default='')
    x = sp.add_parser('show', help='查看一期')
    x.add_argument('name')
    x = sp.add_parser('add', help='归档文件到某期')
    x.add_argument('name')
    x.add_argument('files', nargs='+')
    x.add_argument('-c', '--category', choices=CATS)
    x.add_argument('-m', '--note', default='')
    x = sp.add_parser('note', help='记一条文字资料：kb note <期名> "内容" [-c 分类] [-k 类型] [-u 链接]；--rm T001 删除')
    x.add_argument('name')
    x.add_argument('content', nargs='?', default='')
    x.add_argument('-c', '--category', choices=CATS)
    x.add_argument('-k', '--kind', choices=NOTE_KINDS)
    x.add_argument('-t', '--title', default='')
    x.add_argument('-u', '--url', default='')
    x.add_argument('-f', '--source', default='', help='来自谁')
    x.add_argument('--rm', metavar='编号', help='删除这条文字资料')
    x = sp.add_parser('inbox', help='把收件箱里的文件全部归档到某期（自动分类）')
    x.add_argument('name')
    x = sp.add_parser('search', help='检索')
    x.add_argument('query', nargs='+')
    x.add_argument('-p', '--period')
    x.add_argument('-s', '--scope', choices=['all', 'docs', 'code'], default='all')
    x.add_argument('-n', '--limit', type=int, default=10)
    x = sp.add_parser('repo', help='登记代码仓库：kb repo <路径> [名称]')
    x.add_argument('path')
    x.add_argument('repo_name', nargs='?')
    x = sp.add_parser('link', help='关联仓库到某期')
    x.add_argument('name')
    x.add_argument('repo')
    x = sp.add_parser('index', help='更新索引：all / docs / code / 仓库名')
    x.add_argument('target', nargs='?', default='all')
    x = sp.add_parser('approve', help='批准某期开始开发（只能本人在终端执行）')
    x.add_argument('name')
    x = sp.add_parser('status', help='修改状态')
    x.add_argument('name')
    x.add_argument('status', choices=STATUSES)
    x.add_argument('-m', '--note', default='')
    x = sp.add_parser('log', help='追加记录')
    x.add_argument('name')
    x.add_argument('note')
    x = sp.add_parser('login', help='保存某网站的登录凭据（Mac 存钥匙串，服务器存加密文件）：kb login confluence.example.com 用户名')
    x.add_argument('host')
    x.add_argument('user')
    x = sp.add_parser('fetch', help='预览网页 / Confluence 页面')
    x.add_argument('url')
    x = sp.add_parser('verify', help='核对来源：kb verify <期名> S001 已核对|有问题|待核对 [-m 备注]')
    x.add_argument('name')
    x.add_argument('sid')
    x.add_argument('status', choices=['已核对', '有问题', '待核对'])
    x.add_argument('-m', '--note', default='')
    x = sp.add_parser('fixlink', help='更正链接：kb fixlink <期名> <旧链接> <新链接> [-m 原因]')
    x.add_argument('name')
    x.add_argument('old')
    x.add_argument('new')
    x.add_argument('-m', '--reason', default='')
    x = sp.add_parser('refresh', help='按登记的网址刷新来源：kb refresh <期名> [S001]；kb refresh --all 检查所有未完成的期')
    x.add_argument('name', nargs='?', default='')
    x.add_argument('sid', nargs='?', default='')
    x.add_argument('--all', action='store_true')
    x = sp.add_parser('plugin', help='插件：kb plugin（列出）；kb plugin run <插件> <期名> [开发开始|开发完成]（手动运行一次）；'
                                     'kb plugin call <工具插件> [参数…]（按需调用）')
    x.add_argument('action', nargs='?', default='list', choices=['list', 'run', 'call'])
    x.add_argument('plugin', nargs='?', default='')
    x.add_argument('name', nargs='?', default='')
    x.add_argument('event', nargs='?', default='')
    x.add_argument('rest', nargs='*', default=[])
    x = sp.add_parser('stats', help='工作统计（统计插件算）：kb stats [今天|本周|本月|近7天|近30天|全部]；--facts 输出给插件的原始事实 JSON')
    x.add_argument('range', nargs='?', default='')
    x.add_argument('--facts', action='store_true')
    x = sp.add_parser('steward', help='管家：kb steward 看待你处理的事和管家做了什么；kb steward tick 立即巡检一轮（明确的事会自动做）')
    x.add_argument('action', nargs='?', default='view', choices=['view', 'tick'])
    x = sp.add_parser('task', help='新建事项（不是产品需求的工作）：kb task <名称> [说明] [-k 类型] [-f 来源] [-p 高|中|低] [--bug 编号…]')
    x.add_argument('name')
    x.add_argument('summary', nargs='?', default='')
    x.add_argument('-k', '--kind', choices=TASK_KINDS)
    x.add_argument('-f', '--source', default='', help='来自哪里')
    x.add_argument('-p', '--priority', choices=TASK_PRI)
    x.add_argument('--bug', nargs='*', default=[])
    x = sp.add_parser('bug', aliases=['zentao'], help='Bug 平台：kb bug sources | test [-s 平台] | sync [--full] [-s 平台] | bugs [期名] [--pending] | get <编号> | assign <编号> <期名|待归纳|事项:名称> | platform <全部|安卓|iOS|服务端|前端> [-s 平台] | scope <我的|全部|指定人> [账号,账号] [-s 平台] | analyze <编号…>（后台只读分析）| fixed <编号> [提交…]（标记已修复）；kb zentao … 是旧名字')
    x.add_argument('action', choices=['sources', 'test', 'sync', 'bugs', 'get', 'bug', 'assign', 'platform', 'scope', 'analyze', 'fixed'])
    x.add_argument('args', nargs='*')
    x.add_argument('-s', '--source', default='', help='平台名称（Bug 页「平台」里的名字；空 = 第一个 / 全部）')
    x.add_argument('--full', action='store_true', help='忽略游标，重新扫一遍')
    x.add_argument('--pending', action='store_true', help='只看待归纳')
    x = sp.add_parser('anr', help='ANR / 崩溃：kb anr add <文件…> [-v 版本] [-t 事项] [-f 来源] | list [关键词] | show <编号> | mapping <版本> <mapping.txt> | task <编号> [事项名|＋新建] | version <编号> <版本> | ignore <编号> | unignore <编号>')
    x.add_argument('action', choices=['add', 'list', 'show', 'mapping', 'task', 'version', 'ignore', 'unignore'])
    x.add_argument('args', nargs='*')
    x.add_argument('-v', '--version', default='')
    x.add_argument('-t', '--task', default='')
    x.add_argument('-f', '--source', default='')
    x.add_argument('-n', '--count', type=int, default=1)
    sp.add_parser('serve', help='以 MCP（stdio）方式运行')
    x = sp.add_parser('web', help='启动网页（默认 http://127.0.0.1:11555 只给本机；部署在远端：kb web --host 0.0.0.0，要先 kb passwd）')
    x.add_argument('--port', type=int, default=int(os.environ.get('KB_PORT') or 11555))
    x.add_argument('--host', default='', help='监听地址，默认 127.0.0.1（或环境变量 KB_HOST）')
    sp.add_parser('passwd', help='设置 / 取消网页访问密码（部署在远端、或网页经反向代理开放时必须设）')
    x = sp.add_parser('token', help='远处的 Claude Code 连知识库用的访问令牌：kb token add <名称> | list | del <名称>')
    x.add_argument('op', choices=['add', 'list', 'del'])
    x.add_argument('name', nargs='?', default='')
    a = ap.parse_args(argv)
    if a.cmd == 'serve':
        return serve()
    if a.cmd == 'web':
        import web
        return web.main(a.port, a.host)
    if a.cmd == 'passwd':
        import getpass
        from .deploy import set_password
        p1 = getpass.getpass('新的网页访问密码（至少 8 位；直接回车 = 取消密码）：')
        if p1 and getpass.getpass('再输一次：') != p1:
            print('两次不一样，没有改')
            return 1
        print(set_password(p1))
        return 0
    if a.cmd == 'token':
        from .deploy import token_add, token_del, token_list
        if a.op == 'add':
            t = token_add(a.name)
            print(f'令牌「{a.name}」（只显示这一次，丢了就删掉重建）：\n{t}\n\n在要连知识库的电脑上：\n'
                  f'  claude mcp add --transport http kb <网页地址>/mcp --header "Authorization: Bearer {t}"')
        elif a.op == 'list':
            print('\n'.join(f'- {x["名称"]}（{x["时间"]} 创建，最近使用 {x["最近使用"] or "无"}）' for x in token_list()) or '还没有令牌')
        else:
            print(token_del(a.name))
        return 0
    try:
        if a.cmd == 'init':
            init()
            r = f'已初始化：{ROOT}'
        elif a.cmd in (None, 'list'):
            r = overview()
        elif a.cmd == 'new':
            r = create_period(a.name, a.summary)
        elif a.cmd == 'show':
            r = period_detail(a.name)
        elif a.cmd == 'add':
            r = '\n\n'.join(add_material(a.name, f, a.category, a.note) for f in a.files)
        elif a.cmd == 'note':
            r = (update_note(a.name, a.rm, delete=True) if a.rm else
                 add_note(a.name, a.content, a.category, a.kind, a.title, a.url, a.source))
        elif a.cmd == 'inbox':
            fs = [p for p in INBOX.iterdir() if not p.name.startswith('.')]
            r = '\n\n'.join(add_material(a.name, f) for f in fs) if fs else '收件箱是空的'
        elif a.cmd == 'search':
            r = search(' '.join(a.query), a.period, None, a.scope, None, a.limit)
        elif a.cmd == 'repo':
            r = add_repo(a.path, a.repo_name)
        elif a.cmd == 'link':
            r = link_repo(a.name, a.repo)
        elif a.cmd == 'index':
            r = reindex(a.target)
        elif a.cmd == 'approve':
            r = approve(a.name)
        elif a.cmd == 'login':
            host = re.sub(r'^https?://', '', a.host).split('/')[0]
            what = 'Figma 个人访问令牌' if 'figma' in host else f'{a.user}@{host} 的密码'
            from .infra import vault
            print(f'请输入{what}（' + ('由 macOS 钥匙串接收，知识库和 AI 看不到明文' if vault.BACKEND == 'keychain' else '存进加密文件，不回显') + '）')
            _fetch().save_cred(host, a.user)
            r = f'已保存到{vault.LABEL}（服务名 kb:{host}）'
        elif a.cmd == 'fetch':
            r = fetch_url(a.url)
        elif a.cmd == 'verify':
            r = verify_source(a.name, a.sid, a.status, a.note)
        elif a.cmd == 'fixlink':
            r = fix_link(a.name, a.old, a.new, a.reason, by='终端')
        elif a.cmd == 'refresh':
            if a.all or not a.name:
                ch = refresh_all(by='终端')
                r = '\n'.join(f'{n}：\n' + '\n'.join(h) for n, h in ch) or '所有未完成的期，来源都没有变化'
            else:
                r = refresh_sources(a.name, a.sid, by='终端')
        elif a.cmd == 'status':
            if a.status == '已批准开发':
                raise KBError('批准开发请用：kb approve <期名>')
            r = set_status(a.name, a.status, a.note, by_human=True)
        elif a.cmd == 'log':
            r = add_log(a.name, a.note)
        elif a.cmd == 'task':
            r = create_task(a.name, a.summary, a.kind or '', a.source, a.priority or '', a.bug, by='终端')
        elif a.cmd == 'anr':
            g = lambda i: a.args[i] if len(a.args) > i else ''
            if a.action == 'add':
                r = anr_add(a.args, a.version, a.source, a.task, a.count, by='终端')
            elif a.action == 'list':
                r = anr_list(g(0), a.task, include_ignored=True)
            elif a.action == 'show':
                r = anr_show(g(0))
            elif a.action == 'mapping':
                r = anr_mapping(g(0), g(1), by='终端')
            elif a.action == 'version':
                r = anr_set_version(g(0), g(1), by='终端')
            elif a.action == 'task':
                r = anr_link(g(0), g(1) or '＋新建', by='终端')
            else:
                r = anr_link(g(0), status='忽略' if a.action == 'ignore' else '', by='终端')
        elif a.cmd in ('bug', 'zentao'):
            g = lambda i: a.args[i] if len(a.args) > i else ''
            if a.action == 'sources':
                r = '\n'.join(f'- {c["ID"]}（{c["适配器"]}，{c["类型"]}）{"" if c["启用"] else "【已停用】"} 账号 {c.get("账号条目") or "自动找"}　范围 {c["范围"]}　平台 {c["平台"]}'
                               for c in bug_sources()) or '还没接入 Bug 平台'
            elif a.action == 'test':
                r = bug_test(a.source)
            elif a.action == 'sync':
                r = bug_sync(by='终端', full=a.full, only=a.source)
            elif a.action == 'bugs':
                r = bug_list(g(0), '待归纳' if a.pending else '')
            elif a.action in ('bug', 'get'):
                r = bug_get(g(0))
            elif a.action == 'assign':
                r = bug_assign(g(0), g(1), by='终端')
            elif a.action == 'fixed':
                r = bug_fixed(g(0), True, a.args[1:], by='终端')
            elif a.action == 'analyze':
                r = bug_analyze(a.args, by='终端')
            elif a.action == 'scope':
                save_zentao_settings(scope=g(0), people=g(1) or None, source=a.source)
                r = f'已改范围：{g(0)}'
            else:
                save_zentao_settings(platform=g(0), source=a.source)
                r = f'已改平台：{g(0)}'
        elif a.cmd == 'steward':
            r = steward_tick('终端') if a.action == 'tick' else steward_text()
        elif a.cmd == 'stats':
            r = json.dumps(stats_facts(), ensure_ascii=False) if a.facts else stats_text(a.range)
        elif a.cmd == 'plugin':
            if a.action == 'run':
                if not a.plugin or not a.name:
                    raise KBError('用法：kb plugin run <插件> <期名> [开发开始|开发完成]')
                r = run_plugin_now(a.plugin, a.name, a.event or '开发开始')
            elif a.action == 'call':
                r = call_plugin(a.plugin, [x for x in [a.name, a.event] + a.rest if x], by='终端')
            else:
                r = '\n'.join(f'{p["id"]}：{p.get("名称", "")} · ' + (p.get('错误') or (f'已挂载（{"、".join(p["时机"]) or "按需调用"}）' if p['启用'] else '未挂载'))
                              + f' · {p["目录"]}' for p in plugins()) or f'没有插件（放到 {PLUGIN_DIR}/<名称>/plugin.json）'
        print(r)
    except KBError as e:
        print(f'✗ {e}', file=sys.stderr)
        return 1
