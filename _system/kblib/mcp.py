# From 大大王.DT
"""MCP 服务：给 Claude 的工具定义和分发。"""
import json
import sys
from .common import CATS, KBError, STATUSES
from .periods import (
    TASK_KINDS,
    TASK_PRI,
    add_log,
    add_material,
    annotate_image,
    create_period,
    create_task,
    init,
    set_status,
    write_doc,
)
from .notes import NOTE_KINDS, add_note, update_note
from .repos import add_repo, link_repo
from .search import read_file, reindex, search
from .baseinfo import BASE_CATS, base_list, base_save, base_secret
from .plugins import call_plugin
from .overview import dev_package, overview, period_detail
from .devprep import dev_prepare
from .devsession import ask, set_dnd, wait_answer
from .devices import ISSUE_KINDS, add_issue, device_claim, device_release, devices_text, test_report
from .urlimport import fetch_url, import_design, import_url
from .refresh import refresh_sources, take_notices
from .fixlink import _conflict_hint, fix_link
from .bugs.index import ZT_OWNER, bug_assign, bug_get, bug_list, bug_sync
from .bugs.analysis import bug_analysis
from .bugs.fix import bug_fixed
from .talk import take_session_msgs
from .builds import builds_text
from .anr.store import anr_add, anr_link, anr_list, anr_mapping, anr_set_version, anr_show


INSTRUCTIONS = """本地知识库（按「期」管理需求 / 设计图 / 接口文档 / 其他资料，并索引本地代码仓库）。
规则：
1. 回答与业务、需求、接口、历史决策有关的问题前，先 kb_search。
2. 用户给出资料文件时，用 kb_add_material 归档到对应的期；用户粘贴的成篇需求、会议纪要，用 kb_write_doc 存成文档，保证每期有完整记录。
   零散的文字资料用 kb_add_note 原样记下（不必是完整原料）：产品说的几句话、要开发的分支、其他小组给的文档地址、账号/环境等。
   分类按内容选（产品说的需求 → 需求，接口相关 → 接口文档，分支/链接/其他 → 其他资料）；能看出是谁说的就填「来自」。
   链接只登记、不强求抓取；之后能访问再按规则 6 导入。内容有变化用 kb_update_note 修改，不要重复新增。
3. 设计图没有文字说明时，用 Read 查看图片后调用 kb_annotate_image 写说明（页面、模块、交互、文案），便于以后检索。
4. 开发必须由用户批准：只有期状态是「已批准开发」或「开发中」时才能写代码，入口是 kb_dev_package。
   批准只能由用户本人操作：终端运行 kb approve <期名>，或在知识库网页点「开始开发」（输入期名确认）。
   你绝不能代为执行 kb approve、调用知识库网页的接口（开始/停止开发、回答待确认问题等），或用其他方式绕过。
5. 开发按这一期的「开发流程」执行（用户在知识库网页「⚙ 设置」里配置，默认是「通用模板」），不要自行换用别的流程，除非这一期选的就是它。
   具体命令写在 kb_dev_package 的「开发约定」里。开发开始时先调用 kb_dev_prepare：它按流程定位文档目录、把本期资料拷过去并列出候选链接
   （SDD 流程：随即按 sdd-start.md 各栏注释把链接、负责范围、接口说明填进空栏，不覆盖已填内容，不用问用户，再用 /sdd-next 推进）。
   开发中需要用户确认时（等人审阅方案 / 接口、待确认问题、方案取舍、操作被拦截等），
   用 kb_ask 发到网页（写清问题、背景、选项、你的建议 recommend），再用 kb_wait_answer 等回答并照做，拿到回答前不要自行决定。
   这一期开了「免打扰」时 kb_ask 会直接返回：按你的建议执行，并用 kb_log 记录理由。免打扰由用户在网页随时开关。
8. 基础知识库（所有期共用的基础上下文）：用户给出网站账号密码、测试某功能用的账号、Wi-Fi / 代理 / VPN、环境配置等通用信息时，
   用 kb_base_save 存进去（密码、令牌、密钥等字段标记 机密=true，只存钥匙串）；回答问题、开发、测试前先用 kb_base 查。
   机密明文只在真正执行时用 kb_base_secret 读取，绝不写进代码、文档、提交、知识库记录或回复里；只属于某一期的信息仍记在那一期。
   开发中的关键决定、接口变更用 kb_log 记录；完成后用 kb_set_status 标为「已完成」。
6. 用户给出网址（Confluence 等）并说「把 XX 加到知识库」时：先 kb_fetch_url 读原文，找到对应条目（如「编号6」所在的表格行或章节）及其关联的链接页面和附件；
   条目里链接到的其他 Confluence 页面也要 kb_fetch_url 看一下，相关的一并导入。然后用 kb_import_url 导入：content 放该条目的原文（保持原意，可带表头），
   summary 写清楚讲了什么，attachments 选相关附件。导入后向用户逐条汇报来源地址和简介，提醒其在网页这一期「资料 → 来源核对」里核对。
   不确定条目指的是哪一项时，把候选列出来问用户，不要猜。抓取提示需要登录时，请用户在终端运行 kb login <主机> <用户名>，不要索要密码。
   用户说需求 / 设计改了、要更新资料时，用 kb_refresh_sources 按登记的网址重新抓取；返回「条目待更新」的，读差异和新快照，
   用 kb_import_url 以同样的 url、item、category、filename 重新导入更新后的条目原文，并向用户汇报改了什么。
   工具结果末尾出现【需求来源有更新】时，按其提示评估对开发的影响。
   用户说某个链接（设计稿、文档地址）给错了时，用 kb_fix_link 更正，不要只改一处；开发中也可以改，会提醒开发会话重新下载物料。
7. 原型图和设计稿要分清：PRD / Axure 里的图是原型图或参考图（存在 需求/原型图/），只用来理解交互和逻辑；
   要实现的产品图是「设计稿地址」那一项（Figma 或蓝湖链接），用 kb_import_design 导入到「设计图」。
   导入需求条目时，若条目带设计稿地址，必须一并导入设计稿。开发时 UI（布局、尺寸、颜色、文案、字号）以设计稿为准，原型与设计稿冲突时以设计稿为准并用 kb_log 记录。
9. 手机是多个期共用的：在手机上装包、测试前先 kb_devices 看、kb_device_claim 申请，只在申请到的手机上操作（adb -s <序列号>），
   不要往别的期占着的手机装包（会覆盖对方的包、打断对方测试），测完 kb_device_release。
   手机不够或没连、缺测试账号、环境不满足等让部分验证做不了、但不影响继续开发的问题，用 kb_issue 记下（写清要什么），然后继续，不要停下等；
   用户会在网页看到并收到通知，条件具备后在网页点「复测」补测。复测会话测完用 kb_test_report 汇报。
10. Bug：知识库定时从 Bug 平台（禅道、Jira…，在网页「🐞 Bug → 平台」接入）同步「我的」安卓 Bug，按执行 / Sprint / 项目 / Jenkins 分支自动归到期，认不出的进「待归纳」。
   知识库里只有索引（链接 + 一两句简介），不是原文：问某期有哪些 Bug 用 kb_bugs；要分析、修复、回答 Bug 细节前，
   必须先用 kb_bug_get 从平台实时拉取正文、评论和截图（截图在临时目录，用 Read 看），不要只凭索引里的简介下结论，
   也不要把拉到的正文、截图存进知识库。用户说某个 Bug 属于哪一期 / 先放着时，用 kb_bug_assign 改归属。
11. 事项：不是产品需求、但要推动的工作（用户上报的 ANR / 崩溃、给功能加埋点、线上问题、优化、调研、其他）用 kb_create_task 建成「事项」，
   不要硬塞进某一期；截图、用户反馈照常用 kb_add_material / kb_add_note 放进事项。几个 Bug 是同一个问题时归到同一个事项。
   事项开始处理同样要用户本人批准，默认按轻量流程（定位 → 用 kb_ask 确认改法 → 修改自测 → 在「其他资料」写 结论.md）。
   排查类似问题前先 kb_search 看有没有以前事项的结论。
12. Bug 分析：用户在对话里让你分析某个 Bug 时，照网页分析会话的做法（只读：kb_bug_get 实时拉取 → 对照本期分支改动和代码定位 → 亲自读过代码位置），
   结论用 kb_bug_analysis 提交，等用户在网页审核；分析阶段不改代码。审核（通过 / 打回）只能用户在网页上做。
   修复：用户在网页对审核通过的 Bug 点「🔧 修复」，知识库起独立的修复会话（每个 Bug 一个提交，kb_bug_fixed 标记）；
   对话里用户让你修某个 Bug 时，同样按通过的分析改、单独提交、kb_bug_fixed 标记。修复状态只记在知识库，绝不改 Bug 平台（平台只用来拉数据）。
13. ANR / 崩溃：用户给 ANR traces、tombstone、崩溃 logcat、Bugly 导出、bugreport.zip 时，用 kb_anr_add 归档（不要用 kb_add_material）：
   知识库按堆栈签名合并成「问题」并累计次数，有对应版本的 mapping 时自动还原混淆；用户给 mapping.txt 时用 kb_anr_mapping 按版本归档（会重算已有样本）。
   问题要处理时用 kb_anr_link 建 / 关联「ANR/崩溃」事项（或 kb_anr_add 时直接带 task）；排查时 kb_anr 看合并后的堆栈和样本原文，先 kb_search 找以前的结论。
14. 工具插件：用户装了按需调用的插件（如按会话编号拉取外部系统里的会话）。用户给出插件能处理的东西（如 resume=会话编号）时，
   先 kb_plugin_call 不带参数看有哪些插件、各要什么参数，再带参数调用；结果以插件输出为准。
   外部系统的内容只做索引：推动解决时建 / 关联事项，用 kb_add_note 记下来源（编号、地址、一句话简介），不要把整段原文存进知识库，处理时重新调用插件拉最新内容。
15. 构建：挂了构建插件（如 Jenkins）时，每一期按分支对应构建任务。要测试包、对版本号、找某次构建的提交或 mapping 时用 kb_builds 查，不要自己猜地址；
   只读，不要触发构建。崩溃日志版本没有 mapping 时，kb_builds 里同版本构建的 mapping 地址可以下载后用 kb_anr_mapping 归档。"""

S = lambda **props: {'type': 'object', 'properties': props}
STR = lambda d: {'type': 'string', 'description': d}
CAT = {'type': 'string', 'enum': CATS, 'description': '分类'}

TOOLS = [
    ('kb_overview', '知识库总览：每期状态与材料数、代码仓库、收件箱待整理文件。', S(), []),
    ('kb_iteration', '查看一期的详情：状态、说明、各分类材料清单、关联仓库、最近记录。',
     S(name=STR('期名（可写部分，唯一匹配即可）')), ['name']),
    ('kb_create_iteration', '新建一期（产品需求的批次 / 版本；不是产品需求的工作用 kb_create_task 建事项），生成 需求/设计图/接口文档/其他资料 目录和记录文件。',
     S(name=STR('期名，建议「日期-主题」，如 2026-11-签到活动v2'), summary=STR('这一期的简介')), ['name']),
    ('kb_add_material', '把本地文件或目录（含收件箱里的）归档到某一期；同名文件自动保留旧版本。不传分类会按文件名自动判断。',
     S(iteration=STR('期名'), path=STR('源文件或目录的绝对路径'), category=CAT, note=STR('备注，写进记录')),
     ['iteration', 'path']),
    ('kb_write_doc', '把文字内容（粘贴的需求、会议纪要、接口说明等）保存为某期下的文档。',
     S(iteration=STR('期名'), category=CAT, filename=STR('文件名，默认 .md'), content=STR('文档内容（Markdown）'),
       note=STR('备注')), ['iteration', 'category', 'filename', 'content']),
    ('kb_add_note', '给某期记一条文字资料（不是文件）：产品说的几句话、要开发的分支、其他小组给的文档地址等，原样保存、可检索，开发包会带上。'
                    '不传分类时：文字 → 需求，分支 / 链接 → 其他资料。',
     S(iteration=STR('期名'), content=STR('文字内容，原样记录；只有链接时可空'), category=CAT,
       kind={'type': 'string', 'enum': NOTE_KINDS, 'description': '类型：文字 / 链接 / 分支 / 其他；不传自动判断'},
       title=STR('简短标题，可空'), url=STR('链接地址（类型为链接时）'), source=STR('来自谁 / 哪个小组，如「产品 小王」')),
     ['iteration']),
    ('kb_update_note', '修改或删除某期的一条文字资料（编号如 T001，见 kb_iteration）。只传要改的字段。',
     S(iteration=STR('期名'), id=STR('编号，如 T001'), content=STR('新内容'), category=CAT,
       kind={'type': 'string', 'enum': NOTE_KINDS}, title=STR('新标题'), url=STR('新链接'), source=STR('来自'),
       delete={'type': 'boolean', 'description': 'true 表示删除这条'}), ['iteration', 'id']),
    ('kb_search', '全文检索知识库文档和已登记代码。多个关键词用空格分隔（同时命中优先）。',
     S(query=STR('关键词'), iteration=STR('限定某一期'), category=CAT,
       scope={'type': 'string', 'enum': ['all', 'docs', 'code'], 'description': '范围，默认 all'},
       repo=STR('限定某个代码仓库'), limit={'type': 'integer', 'description': '条数，默认 10，最多 50'}), ['query']),
    ('kb_read', '读取知识库或已登记仓库中的文件文本（自动解析 docx/pdf/xlsx/pptx/html），支持分段。',
     S(path=STR('文件绝对路径'), start={'type': 'integer', 'description': '起始行，默认 1'},
       max_lines={'type': 'integer', 'description': '最多行数，默认 300'}), ['path']),
    ('kb_annotate_image', '给设计图写文字说明（保存为同目录 <图片名>.说明.md 并建索引）。',
     S(path=STR('图片绝对路径'), description=STR('图片说明：页面、模块、交互、文案、状态')), ['path', 'description']),
    ('kb_add_repo', '登记本地代码文件夹并建立代码索引（大仓库首次可能需要几分钟）。',
     S(path=STR('代码目录绝对路径'), name=STR('仓库名，默认目录名')), ['path']),
    ('kb_link_repo', '把已登记的代码仓库关联到某一期（开发包会带上它）。',
     S(iteration=STR('期名'), repo=STR('仓库名')), ['iteration', 'repo']),
    ('kb_reindex', '重建/增量更新索引。', S(target=STR('all / docs / code / 仓库名，默认 all')), []),
    ('kb_dev_prepare', '开发前准备（已批准开发后、按流程推进前调用）：按这一期的开发流程认出目标仓库和分支、定位文档目录，'
                       '把本期全部资料拷到 文档目录/资料目录名/（不进 git），返回候选链接和接下来的步骤。'
                       'SDD 流程还会按仓库模板新建 sdd-start.md / sdd-status.md，链接按 SDD 栏目分组，供你按 sdd-start.md 注释填写空栏。',
     S(iteration=STR('期名'), repo=STR('目标仓库名或绝对路径；文字资料写了代码路径时可空'),
       store=STR('SDD：多人协作时的子目录名（同 /sdd-start nameB），一般留空')), ['iteration']),
    ('kb_sdd_prepare', '旧名，同 kb_dev_prepare。',
     S(iteration=STR('期名'), repo=STR('目标仓库名或绝对路径'), store=STR('一般留空')), ['iteration']),
    ('kb_base', '查看 / 搜索基础知识库（所有期共用：网站账号、测试账号、Wi-Fi / 代理 / VPN、环境配置等）。机密字段只显示掩码。',
     S(query=STR('关键词，可空（空 = 全部）'), category={'type': 'string', 'enum': BASE_CATS, 'description': '分类，可空'}), []),
    ('kb_base_save', '新增 / 修改 / 删除基础知识库条目。密码、令牌、密钥等字段务必 机密=true（只存 macOS 钥匙串）。'
                     '修改时只传要改的项；fields 传入后整体替换字段列表，机密字段值留空表示保持原值。',
     S(id=STR('编号，如 B001；新增时不传'), category={'type': 'string', 'enum': BASE_CATS, 'description': '分类'},
       name=STR('名称，如「测试账号（国内）」「办公室 Wi-Fi」'), scope=STR('适用产品 / 场景，如「签到功能测试」'),
       fields={'type': 'array', 'description': '字段列表',
               'items': {'type': 'object', 'properties': {'名': {'type': 'string'}, '值': {'type': 'string'},
                                                           '机密': {'type': 'boolean'}}, 'required': ['名']}},
       note=STR('备注（Markdown）'), file=STR('附件文件绝对路径（如 VPN 配置文件），会复制到 基础/附件/'),
       delete={'type': 'boolean', 'description': 'true 表示删除这条'}), []),
    ('kb_base_secret', '读取基础知识库里某个机密字段的明文（会记录读取）。只在真正执行时用（如测试时登录），'
                       '读到的值不要写进代码、文档、提交、日志或回复。',
     S(id=STR('编号，如 B001'), field=STR('字段名，如「密码」'), purpose=STR('用途，如「设备测试登录」')), ['id', 'field']),
    ('kb_ask', '开发中向用户提一个待确认问题（显示在知识库网页并弹系统通知）。之后用 kb_wait_answer 等回答；'
               '本期开了免打扰时直接返回，按你的建议执行。',
     S(iteration=STR('期名'), question=STR('要确认的问题，一句话说清'), context=STR('背景：为什么要问、影响什么（Markdown）'),
       options={'type': 'array', 'items': {'type': 'string'}, 'description': '可选方案（用户可点选，也可自己写）'},
       recommend=STR('你的建议方案（免打扰时按它执行）'), stage=STR('阶段，如 需求分析 / 技术规划 / TASK-3'),
       files={'type': 'array', 'items': {'type': 'string'}, 'description': '相关文件绝对路径（如 prd.md），网页上可点开'}),
     ['iteration', 'question']),
    ('kb_wait_answer', '等待用户在网页回答 kb_ask 提的问题（每次最多等几分钟，没回答就再调一次）。',
     S(iteration=STR('期名'), id=STR('问题编号，如 Q001'), timeout={'type': 'integer', 'description': '本次最多等多少秒，默认 240'}),
     ['iteration', 'id']),
    ('kb_devices', '查看连着的手机和占用情况：哪台空闲、哪台被哪一期（哪个分支）占着。手机是多个期共用的，装包测试前先看。',
     S(iteration=STR('期名')), ['iteration']),
    ('kb_device_claim', '申请手机给这一期测试（优先本期已占着的，再挑空闲的）：返回能用的序列号，只在这些手机上装包、操作'
                        '（adb -s <序列号> / agent-device --serial）。不够时自动记成非阻断问题并通知用户，你继续开发。',
     S(iteration=STR('期名'), count={'type': 'integer', 'description': '要几台，默认 1（多台场景一次申请够）'},
       serials={'type': 'array', 'items': {'type': 'string'}, 'description': '指定序列号（可空）'},
       reason=STR('用途，如「TASK-5 多人送礼：主持 + 2 个麦上用户」')), ['iteration']),
    ('kb_device_release', '释放这一期占着的手机（测完就释放，别的期才能用）。',
     S(iteration=STR('期名'), serials={'type': 'array', 'items': {'type': 'string'}, 'description': '只释放这些；空 = 全部'}),
     ['iteration']),
    ('kb_issue', '记一个不阻断开发、但要用户知道并处理的问题（显示在网页并弹通知，不用等回答）：手机不够或没连、缺测试账号、'
                 '环境不满足导致某些验证做不了等。记下后继续开发；用户条件具备后会点「复测」补测。',
     S(iteration=STR('期名'), title=STR('一句话：缺什么、影响什么，如「需要 3 台手机：多人送礼 case 只测了 2 人」'),
       detail=STR('详情：涉及哪些 case / 任务、现在的情况、证据路径（Markdown）'),
       kind={'type': 'string', 'enum': ISSUE_KINDS, 'description': '类型，不传自动判断'},
       need=STR('要用户提供什么，如「3 台手机」「第 2 个测试账号」')), ['iteration', 'title']),
    ('kb_test_report', '测试 / 复测结束时汇报结果（记进这一期、释放手机、通知用户；仍有阻塞时保留「待复测」）。',
     S(iteration=STR('期名'), summary=STR('小结：测了哪些、结果、发现的问题'),
       passed={'type': 'integer', 'description': '通过数'}, failed={'type': 'integer', 'description': '失败数'},
       blocked={'type': 'integer', 'description': '仍然阻塞（没测成）数'}, need=STR('还缺什么条件，如「第 3 台手机」')),
     ['iteration', 'summary']),
    ('kb_set_dnd', '开关某期的免打扰（用户明确要求时才用）：开启后需要确认的地方由 AI 自行决策并记录。',
     S(iteration=STR('期名'), on={'type': 'boolean', 'description': 'true 开启，false 关闭'}), ['iteration', 'on']),
    ('kb_dev_package', '获取某期的开发包（全部需求、接口文档正文，设计图路径，关联仓库）。仅当用户已批准开发时可用。',
     S(iteration=STR('期名')), ['iteration']),
    ('kb_set_status', '修改某期状态。AI 只能设为 开发中（需已批准）/ 已完成（需开发中）/ 收集中 / 已暂停；「已批准开发」只能由用户本人操作。',
     S(iteration=STR('期名'), status={'type': 'string', 'enum': [s for s in STATUSES if s != '已批准开发']},
       note=STR('备注')), ['iteration', 'status']),
    ('kb_log', '往某期的 记录.md 追加一条记录（关键决定、变更、结论）。',
     S(iteration=STR('期名'), note=STR('记录内容')), ['iteration', 'note']),
    ('kb_fetch_url', '读取网页或 Confluence 页面（不保存）：返回正文（Markdown，含表格、链接、图片地址）、附件清单、子页面。'
                     '用于先看原文、定位用户说的条目（如「编号6」）。Confluence 需用户先 kb login。',
     S(url=STR('网址'), start={'type': 'integer', 'description': '正文起始字符位置，长页面分段读'}), ['url']),
    ('kb_import_url', '把网页 / Confluence 页面或其中某个条目导入一期：保存为文档（顶部写明来源地址、页面版本、条目、简介）、'
                      '保存整页原文快照、按需下载附件，并登记到「来源」清单供用户核对。'
                      '只导某个条目时，把该条目的原文内容（及相关上下文）整理后放进 content，不要改写原意。',
     S(iteration=STR('期名'), url=STR('网址'), category=CAT, item=STR('条目，如「编号6」；整页导入可空'),
       summary=STR('简介：这份资料讲了什么、对应哪个条目、包含哪些附件，用户据此核对'),
       content=STR('只导条目时：该条目的原文内容（Markdown）；空则导入整页'),
       attachments={'type': 'array', 'items': {'type': 'string'},
                    'description': '要下载的附件名或图片/文件网址；"embedded" 表示页面内嵌图片（Axure 导出 PRD 常见）；["all"] 表示全部'},
       filename=STR('保存的文件名，默认「页面标题-条目」')), ['iteration', 'url', 'category', 'summary']),
    ('kb_refresh_sources', '按登记的网址重新抓取某期的来源（产品改了需求时用）：原文没变只记检查时间；整页导入的资料和 Figma 设计稿'
                           '自动重新导入（旧版进历史版本，差异存到 来源快照/变更/）；只导入了条目的，改动落在条目上时标记「待更新」，'
                           '你要按返回的提示重新整理条目。',
     S(iteration=STR('期名'), sid=STR('来源编号如 S001；空则检查全部')), ['iteration']),
    ('kb_create_task', '新建一个「事项」：不是产品需求、但要用知识库推动的工作（用户上报的 ANR / 崩溃、给功能加埋点上报、线上问题排查、性能优化、调研、其他）。'
                       '资料照常用 kb_add_material / kb_add_note 放进去；开始处理同样要用户本人批准，默认按轻量流程（定位 → 确认改法 → 修改自测 → 写结论）。',
     S(name=STR('事项名，简短说清是什么，如「歌房进房 ANR」「礼物面板曝光埋点」'), summary=STR('说明：现象 / 要做什么、影响范围、谁提的'),
       kind={'type': 'string', 'enum': TASK_KINDS, 'description': '类型（不填自动判断）'}, source=STR('来自哪里，如「用户反馈 vv号 123」「Bugly」「产品 小王」'),
       priority={'type': 'string', 'enum': TASK_PRI, 'description': '优先级，默认中'},
       bugs={'type': 'array', 'items': {'type': 'string'}, 'description': '一并归进来的 Bug 编号'}), ['name']),
    ('kb_anr_add', '归档 ANR / 崩溃日志：ANR traces（anr_*、traces.txt）、tombstone、崩溃 logcat、Bugly 导出、bugreport.zip 或目录。'
                   '拆成一次次事件，按关键堆栈签名合并到「问题」并累计次数；有该版本 mapping 时自动还原混淆。返回每个问题的编号和累计次数。',
     S(paths={'type': 'array', 'items': {'type': 'string'}, 'description': '日志文件 / 目录 / zip 的绝对路径'},
       version=STR('App 版本号（日志里认不出版本时填；mapping 按版本对应）'), source=STR('来源，如「用户反馈 vv号 123」「Bugly」'),
       task=STR('直接关联到这个事项（可空）'), count={'type': 'integer', 'description': '这份日志代表发生了几次（Bugly 统计等，默认 1）'}), ['paths']),
    ('kb_anr', '查 ANR / 崩溃问题：不带编号 = 列表（按次数排）；带编号 = 合并后的关键堆栈（已还原）、原因、版本、次数、样本原文路径。',
     S(id=STR('问题编号（8 位）'), query=STR('关键词'), task=STR('只看关联到这个事项的')), []),
    ('kb_anr_mapping', '按版本归档 ProGuard / R8 的 mapping.txt，并用它重算这个版本已归档的样本（还原混淆，签名可能合并）。',
     S(version=STR('版本号，如 5.32.1'), path=STR('mapping.txt 的绝对路径')), ['version', 'path']),
    ('kb_builds', '这一期（事项）在构建平台（如 Jenkins）上的构建：任务、每次构建的结果、完整版本、提交、安装包和 mapping 地址、这个包上报的 Bug。'
                  '找测试包装机、对版本、给 ANR / 崩溃取 mapping 时用；只读，不触发构建。',
     S(iteration=STR('期 / 事项名'), count={'type': 'integer', 'description': '每个任务取几次构建（默认 5）'}), ['iteration']),
    ('kb_plugin_call', '调用按需「工具」插件（用户自己装的，如按会话编号拉取外部系统的会话内容）。不带 plugin = 列出可用插件和参数说明。'
                       '插件需要的账号由知识库从基础信息交给插件，不要自己找密码。',
     S(plugin=STR('插件 id（先不带参数调用一次看有哪些）'), args={'type': 'array', 'items': {'type': 'string'}, 'description': '传给插件的参数'},
       iteration=STR('相关的期 / 事项名（可空；填了会在它的记录里记一笔调用）')), []),
    ('kb_anr_link', '把 ANR / 崩溃问题关联到事项：task 写已有事项名，或「＋新建」自动建一个「ANR/崩溃」事项；空字符串 = 取消关联。'
                    '也可以设 version 给版本不明的样本补版本号。用户说了才改。',
     S(id=STR('问题编号'), task=STR('事项名 / ＋新建 / 空'), version=STR('给这个问题版本不明的样本补版本号'), note=STR('备注')), ['id']),
    ('kb_bugs', '列出 Bug 索引（只有链接、标题、简介、状态、归属）。可按期、归属（期 / 事项 / 待归纳 / 未关联）、状态、关键词筛。'
                '要看正文 / 截图 / 评论用 kb_bug_get 实时拉取。',
     S(iteration=STR('期名（可空 = 所有期）'), owner={'type': 'string', 'enum': list(ZT_OWNER), 'description': '归属类型'},
       status=STR('未关闭（默认）/ 全部 / 激活 / 已解决 / 已关闭'), query=STR('关键词')), []),
    ('kb_bug_get', '从 Bug 平台（禅道、Jira…）实时拉取一个 Bug 的完整内容：正文、评论 / 处理记录、截图和附件（下载到临时目录，不进知识库），并刷新索引。'
                   '分析或修复 Bug 前必须先调它，以平台最新内容为准。',
     S(id=STR('Bug 编号（索引里的编号，如 82613、APP-123）')), ['id']),
    ('kb_bug_assign', '修改 Bug 归属：归到某一期（同时绑定它的执行 / Sprint，以后同一个的 Bug 自动归过来）、放回「待归纳」，或「事项:名称」。用户明确说了才改。',
     S(id=STR('Bug 编号'), target=STR('期名 / 待归纳 / 事项:名称')), ['id', 'target']),
    ('kb_bug_analysis', '提交一个 Bug 的分析结论（只读分析：代码位置 + 原因 + 修复思路），存进知识库等用户在网页审核。'
                        '提交前必须先 kb_bug_get 实时拉取、并亲自读过给出的代码位置；看不出就写低置信度和缺少的信息，不要编造。',
     S(id=STR('Bug 编号'), summary=STR('一句话结论'),
       locations={'type': 'array', 'description': '代码位置，按可能性从高到低，最多 5 个',
                  'items': {'type': 'object', 'properties': {'path': STR('相对仓库根目录的路径'), 'line': {'type': 'integer'},
                                                             'note': STR('为什么可疑')}}},
       cause=STR('原因推测（附证据）'), fix=STR('修复思路（改哪里、怎么改，可给备选）'), impact=STR('影响范围'),
       selftest=STR('自测要点'), confidence={'type': 'string', 'enum': ['高', '中', '低']}, missing=STR('还缺什么信息')),
     ['id', 'summary']),
    ('kb_bug_fixed', '在知识库里标记 Bug 修好了（或没修成），附提交号和说明。只记在知识库，不改 Bug 平台。修复会话改完提交后用；用户说某个 Bug 已经修了也用它。',
     S(id=STR('Bug 编号'), done={'type': 'boolean', 'description': 'true = 修好了；false = 没修成（note 写原因）'},
       commits={'type': 'array', 'items': {'type': 'string'}, 'description': '修复的提交号'}, note=STR('改了什么、怎么验证的、还要人工确认什么 / 没修成的原因')),
     ['id']),
    ('kb_bug_sync', '立即同步 Bug 平台（禅道、Jira…）的 Bug 索引，以及崩溃平台（Sentry、Firebase、Bugly…）到 ANR / 崩溃（平时 15 分钟自动同步一次）。',
     S(source=STR('只同步这个平台（空 = 全部）')), []),
    ('kb_fix_link', '更正某期里给错的链接（设计稿、需求文档地址等）：文档、文字资料、来源、SDD 的 sdd-start.md 一起换成新链接，'
                    '旧内容进历史版本，按新链接重新导入，并提醒开发会话重新下载物料 / 修订。用户说「设计稿链接错了，应该是 XX」时用。',
     S(iteration=STR('期名'), old=STR('错误的旧链接（Figma 只要文件和 node-id 对得上即可）'), new=STR('正确的新链接'),
       reason=STR('原因，如「设计稿给错了版本」')), ['iteration', 'old', 'new']),
    ('kb_import_design', '导入设计稿（要实现的产品图，Figma / 蓝湖链接，通常是需求表里的「设计稿地址」）：'
                         'Figma 逐个画板导出 PNG 并生成设计规格（文案、字体字号、颜色、尺寸），存进「设计图」；蓝湖暂只登记链接。',
     S(iteration=STR('期名'), url=STR('Figma / 蓝湖 链接（保留 node-id 参数）'), item=STR('条目，如「编号6」'),
       summary=STR('简介：这是哪个需求的设计稿、包含哪些页面')), ['iteration', 'url']),
]


_NOTICED = ('kb_dev_package', 'kb_wait_answer', 'kb_log')   # 这几个自己带上了提醒


def call_tool(name, a):
    """调用工具；带期名的，结果后面附上这一期的提醒（需求来源更新、用户在网页发来的消息）。"""
    res = _call_tool(name, a)
    if a.get('iteration') and name not in _NOTICED and isinstance(res, str):
        res += take_notices(a['iteration'])
    if isinstance(res, str):
        res += take_session_msgs()          # Bug 分析 / 修复会话：用户在期页面发给它的消息
    return res


def _call_tool(name, a):
    g = a.get
    if name == 'kb_overview':
        return overview()
    if name == 'kb_iteration':
        return period_detail(g('name'))
    if name == 'kb_create_iteration':
        return create_period(g('name'), g('summary') or '')
    if name == 'kb_add_material':
        return add_material(g('iteration'), g('path'), g('category'), g('note') or '')
    if name == 'kb_write_doc':
        return write_doc(g('iteration'), g('category'), g('filename'), g('content') or '', g('note') or '')
    if name == 'kb_add_note':
        return (add_note(g('iteration'), g('content'), g('category'), g('kind'), g('title'), g('url'), g('source'))
                + _conflict_hint(g('iteration'), f'{g("url") or ""} {g("content") or ""}'))
    if name == 'kb_update_note':
        return update_note(g('iteration'), g('id'), bool(g('delete')), 内容=g('content'), 分类=g('category'),
                           类型=g('kind'), 标题=g('title'), 链接=g('url'), 来自=g('source'))
    if name == 'kb_search':
        return search(g('query'), g('iteration'), g('category'), g('scope') or 'all', g('repo'), g('limit') or 10)
    if name == 'kb_read':
        return read_file(g('path'), g('start') or 1, g('max_lines') or 300)
    if name == 'kb_annotate_image':
        return annotate_image(g('path'), g('description') or '')
    if name == 'kb_add_repo':
        return add_repo(g('path'), g('name'))
    if name == 'kb_link_repo':
        return link_repo(g('iteration'), g('repo'))
    if name == 'kb_reindex':
        return reindex(g('target') or 'all')
    if name == 'kb_dev_package':
        return dev_package(g('iteration')) + take_notices(g('iteration'))
    if name in ('kb_dev_prepare', 'kb_sdd_prepare'):
        return dev_prepare(g('iteration'), g('repo') or '', g('store') or '')
    if name == 'kb_base':
        return base_list(g('query') or '', g('category') or '')
    if name == 'kb_base_save':
        return base_save(g('id') or '', g('category') or '', g('name'), g('fields'), g('scope'), g('note'),
                         g('file') or '', bool(g('delete')))
    if name == 'kb_base_secret':
        return base_secret(g('id'), g('field'), purpose=g('purpose') or '')
    if name == 'kb_ask':
        return ask(g('iteration'), g('question'), g('context') or '', g('options'), g('recommend') or '',
                   g('files'), g('stage') or '')
    if name == 'kb_wait_answer':
        return wait_answer(g('iteration'), g('id'), g('timeout') or 240) + take_notices(g('iteration'))
    if name == 'kb_devices':
        return devices_text(g('iteration'))
    if name == 'kb_device_claim':
        return device_claim(g('iteration'), g('count') or 1, g('serials'), g('reason') or '')
    if name == 'kb_device_release':
        return device_release(g('iteration'), g('serials'))
    if name == 'kb_issue':
        return add_issue(g('iteration'), g('title'), g('detail') or '', g('kind') or '', g('need') or '')
    if name == 'kb_test_report':
        return test_report(g('iteration'), g('summary'), g('passed'), g('failed'), g('blocked'), g('need') or '')
    if name == 'kb_set_dnd':
        return set_dnd(g('iteration'), bool(g('on')), by='Claude（用户要求）')
    if name == 'kb_set_status':
        return set_status(g('iteration'), g('status'), g('note') or '', by_human=False)
    if name == 'kb_log':
        return add_log(g('iteration'), g('note') or '') + take_notices(g('iteration'))
    if name == 'kb_fetch_url':
        return fetch_url(g('url'), g('start') or 0)
    if name == 'kb_create_task':
        return create_task(g('name'), g('summary') or '', g('kind') or '', g('source') or '', g('priority') or '', g('bugs'))
    if name == 'kb_anr_add':
        return anr_add(g('paths') or [], g('version') or '', g('source') or '', g('task') or '', g('count') or 1)
    if name == 'kb_anr':
        return anr_show(g('id')) if g('id') else anr_list(g('query') or '', g('task') or '')
    if name == 'kb_anr_mapping':
        return anr_mapping(g('version'), g('path'))
    if name == 'kb_builds':
        return builds_text(g('iteration'), int(g('count') or 5))
    if name == 'kb_plugin_call':
        return call_plugin(g('plugin') or '', g('args') or [], g('iteration') or '')
    if name == 'kb_anr_link':
        out = []
        if g('version'):
            out.append(anr_set_version(g('id'), g('version')))
        if g('task') is not None or g('note') is not None:
            out.append(anr_link(g('id'), g('task'), None, g('note'), by='Claude'))
        return '\n'.join(out) or '没有要改的'
    if name == 'kb_bugs':
        return bug_list(g('iteration') or '', g('owner') or '', g('status') or '未关闭', g('query') or '')
    if name in ('kb_bug_get', 'kb_bug_get'):
        return bug_get(str(g('id')))
    if name == 'kb_bug_assign':
        return bug_assign(str(g('id')), g('target') or '', by='Claude')
    if name == 'kb_bug_analysis':
        return bug_analysis(str(g('id')), g('summary') or '', g('locations'), g('cause') or '', g('fix') or '', g('impact') or '',
                            g('selftest') or '', g('confidence') or '', g('missing') or '')
    if name == 'kb_bug_fixed':
        return bug_fixed(str(g('id')), g('done') is not False, g('commits'), g('note') or '')
    if name in ('kb_bug_sync', 'kb_zentao_sync'):
        return bug_sync(by='Claude', only=g('source') or '')
    if name == 'kb_fix_link':
        return fix_link(g('iteration'), g('old'), g('new'), g('reason') or '')
    if name == 'kb_refresh_sources':
        return refresh_sources(g('iteration'), g('sid') or '')
    if name == 'kb_import_design':
        return import_design(g('iteration'), g('url'), g('item') or '', g('summary') or '')
    if name == 'kb_import_url':
        return import_url(g('iteration'), g('url'), g('category'), g('item') or '', g('summary') or '',
                          g('content') or '', g('attachments'), g('filename') or '')
    raise KBError(f'未知工具：{name}')


def serve():
    init()
    tools = [{'name': n, 'description': d, 'inputSchema': {**s, 'required': r}} for n, d, s, r in TOOLS]

    def send(obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + '\n')
        sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        mid, method = msg.get('id'), msg.get('method')
        if mid is None:
            continue
        params = msg.get('params') or {}
        if method == 'initialize':
            res = {'protocolVersion': params.get('protocolVersion', '2025-06-18'),
                   'capabilities': {'tools': {}}, 'serverInfo': {'name': 'kb', 'version': '1.0.0'},
                   'instructions': INSTRUCTIONS}
        elif method == 'tools/list':
            res = {'tools': tools}
        elif method == 'tools/call':
            try:
                text, err = call_tool(params.get('name'), params.get('arguments') or {}), False
            except KBError as e:
                text, err = str(e), True
            except Exception as e:
                text, err = f'内部错误：{e!r}', True
            res = {'content': [{'type': 'text', 'text': text}], 'isError': err}
        elif method == 'ping':
            res = {}
        else:
            send({'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': f'未实现：{method}'}})
            continue
        send({'jsonrpc': '2.0', 'id': mid, 'result': res})
