// ==== 期页面：下一步、资料、来源核对、上传、文字资料
// 每一期顶部：走到哪一步、下一步谁做什么（后端 period_guide 算）
function guideHtml(g){
  const n=g['下一步'];
  return `<div class="steps">${g['步骤'].map(s=>`<div class="step ${s['状态']==='done'?'done':s['状态']==='cur'?'cur':''}">${s['状态']==='done'?'✓ ':''}${esc(s['名称'])}</div>`).join('')}</div>
  <div class="gnext">${n['谁']?`<span class="who w-${esc(n['谁'])}">${n['谁']==='你'?'需要你判断':'AI 在做'}</span>`:''}<div class="tx"><b>${esc(n['文字'])}</b>${n['说明']?`<div>${esc(n['说明'])}</div>`:''}</div>
    ${n['按钮']?`<button class="${n['谁']==='你'?'pri':''}" id="gGo" data-to="${esc(n['去']||'')}">${esc(n['按钮'])}</button>`:''}</div>`;
}
async function period(name){
  const d=await api('/api/period?name='+enc(name)), m=d.meta;
  if(!periodNames.length){try{sideNav(await api('/api/overview'))}catch(_){}}
  const isTask=m['类型']==='事项';
  if(isTask&&(m['外部来源']||[]).length&&!fullView[d.name])return pushPage(d);
  if(isTask&&!fullView[d.name])return memoPage(d.name);
  const hist=m['状态历史']||[];
  const lastAt=s=>{for(let i=hist.length-1;i>=0;i--)if(hist[i]['状态']===s)return hist[i]['时间'];return''};
  const flow=['收集中','已批准开发','开发中','已完成'], ci=flow.indexOf(m['状态']);
  const steps=flow.map((s,i)=>`<div class="step ${i<ci?'done':i===ci?'cur':''}">${s}<small>${esc(lastAt(s))}</small></div>`).join('');
  const hasDesign=d.materials['设计图'].some(f=>f.isImage||(f.isDir&&f.images&&f.images.length));
  const missing=d.cats.filter(c=>c!=='其他资料'&&c!=='设计图'&&!d.materials[c].length&&!d.notes[c].length).concat(hasDesign?[]:['设计稿（Figma / 蓝湖）']);
  let notice='';
  if(m['状态']==='收集中'&&isTask)notice=`<div class="notice"><span>把现象、日志 / traces、截图、用户反馈拖进「资料」，或在 🐞 Bug 页把相关 Bug 归进来；准备好后在「开发」里点「开始开发」（按轻量流程：定位 → 确认改法 → 修改自测 → 写结论）。</span></div>`;
  else if(m['状态']==='收集中')notice=`<div class="notice">${missing.length?`<span>还缺：<b>${missing.join('、')}</b>。</span>`:'<span>材料看起来齐了。</span>'}
     <span>确认后点下方「开始开发」，或在终端运行</span><code id="apc">kb approve "${esc(d.name)}"</code><button onclick="navigator.clipboard.writeText(document.getElementById('apc').textContent);toast('已复制')">复制</button><span class="mut small">（批准只能本人操作）</span></div>`;
  if(m['状态']==='已暂停')notice=`<div class="notice">已暂停。</div>`;
  const catBox=c=>{
    const items=d.materials[c], h=d.history[c], ns=d.notes[c];
    const imgs=items.filter(f=>f.isImage), others=items.filter(f=>!f.isImage&&!(f.isDir&&f.images&&f.images.length));
    const dirImgs=others.filter(f=>f.isDir&&f.images&&f.images.length);
    const tip={'设计图':'设计稿 · 要实现的产品图，UI 以此为准（Figma / 蓝湖）','需求':'PRD、需求说明；原型图/参考图只用于理解交互'}[c]||'';
    return `<div class="cat"><div class="hd"><b>${c} <span class="mut">(${items.length+ns.length})</span>${tip?` <span class="mut small" style="font-weight:400">${tip}</span>`:''}</b><span class="row small">${h.length?`<a data-hist="${esc(c)}">历史版本 ${h.length}</a>`:''}<a data-nadd="${esc(c)}">＋ 文字 / 链接</a></span></div><div class="bd">
      ${ns.map(noteCard).join('')}
      ${imgs.length?`<div class="grid">${imgs.map(f=>`<div class="thumb" data-img="${esc(f.path)}"><img loading="lazy" src="${fileUrl(f.path)}"><div class="${f.note?'':'nonote'}" title="${esc(f.note)}">${esc(f.name)}${f.note?'':' · 无说明'}</div></div>`).join('')}</div>`:''}
      ${others.length?`<ul class="files">${others.map(f=>`<li><a data-read="${esc(f.path)}" data-dir="${f.isDir?1:''}">${esc(f.name)}${f.isDir?`/ <span class="mut small">${f.count} 个文件</span>`:''}</a><span class="mut small">${f.isDir?'':size(f.size)+' · '}${when(f.mtime)}</span></li>`).join('')}</ul>`:''}
      ${dirImgs.map(f=>`<details ${c==='设计图'?'open':''} style="margin-top:8px"><summary class="small"><b>${esc(f.name)}/</b> <span class="mut">${f.images.length} 张${f.name==='原型图'?' · 原型图/参考图，仅供理解交互，UI 以设计稿为准':c==='设计图'?' · 设计稿':''}</span></summary>
        <div class="grid" style="margin-top:6px">${f.images.map(p=>`<div class="thumb" data-img="${esc(p)}" data-note="${esc((f.notes||{})[p]||'')}"><img loading="lazy" src="${fileUrl(p)}"><div title="${esc((f.notes||{})[p]||'')}">${esc(p.split('/').pop())}</div></div>`).join('')}</div></details>`).join('')}
      ${c==='设计图'&&!isTask&&!imgs.length&&!dirImgs.length?'<div class="small" style="color:var(--warn);margin-top:6px">还没有设计稿：把需求表里「设计稿地址」（Figma / 蓝湖）发给 Claude 导入，或把导出的画板拖进来</div>':''}
      ${!items.length&&!ns.length?'<div class="mut small">暂无</div>':''}
      <div class="drop" data-cat="${esc(c)}">拖文件 / 链接 / 文字到这里，或点击选择文件</div></div></div>`;
  };
  const tabs=[['dev','开发',(m['待确认']||[]).filter(q=>q['状态']==='待回答').length+((m['非阻断问题']||[]).filter(q=>q['状态']==='待处理').length)],
    ['mat','资料',d.cats.reduce((a,c)=>a+d.materials[c].length+d.notes[c].length,0)],
    ['stack','全栈',m['全栈']&&m['全栈']['状态']==='待拍板'?1:0],
    ['build','构建',0],
    ['bug','Bug',(d.bugs||[]).filter(b=>b['状态']!=='已关闭').length],
    ['log','记录',d.log.length]];
  // 整页：开发一直在资料上面；开发完成（已完成）后 Bug 提到最上面；记录一直在最下面
  const devDone=m['状态']==='已完成', openBugs=(d.bugs||[]).filter(b=>b['状态']!=='已关闭');
  const stackFirst=!devDone&&!['已批准开发','开发中'].includes(m['状态'])&&(m['全栈']||{})['状态']!=='已拍板';
  const order=devDone?['bug','dev','stack','build','mat','log']:stackFirst?['stack','dev','build','mat','bug','log']:['dev','stack','build','mat','bug','log'];
  const focus=devDone?(openBugs.length?'bug':''):['已批准开发','开发中'].includes(m['状态'])?'dev':'';
  const whole=pview==='whole';
  const secHd=k=>{if(!whole)return'';const t=tabs.find(x=>x[0]===k);return`<h2 class="psec">${t[1]}${k===focus?'<span class="cur">进行中</span>':''}</h2>`};
  let tab=(ptabs[d.name]==='src'?'mat':ptabs[d.name])||(m['开发会话']||['已批准开发','开发中','已完成'].includes(m['状态'])?'dev':'mat');
  const branches=Object.values(d.notes).flat().filter(n=>n['类型']==='分支');
  const pend=(m['来源']||[]).filter(x=>x['核对']!=='已核对').length;
  app.innerHTML=`<div class="pagehead"><div style="min-width:0"><div class="crumb"><a href="#/">总览</a> / ${isTask?(((ovPeriods.find(p=>p.name===name)||{}).batch||{})['来源']==='anr'?'<a href="#/anr">💥 ANR / 崩溃</a> / 批次':'事项'):'期'}${isTask?` · <a id="toPush">← ${(m['外部来源']||[]).length?'回到原始内容':'回到简洁版'}</a>`:''}</div>
      <h1>${esc(d.name)} ${badge(m['状态'])}${isTask?` <span class="badge st-收集中">${esc(m['事项类型']||'其他')}</span> <span class="badge ${PRI_C[m['优先级']]||''}">优先级 ${esc(m['优先级']||'中')}</span>`:''}</h1><div class="mut">${esc(m['说明']||'')}${isTask&&m['来自']?`　<span class="small">来自：${esc(m['来自'])}</span>`:''}${isTask?` <a class="small" id="tkEdit">✎ 编辑</a>`:''}</div>
      <div class="pmeta">${branches.length?`<span>🌿 开发分支 ${branches.map(n=>`<b class="mono">${esc(noteTitle(n))}</b>`).join('；')}</span>`:''}
        ${m['开发仓库']?`<span>仓库 <span class="mono">${esc(m['开发仓库'].replace(/^\/Users\/[^/]+/,'~'))}</span></span>`:''}
        <span>关联仓库 ${esc((m['关联仓库']||[]).join('、')||'无')}</span><span class="mono" title="这一期的资料目录">${esc(d.dir.replace(/^\/Users\/[^/]+/,'~'))}</span></div></div>
    <div class="row"><span class="pview" title="分栏：按分类切换；整页：所有内容一页看完，按流程先后排，正在进行的放最上面"><button data-pv="tab" class="${whole?'':'on'}">▤ 分栏</button><button data-pv="whole" class="${whole?'on':''}">☰ 整页</button></span><label class="small mut" for="stSel">状态</label><select id="stSel">${[...new Set([m['状态'],'收集中','开发中','已完成','已暂停'])].map(s=>`<option ${s===m['状态']?'selected':''}>${s}</option>`).join('')}</select><button id="fixLink" title="设计稿、文档地址给错了：所有地方一起换成正确链接">✎ 更正链接</button><button class="danger" id="delP" title="没用的${isTask?'事项':'期'}：从知识库里整个删掉">🗑 删除</button></div></div>
    ${d.guide?guideHtml(d.guide):`<div class="steps">${steps}</div>${notice}`}
    <div class="card2 talk"><div class="bd">
      <div id="sessBar">${devCache.name===d.name?devCache.bar||'':''}</div>
      <textarea id="tkMsg" rows="2" placeholder="跟这一期说：有会话在跑就补充给它；没有就按内容推动解决（后续发现的问题、需求扩展）。Cmd+Enter 发送">${esc(drafts['tk:'+d.name]||'')}</textarea>
      <div class="ctl"><button class="pri" id="tkSend">发送</button><span id="tkMode" class="small row" hidden>
        <label class="row"><input type="radio" name="tkM" value="insert" checked> 插入当前会话</label>
        <label class="row"><input type="radio" name="tkM" value="new"> 启动新会话执行</label>
        <label class="row"><input type="radio" name="tkM" value="queue"> 排队处理</label></span>
        <span id="tkTo" class="small"></span>
        <label class="small row" id="tkIntL" style="color:var(--fg)" hidden><input type="checkbox" id="tkWait"> 等开发会话这一步做完再插入</label></div>
      <div class="mut small" id="tkHint" style="margin-top:4px"></div>
      <div class="chat" id="tkMsgs"></div>
      <details id="tkActD" style="margin-top:6px"><summary class="small"><b>最近动作</b> <span class="mut" id="tkActN"></span>　<a id="tkAll">查看全部开发记录</a></summary><div class="act" id="tkActs"></div></details>
    </div></div>
    <div class="${whole?'pwhole':''}" style="display:flex;flex-direction:column"><nav class="ptabs" style="order:-1">${(whole?order.map(k=>tabs.find(x=>x[0]===k)):tabs).map(([k,t,n])=>`<a class="ptab ${k===tab&&!whole?'on':''}" data-tab="${k}">${t}${n?`<span class="n${k==='dev'&&n?' w':''}">${n}</span>`:''}${k==='mat'&&pend?`<span class="n w" title="来源核对">${pend} 待核对</span>`:''}</a>`).join('')}</nav>
    <div data-pane="dev" style="order:${order.indexOf('dev')}" ${whole||tab==='dev'?'':'hidden'}>${secHd('dev')}<div class="dev" id="devBox">${devCache.name===d.name?devCache.html:'<span class="mut">开发面板加载中…</span>'}</div></div>
    <div data-pane="mat" style="order:${order.indexOf('mat')}" ${whole||tab==='mat'?'':'hidden'}>${secHd('mat')}${(m['来源']||[]).length?`<details class="cat" id="srcSec" ${pend||(m['来源']||[]).some(x=>x['待更新'])?'open':''}><summary class="hd" style="cursor:pointer"><b>来源核对 <span class="mut">(${(m['来源']||[]).length})</span> <span class="mut small" style="font-weight:400">从网址导入的资料，逐条和原网页核对</span></b>${pend?`<span class="badge st-已暂停">${pend} 待核对</span>`:'<span class="badge st-已完成">全部已核对</span>'}</summary><div class="bd">${srcBox(d)}</div></details>`:''}
      <div class="matgrid">${d.cats.map(catBox).join('')}</div></div>
    <div data-pane="stack" style="order:${order.indexOf('stack')}" ${whole||tab==='stack'?'':'hidden'}>${secHd('stack')}<div class="card2"><div class="bd" id="stackBox"><span class="mut small">加载中…</span></div></div></div>
    <div data-pane="build" style="order:${order.indexOf('build')}" ${whole||tab==='build'?'':'hidden'}>${secHd('build')}<div class="card2"><div class="bd" id="buildBox"><span class="mut small">构建加载中…</span></div></div></div>
    <div data-pane="bug" style="order:${order.indexOf('bug')}" ${whole||tab==='bug'?'':'hidden'}>${secHd('bug')}<div class="card2"><div class="bd">
      <p class="mut small" style="margin-top:0">Bug 平台上归到这里的 Bug（按执行 / Sprint / Jenkins 分支自动归，也可手动改归属）。知识库只存链接和简介；「分析」由后台 AI 只读完成（实时拉取原文和截图 → 对照本期分支改动和代码），结论等你审核。<a href="#/bugs">全部 Bug →</a></p>
      ${fixPanel(d.fixq,new Set((d.bugs||[]).map(b=>b['编号'])))}${bugTable(d.bugs||[],kbPeriods(d),'未关闭')}</div></div></div>
    <div data-pane="log" style="order:${order.indexOf('log')}" ${whole||tab==='log'?'':'hidden'}>${secHd('log')}<div class="card2"><div class="bd">
      <div class="row" style="margin-bottom:8px"><input type="text" id="logIn" placeholder="追加一条记录…"><button id="logGo">记录</button></div>
      <div class="tl">${d.log.slice().reverse().map(l=>`<div class="it"><div class="mut small">${esc(l.time)}</div><span class="a">${esc(l.action)}</span>　${esc(l.content)}</div>`).join('')||'<span class="mut">暂无</span>'}</div></div></div></div></div>`;
  app.querySelectorAll('[data-pv]').forEach(b=>b.onclick=()=>{pview=b.dataset.pv;try{localStorage.setItem('kb.pview',pview)}catch(_){}render()});
  if(!whole)app.querySelectorAll('[data-tab]').forEach(a=>a.onclick=()=>{ptabs[d.name]=a.dataset.tab;try{localStorage.setItem('kb.ptabs',JSON.stringify(ptabs))}catch(_){}
    app.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('on',x===a));app.querySelectorAll('[data-pane]').forEach(x=>x.hidden=x.dataset.pane!==a.dataset.tab)});
  const gb=$('#gGo');if(gb)gb.onclick=()=>{const k=(gb.dataset.to||'').replace('tab:','');if(!k)return;
    if(whole){const p=app.querySelector(`[data-pane="${k}"]`);if(p)p.scrollIntoView({behavior:'smooth',block:'start'})}else{const a=app.querySelector(`[data-tab="${k}"]`);if(a)a.click()}};
  devBox(d.name);talkBind(d.name);buildBox(d.name);stackBox(d.name);
  bindBugs(app);
  app.querySelectorAll('[data-read]').forEach(a=>a.onclick=()=>a.dataset.dir?toast('目录：请在 Finder 或让 Claude 查看'):readFile(a.dataset.read));
  app.querySelectorAll('[data-img]').forEach(a=>a.onclick=()=>showImg(a.dataset.img,d));
  app.querySelectorAll('[data-hist]').forEach(a=>a.onclick=()=>{const c=a.dataset.hist;openDlg(c+' · 历史版本',`<ul class="files">${d.history[c].map(f=>`<li><a onclick="readFile('${esc(f.path).replace(/'/g,"\\'")}')">${esc(f.name)}</a><span class="mut small">${when(f.mtime)}</span></li>`).join('')}</ul>`)});
  app.querySelectorAll('.drop').forEach(z=>bindDrop(z,d.name,z.dataset.cat));
  const allNotes=Object.values(d.notes).flat(), byId=id=>allNotes.find(n=>n['编号']===id);
  app.querySelectorAll('[data-nadd]').forEach(a=>a.onclick=()=>noteForm(d,{'分类':a.dataset.nadd}));
  app.querySelectorAll('[data-nedit]').forEach(a=>a.onclick=()=>noteForm(d,byId(a.dataset.nedit)));
  app.querySelectorAll('[data-ndel]').forEach(a=>a.onclick=async()=>{const n=byId(a.dataset.ndel);
    if(!confirm(`删除 ${n['编号']}「${noteTitle(n)}」？`))return;
    try{const r=await post('/api/note',{period:d.name,id:n['编号'],delete:true});toast(r.msg);render()}catch(e){toast(e.message)}});
  app.querySelectorAll('[data-v]').forEach(b=>b.onclick=async()=>{
    let note='';if(b.dataset.s==='有问题'){note=prompt('哪里有问题？（会记进记录，Claude 可据此修正）')||'';}
    try{const r=await post('/api/verify',{period:d.name,sid:b.dataset.v,status:b.dataset.s,note});toast(r.msg);render()}catch(e){toast(e.message)}});
  const refresh=async(sid,b)=>{b.disabled=true;const t=b.textContent;b.textContent='检查中…';
    try{const r=await post('/api/refresh',{period:d.name,sid});openDlg('检查更新结果',`<pre style="white-space:pre-wrap">${esc(r.msg)}</pre>`);render()}
    catch(e){toast(e.message)}finally{b.disabled=false;b.textContent=t}};
  app.querySelectorAll('[data-refresh]').forEach(b=>b.onclick=()=>refresh(b.dataset.refresh,b));
  if($('#srcAll'))$('#srcAll').onclick=()=>refresh('',$('#srcAll'));
  if($('#srcClaude'))$('#srcClaude').onclick=async()=>{try{const r=await post('/api/refresh/claude',{period:d.name});toast(r.msg);render()}catch(e){toast(e.message)}};
  $('#logGo').onclick=async()=>{const v=$('#logIn').value.trim();if(!v)return;try{await post('/api/log',{period:d.name,note:v});render()}catch(e){toast(e.message)}};
  $('#fixLink').onclick=()=>fixLinkDlg(d);
  if($('#toPush'))$('#toPush').onclick=()=>{delete fullView[d.name];render()};
  $('#delP').onclick=()=>delPeriod(d.name,isTask);
  if($('#tkEdit'))$('#tkEdit').onclick=()=>{openDlg('编辑事项',`<div class="form">${taskForm({edit:1,name:d.name,kind:m['事项类型'],priority:m['优先级'],from:m['来自'],summary:m['说明'],kinds:d.taskKinds,pris:d.taskPri})}
      <div class="row"><button class="pri" id="tkGo">保存</button></div></div>`);
    $('#tkGo').onclick=async()=>{try{const r=await post('/api/task/meta',{period:d.name,kind:$('#tkK').value,priority:$('#tkP').value,source:$('#tkF').value.trim(),summary:$('#tkS').value.trim()});toast(r.msg);dlg.close();render()}catch(e){toast(e.message)}}};
  $('#stSel').title='选另一个状态会先确认再修改';
  $('#stSel').onchange=async()=>{const sel=$('#stSel'),to=sel.value;
    if(!confirm(`把「${d.name}」的状态从「${m['状态']}」改为「${to}」？`)){sel.value=m['状态'];return}
    try{const r=await post('/api/status',{period:d.name,status:to});toast(r.msg);render()}catch(e){toast(e.message);sel.value=m['状态']}};
}

// 新加了设计稿链接、这一期又有别的设计稿链接：问是不是要替换旧的
function askReplace(p,r){
  if(!r||!r.replace||!r.replace.length)return;
  openDlg('要替换旧的设计稿链接吗？',`<div class="small" style="margin-bottom:8px">新链接：<span class="mut">${esc(r.new)}</span></div>
    <div class="small">这一期还有别的设计稿链接。如果新链接是用来<b>替换</b>旧的，选中旧链接点「替换」：文档、SDD 配置里的旧链接会一起换掉，开发会话会重新下载设计稿。只是补充一个页面就点「不替换」。</div>
    ${r.replace.map((u,i)=>`<label class="small" style="display:block;margin-top:6px"><input type="checkbox" value="${i}" checked> ${esc(u)}</label>`).join('')}
    <div class="row" style="margin-top:10px"><button class="pri" id="rpGo">替换</button><button id="rpNo">不替换</button></div>`);
  $('#rpNo').onclick=()=>dlg.close();
  $('#rpGo').onclick=async()=>{const b=$('#rpGo');b.disabled=true;b.textContent='处理中…';const out=[];
    for(const c of $('#dlgB').querySelectorAll('input[type=checkbox]:checked')){
      try{out.push((await post('/api/fixlink',{period:p,old:r.replace[+c.value],new:r.new,reason:'网页新加设计稿链接时选择替换'})).msg)}catch(e){out.push('失败：'+e.message)}}
    openDlg('替换结果',`<pre style="white-space:pre-wrap">${esc(out.join('\n\n')||'没有选择')}</pre>`);render()};
}

async function fixLinkDlg(d){
  let ls=[];try{ls=await api('/api/links?name='+enc(d.name))}catch(e){return toast(e.message)}
  if(!ls.length)return toast('这一期还没有链接');
  openDlg('更正链接',`<div class="mut small" style="margin-bottom:8px">把给错的链接换成正确的：文档、文字资料、来源、SDD 配置（sdd-start.md）一起改，旧内容进历史版本；新链接是设计稿会自动导入；正在开发时会提醒开发会话重新下载物料。</div>
    <label class="small">错误的链接</label><select id="flOld" style="width:100%">${ls.map((x,i)=>`<option value="${i}">${esc(x['链接'].length>90?x['链接'].slice(0,90)+'…':x['链接'])}　〔${esc(x['出处'].join('、'))}〕</option>`).join('')}</select>
    <label class="small" style="margin-top:8px;display:block">正确的链接</label><input type="text" id="flNew" style="width:100%" placeholder="https://www.figma.com/design/…?node-id=…">
    <label class="small" style="margin-top:8px;display:block">原因（可空）</label><input type="text" id="flWhy" style="width:100%" placeholder="如：设计稿给错了版本">
    <div class="row" style="margin-top:10px"><button class="pri" id="flGo">更正</button></div>`);
  $('#flGo').onclick=async()=>{const b=$('#flGo');b.disabled=true;b.textContent='处理中…';
    try{const r=await post('/api/fixlink',{period:d.name,old:ls[+$('#flOld').value]['链接'],new:$('#flNew').value.trim(),reason:$('#flWhy').value.trim()});
      openDlg('更正结果',`<pre style="white-space:pre-wrap">${esc(r.msg)}</pre>`);render()}
    catch(e){toast(e.message);b.disabled=false;b.textContent='更正'}};
}

const VCLS={'待核对':'st-已批准开发','已核对':'st-已完成','有问题':'st-已暂停'};
function srcBox(d){
  const ss=d.meta['来源']||[];if(!ss.length)return'';
  const pend=ss.filter(s=>s['核对']!=='已核对').length;
  const base=d.dir+'/';
  const fl=f=>`<a data-read="${esc(base+f)}">${esc(f)}</a>`;
  const IMG=/\.(png|jpe?g|gif|webp|bmp|heic|tiff?)$/i;
  const flist=fs=>{const docs=fs.filter(f=>!IMG.test(f)), g={};fs.filter(f=>IMG.test(f)).forEach(f=>{const k=f.slice(0,f.lastIndexOf('/')+1);g[k]=(g[k]||0)+1});
    return docs.map(fl).concat(Object.entries(g).map(([k,n])=>`<span class="mut">${esc(k)}</span> ${n} 张图`)).join('<br>')};
  const stale=ss.filter(s=>s['待更新']).map(s=>s['编号']), up=d.meta['更新会话']||{}, upRun=up['状态']==='运行中';
  const ar=d.autoRefresh||{};
  return `<div class="small mut" style="margin-bottom:8px">共 ${ss.length} 条${pend?'，<b style="color:var(--warn)">'+pend+' 条待核对</b>':'，全部已核对'}：逐条确认导入的内容和原网页一致</div>
  <div class="row" style="margin-bottom:8px;align-items:center">
    <button id="srcAll" title="按登记的网址重新抓取，原文没变不会改动任何文件">⟳ 全部检查更新</button>
    ${stale.length?(upRun?`<span class="badge st-开发中">Claude 正在更新 ${esc((up['来源']||[]).join('、'))}…</span>`
      :`<button id="srcClaude" class="pri">交给 Claude 更新 ${esc(stale.join('、'))}</button>`):''}
    <span class="mut small">${ar.hours>0?`自动检查：每 ${ar.hours} 小时${ar.last?'，上次 '+esc(ar.last)+'（'+esc(ar.result)+'）':''}${ar.next?'，下次 '+esc(ar.next):''}`:'自动检查已关闭'}</span>
  </div>
  ${stale.length&&!upRun?`<div class="small" style="color:var(--warn);margin-bottom:8px">⚠ ${esc(stale.join('、'))} 只导入了页面里的某个条目，原文在条目范围内有改动：快照已更新，条目文档需要重新整理。点「交给 Claude 更新」在后台处理，或在对话里让 Claude 更新。</div>`:''}
  ${up['状态']==='已结束'&&up['结束时间']?`<div class="small mut" style="margin-bottom:8px">上次条目更新：${esc(up['结束时间'])}${up['出错']?'（有错误）':''}${up['结果']?' — '+esc(up['结果'].slice(0,200)):''}</div>`:''}
  <div class="tw"><table><tr><th>编号</th><th>来源</th><th>条目 / 简介</th><th>本地文件</th><th>核对</th></tr>
  ${ss.slice().reverse().map(s=>`<tr>
    <td>${esc(s['编号'])}<div class="small mut">${esc(s['类型']||'资料')}</div></td>
    <td><a href="${esc(s['地址'])}" target="_blank" rel="noopener">${esc(s['标题'])} ↗</a>
      <div class="mut small">${s['页面版本']?'v'+esc(s['页面版本'])+' · ':''}${esc(s['最后修改']||'')}</div>
      <div class="mut small">抓取 ${esc(s['抓取时间'])}</div>
      ${s['检查时间']?`<div class="small ${['已更新','条目待更新','失败'].includes(s['检查结果'])?'':'mut'}" ${s['检查结果']==='失败'?'style="color:var(--warn)"':''}>检查 ${esc(s['检查时间'])} · ${esc(s['检查结果']||'')}${s['检查说明']&&s['检查结果']==='失败'?'：'+esc(s['检查说明']):''}</div>`:''}
      ${s['待更新']?'<div class="small" style="color:var(--warn)">⚠ 原文已变化，条目待更新</div>':''}
      ${(s['变更记录']||[]).slice(-3).reverse().map(c=>`<div class="small">变更 ${esc(c['时间'])} · ${esc(c['版本'])} · ${esc(c['改动'])} · ${esc(c['处理'])} <a data-read="${esc(base+c['差异'])}">差异</a></div>`).join('')}
      <button class="small" style="margin-top:4px" data-refresh="${esc(s['编号'])}">⟳ 检查更新</button></td>
    <td>${s['条目']?'<b>'+esc(s['条目'])+'</b><br>':''}${esc(s['简介'])}</td>
    <td class="small">${flist(s['文件']||[])}${s['快照']?`<br><span class="mut">快照：</span>${fl(s['快照'])}`:''}</td>
    <td style="min-width:150px">${badge2(s['核对'])}${s['核对备注']?'<div class="small mut">'+esc(s['核对备注'])+'</div>':''}
      <div class="row" style="margin-top:6px"><button class="small" data-v="${esc(s['编号'])}" data-s="已核对">✓ 正确</button><button class="small" data-v="${esc(s['编号'])}" data-s="有问题">✗ 有问题</button></div></td>
  </tr>`).join('')}</table></div>`;
}
const badge2=s=>`<span class="badge ${VCLS[s]||''}">${esc(s)}</span>`;
function bindDrop(z,p,c){
  const pick=document.createElement('input');pick.type='file';pick.multiple=true;
  z.onclick=()=>pick.click();pick.onchange=()=>upload([...pick.files],p,c);
  z.ondragover=e=>{e.preventDefault();z.classList.add('over')};z.ondragleave=()=>z.classList.remove('over');
  z.ondrop=async e=>{e.preventDefault();z.classList.remove('over');const fs=[...e.dataTransfer.files];
    if(fs.length)return upload(fs,p,c);
    const u=(e.dataTransfer.getData('text/uri-list')||'').split('\n').find(x=>x&&!x.startsWith('#'))||'', t=e.dataTransfer.getData('text/plain')||'';
    if(!u&&!t.trim())return;
    try{const r=await post('/api/note',{period:p,category:c,content:u&&t.trim()===u?'':t,url:u});toast(r.msg.split('\n')[0]);render();askReplace(p,r)}catch(err){toast(err.message)}};
}
async function upload(files,p,c){
  for(const f of files){
    if(!f.size&&!f.type){toast(`跳过 ${f.name}：文件夹请用 kb add 或让 Claude 归档`);continue}
    toast(`上传 ${f.name}…`);
    try{const r=await api('/api/upload',{method:'POST',headers:{'X-Period':enc(p),'X-Category':enc(c),'X-Filename':enc(f.name)},body:f});toast(r.msg.split('\n')[0])}
    catch(e){toast(`${f.name}：${e.message}`)}
  }
  render();
}
const noteTitle=n=>n['显示标题']||n['标题']||'';
function noteCard(n){
  return `<div class="note k-${esc(n['类型'])}"><div class="row"><span class="badge st-收集中">${esc(n['类型'])}</span>
    ${n['标题']?`<b>${esc(n['标题'])}</b>`:''}<span class="mut small">${esc(n['编号'])} · ${esc(n['更新时间']||n['时间'])}${n['来自']?' · 来自 '+esc(n['来自']):''}</span>
    <span class="ops"><a data-nedit="${esc(n['编号'])}">编辑</a><a data-ndel="${esc(n['编号'])}">删除</a></span></div>
    ${n['链接']?`<div class="nu"><a href="${esc(n['链接'])}" target="_blank" rel="noopener">${esc(n['链接'])} ↗</a></div>`:''}
    ${n['内容']&&n['内容']!==n['链接']?`<div class="nb">${esc(n['内容'])}</div>`:''}</div>`;
}
function noteForm(d,n){
  const isNew=!n['编号'], opt=(arr,v,first)=>(first?`<option value="">${first}</option>`:'')+arr.map(x=>`<option ${x===v?'selected':''}>${esc(x)}</option>`).join('');
  openDlg(isNew?'记一条文字资料':`编辑 ${n['编号']}`,`<div class="form">
    <div class="mut small">不必是完整材料：产品说的几句话、要开发的分支、别的小组给的文档地址…都可以先记下。</div>
    <div class="row"><label style="flex:1">分类<select id="nfC">${opt(d.cats,n['分类'])}</select></label>
      <label style="flex:1">类型<select id="nfK">${opt(d.noteKinds,n['类型'],'自动判断')}</select></label></div>
    <label>内容<textarea id="nfT" rows="6" placeholder="原样粘贴，如：产品：连续签到满 7 天弹奖励弹窗，奖励金额后台可配">${esc(n['内容']||'')}</textarea></label>
    <label>链接（可空）<input type="text" id="nfU" value="${esc(n['链接']||'')}" placeholder="https://…"></label>
    <div class="row"><label style="flex:1">标题（可空）<input type="text" id="nfN" value="${esc(n['标题']||'')}" placeholder="不填就用内容的第一行"></label>
      <label style="flex:1">来自（可空）<input type="text" id="nfF" value="${esc(n['来自']||'')}" placeholder="如：产品 小王 / 服务端组"></label></div>
    <div class="row"><button class="pri" id="nfGo">保存</button><span class="mut small">⌘ + 回车 保存</span></div></div>`);
  const go=async()=>{const b={period:d.name,id:n['编号']||'',category:$('#nfC').value,kind:$('#nfK').value,
      content:$('#nfT').value,url:$('#nfU').value,title:$('#nfN').value,source:$('#nfF').value};
    try{const r=await post('/api/note',b);dlg.close();toast(r.msg.split('\n')[0]);render();askReplace(d.name,r)}catch(e){toast(e.message)}};
  $('#nfGo').onclick=go;$('#dlgB').onkeydown=e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey))go()};
  $('#nfT').focus();
}