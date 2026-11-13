// ==== 管家卡片、首次引导、工作统计
// 管家：明确的事自己做（只读 / 能重做的），要你批准的出卡片，不明确的只问一个问题
const STW_TAG={问你:'❓ AI 想问你',待你:'需要你判断',建议:'💡 AI 的建议'};
const STW_ACT={'Bug分析':'Bug 只读分析','来源整理':'需求资料重新整理'};
function stwHtml(v){
  if(!v)return '';
  const s=v['设置'],cs=v['卡片']||[],did=v['已做']||[];
  const head=`<div class="sh"><h2>🤖 管家</h2><span class="mut small">${s['开启']?`自主度「${esc(s['自主度'])}」 · 今天自动做了 ${v['今日已做']}/${s['每日上限']} 件`:'已关闭：只看不做'}${v['上次']?` · 上次巡检 ${esc(v['上次'].slice(11))}`:''}</span>
    <button class="small" id="stwTick" title="现在就巡检一轮：明确的事会自动做">立即巡检</button><a class="small src" href="#/settings">管家设置</a></div>`;
  const card=c=>`<div class="stc t-${esc(c['类型'])}"><span class="small mut">${STW_TAG[c['类型']]||esc(c['类型'])}</span><div class="tt">${esc(c['标题'])}</div>
    ${c['说明']?`<div class="ds">${esc(c['说明'])}</div>`:''}${c['为什么']?`<div class="wy">${esc(c['为什么'])}</div>`:''}${c['提议']?propHtml(c['提议'],c.id):''}
    <div class="ac">${c['提议']?`<a class="small" href="${esc(c['链接']||'#/')}">看事项</a>`:c['选项']?`<select data-sopt="${esc(c.id)}">${c['选项'].map(o=>`<option value="${esc(o['值'])}">${esc(o['标签'])}</option>`).join('')}</select><button class="pri" data-sans="${esc(c.id)}">就用这个</button>`
      :(c['动作']==='run'||c['动作']==='ignore'||c['动作']==='upgrade')?`<button class="pri" data-sans="${esc(c.id)}">${esc(c['按钮']||'现在就做')}</button>${c['链接']?`<a class="small" href="${esc(c['链接'])}">看看</a>`:''}`
      :c['链接']?`<a class="btn" href="${esc(c['链接'])}"><button class="pri">${esc(c['按钮']||'去看看')}</button></a>`:''}
      <span class="no" data-sno="${esc(c.id)}" title="这件事先不提；情况有变化会再出现">不用了</span></div></div>`;
  return head+(v['日报']?`<div class="brief">📰 今日日报：${esc(v['日报']['内容'])}</div>`:'')
    +(cs.length?`<div class="stcards">${cs.map(card).join('')}</div>`:'<p class="mut small" style="margin:0">✓ 现在没有要你处理的事。</p>')
    +(did.length?`<details><summary>管家最近自动做了 ${did.length} 件</summary><ul>${did.map(r=>`<li><span class="mut">${esc(r['时间'].slice(5))}</span> ${esc(STW_ACT[r['动作']]||r['动作'])}：${esc([].concat(r['对象']).join('、'))} · ${esc(r['结果'])}</li>`).join('')}</ul></details>`:'');
}
// 首次引导：引擎能用 → 勾选本机仓库 → 放进第一个需求（三步都好了或点「收起」就不再出现）
let onbScan=null;
async function loadOnb(){
  const el=$('#ovOnb');if(!el)return;let o;try{o=await api('/api/onboard')}catch(_){return}
  if(o['完成']||o['收起']){el.innerHTML='';el.className='';return}
  el.className='onb';const e=o['引擎'],ok=o['步骤'];
  const st=(i,title,body)=>`<div class="os ${ok[i]?'ok':''}"><span class="num">${ok[i]?'✓':i+1}</span><div><b>${title}</b><div class="small" style="margin-top:3px">${body}</div></div></div>`;
  const s1=!e['已安装']?`没找到 ${esc(e['名称']||'AI 引擎')}。先安装 <a href="https://claude.com/claude-code" target="_blank" rel="noopener">Claude Code</a> 并登录，装好后刷新这一页；用别的 AI 到「⚙ 设置 → AI 引擎」里选。`
    :e['已接入']===false?`${esc(e['名称'])} 已安装，但还没接入知识库（接入后它才能读资料、在网页上问你）。 ${e['能接入']?'<button class="pri small" id="onbLink">一键接入</button>':'到「⚙ 设置 → AI 引擎」按说明接入。'}`
    :`${esc(e['名称'])} ${esc(e['版本']||'')} 能用了。`;
  const rows=onbScan?onbScan.filter(r=>!r['已登记']):null;
  const s2=ok[1]&&!onbScan?`已有 ${o['仓库数']} 个代码仓库可选。<a id="onbScan">再扫描一次</a>`
    :!rows?`<button class="pri small" id="onbScan">扫描本机代码仓库</button> <span class="mut">在家目录下找 git / svn 仓库，认出是哪个端，你勾选就行。</span>`
    :rows.length?`<div class="rl">${rows.map(r=>`<label><input type="checkbox" data-onbr="${esc(r['路径'])}" ${r['端'].length?'checked':''}><b>${esc(r['名称'])}</b> <span class="badge">${esc(r['端'].join('/')||'未识别')}</span> <span class="mut mono">${esc(r['路径'].replace(/^\/Users\/[^/]+/,'~'))}</span></label>`).join('')}</div>
      <button class="pri small" id="onbAdd">登记勾选的仓库</button> <span class="mut">没找到的仓库：终端 <code>kb repo &lt;路径&gt;</code>，或以后在每一期「全栈」里直接填路径。</span>`
    :'没找到新的仓库。仓库在别处的话：终端 <code>kb repo &lt;路径&gt;</code>，或以后在每一期「全栈」里直接填路径。';
  const s3=ok[2]?`已有 ${o['期数']} 期。`:`<button class="pri small" id="onbNew">＋ 放进第一个需求</button> <span class="mut">粘贴需求链接、文档或产品说的话，AI 自动建期、归好类；之后每一期顶部会告诉你下一步做什么。</span>
    <div style="margin-top:6px"><button class="small" id="onbDemo">先看一个示例</button> <span class="mut">建一个「连续签到奖励」示例期（服务端 + Android 两个小示例仓库），跟着点一遍出方案 → 拍板 → 开发 → 验收，看完删掉。</span></div>`;
  el.innerHTML=`<div class="sh"><h2>👋 三步上手</h2><span class="mut small">做完就能让 AI 按流程干活</span><a class="small" id="onbHide">收起</a></div>
    ${st(0,'AI 引擎',s1)}${st(1,'代码仓库',s2)}${st(2,'第一个需求',s3)}`;
  const go=async(u,b)=>{try{toast((await post(u,b)).msg)}catch(err){toast(err.message)}loadOnb()};
  if($('#onbLink'))$('#onbLink').onclick=()=>go('/api/engine/link',{id:e.id});
  if($('#onbScan'))$('#onbScan').onclick=async()=>{$('#onbScan').textContent='扫描中…';try{onbScan=(await api('/api/onboard/scan')).items}catch(err){toast(err.message)}loadOnb()};
  if($('#onbAdd'))$('#onbAdd').onclick=()=>{const ps=[...el.querySelectorAll('[data-onbr]:checked')].map(x=>x.dataset.onbr);if(!ps.length)return toast('先勾选仓库');onbScan=null;go('/api/onboard/repos',{paths:ps})};
  if($('#onbNew'))$('#onbNew').onclick=()=>askOpen(true);
  if($('#onbDemo'))$('#onbDemo').onclick=async()=>{try{const r=await post('/api/demo',{});toast(r.msg);location.hash='#/p/'+enc(r.name)}catch(err){toast(err.message)}};
  $('#onbHide').onclick=()=>go('/api/onboard/hide',{hide:true});
}
async function loadStw(){
  try{ovStw=await api('/api/steward')}catch(e){ovStw=null}
  const el=$('#ovStw');if(!el)return;el.innerHTML=stwHtml(ovStw);
  const go=async(u,b)=>{try{toast((await post(u,b)).msg)}catch(e){toast(e.message)}loadStw()};
  const t=$('#stwTick');if(t)t.onclick=()=>{t.disabled=true;t.textContent='巡检中…';go('/api/steward/tick',{})};
  el.querySelectorAll('[data-sans]').forEach(b=>b.onclick=()=>{if(/忽略/.test(b.textContent)&&!confirm('忽略这些陈旧 Bug？只在知识库标记，不改 Bug 平台，随时能在 Bug 页取消。'))return;const s=el.querySelector(`[data-sopt="${CSS.escape(b.dataset.sans)}"]`);b.disabled=true;go('/api/steward/answer',{id:b.dataset.sans,value:s?s.value:''})});
  el.querySelectorAll('[data-sno]').forEach(b=>b.onclick=()=>go('/api/steward/dismiss',{id:b.dataset.sno}));
  bindProp(el,'/api/steward/answer');
}

// 工作统计：数由「统计」插件算（⚙ 设置 → 插件 挂载「工作统计」）；没挂就不显示
function statsHtml(r){
  if(!r)return '';
  if(r['错误'])return `<div class="sh"><h2>工作统计</h2><span class="mut small">${esc(r['错误'])}</span></div>`;
  const pr=r['进度']||[];
  return `<div class="sh"><h2>工作统计</h2>${(r['范围列表']||[]).map(x=>`<button class="fchip ${x===r['范围']?'on':''}" data-sr="${esc(x)}">${esc(x)}</button>`).join('')}
    <span class="mut small src">插件「${esc(r['插件'])}」计算${r['起']?` · ${esc(r['起'])} 起`:''}</span></div>
  <div class="scards">${(r['卡片']||[]).map(c=>{const t=c['链接']?'a':'div';return `<${t} class="scard"${c['链接']?` href="${esc(c['链接'])}"`:''}><div class="k">${esc(c['标题'])}</div><div class="v">${esc(c['值'])}<small>${esc(c['单位']||'')}</small></div>${c['说明']?`<div class="s">${esc(c['说明'])}</div>`:''}</${t}>`}).join('')}</div>
  ${pr.length?`<div class="sprog">${pr.map(x=>{const pc=x['总数']?Math.round(100*x['完成']/x['总数']):0;return `<div class="sprow"><div class="nm">${badge(x['状态'])} <a href="${esc(x['链接']||'#/')}" title="${esc(x['名称'])}">${esc(x['名称'])}</a></div>
    <div class="sbar">${x['总数']?`<span class="b"><i style="width:${pc}%"></i></span><span>${x['完成']}/${x['总数']}</span>`:'<span class="mut">—</span>'}</div><div class="small mut">${esc(x['说明']||'')}</div></div>`}).join('')}</div>`:''}`;
}
async function loadStats(){
  try{ovStats=await api('/api/stats'+(ovRange?'?range='+enc(ovRange):''))}catch(e){ovStats=null}
  const el=$('#ovStats');if(!el)return;el.innerHTML=statsHtml(ovStats);
  el.querySelectorAll('[data-sr]').forEach(b=>b.onclick=()=>{ovRange=b.dataset.sr;try{localStorage.setItem('kb.statRange',ovRange)}catch(_){}loadStats()});
}
