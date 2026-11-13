// ==== 经典侧栏、导航刷新、退出登录
// 左侧导航：期列表（状态色点 + 待确认 / 问题数）、手机空闲数、当前页高亮
// 侧边栏按分类折叠：每个分类标题点一下收起 / 展开，记在本机浏览器；收起的分类里有待确认 / 问题时标题后亮个点
let navFold={};try{navFold=JSON.parse(localStorage.getItem('kb.navFold')||'{}')}catch(_){}
function navGroups(){
  const side=document.querySelector('.side');if(!side)return;   // 只有经典版的侧栏要分组折叠
  side.querySelectorAll(':scope>.navh').forEach(h=>{
    const b=document.createElement('div');b.className='navb';
    let n=h.nextElementSibling;while(n&&!n.classList.contains('navh')&&!n.classList.contains('foot')){const nx=n.nextElementSibling;b.appendChild(n);n=nx}
    h.after(b);const k=h.textContent.trim();h.dataset.g=k;h.insertAdjacentHTML('beforeend','<i class="hd"></i>');h.title='点击收起 / 展开';
    h.classList.toggle('fold',!!navFold[k]);
    h.onclick=()=>{navFold[k]=!navFold[k];if(!navFold[k])delete navFold[k];h.classList.toggle('fold',!!navFold[k]);try{localStorage.setItem('kb.navFold',JSON.stringify(navFold))}catch(_){}};
  });
}
function navAlerts(){document.querySelectorAll('.side .navh').forEach(h=>{const b=h.nextElementSibling;h.classList.toggle('alert',!!(b&&b.querySelector('.n.w:not(:empty),.n.q:not(:empty)')))})}
// 导航刷新：先更新 core 要用的数据（期名单、事项名单、工具入口），再画导航——模板设了 KB.hooks.nav 就交给模板，否则画经典侧栏
// d：/api/overview 的结果（只更新高亮时为空）；site：/api/site 的结果（模板接管时才有）
function sideNav(d,site){
  if(d){periodNames=d.periods.filter(p=>p.kind!=='事项').map(p=>p.name);taskNames=d.periods.filter(p=>p.kind==='事项').map(p=>p.name);entries=d.entries||[];ovPeriods=d.periods;authOn=!!d.auth}
  if(KB.hooks.nav){if(d&&!site){navRefresh();return}   // 页面自己拿到了 overview：模板要的是整站数据，补拉一次 /api/site
    try{KB.hooks.nav(site?d:null,site||null)}catch(e){console.error(e)}return}
  classicNav(d);
}
function classicNav(d){
  if(!$('.side #navPs'))return;     // 页面上没有经典侧栏
  $('#hostName').textContent=location.hostname;
  if(d){const lo=$('#logout');lo.hidden=!d.auth;lo.onclick=logout;
    const navItem=p=>`<a class="nav" data-nav="/p/${esc(p.name)}" href="#/p/${enc(p.name)}" title="${esc(p.name)} · ${esc(p.status)}"><span class="d" style="background:${DOT[p.status]||'var(--s0)'}"></span><span class="t">${esc(p.name)}</span><span class="x" data-navx="${esc(p.name)}" title="从侧栏移除（在总览里可以加回）">✕</span>${p.pendingQ?`<span class="n q">${p.pendingQ}</span>`:''}${p.issues?`<span class="n w">${p.issues}</span>`:''}${p.openBugs?`<span class="n b" title="${p.openBugs} 个 Bug 没解决">🐞${p.openBugs}</span>`:''}</a>`;
    const pv=d.periods.filter(p=>p.kind!=='事项'&&!p.navHidden),ph=d.periods.filter(p=>p.kind!=='事项'&&p.navHidden).length;
    $('#navPs').innerHTML=pv.map(navItem).join('')+(ph?`<a class="nav" href="#/" title="在总览的期卡片上点「加到侧栏」"><span class="t mut small">已移出 ${ph} 期，在总览加回</span></a>`:'');
    const bt=d.periods.filter(p=>p.kind==='事项'&&!(p.plugins||[]).length&&(p.batch?p.batch['侧栏']:p.status!=='已完成'));
    const batchItem=p=>{const b=p.batch||{},nm=b['来源']==='anr'?batchName(p.name):p.name;
      return `<a class="nav" data-nav="/p/${esc(p.name)}" href="#/p/${enc(p.name)}" title="${esc(p.name)} · ${esc(p.status)}${b['总数']?` · 已处理 ${b['已处理']}/${b['总数']}${b['待确认']?`，待确认 ${b['待确认']}`:''}`:''}"><span class="d" style="background:${DOT[p.status]||'var(--s0)'}"></span><span class="t">${esc(nm)}</span><span class="x" data-navx="${esc(p.name)}" title="从侧栏移除（在 ANR / 崩溃、总览里能找回；有新问题会自动回来）">✕</span>${p.pendingQ?`<span class="n q">${p.pendingQ}</span>`:''}${b['总数']?`<span class="n${b['待确认']?' q':''}">${b['已处理']}/${b['总数']}</span>`:''}${p.openBugs?`<span class="n b" title="${p.openBugs} 个 Bug 没解决">🐞${p.openBugs}</span>`:''}</a>`};
    const src=k=>bt.filter(p=>((p.batch||{})['来源']||'')===k).map(batchItem).join('');
    $('#navAnrTs').innerHTML=src('anr');$('#navBugTs').innerHTML=src('bug');
    $('#navTs').innerHTML=src('');
    document.querySelectorAll('[data-navx]').forEach(x=>x.onclick=e=>{e.preventDefault();e.stopPropagation();taskNav(x.dataset.navx,false)});
    $('#navPh').textContent=d.phones?`${d.phones.free}/${d.phones.total}`:'';$('#navPh').parentElement.hidden=!d.phones;   // 本机没装 adb 就不显示「手机」
    const nb=$('#navBug');nb.textContent=d.zentao&&d.zentao.pending?d.zentao.pending:'';nb.title='待归纳（未关闭）';nb.classList.toggle('w',!!(d.zentao&&d.zentao.pending));
    $('#navEnt').innerHTML=entries.map(x=>{const ts=d.periods.filter(p=>(p.plugins||[]).includes(x.id)&&p.status!=='已完成'),q=ts.reduce((a,p)=>a+(p.pendingQ||0),0);
      return `<a class="nav" data-nav="/tool/${esc(x.id)}" href="#/tool/${enc(x.id)}" title="${esc(x['说明']||'')}${ts.length?' · 待解决 '+ts.length+' 条':''}"><span class="t">${esc(x['图标'])} ${esc(x['名称'])}</span>${q?`<span class="n q" title="${q} 个待你确认">${q}</span>`:ts.length?`<span class="n">${ts.length}</span>`:''}</a>`}).join('');
    const na=$('#navAnr'),at=d.anr?d.anr.todo:0;na.textContent=at||'';na.title='待处理：没关联事项，或事项完成后又出现';na.classList.toggle('w',!!at)}
  const h=decodeURIComponent(location.hash.slice(1)||'/');
  const pt=h.startsWith('/p/')&&ovPeriods.find(p=>p.name===h.slice(3)&&(p.plugins||[]).length),hh=pt?'/tool/'+pt.plugins[0]:h;
  document.querySelectorAll('.side .nav').forEach(a=>{const k=a.dataset.nav;a.classList.toggle('on',k==='/'?(hh==='/'||hh==='/classic'):k==='/d/'?hh.startsWith('/d/'):hh===k)});
  navAlerts();
}
const batchName=n=>n.replace(/^(ANR\s*\/\s*崩溃|ANR|崩溃)\s*/,'')||n;
// 「从侧栏移除 / 加回侧栏」只属于经典版的侧栏；用界面模板（模板自己画导航）时不显示这些链接
const sideOn=()=>!KB.hooks.nav;
async function taskNav(name,show){try{const r=await post('/api/task/nav',{period:name,show});toast(r.msg+(show?'':'；在总览里可以加回'));await navRefresh();render()}catch(e){toast(e.message)}}
async function navRefresh(){try{if(KB.hooks.nav){const s=await api('/api/site?full=1');KB.siteCache=s;sideNav(s.overview,s)}else sideNav(await api('/api/overview'))}catch(_){}}
let authOn=false;
async function logout(){await fetch('/api/logout',{method:'POST'});location.href='/login'}
