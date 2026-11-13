// ==== 事项记事本、推动
// ---------------- 事项：记事本样式。一组条目，每条单独「推动」给 AI；分支、工程等放「补充」
const ITEM_ICON={待处理:['○','var(--mut)'],推动中:['●','var(--s1)'],已解决:['✓','var(--s3,#2f9e44)'],没解决:['✗','var(--s4)'],待确认:['?','var(--s1)']};
async function memoPage(name){
  if(!ovPeriods.length)await navRefresh();
  let v;try{v=await api('/api/task/memo?name='+enc(name))}catch(e){app.innerHTML=`<p class="mut">${esc(e.message)}</p>`;return}
  const its=v['条目'],done=its.filter(x=>x['状态']==='已解决').length;
  const sup=v['补充'].map(n=>`<li><span class="mut small">${n['类型']==='分支'?'分支':n['类型']==='链接'?'链接':''}</span> ${n['类型']==='分支'?`<b class="mono">${esc(n['内容'])}</b>`:esc(n['内容'])} <a class="mut small" data-sdel="${esc(n['编号'])}">删除</a></li>`).join('');
  const ob=(ovPeriods.find(p=>p.name===name)||{}).batch||{},srcC=ob['来源']==='anr'?'<a href="#/anr">💥 ANR / 崩溃</a> / 批次':ob['来源']==='bug'?'<a href="#/bugs">🐞 Bug</a> / 事项':'事项';
  app.innerHTML=`<div class="pagehead"><div style="min-width:0"><div class="crumb"><a href="#/">总览</a> / ${srcC}</div>
      <h1>${esc(name)} ${badge(v['状态'])}</h1>
      <div class="small mut">${esc(v['事项类型'])} · 优先级 ${esc(v['优先级']||'中')}${v['说明']?' · '+esc(v['说明']):''}　<a id="mmFull">完整页面</a>${sideOn()?`　<a id="mmNav" data-show="${ob['侧栏']===false?'1':''}">${ob['侧栏']===false?'加回侧栏':'从侧栏移除'}</a>`:''}　<a id="mmDel" style="color:var(--s4)">删除</a></div></div></div>
    <div class="card2 talk" style="margin-bottom:12px"><div class="bd">
      <textarea id="tkMsg" rows="2" placeholder="接着刚才的上下文说：如「编译校验一下」「把刚才的改动提交」。Cmd+Enter 发送">${esc(drafts['tk:'+name]||'')}</textarea>
      <div class="ctl"><button class="pri" id="tkSend">发送</button><span id="tkMode" class="small row" hidden>
        <label class="row"><input type="radio" name="tkM" value="insert" checked> 插入当前会话</label>
        <label class="row"><input type="radio" name="tkM" value="new"> 启动新会话执行</label>
        <label class="row"><input type="radio" name="tkM" value="queue"> 排队处理</label></span>
        <span id="tkTo" class="small"></span>
        <label class="small row" id="tkIntL" style="color:var(--fg)" hidden><input type="checkbox" id="tkWait"> 等这一步做完再插入</label></div>
      <div class="mut small" id="tkHint" style="margin-top:4px"></div>
      <div class="chat" id="tkMsgs"></div>
      <details id="tkActD" style="margin-top:6px"><summary class="small"><b>最近动作</b> <span class="mut" id="tkActN"></span>　<a id="tkAll">查看全部记录</a></summary><div class="act" id="tkActs"></div></details>
    </div></div>
    <div class="card2" style="margin-bottom:12px"><div class="bd"><b>补充</b>
      <ul class="memo" style="margin:6px 0 8px;padding-left:18px">
        <li><span class="mut small">工程</span> <select id="mmRepo"><option value="">${v['工程']?esc(v['工程']):'— 未选 —'}</option>${PICK_OPT}</select></li>${sup}</ul>
      <div class="row" style="gap:6px"><input type="text" id="mmSup" placeholder="补充一条：分支、工程路径、账号、注意事项…（回车）" style="flex:1"></div></div></div>
    <div class="card2"><div class="bd"><div class="row" style="justify-content:space-between"><b>条目 <span class="mut small">${its.length} 条${done?`，已解决 ${done}`:''}</span></b></div>
      <div class="row" style="gap:6px;margin:8px 0"><input type="text" id="mmAdd" placeholder="记一条…（回车）" style="flex:1"></div>
      ${its.map(x=>{const ic=ITEM_ICON[x['状态']]||ITEM_ICON['待处理'];return `<div class="mitem" style="display:flex;gap:10px;padding:8px 0;border-top:1px solid var(--soft)">
        <span title="${esc(x['状态'])}" style="color:${ic[1]};font-weight:700;width:16px">${ic[0]}</span>
        <div style="flex:1;min-width:0"><div>${x['类型']!=='记录'?`<span class="badge">${esc(x['类型'])}</span> `:''}${x['类型']==='Bug'&&x['链接']?`<a href="${esc(x['链接'])}" target="_blank" rel="noopener">${esc(x['编号'])}</a> `:''}${x['键'].startsWith('anr:')?`<a data-manr="${esc(x['编号'])}">${esc(x['标题'].replace(/^ANR · /,''))}</a>`:esc(x['标题'])}</div>
          ${x['内容']&&x['内容']!==x['标题']?`<div class="small mut">${esc(x['内容'].slice(0,200))}</div>`:''}
          ${x['结论']?`<div class="small" style="margin-top:2px">→ ${esc(x['结论'])} <span class="mut">${esc(x['结论时间']||'')}</span></div>`:''}</div>
        <div class="row" style="gap:6px;align-self:flex-start">${x['状态']==='推动中'?'<span class="small mut">推动中…</span>':`<button class="small" data-mpush="${esc(x['键'])}">推动</button>`}
          ${x['状态']==='已解决'?`<a class="small mut" data-mset="${esc(x['键'])}" data-st="待处理">重开</a>`:`<a class="small mut" data-mset="${esc(x['键'])}" data-st="已解决">标已解决</a>`}
          ${x['类型']==='记录'?`<a class="small mut" data-mdel="${esc(x['键'])}">删除</a>`:''}</div></div>`}).join('')||'<div class="mut small">还没有条目：记一条，或在说明里写清要做什么，就能点「推动」</div>'}
      <div id="pushBox"></div></div></div>
`;
  talkBind(name);
  const reload=()=>memoPage(name);
  if($('#mmNav'))$('#mmNav').onclick=()=>taskNav(name,!!$('#mmNav').dataset.show);
  const item=async(b)=>{try{const r=await post('/api/task/item',Object.assign({period:name},b));toast(r.msg);reload()}catch(e){
    if(e.need){needDlg({period:name,note:e.need['备注']||'',confirm:name},e.need)}else toast(e.message)}};
  $('#mmFull').onclick=()=>{fullView[name]=1;render()};
  $('#mmDel').onclick=()=>delPeriod(name,true);
  $('#mmAdd').onkeydown=e=>{if(e.key==='Enter'&&e.target.value.trim())item({action:'add',text:e.target.value.trim()})};
  $('#mmSup').onkeydown=async e=>{const t=e.target.value.trim();if(e.key!=='Enter'||!t)return;
    const br=/^[\w.\/-]+$/.test(t)&&/[-\/]/.test(t)&&!t.startsWith('/');
    if(t.startsWith('/')&&!/\s/.test(t))return item({action:'repo',text:t});
    try{toast((await post('/api/note',{period:name,content:t,category:'其他资料',kind:br?'分支':''})).msg);reload()}catch(err){toast(err.message)}};
  app.querySelectorAll('[data-sdel]').forEach(a=>a.onclick=async()=>{try{toast((await post('/api/note',{period:name,id:a.dataset.sdel,delete:true})).msg);reload()}catch(e){toast(e.message)}});
  const rs=$('#mmRepo');rs.onfocus=async()=>{if(rs.dataset.l)return;rs.dataset.l=1;try{const r=await api('/api/repos/choices');
    rs.innerHTML=`<option value="">${v['工程']?esc(v['工程']):'— 未选 —'}</option>`+r.items.filter(x=>x['路径']!==v['工程']).map(x=>`<option value="${esc(x['路径'])}">${esc(x['名称'])} · ${(x['端']||[]).length?esc(x['端'].join(' / ')):'端未知'}　${esc(x['分支']||'')}${x['改动']?` · ${x['改动']} 个未提交改动`:''}${x['在用'].length?` · 正用于 ${esc(x['在用'].join('、'))}`:''}</option>`).join('')+PICK_OPT}catch(e){toast(e.message)}};
  rs.onchange=()=>{if(rs.value)item({action:'repo',text:rs.value})};
  app.querySelectorAll('[data-mset]').forEach(a=>a.onclick=()=>item({action:'set',key:a.dataset.mset,status:a.dataset.st}));
  app.querySelectorAll('[data-mdel]').forEach(a=>a.onclick=()=>{if(confirm('删除这一条？'))item({action:'delete',key:a.dataset.mdel})});
  app.querySelectorAll('[data-manr]').forEach(a=>a.onclick=()=>anrDlg(a.dataset.manr,[]));
  app.querySelectorAll('[data-mpush]').forEach(b=>b.onclick=()=>{const x=its.find(i=>i['键']===b.dataset.mpush);
    openDlg('推动：'+x['标题'].slice(0,40),`<div class="form"><p class="small mut" style="margin:0">点了就是你批准处理这一条：不走开发流程，AI 自己判断怎么查、怎么改，改代码前先问你，做完把结论记在这一条下面。</p>
      <textarea id="mpN" rows="3" placeholder="补充说明（可空）：如「先确认是不是三方 SDK 的问题」"></textarea><div class="row"><button class="pri" id="mpGo">推动</button></div></div>`);
    $('#mpGo').onclick=()=>{dlg.close();item({action:'push',key:x['键'],text:$('#mpN').value.trim()})}});
  pushBox(name);
}
function pushPage(d){
  const m=d.meta,name=d.name,src=m['外部来源']||[];
  const concl=(d.materials['其他资料']||[]).filter(f=>/结论/.test(f.name));
  const ent=entries.find(x=>x.id===src[0]['插件']);
  app.innerHTML=`<div class="pagehead"><div style="min-width:0"><div class="crumb"><a href="#/">总览</a> / ${ent?`<a href="#/tool/${enc(ent.id)}">${esc(ent['图标']+' '+ent['名称'])}</a>`:'事项'}</div>
      <h1>${esc(name)} ${badge(m['状态'])}</h1>
      <div class="small mut">${src.map(x=>`${esc(x['名称']||x['插件'])} <a href="${esc(x['地址']||'#')}" target="_blank" rel="noopener" class="mono">${esc(x['编号'])}</a>`).join('　')}
        ${concl.length?'　结论：'+concl.map(f=>`<a data-read="${esc(f.path)}">${esc(f.name)}</a>`).join(' '):''}　<a id="puFull">完整页面</a>　<a id="puDel" style="color:var(--s4)">删除</a></div></div></div>
    <div class="card2 pushin"><div class="bd"><textarea id="puIn" rows="3" placeholder="想怎么推动（可空）：如「确认是不是客户端的问题；是的话把修复移到 master，先别提交」">${esc(drafts['push:'+name]||'')}</textarea>
      <div class="row" style="margin-top:6px"><button class="pri" id="puGo">分析推动</button><span class="mut small" id="puTip">点了就是你批准处理：后台 AI 实时拉取原始内容 → 在本地代码里核实 → 需要你拍板的问题出现在下面 → 改代码前先问你</span></div>
      <div id="pushBox"></div></div></div>
    ${src.map((x,i)=>`<div class="card2" style="margin-top:12px"><div class="bd"><div class="row" style="justify-content:space-between"><b>${esc(x['标题']||x['编号'])}</b><a data-rf2="${i}" class="small">刷新</a></div><div id="raw${i}"><span class="mut">原始内容拉取中…</span></div></div></div>`).join('')}`;
  app.querySelectorAll('[data-read]').forEach(a=>a.onclick=()=>readFile(a.dataset.read));
  $('#puFull').onclick=()=>{fullView[name]=1;render()};
  $('#puDel').onclick=()=>delPeriod(name,true);
  const ta=$('#puIn');ta.oninput=()=>drafts['push:'+name]=ta.value;
  $('#puGo').onclick=async()=>{const t=ta.value.trim(),b=$('#puGo');b.disabled=true;
    try{const r=await post('/api/task/push',{period:name,text:t});delete drafts['push:'+name];ta.value='';toast(r.msg);pushBox(name)}
    catch(e){if(e.need){delete drafts['push:'+name];needDlg({period:name,note:t||'网页「分析推动」',confirm:name},e.need)}else toast(e.message)}
    finally{b.disabled=false}};
  ta.onkeydown=e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey))$('#puGo').click()};
  const load=(i,fresh)=>api('/api/plugin/content?id='+enc(src[i]['插件'])+'&item='+enc(src[i]['编号'])+(fresh?'&fresh=1':''))
    .then(c=>{const el=$('#raw'+i);if(el)el.innerHTML=rawView(c)}).catch(e=>{const el=$('#raw'+i);if(el)el.innerHTML=`<span style="color:var(--s4)">${esc(e.message)}</span>`});
  src.forEach((_,i)=>load(i));
  app.querySelectorAll('[data-rf2]').forEach(a=>a.onclick=()=>{$('#raw'+a.dataset.rf2).innerHTML='<span class="mut">拉取中…</span>';load(+a.dataset.rf2,true)});
  pushBox(name);
}
async function pushBox(name){
  const box=$('#pushBox');if(!box)return;
  let v;try{v=await api('/api/dev?name='+enc(name))}catch(e){box.innerHTML='';return}
  if(!$('#pushBox'))return;
  const sig=JSON.stringify([v['会话'],v['待确认'],v['动作'].slice(-6)]);if(box.dataset.sig===sig)return;
  if(box.dataset.sig&&document.activeElement&&box.contains(document.activeElement)&&document.activeElement.matches('textarea'))return;
  const s=v['会话'],run=s&&s['状态']==='运行中',pend=v['待确认'].filter(q=>q['状态']==='待回答');
  const go=$('#puGo');if(go){go.textContent=run?'发给正在推动的 AI':'分析推动'}
  box.innerHTML=(s?`<div class="small" style="margin-top:10px">${run?`<span class="badge st-开发中">● 推动中</span> 已运行 <span data-since="${esc(s['开始时间'])}">${since(s['开始时间'])}</span> · ${esc((s['仓库']||'').split('/').pop())} ${esc(s['分支']||'')}　<a id="puStop" style="color:var(--s4)">停止</a>`
      :`<span class="badge st-${s['退出码']?'已暂停':'已完成'}">上次推动${esc(s['状态'])}</span> <span class="mut">${esc(s['结束时间']||'')}</span>`}</div>`:'')
    +pend.map(q=>`<div class="q" data-q="${esc(q['编号'])}"><div style="font-weight:600">🔔 ${esc(q['问题'])}</div>${q['背景']?`<div class="ctx md">${md(q['背景']).html}</div>`:''}
      ${q['AI建议']?`<div class="small">AI 建议：<b>${esc(q['AI建议'])}</b></div>`:''}<div class="opts">${q['选项'].map((o,i)=>`<button data-opt="${i}">${esc(o)}</button>`).join('')}${q['AI建议']?'<button data-ai="1">采用 AI 建议</button>':''}</div>
      <textarea rows="2" placeholder="你的回答（Cmd+Enter 提交）">${esc(drafts[q['编号']]||'')}</textarea><div class="row" style="margin-top:6px"><button class="pri" data-ans="1">提交回答</button></div></div>`).join('')
    +(v['动作'].length&&!$('#tkMsg')?`<details style="margin-top:8px" ${run?'open':''}><summary class="small mut">最近动作</summary><div class="act">${v['动作'].slice(-8).reverse().map(actLine).join('')}</div></details>`:'');
  box.dataset.sig=sig;
  const st=$('#puStop');if(st)st.onclick=async()=>{if(!confirm('停止正在推动的后台 AI？'))return;try{toast((await post('/api/dev/stop',{period:name})).msg);pushBox(name)}catch(e){toast(e.message)}};
  box.querySelectorAll('.q').forEach(el=>{const id=el.dataset.q,ta=el.querySelector('textarea'),q=pend.find(x=>x['编号']===id);
    ta.oninput=()=>drafts[id]=ta.value;
    el.querySelectorAll('[data-opt]').forEach(b=>b.onclick=()=>{ta.value=q['选项'][+b.dataset.opt];drafts[id]=ta.value;ta.focus()});
    const ai=el.querySelector('[data-ai]');if(ai)ai.onclick=()=>{ta.value=q['AI建议'];drafts[id]=ta.value;ta.focus()};
    const ok=async()=>{try{toast((await post('/api/answer',{period:name,id,answer:ta.value})).msg);delete drafts[id];box.dataset.sig='';pushBox(name)}catch(e){toast(e.message)}};
    el.querySelector('[data-ans]').onclick=ok;ta.onkeydown=e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey))ok()}});
}
