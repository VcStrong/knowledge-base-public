/* 知识库界面模板：一份「智能状态」（/api/brief，见 kblib/brief.py），几种摆法。
 * 网页总览和设置里的预览（/ui-preview）都用这一个文件，模板里只摆放、不写业务：
 *   KBUI.render(名称, 状态, 选项) → HTML；KBUI.bind(根元素, 状态, 选项) → 绑定按钮。
 *   选项：act(判断编号, 动作, {value, repo, branch}) 执行判断；ask(文字) 交给管家；preview(文字) → 理解预览；demo 为真时按钮只做样子。
 * 加新模板：在 T 里加一项 {名称, 说明, html(b, o)}，并把不认识的素材交给 other(b) 兜底。
 */
(function () {
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const home = p => { const s = String(p || '').replace(/^\/Users\/[^/]+/, '~').split('/'); return s.length > 4 ? '…/' + s.slice(-2).join('/') : s.join('/') };
  const CSS = `
.kbt{--g:#14b8a6;--gb:#dcf6f2;--th:#8b5cf6;--thb:#efe9fe;--wn:#c2410c;--wnb:#fdeee4;--okc:#15803d;--okb2:#e2f4e8;--bd:#c4321f;--bdb:#fde8e5;
  --dk:#0e1422;--dkfg:#e7ebf3;--dkmut:#8a93a8;--dkline:#232c3f;font-size:13px;color:var(--fg)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .kbt{--g:#2dd4bf;--gb:#10302d;--th:#a78bfa;--thb:#261f45;--wn:#fb923c;--wnb:#3a2414;--okc:#4ade80;--okb2:#14301f;--bd:#ff8a7a;--bdb:#3d1c19;--dk:#080c14;--dkline:#1d2537}}
:root[data-theme="dark"] .kbt{--g:#2dd4bf;--gb:#10302d;--th:#a78bfa;--thb:#261f45;--wn:#fb923c;--wnb:#3a2414;--okc:#4ade80;--okb2:#14301f;--bd:#ff8a7a;--bdb:#3d1c19;--dk:#080c14;--dkline:#1d2537}
.kbt *{box-sizing:border-box}
.kbt .mono{font-family:"SF Mono",ui-monospace,Menlo,monospace;font-size:11.5px}
.kbt .mt{color:var(--mut)}.kbt .sm{font-size:11.5px}
.kbt .ch{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;padding:2px 9px;border-radius:999px;background:var(--soft);color:var(--mut);white-space:nowrap}
.kbt .ch.g{background:var(--gb);color:var(--g)}.kbt .ch.t{background:var(--thb);color:var(--th)}.kbt .ch.w{background:var(--wnb);color:var(--wn)}.kbt .ch.b{background:var(--bdb);color:var(--bd)}.kbt .ch.o{background:var(--okb2);color:var(--okc)}
.kbt .cf{display:inline-flex;align-items:center;gap:6px;font-size:11px;color:var(--mut)}.kbt .cf .m{width:46px;height:4px;border-radius:2px;background:var(--soft);overflow:hidden}.kbt .cf .m i{display:block;height:100%;background:var(--g)}
.kbt .yes{display:inline-block;padding:6px 12px;border-radius:8px;background:var(--fg);color:var(--bg);font-weight:600;font-size:12px;border:0;cursor:pointer;font-family:inherit;text-decoration:none}
.kbt .alt{display:inline-block;padding:6px 10px;border-radius:8px;border:1px solid var(--line);background:transparent;color:var(--fg);font-size:12px;cursor:pointer;font-family:inherit;text-decoration:none}
.kbt .live{width:7px;height:7px;border-radius:50%;background:var(--g);display:inline-block;flex:none;animation:kbtping 1.8s ease-out infinite}
@keyframes kbtping{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--g) 60%,transparent)}100%{box-shadow:0 0 0 8px transparent}}
.kbt .caret::after{content:"▍";color:var(--g);animation:kbtblink 1s steps(2) infinite;margin-left:1px}@keyframes kbtblink{50%{opacity:0}}
@media (prefers-reduced-motion:reduce){.kbt *{animation:none!important;transition:none!important}}
.kbt .jd{display:grid;gap:7px;min-width:0}.kbt .jd .h{display:flex;justify-content:space-between;gap:4px 8px;align-items:center;flex-wrap:wrap}.kbt .jd .why{font-size:12px;color:var(--mut)}
.kbt .jd .acts{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.kbt .jd select,.kbt .jd input{font:inherit;font-size:12px;padding:4px 8px;border:1px solid var(--line);border-radius:7px;background:var(--bg);color:var(--fg);min-width:0;max-width:100%}
.kbt .jd .fields{display:grid;grid-template-columns:auto 1fr;gap:6px 10px;align-items:center;font-size:12px}
.kbt .other{display:grid;gap:6px;margin-top:10px}.kbt .other a{display:block;padding:8px 10px;border:1px solid var(--line);border-radius:9px;background:var(--card);color:var(--fg);text-decoration:none}
.kbt .strip{display:flex;gap:6px;flex-wrap:wrap}
/* 指挥台 */
.kbt.t1{background:radial-gradient(90% 50% at 50% 0%,var(--accb),transparent 70%);border-radius:14px;padding:26px 16px 22px;display:flex;flex-direction:column;align-items:center;gap:14px}
.kbt.t1 .greet{font-size:21px;font-weight:600;text-align:center;text-wrap:balance;max-width:640px}
.kbt.t1 .box{width:100%;max-width:640px;background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:0 8px 24px rgba(15,25,50,.08);overflow:hidden}
.kbt.t1 textarea{width:100%;border:0;outline:0;resize:none;padding:13px 14px;font:inherit;font-size:14px;background:transparent;color:var(--fg);min-height:52px;display:block}
.kbt.t1 .bar{display:flex;justify-content:space-between;align-items:center;padding:6px 10px 8px 14px;color:var(--mut);font-size:12px}
.kbt.t1 .parse{border-top:1px dashed var(--line);padding:11px 14px;display:grid;gap:8px;background:color-mix(in srgb,var(--gb) 45%,var(--card))}
.kbt.t1 .amb{width:100%;max-width:640px;display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px}
.kbt.t1 .amb a,.kbt.t1 .amb div{background:color-mix(in srgb,var(--card) 75%,transparent);border:1px solid var(--line);border-radius:10px;padding:8px 10px;display:grid;gap:2px;color:var(--fg);text-decoration:none;min-width:0}
.kbt.t1 .more{width:100%;max-width:640px;display:grid;gap:8px}.kbt.t1 .more .jd{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
/* 团队 */
.kbt.t2 .hd{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px}.kbt.t2 .hd b{font-size:16px}
.kbt.t2 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px}
.kbt.t2 .ag{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 11px;display:flex;flex-direction:column;gap:6px;min-width:0;color:var(--fg);text-decoration:none}
.kbt.t2 .ag.idle{opacity:.5}.kbt.t2 .ag.ask{border-color:var(--wn);box-shadow:0 0 0 3px var(--wnb)}
.kbt.t2 .ag .h{display:flex;gap:7px;align-items:center}.kbt.t2 .av{width:24px;height:24px;border-radius:8px;display:grid;place-items:center;font-size:12px;font-weight:700;color:#fff;flex:none}
.kbt.t2 .ag .nm{font-weight:600;flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kbt.t2 .feed{display:grid;gap:4px;border-left:2px solid var(--line);padding-left:8px;margin-left:3px}
.kbt.t2 .feed .s{font-family:"SF Mono",ui-monospace,Menlo,monospace;font-size:10.5px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.kbt.t2 .feed .s.now{color:var(--fg)}
.kbt.t2 .asks{display:grid;gap:8px;margin-top:12px}.kbt.t2 .asks .jd{background:var(--wnb);border-radius:12px;padding:10px 12px}
.kbt.t2 .foot{margin-top:12px;font-size:12px;color:var(--mut);display:flex;gap:8px;align-items:center}
/* 画布 */
.kbt.t3{background:var(--dk);color:var(--dkfg);border-radius:14px;overflow:hidden}
.kbt.t3 .hd{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid var(--dkline)}.kbt.t3 .hd a{color:var(--dkfg);font-weight:600;text-decoration:none}
.kbt.t3 .hd .ch{background:var(--dkline);color:var(--dkmut)}
.kbt.t3 .cv{position:relative;height:440px;background-image:radial-gradient(var(--dkline) 1px,transparent 1px);background-size:18px 18px}
.kbt.t3 svg{position:absolute;inset:0;width:100%;height:100%}
.kbt.t3 .nd{position:absolute;transform:translate(-50%,-50%);background:#151d2e;border:1px solid var(--dkline);border-radius:10px;padding:6px 10px;font-size:11.5px;white-space:nowrap;max-width:170px;overflow:hidden;text-overflow:ellipsis}
.kbt.t3 .nd small{display:block;color:var(--dkmut);font-size:10px;overflow:hidden;text-overflow:ellipsis}
.kbt.t3 .nd.dim{opacity:.35}.kbt.t3 .nd.hot{border-color:var(--g);box-shadow:0 0 0 3px color-mix(in srgb,var(--g) 25%,transparent),0 0 24px color-mix(in srgb,var(--g) 35%,transparent)}
.kbt.t3 .nd.miss{border-style:dashed;border-color:var(--wn);color:var(--wn)}.kbt.t3 .nd.bad{border-color:var(--bd);box-shadow:0 0 18px color-mix(in srgb,var(--bd) 35%,transparent)}
.kbt.t3 .nd.ok{border-color:var(--okc)}.kbt.t3 .nd.core{background:linear-gradient(135deg,#1c2a4a,#13213d);border-color:var(--acc);font-weight:600}
.kbt.t3 .ins{position:absolute;right:12px;top:50%;transform:translateY(-50%);width:min(260px,40%);background:rgba(18,26,42,.94);border:1px solid var(--dkline);border-radius:12px;padding:10px 12px;display:grid;gap:8px;font-size:12px}
.kbt.t3 .ins .t{color:var(--g);font-size:11px;letter-spacing:.06em}.kbt.t3 .ins .yes{background:var(--dkfg);color:var(--dk)}.kbt.t3 .ins .alt{border-color:var(--dkline);color:var(--dkfg)}
.kbt.t3 .ins .jd .why,.kbt.t3 .ins .mt{color:var(--dkmut)}
.kbt.t3 .empty{padding:60px 20px;text-align:center;color:var(--dkmut)}
/* 简报 */
.kbt.t4{display:grid;grid-template-columns:minmax(0,1fr) 240px;background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.kbt.t4 .art{padding:20px 24px;display:flex;flex-direction:column;gap:12px;min-width:0}
.kbt.t4 .art h2{margin:0;font-size:22px;line-height:1.35;text-wrap:balance}.kbt.t4 .art p{margin:0;line-height:1.8;max-width:62ch}
.kbt.t4 sup{font-family:"SF Mono",ui-monospace,Menlo,monospace;font-size:9.5px;color:var(--acc);background:var(--accb);border-radius:4px;padding:0 4px;margin-left:1px}
.kbt.t4 .jd{border:1px solid var(--line);border-radius:12px;padding:11px 12px;background:var(--bg)}
.kbt.t4 .rail{border-left:1px solid var(--line);padding:16px;display:grid;align-content:start;gap:14px}
.kbt.t4 .met{display:grid;gap:2px;color:var(--fg);text-decoration:none}.kbt.t4 .met .v{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums}.kbt.t4 .met svg{width:100%;height:30px;display:block}
.kbt.t4 .src{font-size:11.5px;color:var(--mut);display:grid;gap:3px}.kbt.t4 .src a{color:var(--mut)}
/* 静默 */
.kbt.t5{background:var(--dk);color:var(--dkfg);border-radius:14px;padding:16px 22px 18px;display:flex;flex-direction:column;gap:12px;min-height:460px}
.kbt.t5 .hd{display:flex;justify-content:space-between;color:var(--dkmut);font-size:12px}
.kbt.t5 .mid{flex:1;display:grid;grid-template-columns:230px minmax(0,1fr);align-items:center;gap:26px}
.kbt.t5 .orb{width:190px;height:190px;border-radius:50%;position:relative;display:grid;place-items:center;justify-self:center}
.kbt.t5 .orb::before{content:"";position:absolute;inset:0;border-radius:50%;background:conic-gradient(from var(--kbta,0deg),var(--o1),var(--o2),var(--o3),var(--o1));filter:blur(18px);opacity:.75;animation:kbtspin 9s linear infinite}
.kbt.t5 .orb::after{content:"";position:absolute;inset:14px;border-radius:50%;background:var(--dk)}
@property --kbta{syntax:"<angle>";inherits:false;initial-value:0deg}@keyframes kbtspin{to{--kbta:360deg}}
.kbt.t5 .orb .c{position:relative;z-index:1;text-align:center}.kbt.t5 .orb .c b{display:block;font-size:30px;font-variant-numeric:tabular-nums}.kbt.t5 .orb .c span{font-size:11px;color:var(--dkmut)}
.kbt.t5 .say{font-size:18px;line-height:1.5;text-wrap:balance}
.kbt.t5 .cap{border:1px solid var(--dkline);background:rgba(255,255,255,.03);border-radius:14px;padding:10px 12px}
.kbt.t5 .cap .yes{background:var(--dkfg);color:var(--dk)}.kbt.t5 .cap .alt{border-color:var(--dkline);color:var(--dkfg)}.kbt.t5 .cap .why,.kbt.t5 .mt{color:var(--dkmut)}
.kbt.t5 .cap select,.kbt.t5 .cap input{background:var(--dk);color:var(--dkfg);border-color:var(--dkline)}
.kbt.t5 .ft{display:flex;justify-content:center;gap:10px;flex-wrap:wrap}.kbt.t5 .ft a,.kbt.t5 .ft button{padding:4px 12px;border-radius:999px;border:1px solid var(--dkline);color:var(--dkmut);background:transparent;font:inherit;font-size:12px;cursor:pointer;text-decoration:none}
@media (max-width:760px){.kbt.t4{grid-template-columns:1fr}.kbt.t4 .rail{border-left:0;border-top:1px solid var(--line)}.kbt.t5 .mid{grid-template-columns:1fr}.kbt.t5 .orb{width:130px;height:130px}.kbt.t3 .ins{position:static;transform:none;width:auto;margin:10px}.kbt.t3 .cv{height:380px}}`;

  function css() {
    if (document.getElementById('kbt-css')) return;
    const s = document.createElement('style'); s.id = 'kbt-css'; s.textContent = CSS; document.head.prepend(s);   // 放最前面：模板 skin.css 同权重时能盖过它
  }
  const conf = p => p == null ? '' : `<span class="cf">把握<span class="m"><i style="width:${p}%"></i></span>${p}%</span>`;

  // 判断：所有模板共用的一块（按钮全部交给 o.act）
  function judg(j, opt = {}) {
    const p = j['提议'];
    let main = '';
    if (j['主动作'] === 'confirm' && p) {
      const rs = p['仓库'] || [];
      main = `<div class="fields"><span class="mt">工程</span>${rs.length ? `<select data-f="repo">${rs.map(r => `<option value="${esc(r['路径'])}" data-br="${esc(r['分支'] || '')}" ${r['路径'] === p['默认仓库'] ? 'selected' : ''}>${esc(r['名称'])} · ${esc(home(r['路径']))}</option>`).join('')}<option value="__pick">📁 选择本地路径…</option></select>`
        : `<input data-f="repo" placeholder="工程目录" value="${esc(p['默认仓库'] || '')}">`}
        ${p['类型'] === 'Bug分析' ? '' : `<span class="mt">分支</span><input data-f="branch" value="${esc(p['默认分支'] || '')}" placeholder="不填 = 工程现在的分支">`}</div>
        <div class="acts"><button class="yes" data-jact="confirm">${p['类型'] === 'Bug分析' ? '▶ 分析' : '▶ 推动'}${(p['条目'] || []).length > 1 ? `（${p['条目'].length} 条）` : ''}</button>${alts(j)}</div>`;
    } else if (j['主动作'] === 'choose') {
      main = `<div class="acts"><select data-f="value">${(j['选项'] || []).map(x => `<option value="${esc(x['值'])}">${esc(x['标签'])}</option>`).join('')}</select><button class="yes" data-jact="choose">就用这个</button>${alts(j)}</div>`;
    } else if (j['主动作'] === 'do') {
      main = `<div class="acts"><button class="yes" data-jact="do">${esc(j['建议'])}</button>${j['链接'] ? `<a class="alt" href="${esc(j['链接'])}">看看</a>` : ''}${alts(j)}</div>`;
    } else {
      main = `<div class="acts"><a class="yes" href="${esc(j['链接'] || '#/')}">${esc(j['建议'] || '去看看')}</a>${alts(j)}</div>`;
    }
    return `<div class="jd" data-j="${esc(j.id)}"><div class="h"><b>${esc(j['问题'])}</b>${conf(j['把握'])}</div>
      ${j['主动作'] === 'confirm' || j['主动作'] === 'choose' ? `<div>建议：<b>${esc(j['建议'])}</b></div>` : j['说明'] ? `<div>${esc(j['说明'])}</div>` : ''}
      ${j['理由'] && !opt.short ? `<div class="why">${esc(j['理由'])}</div>` : ''}${main}</div>`;
  }
  const alts = j => (j['备选'] || []).map(a => `<button class="alt" data-jact="${esc(a['动作'])}">${esc(a['标签'])}</button>`).join('');
  const other = b => (b['其他'] || []).length ? `<div class="other">${b['其他'].map(x => `<a href="${esc(x['链接'] || '#/')}"><b>${esc(x['标题'])}</b> <span class="mt sm">${esc(x['说明'] || '')}</span></a>`).join('')}</div>` : '';
  const strip = b => (b['进行中'] || []).length ? `<div class="strip">${b['进行中'].map(p => `<a class="ch ${p['谁'] === '你' ? 'w' : p['谁'] === 'AI' ? 'g' : ''}" href="${esc(p['链接'])}" title="${esc(p['下一步'])}">${esc(p['名称'])} · ${esc(p['阶段'] || '完成')}</a>`).join('')}</div>` : '';
  const spark = v => { if (!v || !v.length) return ''; const mx = Math.max(...v, 1), pts = v.map((y, i) => `${i / Math.max(1, v.length - 1) * 100},${28 - y / mx * 24}`).join(' ');
    return `<svg viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="var(--g)" stroke-width="2" vector-effect="non-scaling-stroke"/><circle cx="100" cy="${28 - v[v.length - 1] / mx * 24}" r="2.5" fill="var(--g)"/></svg>` };
  const ROLES = ['方案', '服务端', 'Android', 'iOS', '审查', 'Bug 分析'];
  const RC = { '方案': '#8b5cf6', '服务端': '#0ea5e9', 'Android': '#16a34a', 'iOS': '#64748b', '审查': '#f59e0b', 'Bug 分析': '#ef4444' };

  const T = {
    '指挥台': { 说明: '一句问候和一个会理解你的输入框，需要你判断的事附 AI 建议',
      html(b, o) {
        const [j, ...rest] = b['判断'] || [];
        const amb = (b['活动'] || []).slice(0, 3).map(a => [a['角色'], `${a['对象']} · ${a['状态']}`, a['链接']]);
        while (amb.length < 3 && (b['指标'] || [])[amb.length]) { const m = b['指标'][amb.length]; amb.push([m['名称'], `${m['值']} ${m['单位'] || ''} · ${m['说明'] || ''}`, m['链接'] || '']); }
        return `<div class="kbt t1"><span class="ch g">${(b['状态'] || {})['在工作'] ? `<span class="live"></span>${b['状态']['在工作']} 个 AI 在工作` : '今天替你做了 ' + ((b['状态'] || {})['今天完成'] || 0) + ' 件'}</span>
          <div class="greet">${esc(b['问候'])}</div>
          <div class="box"><textarea data-ask rows="2" placeholder="交给我任何东西：需求、日志、Bug、账号……或者问我"></textarea>
            <div class="bar"><span>回车交给管家 · Shift+回车换行</span><button class="yes" data-askgo>交给管家</button></div>
            <div class="parse" data-parse>${j ? judg(j, { short: true }) : '<span class="mt">现在没有需要你判断的事。</span>'}</div></div>
          ${amb.length ? `<div class="amb">${amb.map(([h, t, l]) => `<${l ? 'a href="' + esc(l) + '"' : 'div'}><b class="sm">${esc(h)}</b><span class="mt sm">${esc(t)}</span></${l ? 'a' : 'div'}>`).join('')}</div>` : ''}
          ${rest.length ? `<div class="more">${rest.slice(0, 4).map(x => judg(x, { short: true })).join('')}</div>` : ''}${strip(b)}${other(b)}</div>`;
      } },
    '团队': { 说明: '看着 AI 团队工作：每个 AI 一张卡，实时显示在做什么',
      html(b) {
        const acts = b['活动'] || [], used = new Set(acts.map(a => a['角色']));
        const card = a => `<a class="ag ${a['等你'] ? 'ask' : ''}" href="${esc(a['链接'] || '#/')}"><div class="h"><span class="av" style="background:${esc(a['颜色'])}">${esc(a['角色'][0])}</span><span class="nm">${esc(a['角色'])}</span>${a['等你'] ? '' : '<span class="live"></span>'}<span class="ch ${a['等你'] ? 'w' : ''}">${esc(a['状态'])}</span></div>
          <div class="mt sm">${esc(a['对象'])}</div>${(a['步骤'] || []).length ? `<div class="feed">${a['步骤'].map((s, i) => `<div class="s ${i === a['步骤'].length - 1 && !a['等你'] ? 'now caret' : ''}">${esc(s)}</div>`).join('')}</div>` : ''}</a>`;
        const idle = ROLES.filter(r => !used.has(r)).map(r => `<div class="ag idle"><div class="h"><span class="av" style="background:${RC[r]}">${r[0]}</span><span class="nm">${r}</span><span class="mt sm">空闲</span></div></div>`);
        const asks = (b['判断'] || []).slice(0, 3);
        return `<div class="kbt t2"><div class="hd"><b>AI 团队</b><span class="ch g">${acts.filter(a => !a['等你']).length ? '<span class="live"></span>' : ''}${acts.filter(a => !a['等你']).length} 个在工作</span><span class="ch">今天替你完成 ${(b['状态'] || {})['今天完成'] || 0} 件</span></div>
          <div class="grid">${acts.map(card).join('')}${idle.join('')}</div>
          ${asks.length ? `<div class="asks">${asks.map(x => judg(x)).join('')}</div>` : ''}
          <div class="foot"><span class="live"></span>审查和开发用不同的 AI · 改动只在开发分支 · 推送和提交要你确认</div>${strip(b)}${other(b)}</div>`;
      } },
    '画布': { 说明: '当前这一期的关系图：需求、设计、接口、各端、问题怎么连着',
      html(b) {
        const g = b['关系'];
        if (!g) return `<div class="kbt t3"><div class="hd"><b>关系图</b></div><div class="empty">还没有进行中的期。把需求交给管家，这里会画出它和各端代码的关系。</div>${other(b)}</div>`;
        const ns = g['节点'].map(n => ({ ...n })), pos = {}, ends = ns.filter(n => n['类'] === '端'), bugs = ns.filter(n => n['类'] === '问题');
        const fixed = { '需求': [50, 13], '设计': [16, 32], '接口': [84, 32], '契约': [50, 45], '证据': [50, 63] };
        ns.forEach(n => { if (fixed[n['类']]) pos[n.id] = fixed[n['类']] });
        ends.forEach((n, i) => pos[n.id] = [ends.length === 1 ? 50 : 14 + i * 72 / Math.max(1, ends.length - 1), 78]);
        bugs.forEach((n, i) => pos[n.id] = [20 + i * 30, 93]);
        Object.values(pos).forEach(p => p[0] = p[0] * 0.6 + 4);
        const hot = id => ['hot', 'bad', 'core'].includes((ns.find(n => n.id === id) || {})['状态']);
        const j = (b['判断'] || [])[0];
        return `<div class="kbt t3"><div class="hd"><a href="${esc(g['链接'])}">${esc(g['标题'])}</a><span class="ch">关系图</span><span style="flex:1"></span>${(g['步骤'] || []).map(s => `<span class="ch" style="${s['状态'] === 'cur' ? 'color:var(--g)' : ''}">${s['状态'] === 'done' ? '✓ ' : ''}${esc(s['名称'])}</span>`).join('')}</div>
          <div class="cv"><svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">${g['边'].filter(([a, c]) => pos[a] && pos[c]).map(([a, c]) => `<line x1="${pos[a][0]}" y1="${pos[a][1]}" x2="${pos[c][0]}" y2="${pos[c][1]}" stroke="${hot(a) && hot(c) ? 'var(--g)' : 'var(--dkline)'}" style="stroke-width:1.5px" vector-effect="non-scaling-stroke" ${[a, c].some(x => (ns.find(n => n.id === x) || {})['状态'] === 'miss') ? 'stroke-dasharray="4 4"' : ''}/>`).join('')}</svg>
          ${ns.filter(n => pos[n.id]).map(n => `<div class="nd ${esc(n['状态'])}" style="left:${pos[n.id][0]}%;top:${pos[n.id][1]}%">${esc(n['名称'])}${n['说明'] ? `<small>${esc(n['说明'])}</small>` : ''}</div>`).join('')}
          <div class="ins"><span class="t">AI 洞察</span><b>${esc(g['洞察']['标题'] || '在推进')}</b>${g['洞察']['内容'] ? `<span class="mt">${esc(g['洞察']['内容'])}</span>` : ''}${j ? judg(j, { short: true }) : ''}</div></div>${other(b)}</div>`;
      } },
    '简报': { 说明: 'AI 写给你的报告：进展、风险、需要你的判断，每句可追溯',
      html(b) {
        const n = b['叙述'] || {}, cites = n['引用'] || [];
        const body = esc(n['正文'] || '').replace(/\[(\d+)\]/g, (_, i) => { const c = cites[i - 1]; return c && c['链接'] ? `<a href="${esc(c['链接'])}"><sup>${i}</sup></a>` : `<sup>${i}</sup>` });
        return `<div class="kbt t4"><div class="art"><div class="strip"><span class="ch t">由 AI 撰写 · ${esc((b['时间'] || '').slice(11))}</span><span class="ch ${(b['状态'] || {})['名称'] === '等你判断' ? 'w' : 'g'}">${esc((b['状态'] || {})['名称'])}</span></div>
          <h2>${esc(n['标题'])}</h2><p>${body}</p>${(b['判断'] || []).slice(0, 3).map(x => judg(x)).join('')}${strip(b)}${other(b)}</div>
          <div class="rail">${(b['指标'] || []).map(m => `<${m['链接'] ? 'a href="' + esc(m['链接']) + '"' : 'div'} class="met"><span class="mt sm">${esc(m['名称'])}</span><span class="v">${esc(m['值'])}<span class="mt sm"> ${esc(m['单位'] || '')}</span></span>${spark(m['趋势'])}${m['说明'] ? `<span class="mt sm">${esc(m['说明'])}</span>` : ''}</${m['链接'] ? 'a' : 'div'}>`).join('')}
          ${cites.length ? `<div class="src"><b style="color:var(--fg)">引用</b>${cites.map((c, i) => `<span><sup>${i + 1}</sup> ${c['链接'] ? `<a href="${esc(c['链接'])}">${esc(c['文字'])}</a>` : esc(c['文字'])}</span>`).join('')}</div>` : ''}</div></div>`;
      } },
    '静默': { 说明: '没事时很安静：一个光环表示状态，只有要你判断时才出现',
      html(b) {
        const s = b['状态'] || {}, O = { '等你判断': ['#a78bfa', '#6f9bff', '#c084fc'], '工作中': ['#6f9bff', '#2dd4bf', '#a78bfa'], '发现问题': ['#fb923c', '#f87171', '#fbbf24'], '安静': ['#2dd4bf', '#38bdf8', '#4ade80'] }[s['名称']] || ['#2dd4bf', '#38bdf8', '#4ade80'];
        const js = (b['判断'] || []).slice(0, 2);
        return `<div class="kbt t5"><div class="hd"><span>知识库</span><span>今天替你完成 ${s['今天完成'] || 0} 件</span></div>
          <div class="mid"><div class="orb" style="--o1:${O[0]};--o2:${O[1]};--o3:${O[2]}"><div class="c"><b>${s['等你'] || s['在工作'] || 0}</b><span>${s['等你'] ? '件事等你判断' : s['在工作'] ? '个 AI 在工作' : esc(s['名称'])}</span></div></div>
            <div style="display:grid;gap:10px;min-width:0"><div class="say">${esc(b['问候'])}</div>${js.map(x => `<div class="cap">${judg(x)}</div>`).join('')}</div></div>
          <div class="ft"><button data-askopen>交给我</button><a href="#/classic">全部期</a><a href="#/bugs">问题</a><a href="#/settings">设置</a></div>${other(b)}</div>`;
      } }
  };

  function bind(root, b, o) {
    css(); o = o || {};
    root.querySelectorAll('[data-j]').forEach(box => {
      const sel = box.querySelector('select[data-f="repo"]'), br = box.querySelector('[data-f="branch"]');
      if (sel && br) sel.onchange = () => { br.value = sel.selectedOptions[0].dataset.br || '' };
      box.querySelectorAll('[data-jact]').forEach(btn => btn.onclick = async e => {
        e.preventDefault(); if (o.demo || !o.act) return;
        const v = k => (box.querySelector(`[data-f="${k}"]`) || {}).value || '';
        btn.disabled = true;
        try { await o.act(box.dataset.j, btn.dataset.jact, { value: v('value'), repo: v('repo').trim(), branch: v('branch').trim() }) } finally { btn.disabled = false }
      });
    });
    const ta = root.querySelector('[data-ask]');
    if (ta) {
      const go = () => { const t = ta.value.trim(); if (t && o.ask && !o.demo) { o.ask(t); ta.value = '' } };
      ta.onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); go() } };
      const gb = root.querySelector('[data-askgo]'); if (gb) gb.onclick = go;
      let h; ta.oninput = () => { clearTimeout(h); h = setTimeout(async () => {      // 理解预览：回车之前先说它看懂了什么
        const box = root.querySelector('[data-parse]'); if (!box || !o.preview) return;
        const t = ta.value.trim(); if (!t) { box.innerHTML = (b['判断'] || [])[0] ? judg(b['判断'][0], { short: true }) : '<span class="mt">现在没有需要你判断的事。</span>'; bind(box, b, o); return }
        try { const r = await o.preview(t); box.innerHTML = `<div class="jd"><div class="h"><b>我的理解</b>${conf(r['把握'])}</div><div class="strip">${(r['标签'] || []).map(([x, c]) => `<span class="ch ${esc(c)}">${esc(x)}</span>`).join('')}</div><div class="mt sm">回车后：${esc(r['计划'] || '')}</div></div>` } catch (_) {}
      }, 350) };
    }
    root.querySelectorAll('[data-askopen]').forEach(x => x.onclick = () => o.openAsk && o.openAsk());
  }

  window.KBUI = {
    list: Object.keys(T).map(k => ({ 名称: k, 说明: T[k]['说明'] })),
    has: n => !!T[n],
    render(n, b, o) { css(); return (T[n] || T['指挥台']).html(b, o || {}) },
    bind, judg: (j, opt) => { css(); return judg(j, opt) }, css
  };
})();
