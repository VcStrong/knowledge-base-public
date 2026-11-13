# From 大大王.DT
"""Bug / 崩溃平台接入：设置里的平台列表、用基础信息里哪条账号、适配器实例、连接测试、增删改平台。"""
import json
import subprocess
import sys
from kblib.core.common import KBError, load_settings, save_settings
from kblib.core.baseinfo import base_load, base_secret
from kblib.plugins.registry import _plugin_env, plugins
from kblib import lazy
_bug_index = lazy('kblib.bugs.index')      # 上层模块：用到时才 import（不形成循环）


def _bsrc():
    from kblib.bugs import adapters as bugsrc
    return bugsrc


def bug_sources(kind=None):
    """设置里的 Bug / 崩溃平台列表。老版本只有「禅道」一项设置：第一次读时转成一个来源（ID 仍叫「禅道」，老编号不变）。"""
    s = load_settings()
    if 'Bug平台' not in s:
        z = s.get('禅道') or {}
        srcs = []
        if z or _bug_index.ZT_FILE.exists() or any('禅道' in x['名称'] for x in base_load()['条目']):
            srcs.append({'ID': '禅道', '适配器': '禅道', '启用': z.get('启用', True), '账号条目': z.get('账号条目', ''),
                         '范围': z.get('范围') or '我的', '人员': z.get('人员') or [], '平台': z.get('平台') or '安卓',
                         **({'产品': z['产品']} if z.get('产品') else {})})
        s['Bug平台'] = srcs
        if z.get('产品仓库'):
            s.setdefault('Bug仓库', {}).update({f'禅道/{k}': v for k, v in z['产品仓库'].items()})
        s.pop('禅道', None)
        save_settings(s)
    out = []
    for c in s['Bug平台']:
        c = dict(c)
        c.setdefault('启用', True)
        c.setdefault('范围', '我的')
        c.setdefault('平台', '安卓')
        c.setdefault('人员', [])
        c['类型'] = _src_kind(c)
        if kind is None or c['类型'] == kind:
            out.append(c)
    return out


def _src_kind(c):
    bs = _bsrc()
    if c.get('适配器') in bs.ADAPTERS:
        return bs.ADAPTERS[c['适配器']].kind
    p = next((x for x in plugins() if x.get('Bug平台') and c.get('适配器') in (x['id'], x.get('名称'))), None)
    return (p or {}).get('平台类型') or '缺陷'


def bug_source_conf(sid=''):
    ss = bug_sources()
    c = next((x for x in ss if x['ID'] == sid), None) if sid else next((x for x in ss if x['类型'] == '缺陷'), None)
    if not c:
        raise KBError(f'没有这个 Bug 平台：{sid}' if sid else '还没接入 Bug 平台：网页「🐞 Bug」页点「＋ 接入平台」')
    return c


def zentao_settings():          # 旧名字：第一个缺陷平台的设置（产品仓库等已迁到 Bug仓库）
    try:
        return bug_source_conf()
    except KBError:
        return {}


def _src_entry(c):
    """来源用基础信息里哪条账号：设置里选的 > 名称 / 内容带适配器关键字的那条。"""
    bs = _bsrc()
    es = base_load()['条目']
    if c.get('账号条目'):
        e = next((x for x in es if x['编号'] == c['账号条目']), None)
        if not e:
            raise KBError(f'Bug 平台「{c["ID"]}」用的基础信息 {c["账号条目"]} 不存在了：在「🐞 Bug → 平台」里重新选')
        return e
    cls = bs.ADAPTERS.get(c.get('适配器'))
    words = [w.lower() for w in (cls.guess if cls else ()) + (c['ID'],) if w]
    e = next((x for x in es if any(w in x['名称'].lower() for w in words)), None) or \
        next((x for x in es if any(w in json.dumps(x, ensure_ascii=False).lower() for w in words)), None)
    if not e:
        raise KBError(f'基础知识库里没有 {c["ID"]} 的账号：先在「◈ 基础信息」添加（{cls.fields if cls else "插件说明里要求的字段"}），'
                      f'再在「🐞 Bug → 平台」里选它')
    return e


_SRC = {}


def bug_source(c, by='Bug同步'):
    """来源设置 → 适配器实例（同一配置复用，登录令牌留在内存里）。"""
    bs = _bsrc()
    if isinstance(c, str):
        c = bug_source_conf(c)
    e = _src_entry(c)
    key = json.dumps([c, e['编号']], ensure_ascii=False, sort_keys=True)
    if key in _SRC:
        return _SRC[key]
    cred = bs.Cred(e, lambda f: base_secret(e['编号'], f, by=by, purpose=f'登录 {c["ID"]}'))
    if c.get('适配器') in bs.ADAPTERS:
        src = bs.ADAPTERS[c['适配器']](c, cred)
    else:
        p = next((x for x in plugins() if x.get('Bug平台') and c.get('适配器') in (x['id'], x.get('名称'))), None)
        if not p:
            raise KBError(f'Bug 平台「{c["ID"]}」的适配器「{c.get("适配器")}」不存在（内置：{"、".join(bs.ADAPTERS)}；或插件被删了）')
        src = bs.PluginSource(c, cred, p, _plugin_runner(p, e, by))
    _SRC.clear() if len(_SRC) > 20 else None
    _SRC[key] = src
    return src


def _plugin_runner(p, e, by):
    def run(args, stdin):
        b = {f['名']: base_secret(e['编号'], f['名'], by=by, purpose=f'插件「{p.get("名称")}」') if f.get('机密') else f.get('值', '')
             for f in e['字段']}
        env = _plugin_env(p, by, KB_EVENT='Bug平台')
        env['KB_PLUGIN_BASE'] = json.dumps({'账号': b}, ensure_ascii=False)
        cmd = [sys.executable if x == '{python}' else x for x in p['命令']] + [str(a) for a in args]
        try:
            r = subprocess.run(cmd, cwd=p['目录'], env=env, input=stdin, capture_output=True, text=True, timeout=int(p.get('超时') or 300))
        except subprocess.TimeoutExpired:
            raise KBError(f'插件「{p["名称"]}」超时')
        if r.returncode:
            raise KBError(f'插件「{p["名称"]}」失败（退出码 {r.returncode}）：{(r.stdout + r.stderr)[-2000:]}')
        return r.stdout
    return run


def _src_call(fn, *a, **kw):
    bs = _bsrc()
    try:
        return fn(*a, **kw)
    except bs.SourceError as ex:
        raise KBError(str(ex))


def bug_test(sid=''):
    """登录并列出接口里能拿到的字段，确认接入是否可用。不输出机密。"""
    c = bug_source_conf(sid)
    return f'【{c["ID"]}（{c["适配器"]}）】\n' + _src_call(bug_source(c, by='连接测试').test)


def zentao_test():
    return bug_test()
