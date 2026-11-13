// From 大大王.DT
/* 界面模板「画布」：整个网站是一张可以缩放的项目地图。
 * - 全局画布（#/）：进行中的期、事项、问题簇（Bug / ANR）、正在干活的 AI、管家都是节点，按五个阶段分区摆放；
 *   AI 在做的节点发光，缺东西的虚线，出问题的标红，需要你判断的琥珀色并由管家连线过去。
 * - 点期节点（#/p/<名>）：画布聚焦到这一期的关系图（需求、设计稿、接口、契约、各端、证据、Bug），core 的期详情在右侧抽屉里。
 * - 其他页面（Bug、ANR、手机、基础信息、设置、文档、工具、搜索、经典总览、列表）都开在抽屉 / 宽抽屉里，背景画布保留并变暗。
 * - 右下角 AI 洞察：当前焦点的一句洞察 + 需要你判断的事（AI 建议、理由、把握）。
 * 数据：/api/site（hooks.nav 给）、/api/brief（自己拉，SSE 有变化时重拉）、/api/period + /api/stack（聚焦的那一期）。
 * 功能页面全部由 core 渲染，这里只做骨架、导航、首页和布局；id / class 一律 tpl 前缀。
 */
(function () {
  'use strict';
  const TPL = '画布';
  const $ = s => document.querySelector(s);
  const esc = KB.esc, enc = KB.enc;
  KB.setApp('#tplApp');

  // ---------------------------------------------------------------- 状态
  const S = {
    site: null, brief: null, mode: 'home', hash: '/', focus: null, graph: null,
    cam: { x: 0, y: 0, k: 1 }, moved: false, bounds: null, pos: {},
    filter: 'all', wide: false, insCollapsed: false
  };
  const LS = (k, v) => { try { if (v === undefined) return localStorage.getItem('kb.tplcv.' + k); localStorage.setItem('kb.tplcv.' + k, v) } catch (_) { return null } };
  S.filter = LS('filter') || 'all';
  S.insCollapsed = LS('ins') === '1';
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const narrow = () => innerWidth < 720;
  const docked = () => innerWidth < 1100;          // 抽屉占满宽度（画布被盖住）

  // 主题：跟随系统 → 深色 → 浅色
  const THEMES = ['', 'dark', 'light'], THEME_N = { '': '跟随系统', dark: '深色', light: '浅色' };
  function applyTheme(t) { if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme; $('#tplTheme').title = '主题：' + THEME_N[t] + '（点一下切换）' }
  applyTheme(LS('theme') || '');

  // ---------------------------------------------------------------- 阶段
  const STAGES = [
    { k: 'collect', n: '收集资料', d: '需求、设计稿、接口还在补', ins: '缺口' },
    { k: 'plan', n: '方案拍板', d: 'AI 出方案，等你拍板', ins: '影响面' },
    { k: 'dev', n: '并行开发', d: '各端 AI 同时开发、互相审查', ins: '进展' },
    { k: 'accept', n: '验收上线', d: '对照需求看证据、构建', ins: '结论' },
    { k: 'online', n: '线上维护', d: 'Bug、ANR 和各种事项', ins: '根因' }
  ];
  const SI = k => STAGES.findIndex(s => s.k === k);
  function stageOf(p) {
    if (!p) return 'collect';
    if (p['事项'] || p['状态'] === '已完成') return 'online';
    const s = p['当前步骤'] || '';
    if (/资料|仓库|收集|需求|来源/.test(s)) return 'collect';
    if (/方案|拍板|评审|设计|契约/.test(s)) return 'plan';
    if (/开发|联调|编码|实现|修复/.test(s)) return 'dev';
    if (/验收|构建|测试|提测|上线|发布|复测|推送/.test(s)) return 'accept';
    if (!s && (p['步骤'] || []).length && p['步骤'].every(x => x['状态'] === 'done')) return 'accept';
    return { 收集中: 'collect', 已批准开发: 'plan', 开发中: 'dev' }[p['状态']] || 'collect';
  }
  const periodOf = n => ((S.site && S.site['期']) || []).find(p => p['名称'] === n);

  // ---------------------------------------------------------------- 智能状态（/api/brief）
  let briefBusy = false, briefSig = '';
  async function loadBrief(force) {
    if (briefBusy) return; briefBusy = true;
    try {
      const b = await KB.api('/api/brief'), sig = JSON.stringify(b).replace(/"时间":"[^"]*"/, '');
      if (!force && sig === briefSig) return;
      briefSig = sig; S.brief = b; scheduleDraw();
    } catch (_) { } finally { briefBusy = false }
  }
  let bt = null; const briefSoon = () => { clearTimeout(bt); bt = setTimeout(() => loadBrief(), 1200) };
  KB.on('overview', briefSoon); KB.on('dev', briefSoon);
  setInterval(() => { if (!document.hidden && (S.mode === 'home' || S.mode === 'focus')) loadBrief() }, 12000);

  const judgments = () => (S.brief && S.brief['判断']) || [];
  const acts = () => (S.brief && S.brief['活动']) || [];
  const actsOf = link => acts().filter(a => a['链接'] === link);
  const judgOf = link => judgments().filter(j => j['链接'] === link);

  const briefOpts = {
    act: async (id, action, x) => {
      try { const r = await KB.post('/api/brief/act', { id, action, ...x }); KB.toast(String((r && r.msg) || '好的').split('\n')[0]) } catch (e) { KB.toast(e.message) }
      await loadBrief(true); KB.navRefresh();
    },
    ask: async text => { try { await KB.post('/api/chat/ask', { text, page: '#' + KB.curHash() }); KB.askOpen(true) } catch (e) { KB.toast(e.message) } },
    preview: text => KB.api('/api/intake/preview?text=' + enc(text)),
    openAsk: () => KB.askOpen(true)
  };

  // ---------------------------------------------------------------- 全局布局
  const NW = 206, NH_P = 104, NH_T = 70, ZW = 228, ZG = 22, ZTOP = 80, GAP = 12;
  function globalModel() {
    const site = S.site; if (!site) return null;
    const nodes = [], edges = [], zones = STAGES.map(s => ({ ...s, items: [] }));
    const js = judgments();
    const judgLinks = new Set(js.map(j => j['链接']).filter(Boolean));
    const actLinks = new Set(acts().map(a => a['链接']).filter(Boolean));
    const ps = site['期'] || [];
    const rank = p => (judgLinks.has(p['链接']) ? 0 : 4) + (p['在跑'] || actLinks.has(p['链接']) ? 0 : 2) + (p['事项'] ? 1 : 0) + (p['状态'] === '已完成' ? 6 : 0);
    ps.slice().sort((a, b) => rank(a) - rank(b) || String(b['更新时间']).localeCompare(String(a['更新时间']))).forEach(p => {
      const z = zones[SI(stageOf(p))];
      const nx = p['下一步'] || {};
      const ask = judgLinks.has(p['链接']) || p['待确认'] > 0;
      const hot = p['在跑'] || actLinks.has(p['链接']);
      const bad = p['没解决Bug'] > 0;
      const miss = p['问题'] > 0 || (!p['事项'] && stageOf(p) === 'collect' && nx['谁'] === '你');
      z.items.push({ id: 'p:' + p['名称'], t: p['事项'] ? 'task' : 'period', p, ask, hot, bad, miss, done: p['状态'] === '已完成' || p['状态'] === '已暂停' });
    });
    // 问题簇放在「线上维护」最上面
    const on = zones[4], bug = site['Bug'] || {}, anr = site['ANR'] || {};
    on.items.unshift({ id: 'x:anr', t: 'cluster', name: 'ANR / 崩溃', icon: '💥', link: '#/anr', sub: `待处理 ${anr['待处理'] || 0} · 共 ${anr['总数'] || 0}`, bad: anr['待处理'] > 0, hot: actLinks.has('#/anr'), ask: judgLinks.has('#/anr') });
    on.items.unshift({ id: 'x:bug', t: 'cluster', name: 'Bug', icon: '🐞', link: '#/bugs', sub: `未关闭 ${bug['未关闭'] || 0} · 待归纳 ${bug['待归纳'] || 0}`, bad: bug['未关闭'] > 0, hot: actLinks.has('#/bugs'), ask: judgLinks.has('#/bugs') });

    const vert = narrow(), MAXZ = 12;
    let maxH = 0;
    zones.forEach((z, i) => {
      let items = z.items;
      if (items.length > MAXZ) { const more = items.length - (MAXZ - 1); items = items.slice(0, MAXZ - 1); items.push({ id: 'x:more:' + z.k, t: 'more', name: `还有 ${more} 个`, link: '#/list', sub: '在列表里看全部' }) }
      z.shown = items;
      z.x = vert ? 0 : i * (ZW + ZG); z.w = ZW;
      let y = ZTOP;
      items.forEach(n => { n.h = n.t === 'period' ? NH_P : NH_T; n.x = z.x + (ZW - NW) / 2; n.y = y; n.w = NW; y += n.h + GAP; });
      z.h = Math.max(y + 10, vert ? 150 : 240); maxH = Math.max(maxH, z.h);
    });
    if (vert) {         // 手机：阶段从上往下排
      let y = 0;
      zones.forEach(z => { const dy = y; z.y = dy; z.shown.forEach(n => n.y += dy); y += z.h + ZG; });
      maxH = y;
    } else zones.forEach(z => { z.y = 0; z.h = maxH });
    zones.forEach(z => z.shown.forEach(n => nodes.push(n)));

    // 管家（中枢）：放在最上面，连到需要你判断的节点
    const totalW = vert ? ZW : 5 * ZW + 4 * ZG;
    const st = (S.brief && S.brief['状态']) || {};
    const hub = { id: 'hub', t: 'hub', x: totalW / 2 - 150, y: -150, w: 300, h: 92, st };
    nodes.push(hub);
    // 基地：工具、手机、基础信息、文档、设置、经典总览
    const stations = [];
    if (site['手机']) stations.push({ name: '手机', icon: '▯', link: '#/phones', sub: `空闲 ${site['手机']['空闲']} / ${site['手机']['总数']}` });
    stations.push({ name: '基础信息', icon: '◈', link: '#/base', sub: `${(site['基础信息'] || {})['条数'] || 0} 条` });
    (site['工具'] || []).forEach(t => stations.push({ name: t['名称'], icon: t['图标'] || '⚒', link: t['链接'], sub: t['待解决'] ? `${t['待解决']} 件在处理` : (t['说明'] || '').slice(0, 14), ask: t['待确认'] > 0 }));
    stations.push({ name: '文档', icon: '☰', link: '#/d/', sub: `${(site['文档'] || []).length || ''} 份说明`.trim() });
    stations.push({ name: '设置', icon: '⚙', link: '#/settings', sub: '引擎、流程、管家' });
    stations.push({ name: '经典总览', icon: '▦', link: '#/classic', sub: '原来的卡片总览' });
    const SW = 156, SH = 58, per = vert ? 2 : Math.max(1, Math.floor((totalW + 12) / (SW + 12)));
    const by = maxH + 60;
    stations.forEach((s, i) => { const r = Math.floor(i / per), c = i % per, cnt = Math.min(per, stations.length - r * per), rowW = cnt * SW + (cnt - 1) * 12;
      nodes.push({ id: 'st:' + s.link, t: 'station', ...s, x: (totalW - rowW) / 2 + c * (SW + 12), y: by + 30 + r * (SH + 12), w: SW, h: SH }) });
    const baseH = 30 + Math.ceil(stations.length / per) * (SH + 12);

    // 连线
    const byLink = {}; nodes.forEach(n => { const l = n.p ? n.p['链接'] : n.link; if (l) byLink[l] = n });
    js.forEach(j => { const n = byLink[j['链接']]; if (n) edges.push({ a: 'hub', b: n.id, c: 'ask' }) });
    ps.filter(p => p['没解决Bug'] > 0).forEach(p => { if (byLink[p['链接']]) edges.push({ a: 'x:bug', b: byLink[p['链接']].id, c: 'bad' }) });
    ps.filter(p => p['事项'] && /ANR|崩溃/.test(p['事项类型'] || '') && p['状态'] !== '已完成').forEach(p => { if (byLink[p['链接']]) edges.push({ a: 'x:anr', b: byLink[p['链接']].id, c: 'soft' }) });
    // 正在干活的 AI：小圆点挂在它在处理的节点上
    const agents = [];
    const cnt = {};
    acts().forEach(a => {
      const tgt = byLink[a['链接']] || hub;
      const i = cnt[tgt.id] = (cnt[tgt.id] || 0) + 1;
      agents.push({ a, x: tgt.x + tgt.w - 14 - (i - 1) * 24, y: tgt.y - 12, tgt });
    });
    return { nodes, edges, zones, agents, hub, bounds: { x: -20, y: hub.y - 20, w: totalW + 40, h: by + baseH + 20 - (hub.y - 20) }, baseY: by, baseH, totalW };
  }

  // ---------------------------------------------------------------- 画全局
  const dots = st => (st || []).map(s => `<i class="${s['状态']}" title="${esc(s['名称'])}"></i>`).join('');
  function nodeHtml(n) {
    const cls = ['tpl-n', 'tpl-n-' + n.t, n.hot && 'hot', n.ask && 'ask', n.bad && 'bad', n.miss && 'miss', n.done && 'done', n.dim && 'faint'].filter(Boolean).join(' ');
    const sty = `left:${n.x}px;top:${n.y}px;width:${n.w}px;height:${n.h}px`;
    if (n.t === 'hub') {
      const st = n.st || {}, w = acts().filter(a => !a['等你']).length;
      return `<button type="button" class="tpl-n tpl-n-hub ${st['等你'] ? 'ask' : ''} ${w ? 'hot' : ''}" data-id="hub" style="${sty}" title="交给管家">
        <span class="tpl-orb" aria-hidden="true"></span><span class="tpl-hb"><b>管家 · ${esc(st['名称'] || '在看着')}</b>
        <span>${w ? `${w} 个 AI 在工作` : 'AI 都在休息'} · 今天替你完成 ${st['今天完成'] || 0} 件</span>
        <span class="tpl-hq">${st['等你'] ? `${st['等你']} 件事需要你判断` : '把需求、日志、文件交给我'}</span></span></button>`;
    }
    if (n.t === 'period' || n.t === 'task') {
      const p = n.p, nx = p['下一步'] || {}, ac = actsOf(p['链接'])[0];
      const kind = p['事项'] ? `事项 · ${p['事项类型'] || '其他'}` : `期 · ${p['流程'] || '开发'}`;
      const line = ac ? `<span class="tpl-ai"><i class="tpl-pulse"></i>${esc(ac['角色'])}：${esc(ac['状态'])}${(ac['步骤'] || []).length ? ' · ' + esc(ac['步骤'][ac['步骤'].length - 1]) : ''}</span>`
        : p['在跑'] ? `<span class="tpl-ai"><i class="tpl-pulse"></i>AI 正在推进</span>`
          : nx['文字'] ? `<span class="tpl-nx ${nx['谁'] === '你' ? 'you' : ''}">${nx['谁'] === '你' ? '需要你：' : nx['谁'] === 'AI' ? 'AI 接着：' : '下一步：'}${esc(nx['文字'])}</span>` : `<span class="tpl-nx">${esc(p['说明'] || p['状态'])}</span>`;
      const tags = [p['待确认'] ? `<b class="a" title="待确认">? ${p['待确认']}</b>` : '', p['问题'] ? `<b class="m" title="问题（缺手机、账号等）">! ${p['问题']}</b>` : '', p['没解决Bug'] ? `<b class="b" title="没解决的 Bug">● ${p['没解决Bug']}</b>` : '', p['免打扰'] ? '<b title="免打扰">☾</b>' : ''].join('');
      return `<a class="${cls}" href="${esc(p['链接'])}" data-id="${esc(n.id)}" style="${sty}" title="${esc(p['名称'] + (p['说明'] ? '\n' + p['说明'] : ''))}">
        <span class="tpl-nk">${esc(kind)}${p['当前步骤'] ? `<em>${esc(p['当前步骤'])}</em>` : `<em>${esc(p['状态'])}</em>`}</span>
        <b class="tpl-nt">${esc(p['名称'])}</b>${line}
        ${n.t === 'period' ? `<span class="tpl-nf"><span class="tpl-dots">${dots(p['步骤'])}</span><span class="tpl-tags">${tags}</span></span>` : tags ? `<span class="tpl-tags tpl-tags-r">${tags}</span>` : ''}</a>`;
    }
    return `<a class="${cls}" href="${esc(n.link)}" data-id="${esc(n.id)}" style="${sty}"><span class="tpl-si" aria-hidden="true">${esc(n.icon || '…')}</span><span class="tpl-sb"><b>${esc(n.name)}</b><span>${esc(n.sub || '')}</span></span></a>`;
  }
  const center = n => [n.x + n.w / 2, n.y + n.h / 2];
  function edgePath(A, B) {
    const [x1, y1] = center(A), [x2, y2] = center(B);
    const dx = x2 - x1, dy = y2 - y1;
    if (Math.abs(dy) >= Math.abs(dx) * 0.6) {                // 竖向：从上下边出
      const sy = y1 + Math.sign(dy) * A.h / 2, ey = y2 - Math.sign(dy) * B.h / 2, my = (sy + ey) / 2;
      return `M${x1} ${sy}C${x1} ${my},${x2} ${my},${x2} ${ey}`;
    }
    const sx = x1 + Math.sign(dx) * A.w / 2, ex = x2 - Math.sign(dx) * B.w / 2, mx = (sx + ex) / 2;
    return `M${sx} ${y1}C${mx} ${y1},${mx} ${y2},${ex} ${y2}`;
  }
  const matchFilter = n => {
    const f = S.filter; if (f === 'all' || n.t === 'hub') return true;
    if (f === 'ask') return n.ask; if (f === 'hot') return n.hot; if (f === 'bad') return n.bad || n.miss;
    if (f === 'period') return n.t === 'period'; if (f === 'task') return n.t === 'task' || n.t === 'cluster';
    return true;
  };
  const FILTERS = [['all', '全部'], ['ask', '需要你判断'], ['hot', 'AI 在做'], ['bad', '有问题 / 缺东西'], ['period', '只看期'], ['task', '只看事项和问题']];

  function focusStageKey() {
    const g = S.brief && S.brief['关系'];
    if (g && periodOf(g['标题'])) return stageOf(periodOf(g['标题']));
    const j = judgments()[0]; if (j && periodOf((j['链接'] || '').replace('#/p/', ''))) return stageOf(periodOf(j['链接'].replace('#/p/', '')));
    return '';
  }

  function drawGlobal() {
    const M = globalModel(); if (!M) return false;
    S.model = M;
    const now = focusStageKey();
    const zh = M.zones.map((z, i) => `<section class="tpl-zone ${z.k === now ? 'now' : ''} z-${z.k}" style="left:${z.x}px;top:${z.y}px;width:${z.w}px;height:${z.h}px">
        <header><span class="tpl-zi">${i + 1}</span><b>${esc(z.n)}</b><span class="tpl-zc">${z.items.length - (z.k === 'online' ? 2 : 0)}</span>${z.k === now ? '<em>现在的重点</em>' : ''}<small>${esc(z.d)}</small></header>
        ${z.shown.length ? '' : '<div class="tpl-zempty">这一阶段没有东西</div>'}</section>`).join('')
      + `<section class="tpl-zone tpl-base" style="left:-10px;top:${M.baseY}px;width:${M.totalW + 20}px;height:${M.baseH + 24}px"><header><b>基地</b><small>工具、手机、基础信息、文档、设置</small></header></section>`;
    const nh = M.nodes.map(nodeHtml).join('')
      + M.agents.map(g => `<a class="tpl-agent ${g.a['等你'] ? 'wait' : ''}" href="${esc(g.a['链接'] || '#/')}" style="left:${g.x}px;top:${g.y}px;--c:${esc(g.a['颜色'] || '#64748b')}" title="${esc(g.a['角色'] + ' · ' + g.a['状态'] + ((g.a['步骤'] || []).length ? '\n' + g.a['步骤'].slice(-3).join('\n') : ''))}">${esc((g.a['角色'] || 'AI')[0])}</a>`).join('');
    const idx = {}; M.nodes.forEach(n => idx[n.id] = n);
    const eh = M.edges.filter(e => idx[e.a] && idx[e.b]).map(e => `<path class="tpl-e e-${e.c}" d="${edgePath(idx[e.a], idx[e.b])}"/>`).join('')
      + M.agents.map(g => { const [x2, y2] = center(g.tgt); return g.tgt.id === 'hub' ? '' : `<path class="tpl-e e-agent" style="stroke:${esc(g.a['颜色'] || '#64748b')}" d="M${g.x + 11} ${g.y + 11}L${Math.min(g.x + 11, x2)} ${y2 - g.tgt.h / 2}"/>` }).join('');
    if (zh + nh + eh === S.lastG) return false;      // 没变化就不动 DOM（不打断动画和悬停）
    if (!S.lastG) { stage.classList.add('tpl-enter'); setTimeout(() => stage.classList.remove('tpl-enter'), 1500) }
    S.lastG = zh + nh + eh;
    $('#tplZones').innerHTML = zh; $('#tplNodes').innerHTML = nh; $('#tplEdges').innerHTML = eh;
    applyFilter();
    $('#tplNodes').querySelector('[data-id="hub"]').onclick = () => KB.askOpen(true);
    return true;
  }
  function applyFilter() {
    if (!S.model) return;
    const idx = {}; S.model.nodes.forEach(n => idx[n.id] = n);
    document.querySelectorAll('#tplNodes .tpl-n').forEach(el => { const n = idx[el.dataset.id]; el.classList.toggle('tpl-off', !!n && !matchFilter(n)) });
    $('#tplFilterLbl').textContent = (FILTERS.find(f => f[0] === S.filter) || FILTERS[0])[1];
  }

  // ---------------------------------------------------------------- 聚焦：一期的关系图
  const gcache = {};
  async function periodGraph(name, force) {
    const c = gcache[name]; if (c && !force && Date.now() - c.t < 5000) return c.g;
    const sp = periodOf(name) || {};
    let d = null, st = null;
    try { d = await KB.api('/api/period?name=' + enc(name)) } catch (_) { }
    const m = (d && d.meta) || {}, isTask = sp['事项'] || m['类型'] === '事项';
    const mats = (d && d.materials) || {}, notes = (d && d.notes) || {};
    const cnt = k => (mats[k] || []).length + (notes[k] || []).length;
    const bugs = ((d && d.bugs) || []).filter(b => !b['忽略'] && (b['状态'] || '激活') === '激活').slice(0, 4);
    const nodes = [], edges = [];
    if (!isTask) {
      try { st = await KB.api('/api/stack?name=' + enc(name)) } catch (_) { }
      const fs = (m['全栈'] || {})['状态'] || (st && st['状态']) || '';
      const bg = S.brief && S.brief['关系'] && S.brief['关系']['标题'] === name ? S.brief['关系'] : null;
      if (bg) { bg['节点'].forEach(n => nodes.push({ ...n })); bg['边'].forEach(e => edges.push(e.slice())) }
      else {
        nodes.push({ id: 'req', 类: '需求', 名称: '需求', 说明: cnt('需求') ? `${cnt('需求')} 份` : '还没有', 状态: cnt('需求') ? (fs ? '' : 'hot') : 'miss' });
        nodes.push({ id: 'des', 类: '设计', 名称: '设计稿', 说明: cnt('设计图') ? `${cnt('设计图')} 份` : '还没有', 状态: cnt('设计图') ? '' : 'miss' });
        nodes.push({ id: 'api', 类: '接口', 名称: '接口文档', 说明: cnt('接口文档') ? `${cnt('接口文档')} 份` : '还没有', 状态: cnt('接口文档') ? '' : 'miss' });
        const plan = fs && !/失败|未/.test(fs);
        nodes.push({ id: 'ct', 类: '契约', 名称: '方案 · 接口契约', 说明: fs || '未出', 状态: plan ? 'core' : 'dim' });
        edges.push(['req', 'des'], ['req', 'api'], ['req', 'ct'], ['des', 'ct'], ['api', 'ct']);
        const dev = m['各端开发'] || {};
        ((st && st['各端']) || []).filter(x => x['仓库']).forEach(x => {
          const s = (dev[x['端']] || {})['状态'] || '';
          nodes.push({ id: 'e:' + x['端'], 类: '端', 名称: x['端'], 说明: s || x['分支'] || '', 状态: /开发中|审查中|排队中|打回/.test(s) ? 'hot' : /要你看|失败/.test(s) ? 'bad' : s === '审查通过' ? 'ok' : '' });
          edges.push(['ct', 'e:' + x['端']]);
        });
        if (/各端完成|已验收/.test(fs)) { nodes.push({ id: 'ev', 类: '证据', 名称: '证据包', 说明: fs === '已验收' ? '已验收' : '等你验收', 状态: fs === '已验收' ? 'ok' : 'hot' }); nodes.filter(n => n['类'] === '端').forEach(n => edges.push([n.id, 'ev'])) }
        bugs.slice(0, 3).forEach(b => { const ends = nodes.filter(n => n['类'] === '端'); nodes.push({ id: 'b:' + b['编号'], 类: '问题', 名称: 'Bug ' + (b['编号'] || ''), 说明: String(b['标题'] || '').slice(0, 14), 状态: 'bad' }); edges.push([ends[0] ? ends[0].id : 'ct', 'b:' + b['编号']]) });
      }
    } else {
      const total = Object.keys(mats).reduce((a, k) => a + cnt(k), 0);
      nodes.push({ id: 'src', 类: '来源', 名称: m['事项类型'] || sp['事项类型'] || '事项', 说明: String(m['来自'] || m['优先级'] && ('优先级 ' + m['优先级']) || '').slice(0, 18), 状态: 'core' });
      nodes.push({ id: 'mat', 类: '资料', 名称: '资料 · 日志', 说明: total ? `${total} 份` : '还没有', 状态: total ? '' : 'miss' });
      const repos = (m['关联仓库'] || []).length ? m['关联仓库'] : m['开发仓库'] ? [m['开发仓库']] : [];
      const ses = m['开发会话'] || {};
      nodes.push({ id: 'repo', 类: '仓库', 名称: '工程', 说明: repos.length ? repos.map(r => String(r).split('/').pop()).join('、').slice(0, 18) : '还没选', 状态: repos.length ? '' : 'miss' });
      nodes.push({ id: 'res', 类: '结论', 名称: '定位 · 修复', 说明: sp['在跑'] ? 'AI 在处理' : ses['状态'] ? '上次推动' + ses['状态'] : (m['状态'] || ''), 状态: sp['在跑'] ? 'hot' : m['状态'] === '已完成' ? 'ok' : 'dim' });
      edges.push(['src', 'mat'], ['src', 'repo'], ['mat', 'res'], ['repo', 'res']);
      bugs.forEach(b => { nodes.push({ id: 'b:' + b['编号'], 类: '问题', 名称: 'Bug ' + (b['编号'] || ''), 说明: String(b['标题'] || '').slice(0, 14), 状态: 'bad' }); edges.push(['res', 'b:' + b['编号']]) });
    }
    const g = { name, isTask, nodes, edges, sp, guide: (d && d.guide) || {} };
    gcache[name] = { t: Date.now(), g };
    return g;
  }
  // 不同阶段，图上亮的地方不同
  function stageLook(g, sk) {
    g.nodes.forEach(n => {
      if (n['状态'] === 'bad' || n['状态'] === 'miss' || n['状态'] === 'hot') return;
      if (sk === 'collect' && ['需求', '设计', '接口', '资料', '来源'].includes(n['类'])) n.lit = 1;
      if (sk === 'plan' && ['契约', '需求'].includes(n['类'])) n.lit = 1;
      if (sk === 'dev' && ['端', '契约', '结论'].includes(n['类'])) n.lit = 1;
      if (sk === 'accept' && ['证据', '端', '需求'].includes(n['类'])) n.lit = 1;
      if (sk === 'online' && ['问题', '结论', '端'].includes(n['类'])) n.lit = 1;
    });
  }
  const FW = 172, FH = 66;
  function layoutFocus(g, cx, cy) {
    const P = {}, row = (list, y) => list.forEach((n, i) => P[n.id] = [cx + (i - (list.length - 1) / 2) * (FW + 30), y]);
    const T = k => g.nodes.filter(n => n['类'] === k);
    if (!g.isTask) {
      row(T('需求'), cy - 210);
      T('设计').forEach(n => P[n.id] = [cx - 210, cy - 120]); T('接口').forEach(n => P[n.id] = [cx + 210, cy - 120]);
      row(T('契约'), cy - 30);
      row(T('证据'), cy + 70);
      row(T('端'), cy + (T('证据').length ? 170 : 120));
      row(T('问题'), cy + (T('证据').length ? 270 : 220));
    } else {
      row(T('来源'), cy - 170); T('资料').forEach(n => P[n.id] = [cx - 200, cy - 60]); T('仓库').forEach(n => P[n.id] = [cx + 200, cy - 60]);
      row(T('结论'), cy + 50); row(T('问题'), cy + 160);
    }
    g.nodes.forEach(n => { if (!P[n.id]) P[n.id] = [cx, cy + 320] });
    return P;
  }
  const NODE_TAB = { 需求: 'mat', 设计: 'mat', 接口: 'mat', 资料: 'mat', 契约: 'stack', 端: 'stack', 证据: 'stack', 问题: 'bug', 来源: 'dev', 仓库: 'dev', 结论: 'dev' };
  let focusSeq = 0;
  async function drawFocus(name, force) {
    const seq = ++focusSeq;
    const g = await periodGraph(name, force); if (seq !== focusSeq || S.mode !== 'focus') return;
    S.graph = g;
    const M = S.model, me = M && M.nodes.find(n => n.id === 'p:' + name);
    const [cx, cy] = me ? center(me) : [600, 300];
    const sk = stageOf(g.sp);
    stageLook(g, sk);
    const P = layoutFocus(g, cx, cy);
    const ag = actsOf('#/p/' + name);
    const steps = (g.sp['步骤'] || g.guide['步骤'] || []);
    const xs = Object.values(P).map(p => p[0]), ys = Object.values(P).map(p => p[1]);
    const top = Math.min(...ys) - FH / 2 - 112;
    const title = `<div class="tpl-ftitle" style="left:${cx}px;top:${top}px"><span class="tpl-fk">${g.isTask ? '事项' : '期'} · ${esc(STAGES[SI(sk)].n)}</span><b>${esc(name)}</b>
      ${steps.length ? `<span class="tpl-route">${steps.map(s => `<i class="${s['状态']}">${s['状态'] === 'done' ? '✓ ' : ''}${esc(s['名称'])}</i>`).join('<u></u>')}</span>` : ''}</div>`;
    const fh = title + g.nodes.map(n => {
      const [x, y] = P[n.id], st = n['状态'] || '';
      const a = ag.find(z => n.id === 'e:' + z['角色']) || (n['类'] === '契约' && ag.find(z => z['角色'] === '方案')) || (n['类'] === '结论' && ag[0]);
      return `<button type="button" class="tpl-fn ${esc(st)} ${n.lit ? 'lit' : ''} ${a ? 'hot' : ''} k-${esc(n['类'])}" data-tab="${NODE_TAB[n['类']] || ''}" style="left:${x - FW / 2}px;top:${y - FH / 2}px;width:${FW}px;height:${FH}px">
        <span class="tpl-fc">${esc(n['类'])}</span><b>${esc(n['名称'])}</b><span>${a ? `<i class="tpl-pulse"></i>${esc(a['状态'])}` : esc(n['说明'] || '')}</span></button>`;
    }).join('');
    const hotIds = new Set(g.nodes.filter(n => ['hot', 'core', 'bad'].includes(n['状态']) || n.lit).map(n => n.id));
    const miss = new Set(g.nodes.filter(n => n['状态'] === 'miss').map(n => n.id));
    const bad = new Set(g.nodes.filter(n => n['状态'] === 'bad').map(n => n.id));
    const box = id => ({ x: P[id][0] - FW / 2, y: P[id][1] - FH / 2, w: FW, h: FH });
    const feh = g.edges.filter(([a, b]) => P[a] && P[b]).map(([a, b]) => `<path class="tpl-e ${bad.has(b) ? 'e-bad' : miss.has(a) || miss.has(b) ? 'e-miss' : hotIds.has(a) && hotIds.has(b) ? 'e-hot' : ''}" d="${edgePath(box(a), box(b))}"/>`).join('');
    if (fh + feh !== S.lastF) { S.lastF = fh + feh; $('#tplFocus').innerHTML = fh; $('#tplFEdges').innerHTML = feh }
    $('#tplFocus').querySelectorAll('[data-tab]').forEach(b => b.onclick = () => {
      const k = b.dataset.tab, t = k && document.querySelector(`#tplApp [data-tab="${k}"]`), pane = k && document.querySelector(`#tplApp [data-pane="${k}"]`);
      if (t) t.click();
      const el = pane && !pane.hidden ? pane : t;
      if (el) scrollTo({ top: Math.max(0, el.getBoundingClientRect().top + scrollY - (docked() ? 120 : 70)), behavior: reduced.matches ? 'auto' : 'smooth' });
    });
    S.fbounds = { x: Math.min(...xs) - FW / 2 - 20, y: top - 10, w: Math.max(...xs) - Math.min(...xs) + FW + 40, h: Math.max(...ys) + FH / 2 + 20 - top };
    drawInsight();
    if (!S.moved) fit(S.fbounds, true);
  }

  // ---------------------------------------------------------------- 相机
  const world = $('#tplWorld'), stage = $('#tplStage');
  function applyCam(anim) {
    world.classList.toggle('tpl-anim', !!anim && !reduced.matches);
    world.style.transform = `translate(${S.cam.x}px,${S.cam.y}px) scale(${S.cam.k})`;
    stage.style.setProperty('--tpl-k', S.cam.k);
    stage.style.backgroundSize = `${22 * S.cam.k}px ${22 * S.cam.k}px`;
    stage.style.backgroundPosition = `${S.cam.x}px ${S.cam.y}px`;
  }
  function visArea() {
    const tools = $('#tplTools').getBoundingClientRect();
    const open = document.body.classList.contains('tpl-open');
    const dw = open && !docked() ? $('#tplDrawer').getBoundingClientRect().width : 0;
    const ins = $('#tplInsight').getBoundingClientRect();
    const insBot = open && !narrow() && !docked() && ins.height && !$('#tplInsight').classList.contains('tpl-col') ? innerHeight - ins.top + 12 : 0;
    const top = narrow() ? tools.bottom + 10 : 76, bot = insBot ? Math.min(insBot, innerHeight * 0.45) : narrow() && ins.height ? Math.min(innerHeight * 0.5, Math.max(64, innerHeight - ins.top + 10)) : narrow() ? 64 : 30;
    const insW = !open && !narrow() && !S.insCollapsed && $('#tplInsight').offsetWidth ? $('#tplInsight').offsetWidth + 24 : 0;
    return { l: 16, t: top, w: Math.max(120, innerWidth - dw - 32 - insW), h: Math.max(120, innerHeight - top - bot) };
  }
  function fit(b, anim) {
    if (!b) return;
    const A = visArea();
    let k = Math.min(A.w / b.w, A.h / b.h, 1.15);
    if (narrow() && S.mode === 'home') k = Math.min(A.w / b.w, 1.1);   // 手机：按宽度适配，竖着拖
    k = Math.max(0.2, k);
    S.cam.k = k;
    S.cam.x = A.l + (A.w - b.w * k) / 2 - b.x * k;
    S.cam.y = (narrow() && S.mode === 'home' && b.h * k > A.h) ? A.t - b.y * k : A.t + (A.h - b.h * k) / 2 - b.y * k;
    applyCam(anim);
  }
  function fitCurrent(anim) { S.moved = false; fit(S.mode === 'focus' && S.fbounds ? S.fbounds : S.model && S.model.bounds, anim) }
  function zoomAt(f, px, py, anim) {
    const k = Math.min(2.5, Math.max(0.15, S.cam.k * f)); f = k / S.cam.k;
    S.cam.x = px - (px - S.cam.x) * f; S.cam.y = py - (py - S.cam.y) * f; S.cam.k = k; S.moved = true; applyCam(anim);
  }
  const zoomBtn = z => { const A = visArea(); if (z === 'fit') fitCurrent(true); else zoomAt(z === '+' ? 1.25 : 0.8, A.l + A.w / 2, A.t + A.h / 2, true) };

  // 拖动 / 双指缩放 / 滚轮
  const pts = new Map(); let drag = null, pinch = null, suppress = false;
  stage.addEventListener('pointerdown', e => {
    if (e.button !== 0 && e.pointerType === 'mouse') return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 1) drag = { x: e.clientX, y: e.clientY, cx: S.cam.x, cy: S.cam.y, moved: false };
    else if (pts.size === 2) { const [a, b] = [...pts.values()]; pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), k: S.cam.k }; drag = null }
  });
  addEventListener('pointermove', e => {
    if (!pts.has(e.pointerId)) return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinch && pts.size === 2) { const [a, b] = [...pts.values()], d = Math.hypot(a.x - b.x, a.y - b.y); zoomAt((pinch.k * d / pinch.d) / S.cam.k, (a.x + b.x) / 2, (a.y + b.y) / 2); suppress = true; return }
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < 5) return;
    drag.moved = true; suppress = true; stage.classList.add('tpl-grab');
    S.cam.x = drag.cx + dx; S.cam.y = drag.cy + dy; S.moved = true; applyCam(false);
  });
  const up = e => { pts.delete(e.pointerId); if (pts.size < 2) pinch = null; if (!pts.size) { drag = null; stage.classList.remove('tpl-grab'); setTimeout(() => suppress = false, 0) } };
  addEventListener('pointerup', up); addEventListener('pointercancel', up);
  stage.addEventListener('click', e => { if (suppress) { e.preventDefault(); e.stopPropagation(); suppress = false } }, true);
  stage.addEventListener('wheel', e => {
    e.preventDefault();
    if (e.ctrlKey || e.metaKey) zoomAt(Math.exp(-e.deltaY * 0.01), e.clientX, e.clientY);
    else { S.cam.x -= e.deltaX; S.cam.y -= e.deltaY; S.moved = true; applyCam(false) }
  }, { passive: false });
  let rt = null; addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => { const v = narrow(); if (v !== S.vert) { S.vert = v; drawGlobal() } if (!S.moved) fitCurrent(false) }, 150) });
  S.vert = narrow();

  // ---------------------------------------------------------------- AI 洞察（右下角）
  function insightFor() {
    const b = S.brief, h = S.hash;
    if (S.mode === 'focus' && S.focus) {
      const p = periodOf(S.focus) || {}, nx = p['下一步'] || {}, sk = stageOf(p), link = '#/p/' + S.focus;
      const ag = actsOf(link);
      const g = b && b['关系'] && b['关系']['标题'] === S.focus ? b['关系']['洞察'] : null;
      return {
        tag: `AI 洞察 · ${STAGES[SI(sk)].ins}`, title: (g && g['标题']) || nx['文字'] || (p['事项'] ? (p['说明'] || p['状态'] || '') : '在推进'),
        body: (g && g['内容']) || nx['说明'] || '',
        who: nx['谁'], acts: ag, js: judgOf(link), all: judgments().length
      };
    }
    const route = h.startsWith('/bugs') ? '#/bugs' : h.startsWith('/anr') ? '#/anr' : '';
    if (!b) return { tag: 'AI 洞察', title: '正在读取…', body: '', acts: [], js: [], all: 0 };
    const n = b['叙述'] || {};
    const js = route ? judgOf(route) : judgments();
    return { tag: `AI 洞察 · ${(b['状态'] || {})['名称'] || ''}`, title: n['标题'] || b['问候'] || '', body: n['正文'] || '', cites: n['引用'] || [], acts: acts().filter(a => !route || a['链接'] === route), js, all: judgments().length };
  }
  function drawInsight() {
    const box = $('#tplInsight'); if (!box) return;
    const I = insightFor(), jn = I.js.length;
    const dockMode = (docked() && S.mode !== 'home' && !document.body.classList.contains('tpl-peek')) || S.mode === 'drawer' || (narrow() && S.mode === 'home');   // 抽屉占满屏 / 普通抽屉页：洞察默认收成一颗胶囊
    const col = dockMode ? !S.dockOpen : S.insCollapsed;
    box.classList.toggle('tpl-col', col);
    box.classList.toggle('tpl-asking', jn > 0);
    if (col) {
      box.innerHTML = `<button type="button" class="tpl-ipill" id="tplInsT" aria-expanded="false"><i class="tpl-pulse ${acts().some(a => !a['等你']) ? '' : 'idle'}"></i>AI 洞察${jn ? `<b>${jn} 件需要你判断</b>` : ''}</button>`;
      $('#tplInsT').onclick = () => { if (dockMode) S.dockOpen = true; else { S.insCollapsed = false; LS('ins', '0') } drawInsight(); if (!S.moved && S.mode === 'home') fitCurrent(true) };
      return;
    }
    const working = I.acts.filter(a => !a['等你']);
    const body = esc(I.body).replace(/\[(\d+)\]/g, (_, i) => { const c = (I.cites || [])[i - 1]; return c && c['链接'] ? `<a href="${esc(c['链接'])}"><sup>${i}</sup></a>` : `<sup>${i}</sup>` });
    const showJ = I.js.slice(0, S.insAll ? 8 : (docked() ? 1 : 2));
    box.innerHTML = `<div class="tpl-ihd"><span class="tpl-itag"><i class="tpl-pulse ${working.length ? '' : 'idle'}"></i>${esc(I.tag)}</span><span class="tpl-sp"></span>
        <button type="button" class="tpl-tb tpl-ix" id="tplInsT" title="收起" aria-expanded="true" aria-label="收起 AI 洞察">–</button></div>
      <div class="tpl-ib"><b class="tpl-ititle">${esc(I.title)}</b>${body ? `<p class="tpl-ibody">${body}</p>` : ''}
      ${working.length ? `<div class="tpl-iacts">${working.slice(0, 3).map(a => `<a href="${esc(a['链接'] || '#/')}" class="tpl-iact"><i style="background:${esc(a['颜色'])}">${esc(a['角色'][0])}</i><span><b>${esc(a['角色'])}</b> ${esc(a['状态'])}${(a['步骤'] || []).length ? `<small class="tpl-caret">${esc(a['步骤'][a['步骤'].length - 1])}</small>` : ''}</span></a>`).join('')}</div>` : I.who === 'AI' ? '<div class="tpl-iacts tpl-mut">AI 会接着往下做，暂时不需要你。</div>' : ''}
      ${jn ? `<div class="tpl-ijh">需要你判断 <span>${jn} 件</span></div><div class="kbt tpl-kbt">${showJ.map(j => `<div class="tpl-ij">${KBUI.judg(j)}</div>`).join('')}</div>
        ${jn > showJ.length ? `<button type="button" class="tpl-more" id="tplInsMore">还有 ${jn - showJ.length} 件</button>` : ''}` : `<div class="tpl-iok">${I.all && S.mode === 'focus' ? `这一期没有要你判断的事；别处还有 ${I.all} 件。` : '现在没有需要你判断的事。'}</div>`}
      </div>`;
    if (window.KBUI) { KBUI.css(); KBUI.bind(box, S.brief || {}, briefOpts) }
    $('#tplInsT').onclick = () => { if (dockMode) S.dockOpen = false; else { S.insCollapsed = true; LS('ins', '1') } drawInsight(); if (!S.moved && S.mode === 'home') fitCurrent(true) };
    const mo = $('#tplInsMore'); if (mo) mo.onclick = () => { S.insAll = true; drawInsight() };
  }

  // ---------------------------------------------------------------- 弹出菜单：筛选 / 地点 / 更多
  const pop = $('#tplPop');
  function openPop(anchor, html, bind) {
    if (!pop.hidden && pop._a === anchor) { closePop(); return }
    pop.innerHTML = html; pop.hidden = false; pop._a = anchor;
    const r = anchor.getBoundingClientRect();
    pop.style.left = Math.max(8, Math.min(r.left, innerWidth - pop.offsetWidth - 8)) + 'px'; pop.style.top = (r.bottom + 8) + 'px';
    bind && bind(pop);
    const f = pop.querySelector('a,button'); if (f) f.focus({ preventScroll: true });
  }
  function closePop() { pop.hidden = true; pop._a = null }
  document.addEventListener('pointerdown', e => { if (!pop.hidden && !pop.contains(e.target) && !e.target.closest('[aria-haspopup]')) closePop() });
  pop.addEventListener('click', e => { if (e.target.closest('a[href]')) closePop() });
  const filterHtml = () => `<div class="tpl-ph">筛选画布</div>${FILTERS.map(([k, t]) => `<button type="button" class="tpl-pi ${S.filter === k ? 'on' : ''}" data-f="${k}">${esc(t)}</button>`).join('')}`;
  const bindFilter = p => p.querySelectorAll('[data-f]').forEach(b => b.onclick = () => { S.filter = b.dataset.f; LS('filter', S.filter); applyFilter(); closePop(); if (S.mode !== 'home') location.hash = '#/' });
  function placesHtml() {
    const s = S.site || {}, nav = (s['导航'] || []).filter(x => x['链接'] !== '#/');
    return `<div class="tpl-ph">地点</div>${nav.map(x => `<a class="tpl-pi" href="${esc(x['链接'])}"><span>${esc(x['图标'])}</span>${esc(x['名称'])}${x['数'] ? `<em>${esc(x['数'])}</em>` : ''}</a>`).join('')}
      <a class="tpl-pi" href="#/classic"><span>▦</span>经典总览</a><a class="tpl-pi" href="#/list"><span>☰</span>全部列表</a>
      ${(s['文档'] || []).length ? `<div class="tpl-ph">文档</div>${s['文档'].slice(0, 6).map(d => `<a class="tpl-pi" href="${esc(d['链接'])}"><span>¶</span>${esc(d['名称'])}</a>`).join('')}` : ''}
      <div class="tpl-ph">新建</div><button type="button" class="tpl-pi" data-add="new"><span>＋</span>新建一期</button><button type="button" class="tpl-pi" data-add="task"><span>＋</span>新建事项</button><button type="button" class="tpl-pi" data-add="add"><span>＋</span>模糊添加</button>
      <div class="tpl-ph">界面</div><a class="tpl-pi" href="/?ui=classic"><span>↗</span>临时看经典版</a><button type="button" class="tpl-pi" data-back><span>↺</span>换回经典界面</button>`;
  }
  const bindPlaces = p => {
    p.querySelectorAll('[data-add]').forEach(b => b.onclick = () => { closePop(); KB.addDlg(b.dataset.add) });
    const bk = p.querySelector('[data-back]'); if (bk) bk.onclick = () => { if (confirm('把界面换回经典（会改设置）？')) KB.setTemplate('经典') };
  };
  $('#tplFilterBtn').onclick = e => openPop(e.currentTarget, filterHtml(), bindFilter);
  $('#tplPlacesBtn').onclick = e => openPop(e.currentTarget, placesHtml(), bindPlaces);
  $('#tplMoreBtn').onclick = e => openPop(e.currentTarget, `<div class="tpl-ph">视图</div><div class="tpl-prow"><button type="button" class="tpl-tb" data-zoom="-">−</button><button type="button" class="tpl-tb" data-zoom="fit">⤢ 适应</button><button type="button" class="tpl-tb" data-zoom="+">+</button><a class="tpl-tb" href="#/list">☰ 列表</a><button type="button" class="tpl-tb" data-theme>◐ 主题</button></div>` + filterHtml() + placesHtml(), p => {
    bindFilter(p); bindPlaces(p);
    p.querySelectorAll('[data-zoom]').forEach(b => b.onclick = () => zoomBtn(b.dataset.zoom));
    p.querySelector('[data-theme]').onclick = cycleTheme;
  });
  document.querySelectorAll('#tplTools [data-zoom]').forEach(b => b.onclick = () => zoomBtn(b.dataset.zoom));
  function cycleTheme() { const t = THEMES[(THEMES.indexOf(LS('theme') || '') + 1) % 3]; LS('theme', t); applyTheme(t); KB.toast('主题：' + THEME_N[t]) }
  $('#tplTheme').onclick = cycleTheme;
  $('#tplAsk').onclick = () => KB.askOpen(true);
  const peek = on => { document.body.classList.toggle('tpl-peek', on); if (!on) return; scrollTo(0, 0); S.moved = false; drawInsight(); setTimeout(() => fitCurrent(true), 30) };
  $('#tplPeek').onclick = () => peek(true);
  $('#tplUnpeek').onclick = () => { peek(false); drawInsight() };
  $('#tplWide').onclick = () => { S.wide = !S.wide; document.body.classList.toggle('tpl-wide', S.wide); setTimeout(() => { if (!S.moved) fitCurrent(true) }, 320) };

  // 键盘：/ 搜索、Esc 收起、+ - 0 缩放
  addEventListener('keydown', e => {
    const typing = e.target.matches && e.target.matches('input,textarea,select,[contenteditable]');
    if (e.key === 'Escape') { if (!pop.hidden) { closePop(); return } if (!typing && !$('#dlg').open && $('#askPanel').hidden && S.mode !== 'home') location.hash = '#/'; return }
    if (typing || e.metaKey || e.ctrlKey || e.altKey || $('#dlg').open) return;
    if (e.key === '/') { e.preventDefault(); $('#q').focus() }
    else if (S.mode === 'home' || S.mode === 'focus') { if (e.key === '+' || e.key === '=') zoomBtn('+'); else if (e.key === '-') zoomBtn('-'); else if (e.key === '0') zoomBtn('fit') }
  });

  // 管家面板开着时洞察让位
  new MutationObserver(() => document.body.classList.toggle('tpl-asking-open', !$('#askPanel').hidden)).observe($('#askPanel'), { attributes: true, attributeFilter: ['hidden'] });

  // ---------------------------------------------------------------- 列表视图（#/list）：画布的无障碍 / 手机替代
  KB.routes['/list'] = async () => {
    if (!S.site) { try { S.site = await KB.site() } catch (_) { } }
    const s = S.site || { 期: [] }, js = judgments();
    const jl = new Set(js.map(j => j['链接']));
    const row = p => { const nx = p['下一步'] || {}, a = actsOf(p['链接'])[0];
      return `<a class="tpl-lrow ${p['在跑'] || a ? 'hot' : ''} ${jl.has(p['链接']) || p['待确认'] ? 'ask' : ''} ${p['没解决Bug'] ? 'bad' : ''}" href="${esc(p['链接'])}">
        <span class="tpl-lk">${p['事项'] ? '事项' : '期'}</span><span class="tpl-lm"><b>${esc(p['名称'])}</b><small>${a ? `<i class="tpl-pulse"></i>${esc(a['角色'])}：${esc(a['状态'])}` : nx['文字'] ? (nx['谁'] === '你' ? '需要你：' : '下一步：') + esc(nx['文字']) : esc(p['说明'] || '')}</small></span>
        <span class="tpl-lr">${p['当前步骤'] ? `<em>${esc(p['当前步骤'])}</em>` : ''}${KB.badge(p['状态'])}${p['待确认'] ? `<b class="a">? ${p['待确认']}</b>` : ''}${p['没解决Bug'] ? `<b class="b">● ${p['没解决Bug']}</b>` : ''}</span></a>` };
    KB.app.innerHTML = `<div class="pagehead"><div><div class="crumb">画布 / 列表</div><h1>全部节点</h1><p class="mut">画布上的东西按阶段排成列表。点一行打开详情，<a href="#/">回到画布</a>。</p></div>
      <div class="row"><button type="button" id="tplLNew">＋ 新建一期</button><button type="button" id="tplLTask">＋ 新建事项</button></div></div>
      ${STAGES.map(st => { const ps = (s['期'] || []).filter(p => stageOf(p) === st.k); return `<section class="tpl-lsec"><h2><span class="tpl-zi">${SI(st.k) + 1}</span>${esc(st.n)} <span class="mut small">${ps.length} · ${esc(st.d)}</span></h2>
        ${st.k === 'online' ? `<a class="tpl-lrow ${(s['Bug'] || {})['未关闭'] ? 'bad' : ''}" href="#/bugs"><span class="tpl-lk">问题</span><span class="tpl-lm"><b>🐞 Bug</b><small>未关闭 ${(s['Bug'] || {})['未关闭'] || 0} · 待归纳 ${(s['Bug'] || {})['待归纳'] || 0}</small></span></a>
          <a class="tpl-lrow ${(s['ANR'] || {})['待处理'] ? 'bad' : ''}" href="#/anr"><span class="tpl-lk">问题</span><span class="tpl-lm"><b>💥 ANR / 崩溃</b><small>待处理 ${(s['ANR'] || {})['待处理'] || 0} · 共 ${(s['ANR'] || {})['总数'] || 0}</small></span></a>` : ''}
        ${ps.map(row).join('') || (st.k === 'online' ? '' : '<p class="mut small">这一阶段没有东西。</p>')}</section>` }).join('')}
      <section class="tpl-lsec"><h2>基地</h2><div class="tpl-lgrid">${(s['导航'] || []).filter(x => x['链接'] !== '#/').map(x => `<a class="tpl-lst" href="${esc(x['链接'])}"><span>${esc(x['图标'])}</span><b>${esc(x['名称'])}</b>${x['数'] ? `<em>${esc(x['数'])}</em>` : ''}</a>`).join('')}<a class="tpl-lst" href="#/classic"><span>▦</span><b>经典总览</b></a></div></section>`;
    $('#tplLNew').onclick = () => KB.addDlg('new'); $('#tplLTask').onclick = () => KB.addDlg('task');
  };

  // ---------------------------------------------------------------- 首页 = 全局画布
  KB.pages.home = async () => {
    KB.app.innerHTML = `<h1 class="tpl-sr">项目地图</h1><p class="tpl-sr">全局画布：<a href="#/list">用列表看全部节点</a></p>`;
    if (!S.brief) await loadBrief(true);
    drawGlobal();
  };

  // ---------------------------------------------------------------- 导航钩子：数据来了就重画画布
  let drawT = null;
  function scheduleDraw() { cancelAnimationFrame(drawT); drawT = requestAnimationFrame(() => { const ch = drawGlobal(); if (S.mode === 'focus' && S.focus) drawFocus(S.focus); else if (ch && !S.moved) { fitCurrent(!!S.fitted); S.fitted = true } drawInsight() }) }
  KB.hooks.nav = (d, site) => { if (site) { S.site = site; scheduleDraw() } };

  // ---------------------------------------------------------------- 每次换页：模式、抽屉、面包屑、标题
  const NAMES = { '/bugs': ['🐞', 'Bug'], '/anr': ['💥', 'ANR / 崩溃'], '/phones': ['▯', '手机'], '/base': ['◈', '基础信息'], '/settings': ['⚙', '设置'], '/classic': ['▦', '经典总览'], '/list': ['☰', '列表'] };
  KB.hooks.afterRender = h => {
    const prev = S.hash, prevMode = S.mode, prevFocus = S.focus;
    S.hash = h;
    let mode = 'drawer', crumb = '', title = '';
    if (h === '/' || h === '') { mode = 'home'; title = '画布' }
    else if (h.startsWith('/p/')) { mode = 'focus'; S.focus = h.slice(3); const p = periodOf(S.focus); crumb = `<span>${p && p['事项'] ? '事项' : '期'} · ${esc(STAGES[SI(stageOf(p))].n)}</span><b>${esc(S.focus)}</b>`; title = S.focus }
    else if (h.startsWith('/d/')) { crumb = `<span>文档</span><b>${esc(h.slice(3) || '使用说明')}</b>`; title = '文档' }
    else if (h.startsWith('/s/')) { const q = h.slice(3).split('\u0001')[0]; crumb = `<span>搜索</span><b>${esc(q)}</b>`; title = '搜索 ' + q; $('#q').value = q }
    else if (h.startsWith('/tool/')) { const t = ((S.site && S.site['工具']) || []).find(x => x.id === h.slice(6)); crumb = `<span>工具</span><b>${esc(t ? t['名称'] : h.slice(6))}</b>`; title = t ? t['名称'] : '工具' }
    else { const n = NAMES[h]; crumb = n ? `<b>${n[0]} ${esc(n[1])}</b>` : `<b>${esc(h)}</b>`; title = n ? n[1] : h }
    if (mode !== 'focus') S.focus = null;
    S.mode = mode;
    document.title = (title ? title + ' · ' : '') + '知识库 · 画布';
    $('#tplCrumb').innerHTML = `<a href="#/" class="tpl-cm">◎ 画布</a>${crumb ? '<i>›</i>' + crumb : ''}`;
    const open = mode !== 'home';
    const wideRoute = mode === 'drawer' && h !== '/list';
    document.body.classList.toggle('tpl-open', open);
    document.body.classList.toggle('tpl-wide', open && (wideRoute || S.wide));
    document.body.classList.toggle('tpl-mfocus', mode === 'focus');
    document.body.dataset.tplMode = mode;
    if (mode !== 'focus') { $('#tplFocus').innerHTML = ''; $('#tplFEdges').innerHTML = ''; S.lastF = '' }
    const changed = prev !== h;
    if (changed) {
      closePop(); document.body.classList.remove('tpl-peek');
      if (open && (prevMode === 'home' || prevMode !== mode || prevFocus !== S.focus)) { scrollTo(0, 0); const d = $('#tplDrawer'); if (!reduced.matches) { d.classList.remove('tpl-in'); void d.offsetWidth; d.classList.add('tpl-in') } }
      S.moved = false; S.insAll = false; S.dockOpen = false;
    }
    // 期页面的「谁」：措辞改成判断 / AI 在做
    document.querySelectorAll('#tplApp .gnext .who').forEach(w => { if (w.classList.contains('w-你')) w.textContent = '需要你判断'; else if (w.classList.contains('w-AI')) w.textContent = 'AI 在做' });
    if (!S.brief) loadBrief(true);
    if (mode === 'focus') drawFocus(S.focus, changed);
    else if (S.model && (changed || !S.fitted)) { setTimeout(() => fitCurrent(changed && prevMode !== 'home' || prevMode === 'focus'), changed ? 30 : 0); S.fitted = true }
    drawInsight();
  };
})();
