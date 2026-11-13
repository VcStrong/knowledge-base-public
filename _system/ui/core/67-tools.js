// ==== 工具插件入口、删除期
// ---------------- 工具插件入口（如 Hermes 会话）：输入 → 候选 → 加入事项；事项页只展示原始内容 + 一个输入框 +「分析推动」
const fullView={};
function delPeriod(name,isTask){
  const k=isTask?'事项':'期';
  openDlg(`删除${k} · ${name}`,`<div class="form"><p style="margin:0">把这个${k}从知识库里<b>整个删掉</b>：资料、文字资料、记录、开发会话记录都不再出现在知识库里，也搜不到。</p>
    <ul class="small" style="margin:6px 0 0;padding-left:18px"><li>归到它的禅道 Bug 回到「待归纳」；关联的 ANR / 崩溃问题取消关联；它占着的手机释放</li>
    <li>目录移到系统<b>废纸篓</b>，真删错了还能从废纸篓找回；代码仓库里的代码和提交不动</li><li>后台会话在跑时不能删，先停止</li></ul>
    <label>输入${k}名称确认<input type="text" id="dpC" placeholder="${esc(name)}"></label>
    <div class="row"><button class="danger" id="dpGo">🗑 删除</button><button onclick="dlg.close()">取消</button></div></div>`);
  $('#dpGo').onclick=async()=>{try{const r=await post('/api/period/delete',{period:name,confirm:$('#dpC').value});dlg.close();toast(r.msg);location.hash='#/'}catch(e){toast(e.message)}};
}
function rawGroups(ms){   // 连续几条只有工具调用、没有文字的，合成一条折叠
  const out=[];for(const m of ms){const only=m['角色']!=='用户'&&m['角色']!=='摘要'&&!m['内容']&&(m['工具']||[]).length;
    if(only){const l=out[out.length-1];if(l&&l.steps)l.steps.push(m);else out.push({steps:[m]})}else out.push(m)}
  return out}
function rawView(c){
  const tl=t=>t['工具']?`<div><b>🔧 ${esc(t['工具'])}</b> <span class="mut">${esc(t['参数']||'')}</span>${t['结果']?`<pre>${esc(t['结果'])}</pre>`:''}</div>`:'';
  return `<div class="raw">${(c['会话']||[]).map((x,i)=>`${i?'<hr>':''}<div class="small mut">${esc(x['编号'])} · ${esc(x['来源']||'')}${x['提问人']?' · 提问人 '+esc(x['提问人']):''} · 最近 ${esc(x['时间']||'')} · ${x['消息数']||0} 条消息　<a href="${esc(x['地址'])}" target="_blank" rel="noopener">在原系统打开 ↗</a></div>
    ${rawGroups(x['消息']||[]).map(m=>m.steps?`<details class="steps"><summary>🔧 ${m.steps.length} 步工具调用（${esc(m.steps[0]['时间'].slice(11))}–${esc(m.steps[m.steps.length-1]['时间'].slice(11))}）：${esc([...new Set(m.steps.flatMap(x=>x['工具'].map(t=>t['工具'])))].join('、'))}</summary>${m.steps.flatMap(x=>x['工具']).map(tl).join('')}</details>`
      :m['角色']==='摘要'?`<details class="msg"><summary class="who">上下文压缩前的摘要 · ${esc(m['时间'])}</summary><div class="md">${md(m['内容']).html}</div></details>`
      :`<div class="msg ${m['角色']==='用户'?'u':''}"><div class="who">${m['角色']==='用户'?'👤 用户':'🤖 '+esc(m['角色'])} · ${esc(m['时间'])}</div>
        ${m['内容']?`<div class="md">${md(m['内容']).html}</div>`:''}
        ${(m['工具']||[]).length?`<details class="tools"><summary class="mut">🔧 ${m['工具'].length} 次工具调用：${esc([...new Set(m['工具'].map(t=>t['工具']))].join('、'))}</summary>${m['工具'].map(tl).join('')}</details>`:''}</div>`).join('')}`).join('')}</div>`;
}
async function toolPage(id){
  if(!entries.length){try{sideNav(await api('/api/overview'))}catch(_){}}
  const e=entries.find(x=>x.id===id);
  if(!e){app.innerHTML=`<p>没有这个入口：${esc(id)}（插件没挂载，或没有「入口」）。<a href="#/settings">去设置 →</a></p>`;return}
  let last='';try{last=sessionStorage.getItem('kb.tool.'+id)||''}catch(_){}
  app.innerHTML=`<div class="pagehead"><div><div class="crumb"><a href="#/">总览</a> / 插件入口</div><h1>${esc(e['图标'])} ${esc(e['名称'])}</h1><div class="mut">${esc(e['说明']||'')}</div></div></div>
    <div class="card2 pushin"><div class="bd"><textarea id="tIn" rows="3" placeholder="${esc(e['提示']||'')}">${esc(last)}</textarea>
      <div class="row" style="margin-top:6px"><button class="pri" id="tGo">查找</button><span class="mut small">resume=… 精确拉取；其他内容按标题、开头的提问和关键词模糊查找（Cmd+Enter）</span></div></div></div>
    <div id="tRes" style="margin-top:12px"></div>
    <div id="tItems" style="margin-top:16px"></div>`;
  toolItems(id);
  const go=async()=>{const q=$('#tIn').value.trim();if(!q)return toast('先输入内容');try{sessionStorage.setItem('kb.tool.'+id,q)}catch(_){}
    const b=$('#tGo');b.disabled=true;b.textContent='查找中…';$('#tRes').innerHTML='<span class="mut">查找中…</span>';
    try{const r=await api('/api/plugin/resolve?id='+enc(id)+'&q='+enc(q));showCands(id,r.items)}catch(err){$('#tRes').innerHTML=`<span style="color:var(--s4)">${esc(err.message)}</span>`}
    finally{b.disabled=false;b.textContent='查找'}};
  $('#tGo').onclick=go;$('#tIn').onkeydown=ev=>{if(ev.key==='Enter'&&(ev.metaKey||ev.ctrlKey))go()};
  if(last&&/resume=/.test(last))go();
}
async function toolItems(id){
  let d;try{d=await api('/api/overview')}catch(_){return}
  ovPeriods=d.periods;const box=$('#tItems');if(!box)return;
  const ts=d.periods.filter(p=>(p.plugins||[]).includes(id)),open=ts.filter(p=>p.status!=='已完成'),done=ts.filter(p=>p.status==='已完成');
  const row=p=>`<a class="cand" href="#/p/${enc(p.name)}" style="display:block;color:inherit"><div class="row" style="justify-content:space-between;align-items:baseline">
      <b>${esc(p.name)}</b><span>${p.pendingQ?`<span class="badge st-已批准开发">🔔 ${p.pendingQ} 个待你确认</span> `:''}${p.running?'<span class="badge st-开发中">● 推动中</span> ':''}${badge(p.status)}</span></div>
    <div class="small mut">${esc((p.srcTitles||[]).join('；'))}${p.lastLog?' · 最近：'+esc((p.lastLog.time||'')+' '+(p.lastLog.action||'')+' '+(p.lastLog.content||'').slice(0,60)):''}</div></a>`;
  box.innerHTML=`<h3 style="margin:0 0 4px;font-size:15px">待解决（${open.length}）</h3>${open.map(row).join('')||'<div class="mut small">还没有。上面找到会话后点「加入事项」。</div>'}
    ${done.length?`<details style="margin-top:10px"><summary class="small mut">已完成（${done.length}）</summary>${done.map(row).join('')}</details>`:''}`;
}
function showCands(id,items){
  if(!items.length){$('#tRes').innerHTML='<span class="mut">没找到。换几个关键词试试，或直接给 resume=会话编号。</span>';return}
  $('#tRes').innerHTML=`<div class="small mut">找到 ${items.length} 个，最像的在前：</div>`+items.map((x,i)=>`<div class="cand"><div class="row" style="justify-content:space-between;align-items:baseline">
      <b>${esc(x['标题'])}</b><span class="small mut mono">${esc(x['编号'])}</span></div>
    ${x['错误']?'':`<div class="small mut">${esc([x['来源'],x['提问人']&&'提问人 '+x['提问人'],x['时间'],x['消息数']+' 条消息',x['匹配']].filter(Boolean).join(' · '))}</div>
    ${x['摘要']?`<div class="small" style="margin-top:2px">${esc(x['摘要'])}</div>`:''}
    <div class="row" style="margin-top:6px"><button data-cv="${i}">预览</button><button class="pri" data-ct="${i}">加入事项</button>
      ${(x['事项']||[]).length?`<span class="small">已在：${x['事项'].map(t=>`<a href="#/p/${enc(t)}">${esc(t)}</a>`).join('、')}</span>`:''}</div>`}</div>`).join('');
  $('#tRes').querySelectorAll('[data-cv]').forEach(b=>b.onclick=async()=>{const x=items[+b.dataset.cv];
    openDlg(x['标题'],'<span class="mut">拉取中…</span>');
    try{const c=await api('/api/plugin/content?id='+enc(id)+'&item='+enc(x['编号']));$('#dlgB').innerHTML=rawView(c)}catch(e){$('#dlgB').innerHTML=esc(e.message)}});
  $('#tRes').querySelectorAll('[data-ct]').forEach(b=>b.onclick=()=>{const x=items[+b.dataset.ct];
    openDlg('加入事项',`<div class="form"><div class="small mut">知识库只记来源（编号、标题、地址），原始内容在事项页实时拉取。</div>
      <label>加入到<select id="ctT"><option value="＋新建">＋ 新建事项</option>${taskNames.map(t=>`<option>${esc(t)}</option>`).join('')}</select></label>
      <label id="ctNl">新事项名称<input type="text" id="ctN" value="${esc(x['标题'])}"></label>
      <div class="row"><button class="pri" id="ctGo">加入</button></div></div>`);
    $('#ctT').onchange=()=>$('#ctNl').hidden=$('#ctT').value!=='＋新建';
    $('#ctGo').onclick=async()=>{try{const r=await post('/api/plugin/task',{id,item:x['编号'],task:$('#ctT').value,name:$('#ctN').value.trim(),title:x['标题'],url:''});
      dlg.close();toast(r.msg);location.hash='#/p/'+enc(r.name)}catch(e){toast(e.message)}}});
}