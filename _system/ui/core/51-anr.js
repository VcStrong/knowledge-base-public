// ==== ANR / 崩溃页：自建问题、批次、详情
let anrF={v:'待处理',q:''};try{anrF=Object.assign(anrF,JSON.parse(localStorage.getItem('kb.anrF')||'{}'))}catch(_){}
const ANR_COLS=[['原因','原因'],['详情','类型 / 版本 / 首次 / 最近']];
let anrCols=[];try{anrCols=JSON.parse(localStorage.getItem('kb.anrCols')||'[]')}catch(_){}
const ANR_K={'ANR':'st-开发中','Java崩溃':'st-已暂停2','Native崩溃':'st-已暂停2'};
let anrIndex={};
// 自建问题 / 归档 mapping：日志可粘贴内容或选文件；mapping 可选本地文件或填 URL 自动下载
async function anrStage(f){const r=await api('/api/anr/stage',{method:'POST',headers:{'X-Filename':enc(f.name)},body:f});return r.id}
function anrNewDlg(tasks,mapOnly){
  const mapBox=`<div class="small mut" style="margin-top:4px">mapping <span class="row" style="display:inline-flex;gap:10px;color:var(--fg)">${mapOnly?'':'<label style="display:inline-flex;flex-direction:row;align-items:center;gap:4px;margin:0"><input type="radio" name="anM" value="" checked> 不带</label>'}<label style="display:inline-flex;flex-direction:row;align-items:center;gap:4px;margin:0"><input type="radio" name="anM" value="file" ${mapOnly?'checked':''}> 本地文件</label><label style="display:inline-flex;flex-direction:row;align-items:center;gap:4px;margin:0"><input type="radio" name="anM" value="url"> URL 自动下载</label></span></div>
    <div id="anMF" ${mapOnly?'':'hidden'}><input type="file" id="anMap"></div>
    <div id="anMU" hidden><input type="text" id="anMapU" placeholder="mapping.txt / zip / gz 的下载地址，如 Jenkins 构建产物；要登录的站点先 kb login 存账号" style="width:100%"></div>`;
  openDlg(mapOnly?'归档 mapping':'＋ 自建问题',`<div class="form">
    ${mapOnly?'':`<label>标题（可空：认出堆栈时用堆栈里的标题；认不出时必填）<input type="text" id="anT" placeholder="如：送礼面板快速连点后崩溃"></label>
    <label>日志内容（粘贴复制的崩溃日志、traces、tombstone、logcat 片段）<textarea id="anX" rows="8" class="mono" style="font-size:12px" placeholder="FATAL EXCEPTION: main&#10;Process: com.xxx, PID: 1234&#10;java.lang.NullPointerException: ...&#10;    at com.xxx.Foo.bar(Foo.java:42)"></textarea></label>
    <label>日志文件（可多选，可空）<input type="file" id="anF" multiple></label>`}
    <div class="row" style="gap:10px;flex-wrap:wrap"><label class="small mut">版本 <input type="text" id="anV" value="${esc($('#arV')?$('#arV').value.trim():'')}" placeholder="可空，如 5.32.1" style="width:170px"></label>
      ${mapOnly?'':`<label class="small mut">来源 <input type="text" id="anS" value="${esc($('#arS')?$('#arS').value.trim():'')}" placeholder="如 用户反馈 vv号 123" style="width:190px"></label>
      <label class="small mut">事项 <select id="anK"><option value="">— 不关联 —</option><option value="＋新建">＋ 新建事项</option>${tasks.map(t=>`<option>${esc(t)}</option>`).join('')}</select></label>`}</div>
    ${mapOnly?'':`<div id="anTk" hidden class="row" style="gap:10px;flex-wrap:wrap"><label class="small mut">事项名 <input type="text" id="anTN" placeholder="可空，自动取" style="width:200px"></label>
      <label class="small mut">分支 <input type="text" id="anBr" placeholder="如 feature-xxx-stable" style="width:240px"></label>
      <label class="small mut">代码仓库 <select id="anRp"><option value="">— 开始处理时再选 —</option>${PICK_OPT}</select></label></div>
      <div class="small mut" id="anRpH" hidden>一次粘贴的几段日志都归到这一个事项；建好后到事项页点「▶ 开始开发」</div>`}
    ${mapBox}
    ${mapOnly?'':'<label>备注（可空）<input type="text" id="anN" placeholder="如：用户反馈进房卡顿，版本 5.2.1，小米 13"></label>'}
    <div class="row"><button class="pri" id="anGo">${mapOnly?'归档':'建问题'}</button><span class="mut small">${mapOnly?'归档后会用它还原这个版本的样本；不写版本时存成「未标版本-时间」，给样本补上这个版本名即可还原':'认得出堆栈的按签名合并到已有问题、累计次数；版本、来源都可空，带 mapping 又没写版本时先从日志里认，认不出就和这次的日志共用一个版本名'}</span></div></div>`);
  if($('#anK'))$('#anK').onchange=async()=>{const nw=$('#anK').value==='＋新建';$('#anTk').hidden=!nw;$('#anRpH').hidden=!nw;
    if(nw&&$('#anRp').options.length<2){try{const r=await api('/api/repos/choices');
      $('#anRp').innerHTML='<option value="">— 开始处理时再选 —</option>'+r.items.map(x=>`<option value="${esc(x['路径'])}">${esc(x['名称'])}　${esc(x['分支']||'')}${x['改动']?` · ${x['改动']} 个未提交改动`:''}${x['在用'].length?` · 正用于 ${esc(x['在用'].join('、'))}`:''}</option>`).join('')+PICK_OPT}catch(e){toast(e.message)}}};
  document.querySelectorAll('input[name=anM]').forEach(r=>r.onchange=()=>{const v=document.querySelector('input[name=anM]:checked').value;$('#anMF').hidden=v!=='file';$('#anMU').hidden=v!=='url'});
  $('#anGo').onclick=async()=>{const b=$('#anGo'),t=b.textContent;
    const mm=document.querySelector('input[name=anM]:checked').value,ver=$('#anV').value.trim();
    const mf=mm==='file'?$('#anMap').files[0]:null,mu=mm==='url'?$('#anMapU').value.trim():'';
    if(mm==='file'&&!mf)return toast('选一下 mapping 文件');if(mm==='url'&&!mu)return toast('填一下 mapping 地址');
    b.disabled=true;b.textContent=mu?'下载 mapping 中…':'处理中…';
    try{let r;
      if(mapOnly){r=mu?await post('/api/anr/mapping-url',{version:ver,url:mu})
        :await api('/api/anr/upload',{method:'POST',headers:{'X-Kind':'mapping','X-Version':enc(ver),'X-Filename':enc(mf.name)},body:mf})}
      else{const files=[];for(const f of $('#anF').files)files.push(await anrStage(f));
        r=await post('/api/anr/create',{title:$('#anT').value.trim(),text:$('#anX').value,files,version:ver,source:$('#anS').value.trim(),
          task:$('#anK').value,note:$('#anN').value.trim(),mappingUrl:mu,mappingFile:mf?await anrStage(mf):'',
          taskName:$('#anTN').value.trim(),branch:$('#anBr').value.trim(),repo:$('#anRp').value})}
      openDlg(mapOnly?'已归档 mapping':'已建问题',`<pre style="white-space:pre-wrap">${esc(r.msg)}</pre>`);anrPage()}
    catch(e){toast(e.message);b.disabled=false;b.textContent=t}};
}
async function anrPage(){
  const [d]=await Promise.all([api('/api/anr'),navRefresh()]);
  d.problems.forEach(p=>anrIndex[p['编号']]=p);
  const bs=ovPeriods.filter(p=>p.kind==='事项'&&(p.batch||{})['来源']==='anr'),side=sideOn(),bOn=side?bs.filter(p=>p.batch['侧栏']):bs,bOff=side?bs.filter(p=>!p.batch['侧栏']):[];
  const bCard=p=>{const b=p.batch;return `<div class="bcard"><a href="#/p/${enc(p.name)}"><b>${esc(batchName(p.name))}</b></a> ${badge(p.status)}
    <div class="small mut">已处理 ${b['已处理']}/${b['总数']}${b['待确认']?` · 待确认 ${b['待确认']}`:''}${p.running?' · AI 处理中':''}</div>
    ${side?`<a class="small mut" data-bnav="${esc(p.name)}" data-show="${b['侧栏']?'':'1'}">${b['侧栏']?'从侧栏移除':'加回侧栏'}</a>`:''}</div>`};
  const todo=p=>p['状态']!=='忽略'&&(!p['事项']||p['修复后又出现']);
  const V={'待处理':todo,'已关联':p=>p['状态']!=='忽略'&&p['事项'],'忽略':p=>p['状态']==='忽略','全部':()=>true};
  const q=anrF.q.trim().toLowerCase();
  const list=d.problems.filter(V[anrF.v]||todo).filter(p=>!q||JSON.stringify(p).toLowerCase().includes(q));
  const on=k=>anrCols.includes(k);
  const taskOpts=p=>`<select data-alink="${p['编号']}"><option value="">— 未关联 —</option><option value="＋新建">＋ 新建批次</option>${d.tasks.map(t=>`<option value="${esc(t)}" ${t===p['事项']?'selected':''}>${esc(batchName(t))}</option>`).join('')}</select>`;
  app.innerHTML=`<div class="pagehead"><div><h1>💥 ANR / 崩溃</h1><p class="mut">把 traces、tombstone、崩溃日志、Bugly 导出、bugreport.zip 拖进来：按关键堆栈合并成「问题」并累计次数；有对应版本的 mapping 时自动还原混淆。勾选要处理的问题放进一个「批次」，到批次里逐条推动给 AI。接入了崩溃平台（Sentry、Firebase Crashlytics、Bugly，在「🐞 Bug → ＋ 接入平台」）的，问题会自动同步进来，次数取平台上的累计值。</p></div></div>
  ${bs.length?`<div class="card2" style="margin-bottom:12px"><div class="bd"><b>批次</b> <span class="mut small">挑出来交给 AI 处理的一组问题${side?'；处理完可以从侧栏移除，有新问题会自动回来':''}</span>
    <div class="bcards">${bOn.map(bCard).join('')||`<span class="mut small">${side?'侧栏里没有批次':'没有批次'}</span>`}</div>
    ${bOff.length?`<details style="margin-top:6px"><summary class="small mut">已移出侧栏 ${bOff.length} 个</summary><div class="bcards">${bOff.map(bCard).join('')}</div></details>`:''}</div></div>`:''}
  <div class="card2" style="margin-bottom:12px"><div class="bd">
    <div class="row" style="flex-wrap:wrap;gap:10px;margin-bottom:8px"><label class="small mut">版本 <input type="text" id="arV" placeholder="日志里认不出时填，如 5.32.1" style="width:180px"></label>
      <label class="small mut">来源 <input type="text" id="arS" placeholder="如 用户反馈 vv号 123 / Bugly" style="width:200px"></label></div>
    <div class="row" style="gap:8px;align-items:stretch"><div class="drop" id="arDrop" style="flex:1;margin:0">拖日志文件到这里，或点击选择（可多选；zip 会取出 anr/、tombstones/ 和日志）</div>
      <button class="pri" id="arNew" title="粘贴复制的崩溃日志、或选日志文件，可同时带上 mapping（本地文件或 URL）；认不出堆栈的按标题建">＋ 自建问题</button></div><input type="file" id="arPick" multiple hidden>
    <div class="row small mut" style="margin-top:8px;flex-wrap:wrap;gap:8px">mapping：${d.mappings.length?d.mappings.map(v=>`<span class="badge">${esc(v)}</span>`).join(' '):'还没有'}
      <button class="small" id="arMap">＋ 归档 mapping</button><span>（按版本存，归档后会重算这个版本的样本）</span></div></div></div>
  <div class="fchips">${Object.keys(V).map(k=>`<button class="fchip ${k===anrF.v?'on':''}" data-av="${k}">${k}<b>${d.problems.filter(V[k]).length}</b></button>`).join('')}
    <input type="text" id="arQ" value="${esc(anrF.q)}" placeholder="筛选：类名、方法、原因…" style="margin-left:auto;width:220px"></div>
  <div class="row small mut" style="margin-bottom:6px;gap:10px">显示${ANR_COLS.map(([k,t])=>`<label class="row" style="gap:3px;color:var(--fg)"><input type="checkbox" data-acol="${k}" ${on(k)?'checked':''}>${t}</label>`).join('')}</div>
  ${list.length?`<div class="row small" id="arBulk" hidden style="gap:8px;margin-bottom:6px;padding:6px 10px;background:var(--soft);border-radius:8px">已选 <b id="arBN"></b> 个，放进
    <select id="arBT"><option value="＋新建">＋ 新批次</option>${d.tasks.map(t=>`<option value="${esc(t)}">${esc(batchName(t))}</option>`).join('')}</select><button class="pri small" id="arBGo">放进去</button><a class="mut" id="arBX">取消</a></div>
  <div class="tw"><table><tr><th style="width:28px"><input type="checkbox" id="arAll" title="全选"></th><th style="width:84px">编号</th><th>问题</th><th style="width:70px">次数</th><th style="width:240px">批次</th></tr>${list.map(p=>`<tr>
    <td><input type="checkbox" data-asel="${p['编号']}"></td>
    <td><a data-ashow="${p['编号']}" class="mono">${p['编号']}</a></td>
    <td><a data-ashow="${p['编号']}"><b>${esc(p['标题'])}</b></a>${(p['平台']||[]).map(x=>` <a href="${esc(x['链接'])}" target="_blank" rel="noopener" class="badge" title="${esc(x['来源'])} 上累计 ${esc(x['次数'])} 次，影响 ${esc(x['用户数'])} 人">${esc(x['来源'])} ↗</a>`).join('')}${p['已还原']===false?' <span class="badge st-已暂停2" title="缺 mapping 或版本不明">未还原</span>':''}${p['状态']==='忽略'?' <span class="badge">忽略</span>':''}
      ${on('原因')&&p['原因']?`<div class="small">${esc(p['原因'])}</div>`:''}
      ${on('详情')?`<div class="mut small"><span class="badge ${ANR_K[p['类型']]||''}">${esc(p['类型'])}</span> 版本 ${esc(p['版本'].join('、')||'不明')} · 首次 ${esc(p['首次'].slice(0,16))} · 最近 ${esc(p['最近'].slice(0,16))}</div>`:''}</td>
    <td><b>${p['次数']}</b>${p['样本数']!==p['次数']?`<div class="mut small">${p['样本数']} 份日志</div>`:''}</td>
    <td>${p['事项']?`<a href="#/p/${enc(p['事项'])}">${esc(batchName(p['事项']))}</a> ${badge(p['事项状态'])}${p['修复后又出现']?`<div class="small" style="color:var(--s4)">⚠ 完成后又出现 ${p['修复后又出现']} 次</div>`:''}`:taskOpts(p)}</td></tr>`).join('')}</table></div>`
    :`<p class="mut">${d.problems.length?'这里没有问题。':'还没有 ANR / 崩溃日志。'}</p>`}`;
  const save=()=>{try{localStorage.setItem('kb.anrF',JSON.stringify(anrF))}catch(_){}};
  app.querySelectorAll('[data-av]').forEach(b=>b.onclick=()=>{anrF.v=b.dataset.av;save();anrPage()});
  $('#arQ').onchange=()=>{anrF.q=$('#arQ').value;save();anrPage()};
  app.querySelectorAll('[data-acol]').forEach(c=>c.onchange=()=>{const k=c.dataset.acol;anrCols=c.checked?[...new Set([...anrCols,k])]:anrCols.filter(x=>x!==k);try{localStorage.setItem('kb.anrCols',JSON.stringify(anrCols))}catch(_){}anrPage()});
  app.querySelectorAll('[data-ashow]').forEach(a=>a.onclick=()=>anrDlg(a.dataset.ashow,d.tasks));
  app.querySelectorAll('[data-alink]').forEach(sel=>sel.onchange=()=>anrLink(sel.dataset.alink,{task:sel.value}));
  app.querySelectorAll('[data-bnav]').forEach(a=>a.onclick=()=>taskNav(a.dataset.bnav,!!a.dataset.show));
  const sels=()=>[...app.querySelectorAll('[data-asel]:checked')].map(c=>c.dataset.asel);
  const bulk=()=>{const n=sels().length;if($('#arBulk')){$('#arBulk').hidden=!n;$('#arBN').textContent=n}};
  app.querySelectorAll('[data-asel]').forEach(c=>c.onchange=bulk);
  if($('#arAll')){$('#arAll').onchange=()=>{app.querySelectorAll('[data-asel]').forEach(c=>c.checked=$('#arAll').checked);bulk()};
    $('#arBX').onclick=()=>{app.querySelectorAll('[data-asel],#arAll').forEach(c=>c.checked=false);bulk()};
    $('#arBGo').onclick=async()=>{const ids=sels(),t=$('#arBT').value;let name='';
      if(t==='＋新建'){name=prompt('新批次叫什么？',`ANR 第${bs.length+1}批`);if(name===null)return}
      try{const r=await post('/api/anr/batch',{ids,task:t,name});toast(r.msg);anrPage()}catch(e){toast(e.message)}}}
  const send=async(files,kind,ver)=>{for(const f of files){toast(`上传 ${f.name}…`);
    try{const r=await api('/api/anr/upload',{method:'POST',headers:{'X-Kind':kind,'X-Version':enc(ver||''),'X-Source':enc($('#arS').value.trim()),'X-Filename':enc(f.name)},body:f});
      openDlg(kind==='mapping'?'已归档 mapping':`已归档 ${f.name}`,`<pre style="white-space:pre-wrap">${esc(r.msg)}</pre>`)}catch(e){toast(e.message)}}
    anrPage()};
  const z=$('#arDrop'),pick=$('#arPick');
  z.onclick=()=>pick.click();pick.onchange=()=>send([...pick.files],'log',$('#arV').value.trim());
  z.ondragover=e=>{e.preventDefault();z.classList.add('over')};z.ondragleave=()=>z.classList.remove('over');
  z.ondrop=e=>{e.preventDefault();z.classList.remove('over');send([...e.dataTransfer.files],'log',$('#arV').value.trim())};
  $('#arMap').onclick=()=>anrNewDlg(d.tasks,true);
  $('#arNew').onclick=()=>anrNewDlg(d.tasks,false);
}
async function anrLink(id,b){
  if(b.task==='＋新建'&&!confirm('新建一个「ANR/崩溃」事项，并把这个问题关联进去？'))return anrPage();
  try{const r=await post('/api/anr/link',Object.assign({id},b));toast(r.msg);if(dlg.open)dlg.close();render()}catch(e){toast(e.message)}}
function anrDlg(id,tasks){
  const p=anrIndex[id];if(!p)return;
  openDlg(`${p['类型']} ${p['编号']}`,`<div style="max-width:900px">
    <p><b>${esc(p['标题'])}</b></p>
    <div class="small mut">${p['次数']} 次（${p['样本数']} 份日志）· 版本 ${esc(p['版本'].join('、')||'不明')} · 首次 ${esc(p['首次'])} · 最近 ${esc(p['最近'])}</div>
    ${p['原因']?`<p>原因：${esc(p['原因'])}</p>`:''}
    ${p['已还原']===false?`<div class="notice"><span>堆栈是混淆的：${p['版本'].length?'这个版本还没有 mapping，在 ANR 页归档后自动还原。':'认不出版本，补上版本号后会用对应的 mapping 还原。'}</span>
      <input type="text" id="adV" placeholder="版本号" style="width:120px"><button id="adVGo">补版本号</button>${p['版本'].length?`<button id="adAuto" title="到各期的构建（如 Jenkins）里找同版本构建的 mapping，归档后自动还原">从构建找 mapping</button>`:''}</div>`:''}
    <h3 style="margin:12px 0 4px">关键堆栈 <span class="small mut" style="font-weight:400">最近一次${p['已还原']?'，已用 mapping 还原':''}；完整内容看样本原文</span></h3>
    <pre class="mono" style="font-size:12px;overflow:auto;max-height:360px">${esc(p['关键堆栈'].join('\n'))}</pre>
    <h3 style="margin:12px 0 4px">样本</h3>
    ${p['样本'].slice(0,20).map(s=>`<div class="small row" style="gap:8px"><a href="/file?path=${enc(s['路径'])}" target="_blank" class="mono">${esc(s['编号'])}</a><span>${esc(s['发生时间']||s['加入时间'])}</span><span class="mut">版本 ${esc(s['版本']||'不明')}${s['次数']>1?' ×'+s['次数']:''}${s['来源']?' · '+esc(s['来源']):''} · ${esc(s['原文件'])}</span><a data-adel="${esc(s['编号'])}" class="mut" style="margin-left:auto">删除</a></div>`).join('')}
    <div class="form" style="margin-top:14px"><label class="small mut">事项 <select id="adT"><option value="">— 未关联 —</option><option value="＋新建">＋ 新建事项</option>${tasks.map(t=>`<option ${t===p['事项']?'selected':''}>${esc(t)}</option>`).join('')}</select></label>
      <textarea id="adN" rows="2" placeholder="备注（如：系统问题、已知原因）">${esc(p['备注']||'')}</textarea>
      <div class="row"><button class="pri" id="adGo">保存</button><button id="adIgn">${p['状态']==='忽略'?'取消忽略':'忽略'}</button>${p['事项']?`<a href="#/p/${enc(p['事项'])}" onclick="dlg.close()" style="margin-left:auto">打开事项 →</a>`:''}</div></div></div>`);
  $('#adGo').onclick=()=>{const b={note:$('#adN').value.trim()};if($('#adT').value!==(p['事项']||''))b.task=$('#adT').value;anrLink(id,b)};
  $('#adIgn').onclick=()=>anrLink(id,{status:p['状态']==='忽略'?'':'忽略'});
  if($('#adVGo'))$('#adVGo').onclick=()=>{const v=$('#adV').value.trim();if(v)anrLink(id,{version:v})};
  if($('#adAuto'))$('#adAuto').onclick=async()=>{const b=$('#adAuto');b.disabled=true;b.textContent='查找中…';
    try{let msg='';for(const v of p['版本']){const r=await post('/api/anr/automap',{version:v});msg+=r.msg+'\n'}
      openDlg('从构建找 mapping',`<pre style="white-space:pre-wrap">${esc(msg)}</pre>`);render()}catch(e){toast(e.message);b.disabled=false;b.textContent='从构建找 mapping'}};
  $('#dlgB').querySelectorAll('[data-adel]').forEach(a=>a.onclick=async()=>{if(!confirm('删除这份样本（不是这个问题的日志）？'))return;
    try{const r=await post('/api/anr/delete',{sample:a.dataset.adel});toast(r.msg);dlg.close();render()}catch(e){toast(e.message)}});
}
