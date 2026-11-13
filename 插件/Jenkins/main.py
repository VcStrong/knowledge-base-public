"""知识库插件：Jenkins 构建（只读）。账号由知识库通过 KB_PLUGIN_BASE 传入，这里不存密码。

子命令（知识库用，输出 JSON）：
  test                         连接测试 → {"文本"}
  jobs <关键词…>               按分支 / 关键词模糊找任务 → [{"名称", "地址", "分"}]
  builds <任务名或地址> [数量]  最近的构建 → {"任务", "地址", "构建": [构建]}
  build <构建地址>             一次构建 → 构建
构建：{"编号", "地址", "结果", "进行中", "时间", "耗时", "版本", "分支", "提交", "说明", "产物": [{"名称", "路径", "地址", "类型"}]}
不带子命令（对话里按需调用）：给分支 / 关键词 / 地址，输出给人和 AI 看的文字。
"""
import base64, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

TREE_BUILD = ('number,url,result,building,timestamp,duration,displayName,description,'
              'artifacts[fileName,relativePath],actions[parameters[name,value],lastBuiltRevision[SHA1,branch[name]]]')
CACHE = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'kb-jenkins-jobs.json')


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(2)


def conf():
    c = json.loads(os.environ.get('KB_PLUGIN_CONFIG') or '{}')
    b = (json.loads(os.environ.get('KB_PLUGIN_BASE') or '{}')).get('账号') or {}
    pick = lambda *ks: next((str(b[k]) for k in ks if b.get(k)), '')
    base = (c.get('地址') or pick('地址', '网址', 'URL', 'url')).strip().rstrip('/')
    if not base:
        die('Jenkins 插件没配好：在「◈ 基础信息」加一条 Jenkins（字段「地址」，如 http://jenkins.example.com:8080/jenkins），'
            '再到「⚙ 设置 → 插件 → Jenkins → 配置」选它')
    user = pick('用户名', '账号', 'username', '用户')
    pw = pick('令牌', 'API令牌', 'token', '密码', 'password')
    try:
        n = max(1, min(50, int(c.get('数量') or 10)))
    except ValueError:
        n = 10
    return base, user, pw, n


BASE, USER, PW, NUM = conf()


def get(url, tree=None, raw=False):
    if not url.startswith('http'):
        url = BASE + url
    if not raw:
        url = url.rstrip('/') + '/api/json' + ('?tree=' + urllib.parse.quote(tree, safe=',') if tree else '')
    req = urllib.request.Request(url, headers={'User-Agent': 'kb-jenkins'})
    if USER and PW:
        req.add_header('Authorization', 'Basic ' + base64.b64encode(f'{USER}:{PW}'.encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        die(f'Jenkins 请求失败 {e.code}：{url}' + ('（要登录：在基础信息条目里填 用户名 + API 令牌）' if e.code in (401, 403) else ''))
    except urllib.error.URLError as e:
        die(f'连不上 Jenkins：{e.reason}（是否需要 VPN / 内网？）')
    return data if raw else json.loads(data)


def all_jobs():
    """任务列表（含文件夹里的一层）缓存 10 分钟：几千个任务，模糊匹配时不必每次都拉。"""
    try:
        c = json.load(open(CACHE))
        if c.get('base') == BASE and time.time() - c['t'] < 600:
            return c['jobs']
    except (OSError, ValueError, KeyError):
        pass
    js = get('', 'jobs[name,url,jobs[name,url]]')['jobs']
    out = []
    for j in js:
        out.append({'名称': j['name'], '地址': j['url']})
        for k in j.get('jobs') or []:
            out.append({'名称': f'{j["name"]}/{k["name"]}', '地址': k['url']})
    try:
        json.dump({'base': BASE, 't': time.time(), 'jobs': out}, open(CACHE, 'w'))
    except OSError:
        pass
    return out


def norm(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')


def score(name, kw):
    """分支 feature-shop-24-gift-box-stable ↔ 任务 app_android_new_feature-shop-24-gift-box-stable：
    整段包含得高分；否则按词的重合程度（任务名里常有错拼 fature / featuer，所以不要求逐字一致）。"""
    n, k = norm(name), norm(kw)
    if not k:
        return 0
    if k in n:
        return 100 - max(0, len(n) - len(k)) * 0.1
    a, b = set(k.split('-')) - {'feature', 'stable', 'fature', 'featuer'}, set(n.split('-'))
    if not a:
        return 0
    hit = len(a & b) / len(a)
    return round(hit * 80, 1) if hit >= 0.6 else 0


def jobs(kws):
    res = {}
    for j in all_jobs():
        s = max(score(j['名称'], k) for k in kws)
        if s:
            res[j['名称']] = dict(j, 分=s)
    return sorted(res.values(), key=lambda x: -x['分'])[:20]


def kind(path):
    p = path.lower()
    return ('安装包' if p.endswith(('.apk', '.aab', '.ipa')) else 'mapping' if p.endswith('mapping.txt') or 'mapping' in p.rsplit('/', 1)[-1]
            else '二维码' if p.endswith(('.png', '.jpg')) and 'qr' in p else '提交' if p.endswith('commit_id.txt') else '符号' if p.endswith('.so') else '其他')


def build_of(b, commit=True):
    params = {}
    rev = {}
    for a in b.get('actions') or []:
        for p in (a or {}).get('parameters') or []:
            params[p.get('name')] = p.get('value')
        if (a or {}).get('lastBuiltRevision'):
            rev = a['lastBuiltRevision']
    arts = [{'名称': x['fileName'], '路径': x['relativePath'], '地址': f'{b["url"]}artifact/{x["relativePath"]}', '类型': kind(x['relativePath'])}
            for x in b.get('artifacts') or []]
    arts = [x for x in arts if x['类型'] != '符号']        # .so 太多，没用
    sha = rev.get('SHA1') or ''
    if not sha and commit:
        c = next((x for x in arts if x['类型'] == '提交'), None)
        if c:
            try:
                sha = get(c['地址'], raw=True).decode('utf-8', 'replace').strip().split()[0][:40]
            except SystemExit:
                sha = ''
    br = params.get('branch') or params.get('BRANCH') or params.get('git_branch') or next(
        (x['name'] for x in rev.get('branch') or []), '')
    ver = str(params.get('build_version') or params.get('version') or params.get('VERSION') or params.get('versionName') or '')
    # 产物文件名里常带完整版本（参数 95.0.0 + 构建号 → 95.0.0.11），崩溃日志里的 versionName 就是它，对 mapping 用这个
    full = next((m.group(0) for x in arts for m in [re.search(re.escape(ver) + r'\.\d+' if ver else r'\d+\.\d+\.\d+\.\d+', x['名称'])] if m), '')
    return {'编号': b['number'], '地址': b['url'], '结果': b.get('result') or ('进行中' if b.get('building') else ''),
            '进行中': bool(b.get('building')), '时间': time.strftime('%Y-%m-%d %H:%M', time.localtime(b['timestamp'] / 1000)),
            '耗时': round((b.get('duration') or 0) / 60000, 1), '版本': full or ver, '版本参数': ver, '分支': re.sub(r'^(origin|refs/heads)/', '', str(br)),
            '提交': sha, '说明': b.get('description') or '', '名称': b.get('displayName') or '',
            '参数': {k: v for k, v in params.items() if isinstance(v, (str, int, float, bool))}, '产物': arts}


def job_url(x):
    if x.startswith('http'):
        return x.split('/api/')[0].rstrip('/') + '/'
    return BASE + '/job/' + '/job/'.join(urllib.parse.quote(p) for p in x.split('/')) + '/'


def builds(x, n=None):
    u = job_url(x)
    j = get(u, f'name,url,builds[{TREE_BUILD}]{{0,{n or NUM}}}')
    bs = j.get('builds') or []
    with ThreadPoolExecutor(6) as ex:
        out = list(ex.map(build_of, bs))
    return {'任务': j.get('name') or x, '地址': j.get('url') or u, '构建': out}


def text(args):
    out = []
    for a in args:
        if re.search(r'/job/[^/]+/\d+/?$', a.split('/api/')[0]):
            b = build_of(get(a, TREE_BUILD))
            out.append(fmt_build(b))
            continue
        js = [{'名称': a, '地址': job_url(a)}] if a.startswith('http') else jobs([a])[:3]
        if not js:
            out.append(f'没找到和「{a}」匹配的 Jenkins 任务')
            continue
        for j in js[:2]:
            r = builds(j['地址'], 5)
            out.append(f'## {r["任务"]}　{r["地址"]}')
            out += [fmt_build(b) for b in r['构建']]
        if len(js) > 2:
            out.append('其他匹配：' + '、'.join(j['名称'] for j in js[2:]))
    return '\n'.join(out)


def fmt_build(b):
    apk = next((x['地址'] for x in b['产物'] if x['类型'] == '安装包'), '')
    mp = next((x['地址'] for x in b['产物'] if x['类型'] == 'mapping'), '')
    return (f'- #{b["编号"]} {b["结果"] or "?"} {b["时间"]} 版本 {b["版本"] or "?"} 分支 {b["分支"] or "?"} 提交 {b["提交"][:10] or "?"}　{b["地址"]}'
            + (f'\n  安装包 {apk}' if apk else '') + (f'\n  mapping {mp}' if mp else ''))


def main():
    a = sys.argv[1:]
    if not a:
        die('给分支名 / 关键词 / 任务地址 / 构建地址')
    cmd = a[0]
    if cmd == 'test':
        n = len(all_jobs())
        print(json.dumps({'文本': f'已连上 {BASE}，能看到 {n} 个任务'}, ensure_ascii=False))
    elif cmd == 'jobs':
        print(json.dumps(jobs(a[1:]), ensure_ascii=False))
    elif cmd == 'builds':
        print(json.dumps(builds(a[1], int(a[2]) if len(a) > 2 else None), ensure_ascii=False))
    elif cmd == 'build':
        print(json.dumps(build_of(get(a[1], TREE_BUILD)), ensure_ascii=False))
    else:
        print(text(a))


if __name__ == '__main__':
    main()
