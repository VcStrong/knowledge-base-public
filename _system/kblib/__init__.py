# From 大大王.DT
"""知识库程序的业务层。按领域分包，分五层，下层不在模块顶部 import 上层（要用写 lazy('kblib.x.y')，调用时才取）：

  层 0  基础
    core/      common（路径、设置、错误）、periods（期 / 事项）、notes（文字资料、资料文件）、repos（代码仓库）、
               search（全文索引）、textx（文本提取）、baseinfo（基础信息：账号、环境）
    infra/     hosts（本机 / 远程、git / svn）、deploy（服务器部署、登录、令牌）、devlock（手机占用锁，bin/adb 也用）、
               fetch（网页抓取）、vault（机密存储）
  层 1  能力
    ai/        engines（AI 引擎、角色）、flows（开发流程）、devprep（开发准备）、devsession（开发会话）、
               devices（手机、问题、复测）、talk（期页面对话）
    plugins/   registry（发现、挂载、配置）、run（按时机运行）、builds（构建插件）、stats（统计插件）
    sources/   urlimport（网址导入）、refresh（来源刷新）、fixlink（更正链接）、quickadd（模糊添加）
  层 2  领域
    bugs/      sources（接入的平台）、index（同步、索引、归属）、analysis（只读分析）、fix（修复队列）、adapters/（各平台）
    anr/       parse（解析、签名、mapping 还原）、store（归并、问题）、manual（自建问题）
    tasks/     memo（事项记事本、推动）
    stack/     plan（出方案、拍板）、dev（各端开发、审查、验收）、guide（每一期的下一步）
  层 3  管家
    steward/   patrol（巡检、自主动作）、chat（交给管家）、intake（统一收件）、brief（智能状态、界面模板清单）、
               site（整站导航）、onboard（首次引导、示例期、目录浏览）
  层 4  对外
    api/       mcp（MCP 工具）、cli（命令行）、overview（总览和开发包文本）
  网页接口在 _system/webapp/（routes/ 按领域一个文件），前端在 _system/ui/（core/ 共用功能层 + 每套界面模板一个目录）。

约定
  - 命名：包和模块用领域名词；对外函数 <领域>_<动作>（bug_analyze、stack_plan_start、steward_tick），
    模块内部函数下划线开头；数据字段用中文（和 JSON 文件、网页一致）。
  - kb.py 把各模块的公开函数合到一个命名空间（kb.xxx），公开函数不能重名（导入时会报错）。
  - 新功能放进对应领域的包；跨领域只读数据用对方的公开函数，不直接读对方的 JSON 文件。
  - 给管家、各套界面用的东西产出成「智能状态」的五种素材之一（steward/brief.py：判断、活动、关系、指标、叙述）。
  - 改完跑 python3 tools/check-arch.py：分层、重名、接口、前端语法、模板目录。
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
