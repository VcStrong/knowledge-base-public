# From 大大王.DT
"""Bug / 崩溃平台适配器：知识库本体只认统一格式，每个平台一个适配器（只读）。

两类平台：
- 缺陷单（禅道、Jira…）→ 「🐞 Bug」页：sync 产出统一的 Bug 条目，get 实时拉取一条的正文 / 评论 / 附件。
- 崩溃聚合（Sentry、Firebase Crashlytics、Bugly…）→ 「💥 ANR / 崩溃」页：sync 产出「问题」（签名、堆栈、次数、版本、链接）。

适配器协议里没有任何写操作：知识库从不回写外部平台。
公司 / 小组特有的平台不写进这里，做成「Bug平台」类型的插件（协议见 adapters/plugin.py），由 PluginSource 按同一协议调用。

本模块不 import kb（kb.py 也会作为 __main__ 运行，反向 import 会加载出第二份）；凭据由调用方经 Cred 交进来。

一个平台一个文件：base（共用）、zentao / jira（缺陷）、crash + sentry / crashlytics / bugly（崩溃）、plugin（插件实现的平台）。
新增平台：写一个 Source 子类，加进下面的 ADAPTERS。"""
from kblib.bugs.adapters.base import PLATFORMS, Cred, Source, SourceError, entry, norm
from kblib.bugs.adapters.bugly import BuglySource
from kblib.bugs.adapters.crashlytics import CrashlyticsSource
from kblib.bugs.adapters.jira import JiraSource
from kblib.bugs.adapters.plugin import PluginSource
from kblib.bugs.adapters.sentry import SentrySource
from kblib.bugs.adapters.zentao import ZentaoSource

ADAPTERS = {c.adapter: c for c in (ZentaoSource, JiraSource, SentrySource, CrashlyticsSource, BuglySource)}


def adapter_info():
    """网页「添加平台」用：内置适配器的说明。"""
    return [{'名称': n, '类型': c.kind, '账号字段': c.fields, '选项': [{'名': a, '说明': b, '默认': d} for a, b, d in c.options],
             '关键字': list(c.guess)} for n, c in ADAPTERS.items()]


__all__ = ['ADAPTERS', 'PLATFORMS', 'Cred', 'PluginSource', 'Source', 'SourceError', 'adapter_info', 'entry', 'norm']
