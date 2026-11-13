// From 大大王.DT
/* 界面模板「团队」：整个网站是一间 AI 团队办公室。
 *  - 顶部：品牌 + 五个空间（团队 / 项目 / 问题 / 资料 / 设置）+ 搜索 + 交给管家；下面一条团队栏，每个 AI 角色一个头像，带实时状态
 *    （在做什么 / 空闲 / 需要你判断），点头像在右侧抽屉里看它的工作流和它提出的判断。
 *  - 空间下面是分段导航（当前空间里的几个页面），再下面是内容。
 *  - 首页 = 团队墙：阶段条（收集资料 → 方案拍板 → 并行开发 → 验收上线 → 线上维护，按当前这一期调整重点）、管家的话、
 *    每个在工作的 AI 一张卡（实时滚动最近几步）、需要你判断的事（AI 建议 + 理由 + 把握）、项目房间。
 *  - 自己加的路由：#/projects（项目房间列表）、#/issues（Bug + ANR 按 AI 分析进展分组）、#/library（资料概览）。
 *  - 期 / 事项详情由 core 渲染，afterRender 把页头、步骤、下一步收进「房间头」，并加上在场 AI 和各端「成员卡」。
 *  - /api/brief 每 5 秒看一次，有变化才重画（KB.canRender() 为假 = 正在输入 / 对话框开着时不刷新）。
 * 只用 core 契约里的东西；页面功能全部交给 core。
 */
(function () {
  'use strict';
  const { esc, enc } = KB;
  const $ = s => document.querySelector(s);
  const DEMO = new URLSearchParams(location.search).has('tpldemo');   // ?tpldemo=1：塞几条演示活动，只用来看「工作中」的样子

  // ---------------------------------------------------------------- 团队成员（角色、颜色、头像字、职责、哪个阶段是主角）
  const ROLES = [
    { k: '管家', c: '#7c3aed', g: '管', d: '接收你交来的东西、归档、按规矩推动下一步，每天写日报' },
    { k: '方案', c: '#8b5cf6', g: '方', d: '读资料、设计稿和代码，出需求规格、设计对照、影响分析和接口契约' },
    { k: '开发', c: '#2f6fed', g: '开', d: '单端 / 事项的开发会话：定位、改代码、自测、写结论' },
    { k: '服务端', c: '#0ea5e9', g: '服', d: '按拍板的契约开发服务端，做完交给审查' },
    { k: 'Web', c: '#06b6d4', g: 'W', d: '按契约开发 Web 端，做完交给审查' },
    { k: 'Android', c: '#16a34a', g: 'A', d: '按契约开发 Android，接口没好时先按契约 mock' },
    { k: 'iOS', c: '#64748b', g: 'i', d: '按契约开发 iOS，接口没好时先按契约 mock' },
    { k: '鸿蒙', c: '#e11d48', g: '鸿', d: '按契约开发鸿蒙端，做完交给审查' },
    { k: '审查', c: '#f59e0b', g: '审', d: '用独立会话对照需求、契约和设计挑错，汇总证据包' },
    { k: 'Bug 分析', c: '#ef4444', g: 'B', d: '只读分析 Bug 和 ANR：拉原文、对照代码，给出位置和修复思路' },
    { k: 'Bug 修复', c: '#dc2626', g: '修', d: '修复审核通过的 Bug，改动只在开发分支', opt: true },
    { k: '整理', c: '#14b8a6', g: '整', d: '按来源网址检查更新，把新原文整理进资料' }
  ];
  const RM = Object.fromEntries(ROLES.map(r => [r.k, r]));
  const roleOf = k => RM[k] || { k, c: '#64748b', g: String(k || '?')[0], d: '' };
  const ENDS = ['服务端', 'Web', 'Android', 'iOS', '鸿蒙'];

  // 五个阶段，以及每个阶段谁是主角、首页说什么
  const STAGES = [
    { k: 'collect', t: '收集资料', lead: ['整理', '管家', '方案'], tx: '在收集资料：整理 AI 读需求、找缺口，资料够了就交给方案 AI。' },
    { k: 'plan', t: '方案拍板', lead: ['方案', '审查'], tx: '在出方案：方案 AI 读资料和代码写契约，拍板这一步需要你判断。' },
    { k: 'dev', t: '并行开发', lead: ['服务端', 'Web', 'Android', 'iOS', '鸿蒙', '开发', '审查'], tx: '各端并行开发：每个端一个 AI，审查 AI 跟在后面挑错。' },
    { k: 'accept', t: '验收上线', lead: ['审查'], tx: '在验收：审查 AI 汇总证据包，上不上线需要你判断。' },
    { k: 'online', t: '线上维护', lead: ['Bug 分析', 'Bug 修复', '开发'], tx: '线上维护：Bug 分析 AI 盯着新 Bug 和 ANR，有结论再来找你。' }
  ];
  const SI = k => Math.max(0, STAGES.findIndex(s => s.k === k));
  function stageOfPeriod(p) {
    if (!p) return 'online';
    if (p['状态'] === '已完成') return 'online';
    if (p['事项']) return /ANR|崩溃|Bug/i.test(p['事项类型'] || '') || (p['批次'] || {})['来源'] ? 'online' : 'dev';
    const s = p['当前步骤'] || '';
    if (s === '资料') return 'collect';
    if (['选仓库', '出方案', '拍板', '开始开发'].includes(s)) return 'plan';
    if (['开发', '开发中'].includes(s)) return 'dev';
    if (['验收', '完成'].includes(s)) return 'accept';
    return (p['步骤'] || []).length ? 'online' : 'dev';
  }

  // ---------------------------------------------------------------- 状态
  const S = { site: null, brief: null, sig: '', drawer: '', stack: {}, timer: null };
  const P = n => ((S.site || {})['期'] || []).find(p => p['名称'] === n);
  const periods = () => ((S.site || {})['期'] || []);
  async function ensureSite() { if (!S.site) { try { S.site = await KB.api('/api/site') } catch (_) { S.site = { '期': [] } } } return S.site }

  // 判断归到哪个 AI 名下（id 前缀来自 kblib/steward.py 和 brief.py）
  function judgRole(j) {
    const id = j.id || '';
    if (id.startsWith('chat:')) return (j['提议'] || {})['类型'] === 'Bug分析' ? 'Bug 分析' : '开发';
    if (/^(planfail|approve):/.test(id)) return '方案';
    if (/^accept:/.test(id)) return '审查';
    if (/^(ask:bug|bug-|anr)/.test(id)) return 'Bug 分析';
    if (/^(ask|push):/.test(id)) return '开发';
    if (/^src-left:/.test(id)) return '整理';
    return '管家';
  }
  const isAsk = j => j['类型'] === '问你' || j['类型'] === '待你';
  const B = () => S.brief || { '判断': [], '活动': [], '状态': {}, '指标': [], '进行中': [], '其他': [] };
  function roleState(k) {
    const b = B(), acts = (b['活动'] || []).filter(a => a['角色'] === k), js = (b['判断'] || []).filter(j => judgRole(j) === k);
    const asks = js.filter(isAsk), sugs = js.filter(j => !isAsk(j));
    const st = asks.length || acts.some(a => a['等你']) ? 'ask' : acts.length ? 'work' : 'idle';
    const a0 = acts.find(a => !a['等你']) || acts[0];
    const text = st === 'ask' ? '需要你判断' : st === 'work' ? `${a0['状态']} · ${a0['对象']}` : sugs.length ? `有 ${sugs.length} 条建议` : '空闲';
    return { st, acts, asks, sugs, text };
  }
  const av = (k, cls = '') => { const r = roleOf(k); return `<span class="tpl-av ${cls}" style="--rc:${esc(r.c)}" title="${esc(r.k)}" aria-hidden="true">${esc(r.g)}</span>` };
  const conf = p => p == null ? '' : `<span class="tpl-conf" title="AI 的把握">把握<span class="m"><i style="width:${+p}%"></i></span>${+p}%</span>`;
  const short = (s, n) => { s = String(s || ''); return s.length > n ? s.slice(0, n - 1) + '…' : s };

  // ---------------------------------------------------------------- 数据：/api/brief（加演示活动时只改本地副本）
  function demoActs(b) {
    const f = (b['关系'] || {})['标题'] || (periods().find(p => !p['事项']) || {})['名称'] || '示例';
    const t = m => { const d = new Date(Date.now() - m * 60000); return d.toISOString().slice(0, 10) + ' ' + d.toTimeString().slice(0, 5) };
    return [
      { id: 'demo1', 角色: '方案', 颜色: '#8b5cf6', 对象: f, 状态: '出方案中', 链接: '#/p/' + f, 等你: false, 开始: t(12), 步骤: ['Read 需求/PRD-连续签到.md', 'Grep "SignIn" server/app', '读 android/app/sign/SignActivity.kt', '写接口契约：签到、补签、奖励 3 个', '设计对照：缺「断签」空态'] },
      { id: 'demo2', 角色: 'Android', 颜色: '#16a34a', 对象: f, 状态: '开发中 · 第 1 轮', 链接: '#/p/' + f, 等你: false, 开始: t(31), 步骤: ['Edit SignAdapter.kt +88', 'Edit SignViewModel.kt +41', './gradlew assembleDebug', '编译通过', '按契约 mock /sign/reward'] },
      { id: 'demo3', 角色: '审查', 颜色: '#f59e0b', 对象: f + ' · 服务端', 状态: '审查中', 链接: '#/p/' + f, 等你: false, 开始: t(4), 步骤: ['对照需求 R1–R4', '读 sign_api.py diff', '服务端：0 个高优问题'] },
      { id: 'demo4', 角色: 'Bug 分析', 颜色: '#ef4444', 对象: 'ANR OtherApp.onCreate', 状态: '只读分析中', 链接: '#/issues', 等你: false, 开始: t(7), 步骤: ['归并 1 次上报', '堆栈：ZaloSDKApplication.wrap', '主线程初始化三方 SDK', '对照 OtherApp.java:685'] }
    ];
  }
  async function loadBrief() {
    let b; try { b = await KB.api('/api/brief') } catch (_) { return false }
    if (DEMO) { b['活动'] = demoActs(b).concat(b['活动'] || []); b['状态']['在工作'] = (b['状态']['在工作'] || 0) + 4 }
    const sig = JSON.stringify(b).replace(/"时间":"[^"]*"/, '');
    S.brief = b; if (sig === S.sig) return false; S.sig = sig; return true;
  }
  // 判断按钮：和 core 首页一样走 /api/brief/act
  const jOpts = {
    act: async (id, action, x) => { try { KB.toast((await KB.post('/api/brief/act', { id, action, ...x })).msg.split('\n')[0]) } catch (e) { KB.toast(e.message) } S.sig = ''; await refresh(true) },
    ask: async text => { try { await KB.post('/api/chat/ask', { text, page: '/' + KB.curHash() }); KB.askOpen(true) } catch (e) { KB.toast(e.message) } },
    preview: text => KB.api('/api/intake/preview?text=' + enc(text)), openAsk: () => KB.askOpen(true)
  };
  const bindJ = root => { if (window.KBUI && root) KBUI.bind(root, B(), jOpts) };
  const judgHtml = (j, opt) => window.KBUI ? KBUI.judg(j, opt) : `<div class="jd"><b>${esc(j['问题'])}</b> <a href="${esc(j['链接'] || '#/')}">去看看</a></div>`;
  function decHtml(j) {
    const k = judgRole(j);
    return `<div class="tpl-dec" id="tpl-j-${(B()['判断'] || []).indexOf(j)}" style="--rc:${esc(roleOf(k).c)}">
      <div class="tpl-dec-who">${av(k, 'sm')}<b>${esc(k)}</b><span>${isAsk(j) ? (j['类型'] === '问你' ? '想问你' : '提出一个判断') : '有个建议'}</span>${j['链接'] ? `<a class="tpl-dec-go" href="${esc(j['链接'])}">看依据 →</a>` : ''}</div>${judgHtml(j)}</div>`;
  }

  // ---------------------------------------------------------------- 顶部：空间、团队栏、分段导航
  const SPACES = [{ k: 'team', t: '团队', h: '#/' }, { k: 'proj', t: '项目', h: '#/projects' }, { k: 'issue', t: '问题', h: '#/issues' }, { k: 'lib', t: '资料', h: '#/library' }, { k: 'set', t: '设置', h: '#/settings' }];
  const issueTask = p => p && p['事项'] && (/ANR|崩溃|Bug/i.test(p['事项类型'] || '') || ['anr', 'bug'].includes((p['批次'] || {})['来源']));
  function spaceOf(h) {
    if (h === '/' || h === '/classic') return 'team';
    if (h === '/projects') return 'proj';
    if (h.startsWith('/p/')) { const p = P(h.slice(3)); if (p && (p['插件'] || []).length) return 'lib'; return issueTask(p) ? 'issue' : 'proj' }
    if (['/issues', '/bugs', '/anr'].includes(h)) return 'issue';
    if (h === '/settings') return 'set';
    return 'lib';
  }
  function paintSpaces() {
    const s = S.site || {}, sp = spaceOf(KB.curHash()), js = (B()['判断'] || []).filter(isAsk);
    const askIn = { team: js.length, proj: js.filter(j => /^#\/p\//.test(j['链接'] || '') && !issueTask(P((j['链接'] || '').slice(4)))).length, issue: js.filter(j => ['Bug 分析', 'Bug 修复'].includes(judgRole(j))).length };
    const live = periods().filter(p => !p['事项'] && p['状态'] !== '已完成' && p['状态'] !== '已暂停').length;
    const n = { proj: live, issue: ((s['Bug'] || {})['待归纳'] || 0) + ((s['ANR'] || {})['待处理'] || 0), lib: ((s['基础信息'] || {})['条数'] || 0) };
    $('#tplSpaces').innerHTML = SPACES.map(x => `<a class="tpl-space ${x.k === sp ? 'on' : ''}" href="${x.h}"${x.k === sp ? ' aria-current="page"' : ''}>${x.t}${askIn[x.k] && x.k !== 'team' ? `<i class="tpl-askdot" title="${askIn[x.k]} 件需要你判断"></i>` : ''}${n[x.k] ? `<span class="tpl-cnt">${n[x.k]}</span>` : ''}</a>`).join('');
    paintSub(sp);
  }
  function paintSub(sp) {
    const s = S.site || {}, h = KB.curHash(), items = [];
    if (sp === 'team') items.push(['团队墙', '#/'], ['经典总览', '#/classic']);
    if (sp === 'proj') {
      items.push(['全部房间', '#/projects']);
      periods().filter(p => !p['事项'] && p['状态'] !== '已完成').forEach(p => items.push([p['名称'], '#/p/' + p['名称'], p['待确认'], p['在跑']]));
      periods().filter(p => p['事项'] && !issueTask(p) && !(p['插件'] || []).length && p['状态'] !== '已完成').forEach(p => items.push([p['名称'], '#/p/' + p['名称'], p['待确认'], p['在跑']]));
      if (h.startsWith('/p/') && !items.some(x => x[1] === '#' + h)) items.push([h.slice(3), '#' + h]);
    }
    if (sp === 'issue') {
      items.push(['按 AI 进展', '#/issues'], ['Bug 平台', '#/bugs', (s['Bug'] || {})['待归纳']], ['ANR / 崩溃', '#/anr', (s['ANR'] || {})['待处理']]);
      periods().filter(p => issueTask(p) && p['状态'] !== '已完成').forEach(p => items.push([p['名称'], '#/p/' + p['名称'], p['待确认'], p['在跑']]));
      if (h.startsWith('/p/') && !items.some(x => x[1] === '#' + h)) items.push([h.slice(3), '#' + h]);
    }
    if (sp === 'lib') {
      items.push(['概览', '#/library'], ['基础信息', '#/base', (s['基础信息'] || {})['条数']], ['文档', '#/d/']);
      if (s['手机']) items.push(['手机', '#/phones', `${s['手机']['空闲']}/${s['手机']['总数']}`]);
      (s['工具'] || []).forEach(t => items.push([`${t['图标']} ${t['名称']}`, t['链接'], t['待确认'] || t['待解决']]));
      if (h.startsWith('/s/')) items.push(['搜索：' + short(h.slice(3).split('\u0001')[0], 16), '#' + h]);
      if (h.startsWith('/p/') && !items.some(x => x[1] === '#' + h)) items.push([h.slice(3), '#' + h]);
    }
    if (sp === 'set') items.push(['设置', '#/settings'], ['临时看经典版', '/?ui=classic' + location.hash]);
    const on = x => x === '#' + h || (x === '#/d/' && h.startsWith('/d/')) || (x === '#/' && h === '/');
    $('#tplSub').innerHTML = `<div class="tpl-sub-in">${items.map(([t, l, c, run]) => `<a class="tpl-seg ${on(l) ? 'on' : ''}" href="${esc(l)}">${run ? '<i class="tpl-livedot" title="AI 在这里工作"></i>' : ''}${esc(t)}${c ? `<span class="tpl-cnt">${esc(c)}</span>` : ''}</a>`).join('')}
      ${sp === 'proj' ? '<button type="button" class="tpl-seg tpl-seg-add" data-tpladd="new">＋ 新建一期</button><button type="button" class="tpl-seg tpl-seg-add" data-tpladd="task">＋ 事项</button>' : ''}</div>`;
    $('#tplSub').querySelectorAll('[data-tpladd]').forEach(b => b.onclick = () => KB.addDlg(b.dataset.tpladd));
  }
  function paintCrew() {
    const b = B(), act = new Set((b['活动'] || []).map(a => a['角色']));
    const list = ROLES.filter(r => !r.opt || act.has(r.k)).concat([...act].filter(k => !RM[k]).map(roleOf));
    const st = list.map(r => [r, roleState(r.k)]), w = st.filter(x => x[1].st === 'work').length, a = st.filter(x => x[1].st === 'ask').length;
    $('#tplCrew').innerHTML = `<div class="tpl-crew-in"><div class="tpl-crew-sum"><b>团队</b><span>${w ? `<i class="tpl-livedot"></i>${w} 在工作` : '都在待命'}</span>${a ? `<span class="tpl-ask-t">${a} 需要你判断</span>` : ''}</div>
      <div class="tpl-crew-list">${st.map(([r, x]) => `<button type="button" class="tpl-mate s-${x.st} ${S.drawer === r.k ? 'on' : ''}" data-role="${esc(r.k)}" title="${esc(r.k)}：${esc(x.text)}">
        <span class="tpl-av" style="--rc:${esc(r.c)}">${esc(r.g)}<i class="tpl-dot"></i></span><span class="tpl-mate-t"><b>${esc(r.k)}</b><small>${esc(short(x.text, 18))}</small></span></button>`).join('')}</div></div>`;
    $('#tplCrew').querySelectorAll('[data-role]').forEach(x => x.onclick = () => openRole(x.dataset.role));
  }

  // ---------------------------------------------------------------- 抽屉：某个 AI 的工作流
  function openRole(k) {
    S.drawer = k; paintDrawer(); $('#tplDrawer').hidden = false; $('#tplScrim').hidden = false;
    document.body.classList.add('tpl-drawer-open'); paintCrew();
    setTimeout(() => { const x = $('#tplDrawer .tpl-dr-x'); if (x) x.focus() }, 30);
  }
  function closeRole() { if (!S.drawer) return; S.drawer = ''; $('#tplDrawer').hidden = true; $('#tplScrim').hidden = true; document.body.classList.remove('tpl-drawer-open'); paintCrew() }
  function feed(steps, live) { return (steps || []).length ? `<ol class="tpl-feed">${steps.map((s, i) => `<li class="${i === steps.length - 1 && live ? 'now' : ''}">${esc(s)}</li>`).join('')}</ol>` : '<div class="tpl-mut">还没有步骤记录</div>' }
  function paintDrawer() {
    const k = S.drawer; if (!k) return;
    const r = roleOf(k), x = roleState(k), b = B();
    const where = {
      '管家': [['交给管家的记录', 'ask'], ['管家设置', '#/settings']], '方案': [['项目房间', '#/projects']], '审查': [['项目房间', '#/projects']],
      'Bug 分析': [['问题空间', '#/issues'], ['Bug 平台', '#/bugs'], ['ANR / 崩溃', '#/anr']], 'Bug 修复': [['Bug 平台', '#/bugs']], '整理': [['项目房间', '#/projects']], '开发': [['项目房间', '#/projects']]
    }[k] || [['项目房间', '#/projects']];
    const stw = b['管家'] || {}, set = stw['设置'] || {};
    $('#tplDrawer').innerHTML = `<div class="tpl-dr-hd" style="--rc:${esc(r.c)}">${av(k, 'lg')}<div class="tpl-dr-t"><b>${esc(k)}${k === '管家' ? '' : ' AI'}</b><span class="tpl-state s-${x.st}">${x.st === 'ask' ? '需要你判断' : x.st === 'work' ? '工作中' : '待命'}</span><small>${esc(r.d)}</small></div><button type="button" class="tpl-dr-x" aria-label="关闭">✕</button></div>
      <div class="tpl-dr-bd">
        ${x.acts.length ? `<section><h3>正在做</h3>${x.acts.map(a => `<div class="tpl-dr-act"><div class="tpl-dr-obj">${a['链接'] ? `<a href="${esc(a['链接'])}">${esc(a['对象'])}</a>` : esc(a['对象'])}<span class="tpl-state s-${a['等你'] ? 'ask' : 'work'}">${esc(a['状态'])}</span></div>
            ${a['开始'] ? `<div class="tpl-mut">已运行 <span data-since="${esc(a['开始'])}">${esc(KB.since(a['开始']))}</span></div>` : ''}${feed(a['步骤'], !a['等你'])}</div>`).join('')}</section>`
          : `<section><h3>现在</h3><p class="tpl-mut">${x.asks.length ? '手上的活做到一半，在等你一个判断。' : '空闲，待命中。有活进来会自动开始，这里会实时显示它的每一步。'}</p></section>`}
        ${x.asks.length ? `<section class="kbt"><h3>需要你判断</h3>${x.asks.map(j => `<div class="tpl-dec" style="--rc:${esc(r.c)}">${judgHtml(j)}</div>`).join('')}</section>` : ''}
        ${x.sugs.length ? `<section class="kbt"><h3>它的建议</h3>${x.sugs.map(j => `<div class="tpl-dec soft" style="--rc:${esc(r.c)}">${judgHtml(j, { short: true })}</div>`).join('')}</section>` : ''}
        ${k === '管家' ? `<section><h3>工作方式</h3><div class="tpl-kv"><span>自主度</span><b>${esc(set['自主度'] || '标准')}</b><span>每天最多</span><b>${esc(set['每日上限'] ?? '')} 件</b><span>上次巡视</span><b>${esc(stw['上次'] || '—')}</b><span>今天完成</span><b>${esc((b['状态'] || {})['今天完成'] || 0)} 件</b></div>
          ${(stw['规矩'] || []).length ? `<h3>你定的规矩</h3><ul class="tpl-rules">${stw['规矩'].map(x => `<li>${esc(x['内容'])}<small>${esc(x['时间'] || '')}</small></li>`).join('')}</ul>` : ''}</section>` : ''}
        <section><h3>它的工作在哪</h3><div class="tpl-dr-links">${where.map(([t, l]) => l === 'ask' ? `<button type="button" data-tplask>${esc(t)}</button>` : `<a href="${esc(l)}">${esc(t)} →</a>`).join('')}</div></section>
      </div>`;
    const d = $('#tplDrawer');
    d.querySelector('.tpl-dr-x').onclick = closeRole;
    d.querySelectorAll('a[href^="#"]').forEach(a => a.addEventListener('click', () => setTimeout(closeRole, 0)));
    d.querySelectorAll('[data-tplask]').forEach(x => x.onclick = () => { closeRole(); KB.askOpen(true) });
    bindJ(d);
  }

  // ---------------------------------------------------------------- 首页：团队墙
  function focusPeriod() {
    const g = (B()['关系'] || {})['标题'];
    return (g && P(g)) || periods().filter(p => !p['事项'] && !['已完成', '已暂停'].includes(p['状态'])).sort((a, b) => (b['更新时间'] || '').localeCompare(a['更新时间'] || ''))[0] || null;
  }
  function phaseHtml(p, compact) {
    const sk = stageOfPeriod(p), ci = SI(sk);
    return `<div class="tpl-phase ${compact ? 'compact' : ''}">${compact ? '' : `<div class="tpl-phase-hd"><span>现在的阶段</span>${p ? `<a href="#/p/${enc(p['名称'])}">${esc(p['名称'])}</a>` : '<span class="tpl-mut">没有进行中的期</span>'}</div>`}
      <ol class="tpl-phase-ol">${STAGES.map((s, i) => `<li class="${i < ci ? 'done' : i === ci ? 'cur' : ''}"><i></i><span>${s.t}</span></li>`).join('')}</ol>
      ${compact ? '' : `<p class="tpl-phase-tx">${esc(STAGES[ci].tx)}</p>`}</div>`;
  }
  function presenceOf(name) {
    const b = B(), ks = new Set();
    (b['活动'] || []).forEach(a => { if (a['对象'] === name || String(a['对象']).startsWith(name + ' · ')) ks.add(a['角色']) });
    (b['判断'] || []).filter(isAsk).forEach(j => { if ((j['链接'] || '') === '#/p/' + name) ks.add(judgRole(j)) });
    return [...ks];
  }
  function roomCard(p) {
    const here = presenceOf(p['名称']), sk = stageOfPeriod(p), lead = STAGES[SI(sk)].lead.filter(k => !here.includes(k)).slice(0, 3);
    const nx = p['下一步'] || {}, steps = p['步骤'] || [], b = p['批次'];
    const done = steps.filter(s => s['状态'] === 'done').length;
    return `<a class="tpl-room ${p['在跑'] || here.length ? 'tpl-live' : ''}" href="#/p/${enc(p['名称'])}">
      <div class="tpl-room-hd"><b>${esc(p['名称'])}</b>${KB.badge(p['状态'])}</div>
      ${steps.length ? `<div class="tpl-room-steps" title="${esc(steps.map(s => s['名称']).join(' → '))}">${steps.map(s => `<i class="${s['状态']}"></i>`).join('')}<span>${esc(p['当前步骤'] || '完成')} · ${done}/${steps.length}</span></div>`
        : `<div class="tpl-room-steps"><span>${esc(p['事项类型'] || '事项')}${p['优先级'] ? ' · 优先级 ' + esc(p['优先级']) : ''}${b && b['总数'] ? ` · 已处理 ${b['已处理']}/${b['总数']}` : ''}</span></div>`}
      ${nx['文字'] ? `<div class="tpl-room-next ${nx['谁'] === '你' ? 'you' : 'ai'}"><span>${nx['谁'] === '你' ? '需要你判断' : 'AI 在做'}</span>${esc(nx['文字'])}</div>` : p['说明'] ? `<div class="tpl-room-sum">${esc(short(p['说明'], 60))}</div>` : ''}
      <div class="tpl-room-ft"><span class="tpl-stackav">${here.map(k => av(k, 'xs')).join('')}${lead.map(k => av(k, 'xs ghost')).join('')}</span>
        <span class="tpl-room-n">${here.length ? `${here.length} 个 AI 在场` : '待命'}${p['待确认'] ? ` · <b class="tpl-ask-t">${p['待确认']} 待确认</b>` : ''}${p['没解决Bug'] ? ` · Bug ${p['没解决Bug']}` : ''}</span></div></a>`;
  }
  function wallCard(r, x) {
    const live = x.acts.filter(a => !a['等你']);
    return `<article class="tpl-card s-${x.st}" style="--rc:${esc(r.c)}" data-role="${esc(r.k)}">
      <header>${av(r.k)}<div class="tpl-card-who"><b>${esc(r.k)}</b><small>${esc(x.st === 'idle' ? r.d : x.acts.length ? x.acts.length + ' 项工作' : '等你一个判断')}</small></div><span class="tpl-state s-${x.st}">${x.st === 'ask' ? '需要你判断' : x.st === 'work' ? '工作中' : '待命'}</span></header>
      ${x.acts.slice(0, 2).map(a => `<div class="tpl-card-job"><a class="tpl-obj" href="${esc(a['链接'] || '#/')}">${esc(a['对象'])}</a><span class="tpl-mut">${esc(a['状态'])}${a['开始'] ? ` · <span data-since="${esc(a['开始'])}">${esc(KB.since(a['开始']))}</span>` : ''}</span>${feed((a['步骤'] || []).slice(-5), !a['等你'] && live.includes(a))}</div>`).join('')}
      ${x.asks.map(j => `<a class="tpl-askline" href="#tpl-j-${(B()['判断'] || []).indexOf(j)}"><b>${esc(short(j['问题'], 48))}</b>${j['建议'] ? `<span>建议：${esc(short(j['建议'], 36))}</span>` : ''}${conf(j['把握'])}</a>`).join('')}
      ${x.st === 'idle' ? '<div class="tpl-mut tpl-standby">这个阶段由它接手，有活就开始</div>' : ''}</article>`;
  }
  function homeHtml() {
    const b = B(), s = b['状态'] || {}, p = focusPeriod(), sk = stageOfPeriod(p), lead = STAGES[SI(sk)].lead;
    const js = b['判断'] || [], asks = js.filter(isAsk), sugs = js.filter(j => !isAsk(j));
    const act = new Set((b['活动'] || []).map(a => a['角色']));
    const roster = ROLES.filter(r => !r.opt || act.has(r.k)).concat([...act].filter(k => !RM[k]).map(roleOf)).map(r => [r, roleState(r.k)]);
    const rank = ([r, x]) => (x.st === 'ask' ? 0 : x.st === 'work' ? 1 : 2) * 100 + (lead.includes(r.k) ? lead.indexOf(r.k) : 50);
    const busy = roster.filter(([, x]) => x.st !== 'idle').sort((a, c) => rank(a) - rank(c));
    const standby = roster.filter(([r, x]) => x.st === 'idle' && lead.includes(r.k)).sort((a, c) => rank(a) - rank(c));
    const idle = roster.filter(([r, x]) => x.st === 'idle' && !lead.includes(r.k));
    const n = b['叙述'] || {}, cites = n['引用'] || [];
    const say = esc(n['正文'] || '').replace(/\[(\d+)\]/g, (_, i) => { const c = cites[i - 1]; return c && c['链接'] ? `<a class="tpl-cite" href="${esc(c['链接'])}" title="${esc(c['文字'])}">${i}</a>` : `<span class="tpl-cite" title="${esc(c ? c['文字'] : '')}">${i}</span>` });
    const rooms = periods().filter(x => !x['事项'] && !['已完成'].includes(x['状态'])).sort((a, c) => (c['更新时间'] || '').localeCompare(a['更新时间'] || ''));
    const tasks = periods().filter(x => x['事项'] && x['状态'] !== '已完成' && !(x['插件'] || []).length);
    const ms = b['指标'] || [];
    const spark = v => { if (!v || !v.length) return ''; const mx = Math.max(...v, 1), pts = v.map((y, i) => `${i / Math.max(1, v.length - 1) * 100},${28 - y / mx * 24}`).join(' '); return `<svg viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>` };
    return `<div class="tpl-home tpl-st-${sk}">
      <section class="tpl-hero">
        <div class="tpl-hero-main"><div class="tpl-kicker">团队墙 · ${esc((b['时间'] || '').slice(5))} 更新${DEMO ? ' · <b>演示数据</b>' : ''}</div>
          <h1 class="tpl-h1">${esc(b['问候'] || 'AI 团队')}</h1>
          <div class="tpl-chips"><span class="tpl-chip ${s['在工作'] ? 'g' : ''}">${s['在工作'] ? '<i class="tpl-livedot"></i>' : ''}${s['在工作'] || 0} 个 AI 在工作</span>
            ${asks.length ? `<a class="tpl-chip w" href="#tplDecide">${asks.length} 件需要你判断</a>` : '<span class="tpl-chip">没有要你判断的事</span>'}
            <span class="tpl-chip">今天替你完成 ${s['今天完成'] || 0} 件</span></div></div>
        ${phaseHtml(p)}
      </section>
      ${n['正文'] ? `<div class="tpl-say">${av('管家')}<div class="tpl-bubble"><div class="tpl-bubble-hd"><b>管家</b><span>写给你的进展</span></div><p>${say}</p></div></div>` : ''}
      <section class="tpl-sec"><div class="tpl-sec-hd"><h2>谁在做什么</h2><span class="tpl-mut">${busy.length ? `${busy.length} 位成员手上有活` : '现在没人在跑，阶段主角在待命'}</span></div>
        <div class="tpl-wall">${busy.concat(standby).map(([r, x]) => wallCard(r, x)).join('')}</div>
        ${idle.length ? `<div class="tpl-idle"><span class="tpl-mut">待命</span>${idle.map(([r]) => `<button type="button" class="tpl-idle-m" data-role="${esc(r.k)}">${av(r.k, 'xs')}${esc(r.k)}</button>`).join('')}</div>` : ''}
      </section>
      <section class="tpl-sec kbt" id="tplDecide"><div class="tpl-sec-hd"><h2>需要你判断${asks.length ? ` <span class="tpl-n">${asks.length}</span>` : ''}</h2><span class="tpl-mut">每件事都附 AI 的建议、理由和把握；按建议就点深色按钮</span></div>
        ${asks.length ? `<div class="tpl-decs">${asks.map(decHtml).join('')}</div>` : '<div class="tpl-empty">现在没有需要你判断的事。AI 拿不准的时候，会在这里把建议和把握写清楚再问你。</div>'}
        ${sugs.length ? `<details class="tpl-sugs"><summary>AI 的建议 <span class="tpl-cnt">${sugs.length}</span><span class="tpl-mut">可以不管，管家会按自主度处理</span></summary><div class="tpl-decs">${sugs.map(decHtml).join('')}</div></details>` : ''}
      </section>
      <section class="tpl-sec"><div class="tpl-sec-hd"><h2>项目房间</h2><a href="#/projects">全部房间 →</a></div>
        ${rooms.length || tasks.length ? `<div class="tpl-rooms">${rooms.concat(tasks).slice(0, 6).map(roomCard).join('')}</div>` : '<div class="tpl-empty">还没有进行中的期。把需求交给管家，它会开一间房间，叫上方案 AI。 <button type="button" class="pri" data-tplask>交给管家</button></div>'}
      </section>
      ${ms.length ? `<section class="tpl-sec"><div class="tpl-metrics">${ms.slice(0, 5).map(m => `<${m['链接'] ? `a href="${esc(m['链接'])}"` : 'div'} class="tpl-metric"><span class="tpl-mut">${esc(m['名称'])}</span><b>${esc(m['值'])}<small>${esc(m['单位'] || '')}</small></b>${spark(m['趋势'])}${m['说明'] ? `<small class="tpl-mut">${esc(m['说明'])}</small>` : ''}</${m['链接'] ? 'a' : 'div'}>`).join('')}</div></section>` : ''}
      ${(b['其他'] || []).length ? `<section class="tpl-sec"><div class="tpl-others">${b['其他'].map(x => `<a href="${esc(x['链接'] || '#/')}"><b>${esc(x['标题'])}</b> <span class="tpl-mut">${esc(x['说明'] || '')}</span></a>`).join('')}</div></section>` : ''}
      <footer class="tpl-foot"><i class="tpl-livedot"></i>审查和开发用不同的 AI 会话 · 改动只在开发分支 · 推送和提交要你确认</footer></div>`;
  }
  function paintHome() {
    const app = KB.app; app.innerHTML = homeHtml(); bindJ(app);
    app.querySelectorAll('[data-role]').forEach(x => x.addEventListener('click', e => { if (e.target.closest('a')) return; openRole(x.dataset.role) }));
    app.querySelectorAll('[data-tplask]').forEach(x => x.onclick = () => KB.askOpen(true));
    app.querySelectorAll('a[href^="#tpl"]').forEach(a => a.onclick = e => { e.preventDefault(); const t = document.getElementById(a.getAttribute('href').slice(1)); if (t) { t.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion:reduce)').matches ? 'auto' : 'smooth', block: 'start' }); t.classList.add('tpl-flash'); setTimeout(() => t.classList.remove('tpl-flash'), 1600) } });
  }
  async function homePage() { await Promise.all([ensureSite(), S.brief ? null : loadBrief()]); paintHome() }

  // ---------------------------------------------------------------- 项目：房间列表
  async function projectsPage() {
    await Promise.all([ensureSite(), S.brief ? null : loadBrief()]);
    const ps = periods(), live = ps.filter(p => !p['事项'] && !['已完成', '已暂停'].includes(p['状态'])), tasks = ps.filter(p => p['事项'] && !issueTask(p) && !(p['插件'] || []).length && p['状态'] !== '已完成');
    const issues = ps.filter(p => issueTask(p) && p['状态'] !== '已完成'), rest = ps.filter(p => p['状态'] === '已完成' || (!p['事项'] && p['状态'] === '已暂停'));
    const group = (t, sub, xs) => xs.length ? `<section class="tpl-sec"><div class="tpl-sec-hd"><h2>${t} <span class="tpl-cnt">${xs.length}</span></h2><span class="tpl-mut">${sub}</span></div><div class="tpl-rooms big">${xs.map(roomCard).join('')}</div></section>` : '';
    KB.app.innerHTML = `<div class="tpl-pagehd"><div><div class="tpl-kicker">项目</div><h1 class="tpl-h1">项目房间</h1><p class="tpl-mut">每一期是一间房间：进驻的 AI、走到哪一步、下一步需要谁。亮色头像是正在里面工作的 AI，淡色是这个阶段待命的。</p></div>
      <div class="row"><button class="pri" data-tpladd="new">＋ 新建一期</button><button data-tpladd="task">＋ 事项</button><a href="#/classic">经典总览</a></div></div>
      ${live.length ? group('进行中', '按最近有动静排序', live.sort((a, b) => (b['更新时间'] || '').localeCompare(a['更新时间'] || ''))) : '<div class="tpl-empty">还没有进行中的期。点「＋ 新建一期」，或者把需求交给管家。</div>'}
      ${group('事项', '小事项：不走全栈流程，一个 AI 定位、修改、写结论', tasks)}
      ${group('问题批次', 'Bug / ANR 归成的事项，也在「问题」空间里', issues)}
      ${rest.length ? `<details class="tpl-sec tpl-fold"><summary><h2>已完成 / 已暂停 <span class="tpl-cnt">${rest.length}</span></h2></summary><div class="tpl-rooms big">${rest.map(roomCard).join('')}</div></details>` : ''}`;
    KB.app.querySelectorAll('[data-tpladd]').forEach(b => b.onclick = () => KB.addDlg(b.dataset.tpladd));
  }

  // ---------------------------------------------------------------- 问题：Bug + ANR 按 AI 分析进展分组
  async function issuesPage() {
    await ensureSite(); if (!S.brief) await loadBrief();
    const [zt, anr] = await Promise.all([KB.api('/api/zentao').catch(() => ({ bugs: [] })), KB.api('/api/anr').catch(() => ({ problems: [] }))]);
    const G = { judge: [], work: [], todo: [], done: [] };
    (zt.bugs || []).filter(x => x['状态'] !== '已关闭' && !x['忽略']).forEach(x => {
      const a = x['分析'], f = x['修复'];
      const it = { k: 'Bug', t: x['标题'], id: x['编号'], l: '#/bugs', meta: [x['来源'], x['归属'] && x['归属']['名称'], x['状态']].filter(Boolean).join(' · '), why: a ? a['摘要'] : '' };
      if (x['分析中'] || (f && f['状态'] === '修复中')) G.work.push({ ...it, st: x['分析中'] ? '分析中' : '修复中' });
      else if (a && ['待审核', '需重分析'].includes(a['状态'])) G.judge.push({ ...it, st: a['状态'] === '待审核' ? '分析好了，等你审核' : '需要重新分析', conf: a['置信度'] });
      else if (!a && x['状态'] === '激活') G.todo.push({ ...it, st: '还没分析' });
      else G.done.push({ ...it, st: f ? f['状态'] : a ? a['状态'] : x['状态'] });
    });
    (anr.problems || []).filter(x => x['状态'] !== '忽略').forEach(x => {
      const tp = x['事项'] && P(x['事项']);
      const it = { k: x['类型'] || 'ANR', t: x['标题'], id: x['编号'], l: x['事项'] ? '#/p/' + x['事项'] : '#/anr', meta: [`${x['次数']} 次`, x['最近'] && '最近 ' + x['最近'], x['事项'] && '→ ' + x['事项']].filter(Boolean).join(' · '), why: x['原因'] || (x['应用帧'] || [])[0] || '' };
      if (x['修复后又出现']) G.judge.push({ ...it, st: '修好后又出现了' });
      else if (tp && tp['在跑']) G.work.push({ ...it, st: 'AI 处理中' });
      else if (!x['事项']) G.todo.push({ ...it, st: '没放进批次' });
      else G.done.push({ ...it, st: x['事项状态'] || '已关联' });
    });
    const js = (B()['判断'] || []).filter(j => ['Bug 分析', 'Bug 修复'].includes(judgRole(j)) || /^#\/(bugs|anr)/.test(j['链接'] || '') || issueTask(P((j['链接'] || '').slice(4))));
    const bx = roleState('Bug 分析'), s = S.site || {};
    const row = x => `<a class="tpl-iss" href="${esc(x.l)}"><span class="tpl-kind k-${x.k === 'Bug' ? 'bug' : 'anr'}">${esc(x.k)}</span><span class="tpl-iss-m"><b>${esc(x.t)}</b><small>${esc(x.id)}${x.meta ? ' · ' + esc(x.meta) : ''}</small>${x.why ? `<small class="tpl-iss-why">AI：${esc(short(x.why, 90))}</small>` : ''}</span><span class="tpl-iss-st">${esc(x.st)}${x.conf ? `<small>把握 ${esc(x.conf)}</small>` : ''}</span></a>`;
    const col = (k, t, sub, extra = '') => `<section class="tpl-col c-${k}"><div class="tpl-col-hd"><b>${t}</b><span class="tpl-cnt">${G[k].length + (k === 'judge' ? js.length : 0)}</span></div><p class="tpl-mut">${sub}</p>${extra}${G[k].slice(0, 30).map(row).join('')}${G[k].length > 30 ? `<div class="tpl-mut">还有 ${G[k].length - 30} 条，去 Bug / ANR 页看全部</div>` : ''}${!G[k].length && !extra ? '<div class="tpl-empty sm">没有</div>' : ''}</section>`;
    KB.app.innerHTML = `<div class="tpl-pagehd"><div><div class="tpl-kicker">问题</div><h1 class="tpl-h1">Bug 和 ANR，按 AI 的进展</h1><p class="tpl-mut">Bug 分析 AI 只读分析：拉原文、对照代码、给出位置和修复思路；结论要你审核后才会修。</p></div>
      <div class="tpl-pres">${av('Bug 分析')}<div><b>Bug 分析</b><small class="tpl-mut">${esc(bx.text)}</small></div>${av('Bug 修复', 'ghost')}<div><b>Bug 修复</b><small class="tpl-mut">${esc(roleState('Bug 修复').text)}</small></div></div></div>
      <div class="tpl-chips" style="margin-bottom:14px"><a class="tpl-chip" href="#/bugs">Bug 未关闭 ${esc((s['Bug'] || {})['未关闭'] || 0)} · 待归纳 ${esc((s['Bug'] || {})['待归纳'] || 0)}</a><a class="tpl-chip" href="#/anr">ANR / 崩溃 ${esc((s['ANR'] || {})['总数'] || 0)} · 待处理 ${esc((s['ANR'] || {})['待处理'] || 0)}</a></div>
      <div class="tpl-cols">
        ${col('judge', '需要你判断', 'AI 有了结论，或者情况有变化', js.length ? `<div class="kbt tpl-decs">${js.map(decHtml).join('')}</div>` : '')}
        ${col('work', 'AI 正在处理', '分析或修复会话正在跑')}
        ${col('todo', '等 AI 接手', '还没分析；管家按规矩安排，也可以在 Bug / ANR 页手动开始')}
        ${col('done', '已有结论', '分析通过、已修复，或已经放进事项')}
      </div>`;
    bindJ(KB.app);
  }

  // ---------------------------------------------------------------- 资料：概览
  async function libraryPage() {
    const s = await ensureSite();
    const docs = s['文档'] || [], tools = s['工具'] || [], ph = s['手机'], base = s['基础信息'] || {};
    KB.app.innerHTML = `<div class="tpl-pagehd"><div><div class="tpl-kicker">资料</div><h1 class="tpl-h1">团队共用的资料</h1><p class="tpl-mut">AI 干活时会读这里：基础信息（账号、环境，机密字段加密保存）、说明文档、插件工具和测试手机。</p></div></div>
      <form class="tpl-bigsearch" id="tplLibS"><input type="text" placeholder="搜索资料、文档、代码……" aria-label="搜索"><select aria-label="范围"><option value="all">全部</option><option value="docs">文档</option><option value="code">代码</option></select><button class="pri">搜索</button></form>
      <div class="tpl-libs">
        <a class="tpl-lib" href="#/base"><span class="tpl-lib-ic">◈</span><b>基础信息</b><span class="tpl-mut">${esc(base['条数'] || 0)} 条：账号、环境、地址</span></a>
        <a class="tpl-lib" href="#/d/"><span class="tpl-lib-ic">❏</span><b>文档</b><span class="tpl-mut">${docs.length ? docs.slice(0, 4).map(d => esc(d['名称'])).join('、') + (docs.length > 4 ? ` 等 ${docs.length} 份` : '') : '使用说明等文档'}</span></a>
        ${ph ? `<a class="tpl-lib" href="#/phones"><span class="tpl-lib-ic">▯</span><b>手机</b><span class="tpl-mut">空闲 ${esc(ph['空闲'])} / ${esc(ph['总数'])} 台</span></a>` : ''}
        ${tools.map(t => `<a class="tpl-lib" href="${esc(t['链接'])}"><span class="tpl-lib-ic">${esc(t['图标'])}</span><b>${esc(t['名称'])}</b><span class="tpl-mut">${esc(t['说明'] || '')}${t['待解决'] ? ` · 待解决 ${t['待解决']}` : ''}</span></a>`).join('')}
        <a class="tpl-lib" href="#/settings"><span class="tpl-lib-ic">⚙</span><b>插件和规矩</b><span class="tpl-mut">在设置里管理插件、命令和管家的规矩</span></a>
      </div>`;
    const f = $('#tplLibS'); f.onsubmit = e => { e.preventDefault(); const q = f.querySelector('input').value.trim(); if (q) location.hash = '#/s/' + enc(q + '\u0001' + f.querySelector('select').value) };
  }

  // ---------------------------------------------------------------- 期 / 事项详情：收成「项目房间」
  function memberCard(e, v) {
    const r = roleOf(e), dv = (v['开发'] || []).find(x => x['端'] === e) || null, plan = ((v['方案'] || {})['各端'] || []).find(x => x['端'] === e), end = (v['各端'] || []).find(x => x['端'] === e) || {};
    const st = dv ? (dv['状态'] === '要你看' || dv['状态'] === '失败' ? 'ask' : dv['在跑'] ? 'work' : dv['状态'] === '审查通过' ? 'ok' : 'idle') : 'idle';
    const label = dv ? dv['状态'] + (dv['轮次'] ? ` · 第 ${dv['轮次']} 轮` : '') : plan ? (plan['涉及'] ? `方案：工作量${plan['工作量'] || '?'}` : '方案里不涉及') : end['仓库'] ? '待命' : '还没选仓库';
    const rep = dv ? ((dv['汇报'] || {})['总结'] || (dv['审查'] || {})['总结'] || dv['结果'] || dv['等待'] || '') : plan ? plan['原因'] || '' : '';
    return `<button type="button" class="tpl-member s-${st}" style="--rc:${esc(r.c)}" data-tplend="${esc(e)}" title="到「全栈」看 ${esc(e)} 的详情">
      <span class="tpl-member-hd">${av(e, 'sm')}<b>${esc(e)}</b><span class="tpl-state s-${st === 'ok' ? 'idle' : st}">${esc(label)}</span></span>
      <small>${end['仓库'] ? esc(String(end['显示'] || end['仓库']).replace(/^.*\//, '')) + (end['分支'] || end['当前分支'] ? ' · ' + esc(end['分支'] || end['当前分支']) : '') : '—'}</small>
      ${rep ? `<span class="tpl-member-rep">${esc(short(rep, 80))}</span>` : ''}${(dv && dv['审查'] && dv['审查']['结论']) ? `<span class="tpl-member-rv">审查：${esc(dv['审查']['结论'])}</span>` : ''}</button>`;
  }
  function presenceHtml(name, v) {
    const here = presenceOf(name), p = P(name), sk = stageOfPeriod(p);
    const ends = v ? [...new Set([...(v['各端'] || []).filter(x => x['仓库']).map(x => x['端']), ...((v['全栈'] || {})['涉及'] || []), ...(v['开发'] || []).map(x => x['端'])])] : [];
    const lead = STAGES[SI(sk)].lead.filter(k => !here.includes(k) && !ENDS.includes(k)).slice(0, 3);
    return `<div class="tpl-pres-row"><span class="tpl-pres-l">在场</span>${here.length ? here.map(k => `<button type="button" class="tpl-pchip s-${roleState(k).st}" data-role="${esc(k)}">${av(k, 'xs')}${esc(k)}</button>`).join('') : '<span class="tpl-mut">现在没有 AI 在这间房里工作</span>'}
        ${lead.length ? `<span class="tpl-pres-l">待命</span>${lead.map(k => `<button type="button" class="tpl-pchip ghost" data-role="${esc(k)}">${av(k, 'xs ghost')}${esc(k)}</button>`).join('')}` : ''}
        <span class="tpl-pres-stage">${phaseHtml(p, true)}</span></div>
      ${v ? (ends.length ? `<div class="tpl-members">${ends.map(e => memberCard(e, v)).join('')}</div>` : `<div class="tpl-mut tpl-members-empty">各端成员还没进场：在「全栈」里选这一期涉及的端和仓库，方案 AI 出方案后，每个端会有一个 AI 开发。<a data-tplend="">去选仓库 →</a></div>`) : ''}`;
  }
  async function paintPresence(name) {
    if (!S.site || !S.brief) { await Promise.all([ensureSite(), S.brief ? null : loadBrief()]) }
    const box = document.getElementById('tplPresence'); if (!box) return;
    const p = P(name), full = p && !p['事项'];
    box.innerHTML = presenceHtml(name, full ? S.stack[name] : null);
    bindPresence(box);
    if (!full) return;
    try { const v = await KB.api('/api/stack?name=' + enc(name)); S.stack[name] = v; const b2 = document.getElementById('tplPresence'); if (b2 && KB.curHash() === '/p/' + name) { b2.innerHTML = presenceHtml(name, v); bindPresence(b2) } } catch (_) {}
  }
  function bindPresence(box) {
    box.querySelectorAll('[data-role]').forEach(x => x.onclick = () => openRole(x.dataset.role));
    box.querySelectorAll('[data-tplend]').forEach(x => x.onclick = () => {
      const t = KB.app.querySelector('[data-tab="stack"]'); if (t && !t.closest('.pwhole')) t.click();
      const pane = KB.app.querySelector('[data-pane="stack"]'); if (pane) pane.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion:reduce)').matches ? 'auto' : 'smooth', block: 'start' });
    });
  }
  function enhanceRoom(name) {
    const app = KB.app, ph = app.querySelector('.pagehead'); if (!ph || app.querySelector('.tpl-roomtop')) return;
    const top = document.createElement('section'); top.className = 'tpl-roomtop';
    const p = P(name);
    ph.before(top); top.appendChild(ph);
    const steps = app.querySelector(':scope > .steps'), gn = app.querySelector(':scope > .gnext'), nt = app.querySelector(':scope > .notice');
    if (steps) top.appendChild(steps); if (gn) top.appendChild(gn); if (nt) top.appendChild(nt);
    const crumb = ph.querySelector('.crumb a[href="#/"]'); if (crumb) { const iss = issueTask(p); crumb.textContent = iss ? '问题' : '项目'; crumb.setAttribute('href', iss ? '#/issues' : '#/projects') }
    const who = top.querySelector('.gnext .who');
    if (who) { const you = who.classList.contains('w-你'); who.textContent = you ? '需要你判断' : 'AI 在做'; who.insertAdjacentHTML('afterbegin', you ? '' : '<i class="tpl-livedot"></i>') }
    if (gn && !gn.querySelector('.tpl-gn-k')) gn.insertAdjacentHTML('afterbegin', `<span class="tpl-gn-k">${av('管家', 'sm')}</span>`);
    const pres = document.createElement('div'); pres.id = 'tplPresence'; pres.className = 'tpl-presence'; top.appendChild(pres);
    paintPresence(name);
  }

  // ---------------------------------------------------------------- 刷新
  async function refresh(force) {
    const changed = await loadBrief();
    if (!changed && !force) return;
    paintCrew(); paintSpaces();
    const ae = document.activeElement;
    if (S.drawer && !($('#tplDrawer').contains(ae) && ae.matches('select,input,textarea'))) paintDrawer();
    if (!KB.canRender()) return;
    const h = KB.curHash();
    if (h === '/') { const y = scrollY; paintHome(); scrollTo(0, y) }
    else if (h.startsWith('/p/')) paintPresence(h.slice(3));
  }
  function poll() { clearTimeout(S.timer); S.timer = setTimeout(async () => { if (!document.hidden && KB.canRender()) await refresh(); poll() }, 5000) }

  // ---------------------------------------------------------------- 接到 core 上
  KB.setApp('#tplApp');
  KB.pages.home = homePage;
  Object.assign(KB.routes, { '/projects': projectsPage, '/issues': issuesPage, '/library': libraryPage });
  KB.hooks.nav = (d, site) => { if (site) { S.site = site } paintSpaces(); if (site) paintCrew() };
  const TITLES = { team: '团队', proj: '项目', issue: '问题', lib: '资料', set: '设置' };
  KB.hooks.afterRender = h => {
    const sp = spaceOf(h);
    document.title = (h.startsWith('/p/') ? h.slice(3) + ' · ' : '') + TITLES[sp] + ' · AI 团队办公室';
    document.body.dataset.tplSpace = sp;
    if (h.startsWith('/p/')) enhanceRoom(h.slice(3));
    if (h === '/classic') KB.app.querySelectorAll('.stc .ac button.pri').forEach(b => { if (b.textContent === '去处理') b.textContent = '去看看' });
  };
  KB.on('overview', () => refresh());
  KB.on('dev', ev => { if (KB.curHash() === '/p/' + ev.period) paintPresence(ev.period) });

  // 顶栏按钮、抽屉关闭、手机上的搜索开关
  $('#tplAsk').onclick = () => KB.askOpen(true);
  $('#tplScrim').onclick = closeRole;
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && S.drawer && !document.querySelector('#dlg[open]')) closeRole() });
  $('#tplSearchBtn').onclick = () => { document.body.classList.toggle('tpl-search-on'); if (document.body.classList.contains('tpl-search-on')) $('#q').focus() };
  window.addEventListener('hashchange', () => { document.body.classList.remove('tpl-search-on') });

  if (window.KBUI) KBUI.css();     // 判断卡片（KBUI.judg）的样式
  paintSpaces(); paintCrew();
  loadBrief().then(() => { paintCrew(); paintSpaces() });
  poll();
})();
