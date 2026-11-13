#!/usr/bin/env python3
# From 大大王.DT
"""本地知识库入口：命令行（kb …）、MCP 服务（kb.py serve）、web.py 的 import kb。

实现都在 kblib 包里（分层说明见 kblib/__init__.py）。这里只把各模块的名字汇总导出，
web.py、插件、老脚本照旧用 kb.xxx；命令行和 MCP 从 kblib.cli.main 启动。
"""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kblib import _Lazy  # noqa: E402

_MODULES = [
    'common',
    'textx',
    'periods',
    'notes',
    'repos',
    'search',
    'baseinfo',
    'flows',
    'engines',
    'plugins',
    'overview',
    'devprep',
    'devsession',
    'devices',
    'urlimport',
    'refresh',
    'quickadd',
    'fixlink',
    'bugs.sources',
    'bugs.index',
    'bugs.analysis',
    'bugs.fix',
    'talk',
    'anr.store',
    'anr.manual',
    'builds',
    'memo',
    'pluginrun',
    'stack',
    'stackdev',
    'guide',
    'onboard',
    'stats',
    'steward',
    'intake',
    'chat',
    'deploy',
    'mcp',
    'cli',
]
for _name in _MODULES:
    _m = importlib.import_module(f'kblib.{_name}')
    globals().update({k: v for k, v in vars(_m).items() if not k.startswith('__') and not isinstance(v, _Lazy)})
from kblib.infra import devlock, fetch  # noqa: E402,F401
from kblib.anr import parse as anr  # noqa: E402,F401
from kblib.bugs import adapters as bugsrc  # noqa: E402,F401

if __name__ == '__main__':
    from kblib.cli import main
    sys.exit(main() or 0)
