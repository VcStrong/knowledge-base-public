# From 大大王.DT
"""崩溃平台的共同部分：统一「问题」格式、把堆栈拼成 Android 日志的样子。"""
from .base import Source, SourceError


# ---------------------------------------------------------------- 崩溃平台：统一产出「问题」
# {'外部ID', '标题', '类型'（ANR / Java崩溃 / Native崩溃）, '堆栈'（日志格式文本；None = 没变不用重算）, '原因',
#  '次数', '用户数', '版本', '首次', '最近', '链接', '状态'}
# 堆栈拼成 Android 日志的样子（Java：异常行 + 「\tat 类.方法(文件:行)」；Native：signal 行 + 「#00 pc 地址 库 (函数)」），
# 交给 anr.py 算签名，和手动导入的 traces / tombstone 合并。

def java_stack(excs):
    """excs：[(类型, 消息, [(方法全名, 文件, 行)])]，外层在前、根因在后。"""
    out = []
    for i, (t, msg, frames) in enumerate(excs):
        out.append(('Caused by: ' if i else '') + (t or 'java.lang.Throwable') + (f': {msg}' if msg else ''))
        out += [f'\tat {m}({fl or "Unknown Source"}{":" + str(ln) if ln not in (None, "", 0, "0") else ""})' for m, fl, ln in frames if m]
    return '\n'.join(out)


def native_stack(signal, frames, abort=''):
    """frames：[(地址, 库, 函数)]，崩溃点在前。"""
    out = [f'signal {signal or "SIG?"}'] + ([f"Abort message: '{abort}'"] if abort else [])
    out += [f'    #{i:02d} pc {str(a or "0").replace("0x", "").zfill(8)}  {lib or "?"}' + (f' ({fn})' if fn else '') for i, (a, lib, fn) in enumerate(frames)]
    return '\n'.join(out)


def anr_stack(frames, reason=''):
    out = (['ANR'] + ([f'Reason: {reason}'] if reason else []) + ['"main" prio=5 tid=1 Blocked'])
    return '\n'.join(out + [f'  at {m}({fl or "Unknown Source"}{":" + str(ln) if ln not in (None, "", 0, "0") else ""})' for m, fl, ln in frames if m])


class CrashSource(Source):
    kind = '崩溃'
    MAX_DETAIL = 30           # 每次同步最多取几个新问题的详细堆栈（防限流），剩下的下次取

    def key(self, num):
        return str(num)

    def num(self, key):
        return str(key)

    def get(self, key, download=True):
        raise SourceError('崩溃平台的问题在「💥 ANR / 崩溃」里看（kb_anr），原文点链接到平台上看')
