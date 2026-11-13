// From 大大王.DT
/* 界面模板「指挥台」：整个网站围绕一个会理解你的输入框。
 * - 没有导航栏：顶部输入框 = 搜索 + 跳转 + 交给管家，输入时实时显示「我的理解」（/api/intake/preview）；⌘K / Ctrl+K 打开命令面板。
 * - 首页：问候 + 输入框（居中）+ 需要你判断的事 + AI 在后台做的事 + 进行中的期；按当前阶段（收集资料 → 方案拍板 → 并行开发 → 验收上线 → 线上维护）调整先后。
 * - 其他页面：作为「工作区」出现在输入框下方，上面是面包屑 + 与当前上下文相关的建议（AI 的下一步判断、在跑的 AI、需要你判断的事）。
 * - 期详情：core 渲染的各板块（资料 / 全栈 / 开发 / 构建 / Bug / 记录）按流程顺序排成可折叠段落，当前阶段的段落展开并高亮。
 * 功能页面都由 core 渲染（KB.pages.*），这里只做骨架、导航、首页和布局调整。契约见 /ui/core.js 顶部。
 */
(function () {
  'use strict';
  const TPL = '指挥台';
  const q = s => document.querySelector(s);
  const E = KB.esc, N = KB.enc;
  const S = { site: null, brief: null, briefSig: '', open: {}, under: [], uSel: 0, pal: [], pSel: 0, prevSeq: 0 };
  const isMac = /Mac|iPhone|iPad/.test(navigator.platform || '');
  const ls = { get(k) { try { return localStorage.getItem(k) } catch (_) { return null } }, set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v) } catch (_) {} } };
  try { S.open = JSON.parse(ls.get('tpl.secs') || '{}') || {} } catch (_) { S.open = {} }

  KB.setApp('#tplApp');

  // ───────────────────────────────────────────── 数据
  async function loadSite() { try { S.site = await KB.site() } catch (_) {} return S.site }
  async function loadBrief() {
    try {
      const b = await KB.api('/api/brief'), sig = JSON.stringify(b).replace(/"时间":"[^"]*"/, '');
      const changed = sig !== S.briefSig; S.brief = b; S.briefSig = sig; return changed;
    } catch (_) { return false }
  }
  const periods = () => (S.site && S.site['期']) || [];
  const entry = n => periods().find(p => p['名称'] === n);
  const judgs = () => (S.brief && S.brief['判断']) || [];
  const acts = () => (S.brief && S.brief['活动']) || [];
  const curHash = () => KB.curHash();

  // ───────────────────────────────────────────── 阶段：收集资料 → 方案拍板 → 并行开发 → 验收上线 → 线上维护
  const PHASES = [['collect', '收集资料'], ['plan', '方案拍板'], ['build', '并行开发'], ['accept', '验收上线'], ['run', '线上维护']];
  const PH_FOCUS = {
    collect: '把资料收齐。缺什么我标出来了，贴链接或拖文件给我就行。',
    plan: '方案阶段：AI 出方案，你来拍板。判断依据都摆在下面。',
    build: '各端在并行开发。AI 互相审查，有拿不准的才会停下来问你。',
    accept: '做完了，等你验收。看证据包和审查结论，再决定推送。',
    run: '线上维护：Bug、ANR 和反馈由 AI 先做只读分析，结论等你审核。'
  };
  const PH_HOLDER = {
    collect: '贴需求链接、设计稿、接口文档，或者直接问我……',
    plan: '对方案有意见？直接说，或者搜索、跳转……',
    build: '补充给正在开发的 AI，或者搜索、跳转……',
    accept: '说说验收时发现的问题，或者搜索、跳转……',
    run: '贴 ANR 日志、Bug 链接、用户反馈……或者搜索、跳转'
  };
  function phaseOf(p) {
    if (!p) return 'run';
    if (p['状态'] === '已完成') return 'run';
    const c = p['当前步骤'] || '';
    if (/资料|仓库/.test(c)) return 'collect';
    if (/方案|拍板/.test(c)) return 'plan';
    if (/开始开发|开发/.test(c)) return 'build';
    if (/验收|完成/.test(c)) return 'accept';
    return { '收集中': 'collect', '已批准开发': 'build', '开发中': 'build' }[p['状态']] || 'run';
  }
  function focusPeriod() {
    const g = S.brief && S.brief['关系'];
    const live = periods().filter(p => !p['事项'] && !['已完成', '已暂停'].includes(p['状态']));
    return (g && entry(g['标题'])) || live.sort((a, b) => (b['更新时间'] || '').localeCompare(a['更新时间'] || ''))[0] || null;
  }

  // ───────────────────────────────────────────── 小组件
  const conf = p => p == null ? '' : `<span class="tpl-conf" title="AI 的把握">把握<i><b style="width:${+p}%"></b></i>${+p}%</span>`;
  const dot = c => `<span class="tpl-dot" style="--c:${E(c || 'var(--tpl-a)')}"></span>`;
  const briefOpts = {
    act: async (id, action, x) => {
      try { const r = await KB.post('/api/brief/act', { id, action, ...x }); KB.toast(String(r.msg || '好的').split('\n')[0]) } catch (e) { KB.toast(e.message) }
      await Promise.all([loadBrief(), loadSite()]); paintChrome(); if (curHash() === '/') KB.pages.home(); else KB.softRender();
    },
    ask: t => askSend(t),
    preview: t => KB.api('/api/intake/preview?text=' + N(t)),
    openAsk: () => KB.askOpen(true)
  };
  // 判断卡：用共用的 KBUI.judg（按钮行为一致），外面包一层本模板的样式
  function judgHtml(list, opt) {
    if (!window.KBUI || !list.length) return '';
    KBUI.css();
    return `<div class="kbt tpl-judgs">${list.map(j => `<div class="tpl-judg">${j['类型'] ? `<span class="tpl-jt">${E(j['类型'] === '问你' ? 'AI 想确认' : j['类型'] === '待你' ? '需要你判断' : j['类型'])}</span>` : ''}${KBUI.judg(j, opt || {})}</div>`).join('')}</div>`;
  }
  function bindJudg(root) { if (window.KBUI && root && S.brief) KBUI.bind(root, S.brief, briefOpts) }
  function actRow(a) {
    const last = (a['步骤'] || []).slice(-1)[0] || '';
    return `<a class="tpl-act ${a['等你'] ? 'is-ask' : ''}" href="${E(a['链接'] || '#/')}">${dot(a['颜色'])}<span class="tpl-actw"><b>${E(a['角色'])}</b><span class="tpl-mut"> · ${E(a['对象'])}</span></span>
      <span class="tpl-acts ${a['等你'] ? 'is-ask' : ''}">${a['等你'] ? '需要你判断' : E(a['状态'])}</span>${last ? `<span class="tpl-actlog ${a['等你'] ? '' : 'tpl-caret'}">${E(last)}</span>` : ''}${a['开始'] ? `<span class="tpl-mut tpl-sm" data-since="${E(a['开始'])}">${E(KB.since(a['开始']))}</span>` : ''}</a>`;
  }
  function track(p) {
    const st = p['步骤'] || [];
    if (!st.length) return `<span class="tpl-mut tpl-sm">${E(p['状态'])}</span>`;
    return `<span class="tpl-track">${st.map(s => `<i class="is-${E(s['状态'])}" title="${E(s['名称'])}"><em>${E(s['名称'])}</em></i>`).join('')}</span>`;
  }
  function spark(v) {
    if (!v || !v.length) return '';
    const mx = Math.max(...v, 1), pts = v.map((y, i) => `${(i / Math.max(1, v.length - 1) * 100).toFixed(1)},${(26 - y / mx * 22).toFixed(1)}`).join(' ');
    return `<svg class="tpl-sparkline" viewBox="0 0 100 28" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="var(--tpl-a)" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
  }
  const whoLabel = w => w === '你' ? '需要你判断' : w === 'AI' ? 'AI 在推进' : '';

  // ───────────────────────────────────────────── 交给管家（真正会启动管家；页面上只在用户按回车时调用）
  async function askSend(text) {
    try { await KB.post('/api/chat/ask', { text, page: curHash() }); KB.askOpen(true) } catch (e) { KB.toast(e.message) }
  }

  // ───────────────────────────────────────────── 命令：所有期、事项、页面、常用动作
  function themeCycle() {
    const r = document.documentElement, cur = r.dataset.theme || '';
    const nx = cur === '' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'light' : 'dark') : '';
    if (nx) r.dataset.theme = nx; else delete r.dataset.theme;
    ls.set('tpl.theme', nx || null); KB.toast(nx === 'dark' ? '深色' : nx === 'light' ? '浅色' : '跟随系统');
  }
  function commands() {
    const s = S.site || {}, out = [];
    const add = (g, t, sub, go, extra) => out.push({ g, t, sub: sub || '', go, ...(extra || {}) });
    add('页面', '首页', '问候、需要你判断的事、AI 在做的事', '#/', { ico: '◎' });
    const bug = s['Bug'] || {}, anr = s['ANR'] || {}, ph = s['手机'], base = s['基础信息'] || {};
    add('页面', 'Bug', `未关闭 ${bug['未关闭'] || 0} · 待归纳 ${bug['待归纳'] || 0}`, '#/bugs', { ico: '🐞', kw: 'bug 缺陷 禅道 jira' });
    add('页面', 'ANR / 崩溃', `待处理 ${anr['待处理'] || 0} · 共 ${anr['总数'] || 0}`, '#/anr', { ico: '💥', kw: 'anr crash 崩溃 日志 traces' });
    if (ph) add('页面', '手机', `空闲 ${ph['空闲']}/${ph['总数']}`, '#/phones', { ico: '▯', kw: 'phone 设备 adb' });
    add('页面', '基础信息', `${base['条数'] || 0} 条：账号、环境、地址`, '#/base', { ico: '◈', kw: 'base 账号 密码 环境' });
    add('页面', '设置', '界面模板、AI 引擎、开发流程、管家、插件', '#/settings', { ico: '⚙', kw: 'settings 配置' });
    add('页面', '帮助文档', '使用说明', '#/d/', { ico: '?', kw: 'docs help 文档 说明' });
    add('页面', '经典总览', '所有期的卡片、统计、仓库', '#/classic', { ico: '▦', kw: 'classic overview 全部 总览' });
    (s['工具'] || []).forEach(t => add('工具', t['名称'], t['说明'] || t['提示'] || '', t['链接'] || '#/tool/' + N(t.id), { ico: t['图标'] || '✦' }));
    (s['文档'] || []).forEach(d => add('文档', d['名称'], '文档', d['链接'], { ico: '¶' }));
    periods().filter(p => !p['事项']).forEach(p => add('期', p['名称'], [p['当前步骤'] ? '在「' + p['当前步骤'] + '」' : p['状态'], p['下一步'] && p['下一步']['文字']].filter(Boolean).join(' · '), p['链接'], { ico: '◆', st: p['状态'] }));
    periods().filter(p => p['事项']).forEach(p => add('事项', p['名称'], [p['事项类型'], p['状态'], p['说明']].filter(Boolean).join(' · '), p['链接'], { ico: '◇', st: p['状态'] }));
    add('动作', '交给管家', '打开对话：贴需求、日志、Bug、账号，或拖文件', null, { ico: '↗', run: () => KB.askOpen(true), kw: 'ask chat 管家 问' });
    add('动作', '新建一期', '手动建一个需求期', null, { ico: '＋', run: () => KB.addDlg('new'), kw: 'new 新建 期' });
    add('动作', '新建事项', 'ANR、埋点、线上问题、优化、调研……', null, { ico: '＋', run: () => KB.addDlg('task'), kw: 'task 新建 事项' });
    add('动作', '模糊添加', '一段文字，AI 判断放到哪', null, { ico: '✦', run: () => KB.addDlg('add'), kw: 'add 添加' });
    add('动作', '切换深色 / 浅色', '在 跟随系统 / 深色 / 浅色 之间切换', null, { ico: '◐', run: themeCycle, kw: 'theme dark light 主题 深色 浅色' });
    add('动作', '临时看经典版', '不改设置', null, { ico: '↺', run: () => { location.href = '/?ui=classic' + location.hash }, kw: 'classic 经典' });
    add('动作', '换回经典界面', '改设置：以后都用经典版', null, { ico: '↺', run: () => KB.setTemplate('经典'), kw: 'classic 经典 模板' });
    if (s['登录']) add('动作', '退出登录', '', null, { ico: '⏻', run: () => KB.logout(), kw: 'logout' });
    return out;
  }
  function match(list, text) {
    const t = text.trim().toLowerCase();
    if (!t) return list;
    const sc = c => { const a = c.t.toLowerCase(), b = (c.sub + ' ' + (c.kw || '') + ' ' + c.g).toLowerCase(); return a.startsWith(t) ? 3 : a.includes(t) ? 2 : b.includes(t) ? 1 : 0 };
    return list.map(c => [sc(c), c]).filter(x => x[0]).sort((x, y) => y[0] - x[0]).map(x => x[1]);
  }
  function runCmd(c) {
    if (!c) return;
    closePal(); closeUnder();
    if (c.run) return c.run();
    if (c.go) { if (location.hash === c.go || (c.go === '#/' && !location.hash)) KB.render(); else location.hash = c.go; }
  }
  const cmdRow = (c, i, sel) => `<div class="tpl-cmd ${i === sel ? 'on' : ''}" data-i="${i}" role="option"><span class="tpl-cmdi">${E(c.ico || '·')}</span><span class="tpl-cmdt"><b>${E(c.t)}</b>${c.sub ? `<span>${E(c.sub)}</span>` : ''}</span>${c.st ? KB.badge(c.st) : ''}<span class="tpl-cmdg">${E(c.g)}</span></div>`;

  // ───────────────────────────────────────────── 输入框：理解预览 + 匹配到的入口 + 交给管家 / 搜索
  const qEl = q('#tplQ'), under = q('#tplUnder');
  function grow() { qEl.style.height = 'auto'; qEl.style.height = Math.min(qEl.scrollHeight, 180) + 'px' }
  function closeUnder() { under.hidden = true; q('#tplOmni').classList.remove('is-open') }
  function looksLikeHandoff(t) { return t.length > 28 || /\n|https?:\/\/|\.(log|txt|zip)\b|anr|traces|exception|crash|bug[-\s]?\d|#\d+/i.test(t) }
  function drawUnder(prev) {
    const t = qEl.value.trim();
    if (!t) {   // 空：给几个可以直接去的地方（与当前上下文相关）
      const base = suggestCmds();
      S.under = base.map(c => ({ kind: 'cmd', c }));
      under.innerHTML = `<div class="tpl-uh">可以直接去 <span class="tpl-mut">· 输入任何东西：我先说看懂了什么，回车再做</span></div>` + S.under.map((x, i) => cmdRow(x.c, i, S.uSel)).join('');
    } else {
      const m = match(commands(), t).slice(0, 5);
      const hand = { kind: 'ask', c: { ico: '↗', t: '交给管家', sub: '归档到对应的期 / 事项，接着推动；要动代码会让你确认', g: '回车' } };
      const srch = { kind: 'search', c: { ico: '⌕', t: `在资料和代码里搜索「${t.slice(0, 30)}」`, sub: '全文检索', g: '搜索' } };
      const items = m.map(c => ({ kind: 'cmd', c }));
      S.under = looksLikeHandoff(t) || !items.length ? [hand, ...items, srch] : [...items, hand, srch];
      const p = prev === undefined ? under._prev : prev; under._prev = p;
      const understand = p === 'wait' ? `<div class="tpl-und is-wait"><span class="tpl-und-h">我的理解</span><span class="tpl-mut">正在看…</span></div>`
        : p ? `<div class="tpl-und"><div class="tpl-und-h"><b>我的理解</b>${conf(p['把握'])}</div><div class="tpl-tags">${(p['标签'] || []).map(([x, c]) => `<span class="tpl-tag is-${E(c)}">${E(x)}</span>`).join('')}</div>${p['计划'] ? `<div class="tpl-sm"><span class="tpl-mut">交给管家后：</span>${E(p['计划'])}</div>` : ''}</div>` : '';
      under.innerHTML = understand + S.under.map((x, i) => cmdRow(x.c, i, S.uSel)).join('');
    }
    under.hidden = false; q('#tplOmni').classList.add('is-open');
    under.querySelectorAll('.tpl-cmd').forEach(el => {
      el.onmousedown = e => e.preventDefault();
      el.onclick = () => { S.uSel = +el.dataset.i; doUnder() };
    });
  }
  function doUnder() {
    const x = S.under[S.uSel], t = qEl.value.trim();
    if (!x) return;
    if (x.kind === 'cmd') { qEl.value = ''; grow(); qEl.blur(); return runCmd(x.c) }
    if (x.kind === 'search') { qEl.value = ''; grow(); closeUnder(); qEl.blur(); location.hash = '#/s/' + N(t + '\u0001all'); return }
    if (x.kind === 'ask' && t) { qEl.value = ''; grow(); closeUnder(); qEl.blur(); askSend(t) }
  }
  let prevT = 0;
  qEl.addEventListener('input', () => {
    grow(); S.uSel = 0;
    const t = qEl.value.trim();
    clearTimeout(prevT);
    if (!t) { under._prev = null; return drawUnder(null) }
    drawUnder(under._prev ? undefined : 'wait');
    const seq = ++S.prevSeq;
    prevT = setTimeout(async () => {
      try { const r = await briefOpts.preview(t); if (seq === S.prevSeq) drawUnder(r) } catch (_) { if (seq === S.prevSeq) drawUnder(null) }
    }, 320);
  });
  qEl.addEventListener('focus', () => { if (!qEl.value.trim()) drawUnder(null); else drawUnder() });
  qEl.addEventListener('blur', () => setTimeout(closeUnder, 120));
  qEl.addEventListener('keydown', e => {
    if (e.isComposing) return;
    const n = S.under.length;
    if (e.key === 'ArrowDown' && n) { e.preventDefault(); S.uSel = (S.uSel + 1) % n; drawUnder() }
    else if (e.key === 'ArrowUp' && n) { e.preventDefault(); S.uSel = (S.uSel - 1 + n) % n; drawUnder() }
    else if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doUnder() }
    else if (e.key === 'Escape') { if (qEl.value) { qEl.value = ''; grow(); drawUnder(null) } else qEl.blur() }
  });
  // 拖文件到输入框：交给管家面板（它支持附件）
  qEl.addEventListener('dragover', e => { e.preventDefault(); q('#tplOmni').classList.add('is-drop') });
  qEl.addEventListener('dragleave', () => q('#tplOmni').classList.remove('is-drop'));
  qEl.addEventListener('drop', e => { e.preventDefault(); q('#tplOmni').classList.remove('is-drop'); KB.askOpen(true); KB.toast('文件请拖进管家对话框（右下角），我会一起归档') });

  // 与当前上下文相关的建议（空输入框、命令面板的默认列表）
  function suggestCmds() {
    const all = commands(), h = curHash(), out = [];
    const byGo = g => all.find(c => c.go === g);
    judgs().slice(0, 3).forEach(j => out.push({ g: '需要你判断', t: j['问题'], sub: j['建议'] ? 'AI 建议：' + j['建议'] : j['说明'] || '', go: j['链接'] || '#/', ico: '◇' }));
    const f = focusPeriod(); if (f && h !== '/p/' + f['名称']) out.push(byGo(f['链接']));
    if (h !== '/') out.push(byGo('#/'));
    ['#/bugs', '#/anr'].forEach(g => { if (h !== g.slice(1)) out.push(byGo(g)) });
    out.push(all.find(c => c.t === '交给管家'));
    return out.filter(Boolean).slice(0, 7);
  }

  // ───────────────────────────────────────────── 命令面板（⌘K）
  const pal = q('#tplPal'), palQ = q('#tplPalQ'), palL = q('#tplPalL');
  function drawPal() {
    const t = palQ.value, list = t.trim() ? match(commands(), t) : [...suggestCmds().map(c => ({ ...c, g: c.g === '需要你判断' ? c.g : '建议' })), ...commands()];
    S.pal = list.slice(0, 60); if (S.pSel >= S.pal.length) S.pSel = 0;
    let g = '';
    palL.innerHTML = S.pal.length ? S.pal.map((c, i) => { const h = c.g !== g ? `<div class="tpl-palg">${E(c.g)}</div>` : ''; g = c.g; return h + cmdRow(c, i, S.pSel) }).join('')
      : `<div class="tpl-empty">没找到。回车把「${E(t.trim())}」交给管家，或者 <a data-psearch>全文搜索</a></div>`;
    palL.querySelectorAll('.tpl-cmd').forEach(el => el.onclick = () => runCmd(S.pal[+el.dataset.i]));
    const ps = palL.querySelector('[data-psearch]'); if (ps) ps.onclick = () => { closePal(); location.hash = '#/s/' + N(t.trim() + '\u0001all') };
    const on = palL.querySelector('.tpl-cmd.on'); if (on) on.scrollIntoView({ block: 'nearest' });
  }
  function openPal() { closeUnder(); pal.hidden = false; palQ.value = ''; S.pSel = 0; drawPal(); setTimeout(() => palQ.focus(), 10) }
  function closePal() { if (!pal.hidden) { pal.hidden = true } }
  palQ.addEventListener('input', () => { S.pSel = 0; drawPal() });
  palQ.addEventListener('keydown', e => {
    if (e.isComposing) return;
    const n = S.pal.length;
    if (e.key === 'ArrowDown' && n) { e.preventDefault(); S.pSel = (S.pSel + 1) % n; drawPal() }
    else if (e.key === 'ArrowUp' && n) { e.preventDefault(); S.pSel = (S.pSel - 1 + n) % n; drawPal() }
    else if (e.key === 'Enter') { e.preventDefault(); if (n) runCmd(S.pal[S.pSel]); else if (palQ.value.trim()) { const t = palQ.value.trim(); closePal(); askSend(t) } }
    else if (e.key === 'Escape') { e.preventDefault(); closePal() }
  });
  pal.addEventListener('mousedown', e => { if (e.target === pal) closePal() });
  document.addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); pal.hidden ? openPal() : closePal(); return }
    if (e.key === '/' && !e.metaKey && !e.ctrlKey && !document.activeElement.matches('input,textarea,select,[contenteditable]') && !q('#dlg').open) { e.preventDefault(); qEl.focus() }
  });
  q('#tplK').onclick = openPal;
  q('#tplAsk').onclick = () => KB.askOpen(true);
  q('#tplPulse').onclick = () => { if (curHash() !== '/') location.hash = '#/'; else { const j = q('#tplJudg'); if (j) j.scrollIntoView({ behavior: 'smooth', block: 'start' }) } };
  q('#tplK').innerHTML = `<kbd>${isMac ? '⌘' : 'Ctrl'} K</kbd>`; q('#tplHint').innerHTML = `<kbd>${isMac ? '⌘' : 'Ctrl'} K</kbd>`;

  // ───────────────────────────────────────────── 顶部：AI 状态（脉搏）、问候、阶段
  function paintChrome() {
    const b = S.brief || {}, st = b['状态'] || {}, home = curHash() === '/';
    const nW = st['在工作'] || 0, nJ = judgs().length;
    const p = q('#tplPulse');
    p.innerHTML = `${nW ? '<span class="tpl-live"></span>' : '<span class="tpl-dot" style="--c:var(--mut)"></span>'}<span>${nW ? nW + ' 个 AI 在工作' : 'AI 在待命'}</span>${nJ ? `<span class="tpl-pj">${nJ} 件需要你判断</span>` : ''}`;
    p.classList.toggle('has-j', !!nJ);
    q('#tplGreet').textContent = b['问候'] || '你好';
    const f = focusPeriod(), ph = phaseOf(f);
    q('#tplSay').innerHTML = (b['叙述'] && b['叙述']['正文']) ? sayHtml(b['叙述']) : '';
    qEl.placeholder = home ? PH_HOLDER[ph] : '搜索、跳转，或把任何东西交给我…';
    document.body.dataset.tplPhase = ph;
  }
  function sayHtml(n) {
    const cites = n['引用'] || [];
    return E(n['正文'] || '').replace(/\[(\d+)\]/g, (_, i) => { const c = cites[i - 1]; return c && c['链接'] ? `<a class="tpl-cite" href="${E(c['链接'])}" title="${E(c['文字'])}">${i}</a>` : `<sup class="tpl-cite" title="${E(c ? c['文字'] : '')}">${i}</sup>` });
  }

  // ───────────────────────────────────────────── 首页
  KB.pages.home = async function () {
    if (!S.brief) await loadBrief();
    if (!S.site) await loadSite();
    paintChrome();
    const b = S.brief || {}, st = b['状态'] || {}, f = focusPeriod(), ph = phaseOf(f);
    const js = judgs(), as = acts(), mets = b['指标'] || [];
    const prog = periods().filter(p => !p['事项'] && !['已完成', '已暂停'].includes(p['状态']));
    const tasks = periods().filter(p => p['事项'] && p['状态'] !== '已完成');
    const done = periods().filter(p => !p['事项'] && p['状态'] === '已完成');
    const site = S.site || {}, bug = site['Bug'] || {}, anr = site['ANR'] || {}, phn = site['手机'];
    const secs = {};
    secs.judg = `<section class="tpl-hs" id="tplJudg"><h2 class="tpl-h"><span>需要你判断</span>${js.length ? `<span class="tpl-n">${js.length}</span>` : ''}<span class="tpl-hsub">AI 附了建议、理由和把握，你点了才算数</span></h2>
      ${js.length ? judgHtml(js) : `<p class="tpl-quiet">现在没有需要你判断的事。AI 们按自己的判断在推进，有拿不准的会出现在这里。</p>`}</section>`;
    const w7 = (mets[0] && mets[0]['趋势']) || [];
    secs.acts = `<section class="tpl-hs"><h2 class="tpl-h"><span>AI 在后台做的事</span>${as.length ? `<span class="tpl-n is-ai">${as.length}</span>` : ''}<span class="tpl-hsub">今天替你完成 ${st['今天完成'] || 0} 件</span>${w7.length ? `<span class="tpl-hsp" title="近 7 天管家替你做的事">${spark(w7)}</span>` : ''}</h2>
      ${as.length ? `<div class="tpl-acts-l">${as.map(actRow).join('')}</div>` : `<p class="tpl-quiet">现在没有 AI 在跑。${mets[1] && mets[1]['说明'] ? E(mets[1]['说明']) + '。' : ''}交给我新东西，或者在期里点「出方案 / 开工」，它们就会开始工作。</p>`}</section>`;
    const pRow = p => { const n = p['下一步'] || {}, w = n['谁']; return `<a class="tpl-prow ${p === f ? 'is-focus' : ''}" href="${E(p['链接'])}">
      <span class="tpl-pn"><b>${E(p['名称'])}</b><span class="tpl-mut tpl-sm">${E(p['当前步骤'] || p['状态'])}${p['在跑'] ? ' · <span class="tpl-ai-on">AI 在跑</span>' : ''}</span></span>${track(p)}
      <span class="tpl-pnext">${w ? `<span class="tpl-who is-${w === '你' ? 'you' : 'ai'}">${whoLabel(w)}</span>` : ''}${E(n['文字'] || '')}</span></a>` };
    secs.flow = `<section class="tpl-hs"><h2 class="tpl-h"><span>进行中</span><span class="tpl-hsub">${prog.length} 期${tasks.length ? ` · ${tasks.length} 个事项` : ''}${done.length ? ` · 已完成 ${done.length} 期` : ''}</span><a class="tpl-hlink" href="#/classic">全部 →</a></h2>
      ${prog.length ? `<div class="tpl-plist">${prog.map(pRow).join('')}</div>` : '<p class="tpl-quiet">没有进行中的期。把需求贴到上面的输入框，我会建一期并开始整理。</p>'}
      ${tasks.length ? `<details class="tpl-tasks" ${prog.length ? '' : 'open'}><summary>事项 ${tasks.length} 个 <span class="tpl-mut">ANR、埋点、线上问题……</span></summary><div class="tpl-tlist">${tasks.map(t => `<a href="${E(t['链接'])}"><span>${E(t['名称'])}</span><span class="tpl-mut tpl-sm">${E(t['事项类型'] || '')}</span>${KB.badge(t['状态'])}${t['待确认'] ? `<span class="tpl-who is-you">${t['待确认']} 个需要你判断</span>` : ''}</a>`).join('')}</div></details>` : ''}</section>`;
    const g = b['关系'];
    const gaps = g ? (g['节点'] || []).filter(n => ['需求', '设计', '接口'].includes(n['类'])) : [];
    secs.gaps = g && gaps.length ? `<section class="tpl-hs"><h2 class="tpl-h"><span>资料齐不齐</span><span class="tpl-hsub">「${E(g['标题'])}」· AI 对照需求检查的</span></h2>
      <div class="tpl-gaps">${gaps.map(n => `<a href="${E(g['链接'])}" class="tpl-gap ${n['状态'] === 'miss' ? 'is-miss' : 'is-ok'}"><b>${n['状态'] === 'miss' ? '缺' : '✓'}</b><span>${E(n['名称'])}</span><span class="tpl-mut tpl-sm">${E(n['说明'] || '')}</span></a>`).join('')}</div>
      ${g['洞察'] && g['洞察']['标题'] ? `<p class="tpl-insight"><span class="tpl-ai">AI</span>${E(g['洞察']['标题'])}${g['洞察']['内容'] ? `<span class="tpl-mut"> · ${E(g['洞察']['内容'])}</span>` : ''}</p>` : ''}</section>` : '';
    const pills = [['🐞 Bug', `${bug['未关闭'] || 0} 未关闭${bug['待归纳'] ? ` · ${bug['待归纳']} 待归纳` : ''}`, '#/bugs'], ['💥 ANR / 崩溃', `${anr['待处理'] || 0} 待处理 · 共 ${anr['总数'] || 0}`, '#/anr'],
      ...(phn ? [['▯ 手机', `空闲 ${phn['空闲']}/${phn['总数']}`, '#/phones']] : []), ['◈ 基础信息', `${(site['基础信息'] || {})['条数'] || 0} 条`, '#/base'],
      ...(site['工具'] || []).map(t => [`${t['图标']} ${t['名称']}`, t['待确认'] ? `${t['待确认']} 待确认` : t['待解决'] ? `${t['待解决']} 待解决` : '', t['链接']])];
    secs.run = `<section class="tpl-hs"><h2 class="tpl-h"><span>线上</span><span class="tpl-hsub">Bug、崩溃先由 AI 只读分析，结论等你审核</span></h2>
      <div class="tpl-pills">${pills.map(([a, b2, l]) => `<a href="${E(l)}"><b>${E(a)}</b><span class="tpl-mut">${E(b2)}</span></a>`).join('')}</div></section>`;
    const ORDER = { collect: ['gaps', 'judg', 'flow', 'acts', 'run'], plan: ['judg', 'flow', 'acts', 'gaps', 'run'], build: ['acts', 'judg', 'flow', 'run'], accept: ['judg', 'flow', 'acts', 'run'], run: ['run', 'judg', 'acts', 'flow'] }[ph];
    const phi = PHASES.findIndex(x => x[0] === ph);
    KB.app.innerHTML = `<div class="tpl-home">
      <div class="tpl-phase" title="按当前这一期判断的阶段，首页的重点跟着变">${PHASES.map(([k, t], i) => `<span class="${i < phi ? 'is-done' : i === phi ? 'is-cur' : ''}">${E(t)}</span>`).join('<i></i>')}</div>
      <p class="tpl-focus">${f ? `<a href="${E(f['链接'])}">${E(f['名称'])}</a> · ` : ''}${E(PH_FOCUS[ph])}</p>
      ${ORDER.map(k => secs[k]).join('')}</div>`;
    bindJudg(KB.app.querySelector('.tpl-judgs'));
  };

  // ───────────────────────────────────────────── 工作区：面包屑 + 建议 + 需要你判断
  const PAGE = { '/bugs': ['🐞', 'Bug'], '/anr': ['💥', 'ANR / 崩溃'], '/phones': ['▯', '手机'], '/base': ['◈', '基础信息'], '/settings': ['⚙', '设置'], '/classic': ['▦', '经典总览'] };
  const SECS = { mat: ['资料', '需求、设计稿、接口、其他资料，来源核对'], stack: ['全栈', '选仓库 → 出方案 → 拍板 → 开工 → 验收'], dev: ['开发', '开发会话、AI 的提问、问题、复测'], build: ['构建', '安装包、mapping、各次构建'], bug: ['Bug', '归到这里的 Bug 和 AI 的只读分析'], log: ['记录', '这一期发生过的每件事'] };
  function crumbs(h) {
    const c = [['首页', '#/']];
    if (h.startsWith('/p/')) {
      const n = h.slice(3), p = entry(n), ov = (KB.periods || []).find(x => x.name === n) || {};
      if (p && p['事项']) { if ((ov.batch || {})['来源'] === 'anr' || (p['批次'] || {})['来源'] === 'anr') c.push(['ANR 与崩溃', '#/anr']); else c.push(['事项', '']) } else c.push(['期', '']);
      c.push([n, '']);
    } else if (h.startsWith('/d/')) { c.push(['文档', '#/d/']); if (h.slice(3)) c.push([h.slice(3), '']) }
    else if (h.startsWith('/tool/')) { const t = ((S.site || {})['工具'] || []).find(x => x.id === h.slice(6)); c.push(['工具', '']); c.push([t ? t['名称'] : h.slice(6), '']) }
    else if (h.startsWith('/s/')) { c.push(['搜索', '']); c.push(['「' + h.slice(3).split('\u0001')[0] + '」', '']) }
    else if (PAGE[h]) c.push([PAGE[h][1], '']);
    else c.push([h, '']);
    return c.map(([t, l], i) => l && i < c.length - 1 ? `<a href="${E(l)}">${E(t)}</a>` : `<span${i === c.length - 1 ? ' class="is-here"' : ''}>${E(t)}</span>`).join('<i>/</i>');
  }
  function ctxFor(h) {
    const chips = [], live = [];
    let js = [];
    const actChip = a => `<a class="tpl-chip is-ai" href="${E(a['链接'] || '#/')}" title="${E((a['步骤'] || []).slice(-1)[0] || '')}"><span class="tpl-live"></span>${E(a['角色'])} AI · ${E(a['状态'])}</a>`;
    if (h.startsWith('/p/')) {
      const n = h.slice(3), p = entry(n), x = p && p['下一步'];
      js = judgs().filter(j => j['链接'] === '#/p/' + n || (j['提议'] && j['提议']['事项'] === n));
      acts().filter(a => a['对象'] === n || String(a['对象']).startsWith(n + ' · ')).forEach(a => live.push(actChip(a)));
      if (x && x['文字']) chips.push(`<button class="tpl-chip is-main ${x['谁'] === '你' ? 'is-you' : ''}" data-sec="${E((x['去'] || '').replace('tab:', ''))}" type="button"><span class="tpl-ai">AI</span>${x['谁'] ? `<span class="tpl-mut">${whoLabel(x['谁'])} ·</span>` : ''}${E(x['文字'])}${x['按钮'] ? ` <b>→ ${E(x['按钮'])}</b>` : ''}</button>`);
      KB.app.querySelectorAll('.tpl-sec').forEach(sc => { const k = sc.dataset.k; chips.push(`<button class="tpl-chip ${sc.classList.contains('is-cur') ? 'is-cur' : ''}" data-sec="${k}" type="button">${E(SECS[k][0])}</button>`) });
      if (KB.app.querySelector('#tkMsg')) chips.push(`<button class="tpl-chip" data-talk type="button">跟这一期说…</button>`);
    } else if (h === '/bugs') {
      const b = (S.site || {})['Bug'] || {};
      js = judgs().filter(j => (j['链接'] || '').startsWith('#/bugs') || (j['提议'] && j['提议']['类型'] === 'Bug分析'));
      acts().filter(a => /Bug/.test(a['角色'])).forEach(a => live.push(actChip(a)));
      chips.push(`<span class="tpl-chip is-stat">未关闭 <b>${b['未关闭'] || 0}</b></span>`, `<span class="tpl-chip is-stat">待归纳 <b>${b['待归纳'] || 0}</b></span>`);
      chips.push(`<button class="tpl-chip" data-prefill="Bug 链接：" type="button">交给管家一个 Bug 链接</button>`);
    } else if (h === '/anr') {
      const a = (S.site || {})['ANR'] || {};
      js = judgs().filter(j => /ANR|崩溃/.test(j['问题'] || '') || (j['链接'] || '').startsWith('#/anr'));
      chips.push(`<span class="tpl-chip is-stat">待处理 <b>${a['待处理'] || 0}</b></span>`, `<span class="tpl-chip is-stat">共 <b>${a['总数'] || 0}</b> 个问题</span>`);
      chips.push(`<button class="tpl-chip" data-prefill="ANR 日志：" type="button">贴一段日志给管家</button>`);
    } else if (h === '/settings') {
      chips.push(`<button class="tpl-chip" data-run="theme" type="button">◐ 深色 / 浅色</button>`, `<a class="tpl-chip" href="/?ui=classic#/settings">临时看经典版</a>`);
    } else if (h === '/phones') {
      const ph = (S.site || {})['手机']; if (ph) chips.push(`<span class="tpl-chip is-stat">空闲 <b>${ph['空闲']}/${ph['总数']}</b></span>`);
      chips.push(`<span class="tpl-chip is-note">后台会话只用申请到的手机，你点「我在用」它就不碰</span>`);
    } else if (h === '/base') {
      chips.push(`<span class="tpl-chip is-note">机密字段加密保存，AI 用时才取</span>`);
    } else if (h.startsWith('/s/')) {
      const t = h.slice(3).split('\u0001')[0];
      chips.push(`<button class="tpl-chip" data-prefill="${E(t)}" type="button">把「${E(t.slice(0, 16))}」交给管家</button>`);
    }
    return { chips, live, js };
  }
  function paintCtx() {
    const h = curHash(), box = q('#tplCtx');
    if (h === '/') { box.hidden = true; box.innerHTML = ''; return }
    const { chips, live, js } = ctxFor(h);
    box.hidden = false;
    box.innerHTML = `<div class="tpl-crumbs"><nav>${crumbs(h)}</nav><span class="tpl-sp"></span>${live.join('')}</div>
      ${chips.length ? `<div class="tpl-chips">${chips.join('')}</div>` : ''}
      ${js.length ? `<div class="tpl-ctxj"><div class="tpl-h tpl-h-s"><span>需要你判断</span><span class="tpl-n">${js.length}</span></div>${judgHtml(js)}</div>` : ''}`;
    bindJudg(box.querySelector('.tpl-judgs'));
    box.querySelectorAll('[data-sec]').forEach(b => b.onclick = () => { const k = b.dataset.sec; if (k) openSec(k, true); else { const g = q('#gGo'); if (g) g.click() } });
    box.querySelectorAll('[data-talk]').forEach(b => b.onclick = () => { const t = q('#tkMsg'); if (t) { t.scrollIntoView({ behavior: smooth(), block: 'center' }); t.focus() } });
    box.querySelectorAll('[data-prefill]').forEach(b => b.onclick = () => { qEl.value = b.dataset.prefill; grow(); qEl.focus(); qEl.setSelectionRange(qEl.value.length, qEl.value.length); qEl.dispatchEvent(new Event('input')) });
    box.querySelectorAll('[data-run="theme"]').forEach(b => b.onclick = themeCycle);
  }
  const smooth = () => matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';

  // ───────────────────────────────────────────── 期详情：板块按流程排成可折叠段落，当前阶段展开并高亮
  function sectionOrder(p) {
    return p && p['流程'] === '单端' ? ['mat', 'dev', 'build', 'bug', 'log', 'stack'] : ['mat', 'stack', 'dev', 'build', 'bug', 'log'];
  }
  function curSection(p, nav) {
    const x = p && p['下一步'];
    const k = x && (x['去'] || '').replace('tab:', '');
    if (k) return k;
    if (p && p['状态'] === '已完成') return p['没解决Bug'] ? 'bug' : '';
    const on = nav && nav.querySelector('.ptab.on');
    return (on && on.dataset.tab) || 'mat';
  }
  function secState(k, p, cur) {
    if (k === cur) return 'cur';
    const st = (p && p['步骤']) || [], done = n => (st.find(s => s['名称'] === n) || {})['状态'] === 'done';
    if (k === 'mat' && done('资料')) return 'done';
    if (k === 'stack' && p && p['流程'] === '全栈' && done('验收')) return 'done';
    return '';
  }
  function openSec(k, scroll) {
    const s = KB.app.querySelector(`.tpl-sec[data-k="${k}"]`);
    if (!s) return;
    setSec(s, true);
    if (scroll) s.scrollIntoView({ behavior: smooth(), block: 'start' });
  }
  function setSec(s, open) {
    s.classList.toggle('is-open', open);
    s.querySelector('.tpl-sech').setAttribute('aria-expanded', open ? 'true' : 'false');
    const n = s.dataset.p, k = s.dataset.k;
    S.open[n] = S.open[n] || {}; S.open[n][k] = open; ls.set('tpl.secs', JSON.stringify(S.open));
  }
  function periodLayout(name) {
    const app = KB.app, nav = app.querySelector('nav.ptabs');
    // 步骤条 / 下一步：去掉催促式的措辞
    app.querySelectorAll('.gnext .who').forEach(w => { w.textContent = w.classList.contains('w-你') ? '需要你判断' : 'AI 在推进' });
    const gn = app.querySelector('.gnext'); if (gn && !gn.querySelector('.tpl-ai')) gn.insertAdjacentHTML('afterbegin', '<span class="tpl-ai" title="AI 根据这一期的资料、方案和会话状态判断的下一步">AI 判断</span>');
    app.querySelectorAll('.crumb').forEach(c => { if (!c.querySelector('#toPush')) c.hidden = true });
    if (!nav) return;                              // 事项的备忘 / 推送页：没有板块
    const host = nav.parentElement, p = entry(name);
    const panes = {}; host.querySelectorAll(':scope>[data-pane]').forEach(x => panes[x.dataset.pane] = x);
    const label = {}; nav.querySelectorAll('[data-tab]').forEach(a => label[a.dataset.tab] = [...a.querySelectorAll('.n')].map(x => `<span class="tpl-secc ${x.classList.contains('w') ? 'is-w' : ''}" title="${E(x.title || '')}">${E(x.textContent)}</span>`).join(''));
    const cur = curSection(p, nav), mem = S.open[name] || {};
    const flow = document.createElement('div'); flow.className = 'tpl-flow';
    sectionOrder(p).forEach((k, i) => {
      const pane = panes[k]; if (!pane) return;
      const st = secState(k, p, cur), open = k in mem ? mem[k] : st === 'cur';
      const sec = document.createElement('section');
      sec.className = `tpl-sec ${st ? 'is-' + st : ''} ${open ? 'is-open' : ''}`; sec.dataset.k = k; sec.dataset.p = name;
      sec.innerHTML = `<button class="tpl-sech" type="button" aria-expanded="${open}"><span class="tpl-secn">${String(i + 1).padStart(2, '0')}</span><span class="tpl-sect"><b>${E(SECS[k][0])}</b><span class="tpl-mut">${E(SECS[k][1])}</span></span>${label[k] || ''}${st === 'cur' ? '<span class="tpl-secs is-cur">当前阶段</span>' : st === 'done' ? '<span class="tpl-secs">✓ 已完成</span>' : ''}<i class="tpl-car" aria-hidden="true"></i></button><div class="tpl-secb"></div>`;
      pane.hidden = false; pane.style.order = '';
      sec.querySelector('.tpl-secb').appendChild(pane);
      sec.querySelector('.tpl-sech').onclick = () => setSec(sec, !sec.classList.contains('is-open'));
      flow.appendChild(sec);
    });
    host.after(flow); host.style.display = "none";
    // core 的标签切换 / 「下一步」按钮：改成展开对应段落并滚过去
    nav.querySelectorAll('[data-tab]').forEach(a => a.onclick = () => openSec(a.dataset.tab, true));
    const gb = app.querySelector('#gGo'); if (gb) gb.onclick = () => { const k = (gb.dataset.to || '').replace('tab:', ''); if (k) openSec(k, true) };
  }

  // ───────────────────────────────────────────── 钩子
  KB.hooks.nav = (d, site) => {
    if (site) { S.site = site; paintChrome(); }
    paintCtx();
  };
  KB.hooks.afterRender = h => {
    const home = h === '/';
    document.body.classList.toggle('tpl-at-home', home);
    document.body.classList.remove('tpl-boot');
    document.body.dataset.tplRoute = h.split('/')[1] || 'home';
    KB.app.classList.remove('tpl-loading');
    if (h.startsWith('/p/')) periodLayout(h.slice(3));
    paintChrome(); paintCtx();
    const title = home ? '指挥台' : (h.startsWith('/p/') ? h.slice(3) : (PAGE[h] || [, h.split('/')[1]])[1]);
    document.title = '知识库 · ' + title;
    if (!home) { const top = q('#tplTop'); if (scrollY > top.offsetHeight) scrollTo(0, 0) }
  };

  // 换页时工作区先淡一下，新页面画好（afterRender）再恢复：有的页面要等好几个接口
  window.addEventListener('hashchange', () => KB.app.classList.add('tpl-loading'));

  // 智能状态：SSE 有总体变化就重拉；另外 8 秒看一次（AI 的进展不一定有 SSE），有变化才重画
  let bT = 0;
  async function refreshBrief() {
    const changed = await loadBrief();
    if (!changed) return;
    paintChrome(); paintCtx();
    if (curHash() === '/' && !KB.app.contains(document.activeElement) && !q('#dlg').open) KB.pages.home();
  }
  KB.on('overview', () => { clearTimeout(bT); bT = setTimeout(refreshBrief, 400) });
  KB.on('dev', () => { clearTimeout(bT); bT = setTimeout(refreshBrief, 800) });
  setInterval(() => { if (!document.hidden) refreshBrief() }, 8000);

  // 先拿到数据再启动（首页和建议都要用）
  KB.manualStart = true;
  Promise.all([loadSite(), loadBrief()]).finally(() => { paintChrome(); KB.start() });
})();
