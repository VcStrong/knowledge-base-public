// ==== Bug 页：列表、分析、修复、平台接入
// ---- Bug：知识库只存索引（链接 + 简介），原文以 Bug 平台（禅道、Jira…）为准
const BUG_ST={激活:'st-开发中',已解决:'st-已批准开发',已关闭:'st-已完成'};
let bugF={owner:'待归纳',st:'未关闭',q:''};try{Object.assign(bugF,JSON.parse(localStorage.getItem('kb.bugF')||'{}'))}catch(_){}
let periodNames=[];
const kbPeriods=d=>periodNames.length?periodNames:(periodNames=[d.name]);
function ownerSel(b,ps){const o=b['归属']||{},cur=o['类型']==='期'||o['类型']==='事项'?o['名称']:o['类型'];
  const ts=taskNames.slice();if(o['类型']==='事项'&&!ts.includes(o['名称']))ts.push(o['名称']);
  const op=x=>`<option value="${esc(x)}" ${x===cur?'selected':''}>${esc(x==='未关联'?'未关联（别的功能）':x)}</option>`;
  return `<select data-bown="${esc(b['编号'])}" title="${esc((o['依据']||'')+(o['时间']?' · '+o['时间']:''))}" style="max-width:220px">${op('待归纳')}${o['类型']==='未关联'?op('未关联'):''}
    ${ps.length?`<optgroup label="期">${ps.map(op).join('')}</optgroup>`:''}${ts.length?`<optgroup label="事项">${ts.map(op).join('')}</optgroup>`:''}<option value="__task">＋ 新建事项…</option></select>
    <div class="mut small" style="margin-top:2px">${esc(o['依据']||'')}</div>`}
const BUG_ORD={激活:0,已解决:1,已关闭:2};
let bugSort='状态';try{bugSort=localStorage.getItem('kb.bugSort')||'状态'}catch(_){}
const BUG_SORTS={状态:(a,b)=>(BUG_ORD[a['状态']]??9)-(BUG_ORD[b['状态']]??9)||(+a['严重']||9)-(+b['严重']||9)||String(b['修改时间']).localeCompare(String(a['修改时间'])),
  严重:(a,b)=>(+a['严重']||9)-(+b['严重']||9)||(BUG_ORD[a['状态']]??9)-(BUG_ORD[b['状态']]??9),
  最近修改:(a,b)=>String(b['修改时间']).localeCompare(String(a['修改时间'])),
  分析:(a,b)=>anRank(a)-anRank(b)||(BUG_ORD[a['状态']]??9)-(BUG_ORD[b['状态']]??9)};
// 知识库里标了「已修复」的，不管按什么排都沉到下面（组内按所选方式排）
const bugDone=b=>b['修复']&&b['修复']['状态']==='已修复'?1:0;
Object.keys(BUG_SORTS).forEach(k=>{const f=BUG_SORTS[k];BUG_SORTS[k]=(a,b)=>bugDone(a)-bugDone(b)||f(a,b)});
const AN_ST={待审核:'st-已批准开发',已通过:'st-已完成',需重分析:'st-已暂停2',无需审核:'st-已完成'};
function anRank(b){const a=b['分析'],f=b['修复'];return f?(f['状态']==='已修复'?6:1):b['分析中']?2:!a?4:a['过时']?3:a['状态']==='需重分析'||a['状态']==='待审核'?0:a['状态']==='已通过'?1:5}
function anCell(b){const a=b['分析'],done=(b['修复']||{})['状态']==='已修复';
  if(b['忽略'])return `<span class="badge" title="${esc((b['忽略']['时间']||'')+' '+(b['忽略']['说明']||''))}">已忽略</span> <a class="small" data-bign="${esc(b['编号'])}" data-on="">取消忽略</a>`;
  const ign=b['状态']==='激活'&&!b['修复']?` <a class="small mut" data-bign="${esc(b['编号'])}" data-on="1" title="陈旧、不打算处理：只在知识库标记，不改 Bug 平台；不再算没解决，管家也不分析">忽略</a>`:'';
  if(b['分析中'])return '<span class="badge st-开发中">● 分析中</span>';
  const btn=`<button class="small" data-ban="${esc(b['编号'])}" title="后台只读分析：实时拉取 Bug，对照本期分支改动和代码，给出代码位置和修复思路">${a?'重新分析':'🔍 分析'}</button>`;
  if(!a)return b['状态']==='已关闭'?'':btn+ign;
  return `<a data-bav="${esc(b['编号'])}" title="${esc(a['摘要']||'')}"><span class="badge ${AN_ST[a['状态']]||''}">${esc(a['状态'])}</span>${a['过时']&&!done&&a['状态']!=='无需审核'?' <span class="badge st-已暂停2" title="分析之后平台上又改过">可能过时</span>':''} <span class="small mut">置信度${esc(a['置信度']||'?')}</span>
    <div class="small" style="margin-top:2px;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(a['摘要']||'')}</div></a>${(a['过时']||a['状态']==='需重分析')&&!done&&a['状态']!=='无需审核'?'<div style="margin-top:3px">'+btn+'</div>':''}`}
function fixCell(b){const f=b['修复'],a=b['分析'];
  if(f&&f['状态']==='修复中')return '<div style="margin-top:4px"><span class="badge st-开发中">🔧 修复中</span></div>';
  if(f&&f['状态']==='排队中')return `<div style="margin-top:4px"><span class="badge ${f['阻塞']?'st-已暂停2':'st-已批准开发'}" title="${esc(f['等待']||'')}">${f['阻塞']?'⛔ 排队受阻':'⏳ 排队中'}</span></div>`;
  if(f)return `<div style="margin-top:4px"><a data-bfx="${esc(b['编号'])}" title="${esc(f['说明']||'')}"><span class="badge ${f['状态']==='已修复'?'st-已完成':'st-已暂停2'}">${f['状态']==='已修复'?'✅ 已修复':'⚠ 未修成'}</span>${(f['提交']||[]).length?` <span class="mono small">${esc(f['提交'][0]['提交'].slice(0,8))}</span>`:''}</a>${(f['待提交']||[]).length?` <button class="small pri" data-bsvn="${esc(b['编号'])}" title="修复改的 ${f['待提交'].length} 个文件还在 svn 工作副本里：点了才提交到 svn 服务器">⬆ 提交到 svn</button>`:''}</div>`;
  return a&&a['状态']==='已通过'&&!a['过时']&&b['状态']!=='已关闭'?`<div style="margin-top:4px"><button class="small" data-bfix="${esc(b['编号'])}" title="加入修复队列：后台按审核通过的思路改代码、每个 Bug 单独提交，修好后在知识库标记（不改 Bug 平台）">🔧 修复</button></div>`:''}
// 修复进度 / 排队 / 异常：放在 Bug 列表最上面；ids 给了就只看这些 Bug（期页面）
function fixPanel(q,ids){
  if(!q)return '';const keep=x=>!ids||ids.has(x['编号']);
  const run=q['修复中'].filter(keep),wait=q['排队中'].filter(keep),block=q['阻塞'].filter(keep),fail=q['未完成'].filter(keep),warn=(q['警告']||[]).filter(w=>!ids||w.Bug.some(b=>ids.has(b)));
  if(!run.length&&!wait.length&&!block.length&&!fail.length&&!warn.length)return '';
  const t=x=>`<a href="${esc(x['链接'])}" target="_blank" rel="noopener" class="mono">${esc(x['编号'])}</a> ${esc(x['标题'].length>40?x['标题'].slice(0,40)+'…':x['标题'])}`;
  const mins=s=>{const d=(Date.now()-new Date(s.replace(' ','T')))/60000;return d>=0&&d<1e5?Math.round(d):''};
  const rows=[];
  if(run.length){const ss={};run.forEach(x=>(ss[x['会话']]=ss[x['会话']]||[]).push(x));
    Object.values(ss).forEach(g=>rows.push(`<div style="margin:4px 0"><span class="badge st-开发中">🔧 修复中</span> ${g.map(t).join('；')}
      <span class="small mut">· ${esc(g[0]['开始时间'])} 开始，已 ${mins(g[0]['开始时间'])} 分钟 · <span class="mono">${esc((g[0]['仓库']||'').replace(/^\/Users\/[^/]+/,'~'))}</span> ${esc(g[0]['分支']||'')}</span>
      ${(g[0]['动作']||[]).length?`<div class="small mut mono" style="margin:2px 0 0 18px;white-space:pre-wrap">${g[0]['动作'].map(a=>'› '+esc(a)).join('\n')}</div>`:''}</div>`))}
  const byWhy={};block.forEach(x=>(byWhy[x['原因']]=byWhy[x['原因']]||[]).push(x));       // 同一个原因合成一条
  Object.entries(byWhy).forEach(([why,g])=>rows.push(`<div style="margin:4px 0"><span class="badge st-已暂停2">⛔ 需要你处理</span> ${g.map(x=>`${t(x)} <a class="small" data-bunq="${esc(x['编号'])}" title="移出修复队列">移出</a>`).join('；')}<div class="small" style="color:var(--s4);margin-left:18px">${esc(why)}</div></div>`));
  if(wait.length)rows.push(`<div style="margin:4px 0"><span class="badge st-已批准开发">⏳ 排队 ${wait.length}</span> ${wait.map(x=>`${t(x)} <a class="small" data-bunq="${esc(x['编号'])}">移出</a>`).join('；')}${wait[0]['原因']?`<div class="small mut" style="margin-left:18px">${esc(wait[0]['原因'])}，结束后按顺序接着修</div>`:''}</div>`);
  const failRow=x=>`<div style="margin:4px 0"><span class="badge st-已暂停2">⚠ 没修成</span> ${t(x)} <span class="small mut">${esc(x['时间']||'')}</span>
    <div class="small" style="margin-left:18px;white-space:pre-wrap;max-height:4.5em;overflow:hidden" title="${esc(x['原因']||'')}">${esc(x['原因']||'')}</div>
    <div style="margin-left:18px" class="row small"><a data-bav="${esc(x['编号'])}" title="打开分析：先看上次为什么没修成，改审核意见后再点「修复」">重新修复…</a><a data-bfx="${esc(x['编号'])}">详情 / 撤销标记</a></div></div>`;
  fail.slice(0,3).forEach(x=>rows.push(failRow(x)));
  if(fail.length>3)rows.push(`<details><summary class="small mut">还有 ${fail.length-3} 条没修成</summary>${fail.slice(3).map(failRow).join('')}</details>`);
  warn.forEach(w=>rows.push(`<div style="margin:4px 0"><span class="badge st-已暂停2">⚠ 会话警告</span> Bug ${esc(w.Bug.join('、'))}：${esc(w['警告'])}</div>`));
  return `<div class="card2" style="margin-bottom:10px;border-color:${block.length||fail.length?'var(--s4)':'var(--line)'}"><div class="bd"><b class="small">修复进度</b>${rows.join('')}</div></div>`}
function fixDlg(b){const f=b['修复'];
  openDlg(`Bug ${b['编号']} 修复（知识库标记）`,`<div class="form"><p><b>${esc(b['标题'])}</b></p>
    <p><span class="badge ${f['状态']==='已修复'?'st-已完成':'st-已暂停2'}">${esc(f['状态'])}</span> <span class="small mut">${esc(f['时间']||'')} · ${esc(f['标记']||'')}</span></p>
    ${(f['提交']||[]).map(c=>`<div class="mono small">${esc(c['提交'])} ${esc(c['说明'])}</div>`).join('')}
    ${f['说明']?`<div style="white-space:pre-wrap">${esc(f['说明'])}</div>`:''}
    ${(f['待提交']||[]).length?`<p class="small"><b>还没提交到 svn 的文件</b>：<span class="mono">${f['待提交'].map(esc).join('、')}</span></p>`:''}
    <p class="mut small">只记在知识库里，不改 Bug 平台；平台上的状态由测试 / 你自己去改。</p>
    <div class="row">${(f['待提交']||[]).length?`<button class="pri" data-bsvn="${esc(b['编号'])}">⬆ 提交到 svn</button>`:''}${f['状态']!=='已修复'&&b['分析']&&b['分析']['状态']==='已通过'?'<button class="pri" id="fxAgain">🔧 重新修复…</button>':''}<button id="fxUndo">撤销标记</button></div></div>`);
  if($('#fxAgain'))$('#fxAgain').onclick=()=>{dlg.close();analysisDlg(b['编号']).catch(e=>toast(e.message))};   // 先改审核意见再修
  bindSvnCommit(dlg);
  $('#fxUndo').onclick=async()=>{try{const r=await post('/api/zentao/unfix',{id:b['编号']});toast(r.msg);dlg.close();render()}catch(e){toast(e.message)}}}
function bindSvnCommit(root){root.querySelectorAll('[data-bsvn]').forEach(b=>b.onclick=async e=>{e.preventDefault();e.stopPropagation();
  if(!confirm(`把 Bug ${b.dataset.bsvn} 修复改的文件提交到 svn 服务器？（改了同一批文件的其他 Bug 会一起提交）`))return;
  b.disabled=true;try{toast((await post('/api/zentao/svncommit',{id:b.dataset.bsvn})).msg);if(dlg.open)dlg.close();render()}catch(err){toast(err.message);b.disabled=false}})}
async function fixBugs(ids){     // 点「修复」就是批准：直接进修复队列，进度和异常显示在列表顶部
  try{const r=await post('/api/zentao/fix',{ids});toast(r.msg.split('\n')[0]);if(dlg.open)dlg.close();render()}catch(e){toast(e.message)}}
let bugIndex={};
// Bug 列表默认只显示 编号、标题、状态、分析 / 修复；其他信息勾选后显示（记在本机浏览器）
const BUG_COLS=[['简介','简介'],['详情','产品 / 执行·Sprint / 指派 / Jenkins'],['严重','严重 / 平台 / 线上'],['归属','归属（可改）']];
let bugCols=[];try{bugCols=JSON.parse(localStorage.getItem('kb.bugCols')||'[]')}catch(_){}
let bugShowIgn=false;
function bugTable(bugs,ps,st){
  bugs.forEach(b=>bugIndex[b['编号']]=b);
  const nIgn=bugs.filter(b=>b['忽略']&&(st==='全部'||b['状态']!=='已关闭')).length;
  const list=bugs.filter(b=>(st==='全部'||b['状态']!=='已关闭')&&(bugShowIgn||!b['忽略'])).sort(BUG_SORTS[bugSort]||BUG_SORTS['状态']);
  const old30=new Date(Date.now()-30*864e5).toISOString().slice(0,10);
  const stale=list.filter(b=>!b['忽略']&&b['状态']==='激活'&&!b['分析']&&!b['修复']&&!b['分析中']&&(b['修改时间']||'9')<old30).map(b=>b['编号']);
  const ignBar=nIgn?`<p class="small mut"><a data-bshowign>${bugShowIgn?'收起':'显示'}已忽略的 ${nIgn} 个 Bug</a></p>`:'';
  if(!list.length)return `<p class="mut">${bugs.length?'没有未关闭的 Bug。':'还没有 Bug。'}</p>`+ignBar;
  const todo=list.filter(b=>!b['分析']&&!b['分析中']&&!b['忽略']&&b['状态']==='激活').map(b=>b['编号']);   // 只批量分析激活的
  const fixable=list.filter(b=>b['分析']&&b['分析']['状态']==='已通过'&&!b['分析']['过时']&&!b['修复']&&b['状态']!=='已关闭').map(b=>b['编号']);
  const th=(k,t,w)=>`<th${w?` style="width:${w}px"`:''}><a data-bsort="${k}" title="按${k}排序">${t}${bugSort===k?' ▾':''}</a></th>`;
  const on=k=>bugCols.includes(k),multi=new Set(bugs.map(b=>b['来源'])).size>1;
  return `<div class="row small mut" style="margin-bottom:6px;gap:10px;flex-wrap:wrap">排序 ${Object.keys(BUG_SORTS).map(k=>`<a data-bsort="${k}" ${bugSort===k?'style="font-weight:600;color:var(--fg)"':''}>${k}</a>`).join(' · ')}
    <span style="margin-left:12px">显示</span>${BUG_COLS.map(([k,t])=>`<label class="row" style="gap:3px;color:var(--fg)"><input type="checkbox" data-bcol="${k}" ${on(k)?'checked':''}>${t}</label>`).join('')}
    <span style="margin-left:auto"></span>${todo.length?`<button class="small" data-banall="${esc(todo.join(','))}">🔍 分析未分析的激活 Bug（${todo.length}）</button>`:''}
    ${fixable.length?`<button class="small" data-bfixall="${esc(fixable.join(','))}">🔧 修复审核通过的（${fixable.length}）</button>`:''}
    ${stale.length?`<button class="small" data-bignall="${esc(stale.join(','))}" title="平台上 30 天没动、也没分析过的激活 Bug：只在知识库标忽略，不改 Bug 平台">🙈 忽略 30 天没动的（${stale.length}）</button>`:''}</div>
  <div class="tw"><table><tr><th>Bug</th>${th('状态','状态',on('严重')?120:80)}${th('分析','分析 / 修复',240)}${on('归属')?'<th style="width:230px">归属</th>':''}</tr>${list.map(b=>`<tr>
    <td><a href="${esc(b['链接'])}" target="_blank" rel="noopener" class="mono small" title="在${esc(b['来源']||'平台')}打开原页">${esc(b['编号'])}</a>${multi?` <span class="badge" style="font-size:11px">${esc(b['来源']||'')}</span>`:''} <b>${esc(b['标题'])}</b>${on('简介')&&b['简介']?`<div class="small">${esc(b['简介'])}</div>`:''}
      ${on('详情')?`<div class="mut small">${esc(b['产品']||'')}${(b['分组']||[]).filter(g=>g['名']).map(g=>' · '+esc(g['类型']+' '+g['名'])).join('')}${b['指派给']?' · 指派 '+esc(b['指派给']):''} · 平台上修改 ${esc(b['修改时间']||'')}${b['Jenkins任务']?` · <span class="mono" title="Jenkins 任务">${esc(b['Jenkins任务'])}</span>`:''}</div>`:''}
      ${!on('归属')&&b['归属']&&b['归属']['类型']!=='待归纳'&&b['归属']['名称']&&!curPeriod()?`<div class="mut small">→ ${esc(b['归属']['名称'])}</div>`:''}</td>
    <td><span class="badge ${BUG_ST[b['状态']]||''}">${esc(b['状态'])}</span>${on('严重')?` <span class="small mut">严重${esc(b['严重'])}</span>${b['线上']?' <span class="badge st-已暂停2">线上</span>':''}${b['平台']?` <span class="small mut">${esc(b['平台'])}</span>`:''}`:''}</td>
    <td>${anCell(b)}${fixCell(b)}</td>
    ${on('归属')?`<td>${ownerSel(b,ps)}</td>`:''}</tr>`).join('')}</table></div>${ignBar}`}
async function analyze(ids,repo){
  try{const r=await post('/api/zentao/analyze',repo?{ids,repo}:{ids});toast(r.msg.split('\n')[0]);render()}
  catch(e){if(!e.need)return toast(e.message);const n=e.need;
    openDlg('选择分析用的代码仓库',`<div class="form"><p class="small">${esc(e.message)}</p>
      ${n['候选'].map((p,i)=>`<label class="row" style="color:var(--fg)"><input type="radio" name="anR" value="${esc(p)}" ${i?'':'checked'}> <span class="mono small">${esc(p)}</span></label>`).join('')}
      <label class="row" style="color:var(--fg)"><input type="radio" name="anR" value="*" ${n['候选'].length?'':'checked'}> 其他路径 <input type="text" id="anP" style="width:380px;max-width:100%" placeholder="/Users/…/代码仓库根目录"> <button type="button" id="anPick" title="浏览本机目录">📁 选择…</button></label>
      <p class="mut small">会记住「${esc(n['产品']||'这个产品')}」用这个仓库，下次不再问。</p>
      <div class="row"><button class="pri" id="anGo">开始分析</button></div></div>`);
    $('#anPick').onclick=async e=>{e.preventDefault();const p=await pickDir($('#anP').value.trim());if(p){$('#anP').value=p;document.querySelector('[name=anR][value="*"]').checked=true}};
    $('#anGo').onclick=()=>{const v=document.querySelector('[name=anR]:checked').value;const p=v==='*'?$('#anP').value.trim():v;if(!p)return toast('请选择或填写仓库路径');dlg.close();analyze(ids,p)}}}
// 标记已修复：一个居中小弹框，提交号和说明都可空（叠在分析弹框上，取消回到分析弹框）
function fixedDlg(id){
  const d=document.createElement('dialog');d.className='mini';
  d.innerHTML=`<div class="hd"><b>标记 Bug ${esc(id)} 已修复</b><button data-x>取消</button></div><div class="bd">
    <p class="small mut" style="margin:0 0 10px">你自己已经修好了：只在知识库标记，不改 Bug 平台。两项都可以不填。</p>
    <label class="small">提交号（多个用空格隔开）</label><input type="text" id="fdC" style="width:100%;margin:4px 0 10px" placeholder="如 abc1234 def5678">
    <label class="small">说明</label><textarea id="fdN" rows="3" style="width:100%;margin-top:4px" placeholder="改了什么、怎么验证的"></textarea>
    <div class="row" style="justify-content:flex-end;margin-top:12px;gap:8px"><button data-x>取消</button><button class="pri" id="fdOk">标记已修复</button></div></div>`;
  document.body.appendChild(d);d.addEventListener('close',()=>d.remove());
  d.querySelectorAll('[data-x]').forEach(b=>b.onclick=()=>d.close());
  const ok=d.querySelector('#fdOk');
  ok.onclick=async()=>{const c=d.querySelector('#fdC').value.trim(),n=d.querySelector('#fdN').value.trim();ok.disabled=true;
    try{const m=await post('/api/zentao/fixed',{id,done:true,commits:c?c.split(/\s+/):[],note:n});toast(m.msg);d.close();dlg.close();render()}
    catch(e){toast(e.message);ok.disabled=false}};
  d.showModal();d.querySelector('#fdC').focus();
}
async function analysisDlg(id){
  const r=await api('/api/zentao/analysis?id='+enc(id)),a=r.analysis,b=r.bug;
  const sec=(t,v)=>v?`<h3 style="margin:12px 0 4px">${t}</h3><div style="white-space:pre-wrap">${esc(v)}</div>`:'';
  const f=b['修复'], fixing=f&&['修复中','排队中'].includes(f['状态']);
  const noFix=b['状态']==='已关闭'?'平台上已关闭':a['过时']?'分析之后平台上又改过，先重新分析':fixing?(f['状态']==='排队中'?'已在修复队列':'正在修复'):'';
  openDlg(`Bug ${b['编号']} 分析`,`<div style="max-width:900px">
    <div style="position:sticky;top:-12px;z-index:2;background:var(--card);margin:-12px -14px 10px;padding:10px 14px;border-bottom:1px solid var(--line)">
      <div class="row" style="gap:8px;flex-wrap:wrap"><button class="pri" id="rvFix" ${noFix?`disabled title="${esc(noFix)}"`:'title="按这份分析的修复思路改代码：后台修复会话，每个 Bug 单独提交（不 push），只在知识库标记"'}>🔧 ${f&&!fixing?'重新修复':'修复'}</button>
        <button id="rvRe" title="打回，并带着意见立即重新分析">打回并重新分析</button>
        ${noFix?`<span class="small mut">${esc(noFix)}</span>`:''}
        <button id="rvFixed" style="margin-left:auto" title="你自己已经修好了：在知识库里标记（不改 Bug 平台）">标记已修复…</button></div>
      ${f&&f['状态']==='未完成'&&f['说明']?`<div class="small" style="margin-top:8px;padding:6px 8px;border:1px solid var(--s4);border-radius:6px;max-height:9em;overflow:auto;white-space:pre-wrap"><b style="color:var(--s4)">上次没修成</b>（${esc(f['时间']||'')}）：${esc(f['说明'])}</div>`:''}
      <textarea id="rvN" rows="2" style="width:100%;margin-top:8px" placeholder="审核意见：点「修复」时这里写的就是最新意见，修复会话按它改（会替换之前的意见）；打回时写哪里不对、希望往哪个方向查">${esc(a['意见']||'')}</textarea></div>
    <div class="row" style="flex-wrap:wrap;gap:6px"><span class="badge ${AN_ST[a['状态']]||''}">${esc(a['状态'])}</span><span class="small mut">置信度 ${esc(a['置信度']||'?')} · ${esc(a['时间'])} · ${esc(a['提交者']||'')} · 依据平台上修改 ${esc(a['修改时间']||a['禅道修改']||'')}</span>
      ${a['过时']?'<span class="badge st-已暂停2">⚠ 分析之后平台上又改过，可能过时</span>':''}<a href="${esc(b['链接'])}" target="_blank" rel="noopener" class="small" style="margin-left:auto">${esc(b['来源']||'平台')}原页 ↗</a></div>
    <p><b>${esc(b['标题'])}</b></p>
    <p style="font-size:15px">结论：<b>${esc(a['摘要'])}</b></p>
    <h3 style="margin:12px 0 4px">代码位置 <span class="small mut" style="font-weight:400">${esc(a['仓库']||'')}</span></h3>
    ${(a['代码位置']||[]).map(x=>`<div style="margin:6px 0"><span class="mono small"><b>${esc(x['路径'])}:${x['行']}</b></span>${x['分支']?` <span class="small mut">（分支 ${esc(x['分支'])}）</span>`:''} <span class="small ${x['核对'].startsWith('⚠')?'':'mut'}" style="${x['核对'].startsWith('⚠')?'color:var(--s4)':''}">${esc(x['核对'])}</span>
      <div class="small">${esc(x['说明'])}</div>${x['代码']?`<pre class="mono" style="font-size:12px;overflow:auto;max-height:240px;margin:4px 0">${esc(x['代码'])}</pre>`:''}</div>`).join('')||'<p class="mut">没有给出代码位置</p>'}
    ${sec('原因',a['原因'])}${sec('修复思路',a['思路'])}${sec('影响范围',a['影响'])}${sec('自测要点',a['自测'])}${sec('还缺的信息',a['缺少'])}${sec('审核意见',a['意见'])}${(a['意见历史']||[]).length?`<h3 style="margin:12px 0 4px">之前的审核意见 <span class="small mut" style="font-weight:400">已被替换，不再给修复会话</span></h3>${a['意见历史'].map(h=>`<div class="small mut" style="white-space:pre-wrap">· ${esc(h['时间']||'')} ${esc(h['意见']||'')}</div>`).join('')}`:''}</div>`);
  $('#rvFixed').onclick=()=>fixedDlg(id);
  // 点「修复」= 认可这份分析并开始修：先记为通过（带上意见），再起修复会话
  $('#rvFix').onclick=async()=>{const btn=$('#rvFix');btn.disabled=true;
    const note=$('#rvN').value.trim();
    try{if(a['状态']!=='已通过')await post('/api/zentao/review',{id,action:'通过',note});
      const r=await post('/api/zentao/fix',{ids:[id],note});toast(r.msg.split('\n')[0]);dlg.close();render()}
    catch(e){toast(e.message);btn.disabled=false;render()}};
  $('#rvRe').onclick=async()=>{const note=$('#rvN').value.trim();if(!note){toast('打回要写意见：哪里不对、希望往哪个方向查');$('#rvN').focus();return}
    try{const m=await post('/api/zentao/review',{id,action:'打回',note});toast(m.msg);dlg.close();analyze([id])}catch(e){toast(e.message)}};
}
async function ignoreBugs(ids,on){try{toast((await post('/api/zentao/ignore',{ids,on})).msg);render()}catch(e){toast(e.message)}}
function bindBugs(root){
  root.querySelectorAll('[data-bign]').forEach(a=>a.onclick=e=>{e.preventDefault();ignoreBugs([a.dataset.bign],!!a.dataset.on)});
  root.querySelectorAll('[data-bignall]').forEach(b=>b.onclick=()=>{const ids=b.dataset.bignall.split(',');if(confirm(`忽略这 ${ids.length} 个陈旧 Bug？只在知识库标记，不改 Bug 平台，随时能取消。`))ignoreBugs(ids,true)});
  root.querySelectorAll('[data-bshowign]').forEach(a=>a.onclick=()=>{bugShowIgn=!bugShowIgn;render()});
  root.querySelectorAll('[data-bsort]').forEach(a=>a.onclick=()=>{bugSort=a.dataset.bsort;try{localStorage.setItem('kb.bugSort',bugSort)}catch(_){}render()});
  root.querySelectorAll('[data-ban]').forEach(b=>b.onclick=()=>analyze([b.dataset.ban]));
  root.querySelectorAll('[data-banall]').forEach(b=>b.onclick=()=>{const ids=b.dataset.banall.split(',');if(ids.length>6&&!confirm(`分析 ${ids.length} 条会启动多个后台会话，确定？`))return;analyze(ids)});
  root.querySelectorAll('[data-bcol]').forEach(c=>c.onchange=()=>{const k=c.dataset.bcol;bugCols=c.checked?[...new Set([...bugCols,k])]:bugCols.filter(x=>x!==k);
    try{localStorage.setItem('kb.bugCols',JSON.stringify(bugCols))}catch(_){}render()});
  root.querySelectorAll('[data-bfix]').forEach(b=>b.onclick=()=>fixBugs([b.dataset.bfix]));
  bindSvnCommit(root);
  root.querySelectorAll('[data-bunq]').forEach(a=>a.onclick=async()=>{try{const r=await post('/api/zentao/unfix',{id:a.dataset.bunq});toast(r.msg);render()}catch(e){toast(e.message)}});
  root.querySelectorAll('[data-bfixall]').forEach(b=>b.onclick=()=>fixBugs(b.dataset.bfixall.split(',')));
  root.querySelectorAll('[data-bfx]').forEach(a=>a.onclick=()=>fixDlg(bugIndex[a.dataset.bfx]));
  root.querySelectorAll('[data-bav]').forEach(a=>a.onclick=()=>analysisDlg(a.dataset.bav).catch(e=>toast(e.message)));
  root.querySelectorAll('[data-bown]').forEach(sel=>{const old=sel.value;sel.onchange=async()=>{
  let t=sel.value;if(t==='__task'){const n=prompt('新建一个事项并把这个 Bug 归进去，事项名：（如：歌房进房 ANR）');if(!n||!n.trim()){sel.value=old;return}t='事项:'+n.trim()}
  try{const r=await post('/api/zentao/assign',{id:sel.dataset.bown,target:t});toast(r.msg);render()}catch(e){toast(e.message);sel.value=old}}})}
// 接入 / 修改一个 Bug 或崩溃平台：适配器（内置或「Bug平台」插件）+ 基础信息里的账号 + 平台特有选项
function srcDlg(s,ents,c){
  const ads=s['适配器'],isNew=!c;let ad=ads.find(a=>a['名称']===(c?c['适配器']:'')||a['插件']===(c&&c['适配器']))||ads[0];
  const optsHtml=a=>(a['选项']||[]).map(o=>`<label>${esc(o['名'])}${o['说明']?` <span class="mut small">${esc(o['说明'])}</span>`:''}<input type="text" data-sopt="${esc(o['名'])}" value="${esc(((c&&c['选项'])||{})[o['名']]??'')}" placeholder="${esc(o['默认']||'')}"></label>`).join('');
  const body=()=>`<div class="form" style="max-width:640px">
    ${isNew?`<label>平台类型<select id="sAd">${ads.map(a=>`<option value="${esc(a['插件']||a['名称'])}" ${a===ad?'selected':''}>${esc(a['名称'])}（${a['类型']==='崩溃'?'崩溃 → ANR 页':'缺陷 → Bug 页'}${a['插件']?'，插件':''}）</option>`).join('')}</select></label>
      <label>名称 <span class="mut small">自己起，如 jira、sentry；平台编号是纯数字时会加上它作前缀</span><input type="text" id="sId" value="${esc(ad['名称'].split(' ')[0].toLowerCase()==='禅道'?'禅道':ad['名称'].split(' ')[0].toLowerCase())}"></label>`:`<p><b>${esc(c.ID)}</b> <span class="mut small">${esc(c['适配器'])}</span></p>`}
    <label>账号（基础信息条目）<span class="mut small" id="sNeed">需要：${esc(ad['账号字段']||'')}</span>
      <select id="sEnt"><option value="">自动找（名称里带平台名的那条）</option>${ents.map(e=>`<option value="${esc(e['编号'])}" ${c&&c['账号条目']===e['编号']?'selected':''}>${esc(e['编号']+' '+e['名称'])}</option>`).join('')}</select></label>
    <div id="sOpts">${optsHtml(ad)}</div>
    ${c?`<label class="row" style="gap:6px;display:flex;align-items:center"><input type="checkbox" id="sOn" style="width:auto;margin:0" ${c['启用']?'checked':''}> 启用（停用后不再同步，已有索引保留）</label>`:''}
    <p class="mut small">只读：知识库只从平台拉数据，从不回写。密码 / 令牌存在基础信息的机密字段里（Mac 上是钥匙串，服务器上是加密文件）。</p>
    <div class="row" style="gap:8px"><button class="pri" id="sSave">${isNew?'接入并同步':'保存'}</button>${c?'<button id="sTest">测试连接</button><button id="sDel" style="margin-left:auto">移除这个平台</button>':''}</div>
    <pre id="sOut" class="small" style="margin-top:8px"></pre></div>`;
  openDlg(isNew?'接入 Bug / 崩溃平台':`平台：${c.ID}`,body());
  const bind=()=>{
    if($('#sAd'))$('#sAd').onchange=()=>{ad=ads.find(a=>(a['插件']||a['名称'])===$('#sAd').value);$('#sOpts').innerHTML=optsHtml(ad);$('#sNeed').textContent='需要：'+(ad['账号字段']||'');
      $('#sId').value=ad['名称'].split(' ')[0].toLowerCase()};
    $('#sSave').onclick=async()=>{const opts={};document.querySelectorAll('[data-sopt]').forEach(i=>opts[i.dataset.sopt]=i.value.trim());
      const id=c?c.ID:$('#sId').value.trim(),b={id,entry:$('#sEnt').value,options:opts};
      if(isNew)b.adapter=ad['插件']||ad['名称'];if(c)b.enabled=$('#sOn').checked;
      try{await post('/api/bug/source',b);$('#sOut').textContent='已保存，测试连接中…';
        try{const t=await post('/api/bug/test',{id});$('#sOut').textContent=t.msg;await post('/api/zentao/sync',{source:id});toast('已保存，开始同步')}
        catch(e){$('#sOut').textContent='已保存，但连接测试失败：\n'+e.message}
        if(isNew)c={ID:id,'适配器':b.adapter,'启用':true};}catch(e){toast(e.message)}};
    if($('#sTest'))$('#sTest').onclick=async()=>{$('#sOut').textContent='测试中…';try{$('#sOut').textContent=(await post('/api/bug/test',{id:c.ID})).msg}catch(e){$('#sOut').textContent=e.message}};
    if($('#sDel'))$('#sDel').onclick=async()=>{if(!confirm(`移除平台「${c.ID}」？没分析过、没手动归类、没修复过的索引条目会去掉（平台上的数据不受影响）`))return;
      try{const r=await post('/api/bug/source',{id:c.ID,remove:true});toast(r.msg);dlg.close();bugsPage()}catch(e){toast(e.message)}};
  };bind();
  dlg.addEventListener('close',()=>{if(location.hash.startsWith('#/bugs'))bugsPage()},{once:true});
}
async function bugsPage(){
  const d=await api('/api/zentao');navRefresh();periodNames=d.periods;taskNames=d.tasks;const s=d.status;
  const stOk=b=>bugF.st==='全部'||b['状态']!=='已关闭';
  const OW=['待归纳','期','事项','未关联','全部'];
  const cnt=o=>d.bugs.filter(b=>(o==='全部'||b['归属']['类型']===o)&&stOk(b)).length;
  const q=bugF.q.trim().toLowerCase();
  const list=d.bugs.filter(b=>(bugF.owner==='全部'||b['归属']['类型']===bugF.owner)&&(!q||JSON.stringify(b).toLowerCase().includes(q)));
  const srcs=s['平台'],defects=srcs.filter(c=>c['类型']==='缺陷'),crashes=srcs.filter(c=>c['类型']==='崩溃');
  const srcRow=c=>`<div class="row" style="flex-wrap:wrap;gap:10px;margin:4px 0">
      <b>${esc(c.ID)}</b><span class="small mut">${esc(c['适配器'])}${c['启用']?'':' · 已停用'}</span>
      ${c['类型']==='缺陷'?`<label class="small mut">范围 <select data-zscope="${esc(c.ID)}">${s['范围选项'].map(x=>`<option ${x===c['范围']?'selected':''}>${x}</option>`).join('')}</select></label>
      <label class="small mut">平台 <select data-zpf="${esc(c.ID)}">${s['平台选项'].map(x=>`<option ${x===c['平台']?'selected':''}>${x}</option>`).join('')}</select></label>
      <span class="small mut">未关闭 ${c['未关闭']}</span>`:`<a class="small" href="#/anr">→ 💥 ANR / 崩溃</a>`}
      <span class="small mut">${esc(c['同步']||'还没同步')}</span><a class="small" data-zsrc="${esc(c.ID)}">设置…</a></div>`;
  app.innerHTML=`${''}<div class="pagehead"><div><h1>🐞 Bug</h1><p class="mut">从 Bug 平台（禅道、Jira…）同步并自动归到期（按执行 / Sprint / 项目 / Jenkins 分支）；线上反馈、认不出的进「待归纳」，你来归。知识库只存链接和简介，原文以平台为准。崩溃平台（Sentry、Firebase、Bugly）同步到「💥 ANR / 崩溃」。</p></div>
    <div class="row"><button id="zAdd">＋ 接入平台</button><button id="zSync" ${s['正在同步']||!srcs.length?'disabled':''}>${s['正在同步']?'同步中…':'⟳ 立即同步'}</button></div></div>
  ${fixPanel(d.fixq)}
  <div class="card2" style="margin-bottom:12px"><div class="bd">
    ${srcs.length?srcs.map(srcRow).join(''):'<p class="mut" style="margin:0">还没接入 Bug 平台：先在「◈ 基础信息」存好账号，再点右上角「＋ 接入平台」。</p>'}
    <div class="small mut" style="margin-top:4px">「我的」= 指派给我或由我解决 · 上次同步 ${esc(s['上次同步']||'从未')}${s['下次同步']?' · 下次 '+esc(s['下次同步']):''} · 每 ${s['间隔小时']>=1?s['间隔小时']+' 小时':Math.round(s['间隔小时']*60)+' 分钟'}自动同步 · 转给别人的会移除
    ${s['结果']?`<div class="small" style="white-space:pre-wrap;color:var(--fg)">${esc(s['结果'])}</div>`:''}</div></div></div>
  <div class="fchips">${OW.map(o=>`<button class="fchip ${o===bugF.owner?'on':''}" data-bo="${o}">${o}<b>${cnt(o)}</b></button>`).join('')}
    <label class="small mut" style="margin-left:8px"><input type="checkbox" id="zAll" ${bugF.st==='全部'?'checked':''}> 含已关闭</label>
    <input type="text" id="zQ" value="${esc(bugF.q)}" placeholder="筛选：标题、期名、执行…" style="margin-left:auto;width:220px"></div>
  ${(d.sessions||[]).length?`<div class="card2" style="margin-bottom:10px"><div class="bd small">${d.sessions.map(x=>`<div>${x['状态']==='运行中'?(x['类型']==='修复'?'🔧 修复中':'● 分析中'):'⚠'} Bug ${esc(x.Bug.join('、'))} · ${esc(x['引擎']||'')} · <span class="mono">${esc(x['仓库'].replace(/^\/Users\/[^/]+/,'~'))}</span> · ${esc(x['开始时间'])}${x['警告']?` <b style="color:var(--s4)">${esc(x['警告'])}</b>`:''}</div>`).join('')}</div></div>`:''}
  ${bugTable(list,d.periods,bugF.st)}`;
  const save=()=>{try{localStorage.setItem('kb.bugF',JSON.stringify(bugF))}catch(_){}};
  app.querySelectorAll('[data-bo]').forEach(b=>b.onclick=()=>{bugF.owner=b.dataset.bo;save();bugsPage()});
  $('#zAll').onchange=()=>{bugF.st=$('#zAll').checked?'全部':'未关闭';save();bugsPage()};
  $('#zQ').onchange=()=>{bugF.q=$('#zQ').value;save();bugsPage()};
  bindBugs(app);
  const setz=async b=>{try{await post('/api/bug/source',b);const r=await post('/api/zentao/sync',{source:b.id});toast('已保存，'+r.msg);bugsPage()}catch(e){toast(e.message);bugsPage()}};
  app.querySelectorAll('[data-zpf]').forEach(x=>x.onchange=()=>setz({id:x.dataset.zpf,platform:x.value}));
  app.querySelectorAll('[data-zscope]').forEach(x=>x.onchange=()=>{const c=srcs.find(y=>y.ID===x.dataset.zscope);
    if(x.value==='指定人'){const p=prompt('同步哪些人的 Bug？填平台账号，多个用逗号隔开',(c['人员']||[]).join(','));if(!p){x.value=c['范围'];return}setz({id:c.ID,scope:'指定人',people:p});return}
    setz({id:c.ID,scope:x.value})});
  app.querySelectorAll('[data-zsrc]').forEach(a=>a.onclick=()=>srcDlg(s,d.baseEntries,srcs.find(c=>c.ID===a.dataset.zsrc)));
  $('#zAdd').onclick=()=>srcDlg(s,d.baseEntries,null);
  $('#zSync').onclick=async()=>{try{const r=await post('/api/zentao/sync',{});toast(r.msg);$('#zSync').disabled=true;$('#zSync').textContent='同步中…'}catch(e){toast(e.message)}};
}
