#!/usr/bin/env python3
# From 大大王.DT
"""本地知识库入口：命令行（kb …）、MCP 服务（kb.py serve）、web.py 的 import kb。

实现都在 kblib 包里（分层说明见 kblib/__init__.py）。这里只把各模块的名字汇总导出，
web.py、插件、老脚本照旧用 kb.xxx；命令行和 MCP 从 kblib.api.cli.main 启动。
"""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kblib import _Lazy  # noqa: E402

_MODULES = [   # 按依赖从下往上：后面的可以用前面的；分包说明见 kblib/__init__.py
    'core.common',
    'core.textx',
    'core.periods',
    'core.notes',
    'core.repos',
    'core.search',
    'core.baseinfo',
    'ai.flows',
    'ai.engines',
    'plugins.registry',
    'api.overview',
    'ai.devprep',
    'ai.devsession',
    'ai.devices',
    'sources.urlimport',
    'sources.refresh',
    'sources.quickadd',
    'sources.fixlink',
    'bugs.sources',
    'bugs.index',
    'bugs.analysis',
    'bugs.fix',
    'ai.talk',
    'anr.store',
    'anr.manual',
    'plugins.builds',
    'tasks.memo',
    'plugins.run',
    'stack.plan',
    'stack.dev',
    'stack.guide',
    'steward.onboard',
    'plugins.stats',
    'steward.patrol',
    'steward.intake',
    'steward.chat',
    'steward.brief',
    'steward.site',
    'infra.deploy',
    'api.mcp',
    'api.cli',
]
_OWNER = {}
for _name in _MODULES:
    _m = importlib.import_module(f'kblib.{_name}')
    for _k, _v in vars(_m).items():       # 两个模块定义了同名的公开函数，后一个会悄悄覆盖前一个：直接报错，别让网页出怪问题
        if callable(_v) and not _k.startswith('_') and getattr(_v, '__module__', '') == _m.__name__:
            if _k in _OWNER and _OWNER[_k] != _m.__name__:
                raise ImportError(f'{_m.__name__}.{_k} 和 {_OWNER[_k]}.{_k} 重名，kb.{_k} 会被覆盖：请给其中一个改名')
            _OWNER[_k] = _m.__name__
    globals().update({k: v for k, v in vars(_m).items() if not k.startswith('__') and not isinstance(v, _Lazy)})
from kblib.infra import devlock, fetch  # noqa: E402,F401
from kblib.anr import parse as anr  # noqa: E402,F401
from kblib.bugs import adapters as bugsrc  # noqa: E402,F401

if __name__ == '__main__':
    from kblib.api.cli import main
    sys.exit(main() or 0)
