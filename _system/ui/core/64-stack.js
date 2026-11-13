// ==== 全栈：各端仓库、方案、拍板、开工、验收
// ---------------- 全栈：各端仓库 → AI 出影响分析和接口契约 → 你拍板（拍板 1）
let stackRepos=null;
async function stackBox(name){
  const box=$('#stackBox');if(!box)return;
  let v;try{v=await api('/api/stack?name='+enc(name))}catch(e){box.innerHTML=`<span class="mut small">${esc(e.message)}</span>`;return}
  if(!$('#stackBox')||curPeriod()!==name)return;
  if(!stackRepos){try{stackRepos=(await api('/api/stack/repos')).items}catch(_){stackRepos=[]}}
  const st=v['状态'],run=v['会话']&&v['会话']['状态']==='运行中',P=v['方案'],used=new Set(v['各端'].filter(r=>r['仓库']).map(r=>r['仓库']));
  const opts=r=>{const fit=stackRepos.filter(x=>x['端'].includes(r['端'])),rest=stackRepos.filter(x=>!x['端'].includes(r['端'])&&x['路径']!==r['仓库']);
    return `<option value="">— 不涉及 —</option>${r['仓库']?`<option value="${esc(r['仓库'])}" selected>${esc(r['显示'])}</option>`:''}
      ${fit.filter(x=>x['路径']!==r['仓库']).map(x=>`<option value="${esc(x['路径'])}">${esc(x['名称'])}　${esc(x['分支']||'')}</option>`).join('')}
      ${rest.length?`<optgroup label="其他仓库">${rest.map(x=>`<option value="${esc(x['路径'])}">${esc(x['名称'])}${x['端'].length?' ('+esc(x['端'].join('/'))+')':x['远程']?' (远程)':''}</option>`).join('')}</optgroup>`:''}
      ${PICK_OPT}<option value="__other">填写地址（本机路径或 user@主机:/路径）…</option>`};
  const need=new Set((v['全栈']||{})['涉及']||[]);
  const ends=v['各端'].map(r=>`<tr ${need.has(r['端'])&&!r['仓库']?'style="background:var(--s4b)"':''}><td><b>${esc(r['端'])}</b>${need.has(r['端'])&&!r['仓库']?'<div class="small" style="color:var(--s4)">方案要做，选仓库</div>':''}</td>
    <td><select data-send="${esc(r['端'])}" style="max-width:340px">${opts(r)}</select>${r['远程']?' <span class="badge">远程</span>':''}${r['版本库']==='svn'?' <span class="badge st-收集中" title="svn：AI 只改工作副本、不提交；审查通过、你验收后由知识库提交">svn</span>':''}</td>
    <td>${r['仓库']?`<input type="text" data-sbr="${esc(r['端'])}" value="${esc(r['分支']||'')}" placeholder="${esc(r['当前分支']?'当前 '+r['当前分支']:'开发分支')}" style="width:220px">`:''}</td>
    <td class="small mut">${r['仓库']?esc(r['流程']):''}</td></tr>`).join('');
  const W={小:'st-已完成',中:'st-收集中',大:'st-已暂停2'};
  const plan=P?`<div style="margin-top:14px"><div><b>方案</b> <span class="mut small">${esc(P['时间']||'')}</span>　${badge(st==='已拍板'?'已拍板':st==='待拍板'?'待拍板':st||'')}${v['全栈']['契约版本']?` <span class="badge st-开发中">契约 ${esc(v['全栈']['契约版本'])}</span>`:''}</div>
    <p>${esc(P['摘要']||'')}</p>
    ${(P['需求']||[]).length?`<details ${st==='待拍板'?'open':''} style="margin-bottom:10px"><summary class="small"><b>需求 ${P['需求'].length} 条</b> <span class="mut">验收标准 ${P['需求'].reduce((a,r)=>a+(r['验收']||[]).length,0)} 条${v['规格路径']?' · '+esc(v['规格路径']):''}</span></summary>
      <div class="tw"><table><tr><th style="width:80px">编号</th><th>需求与验收</th><th style="width:120px">端</th><th style="width:160px">设计</th></tr>
      ${P['需求'].map(r=>`<tr><td class="mono small">${esc(r['编号'])}</td><td><b>${esc(r['标题']||'')}</b>${r['描述']?`<div class="small mut">${esc(r['描述'])}</div>`:''}
        ${(r['验收']||[]).length?`<ul class="small" style="margin:4px 0 0;padding-left:16px">${r['验收'].map(a=>`<li>${esc(a)}</li>`).join('')}</ul>`:'<div class="small" style="color:var(--s4)">没有验收标准</div>'}</td>
        <td class="small">${esc((r['端']||[]).join('、'))}</td><td class="small">${(r['设计']||[]).length?esc(r['设计'].join('、')):'<span style="color:var(--s4)">无</span>'}</td></tr>`).join('')}</table></div></details>`:''}
    ${(()=>{const dc=P['设计对照']||{},L=(k,t)=>(dc[k]||[]).length?`<div class="small"><b>${t}（${dc[k].length}）</b><ul style="margin:2px 0 6px;padding-left:16px">${dc[k].map(x=>`<li>${esc(typeof x==='string'?x:(x['页面']||'')+' 缺 '+(x['缺']||''))}</li>`).join('')}</ul></div>`:'';
      const body=L('缺设计','需求有、设计没画')+L('设计多出','设计画了、需求没写')+L('缺状态','缺状态')+L('端不一致','各端不一致')+(dc['无法核对']?`<div class="small" style="color:var(--s4)">无法核对：${esc(dc['无法核对'])}</div>`:'');
      return P['设计对照']?`<div class="bcard" style="margin-bottom:10px;border-color:${body?'var(--s1)':'var(--line)'}"><b class="small">设计稿对照</b> ${body?'':'<span class="badge st-已完成">需求和设计一致</span>'}<div style="margin-top:4px">${body}</div></div>`:''})()}
    <div class="bcards">${(P['各端']||[]).map(x=>`<div class="bcard" style="flex:1;min-width:220px;${x['涉及']?'':'opacity:.55'}"><b>${esc(x['端'])}</b> ${x['涉及']?`<span class="badge ${W[x['工作量']]||''}">${esc(x['工作量']||'')}</span>`:'<span class="badge">不涉及</span>'}
      <div class="small mut">${esc(x['原因']||'')}</div>${(x['改动']||[]).length?`<ul class="small" style="margin:4px 0 0;padding-left:16px">${x['改动'].map(c=>`<li>${esc(c)}</li>`).join('')}</ul>`:''}
      ${x['风险']?`<div class="small" style="color:var(--s4);margin-top:4px">风险：${esc(x['风险'])}</div>`:''}</div>`).join('')}</div>
    ${(P['接口']||[]).length?`<div style="margin-top:10px"><b class="small">接口</b><div class="tw"><table><tr><th style="width:70px">方法</th><th>路径</th><th>说明</th><th style="width:60px">类型</th><th style="width:140px">调用端</th></tr>
      ${P['接口'].map(a=>`<tr><td class="mono small">${esc(a['方法'])}</td><td class="mono small">${esc(a['路径'])}</td><td class="small">${esc(a['说明']||'')}</td><td class="small">${esc(a['类型']||'')}</td><td class="small">${esc((a['调用端']||[]).join('、'))}</td></tr>`).join('')}</table></div></div>`:''}
    ${(P['数据']||[]).length?`<div style="margin-top:8px"><b class="small">数据</b><ul class="small" style="margin:2px 0;padding-left:16px">${P['数据'].map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`:''}
    ${(P['待确认']||[]).length?`<div style="margin-top:8px"><b class="small">待确认（${P['待确认'].length}）</b><ol class="small" style="margin:2px 0;padding-left:20px">${P['待确认'].map(q=>`<li>${esc(q['问题'])}${q['建议']?`<div class="mut">建议：${esc(q['建议'])}</div>`:''}</li>`).join('')}</ol></div>`:''}
    ${v['契约']?`<details style="margin-top:8px"><summary class="small"><b>接口契约</b> <span class="mut mono">${esc(v['契约路径'])}</span></summary><pre class="small" style="max-height:420px;overflow:auto">${esc(v['契约'])}</pre></details>`:''}</div>`:'';
  const SB={排队中:'st-收集中',开发中:'st-开发中',待审查:'st-已批准开发',审查中:'st-已批准开发',打回修改:'st-已暂停',审查通过:'st-已完成',要你看:'st-已暂停2',失败:'st-已暂停2',已停止:''};
  const D=v['开发']||[],canDev=['已拍板','开发中','各端完成'].includes(st);
  const CR=v['变更']||[],CRS={待评估:'st-收集中',评估中:'st-开发中',待拍板:'st-已批准开发',已纳入:'st-已完成',已驳回:''};
  const crBox=(P||CR.length)?`<div style="margin-top:14px"><div class="row" style="gap:8px"><b>变更</b><span class="mut small">做的过程中发现要改需求、要别的端配合、要改接口：提出来，AI 出增量方案，你拍板后受影响的端自动补做</span></div>
    ${CR.length?`<div class="tw" style="margin-top:6px"><table><tr><th style="width:70px">编号</th><th>内容</th><th style="width:130px">来源</th><th style="width:90px">状态</th><th style="width:60px"></th></tr>
      ${CR.slice().reverse().map(x=>`<tr><td class="mono small">${esc(x['编号'])}</td><td><b class="small">${esc(x['标题'])}</b>${x['说明']?`<div class="small mut">${esc(x['说明'])}</div>`:''}${(x['影响端']||[]).length?`<div class="small mut">可能影响：${esc(x['影响端'].join('、'))}</div>`:''}</td>
        <td class="small mut">${esc(x['来源'])}<div>${esc(x['时间'])}</div></td><td><span class="badge ${CRS[x['状态']]||''}">${esc(x['状态'])}</span>${x['纳入方案']?`<div class="small mut">方案 ${esc(x['纳入方案'])}</div>`:''}</td>
        <td>${['待评估','待拍板'].includes(x['状态'])?`<a class="small mut" data-crx="${esc(x['编号'])}">驳回</a>`:''}</td></tr>`).join('')}</table></div>`:''}
    <div class="row" style="gap:6px;margin-top:6px;flex-wrap:wrap"><input type="text" id="crT" placeholder="要变什么，如：iOS 也要兼容新的返回字段" style="flex:1;min-width:260px">
      ${['服务端','Web','iOS','Android','鸿蒙'].map(e=>`<label class="small row" style="gap:2px"><input type="checkbox" data-cre="${e}" style="width:auto;margin:0">${e}</label>`).join('')}<button id="crGo">＋ 变更</button></div></div>`:'';
  const EV=v['证据'],evBox=EV&&D.length?`<div style="margin-top:14px"><div class="row" style="gap:8px"><b>证据包</b><span class="mut small">需求 × 端：开发会话汇报的完成度、审查结论</span><span style="flex:1"></span>
      ${EV['可验收']?`<button class="pri" id="stAcc">✓ 验收（拍板 2）</button>`:''}${(v['全栈']||{})['状态']==='已验收'?'<span class="badge st-已完成">已验收</span>':''}</div>
    <div class="tw" style="margin-top:6px"><table><tr><th style="width:80px">需求</th><th>标题</th>${[...new Set(EV['需求'].flatMap(r=>Object.keys(r['端'])))].map(e=>`<th style="width:120px">${esc(e)}</th>`).join('')}</tr>
      ${(()=>{const es=[...new Set(EV['需求'].flatMap(r=>Object.keys(r['端'])))];return EV['需求'].map(r=>`<tr><td class="mono small">${esc(r['编号'])}</td><td class="small">${esc(r['标题'])} <span class="mut">验收 ${r['验收']} 条</span></td>
        ${es.map(e=>{const c=r['端'][e];if(!c)return'<td class="mut small">—</td>';const ok=c['审查']==='通过'&&String(c['完成度']).startsWith('完成');
          return `<td class="small"><span class="badge ${ok?'st-已完成':c['高']?'st-已暂停2':c['完成度']?'st-已暂停':''}">${ok?'✓ 通过':esc(c['完成度']||c['状态'])}</span>${c['问题']?`<div class="mut">问题 ${c['问题']} 个</div>`:''}</td>`}).join('')}</tr>`).join('')})()}</table></div>
    ${EV['可验收']&&!EV['全部通过']?'<div class="small" style="color:var(--s4);margin-top:4px">还有没完全通过的需求：可以提变更、重新开工某一端，或者带着问题验收</div>':''}</div>`:'';
  const devTbl=canDev?`<div style="margin-top:14px"><div class="row" style="gap:8px"><b>各端开发</b><span class="mut small">同时最多 ${v['并行上限']} 个端在跑；每端做完由独立的审查会话对照需求、契约、设计挑错，打回最多 ${v['审查轮数']} 轮</span>
      <span style="flex:1"></span>${!D.length?'<button class="pri" id="stDev">▶ 各端开工</button>':''}</div>
    ${D.length?`<div class="tw" style="margin-top:6px"><table><tr><th style="width:70px">端</th><th style="width:110px">状态</th><th>汇报</th><th>审查</th><th style="width:120px"></th></tr>
    ${D.map(x=>{const rp=x['汇报']||{},rv=x['审查']||{};return `<tr><td><b>${esc(x['端'])}</b></td>
      <td><span class="badge ${SB[x['状态']]||''}">${x['在跑']?'● ':''}${esc(x['状态'])}</span>${x['轮次']?`<div class="small mut">第 ${x['轮次']} 轮修改</div>`:''}${x['等待']?`<div class="small mut">等待：${esc(x['等待'])}</div>`:''}${x['用mock']?'<div class="small mut">按契约 mock</div>':''}${x['联调']?'<div class="small mut">联调轮</div>':''}${x['版本库']==='svn'?`<div class="small mut">${x['已提交']?(x['已提交']==='无改动'?'svn 无改动':'svn 已提交 r'+esc(x['已提交'])):'svn：验收时提交'}</div>`:`<div class="small mut">${x['已推送']?(x['已推送'].includes('@')?'已推送 '+esc(x['已推送'].split('@')[0]):esc(x['已推送'])):'验收时推送'}</div>`}</td>
      <td class="small">${rp['总结']?esc(rp['总结']):'<span class="mut">—</span>'}${rp['提交']?`<div class="mono mut">${esc(rp['提交'])}</div>`:''}${rp['证据']?`<details><summary class="mut">证据</summary>${esc(rp['证据'])}</details>`:''}
        ${x['结果']&&['失败','要你看'].includes(x['状态'])?`<div style="color:var(--s4)">${esc(x['结果'])}</div>`:''}</td>
      <td class="small">${rv['结论']?`<span class="badge ${rv['结论']==='通过'?'st-已完成':'st-已暂停'}">${esc(rv['结论'])}</span> ${esc(rv['总结']||'')}
        ${(rv['问题']||[]).length?`<details><summary class="mut">问题 ${rv['问题'].length} 个</summary><ul style="margin:2px 0;padding-left:16px">${rv['问题'].map(i=>`<li>[${esc(i['严重度']||'')}] ${esc(i['需求']||'')} ${esc(i['问题']||'')} <span class="mut mono">${esc(i['位置']||'')}</span></li>`).join('')}</ul></details>`:''}`:'<span class="mut">—</span>'}</td>
      <td>${x['在跑']||x['状态']==='排队中'?`<button class="small" data-stop="${esc(x['端'])}">停止</button>`:`<button class="small" data-redev="${esc(x['端'])}">重新开工</button>`}</td></tr>`}).join('')}</table></div>`:''}</div>`:'';
  box.innerHTML=`<div class="small mut" style="margin-bottom:8px">选这一期涉及的端和仓库（远程机器写 user@主机:/路径），AI 读资料、设计稿和代码，出需求规格、设计对照、影响分析和接口契约，你拍板一次后各端再开工。</div>
    <div class="tw"><table><tr><th style="width:70px">端</th><th>仓库</th><th style="width:240px">分支</th><th>开发流程</th></tr>${ends}</table></div>
    <div class="row" style="gap:8px;margin-top:10px;flex-wrap:wrap">
      ${run?`<span class="small"><span class="badge st-开发中">● 出方案中</span> <span class="mut">${esc(v['会话']['引擎']||'')} · ${esc(v['会话']['开始时间']||'')} 开始</span></span>`
        :st==='待拍板'?`<button class="pri" id="stOk">✓ 拍板</button><input type="text" id="stNote" placeholder="哪里不对，写意见后重出方案" style="flex:1;min-width:240px"><button id="stRe">重出方案</button>`
        :`<button class="pri" id="stGo">🧭 ${P?'重出方案':'出方案'}</button>${P?'<input type="text" id="stNote" placeholder="意见（可空）" style="flex:1;min-width:240px">':''}`}
      ${st==='出方案失败'&&v['会话']?`<span class="small" style="color:var(--s4)">上次没出来：${esc((v['会话']['结果']||'').slice(0,160))}</span>`:''}</div>
    ${devTbl}${evBox}${crBox}${plan}`;
  if($('#crGo'))$('#crGo').onclick=async()=>{const t=$('#crT').value.trim();if(!t)return toast('写一句要变什么');
    const ends=[...box.querySelectorAll('[data-cre]:checked')].map(c=>c.dataset.cre);
    try{toast((await post('/api/stack/change',{period:name,title:t,ends})).msg)}catch(e){toast(e.message)}stackBox(name)};
  box.querySelectorAll('[data-crx]').forEach(a=>a.onclick=async()=>{if(!confirm(`驳回 ${a.dataset.crx}？`))return;try{toast((await post('/api/stack/reject',{period:name,id:a.dataset.crx})).msg)}catch(e){toast(e.message)}stackBox(name)});
  if($('#stAcc'))$('#stAcc').onclick=async()=>{const pubE=(v['开发']||[]).filter(x=>x['状态']==='审查通过'&&!(x['版本库']==='svn'?x['已提交']:x['已推送'])).map(x=>x['端']+(x['版本库']==='svn'?'（svn 提交）':'（git 推送）'));
    if(!confirm('验收这一期？看过证据包，确认各端做完（这一期会标为已完成，之后照常处理 Bug）。'+(pubE.length?`\n\n验收时会把审查通过的端送上服务器：${pubE.join('、')}。svn 只提交这次改的文件，git 只推开发分支。`:'')))return;
    try{toast((await post('/api/stack/accept',{period:name})).msg)}catch(e){toast(e.message)}render()};
  if($('#stDev'))$('#stDev').onclick=async()=>{if(!confirm('各端开工？涉及的端会各起一个 AI 会话按拍板的方案开发（= 你批准开发）。'))return;
    try{toast((await post('/api/stack/dev',{period:name})).msg)}catch(e){toast(e.message)}stackBox(name)};
  box.querySelectorAll('[data-stop]').forEach(b=>b.onclick=async()=>{if(!confirm(`停止 ${b.dataset.stop}？`))return;try{toast((await post('/api/stack/stop',{period:name,end:b.dataset.stop})).msg)}catch(e){toast(e.message)}stackBox(name)});
  box.querySelectorAll('[data-redev]').forEach(b=>b.onclick=async()=>{if(!confirm(`${b.dataset.redev} 重新开工？`))return;try{toast((await post('/api/stack/dev',{period:name,end:b.dataset.redev})).msg)}catch(e){toast(e.message)}stackBox(name)});
  box.querySelectorAll('[data-send]').forEach(sel=>sel.onchange=async()=>{let repo=sel.value;
    if(repo==='__other'){repo=prompt(`${sel.dataset.send} 的仓库地址：本机写路径，远程写 user@主机:/路径`,'');if(!repo){stackBox(name);return}}
    try{toast((await post('/api/stack/end',{period:name,end:sel.dataset.send,repo})).msg);stackRepos=null}catch(e){toast(e.message)}stackBox(name)});
  box.querySelectorAll('[data-sbr]').forEach(i=>i.onchange=async()=>{const r=v['各端'].find(x=>x['端']===i.dataset.sbr);
    try{toast((await post('/api/stack/end',{period:name,end:r['端'],repo:r['仓库'],branch:i.value.trim()})).msg)}catch(e){toast(e.message)}stackBox(name)});
  const go=async()=>{try{toast((await post('/api/stack/plan',{period:name,note:$('#stNote')?$('#stNote').value.trim():''})).msg)}catch(e){toast(e.message)}stackBox(name)};
  if($('#stGo'))$('#stGo').onclick=go;if($('#stRe'))$('#stRe').onclick=go;
  if($('#stOk'))$('#stOk').onclick=async()=>{if(!confirm('拍板这份方案？接口契约会锁成一个版本，之后各端按它开发。'))return;
    try{toast((await post('/api/stack/approve',{period:name})).msg)}catch(e){toast(e.message)}stackBox(name)};
  if(run||D.some(x=>x['在跑']||['排队中','待审查','打回修改'].includes(x['状态'])))setTimeout(()=>{if(curPeriod()===name)stackBox(name)},6000);
}