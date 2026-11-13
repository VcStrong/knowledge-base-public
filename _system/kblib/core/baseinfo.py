# From 大大王.DT
"""基础知识库：账号、环境等通用信息；机密只在钥匙串。"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from kblib.infra import vault
from kblib.core.common import BASE, KBError, now
from kblib.core.search import index_docs


# 所有期共用的基础信息：网站账号、测试账号、Wi-Fi / 代理 / VPN、环境配置等。
# 机密字段（密码、令牌）只存 macOS 钥匙串（服务名 kb-base），json / md / 索引 / 网页默认都只显示掩码。
BASE_FILE = BASE / '基础信息.json'
BASE_MD = BASE / '基础信息.md'
BASE_LOG = BASE / '记录.md'
BASE_CATS = ['账号密码', '测试账号', '网络代理', 'VPN', '环境配置', '其他']
KC_SERVICE = os.environ.get('KB_KC_SERVICE', 'kb-base')
MASK = '●●●●●●'


def _kc_set(acct, value):           # 名字沿用「钥匙串」：Mac 上存钥匙串，远端服务器存加密文件（infra/vault.py）
    try:
        vault.put(KC_SERVICE, acct, value)
    except vault.VaultError as e:
        raise KBError(str(e))


def _kc_get(acct):
    try:
        return vault.get(KC_SERVICE, acct)
    except vault.VaultError as e:
        raise KBError(str(e))


def _kc_del(acct):
    try:
        vault.delete(KC_SERVICE, acct)
    except vault.VaultError as e:
        raise KBError(str(e))


def _base_log(action, content):
    BASE.mkdir(exist_ok=True)
    if not BASE_LOG.exists():
        BASE_LOG.write_text('# 基础知识库 · 记录\n\n', 'utf-8')
    with BASE_LOG.open('a', encoding='utf-8') as f:
        f.write(f'- {now()} ｜ {action} ｜ {content}\n')


def base_load():
    return json.loads(BASE_FILE.read_text('utf-8')) if BASE_FILE.exists() else {'条目': [], '序号': 0}


def _field_md(fd):
    return f'{fd["名"]}：{MASK}（{vault.LABEL}）' if fd.get('机密') else f'{fd["名"]}：{fd.get("值", "")}'


def base_entry_md(e, head='##'):
    out = [f'{head} {e["编号"]} ［{e["分类"]}］{e["名称"]}']
    if e.get('适用'):
        out.append(f'- 适用：{e["适用"]}')
    out += [f'- {_field_md(fd)}' for fd in e.get('字段') or []]
    if e.get('附件'):
        out.append('- 附件：' + '、'.join(e['附件']))
    if e.get('备注'):
        out += ['', e['备注'].strip()]
    return '\n'.join(out)


def _base_save_all(data):
    BASE.mkdir(exist_ok=True)
    BASE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), 'utf-8')
    es = data['条目']
    md = ['# 基础知识库', '', '> 自动生成，请勿手改（用网页「🗂 基础信息」或让 Claude 修改）。所有期共用；机密字段只存钥匙串，这里只显示掩码。', '']
    for c in BASE_CATS:
        part = [e for e in es if e['分类'] == c]
        if part:
            md += [f'# {c}', ''] + [base_entry_md(e) + '\n' for e in part]
    BASE_MD.write_text('\n'.join(md) + '\n', 'utf-8')
    index_docs()


def base_save(id='', category='', name='', fields=None, scope='', note='', file='', delete=False, by='Claude'):
    """新增 / 修改 / 删除一条基础信息。fields：[{名, 值, 机密}]；修改时机密字段值留空表示不改。"""
    data = base_load()
    es = data['条目']
    e = next((x for x in es if x['编号'] == id), None) if id else None
    if id and not e:
        raise KBError(f'没有这条基础信息：{id}')
    if delete:
        for fd in e.get('字段') or []:
            if fd.get('机密'):
                _kc_del(f'{e["编号"]}/{fd["名"]}')
        es.remove(e)
        _base_save_all(data)
        _base_log('删除', f'{e["编号"]} {e["名称"]}（{by}）')
        return f'已删除基础信息 {e["编号"]} {e["名称"]}'
    if not e:
        if not (name or '').strip():
            raise KBError('名称不能为空')
        data['序号'] = data.get('序号', 0) + 1
        e = {'编号': f'B{data["序号"]:03d}', '分类': '其他', '名称': '', '适用': '', '字段': [], '备注': '', '附件': [],
             '创建时间': now()}
        es.append(e)
        action = '新增'
    else:
        action = '修改'
    if category:
        if category not in BASE_CATS:
            raise KBError(f'分类只能是：{" / ".join(BASE_CATS)}')
        e['分类'] = category
    for k, v in (('名称', name), ('适用', scope), ('备注', note)):
        if v is not None and (v or k != '名称'):
            e[k] = (v or '').strip()
    if fields is not None:
        old = {fd['名']: fd for fd in e.get('字段') or []}
        new = []
        for fd in fields:
            nm = str(fd.get('名') or fd.get('name') or '').strip()
            if not nm:
                continue
            val = str(fd.get('值') if fd.get('值') is not None else fd.get('value') or '')
            secret = bool(fd.get('机密') if '机密' in fd else fd.get('secret'))
            acct = f'{e["编号"]}/{nm}'
            if secret:
                if val:
                    _kc_set(acct, val)
                elif not (old.get(nm, {}).get('机密') and _kc_get(acct) is not None):
                    raise KBError(f'机密字段「{nm}」还没有值')
                new.append({'名': nm, '值': '', '机密': True})
            else:
                if old.get(nm, {}).get('机密'):
                    _kc_del(acct)
                new.append({'名': nm, '值': val, '机密': False})
        for nm, fd in old.items():  # 删掉的机密字段同时清钥匙串
            if fd.get('机密') and nm not in {x['名'] for x in new}:
                _kc_del(f'{e["编号"]}/{nm}')
        e['字段'] = new
    if file:
        src = Path(file).expanduser()
        if not src.is_file():
            raise KBError(f'附件不存在：{src}')
        (BASE / '附件').mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, BASE / '附件' / src.name)
        if f'附件/{src.name}' not in e['附件']:
            e['附件'].append(f'附件/{src.name}')
    e['更新时间'] = now()
    _base_save_all(data)
    _base_log(action, f'{e["编号"]} ［{e["分类"]}］{e["名称"]}（{by}）')
    return f'已{action}基础信息：\n' + base_entry_md(e)


def base_list(query='', category=''):
    es = base_load()['条目']
    if category:
        es = [e for e in es if e['分类'] == category]
    if query:
        norm = lambda x: re.sub(r'[\s\-_./]', '', x.lower())
        terms = [norm(t) for t in query.split()]
        es = [e for e in es if all(t in norm(base_entry_md(e)) for t in terms)]
    if not es:
        return '基础知识库里没有匹配的条目。' + ('' if query or category else '（用 kb_base_save 添加）')
    return ('\n\n'.join(base_entry_md(e) for e in es)
            + f'\n\n（机密字段显示为 {MASK}；执行时确实要用，再用 kb_base_secret 读取）')


def base_secret(id, field, by='Claude', purpose=''):
    e = next((x for x in base_load()['条目'] if x['编号'] == id), None)
    if not e:
        raise KBError(f'没有这条基础信息：{id}')
    fd = next((x for x in e['字段'] if x['名'] == field), None)
    if not fd:
        raise KBError(f'{id} 没有字段「{field}」，有：{"、".join(x["名"] for x in e["字段"])}')
    if not fd.get('机密'):
        return fd.get('值', '')
    v = _kc_get(f'{id}/{field}')
    if v is None:
        raise KBError(f'钥匙串里找不到 {id} 的「{field}」')
    _base_log('读取机密', f'{id} {e["名称"]} · {field}（{by}）' + (f'：{purpose}' if purpose else ''))
    return v


def base_context():
    """给开发包 / SDD 资料用的基础信息摘要（机密只显示掩码）。"""
    es = base_load()['条目']
    if not es:
        return ''
    return '\n\n'.join(base_entry_md(e, '###') for e in es)
