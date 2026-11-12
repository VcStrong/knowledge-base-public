# From 大大王.DT
"""ANR / 崩溃日志解析：拆出一次次事件，取关键堆栈，用 mapping.txt 还原混淆，算出「同一个问题」的签名。

只做纯计算，不落盘；存储、归并、和事项关联由 kb.py 负责。
支持：
- ANR traces（/data/anr/anr_*、traces.txt：「----- pid N at … -----」+ 各线程堆栈）、Bugly 等导出的主线程堆栈
- 平台导出的线程堆栈：「main (blocked):tid=1 systid=… | waiting to lock <…> held by thread 41」，
  一次粘贴多段时每段用引号包起来（"main (runnable):tid=1 …"），一段一次 ANR；同一段里的持锁线程一起带上
- Java 崩溃（logcat 的 FATAL EXCEPTION、异常 + at 帧 + Caused by）
- Native 崩溃（tombstone：signal + backtrace #00 pc …）
"""
import hashlib
import re

# 这些包下的帧算「系统 / 三方库」，签名优先取应用自己的帧
SYS_PREFIX = ('android.', 'androidx.', 'java.', 'javax.', 'kotlin.', 'kotlinx.', 'dalvik.', 'libcore.', 'sun.', 'jdk.',
              'com.android.', 'com.google.', 'org.json.', 'org.apache.', 'org.chromium.', 'org.xmlpull.', 'okhttp3.', 'okio.',
              'retrofit2.', 'io.reactivex.', 'rx.', 'com.squareup.', 'com.facebook.', 'com.bumptech.', 'com.tencent.bugly.',
              'com.tencent.mmkv.', 'org.greenrobot.', 'io.flutter.', 'com.github.', 'org.jetbrains.',
              'com.alibaba.', 'com.zing.zalo.', 'com.appsflyer.', 'com.adjust.', 'com.huawei.hms.', 'com.umeng.', 'io.sentry.')
NATIVE_SYS = ('/system/', '/apex/', '/vendor/', '[vdso]', '/data/dalvik-cache/', 'linker')
SIG_FRAMES = 3       # 签名取前几个应用帧
KEY_LINES = 40       # 关键堆栈保留行数

_LOGCAT = re.compile(r'^(?:\d\d-\d\d \d\d:\d\d:\d\d\.\d+\s+\d+\s+\d+\s+[VDIWEF]\s+[^:]{0,60}?:\s?'
                     r'|[VDIWEF]/[^(:]{1,60}\(\s*\d+\):\s?'
                     r'|\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+\s+\d+-\d+/\S+\s+[VDIWEF]/[^:]{0,60}:\s?)')
_FRAME = re.compile(r'^\s*(?:at\s+)?([A-Za-z_$][\w$]*(?:\.[\w$<>-]+)+)\(([^()]*)\)\s*$')
_EXC = re.compile(r'^\s*(Caused by:\s*)?((?:[a-z_$][\w$]*\.)+[A-Za-z_$][\w$]*(?:Exception|Error|Throwable|Failure|Crash)[\w$]*'
                  r'|(?:[a-z_$][\w$]*\.)*[a-z_$]{1,3}\.[a-z_$]{1,3})(?::\s?(.*))?$')
_THREAD = re.compile(r'^"(.+?)"\s.*?\btid=(\d+)\s+(\w+)')
_PTHREAD = re.compile(r'^\s*"?([^"\n()]+?)\s+\((\w+)\):\s*tid=(\d+)\b')     # 平台导出：main (blocked):tid=1 systid=…
_NATIVE = re.compile(r'^\s*#(\d+)\s+pc\s+([0-9a-fA-F]+)\s+(\S+)(.*)$')
_SIGNAL = re.compile(r'signal\s+\d+\s+\((\w+)\)(?:,\s*code\s+-?\d+\s+\((\w+)\))?')


def _clean(text):
    lines = []
    for ln in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        lines.append(_LOGCAT.sub('', ln, count=1).rstrip())
    return lines


def norm_method(m):
    """签名用的方法名：去掉匿名类 / lambda 的序号（不同构建会变）。"""
    m = re.sub(r'\$\$ExternalSynthetic\w+?\d+', '$$Lambda', m)
    m = re.sub(r'\$\$Lambda\$\w+', '$$Lambda', m)
    m = re.sub(r'lambda\$(\w+?)\$\d+', r'lambda$\1', m)
    m = re.sub(r'\$\d+', '$N', m)
    return m


def is_app(method):
    return not method.startswith(SYS_PREFIX)


def _short(method):
    """com.x.gift.GiftPanel$N.onBind → GiftPanel$N.onBind"""
    parts = method.split('.')
    return '.'.join(parts[-2:]) if len(parts) >= 2 else method


def _version(text):
    m = re.search(r'(?:versionName|App\s*version|app_version|应用版本|版本号?|Version)\s*[=:：]\s*v?(\d+(?:\.\d+){1,3}[\w.-]*)', text, re.I)
    return m.group(1) if m else ''


def _when(text):
    m = (re.search(r'-----\s*pid\s+\d+\s+at\s+(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)', text)
         or re.search(r'Timestamp:\s*(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)', text)
         or re.search(r'(?:发生时间|崩溃时间|crashTime|time)\s*[=:：]\s*(\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d)', text, re.I))
    return m.group(1).replace('T', ' ') if m else ''


# ---------------------------------------------------------------- 拆分事件

def split_events(text):
    """一个文件里可能有多次事件：返回 [{'类型', '原文'}]。"""
    lines = _clean(text)
    body = '\n'.join(lines)
    out = []
    # 平台导出的线程堆栈：每段 "线程 (状态):tid=N …" 用引号包着，一段一次 ANR
    if any(_PTHREAD.match(ln) for ln in lines):
        segs, cur = [], []
        for ln in lines:
            if ln.lstrip().startswith('"') and _PTHREAD.match(ln) and cur:
                segs.append(cur)
                cur = []
            cur.append(ln)
        segs.append(cur)
        for sg in segs:
            t = '\n'.join(sg).strip().strip('"').strip()
            if t and _FRAME.search(t) or re.search(r'(?m)^\s*at\s', t):
                out.append({'类型': 'ANR', '原文': t})
        if out:
            return out
    # ANR traces：只要第一个进程块（发生 ANR 的进程；后面是 system_server 等陪跑进程）
    if re.search(r'^-----\s*pid\s+\d+\s+at\s', body, re.M) and re.search(r'^"main"', body, re.M):
        blocks = re.split(r'(?m)^(?=-----\s*pid\s+\d+\s+at\s)', body)
        head = blocks[0] if not blocks[0].lstrip().startswith('-----') else ''
        first = next((b for b in blocks if b.lstrip().startswith('-----') and '"main"' in b), '')
        end = first.find('----- end')
        out.append({'类型': 'ANR', '原文': (head + first[:end if end > 0 else None]).strip()})
    # tombstone：每个「*** *** ***」一块
    if _SIGNAL.search(body) and re.search(r'^\s*#\d+\s+pc\s', body, re.M):
        parts = re.split(r'(?m)^(?=\*\*\* \*\*\* \*\*\*)', body)
        for p in parts:
            if _SIGNAL.search(p) and re.search(r'^\s*#\d+\s+pc\s', p, re.M):
                out.append({'类型': 'Native崩溃', '原文': p.strip()})
    if out:
        return out
    # Java 崩溃：按 FATAL EXCEPTION 切；没有就整段当一次
    if 'FATAL EXCEPTION' in body:
        parts = re.split(r'(?m)^(?=.*FATAL EXCEPTION)', body)
        for p in parts[1:]:
            seg = p.split('\n')
            # 到下一段不相干的日志为止：见过帧以后，遇到不是帧 / 异常 / 「... N more」的行就停
            keep, seen = [], False
            for ln in seg:
                if _FRAME.match(ln):
                    seen = True
                elif seen and not (_EXC.match(ln) or re.match(r'^\s*(\.\.\.\s*\d+\s+more|Suppressed:)', ln)):
                    break
                keep.append(ln)
            out.append({'类型': 'Java崩溃', '原文': '\n'.join(keep).strip()})
        return out
    frames = [ln for ln in lines if _FRAME.match(ln)]
    if len(frames) >= 2:
        anr = re.search(r'\bANR\b|Input dispatching timed out|not responding|无响应|卡死', body, re.I)
        exc = any(_EXC.match(ln) and not _FRAME.match(ln) for ln in lines)
        out.append({'类型': 'ANR' if anr and not (exc and 'Exception' in body and not re.search(r'^"main"|main\(\d+\)', body, re.M)) else 'Java崩溃',
                    '原文': body.strip()})
    return out


# ---------------------------------------------------------------- mapping 还原

class Mapping:
    """ProGuard / R8 mapping.txt。只解析用得到的类（mapping 动辄上百 MB）。"""

    def __init__(self, path, need=None):
        self.cls, self.src, self.members = {}, {}, {}
        need = set(need) if need is not None else None
        cur = None
        with open(path, encoding='utf-8', errors='replace') as fp:
            for ln in fp:
                if not ln.startswith((' ', '\t')):
                    if ln.startswith('#'):
                        continue
                    m = re.match(r'^(\S+)\s+->\s+(\S+):\s*$', ln)
                    cur = None
                    if m and (need is None or m.group(2) in need):
                        cur = m.group(2)
                        self.cls[cur] = m.group(1)
                        self.members[cur] = []
                    continue
                if cur is None:
                    continue
                s = ln.strip()
                if s.startswith('#'):
                    f = re.search(r'"fileName"\s*:\s*"([^"]+)"', s)
                    if f and not self.members[cur]:
                        self.src[cur] = f.group(1)
                    continue
                m = re.match(r'^(?:(\d+):(\d+):)?(\S+)\s+([^\s(]+)\(([^)]*)\)(?::(\d+)(?::(\d+))?)?\s+->\s+(\S+)$', s)
                if m:
                    a, b, _, name, _, oa, ob, obf = m.groups()
                    self.members[cur].append((obf, int(a) if a else None, int(b) if b else None, name,
                                              int(oa) if oa else None, int(ob) if ob else None))

    def klass(self, obf):
        return self.cls.get(obf, obf)

    def frame(self, method, loc):
        """a.b.c(SourceFile:12) → [(原方法全名, 文件, 行号)]，内联链按调用顺序（最里层在前）。"""
        if '.' not in method:
            return [(method, loc, None)]
        cobf, mobf = method.rsplit('.', 1)
        if cobf not in self.cls:
            return [(method, loc, None)]
        corig = self.cls[cobf]
        line = None
        lm = re.search(r':(\d+)$', loc or '')
        if lm:
            line = int(lm.group(1))
        cands = [x for x in self.members.get(cobf, []) if x[0] == mobf]
        if line is not None:
            hit = [x for x in cands if x[1] is not None and x[1] <= line <= x[2]]
            cands = hit or [x for x in cands if x[1] is None] or cands
        if not cands:
            return [(f'{corig}.{mobf}', self._file(cobf, corig), line)]
        names = {x[3] for x in cands}
        ranged = [x for x in cands if x[1] is not None]
        if line is not None and ranged and len(ranged) == len(cands):
            out = []                      # R8 内联：同一行号区间的连续几条就是内联链
            for x in ranged:
                ol = x[4]
                if ol is not None and x[5] is not None and x[5] != x[4]:
                    ol = x[4] + (line - x[1])
                elif ol is None:
                    ol = line
                full = x[3] if '.' in x[3] else f'{corig}.{x[3]}'
                out.append((full, self._file(cobf, corig, full), ol))
            return out
        full = ' | '.join(sorted(n if '.' in n else f'{corig}.{n}' for n in names))
        return [(full, self._file(cobf, corig), None)]

    def _file(self, cobf, corig, full=None):
        if full and '.' in full and not full.startswith(corig + '.'):
            return full.rsplit('.', 1)[0].split('$')[0].rsplit('.', 1)[-1] + '.java'
        return self.src.get(cobf) or corig.split('$')[0].rsplit('.', 1)[-1] + '.java'


def obf_classes(text):
    """事件里出现的、可能被混淆的类名（给 Mapping 只解析这些）。"""
    out = set()
    for ln in text.split('\n'):
        m = _FRAME.match(ln)
        if m and '.' in m.group(1):
            out.add(m.group(1).rsplit('.', 1)[0])
        m = _EXC.match(ln)
        if m and not _FRAME.match(ln):
            out.add(m.group(2))
    return out


def looks_obfuscated(methods):
    app = [m for m in methods if is_app(m)]
    if not app:
        return False
    short = sum(1 for m in app if all(len(p) <= 2 for p in m.split('.')[:-1][-2:]))
    return short * 2 >= len(app)


# ---------------------------------------------------------------- 分析一次事件

def _frames(lines, mp):
    """[(显示行, 方法全名 or None)]；mp 不为空时还原。"""
    out = []
    for ln in lines:
        m = _FRAME.match(ln)
        if not m:
            e = _EXC.match(ln)
            if e and mp:
                ln = ln.replace(e.group(2), mp.klass(e.group(2)), 1)
            out.append((ln.strip(), None))
            continue
        meth, loc = m.group(1), m.group(2)
        if mp:
            for full, f, line in mp.frame(meth, loc):
                out.append((f'at {full}({f}{":" + str(line) if line else ""})', full))
        else:
            out.append((f'at {meth}({loc})', meth))
    return out


def _sig_frames(fr, n=SIG_FRAMES):
    ms = [m for _, m in fr if m]
    app = [m for m in ms if is_app(m)]
    return [norm_method(m) for m in (app or ms)[:n]], app


def _threads(lines):
    """ANR traces → {tid: {'名称', '状态', '行'}}，按出现顺序。"""
    ths, cur = {}, None
    for ln in lines:
        t = _THREAD.match(ln)
        p = None if t else _PTHREAD.match(ln)
        if t or p:
            name, tid, st = (t.group(1), t.group(2), t.group(3)) if t else (p.group(1).strip(), p.group(3), p.group(2))
            cur = {'名称': name, 'tid': tid, '状态': st, '行': [ln]}
            ths[tid] = cur
            continue
        if cur is not None:
            if not ln.strip():
                cur = None
                continue
            cur['行'].append(ln)
    return ths


def analyze(ev, mp=None):
    """返回：类型、签名、标题、原因、关键堆栈（还原后）、是否已还原、版本、发生时间。"""
    kind, raw = ev['类型'], ev['原文']
    lines = raw.split('\n')
    res = {'类型': kind, '版本': _version(raw), '发生时间': _when(raw), '原因': ''}
    if kind == 'Native崩溃':
        s = _SIGNAL.search(raw)
        sig_name = s.group(1) if s else 'SIG?'
        abort = re.search(r"Abort message:\s*'(.+?)'", raw)
        frames = []
        for ln in lines:
            m = _NATIVE.match(ln)
            if m:
                lib = m.group(3).rsplit('/', 1)[-1]
                rest = re.sub(r'\s*\(BuildId:[^)]*\)\s*$', '', m.group(4))
                f = re.match(r'\s*\((.*)\)\s*$', rest)
                fn = re.sub(r'\+\d+$', '', f.group(1)) if f else ''
                frames.append((m.group(3), lib, fn, ln.strip()))
        app = [f for f in frames if not f[0].startswith(NATIVE_SYS)]
        key = [f'{lib}!{fn or "?"}' for _, lib, fn, _ in (app or frames)[:SIG_FRAMES]]
        top = (app or frames or [('', '?', '', '')])[0]
        res.update(签名=f'NATIVE|{sig_name}|' + '|'.join(key), 原因=(abort.group(1) if abort else (s.group(0) if s else '')),
                   标题=f'{sig_name} · {top[1]}' + (f' {top[2]}' if top[2] else ''),
                   关键堆栈=[ln for ln in lines if _SIGNAL.search(ln) or 'Abort message' in ln][:2] + [f[3] for f in frames][:KEY_LINES],
                   已还原=None, 应用帧=[f'{lib} {fn}' for _, lib, fn, _ in app[:5]])
        return res
    if kind == 'ANR':
        reason = re.search(r'(?:Reason|Subject|ANR reason|原因)\s*[:：]\s*(.+)', raw)
        res['原因'] = reason.group(1).strip()[:200] if reason else ''
        ths = _threads(lines)
        main = next((t for t in ths.values() if t['名称'] == 'main'), None)
        if main:
            mlines, state = main['行'], main['状态']
        else:      # 只有一段主线程堆栈（Bugly 之类导出）
            mlines, state = lines, ''
        fr = _frames(mlines, mp)
        key, app = _sig_frames(fr)
        holder = None
        hm = re.search(r'held by (?:thread |tid=)(\d+)', '\n'.join(mlines))
        if hm and hm.group(1) in ths and ths[hm.group(1)] is not main:
            holder = ths[hm.group(1)]
        ms = [m for _, m in fr if m]
        idle = ms and ms[0].endswith('MessageQueue.nativePollOnce') and not app
        if idle:
            sig, title = 'ANR|idle', 'ANR · 主线程空闲（抓堆栈时已恢复，现场没抓到）'
        else:
            sig = 'ANR|' + '|'.join(key)        # 只看主线程的应用帧：状态、持锁线程每次可能不同，不进签名
            title = f'ANR · 主线程 {state + " · " if state else ""}' + (_short(app[0]) if app else (_short(ms[0]) if ms else '?'))
            jdk = ('java.', 'javax.', 'android.', 'androidx.', 'dalvik.', 'libcore.', 'kotlin.', 'kotlinx.', 'sun.', 'jdk.', 'com.android.')
            first = ms.index(app[0]) if app and app[0] in ms else len(ms)
            sdk = [m for m in ms[:first] if not m.startswith(jdk)]
            if sdk:                                 # 卡在三方 SDK 里：写明是哪个（离应用代码最近的那一帧）
                title += f'（卡在三方 {_short(sdk[-1])}）'
        stack = [x for x, _ in fr][:KEY_LINES]
        if holder:
            hf = _frames(holder['行'], mp)
            _, happ = _sig_frames(hf, 2)
            title += f'（锁被「{holder["名称"]}」占着' + (f' @ {_short(happ[0])}' if happ else '') + '）'
            stack += ['', f'—— 持锁线程：{holder["名称"]} tid={holder["tid"]} {holder["状态"]}'] + [x for x, _ in hf][:20]
        res.update(签名=sig, 标题=title, 关键堆栈=stack, 应用帧=[_short(m) for m in app[:5]])
    else:
        # Java 崩溃：根因 = 最后一个 Caused by；签名 = 根因类型 + 它的前几个应用帧
        fr = _frames(lines, mp)
        excs = [i for i, (x, m) in enumerate(fr) if m is None and _EXC.match(x)]
        if not excs:
            excs = [0]
        root_i = excs[-1]
        root = fr[root_i][0]
        em = _EXC.match(root)
        etype = em.group(2) if em else root.split(':')[0]
        msg = (em.group(3) or '') if em else ''
        seg = fr[root_i:]
        nxt = [i for i in excs if i > root_i]
        if nxt:
            seg = fr[root_i:nxt[0]]
        key, app = _sig_frames(seg)
        if not key:                        # 根因只有「... N more」：用顶层异常的帧
            key, app = _sig_frames(fr)
        ename = etype.rsplit('.', 1)[-1]
        res.update(签名=f'JAVA|{etype}|' + '|'.join(key), 原因=f'{ename}: {msg}'[:200] if msg else ename,
                   标题=f'{ename} · ' + (_short(app[0]) if app else (_short(key[0]) if key else '?')),
                   关键堆栈=[x for x, _ in fr if x][:KEY_LINES], 应用帧=[_short(m) for m in app[:5]])
    ms = [m for _, m in fr if m]
    res['已还原'] = True if mp else (False if looks_obfuscated(ms) else None)
    return res


def sig_id(sig):
    return hashlib.sha1(sig.encode()).hexdigest()[:8]


def raw_id(text):
    return hashlib.sha1(re.sub(r'\s+', ' ', text).encode()).hexdigest()[:12]
