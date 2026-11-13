# From 大大王.DT
"""路径、错误类型、小工具、设置文件：所有模块共用的最底层。"""
import html
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from kblib import lazy
import contextvars

# 会话身份（KB_SESSION / KB_PERIOD）：本机后台会话从环境变量来；远程会话经网页的 /mcp 调用时按请求设置，不改进程环境
_SESS_ENV = contextvars.ContextVar('kb_sess_env', default=None)


def sess_env(k, default=''):
    o = _SESS_ENV.get()
    if o is not None and k in o:
        return o[k]
    return os.environ.get(k, default)


def with_sess_env(env, fn, *a, **kw):
    tok = _SESS_ENV.set(dict(env))
    try:
        return fn(*a, **kw)
    finally:
        _SESS_ENV.reset(tok)
_flows = lazy('kblib.ai.flows')      # 上层模块：用到时才 import（不形成循环）


#!/usr/bin/env python3
# From 大大王.DT
"""本地知识库：按「期」管理需求 / 设计图 / 接口文档 / 其他资料，索引本地代码仓库。

同一份代码提供两种入口：
  - 命令行：kb new / add / search / approve ...（给人用）
  - MCP（stdio）：kb serve（给 Claude Code 用）

开发闸门：一期的状态只有人能改成「已批准开发」（kb approve，必须在真实终端里敲）；
AI 只有在「已批准开发 / 开发中」时才能通过 kb_dev_package 拿到开发包。
"""


ROOT = Path(os.environ.get('KB_ROOT') or Path(__file__).resolve().parents[3])    # kblib/core/common.py → kblib → _system → 知识库根
SYS = ROOT / '_system'          # 数据目录里的 _system（索引、日志、管家记录、临时文件）
PROG = Path(__file__).resolve().parents[2]    # 程序目录（_system：kb.py、ui/、bin/、.venv）；KB_ROOT 指向别处时和 SYS 不同
PERIODS = ROOT / '期'
INBOX = ROOT / '收件箱'
REPOS_FILE = ROOT / '代码仓库.json'
BASE = ROOT / '基础'
DB = SYS / 'index.db'

CATS = ['需求', '设计图', '接口文档', '其他资料']
STATUSES = ['收集中', '已批准开发', '开发中', '已完成', '已暂停']
DEV_OK = ('已批准开发', '开发中')
HIST = '_历史版本'
PROTO_DIR = '原型图'   # 需求/原型图：PRD 里的原型图、参考图，只用于理解交互；UI 以「设计图」里的设计稿为准
DESIGN_HOSTS = ('figma.com', 'lanhuapp.com', 'lanhu.com')
NOTE_SUFFIX = '.说明.md'

IMG_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.heic', '.tif', '.tiff'}
TEXT_EXT = {'.md', '.txt', '.json', '.yaml', '.yml', '.csv', '.tsv', '.sql', '.xml', '.proto',
            '.log', '.ini', '.properties', '.svg', '.har'}
OFFICE_EXT = {'.docx', '.doc', '.rtf', '.odt', '.webarchive'}
DOC_EXT = TEXT_EXT | OFFICE_EXT | IMG_EXT | {'.html', '.htm', '.pdf', '.xlsx', '.pptx'}
CODE_EXT = {'.java', '.kt', '.kts', '.gradle', '.xml', '.json', '.md', '.py', '.js', '.ts', '.tsx',
            '.jsx', '.vue', '.swift', '.m', '.mm', '.h', '.c', '.cc', '.cpp', '.hpp', '.go', '.rs',
            '.proto', '.sql', '.yaml', '.yml', '.properties', '.sh', '.dart', '.cmake', '.toml',
            '.html', '.css', '.scss', '.aidl', '.pro', '.cfg', '.txt'}
SKIP_DIRS = {'.git', 'build', '.gradle', '.idea', 'node_modules', 'dist', 'out', 'Pods', '.cxx',
             'intermediates', '.venv', 'venv', '__pycache__', 'target', '.next', 'DerivedData',
             '.dart_tool', 'generated', '.externalNativeBuild'}
MAX_CODE_BYTES = 400_000
CHUNK_CHARS = 1500


class KBError(Exception):
    pass


class KBNeed(KBError):
    """需要用户在网页上选一下（开发仓库、分支）：data 交给网页弹窗，文字说明给 AI / 命令行。"""
    def __init__(self, msg, data):
        super().__init__(msg)
        self.data = data


def uuid_hex():
    return uuid.uuid4().hex


def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M')


def safe_name(s):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', '-', (s or '').strip()).strip('.- ')
    if not s:
        raise KBError('名称不能为空')
    return s


def read_text(p: Path):
    b = p.read_bytes()
    for enc in ('utf-8', 'gb18030'):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode('utf-8', 'replace')


def html_text(s):
    s = re.sub(r'(?is)<(script|style|noscript)\b.*?</\1>', ' ', s)
    s = re.sub(r'(?i)<br\s*/?>|</(p|div|tr|li|h[1-6]|table|section)>', '\n', s)
    s = html.unescape(re.sub(r'<[^>]+>', ' ', s))
    s = re.sub(r'[ \t ]+', ' ', s)
    return re.sub(r'\n\s*\n+', '\n\n', s).strip()


# 设置文件：网页「⚙ 设置」和各功能的开关都存这里
SETTINGS_FILE = ROOT / '设置.json'


def load_settings():
    try:
        s = json.loads(read_text(SETTINGS_FILE)) if SETTINGS_FILE.exists() else {}
    except ValueError:
        s = {}
    s.setdefault('默认流程', _flows.DEFAULT_FLOW)
    s.setdefault('流程', {})       # id → 自定义流程，或对内置流程的修改
    return s


def save_settings(s):
    tmp = SETTINGS_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=1), 'utf-8')
    tmp.replace(SETTINGS_FILE)
