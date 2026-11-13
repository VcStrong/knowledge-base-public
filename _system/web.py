#!/usr/bin/env python3
# From 大大王.DT
"""知识库网页入口：kb web、launchd / systemd 都调这里的 main()。实现在 webapp 包（分工见 webapp/__init__.py）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from webapp.server import H, main  # noqa: E402,F401

if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 11555)
