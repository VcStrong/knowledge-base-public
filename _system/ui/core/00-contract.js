// From 大大王.DT
/* ============================================================================================
 * 知识库网页的共用功能层（core.js + core.css）。经典版（/_system/web.html）和每套界面模板都用它：
 * 功能只在这里实现一次，模板只负责整站骨架、导航方式、首页和视觉。普通脚本（不是模块），加载后有全局 KB。
 *
 * ── 模板开发契约 ──────────────────────────────────────────────────────────────────────────────
 * 【目录】_system/ui/<目录>/：index.html（整站页面）、app.js（骨架 / 导航 / 首页）、skin.css（皮肤）。
 *   目录名：指挥台=command 团队=team 画布=canvas 简报=brief 静默=calm。每套模板目录里放 template.json（名称、说明、顺序），程序扫描 ui/ 自动发现（kblib/steward/brief.py 的 ui_templates），加模板不用改代码。
 *   服务器：GET / 按设置里的「界面模板」给 ui/<目录>/index.html（文件不在就给经典 web.html）；/?ui=<目录或模板名> 临时指定、不改设置，
 *   /?ui=classic 临时看经典版。静态文件走 GET /ui/<路径>（只限 _system/ui/ 下，js/css/html/json/svg/png/jpg/webp/woff2/ico）。
 * 【index.html 写法】
 *   <link rel="stylesheet" href="/ui/core.css"> 之后再 <link href="/ui/<目录>/skin.css">（皮肤覆盖组件样式）；
 *   <body> 末尾依次：<script src="/ui-templates.js">（KBUI，首页模板渲染器，可选）、<script src="/ui/core.js">、<script src="/ui/<目录>/app.js">。
 *   core.js 必须在 <body> 末尾（加载时要往 body 注入公共 DOM）。
 * 【启动】core 在 DOMContentLoaded 时自动 KB.start()（此时模板 app.js 已执行完）。app.js 里同步做好：
 *   KB.setApp(容器)；按需 KB.hooks.nav / KB.hooks.afterRender / KB.pages.home / KB.routes。
 *   要先异步准备（比如等数据再画骨架）就在 app.js 里设 KB.manualStart=true，准备好后自己调 KB.start()（重复调用无害）。
 *   start 做的事：经典侧栏分组折叠（没有 .side 就跳过）→ 绑搜索框 / 添加按钮（有才绑）→ 监听 hashchange → render() → navRefresh() → 连 SSE。
 *
 * 【KB 成员】
 *   KB.app                    当前页面容器（只读）；KB.setApp(el 或选择器)：页面渲染目标。经典版默认 #app，模板必须设。
 *   KB.pages                  各页面，都是 async，往 KB.app 里写 innerHTML 并绑定事件（可以替换某个页面，route 会调替换后的）：
 *     home()                  首页（#/）：默认 = 设置里的模板是「经典」时画经典总览，否则用 KBUI 画对应模板的首页（数据 /api/brief）。模板一般替换成自己的
 *     overview()              经典总览（#/classic）：管家卡片、工作统计、期卡片网格（筛选 / 加到侧栏）、新手引导、最近添加
 *     brief(模板名)           用 KBUI 画某套模板的首页（/api/brief，6 秒看一次有变化才重画），带「经典总览 / 换界面」链接
 *     period(名称)            期 / 事项详情（#/p/<名称>）：步骤条 + 下一步、会话框（talk）、标签页或整页视图：开发（开发面板 / 待确认 / 问题 / 复测）、
 *                             资料（需求 / 设计图 / 接口 / 其他，上传、文字资料、来源核对）、全栈（选仓库 / 出方案 / 拍板 / 开工 / 验收）、构建、Bug、记录；
 *                             事项（Bug / ANR / 插件来源）显示事项信息、推送、备忘；状态切换、更正链接、删除
 *     bugs()                  Bug（#/bugs）：多平台同步、归属筛选、只读分析 / 审核、修复队列、忽略、列配置
 *     anr()                   ANR / 崩溃（#/anr）：按堆栈归并、批次、mapping 还原、建事项、手动导入
 *     phones()                手机（#/phones）：设备列表、占用 / 释放
 *     base()                  基础信息（#/base）：条目卡片、增删改（机密字段）
 *     settings()              设置（#/settings）：界面模板（预览 / 切换）、AI 引擎、开发流程、管家、规矩、插件、命令、高级
 *     docs(名称)              文档（#/d/<名称>，空 = 第一份）：左侧文档列表 + 目录，右侧 Markdown
 *     tool(插件id)            工具插件页（#/tool/<id>）：输入解析、候选、关联的事项列表
 *     search(词, 范围)        搜索结果（#/s/<词>\u0001<all|docs|code>）
 *   KB.routes                 自定义路由 {'/inbox': fn(hash), '/x/': fn(后缀)}：以 / 结尾的按前缀匹配（参数是去掉前缀的部分），否则全等；优先于内置路由
 *   KB.route(hash?)           按 hash（'#/bugs' 或 '/bugs'，省略 = 当前）调页面；KB.render()：route 当前 hash + 刷导航高亮 + afterRender
 *   KB.softRender()           不打断输入地重画当前页（有草稿 / 对话框开着 / 焦点在输入框时推迟）；KB.canRender()：现在能不能重画
 *   KB.curHash()              当前路由（已解码，如 '/p/某期'）
 *   KB.navRefresh()           重新拉导航数据并调 hooks.nav
 *   KB.hooks.nav(d, site)     设了就由模板画导航（不再画经典侧栏）。site 为 null：只是换了页面，更新高亮就行（每次 render 后都调）；
 *                             site 有值：导航数据变了（启动、SSE overview 事件、侧栏增删）——site 是 /api/site 的结果，d 是 /api/overview 的原始结果。
 *   KB.hooks.afterRender(h)   每次页面画完调（h = curHash()），模板做标题、面包屑、动画等
 *   KB.on(kind, fn)           订阅实时事件（SSE），返回取消函数。kind：overview（总体数据变了）、page（某期页面内容变了，ev.period）、
 *                             dev（某期开发进度，ev.period）、adds（最近添加）、live（连接状态 ev.on）、*（全部）。core 自己已按事件刷新当前页和导航。
 *   KB.api(url, opt)          fetch + JSON，出错抛 Error（e.need = 需要补的信息），401 跳登录；KB.post(url, body)：POST JSON
 *   KB.esc(s) KB.enc(s)       HTML 转义 / encodeURIComponent
 *   KB.toast(文字)            右下角提示；KB.openDlg(标题, html)：全局对话框（#dlg）；KB.md(markdown) → {html, toc}；KB.mdInline(文字)
 *   KB.badge(状态)            状态徽章 html；KB.fileUrl(路径)；KB.readFile(路径)：对话框里看文件；KB.showImg(路径)
 *   KB.since(时间) KB.when(秒) KB.size(字节)   「3 分钟」/ 日期 / 「1.2 MB」
 *   KB.askOpen(true|false)    打开 / 收起「交给管家」面板；KB.addDlg(tab)：手动新建对话框（tab: 'new' 新期 / 'task' 事项 / 'add' 添加）
 *   KB.taskNav(名称, 显示)    把期 / 事项加到或移出侧栏
 *   KB.site()                 GET /api/site（见下）；KB.template()：当前界面模板名（?ui= 优先）；KB.setTemplate(名称)：存设置并重新加载整站（'经典' = 换回经典）
 *   KB.logout()               退出登录（KB.auth 为 true 时才有意义）
 *   KB.periods / KB.entries / KB.periodNames / KB.taskNames / KB.auth   导航数据（只读，来自 /api/overview）；KB.ORDER 状态顺序；KB.DOT 状态颜色
 *
 * 【/api/site】{期:[{名称, 状态, 事项, 事项类型, 优先级, 说明, 更新时间, 待确认, 问题, 没解决Bug, Bug, 在跑, 免打扰, 侧栏隐藏, 插件,
 *   批次:{来源 anr|bug|'', 总数, 已处理, 待确认, 侧栏}|null, 链接, （期才有）流程, 步骤:[{名称, 状态 done|cur|todo}], 当前步骤, 下一步:{文字, 说明, 谁, 按钮, 去}}],
 *   待你, 在跑, Bug:{未关闭, 待归纳, 链接}, ANR:{待处理, 总数, 链接}, 手机:{空闲, 总数, 链接}|null（本机没 adb）, 基础信息:{条数, 链接},
 *   工具:[{id, 名称, 图标, 说明, 提示, 待解决, 待确认, 链接}], 文档:[{名称, 链接}], 导航:[{名称, 图标, 链接, 数?, 提示?}]（经典侧栏的固定入口，按顺序）,
 *   界面模板:{名称, 目录, 列表:[{名称, 说明, 目录}]}, 登录}。?full=1 时多一个 overview（/api/overview 原样）。
 *   「下一步.去」是 tab:mat / tab:dev / tab:stack：跳到期页面对应板块就用 '#/p/<名称>'，页面会按步骤自动选。
 *
 * 【DOM 约定】
 *   core 自动注入（页面上没有才注入，模板可以自己写同 id 的元素来换位置，但内部结构要一致）：
 *     #dlg（<dialog>，内含 #dlgT 标题、#dlgB 内容）、#toast、#askFab（交给管家浮动按钮）、#askPanel（面板，内含 #askSt #askNewP #askClr #askX
 *     #askLog #askFiles #askFile #askIn #askGo）。不想要浮动按钮：skin.css 里 #askFab{display:none!important}，自己的按钮调 KB.askOpen(true)。
 *   可选（有就用，没有不报错）：搜索表单 #sf（内含 #q 输入框、#scope 范围 select，可省）、#addBtn（点了打开管家）、#live（实时连接小圆点，class live / live on）。
 *   经典侧栏专用（模板不用）：.side .navh .nav #navPs #navBugTs #navAnrTs #navTs #navEnt #navPh #navBug #navAnr #hostName #logout。
 *   页面内部会用很多短 id（#tkN #nN #bF #pushBox #sessBar #briefView #adList #tRes …）和 data-* 属性：模板自己的元素一律用 tpl 前缀的 id / class，别重名。
 *   页面滚动：softRender 恢复的是 window 的滚动位置，模板最好让 window 滚动（不要把内容区做成内部滚动容器）。
 *
 * 【CSS（core.css）】
 *   主题变量（:root，含深色 prefers-color-scheme 和 :root[data-theme=dark|light]）：--bg --fg --mut --card --line --soft --acc --accb
 *     --s0..--s4 / --s0b..--s4b（状态色：灰 / 橙 / 蓝 / 绿 / 红）--warn --info --infob --shadow --f-body --f-mono（--side* 只给经典侧栏）。皮肤改变量最省事。
 *   基础：body h1 h2 a input select textarea button(.pri .danger) table th td dialog(.mini) code .mono .mut .small .row .tw .form .sw（开关）
 *   通用组件：.badge .st-<状态>（收集中 / 已批准开发 / 开发中 / 已完成 / 已暂停 / 已暂停2）.chip .chips .card2 .cat(.hd .bd) .bcard .bcards .bgrid
 *     .notice .q（待回答问题）.iss（问题）.note（文字资料）.toast .live .drop（拖放区）.files .grid .thumb .hit（搜索结果）.md（Markdown）
 *     .pagehead .crumb .pmeta .kpis .kpi .stats .stat .fchips .fchip .combo(.dd .ddi) .legend .pbar .prog .pst
 *   期页面：.steps .step(.done .cur) .gnext(.who .tx) .ptabs .ptab .pview .pwhole .psec .matgrid .two .stack .layout .dev .talk .chat .act .raw .cand
 *     .retest .devrow .arec .pushin .issbox .tl .sess .tool
 *   总览 / 管家 / 统计：.pgrid .pcard2(.cover .pb .pf .meta .sum) .navtg .onb .stw .stcards .stc .prop .wstat .scards .scard .sprog .sprow .sbar .board .col .pcard
 *   其他页：.docs .dnav .toc（文档，.dnav 的 sticky top 按经典顶栏 64px 算）.phone(.free .mine .busy .pi)（手机）.frow .sec（基础信息）
 *   交给管家：#askFab #askPanel（.aq 问 .aa 答 .prop 推动卡片 .ft 输入区）
 *   模板 skin.css 可以覆盖以上任何类；经典骨架（.app .side .mainc .topbar main）在 web.html 里，不在 core.css。
 * ============================================================================================ */