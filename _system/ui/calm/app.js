// From 大大王.DT
/* 界面模板「静默」：整个网站是一个安静的环境，AI 在后台干活，只在需要你判断时出声。
 * 骨架：柔和背景 + 顶部极简位置条 + 居中「纸面」（KB.app）+ 屏幕底部居中的悬浮「坞」（此刻 / 交给我 / 项目 / 问题 / 资料 / 设置）。
 * 首页：中央呼吸的光环（颜色和律动 = AI 团队状态），一句话汇报，最多两枚「决定胶囊」，判断依据收在折叠里。
 * 功能页都由 core 渲染，这里只做：导航浮层、afterRender 里的布局微调（操作收进「更多」、长内容渐进展开、措辞）、皮肤。
 * 自己的 id / class 一律 tpl 前缀。 */
(function () {
  'use strict';
  const TPL = '静默', $ = s => document.querySelector(s), esc = KB.esc, enc = KB.enc;
  KB.setApp('#tplApp');
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  const mobile = () => innerWidth < 640;

  let SITE = null, BRIEF = null, homeSig = '', homeTimer = 0, lastHash = null, popK = '';
  const opened = new Set();        // 用户点过「展开更多」的块（hash|序号），softRender 后保持展开

  // ───────── 状态：光环颜色和律动 ─────────
  const STATES = {
    '理解中': { k: 'understand', c: ['#2dd4bf', '#38bdf8', '#5eead4'], t: '理解中' },
    '工作中': { k: 'working', c: ['#6f9bff', '#2dd4bf', '#a78bfa'], t: '工作中' },
    '等你判断': { k: 'judge', c: ['#a78bfa', '#6f9bff', '#c084fc'], t: '需要你判断' },
    '发现问题': { k: 'issue', c: ['#fb923c', '#f87171', '#fbbf24'], t: '发现问题' },
    '安静': { k: 'quiet', c: ['#2dd4bf', '#4ade80', '#38bdf8'], t: '安静' },
  };
  const PHASES = ['收集资料', '方案拍板', '并行开发', '验收上线', '线上维护'];
  const phaseOfStep = s => !s ? 4 : s === '资料' ? 0 : ['选仓库', '出方案', '拍板', '开始开发'].includes(s) ? 1 : ['开发', '开发中'].includes(s) ? 2 : 3;
  const PHASE_DOCK = ['ask', 'proj', 'proj', 'proj', 'issue'];   // 每个阶段最相关的坞入口

  const periods = () => (SITE && SITE['期']) || [];
  const isIssueTask = p => p['事项'] && ['anr', 'bug'].includes(((p['批次'] || {})['来源']) || '') ;
  const isToolTask = p => p['事项'] && (p['插件'] || []).length;
  // 当前最值得关注的那一期：/api/brief 的关系图那期，没有就取最近更新、还在进行的期
  function focusPeriod() {
    const ps = periods(), n = BRIEF && BRIEF['关系'] && BRIEF['关系']['标题'];
    return ps.find(p => p['名称'] === n && !p['事项'])
      || ps.filter(p => !p['事项'] && !['已完成', '已暂停'].includes(p['状态'])).sort((a, b) => String(b['更新时间']).localeCompare(String(a['更新时间'])))[0] || null;
  }
  function phase() {
    const fp = focusPeriod();
    if (fp) return phaseOfStep(fp['当前步骤']);
    if (BRIEF && BRIEF['关系']) { const c = (BRIEF['关系']['步骤'] || []).find(s => s['状态'] === 'cur'); return phaseOfStep(c && c['名称']); }
    return 4;
  }
  function stateNow() {
    if (BRIEF) {
      const s = BRIEF['状态'] || {}, acts = BRIEF['活动'] || [];
      if (s['名称'] !== '等你判断' && acts.some(a => a['角色'] === '管家' && !a['等你'])) return STATES['理解中'];
      return STATES[s['名称']] || STATES['安静'];
    }
    if (!SITE) return STATES['安静'];
    if (SITE['在跑']) return STATES['工作中'];
    if (SITE['待你'] || periods().some(p => p['待确认'])) return STATES['等你判断'];
    return STATES['安静'];
  }
  function paintState() {
    const st = stateNow(), r = document.documentElement.style;
    r.setProperty('--tpl-o1', st.c[0]); r.setProperty('--tpl-o2', st.c[1]); r.setProperty('--tpl-o3', st.c[2]);
    document.body.dataset.tplState = st.k;
    const ph = phase(), hot = PHASE_DOCK[ph];
    document.querySelectorAll('#tplDock .tpl-dk').forEach(b => b.classList.toggle('tpl-hot', b.dataset.k === hot));
    const o = $('#tplOrbm'); if (o) o.parentElement.title = `首页 · AI 团队${st.t} · 阶段：${PHASES[ph]}`;
  }

  // ───────── 浅色 / 深色 ─────────
  const TH_KEY = 'kb.calm.theme';
  function setTheme(t) {
    if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
    try { t ? localStorage.setItem(TH_KEY, t) : localStorage.removeItem(TH_KEY) } catch (_) {}
  }
  $('#tplTheme').onclick = () => {
    const cur = document.documentElement.dataset.theme || '';
    const nx = cur === '' ? 'dark' : cur === 'dark' ? 'light' : '';
    setTheme(nx); KB.toast(nx === 'dark' ? '深夜（深色）' : nx === 'light' ? '晨光（浅色）' : '跟随系统');
  };

  // ───────── 底部坞 + 浮层 ─────────
  const pop = $('#tplPop');
  function openPop(k) {
    if (popK === k) return closePop();
    popK = k; KB.askOpen(false);
    pop.hidden = false;
    pop.querySelectorAll('.tpl-pane').forEach(s => s.hidden = s.dataset.paneK !== k);
    const b = document.querySelector(`#tplDock [data-k="${k}"]`);
    if (b && !mobile()) {         // 浮层对准坞里的按钮
      const r = b.getBoundingClientRect(), w = Math.min(440, innerWidth - 24);
      pop.style.left = Math.max(12, Math.min(innerWidth - w - 12, r.left + r.width / 2 - w / 2)) + 'px';
    } else pop.style.left = '';
    markDock();
    const f = pop.querySelector(`[data-pane-k="${k}"] .tpl-filter`) || (k === 'mat' && $('#q'));
    if (f && !mobile()) setTimeout(() => f.focus(), 30);
  }
  function closePop() { popK = ''; pop.hidden = true; markDock(); }
  document.querySelectorAll('#tplDock button.tpl-dk').forEach(b => b.onclick = e => {
    e.stopPropagation();
    if (b.dataset.k === 'ask') { const open = $('#askPanel').hidden; closePop(); KB.askOpen(open); markDock(); return; }
    openPop(b.dataset.k);
  });
  document.addEventListener('click', e => {
    if (popK && !pop.contains(e.target) && !e.target.closest('#tplDock')) closePop();
    if (e.target.closest('#tplPop a[href]')) closePop();
    const nb = e.target.closest('[data-tpl-new]'); if (nb) { e.preventDefault(); closePop(); KB.addDlg(nb.dataset.tplNew); }
    const cp = e.target.closest('[data-tpl-pop]'); if (cp) { e.preventDefault(); e.stopPropagation(); openPop(cp.dataset.tplPop); }
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && popK) closePop();
    if (e.key === '/' && !e.target.matches('input,textarea,select,[contenteditable]') && !$('#dlg').open) { e.preventDefault(); openPop('mat'); setTimeout(() => $('#q').focus(), 30); }
  });
  $('#sf').addEventListener('submit', () => setTimeout(closePop, 0));
  new MutationObserver(markDock).observe($('#askPanel'), { attributes: true, attributeFilter: ['hidden'] });

  // 当前页属于坞里的哪一组
  function groupOf(h) {
    if (h === '/' || h === '') return 'home';
    if (h.startsWith('/p/')) { const p = periods().find(x => x['名称'] === h.slice(3)); return p && isIssueTask(p) ? 'issue' : p && isToolTask(p) ? 'mat' : 'proj'; }
    if (h === '/bugs' || h === '/anr') return 'issue';
    if (h === '/settings') return 'set';
    if (h === '/classic') return 'proj';
    return 'mat';
  }
  function markDock() {
    const g = groupOf(KB.curHash()), askOn = !$('#askPanel').hidden;
    document.querySelectorAll('#tplDock .tpl-dk').forEach(b => {
      const k = b.dataset.k;
      b.classList.toggle('tpl-on', askOn ? k === 'ask' : popK ? k === popK : k === g);
      if (b.tagName === 'BUTTON') b.setAttribute('aria-expanded', String(k === 'ask' ? askOn : k === popK));
    });
  }

  // 浮层内容
  const steps = p => (p['步骤'] || []).length ? `<span class="tpl-steps" aria-label="步骤">${p['步骤'].map(s => `<i class="tpl-s-${esc(s['状态'])}" title="${esc(s['名称'])}"></i>`).join('')}</span>` : '';
  function aiTag(p) {
    if (p['在跑']) return '<span class="tpl-tag tpl-tag-ai"><i class="tpl-pulse"></i>AI 在做</span>';
    if (p['待确认']) return `<span class="tpl-tag tpl-tag-j">需要你判断 ${p['待确认']}</span>`;
    if (p['免打扰']) return '<span class="tpl-tag">免打扰</span>';
    if (p['问题']) return `<span class="tpl-tag tpl-tag-w">${p['问题']} 个问题</span>`;
    return '';
  }
  const DOTC = { 收集中: 'var(--s0)', 已批准开发: 'var(--info)', 开发中: 'var(--s2)', 已完成: 'var(--s3)', 已暂停: 'var(--s1)' };
  function item(p) {
    const b = p['批次'] || {}, nx = p['下一步'] || {};
    const sub = p['当前步骤'] ? `${esc(p['当前步骤'])}${nx['文字'] ? ' · ' + esc(nx['文字']) : ''}`
      : b['总数'] ? `已处理 ${b['已处理']}/${b['总数']}${b['待确认'] ? ` · 待确认 ${b['待确认']}` : ''}` : esc(p['说明'] || p['状态']);
    return `<a class="tpl-it" href="#/p/${enc(p['名称'])}" title="${esc(p['说明'] || '')}"><span class="tpl-sd" style="--c:${DOTC[p['状态']] || 'var(--s0)'}"></span>
      <span class="tpl-in"><b>${esc(p['名称'])}</b><small>${esc(p['状态'])} · ${sub}</small>${steps(p)}</span>${aiTag(p)}</a>`;
  }
  const live = p => !['已完成', '已暂停'].includes(p['状态']);
  function filterBox(n) { return n > 6 ? '<input class="tpl-filter" type="text" placeholder="筛选…" aria-label="筛选">' : ''; }
  function buildPops() {
    const ps = periods(), pr = ps.filter(p => !p['事项']), gt = ps.filter(p => p['事项'] && !isIssueTask(p) && !isToolTask(p));
    const a = pr.filter(live), ar = a.filter(p => p['在跑']).length, rest = pr.filter(p => !live(p)).concat(gt.filter(p => !live(p)));
    $('#tplPopProj').innerHTML = `<div class="tpl-ph"><b>项目</b><span class="tpl-mut">${a.length} 期在进行${ar ? ` · AI 在做 ${ar}` : ''}</span></div>${filterBox(pr.length + gt.length)}
      <div class="tpl-list">${a.map(item).join('') || '<p class="tpl-empty">还没有进行中的期。把需求交给我，我来建。</p>'}
      ${gt.filter(live).length ? `<div class="tpl-sub">事项</div>${gt.filter(live).map(item).join('')}` : ''}
      ${rest.length ? `<details class="tpl-rest"><summary>已完成 / 暂停 ${rest.length} 个</summary>${rest.map(item).join('')}</details>` : ''}</div>
      <div class="tpl-pf"><a href="#" data-tpl-new="new">＋ 新建一期</a><a href="#" data-tpl-new="task">＋ 事项</a><a href="#/classic">全部总览 →</a></div>`;
    const bug = SITE['Bug'] || {}, anr = SITE['ANR'] || {}, it = ps.filter(isIssueTask), itl = it.filter(live);
    $('#tplPopIssue').innerHTML = `<div class="tpl-ph"><b>问题</b><span class="tpl-mut">线上反馈和崩溃，AI 先只读分析再等你审核</span></div>
      <div class="tpl-tiles"><a class="tpl-tile" href="#/bugs"><span>Bug</span><b>${esc(bug['未关闭'] ?? 0)}</b><small>${bug['待归纳'] ? `${bug['待归纳']} 个待归纳` : '未关闭'}</small></a>
        <a class="tpl-tile" href="#/anr"><span>ANR / 崩溃</span><b>${esc(anr['总数'] ?? 0)}</b><small>${anr['待处理'] ? `${anr['待处理']} 个待处理` : '都有归属'}</small></a></div>
      ${filterBox(it.length)}<div class="tpl-list">${itl.map(item).join('')}${it.length > itl.length ? `<details class="tpl-rest"><summary>其他 ${it.length - itl.length} 个</summary>${it.filter(p => !itl.includes(p)).map(item).join('')}</details>` : ''}</div>`;
    const docs = SITE['文档'] || [], tools = SITE['工具'] || [], ph = SITE['手机'], base = SITE['基础信息'] || {};
    $('#tplPopMat').innerHTML = `<div class="tpl-tiles">
        <a class="tpl-tile" href="#/base"><span>基础信息</span><b>${esc(base['条数'] ?? 0)}</b><small>账号、地址、机密</small></a>
        ${ph ? `<a class="tpl-tile" href="#/phones"><span>手机</span><b>${esc(ph['空闲'])}<small>/${esc(ph['总数'])}</small></b><small>空闲 / 全部</small></a>` : ''}
        <a class="tpl-tile" href="#/d/"><span>文档</span><b>${docs.length || '?'}</b><small>说明和帮助</small></a></div>
      ${tools.length ? `<div class="tpl-sub">工具</div><div class="tpl-list">${tools.map(t => `<a class="tpl-it" href="${esc(t['链接'] || '#/tool/' + enc(t.id))}" title="${esc(t['说明'] || '')}"><span class="tpl-ico">${esc(t['图标'] || '◇')}</span><span class="tpl-in"><b>${esc(t['名称'])}</b><small>${esc(t['提示'] || t['说明'] || '')}</small></span>${t['待确认'] ? `<span class="tpl-tag tpl-tag-j">需要你判断 ${t['待确认']}</span>` : t['待解决'] ? `<span class="tpl-tag">${t['待解决']} 条</span>` : ''}</a>`).join('')}</div>` : ''}
      ${docs.length ? `<div class="tpl-sub">文档</div><div class="tpl-docs">${docs.map(d => `<a href="${esc(d['链接'])}">${esc(d['名称'])}</a>`).join('')}</div>` : ''}`;
    pop.querySelectorAll('.tpl-filter').forEach(f => f.oninput = () => {
      const q = f.value.trim().toLowerCase();
      f.closest('.tpl-pane').querySelectorAll('.tpl-it').forEach(a => a.hidden = !!q && !a.textContent.toLowerCase().includes(q));
      f.closest('.tpl-pane').querySelectorAll('details.tpl-rest').forEach(d => { if (q) d.open = true; });
    });
    // 坞上的柔光点：有需要你判断的事就亮，不写数字
    const pj = pr.concat(gt).some(p => p['待确认'] && live(p)), ij = it.some(p => p['待确认']) || !!anr['待处理'] || !!bug['待归纳'];
    $('#tplDock [data-k="proj"]').classList.toggle('tpl-has', pj);
    $('#tplDock [data-k="issue"]').classList.toggle('tpl-has', ij);
  }

  KB.hooks.nav = (d, site) => {
    if (site) {
      SITE = site; buildPops();
      if (KB.curHash() !== '/') KB.api('/api/brief').then(b => { BRIEF = b; paintState(); }).catch(() => {});   // 光环颜色在每页都一致
    }
    paintState(); markDock(); crumb(KB.curHash());
  };

  // ───────── 顶部位置条 ─────────
  const GN = { proj: '项目', issue: '问题', mat: '资料', set: '设置' };
  function title(h) {
    if (h.startsWith('/p/')) return h.slice(3);
    if (h.startsWith('/tool/')) { const t = (SITE && SITE['工具'] || []).find(x => x.id === h.slice(6)); return t ? t['名称'] : '工具'; }
    if (h.startsWith('/s/')) return '搜索：' + h.slice(3).split('\u0001')[0];
    if (h.startsWith('/d/')) return h.slice(3) || '文档';
    return { '/bugs': 'Bug', '/anr': 'ANR / 崩溃', '/phones': '手机', '/base': '基础信息', '/settings': '设置', '/classic': '全部总览' }[h] || '';
  }
  function crumb(h) {
    const g = groupOf(h), el = $('#tplCrumb');
    if (g === 'home') { el.innerHTML = ''; document.title = '知识库 · 静默'; return; }
    const t = title(h);
    el.innerHTML = `<span class="tpl-sep">/</span>${g === 'set' ? '' : `<a href="#" data-tpl-pop="${g}">${GN[g]}</a><span class="tpl-sep">/</span>`}<b>${esc(t)}</b>`;
    document.title = t + ' · 知识库';
  }

  // ───────── 首页 ─────────
  function capHtml(j) {
    const kind = { '问你': 'AI 想问你', '待你': '需要你判断', '建议': 'AI 的建议' }[j['类型']] || '需要你判断';
    return `<div class="tpl-cap"><div class="tpl-capk"><i></i>${esc(kind)}</div>${KBUI.judg(j)}</div>`;
  }
  function narr(b) {
    const n = b['叙述'] || {}, cites = n['引用'] || [];
    const body = esc(n['正文'] || '').replace(/\[(\d+)\]/g, (_, i) => { const c = cites[i - 1]; return c && c['链接'] ? `<a href="${esc(c['链接'])}"><sup>${i}</sup></a>` : `<sup>${i}</sup>`; });
    const mets = (b['指标'] || []).map(m => `<${m['链接'] ? `a href="${esc(m['链接'])}"` : 'div'} class="tpl-met"><span>${esc(m['名称'])}</span><b>${esc(m['值'])}<small> ${esc(m['单位'] || '')}</small></b>${spark(m['趋势'])}${m['说明'] ? `<small>${esc(m['说明'])}</small>` : ''}</${m['链接'] ? 'a' : 'div'}>`).join('');
    const st = (b['管家'] || {})['设置'] || {}, rules = (b['管家'] || {})['规矩'] || [];
    return `<p class="tpl-narr">${body}</p>${cites.length ? `<div class="tpl-cites">${cites.map((c, i) => `<span><sup>${i + 1}</sup> ${c['链接'] ? `<a href="${esc(c['链接'])}">${esc(c['文字'])}</a>` : esc(c['文字'])}</span>`).join('')}</div>` : ''}
      <div class="tpl-mets">${mets}</div>
      <p class="tpl-mut tpl-small">管家${st['开启'] ? `开着 · 自主度「${esc(st['自主度'] || '')}」 · 每天最多 ${esc(st['每日上限'] ?? '')} 件` : '关着'}${(b['管家'] || {})['上次'] ? ` · 上次巡视 ${esc(b['管家']['上次'])}` : ''}${rules.length ? ` · 记着 ${rules.length} 条规矩：${rules.slice(0, 3).map(r => esc(r['内容'])).join('；')}` : ''} · <a href="#/settings">调整</a></p>`;
  }
  function spark(v) {
    if (!v || !v.length || v.every(x => !x)) return '';
    const mx = Math.max(...v, 1), pts = v.map((y, i) => `${i / Math.max(1, v.length - 1) * 100},${28 - y / mx * 24}`).join(' ');
    return `<svg viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>`;
  }
  function homeHtml(b) {
    const st = stateNow(), s = b['状态'] || {}, js = b['判断'] || [], acts = b['活动'] || [], prog = b['进行中'] || [];
    const g = b['关系'], ph = phase();
    const num = s['等你'] || s['在工作'] || s['今天完成'] || 0;
    const lab = s['等你'] ? '件事需要你判断' : s['在工作'] ? '个 AI 在工作' : s['今天完成'] ? '件今天替你做完' : '一切安静';
    const insight = g && g['洞察'] && g['洞察']['标题'] ? `<p class="tpl-under"><span class="tpl-mut">我对「${esc(g['标题'])}」的理解：</span>${esc(g['洞察']['标题'])}${g['洞察']['内容'] ? `<span class="tpl-mut"> — ${esc(g['洞察']['内容'])}</span>` : ''}</p>` : '';
    const quiet = !js.length && !acts.length;
    return `<section class="tpl-home tpl-st-${st.k}${quiet ? ' tpl-quiet' : ''}">
      <div class="tpl-halo" role="img" aria-label="AI 团队状态：${esc(st.t)}"><span class="tpl-ring"></span><span class="tpl-ring tpl-r2"></span>
        <div class="tpl-core"><b>${esc(num)}</b><span>${esc(lab)}</span></div></div>
      <p class="tpl-state"><i></i>${esc(st.t)}<span class="tpl-mut"> · 阶段：${esc(PHASES[ph])}</span></p>
      <h1 class="tpl-say">${esc(b['问候'] || '')}</h1>${insight}
      ${js.length ? `<div class="kbt tpl-caps" id="tplCaps">${js.slice(0, 2).map(capHtml).join('')}</div>
        ${js.length > 2 ? `<details class="tpl-morej"><summary>还有 ${js.length - 2} 件，不急</summary><div class="kbt tpl-caps">${js.slice(2).map(capHtml).join('')}</div></details>` : ''}` : ''}
      ${acts.length ? `<div class="tpl-acts" aria-label="AI 在做什么">${acts.slice(0, 4).map(a => `<a class="tpl-act" href="${esc(a['链接'] || '#/')}"><i style="background:${esc(a['颜色'] || 'var(--acc)')}"></i><b>${esc(a['角色'])}</b><span>${esc(a['对象'])}</span><em class="${a['等你'] ? 'tpl-w' : 'tpl-caret'}">${esc((a['步骤'] || []).slice(-1)[0] || a['状态'])}</em></a>`).join('')}${acts.length > 4 ? `<span class="tpl-mut tpl-small">还有 ${acts.length - 4} 个 AI 在安静地工作</span>` : ''}</div>` : ''}
      ${prog.length ? `<div class="tpl-prog">${prog.slice(0, 3).map(p => `<a href="${esc(p['链接'])}" title="${esc(p['下一步'] || '')}"><span>${esc(p['名称'])}</span><span class="tpl-bar"><i style="width:${Math.max(4, +p['进度'] || 0)}%"></i></span><small>${esc(p['阶段'] || '完成')}${p['谁'] === 'AI' ? ' · AI 在推进' : p['谁'] === '你' ? ' · 等你一个判断' : ''}</small></a>`).join('')}</div>` : ''}
      <div class="tpl-ask"><textarea id="tplSay" rows="1" placeholder="交给我：需求、日志、Bug……或问一句" aria-label="交给管家"></textarea><button type="button" class="tpl-go" id="tplSayGo" title="交给管家（回车）">↵</button>
        <div class="tpl-parse" id="tplParse" hidden></div></div>
      <ol class="tpl-phase" aria-label="阶段">${PHASES.map((n, i) => `<li class="${i < ph ? 'tpl-pd' : i === ph ? 'tpl-pc' : ''}">${n}</li>`).join('')}</ol>
      <details class="tpl-why"><summary>判断依据</summary>${narr(b)}</details>
      <p class="tpl-today">今天替你完成 ${esc(s['今天完成'] || 0)} 件 · ${esc((b['时间'] || '').slice(11))} 更新</p>
    </section>`;
  }
  const judgOpts = {
    act: async (id, action, x) => {
      try { const r = await KB.post('/api/brief/act', { id, action, ...x }); KB.toast(String(r.msg || '好了').split('\n')[0]); } catch (e) { KB.toast(e.message); }
      homeSig = ''; KB.render();
    },
    openAsk: () => KB.askOpen(true),
  };
  function bindHome(b) {
    document.querySelectorAll('.tpl-caps').forEach(c => KBUI.bind(c, b, judgOpts));
    const ta = $('#tplSay'), box = $('#tplParse'); let hd;
    const go = async () => {
      const t = ta.value.trim(); if (!t) { KB.askOpen(true); return; }
      ta.value = ''; box.hidden = true;
      try { await KB.post('/api/chat/ask', { text: t, page: '/' }); KB.askOpen(true); } catch (e) { KB.toast(e.message); }
    };
    ta.onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); go(); } };
    $('#tplSayGo').onclick = go;
    ta.oninput = () => {
      ta.style.height = 'auto'; ta.style.height = Math.min(160, ta.scrollHeight) + 'px';
      clearTimeout(hd); hd = setTimeout(async () => {         // 回车之前先说它看懂了什么
        const t = ta.value.trim(); if (!t) { box.hidden = true; return; }
        try {
          const r = await KB.api('/api/intake/preview?text=' + enc(t));
          box.innerHTML = `<div class="tpl-ph2"><b>我的理解</b>${r['把握'] != null ? `<span class="tpl-conf" title="把握"><i style="width:${+r['把握']}%"></i></span><small>把握 ${esc(r['把握'])}%</small>` : ''}</div>
            ${(r['标签'] || []).length ? `<div class="tpl-tags">${r['标签'].map(([x, c]) => `<span class="tpl-tg tpl-tg-${esc(c)}">${esc(x)}</span>`).join('')}</div>` : ''}
            <div class="tpl-mut tpl-small">${r['计划'] ? '回车后：' + esc(r['计划']) : '回车交给管家，它会归到对应的地方。'}</div>`;
          box.hidden = false;
        } catch (_) { box.hidden = true; }
      }, 350);
    };
  }
  async function homeRefresh(force) {
    clearTimeout(homeTimer);
    if (KB.curHash() !== '/') return;
    try {
      const b = await KB.api('/api/brief'), sig = JSON.stringify(b).replace(/"时间":"[^"]*"/, '');
      if (KB.curHash() !== '/') return;
      if (force || (sig !== homeSig && KB.canRender() && !($('#tplSay') && $('#tplSay').value))) {
        const open = $('.tpl-why') && $('.tpl-why').open, mj = $('.tpl-morej') && $('.tpl-morej').open;
        BRIEF = b; homeSig = sig; KB.app.innerHTML = homeHtml(b); bindHome(b);
        if (open) $('.tpl-why').open = true; if (mj && $('.tpl-morej')) $('.tpl-morej').open = true;
        paintState();
      }
    } catch (e) { if (force) KB.app.innerHTML = `<section class="tpl-home"><p class="tpl-say">暂时连不上：${esc(e.message)}</p></section>`; }
    homeTimer = setTimeout(() => homeRefresh(false), 6000);   // AI 在做什么：6 秒看一次，有变化才重画
  }
  KBUI.css();
  KB.pages.home = () => homeRefresh(true);

  // ───────── 功能页的布局微调（core 画完之后） ─────────
  const FOLD = ['#tplApp > .bcard', '#tplApp > .card2', '#tplApp > .bgrid', '#tplApp > .tw', '#tplApp > .pgrid', '#tplApp > .stw',
    '[data-pane] > .card2 > .bd', '[data-pane] > .dev', '.matgrid > .cat > .bd', '#tplApp > .card2 .tw'];
  function folds(h) {
    const lim = mobile() ? 360 : 460;
    let i = 0;
    document.querySelectorAll(FOLD.join(',')).forEach(el => {
      const key = h + '|' + (i++);
      if (el.closest('.tpl-fold') || el.querySelector('.tpl-fold') || opened.has(key)) return;
      if (el.scrollHeight <= lim + 120) return;          // 只多一点就不折了
      el.classList.add('tpl-fold'); el.style.setProperty('--tpl-lim', lim + 'px');
      const n = el.querySelectorAll('tr, .cat, .bcard, .it, .hit, .pcard2, .devrow, .iss, .note, li').length;
      const bt = document.createElement('button'); bt.type = 'button'; bt.className = 'tpl-unfold';
      bt.textContent = '展开更多' + (n > 3 ? ` · 共 ${n} 项` : '');
      bt.onclick = () => { const on = el.classList.toggle('tpl-fold'); if (on) opened.delete(key); else opened.add(key); bt.textContent = on ? '展开更多' : '收起'; };
      el.after(bt);
    });
  }
  function tweakPeriod() {
    const ph = $('#tplApp > .pagehead'), ops = ph && ph.querySelector(':scope > .row');
    if (ops && !ops.closest('.tpl-ops')) {                 // 状态 / 更正链接 / 删除 / 视图 收进「更多」
      const d = document.createElement('details'); d.className = 'tpl-ops';
      d.innerHTML = '<summary title="状态、视图、更正链接、删除">⋯ 更多</summary>';
      ph.appendChild(d); d.appendChild(ops);
    }
    document.querySelectorAll('.gnext .who:not([data-tpl])').forEach(w => {      // 不催促：「需要你判断」/「AI 在做」
      w.dataset.tpl = '1';
      if (w.classList.contains('w-你')) w.textContent = '需要你判断';
      else if (w.classList.contains('w-AI')) w.innerHTML = '<i class="tpl-pulse"></i>AI 在做';
    });
    const p = periods().find(x => x['名称'] === KB.curHash().slice(3)), gn = $('.gnext');
    if (p && gn && !gn.querySelector('.tpl-gph')) {
      const ph2 = phaseOfStep(p['当前步骤']);
      gn.insertAdjacentHTML('afterbegin', `<span class="tpl-gph" title="${esc(p['流程'] || '')}流程">${esc(PHASES[ph2])}</span>`);
    }
  }
  function soften() {   // 经典总览 / 管家卡片里的催促措辞换成判断式
    document.querySelectorAll('#tplApp button').forEach(b => { if (b.textContent.trim() === '去处理') b.textContent = '看看'; });
    const W = [['该你了', '需要你判断'], ['👉 待你处理', '需要你判断'], ['待你处理', '需要你判断'], ['需要你处理的问题', '需要你判断的问题'], ['待你确认', '需要你判断']];
    document.querySelectorAll('#tplApp .gnext .who, #tplApp .stc > span.small, #tplApp .stc .tt, #tplApp .kpi .k').forEach(x => {
      if (x.children.length) return;
      let t = x.textContent; W.forEach(([a, b]) => { t = t.replace(a, b); }); if (t !== x.textContent) x.textContent = t;
    });
  }
  KB.hooks.afterRender = h => {
    const g = groupOf(h), app = KB.app;
    document.body.dataset.tplRoute = h === '/' ? 'home' : h.startsWith('/p/') ? 'period' : h.startsWith('/d/') ? 'docs' : h.split('/')[1] || 'home';
    app.classList.toggle('tpl-wide', ['/bugs', '/anr', '/classic'].includes(h) || h.startsWith('/d/'));
    app.classList.toggle('tpl-paper', g !== 'home');
    crumb(h); markDock(); paintState();
    if (h !== '/') {
      clearTimeout(homeTimer);
      if (h.startsWith('/p/')) tweakPeriod();
      soften(); folds(h);
    }
    if (lastHash !== h) {
      lastHash = h; closePop();
      if (!reduce.matches) { app.classList.remove('tpl-enter'); void app.offsetWidth; app.classList.add('tpl-enter'); }
    }
  };
  // core 有些区块是异步 / SSE 局部画的（管家卡片、开发进度、下一步），不经过 afterRender：看着内容变化，把措辞再改一次
  let moT = 0;
  new MutationObserver(() => { clearTimeout(moT); moT = setTimeout(() => { const h = KB.curHash(); if (h === '/') return; if (h.startsWith('/p/')) tweakPeriod(); soften(); }, 80); })
    .observe(KB.app, { childList: true, subtree: true });
  document.addEventListener('click', e => { if (e.target.closest('.ptab, .pview button')) setTimeout(() => folds(KB.curHash()), 60); });
  addEventListener('resize', () => { if (popK) openPop((k => (popK = '', k))(popK)); });
})();
