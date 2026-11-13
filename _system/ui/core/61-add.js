// ==== 添加对话框、通用对话框、看文件、搜索
// ---------------- 模糊添加：随手粘贴，后台 Claude 判断归属并导入
const addRec=x=>{const run=x['状态']==='运行中';
  return `<div class="arec"><div class="row small"><b>${run?'⏳ 整理中':x['出错']||x['退出码']?'❌ 出错':'✅ 已完成'}</b>
    <span class="mut">${esc(x['开始时间'])}${x['期']?' · 指定：'+esc(x['期']):''}${run?' · 已运行 <span data-since="'+esc(x['开始时间'])+'">'+since(x['开始时间'])+'</span>':''}</span></div>
    <div class="in">${esc(x['输入'])}</div>
    ${run?`<div class="act">${(x['动作']||[]).map(actLine).join('')||'<div class="mut">启动中…</div>'}</div>`
      :`<div class="res">${x['结果']?md(x['结果']).html:'<span class="mut">没有返回结果，可能被中断了</span>'}</div>`}</div>`};
async function addList(){const b=$('#adList');if(!b)return;
  try{const xs=(await api('/api/adds')).items;b.innerHTML=xs.map(addRec).join('')||'<p class="mut small">还没有记录</p>'}catch(e){b.textContent=e.message}}
async function addDlg(tab){
  let ps=[],ov={};try{ov=await api('/api/overview');ps=ov.periods.map(p=>p.name)}catch(_){}
  const cur=curPeriod();
  openDlg('添加',`<div class="row" style="margin-bottom:10px;gap:6px"><button id="tabAdd">✨ 模糊添加</button><button id="tabNew">＋ 新建一期</button><button id="tabTask">＋ 新建事项</button></div>
    <div id="paneTask" class="form" style="display:none">${taskForm({kinds:ov.taskKinds||[],pris:ov.taskPri||['高','中','低']})}
      <div class="row"><button class="pri" id="tkGo">创建</button><span class="mut small">事项 = 不是产品需求、但要推动的工作；开始处理同样要你批准</span></div></div>
    <div id="paneNew" style="display:none;gap:8px"><input type="text" id="nN" placeholder="期名，如 2026-11-签到活动v2"><textarea id="nS" rows="3" placeholder="简介（可空）"></textarea>
      <div class="row"><button class="pri" id="nGo">创建</button><span class="mut small">只想把资料放进去、不确定放哪一期时，用「模糊添加」，对不上会自动新建</span></div></div>
    <div id="paneAdd" style="display:grid;gap:8px">
    <textarea id="adT" rows="6" placeholder="随手粘贴，Claude 会按知识库规则判断放进哪一期 / 事项、怎么导入。例如：&#10;https://confluence.example.com/pages/viewpage.action?pageId=67990565 编号8&#10;产品说：连续签到满 7 天才弹奖励弹窗&#10;测试账号 13800000000 / 密码 xxx（会存进基础知识库，密码只进钥匙串）"></textarea>
    <div class="row"><label>放进<select id="adP"><option value="">自动判断（对不上会新建一期）</option>${ps.map(n=>`<option ${n===cur?'selected':''}>${esc(n)}</option>`).join('')}</select></label>
      <button class="pri" id="adGo">交给 Claude 添加</button><span class="mut small">⌘ + 回车 提交 · 后台运行，可关掉弹窗</span></div>
    <h3 style="margin:8px 0 0">最近记录</h3><div id="adList"><span class="mut small">加载中…</span></div></div>`);
  const show=t=>{$('#paneAdd').style.display=t==='add'?'grid':'none';$('#paneNew').style.display=t==='new'?'grid':'none';$('#paneTask').style.display=t==='task'?'grid':'none';
    $('#tabAdd').classList.toggle('pri',t==='add');$('#tabNew').classList.toggle('pri',t==='new');$('#tabTask').classList.toggle('pri',t==='task');({add:$('#adT'),new:$('#nN'),task:$('#tkN')})[t].focus()};
  $('#tabAdd').onclick=()=>show('add');$('#tabNew').onclick=()=>show('new');$('#tabTask').onclick=()=>show('task');
  $('#tkGo').onclick=async()=>{try{const n=$('#tkN').value.trim();if(!n)return toast('请填事项名');
    const r=await post('/api/task',{name:n,kind:$('#tkK').value,priority:$('#tkP').value,source:$('#tkF').value.trim(),summary:$('#tkS').value.trim()});
    dlg.close();toast('已创建事项');location.hash='#/p/'+enc(r.name)}catch(e){toast(e.message)}};
  $('#nGo').onclick=async()=>{try{const n=$('#nN').value.trim();await post('/api/new',{name:n,summary:$('#nS').value});dlg.close();location.hash='#/p/'+enc(n)}catch(e){toast(e.message)}};
  $('#nN').onkeydown=e=>{if(e.key==='Enter')$('#nGo').click()};
  const go=async()=>{const t=$('#adT').value.trim();if(!t)return toast('请粘贴要添加的内容');
    try{const p=$('#adP').value;await post('/api/chat/ask',{text:(p?`放进「${p}」：`:'')+t,page:'添加'});$('#adT').value='';dlg.close();askOpen(true)}catch(e){toast(e.message)}};
  $('#adGo').onclick=go;$('#adT').onkeydown=e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey))go()};
  show(tab||'add');addList();
}
function openDlg(t,h){$('#dlgT').textContent=t;$('#dlgB').innerHTML=h;$('#dlgB').onkeydown=null;dlg.showModal()}
async function readFile(p,start){
  try{const r=await api('/api/read?path='+enc(p)+'&start='+(start||1));openDlg(p.split('/').pop(),`<pre>${esc(r.text)}</pre>`)}catch(e){toast(e.message)}
}
function showImg(p){
  const el=[...document.querySelectorAll('[data-img]')].find(x=>x.dataset.img===p);
  const note=el?.dataset.note||el?.querySelector('div')?.title||'';
  openDlg(p.split('/').pop(),`${note?`<p style="white-space:pre-wrap">${esc(note)}</p>`:'<p class="mut">暂无说明，可让 Claude「把设计图都看一遍补上说明」</p>'}<img src="${fileUrl(p)}">`);
}

async function search(q,scope){
  if($('#q'))$('#q').value=q;if($('#scope'))$('#scope').value=scope||'all';
  app.innerHTML='<p class="mut">搜索中…</p>';
  try{
    const r=await api(`/api/search?q=${enc(q)}&scope=${enc(scope||'all')}`);
    app.innerHTML=`<h1>「${esc(q)}」</h1><p class="mut">${r.hits.length} 条${r.hits.length?'（匹配'+esc(r.mode)+'）':''}</p>`+
      r.hits.map(h=>`<div class="hit"><div class="row"><span class="badge ${h.kind==='code'?'st-开发中':'st-收集中'}">${h.kind==='code'?'代码 · '+esc(h.repo):esc(h.period)+' · '+esc(h.cat||'其他')}</span>
      <a data-p="${esc(h.path)}" data-l="${h.line}">${esc(h.path.split('/').pop())}:${h.line}</a>${h.kind==='doc'&&h.period?`<a class="small" href="#/p/${enc(h.period)}">打开这一期</a>`:''}</div>
      <div class="p">${esc(h.path)}</div><div class="s">${esc(h.snippet.replaceAll(' ⏎ ','\n'))}</div></div>`).join('');
    app.querySelectorAll('[data-p]').forEach(a=>a.onclick=()=>readFile(a.dataset.p,Math.max(1,+a.dataset.l-5)));
  }catch(e){app.innerHTML=`<p>${esc(e.message)}</p>`}
}
