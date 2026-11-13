// From 大大王.DT
/* 界面模板「简报」：整个网站像一份 AI 每天编辑的刊物。
 *   骨架：报头（刊名、日期、AI 编辑时间、实时状态）+ 横向栏目（今日 / 项目 / 问题 / 资料 / 设置）+ 栏目下的小目录，没有侧栏。
 *   首页「今日」：AI 写的头条（标题、导语、带引用角标的正文），需要你判断的事以「编者按」嵌在文中；右栏是会说话的指标和注释。
 *     不同阶段（收集资料 → 方案拍板 → 并行开发 → 验收上线 → 线上维护）排在最前面的版块不同。
 *   项目（#/projects，本模板自定义路由）：所有期和事项的目录。期详情（#/p/）由 core 渲染，这里在 afterRender 里把它排成「专题文章」：
 *     阶段进度当副标题、下一步当导语、各板块当章节（带章节号和目录），并把这一期相关的编者按、AI 动态插在导语下面。
 *   其余页面（Bug、ANR、手机、基础信息、设置、文档、工具、搜索、经典总览）都是 core 渲染，这里只加栏目刊头，视觉交给 skin.css。
 * 只用 KB 公开的接口（见 /ui/core.js 顶部契约），自己的 id / class 都带 tpl 前缀。
 */
(function () {
  'use strict';
  const TPL = '简报';
  const esc = KB.esc, enc = KB.enc;
  const q = s => document.querySelector(s);
  KB.setApp('#tplApp');
  if (window.KBUI && KBUI.css) KBUI.css();   // KBUI 的公共样式（.kbt .jd .cf .ch …），编者按和理解预览要用；只有 render() 才会自动注入

  // ───────────────────────── 数据：整站导航（/api/site）和智能状态（/api/brief），报头和首页共用
  const S = { site: null, brief: null, briefAt: 0, briefSig: '' };
  async function loadBrief(force) {
    if (!force && S.brief && Date.now() - S.briefAt < 4000) return S.brief;
    try { S.brief = await KB.api('/api/brief'); S.briefAt = Date.now(); mastUpdate() } catch (_) {}
    return S.brief;
  }
  const curH = () => KB.curHash() || '/';
  const pName = h => h.startsWith('/p/') ? h.slice(3) : '';
  const siteP = n => ((S.site || {})['期'] || []).find(p => p['名称'] === n);

  // ───────────────────────── 阶段：把当前期的步骤映射到五个阶段，决定首页先讲什么
  const PHASES = [['collect', '收集资料'], ['plan', '方案拍板'], ['dev', '并行开发'], ['accept', '验收上线'], ['online', '线上维护']];
  const PH_NAME = Object.fromEntries(PHASES);
  function stepPhase(p) {
    if (!p) return 'online';
    if (p['状态'] === '已完成') return 'online';
    const s = p['当前步骤'] || '';
    if (/资料|仓库|收集|需求/.test(s)) return 'collect';
    if (/方案|拍板|设计/.test(s)) return 'plan';
    if (/开发|构建|联调|编码/.test(s)) return 'dev';
    if (/验收|上线|测试|审查/.test(s)) return 'accept';
    return { 收集中: 'collect', 已批准开发: 'plan', 开发中: 'dev', 已暂停: 'collect' }[p['状态']] || 'collect';
  }
  function leadPeriod(b) {
    const ps = ((S.site || {})['期'] || []).filter(p => !p['事项']);
    const prog = (b && b['进行中']) || [];
    let p = prog.length ? ps.find(x => x['名称'] === prog[0]['名称']) : null;
    if (!p) p = ps.filter(x => !['已完成', '已暂停'].includes(x['状态'])).sort((a, c) => String(c['更新时间'] || '').localeCompare(String(a['更新时间'] || '')))[0];
    return p || null;
  }

  // 一个期 / 事项属于哪个栏目：ANR / Bug 批次进「问题」，插件来源进「资料」，其余进「项目」
  function secOfPeriod(n) {
    const p = siteP(n) || {};
    if ((p['插件'] || []).length) return 'ref';
    if (p['批次'] && ['anr', 'bug'].includes(p['批次']['来源'])) return 'prob';
    if (p['事项'] && /ANR|崩溃|Bug/i.test(p['事项类型'] || '')) return 'prob';
    return 'proj';
  }
  function secOf(h) {
    if (h === '/' || h === '') return 'today';
    if (h === '/projects' || h === '/classic') return 'proj';
    if (h.startsWith('/p/')) return secOfPeriod(pName(h));
    if (h === '/bugs' || h === '/anr' || h === '/phones') return 'prob';
    if (h === '/base' || h.startsWith('/d/') || h.startsWith('/tool/') || h.startsWith('/s/')) return 'ref';
    if (h === '/settings') return 'set';
    return 'today';
  }

  // ───────────────────────── 报头：日期、刊号、AI 编辑时间、实时状态
  const WD = '日一二三四五六';
  function dateline() {
    const d = new Date(), start = new Date(d.getFullYear(), 0, 0), no = Math.floor((d - start) / 864e5);
    q('#tplDate').innerHTML = `<b>${d.getFullYear()} 年 ${d.getMonth() + 1} 月 ${d.getDate()} 日</b>　星期${WD[d.getDay()]}<span class="tpl-no">　第 ${no} 号</span>`;
  }
  function mastUpdate() {
    const b = S.brief; if (!b) return;
    const s = b['状态'] || {};
    const parts = [];
    if (s['等你']) parts.push(`<b class="tpl-st-ask">${s['等你']} 件事需要你判断</b>`);
    parts.push(s['在工作'] ? `<span class="tpl-st-work"><i class="tpl-pulse"></i>${s['在工作']} 个 AI 在工作</span>` : '<span>AI 都在休息</span>');
    parts.push(`<span>今天完成 ${s['今天完成'] || 0} 件</span>`);
    q('#tplStateTx').innerHTML = parts.join('<span class="tpl-sep">·</span>');
    q('#tplEdTime').textContent = b['时间'] ? `AI 编辑于 ${String(b['时间']).slice(11)}` : '';
    document.body.dataset.tplState = s['名称'] || '';
  }

  // ───────────────────────── 栏目导航：一行栏目 + 当前栏目的小目录
  const SECS = [['today', '今日', '#/'], ['proj', '项目', '#/projects'], ['prob', '问题', '#/bugs'], ['ref', '资料', '#/base'], ['set', '设置', '#/settings']];
  function secCount(k, site) {
    if (!site) return 0;
    if (k === 'proj') return site['期'].filter(p => secOfPeriod(p['名称']) === 'proj').reduce((a, p) => a + (p['待确认'] || 0), 0);
    if (k === 'prob') return ((site.Bug || {})['待归纳'] || 0) + ((site.ANR || {})['待处理'] || 0);
    return 0;
  }
  function drawSecs() {
    const site = S.site, h = curH(), cur = secOf(h);
    q('#tplSecs').innerHTML = SECS.map(([k, t, href], i) => {
      const n = secCount(k, site);
      return `<a class="tpl-sec${k === cur ? ' on' : ''}" href="${href}" data-sec="${k}"${k === cur ? ' aria-current="page"' : ''}><span class="tpl-sec-no">0${i + 1}</span>${t}${n ? `<sup class="tpl-sec-n" title="需要你看一眼的数目">${n}</sup>` : ''}</a>`;
    }).join('');
    drawSub(cur, h);
  }
  function subLink(href, label, on, extra) {
    return `<a class="tpl-subl${on ? ' on' : ''}" href="${esc(href)}"${extra || ''}>${label}</a>`;
  }
  function drawSub(cur, h) {
    const site = S.site, box = q('#tplSub'); if (!site) { box.innerHTML = ''; return }
    let html = '';
    const ps = site['期'];
    if (cur === 'today') {
      const p = leadPeriod(S.brief), ph = stepPhase(p);
      html = `<span class="tpl-sub-k">本刊阶段</span>${PHASES.map(([k, t], i) => `<span class="tpl-ph${k === ph ? ' on' : ''}">${i + 1} ${t}</span>`).join('<span class="tpl-ph-ar">›</span>')}${p ? `<span class="tpl-sub-note">焦点：<a href="#/p/${enc(p['名称'])}">${esc(p['名称'])}</a></span>` : ''}`;
    } else if (cur === 'proj') {
      const vis = ps.filter(p => secOfPeriod(p['名称']) === 'proj' && (!p['事项'] || p['状态'] !== '已完成'));
      html = subLink('#/projects', '全部项目', h === '/projects') + vis.map(p => subLink('#/p/' + enc(p['名称']), `<i class="tpl-dot" style="background:${KB.DOT[p['状态']] || 'var(--s0)'}"></i>${esc(p['名称'])}${p['待确认'] ? `<sup>${p['待确认']}</sup>` : ''}`, h === '/p/' + p['名称'], ` title="${esc((p['当前步骤'] || p['状态']) + (p['在跑'] ? ' · AI 在做' : ''))}"`)).join('')
        + subLink('#/classic', '经典总览', h === '/classic') + `<a class="tpl-subl tpl-subl-add" data-tpladd="new">＋ 新建一期</a>`;
    } else if (cur === 'prob') {
      const b = site.Bug || {}, a = site.ANR || {}, ph = site['手机'];
      const batches = ps.filter(p => secOfPeriod(p['名称']) === 'prob' && p['状态'] !== '已完成');
      html = subLink('#/bugs', `Bug${b['未关闭'] ? `<sup>${b['未关闭']}</sup>` : ''}`, h === '/bugs', ` title="未关闭 ${b['未关闭'] || 0} · 待归纳 ${b['待归纳'] || 0}"`)
        + subLink('#/anr', `ANR / 崩溃${a['待处理'] ? `<sup>${a['待处理']}</sup>` : ''}`, h === '/anr', ` title="待处理 ${a['待处理'] || 0} / 共 ${a['总数'] || 0}"`)
        + (ph ? subLink('#/phones', `测试手机 <span class="tpl-subn">${ph['空闲']}/${ph['总数']}</span>`, h === '/phones') : '')
        + (batches.length ? `<span class="tpl-sub-k">批次</span>` + batches.map(p => subLink('#/p/' + enc(p['名称']), esc(p['名称'].replace(/^(ANR\s*\/\s*崩溃|ANR|崩溃)\s*/, '') || p['名称']) + (p['批次'] && p['批次']['总数'] ? ` <span class="tpl-subn">${p['批次']['已处理']}/${p['批次']['总数']}</span>` : ''), h === '/p/' + p['名称'])).join('') : '');
    } else if (cur === 'ref') {
      const bi = site['基础信息'] || {};
      html = subLink('#/base', `基础信息 <span class="tpl-subn">${bi['条数'] || 0}</span>`, h === '/base')
        + subLink('#/d/', '文档', h === '/d/' && !(site['文档'] || []).length)
        + (site['文档'] || []).map(x => subLink(x['链接'], esc(x['名称']), '#' + h === x['链接'])).join('')
        + (site['工具'] || []).map(x => subLink(x['链接'], `${esc(x['图标'] || '')} ${esc(x['名称'])}${x['待确认'] ? `<sup>${x['待确认']}</sup>` : x['待解决'] ? ` <span class="tpl-subn">${x['待解决']}</span>` : ''}`, '#' + h === x['链接'], ` title="${esc(x['说明'] || '')}"`)).join('')
        + (h.startsWith('/s/') ? `<span class="tpl-sub-k">检索</span><span class="tpl-subl on">「${esc(h.slice(3).split('\u0001')[0])}」</span>` : '');
    } else if (cur === 'set') {
      const t = site['界面模板'] || {};
      html = subLink('#/settings', '编辑部设置', h === '/settings') + subLink('#/classic', '经典总览', false) + subLink('/?ui=classic', '临时看经典版', false)
        + `<span class="tpl-sub-note">当前界面：${esc(t['名称'] || '')}${new URLSearchParams(location.search).get('ui') ? '（本页临时用「简报」）' : ''}</span>`;
    }
    box.innerHTML = html;
    box.querySelectorAll('[data-tpladd]').forEach(a => a.onclick = () => KB.addDlg(a.dataset.tpladd));
    const on = box.querySelector('.on'); if (on && box.scrollWidth > box.clientWidth) on.scrollIntoView({ block: 'nearest', inline: 'center' });
  }
  KB.hooks.nav = (d, site) => {
    if (site) {
      S.site = site;
      const lo = q('#tplLogout'); lo.hidden = !site['登录']; lo.onclick = () => KB.logout();
    }
    drawSecs();
  };

  // ───────────────────────── 小部件
  const spark = (v, cls) => {
    if (!v || v.length < 2) return '';
    const mx = Math.max(...v, 1), pts = v.map((y, i) => `${(i / (v.length - 1) * 100).toFixed(1)},${(27 - y / mx * 23).toFixed(1)}`);
    return `<svg class="tpl-spark ${cls || ''}" viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts.join(' ')}" fill="none" stroke="currentColor" stroke-width="1.6" vector-effect="non-scaling-stroke"/><circle cx="100" cy="${(27 - v[v.length - 1] / mx * 23).toFixed(1)}" r="2.4" fill="currentColor"/></svg>`;
  };
  const conf = p => p == null ? '' : `<span class="tpl-conf" title="AI 的把握">把握 <span class="tpl-conf-m"><i style="width:${+p}%"></i></span> ${+p}%</span>`;
  const whoTag = w => w === '你' ? '<span class="tpl-who you">需要你判断</span>' : w === 'AI' ? '<span class="tpl-who ai"><i class="tpl-pulse"></i>AI 在做</span>' : '';
  // 编者按：一条需要你判断的事（按钮和字段交给 KBUI.judg / KBUI.bind，保持和其他模板同一套动作）
  const TYPE_LABEL = { 问你: '编者按 · 需要你判断', 待你: '编者按 · 需要你判断', 建议: '编者按 · AI 的建议' };
  function edNote(j, i) {
    const inner = window.KBUI ? KBUI.judg(j) : `<a href="${esc(j['链接'] || '#/')}">${esc(j['问题'])}</a>`;
    return `<aside class="tpl-ednote kbt" data-tplj="${esc(j.id)}"><div class="tpl-ednote-k"><span>${esc(TYPE_LABEL[j['类型']] || '编者按 · 需要你判断')}</span>${i != null ? `<span class="tpl-ednote-no">No.${i + 1}</span>` : ''}</div>${inner}</aside>`;
  }
  const briefOpts = {
    act: async (id, action, x) => {
      try { KB.toast((await KB.post('/api/brief/act', { id, action, ...x })).msg.split('\n')[0]) } catch (e) { KB.toast(e.message) }
      S.briefSig = ''; S.briefAt = 0; KB.render();
    },
    ask: async text => { try { await KB.post('/api/chat/ask', { text, page: '#' + curH() }); KB.askOpen(true) } catch (e) { KB.toast(e.message) } },
    preview: text => KB.api('/api/intake/preview?text=' + enc(text)),
    openAsk: () => KB.askOpen(true)
  };
  function bindJ(root) { if (window.KBUI && root) KBUI.bind(root, S.brief || {}, briefOpts) }

  // ───────────────────────── 首页「今日」：头条报告
  let homeTimer = null;
  function citeBody(n) {
    const cites = n['引用'] || [];
    return esc(n['正文'] || '').replace(/\[(\d+)\]/g, (_, i) => {
      const c = cites[i - 1];
      return c && c['链接'] ? `<a class="tpl-cite" href="${esc(c['链接'])}" title="${esc(c['文字'])}"><sup>${i}</sup></a>` : `<sup class="tpl-cite" title="${esc(c ? c['文字'] : '')}">${i}</sup>`;
    });
  }
  function standfirst(p, b) {
    if (!p) {
      const s = S.site || {};
      return `眼下没有推进中的期。${(s.Bug || {})['未关闭'] || (s.ANR || {})['待处理'] ? '本刊转入「线上维护」，重点看问题专栏。' : '线上很安静；有新需求交给管家就能开新的一期。'}`;
    }
    const st = p['步骤'] || [], i = st.findIndex(x => x['状态'] === 'cur'), nx = p['下一步'] || {};
    const pos = st.length && i >= 0 ? `第 ${i + 1}/${st.length} 步「${esc(st[i]['名称'])}」` : `「${esc(p['状态'])}」`;
    return `本期焦点是<a href="#/p/${enc(p['名称'])}">「${esc(p['名称'])}」</a>，走到${pos}。${nx['文字'] ? `下一步：${esc(nx['文字'])}${nx['谁'] === '你' ? '——这一步需要你判断。' : nx['谁'] === 'AI' ? '——AI 正在做。' : '。'}` : ''}`;
  }
  function modDecisions(b) {
    const js = b['判断'] || [];
    return `<section class="tpl-mod" id="tplModJ" data-mod="decisions"><h2 class="tpl-mod-h"><span>编者按</span><small>${js.length ? `${js.length} 件事需要你判断，附 AI 的建议、理由和把握` : '今天没有需要你判断的事'}</small></h2>
      ${js.length ? js.map((j, i) => edNote(j, i)).join('') : '<p class="tpl-quiet">AI 们按计划推进中。有需要你拍板的事，会在这里以编者按的形式出现。</p>'}</section>`;
  }
  function modWire(b) {
    const acts = b['活动'] || [];
    return `<section class="tpl-mod" data-mod="wire"><h2 class="tpl-mod-h"><span>编辑部动态</span><small>${acts.filter(a => !a['等你']).length ? `<i class="tpl-pulse"></i>${acts.filter(a => !a['等你']).length} 个 AI 正在写` : '此刻没有 AI 在工作'}</small></h2>
      ${acts.length ? `<ol class="tpl-wire">${acts.map(a => `<li class="${a['等你'] ? 'ask' : 'run'}"><div class="tpl-wire-h"><span class="tpl-role" style="--rc:${esc(a['颜色'] || '#64748b')}">${esc(a['角色'])}</span>
          <a href="${esc(a['链接'] || '#/')}" class="tpl-wire-o">${esc(a['对象'])}</a><span class="tpl-wire-s">${a['等你'] ? '需要你判断' : esc(a['状态'])}</span>${a['开始'] ? `<span class="tpl-wire-t" data-since="${esc(a['开始'])}">${esc(KB.since(a['开始']))}</span>` : ''}</div>
          ${(a['步骤'] || []).length ? `<div class="tpl-wire-steps">${a['步骤'].slice(-3).map((s, i, arr) => `<div class="${i === arr.length - 1 && !a['等你'] ? 'now' : ''}">${esc(s)}</div>`).join('')}</div>` : ''}</li>`).join('')}</ol>`
        : `<p class="tpl-quiet">编辑部此刻都在休息，今天已经替你完成 ${((b['状态'] || {})['今天完成']) || 0} 件。</p>`}</section>`;
  }
  function modProgress(b) {
    const prog = b['进行中'] || [];
    if (!prog.length) return '';
    return `<section class="tpl-mod" data-mod="progress"><h2 class="tpl-mod-h"><span>连载中</span><small>${prog.length} 个项目的进度</small></h2>
      <ol class="tpl-serial">${prog.map(p => { const sp = siteP(p['名称']) || {}; return `<li><a class="tpl-serial-t" href="${esc(p['链接'])}">${esc(p['名称'])}</a>
        <div class="tpl-track" aria-label="进度 ${+p['进度'] || 0}%">${(sp['步骤'] || []).map(s => `<span class="${s['状态']}" title="${esc(s['名称'])}">${esc(s['名称'])}</span>`).join('') || `<span class="cur">${esc(p['阶段'] || '')}</span>`}</div>
        <div class="tpl-serial-n">下一步：${esc(p['下一步'] || '—')} ${whoTag(p['谁'])}</div></li>` }).join('')}</ol></section>`;
  }
  function modGaps(b) {
    const g = b['关系']; if (!g) return '';
    const miss = (g['节点'] || []).filter(n => n['状态'] === 'miss' || n['状态'] === 'bad');
    const have = (g['节点'] || []).filter(n => ['需求', '设计', '接口'].includes(n['类']) && n['状态'] !== 'miss');
    return `<section class="tpl-mod" data-mod="gaps"><h2 class="tpl-mod-h"><span>稿件清单</span><small>「${esc(g['标题'])}」的资料和方案，AI 读到了什么、还缺什么</small></h2>
      <ul class="tpl-gaps">${have.map(n => `<li class="ok"><b>${esc(n['名称'])}</b><span>${esc(n['说明'] || '已收到')}</span></li>`).join('')}${miss.map(n => `<li class="miss"><b>${esc(n['名称'])}</b><span>${esc(n['说明'] || '还没有')}</span></li>`).join('')}</ul>
      ${g['洞察'] && g['洞察']['标题'] ? `<p class="tpl-insight"><b>AI 的看法：</b>${esc(g['洞察']['标题'])}${g['洞察']['内容'] ? '。' + esc(g['洞察']['内容']) : ''} <a href="${esc(g['链接'])}">去这一期 →</a></p>` : ''}</section>`;
  }
  function modProblems() {
    const s = S.site; if (!s) return '';
    const b = s.Bug || {}, a = s.ANR || {};
    const bt = s['期'].filter(p => secOfPeriod(p['名称']) === 'prob' && p['状态'] !== '已完成');
    const calm = !b['未关闭'] && !a['待处理'] && !bt.length;
    return `<section class="tpl-mod" data-mod="problems"><h2 class="tpl-mod-h"><span>问题专栏</span><small>${calm ? '线上很安静' : '线上反馈和崩溃，AI 已按堆栈归并'}</small></h2>
      <div class="tpl-probrow"><a href="#/bugs"><b>${b['未关闭'] || 0}</b><span>未关闭 Bug${b['待归纳'] ? `，${b['待归纳']} 个待归纳` : ''}</span></a><a href="#/anr"><b>${a['待处理'] || 0}</b><span>待处理 ANR / 崩溃，共 ${a['总数'] || 0} 个问题</span></a></div>
      ${bt.length ? `<ul class="tpl-plist">${bt.map(p => `<li><a href="#/p/${enc(p['名称'])}">${esc(p['名称'])}</a> <span class="tpl-mut">${esc(p['说明'] || '')}</span>${p['批次'] && p['批次']['总数'] ? ` <span class="tpl-subn">已处理 ${p['批次']['已处理']}/${p['批次']['总数']}</span>` : ''}${p['在跑'] ? ' <span class="tpl-who ai"><i class="tpl-pulse"></i>AI 在做</span>' : ''}</li>`).join('')}</ul>` : ''}</section>`;
  }
  function modOther(b) {
    const o = b['其他'] || []; if (!o.length) return '';
    return `<section class="tpl-mod" data-mod="other"><h2 class="tpl-mod-h"><span>简讯</span></h2><ul class="tpl-plist">${o.map(x => `<li><a href="${esc(x['链接'] || '#/')}">${esc(x['标题'])}</a> <span class="tpl-mut">${esc(x['说明'] || '')}</span></li>`).join('')}</ul></section>`;
  }
  function modIntake(b) {
    return `<section class="tpl-mod tpl-intake" data-mod="intake"><h2 class="tpl-mod-h"><span>投稿</span><small>需求、日志、Bug 链接、账号……交给管家，它先说它的理解再动手</small></h2>
      <textarea data-ask rows="3" placeholder="贴什么都行；回车交给管家，Shift+回车换行"></textarea>
      <div class="tpl-intake-bar"><span class="tpl-mut">边输边看 AI 的理解</span><button class="pri" data-askgo>交给管家</button></div>
      <div class="tpl-intake-parse" data-parse>${(b['判断'] || [])[0] ? '<span class="tpl-mut">输入后这里显示 AI 怎么理解、打算怎么做。</span>' : '<span class="tpl-mut">现在没有需要你判断的事；输入后这里显示 AI 的理解。</span>'}</div></section>`;
  }
  const ORDER = {
    collect: ['gaps', 'decisions', 'progress', 'wire', 'problems', 'other'],
    plan: ['decisions', 'progress', 'gaps', 'wire', 'problems', 'other'],
    dev: ['wire', 'decisions', 'progress', 'problems', 'other'],
    accept: ['decisions', 'progress', 'wire', 'problems', 'other'],
    online: ['problems', 'decisions', 'wire', 'progress', 'other']
  };
  const FOCUS_TIP = { collect: '本阶段重点：资料齐不齐', plan: '本阶段重点：方案定不定', dev: '本阶段重点：各端进展', accept: '本阶段重点：能不能上线', online: '本阶段重点：线上健康' };
  function railMetrics(b) {
    const s = S.site || {}, ms = (b['指标'] || []).slice();
    const tell = (n, zero, some) => n ? some : zero;
    if (s.Bug) ms.push({ 名称: '未关闭 Bug', 值: String(s.Bug['未关闭'] || 0), 单位: '个', 说明: tell(s.Bug['未关闭'], '很安静', s.Bug['待归纳'] ? `${s.Bug['待归纳']} 个等你归到期里` : '都已归档'), 链接: '#/bugs' });
    if (s.ANR) ms.push({ 名称: 'ANR / 崩溃', 值: String(s.ANR['待处理'] || 0), 单位: '待处理', 说明: `已归并 ${s.ANR['总数'] || 0} 个问题`, 链接: '#/anr' });
    if (s['手机']) ms.push({ 名称: '测试手机', 值: `${s['手机']['空闲']}/${s['手机']['总数']}`, 单位: '空闲', 说明: s['手机']['总数'] ? '' : '还没连手机', 链接: '#/phones' });
    return ms.map(m => { const L = m['链接'] ? `a href="${esc(m['链接'])}"` : 'div';
      return `<${L} class="tpl-met"><span class="tpl-met-k">${esc(m['名称'])}</span><span class="tpl-met-v">${esc(m['值'])}<small>${esc(m['单位'] || '')}</small></span>${spark(m['趋势'])}${m['说明'] ? `<span class="tpl-met-s">${esc(m['说明'])}</span>` : ''}</${L.split(' ')[0]}>` }).join('');
  }
  async function homePage(quiet) {
    const [b] = await Promise.all([loadBrief(true), S.site ? null : KB.api('/api/site').then(s => { S.site = s; drawSecs() }).catch(() => {})]);
    if (!b) { KB.app.innerHTML = '<p class="tpl-quiet">编辑部暂时联系不上（/api/brief 出错），稍后自动重试。</p>'; return }
    const sig = JSON.stringify(b).replace(/"时间":"[^"]*"/, '') + JSON.stringify((S.site || {}).Bug) + JSON.stringify((S.site || {}).ANR);
    if (quiet && sig === S.briefSig && KB.app.querySelector('.tpl-home')) return;
    S.briefSig = sig;
    const n = b['叙述'] || {}, cites = n['引用'] || [], p = leadPeriod(b), ph = stepPhase(p);
    const mods = { decisions: modDecisions, wire: modWire, progress: modProgress, gaps: modGaps, problems: modProblems, other: modOther };
    const order = ORDER[ph].map(k => mods[k](b)).filter(Boolean);
    if (order.length) order[0] = order[0].replace('class="tpl-mod"', `class="tpl-mod tpl-focus" data-focus="${esc(FOCUS_TIP[ph])}"`);
    const st = b['状态'] || {};
    KB.app.innerHTML = `<div class="tpl-home kbt" data-ph="${ph}">
      <div class="tpl-front">
        <article class="tpl-lead">
          <div class="tpl-kicker"><span class="tpl-kicker-r">头条</span>${esc(PH_NAME[ph])}${p ? ` · ${esc(p['名称'])}` : ''}</div>
          <h1 class="tpl-hl">${esc(n['标题'] || b['问候'] || '今日简报')}</h1>
          <p class="tpl-standfirst">${standfirst(p, b)}</p>
          <div class="tpl-byline"><span>文 / AI 编辑部</span><span>${esc(String(b['时间'] || '').slice(11))} 更新</span><span class="tpl-byline-st st-${esc(st['名称'] || '')}">${esc(st['名称'] || '')}</span></div>
          ${n['正文'] ? `<div class="tpl-prose${/^[\p{L}\p{N}]/u.test(n['正文']) ? ' tpl-dropcap' : ''}"><p>${citeBody(n)}</p></div>` : ''}
          ${order.join('')}
          ${modIntake(b)}
        </article>
        <aside class="tpl-rail" aria-label="指标和注释">
          <div class="tpl-rail-h">数字会说话</div>${railMetrics(b)}
          ${cites.length ? `<div class="tpl-rail-h">注释</div><ol class="tpl-notes">${cites.map(c => `<li>${c['链接'] ? `<a href="${esc(c['链接'])}">${esc(c['文字'])}</a>` : esc(c['文字'])}</li>`).join('')}</ol>` : ''}
          ${b['管家'] ? `<div class="tpl-rail-h">编辑部守则</div><div class="tpl-rules">${(b['管家']['规矩'] || []).slice(0, 3).map(r => `<p>「${esc(r['内容'])}」<span class="tpl-mut">— ${esc(r['来自'] || '你')}</span></p>`).join('') || '<p class="tpl-mut">还没有规矩。</p>'}
            <p class="tpl-mut">管家${b['管家']['设置'] && b['管家']['设置']['开启'] ? `在值班（自主度：${esc(b['管家']['设置']['自主度'] || '')}）` : '休息中'}${b['管家']['上次'] ? `，上次巡视 ${esc(String(b['管家']['上次']).slice(5))}` : ''}。<a href="#/settings">调整</a></p></div>` : ''}
        </aside>
      </div></div>`;
    bindJ(KB.app.querySelector('.tpl-home'));
    clearTimeout(homeTimer);
    homeTimer = setTimeout(function tick() {   // AI 在做什么：8 秒看一次，有变化才重画，不打断输入
      if (curH() !== '/') return;
      if (KB.canRender()) homePage(true).catch(() => {}); else homeTimer = setTimeout(tick, 8000);
    }, 8000);
  }
  KB.pages.home = () => homePage(false);

  // ───────────────────────── 项目目录（#/projects）
  async function projectsPage() {
    const [site, b] = await Promise.all([KB.api('/api/site'), loadBrief()]);
    S.site = site; drawSecs();
    const all = site['期'].filter(p => secOfPeriod(p['名称']) === 'proj');
    const ps = all.filter(p => !p['事项']), ts = all.filter(p => p['事项']);
    const active = ps.filter(p => !['已完成', '已暂停'].includes(p['状态'])), rest = ps.filter(p => ['已完成', '已暂停'].includes(p['状态']));
    const asks = ((b || {})['判断'] || []);
    const askOf = n => asks.filter(j => j['链接'] === '#/p/' + n).length;
    const row = (p, i) => {
      const st = p['步骤'] || [], nx = p['下一步'] || {};
      return `<li class="tpl-toc-row"><span class="tpl-toc-no">${String(i + 1).padStart(2, '0')}</span>
        <div class="tpl-toc-main"><a class="tpl-toc-t" href="#/p/${enc(p['名称'])}">${esc(p['名称'])}</a> ${KB.badge(p['状态'])}
          ${p['说明'] ? `<p class="tpl-toc-d">${esc(p['说明'])}</p>` : ''}
          ${st.length ? `<div class="tpl-track">${st.map(s => `<span class="${s['状态']}">${esc(s['名称'])}</span>`).join('')}</div>` : ''}
          ${nx['文字'] ? `<div class="tpl-serial-n">下一步：${esc(nx['文字'])} ${whoTag(nx['谁'])}</div>` : ''}</div>
        <div class="tpl-toc-side">${p['在跑'] ? '<span class="tpl-who ai"><i class="tpl-pulse"></i>AI 在做</span>' : ''}${askOf(p['名称']) || p['待确认'] ? `<span class="tpl-who you">${askOf(p['名称']) + (p['待确认'] || 0)} 件需要你判断</span>` : ''}
          ${p['没解决Bug'] ? `<span class="tpl-subn">${p['没解决Bug']} 个 Bug 没解决</span>` : ''}<span class="tpl-mut">${esc(String(p['更新时间'] || '').slice(5))}</span></div></li>`;
    };
    const ph = stepPhase(leadPeriod(b));
    KB.app.innerHTML = `<div class="tpl-colhead"><div class="tpl-kicker"><span class="tpl-kicker-r">项目</span>本刊连载目录</div><h1>所有项目</h1>
        <p class="tpl-dek">${active.length} 个期在推进${rest.length ? `，${rest.length} 个已完成或暂停` : ''}${ts.length ? `；另有 ${ts.length} 个事项` : ''}。整体处在「${esc(PH_NAME[ph])}」阶段${asks.length ? `，有 ${asks.length} 件事需要你判断` : ''}。</p>
        <div class="row"><button class="pri" data-tpladd="new">＋ 新建一期</button><button data-tpladd="task">＋ 新建事项</button><a href="#/classic">经典总览 →</a></div></div>
      <section class="tpl-chapter"><h2 class="tpl-mod-h"><span>推进中</span><small>${active.length} 期</small></h2>${active.length ? `<ol class="tpl-toc">${active.map(row).join('')}</ol>` : '<p class="tpl-quiet">没有推进中的期。把需求交给管家，或点「＋ 新建一期」。</p>'}</section>
      ${ts.length ? `<section class="tpl-chapter"><h2 class="tpl-mod-h"><span>事项</span><small>Bug、埋点、零碎任务</small></h2><ol class="tpl-toc">${ts.map((p, i) => `<li class="tpl-toc-row"><span class="tpl-toc-no">${String(i + 1).padStart(2, '0')}</span><div class="tpl-toc-main"><a class="tpl-toc-t" href="#/p/${enc(p['名称'])}">${esc(p['名称'])}</a> ${KB.badge(p['状态'])} <span class="tpl-subn">${esc(p['事项类型'] || '事项')} · 优先级 ${esc(p['优先级'] || '中')}</span>${p['说明'] ? `<p class="tpl-toc-d">${esc(p['说明'])}</p>` : ''}</div><div class="tpl-toc-side">${p['在跑'] ? '<span class="tpl-who ai"><i class="tpl-pulse"></i>AI 在做</span>' : ''}${p['待确认'] ? `<span class="tpl-who you">${p['待确认']} 件需要你判断</span>` : ''}<span class="tpl-mut">${esc(String(p['更新时间'] || '').slice(5))}</span></div></li>`).join('')}</ol></section>` : ''}
      ${rest.length ? `<section class="tpl-chapter"><h2 class="tpl-mod-h"><span>已完成 / 暂停</span><small>${rest.length} 期</small></h2><ol class="tpl-toc tpl-toc-dim">${rest.map(row).join('')}</ol></section>` : ''}`;
    KB.app.querySelectorAll('[data-tpladd]').forEach(x => x.onclick = () => KB.addDlg(x.dataset.tpladd));
  }
  KB.routes['/projects'] = projectsPage;

  // ───────────────────────── 期详情 → 专题文章
  const CN = '一二三四五六七八九十';
  async function periodEnhance(name) {
    const app = KB.app, head = app.querySelector('.pagehead');
    if (!head) return;
    const sp = siteP(name) || {};
    const crumb = head.querySelector('.crumb');
    if (crumb && !crumb.querySelector('.tpl-kicker-r')) crumb.insertAdjacentHTML('afterbegin', `<span class="tpl-kicker-r">${secOfPeriod(name) === 'prob' ? '问题专栏' : sp['事项'] ? '事项' : '专题'}</span>`);
    // 下一步 → 导语：「该你了」换成「需要你判断」
    app.querySelectorAll('.gnext .who').forEach(w => { w.textContent = w.classList.contains('w-你') ? '需要你判断' : w.classList.contains('w-AI') ? 'AI 在做' : w.textContent });
    const gn = app.querySelector('.gnext');
    if (gn && !gn.querySelector('.tpl-lede-k')) gn.insertAdjacentHTML('afterbegin', '<span class="tpl-lede-k">导语</span>');
    // 章节：目录（.ptabs）编号，每个板块加章节标题
    const tabs = [...app.querySelectorAll('.ptabs .ptab')];
    const whole = !!app.querySelector('.pwhole');
    tabs.forEach((a, i) => {
      if (!a.querySelector('.tpl-chno')) a.insertAdjacentHTML('afterbegin', `<span class="tpl-chno">${CN[i] || i + 1}</span>`);
      const pane = app.querySelector(`[data-pane="${a.dataset.tab}"]`); if (!pane) return;
      const label = [...a.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
      if (whole) { const h = pane.querySelector('.psec'); if (h && !h.querySelector('.tpl-chno')) h.insertAdjacentHTML('afterbegin', `<span class="tpl-chno">第${CN[i] || i + 1}章</span>`) }
      else if (!pane.querySelector(':scope>.tpl-chap')) pane.insertAdjacentHTML('afterbegin', `<h2 class="tpl-chap"><span class="tpl-chno">第${CN[i] || i + 1}章</span>${esc(label)}</h2>`);
      if (whole) a.onclick = () => pane.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
    });
    const nav = app.querySelector('.ptabs');
    if (nav && !nav.previousElementSibling?.classList?.contains('tpl-toc-k')) nav.insertAdjacentHTML('beforebegin', `<div class="tpl-toc-k" style="order:-2">本文目录${whole ? '（整页：点章节跳过去）' : '（分栏：点章节切换）'}</div>`);
    // 会话框 → 编辑部热线
    const talk = app.querySelector('.talk .bd');
    if (talk && !talk.querySelector('.tpl-talk-k')) talk.insertAdjacentHTML('afterbegin', '<div class="tpl-talk-k">给这一期的 AI 留言</div>');
    // 导语下面：这一期相关的编者按和 AI 动态
    let box = app.querySelector('#tplPNotes');
    if (!box) {
      box = document.createElement('div'); box.id = 'tplPNotes'; box.className = 'tpl-pnotes';
      const anchor = app.querySelector('.gnext') || app.querySelector('.notice') || app.querySelector('.steps') || head;
      anchor.after(box);
    }
    const b = await loadBrief();
    if (!b || pName(curH()) !== name || !box.isConnected) return;
    const link = '#/p/' + name;
    const js = (b['判断'] || []).filter(j => j['链接'] === link || ((j['提议'] || {})['事项'] === name));
    const acts = (b['活动'] || []).filter(a => a['链接'] === link || a['对象'] === name);
    box.innerHTML = (acts.length ? `<div class="tpl-pwire">${acts.map(a => `<span class="tpl-role" style="--rc:${esc(a['颜色'] || '#64748b')}">${esc(a['角色'])}</span><span>${a['等你'] ? '需要你判断' : `<i class="tpl-pulse"></i>${esc(a['状态'])}`}</span>${(a['步骤'] || []).length ? `<span class="tpl-pwire-s">${esc(a['步骤'][a['步骤'].length - 1])}</span>` : ''}`).join('<br>')}</div>` : '')
      + js.map(j => edNote(j)).join('');
    bindJ(box);
  }

  // 其他页面：栏目刊头（栏目名 + AI 的一句话）
  const KICK = {
    '/bugs': ['问题专栏', () => { const b = (S.site || {}).Bug || {}; return b['未关闭'] ? `未关闭 ${b['未关闭']} 个，${b['待归纳'] ? `${b['待归纳']} 个等你归到期里` : '都已归档'}。分析由后台 AI 只读完成，结论等你审核。` : 'AI 盘点：没有未关闭的 Bug。' }],
    '/anr': ['问题专栏', () => { const a = (S.site || {}).ANR || {}; return `AI 已按关键堆栈归并 ${a['总数'] || 0} 个问题${a['待处理'] ? `，其中 ${a['待处理']} 个待处理` : '，都已有着落'}。` }],
    '/phones': ['问题专栏', () => { const p = (S.site || {})['手机']; return p ? `${p['总数']} 台测试手机，${p['空闲']} 台空闲。` : '' }],
    '/base': ['编辑部手册', () => '账号、地址、环境：AI 干活时查这里，机密只存在钥匙串 / vault。'],
    '/settings': ['编辑部手册', () => 'AI 引擎、开发流程、管家的自主度和规矩、插件、界面模板。'],
    '/classic': ['项目', () => '经典总览：原来的卡片视图，信息最全。'],
    '/d/': ['资料室', () => ''], '/tool/': ['资料室', () => ''], '/s/': ['资料室 · 检索', () => '']
  };
  function kicker(h) {
    const k = ['/d/', '/tool/', '/s/'].find(x => h.startsWith(x)) || h;
    if (!KICK[k]) return;
    const app = KB.app; if (app.querySelector('.tpl-pk')) return;
    const [label, fn] = KICK[k], dek = fn();
    const h1 = app.querySelector('h1');
    const html = `<div class="tpl-pk"><span class="tpl-kicker-r">${esc(label)}</span>${dek ? `<span class="tpl-pk-d">${esc(dek)}</span>` : ''}</div>`;
    if (h1) {
      const ph = h1.closest('.pagehead');
      if (ph) ph.insertAdjacentHTML('beforebegin', html); else if (h1.parentElement === app || h1.parentElement.classList.contains('row')) (h1.parentElement === app ? h1 : h1.parentElement).insertAdjacentHTML('beforebegin', html); else h1.insertAdjacentHTML('beforebegin', html);
    } else app.insertAdjacentHTML('afterbegin', html);
  }

  // ───────────────────────── 每次页面画完：标题、栏目高亮、版式
  KB.hooks.afterRender = h => {
    h = h || '/';
    const kind = h === '/' ? 'home' : h.startsWith('/p/') ? 'period' : h === '/projects' ? 'projects' : h.startsWith('/d/') ? 'docs' : h.startsWith('/s/') ? 'search' : h.startsWith('/tool/') ? 'tool' : h.slice(1) || 'home';
    document.body.dataset.tplR = kind;
    document.body.dataset.tplSec = secOf(h);
    const sec = SECS.find(s => s[0] === secOf(h));
    document.title = (h === '/' ? '今日' : h.startsWith('/p/') ? pName(h) : (sec ? sec[1] : '')) + ' · 知识库简报';
    drawSecs();
    if (kind === 'period') periodEnhance(pName(h)).catch(e => console.error(e));
    else if (kind !== 'home' && kind !== 'projects') kicker(h);
    if (h !== '/') clearTimeout(homeTimer);
  };

  // ───────────────────────── 实时：数据变了就刷报头；首页自己会刷
  KB.on('overview', () => { S.briefAt = 0; loadBrief(true) });
  KB.on('dev', () => { S.briefAt = 0; loadBrief(true) });
  setInterval(() => { if (curH() !== '/' && !document.hidden) loadBrief(true) }, 30000);

  // 报头按钮、换回经典
  q('#tplAsk').onclick = () => KB.askOpen(true);
  q('#tplBack').onclick = () => { if (confirm('把界面换回经典？（会改设置，整站重新加载）')) KB.setTemplate('经典') };
  dateline();
  loadBrief(true);
})();
