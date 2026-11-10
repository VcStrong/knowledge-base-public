# From 大大王.DT
"""知识库程序（kb.py / web.py 的实现）。分层，下层不 import 上层（个别上层调用写成「模块.函数」，调用时才取）：

  common            路径、错误、小工具、设置文件
  infra/            独立小工具：设备占用锁（devlock，bin/adb 也用）、网页抓取（fetch）
  textx  search     文本提取；全文索引 / 检索
  periods notes repos baseinfo     期 / 事项、文字资料、代码仓库、基础知识库
  flows engines plugins            开发流程、AI 引擎、插件
  overview devprep devsession devices   网页总览、开发准备、开发会话、手机 / 问题 / 复测
  urlimport refresh quickadd fixlink    网址导入、来源刷新、模糊添加、更正链接
  bugs/             Bug 平台：sources（接入的平台、账号）、index（同步 / 索引 / 归属）、analysis（只读分析）、fix（修复队列）、adapters/（各平台）
  anr/              ANR / 崩溃：parse（解析、签名、mapping 还原）、store（归并、问题、平台同步）
  mcp  cli          对外接口：MCP 工具、命令行

kb.py 是入口：把各模块的名字汇总导出（web.py 和插件按 kb.xxx 用），命令行 / MCP 从这里启动。
"""
import importlib


class _Lazy:
    """上层模块的句柄：第一次取属性时才 import。下层模块要调上层函数时用它，import 时只沿着分层往下走，不会循环。"""
    __slots__ = ('_name',)

    def __init__(self, name):
        object.__setattr__(self, '_name', name)

    def __getattr__(self, attr):
        return getattr(importlib.import_module(self._name), attr)

    def __repr__(self):
        return f'<lazy {self._name}>'


def lazy(name):
    return _Lazy(name)
