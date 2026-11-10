# From 大大王.DT
"""网页「＋ 添加」：随手粘贴交给 Claude 归档。"""
import json
import threading
import uuid
from datetime import datetime
from .common import KBError, ROOT, SYS, now, read_text
from .periods import period_dir
from .engines import engine_popen, get_engine
from .devsession import _alive, _dev_result, _notify
from .devices import dev_activity


ADD_FILE = SYS / '模糊添加.json'
ADD_DIR = SYS / '模糊添加'
_ADD = {}                    # 编号 -> 「模糊添加」后台进程
_ADD_LOCK = threading.Lock()


def _add_prompt(text, period):
    where = (f'用户指定放进期「{period}」。' if period else
             '用户没有指定期：按需求名、版本号（如「综合版26」）、主题匹配已有的期；都对不上再 kb_create_iteration 新建一期，期名参照已有期的命名（如「综合版26-聊天室语音麦播放歌曲权限」）。')
    return f"""你是由知识库网页启动的【后台无人值守】知识库整理会话。用户在网页「模糊添加」里随手粘贴了下面的内容，请按知识库规则把它加进知识库。
终端里没有人，不要提问；不要改代码仓库，不要改期的状态，不要批准或开始开发。

用户输入：
<<<
{text}
>>>

做法：
1. 先 kb_overview 看已有的期。{where}
2. 按内容处理（细则见知识库 MCP 说明的规则 2、6、7、8），一段输入里有几件事就逐件处理：
   - 网址 + 条目（如「编号8」）：kb_fetch_url 读原文定位条目，条目链接的需求页、PRD 也读；kb_import_url 导入条目原文和 PRD（PRD 的页面内嵌图片用 attachments ["embedded"]）；条目带设计稿地址的用 kb_import_design。
   - 只有网址：kb_fetch_url 看是什么，按内容整页导入，或用 kb_add_note 登记为链接。
   - 成篇需求、会议纪要：kb_write_doc；零散文字、分支、链接：kb_add_note。
   - 网站账号、测试账号、Wi-Fi、代理、VPN、环境配置等通用信息：kb_base_save（密码、令牌等标机密），不放进期。
   - 不是产品需求、但要处理的工作（用户上报的 ANR / 崩溃、加埋点、线上问题、优化、调研）：对得上已有事项就放进去，否则 kb_create_task 新建事项，再把日志、截图、反馈放进去。
3. 需要人操作才能继续的（抓取要登录、缺 Figma 令牌等）：把链接用 kb_add_note 登记下来，接着做别的，不要卡住。
4. 看不出条目指哪一项、或判断不了归属时：不要猜，也不要新建期，直接结束，在回复里列出候选，请用户补充后重新提交。
5. 最后的回复会原样显示在网页上：简短列出放进了哪一期、导入 / 记下了什么（来源编号、文件名）、需要用户做的事（来源核对、登录命令等）。回复里绝不能出现机密明文。"""


def _add_load():
    try:
        return json.loads(read_text(ADD_FILE)) if ADD_FILE.exists() else []
    except ValueError:
        return []


def _add_save(items):
    tmp = ADD_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(items[-50:], ensure_ascii=False, indent=1), 'utf-8')
    tmp.replace(ADD_FILE)


def _add_finish(aid, code=None):
    with _ADD_LOCK:
        items = _add_load()
        x = next((i for i in items if i['编号'] == aid), None)
        if not x or x.get('状态') != '运行中':
            return
        x.update(状态='已结束', 结束时间=now(), 退出码=code, **_dev_result(x.get('日志', '')))
        _add_save(items)
    _notify('知识库 · 模糊添加', (x.get('结果') or '已结束').splitlines()[0])


def add_sessions(n=20):
    """最近的模糊添加记录（新的在前），运行中的带最近动作。"""
    for x in _add_load():
        if x.get('状态') == '运行中' and x['编号'] not in _ADD and not _alive(x.get('pid', 0)):
            _add_finish(x['编号'])
    out = []
    for x in reversed(_add_load()[-n:]):
        x = dict(x)
        if x.get('状态') == '运行中':
            x['动作'] = dev_activity(x.get('日志'), 8)
        out.append(x)
    return out


def claude_add(text, period=''):
    """网页「模糊添加」：用户随手粘贴（网址 + 编号、几句需求、账号……），后台启动 Claude 按知识库规则判断归属并导入。不作为 MCP 工具提供。"""
    text = (text or '').strip()
    if not text:
        raise KBError('请粘贴要添加的内容')
    if period:
        period = period_dir(period).name
    eng = get_engine()
    ADD_DIR.mkdir(exist_ok=True)
    aid = f'A{datetime.now():%Y%m%d%H%M%S}{uuid.uuid4().hex[:4]}'
    logf = ADD_DIR / f'{aid}.jsonl'
    proc = engine_popen(eng, _add_prompt(text, period), f'kb·模糊添加·{aid}', logf, ROOT)
    _ADD[aid] = proc
    with _ADD_LOCK:
        items = _add_load()
        items.append({'编号': aid, '输入': text[:4000], '期': period, 'pid': proc.pid, '状态': '运行中', '引擎': eng['名称'],
                      '开始时间': now(), '日志': str(logf)})
        _add_save(items)

    def wait():
        code = proc.wait()
        _ADD.pop(aid, None)
        _add_finish(aid, code)
    threading.Thread(target=wait, daemon=True).start()
    return f'已交给 {eng["名称"]} 在后台整理，完成后会通知你'
