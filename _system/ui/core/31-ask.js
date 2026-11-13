// ==== 交给管家面板、推动卡片
// 问管家：右下角常驻，说话代替大部分表单；它用知识库工具查和改，红线动作只告诉你去哪点
let askTimer=null;
function askOpen(o){$('#askPanel').hidden=!o;$('#askFab').hidden=o;if(o){askLoad();setTimeout(()=>$('#askIn').focus(),50)}}
async function askLoad(){
  let r;try{r=await api('/api/chat')}catch(e){return}
  const box=$('#askLog'),hint=`<div class="mut small">把东西交给我就行：需求、日志、Bug、账号、文件……我归到对应的地方，接着往下推（资料齐了出方案、日志建事项、Bug 只读分析）；要动代码的给你一个确认按钮，拍板、开工、验收在页面上点。${(r['规矩']||[]).length?`<br>记着的规矩：${r['规矩'].map(x=>esc(x['内容'])).join('；')}`:''}</div>`;
  box.innerHTML=hint+r['对话'].map(x=>`<div class="aq">${esc(x['问'])}${(x['文件']||[]).length?`<div class="small mut">📎 ${x['文件'].map(esc).join('、')}</div>`:''}</div>`+(x['状态']==='思考中'?'<div class="aa mut">思考中…（会用知识库工具查，可能要一两分钟）</div>'
    :`<div class="aa ${x['状态']==='出错'?'err':''}">${md(x['答']||'').html.replace(/href="(#[^"]*)" target="_blank" rel="noopener"/g,'href="$1"')}${x['提议']?propHtml(x['提议'],x['编号']):''}</div>`)).join('');
  bindProp(box,'/api/chat/confirm');
  box.scrollTop=box.scrollHeight;$('#askSt').textContent=r['思考中']?'思考中…':'';
  clearTimeout(askTimer);if(r['思考中']&&!$('#askPanel').hidden)askTimer=setTimeout(askLoad,3000);
}
// 推动卡片：只问工程和分支（默认值选好了），点「▶ 推动」= 你本人批准
function propHtml(p,id){
  if(p['已确认'])return `<div class="prop">✓ 已推动「${esc(p['事项'])}」· 工程 <span class="mono">${esc((p['工程']||'').replace(/^\/Users\/[^/]+/,'~'))}</span>${p['分支']?' · 分支 '+esc(p['分支']):''}<div class="small mut">${esc((p['结果']||'').split('\n')[0])}</div><a href="#/p/${enc(p['事项'])}">看进展</a></div>`;
  const rs=p['仓库']||[];
  return `<div class="prop" data-prop="${esc(id)}"><div class="small mut">${esc(p['说明']||'')}</div>
    <label class="small">工程${rs.length?`<select data-prepo>${rs.map(r=>`<option value="${esc(r['路径'])}" data-br="${esc(r['分支']||'')}" ${r['路径']===p['默认仓库']?'selected':''}>${esc(r['名称'])} · ${esc(r['路径'].replace(/^\/Users\/[^/]+/,'~'))}</option>`).join('')}${PICK_OPT}</select>`
      :`<input data-prepo placeholder="工程目录，如 ~/AndroidStudioProjects/app" value="${esc(p['默认仓库']||'')}">`}</label>
    <label class="small">分支<input data-pbr value="${esc(p['默认分支']||'')}" placeholder="不填 = 用工程现在的分支"></label>
    <button class="pri" data-pgo="${esc(id)}">▶ 推动（${(p['条目']||[]).length} 条）</button></div>`;
}
function bindProp(root,url,extra){
  root.querySelectorAll('[data-prop]').forEach(box=>{const sel=box.querySelector('select[data-prepo]'),br=box.querySelector('[data-pbr]');
    if(sel)sel.onchange=()=>{br.value=sel.selectedOptions[0].dataset.br||''};
    box.querySelector('[data-pgo]').onclick=async e=>{const b=e.target;b.disabled=true;b.textContent='推动中…';
      try{toast((await post(url,{id:box.dataset.prop,repo:box.querySelector('[data-prepo]').value.trim(),branch:br.value.trim(),...(extra||{})})).msg.split('\n')[0])}catch(err){toast(err.message);b.disabled=false;b.textContent='▶ 推动'}
      askLoad();if(typeof loadStw==='function')loadStw()}})}
let askStaged=[];
function askFilesShow(){$('#askFiles').innerHTML=askStaged.map((f,i)=>`<span>${esc(f.name)} <a data-afx="${i}">✕</a></span>`).join('');
  $('#askFiles').querySelectorAll('[data-afx]').forEach(a=>a.onclick=()=>{askStaged.splice(+a.dataset.afx,1);askFilesShow()})}
async function askStage(fs){for(const f of fs){try{const r=await fetch('/api/chat/stage',{method:'POST',headers:{'X-Filename':encodeURIComponent(f.name)},body:f});
  const j=await r.json();if(!r.ok)throw new Error(j.error||'上传失败');askStaged.push({id:j.id,name:f.name})}catch(e){toast(f.name+'：'+e.message)}}askFilesShow()}
async function askSend(){const v=$('#askIn').value.trim();if(!v&&!askStaged.length)return;
  try{await post('/api/chat/ask',{text:v,files:askStaged.map(f=>f.id),page:decodeURIComponent(location.hash.slice(1)||'/')});$('#askIn').value='';askStaged=[];askFilesShow();askLoad()}catch(e){toast(e.message)}}
$('#askFile').onchange=e=>{askStage([...e.target.files]);e.target.value=''};
const ap=$('#askPanel');ap.addEventListener('dragover',e=>{e.preventDefault();ap.classList.add('drop')});ap.addEventListener('dragleave',()=>ap.classList.remove('drop'));
ap.addEventListener('drop',e=>{e.preventDefault();ap.classList.remove('drop');if(e.dataTransfer.files.length)askStage([...e.dataTransfer.files])});
$('#askIn').addEventListener('paste',e=>{const fs=[...(e.clipboardData||{}).files||[]];if(fs.length){e.preventDefault();askStage(fs)}});
$('#askFab').onclick=()=>askOpen(true);$('#askX').onclick=()=>askOpen(false);$('#askGo').onclick=askSend;
$('#askIn').onkeydown=e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){e.preventDefault();askSend()}};
$('#askNewP').onclick=()=>addDlg('new');
$('#askClr').onclick=async()=>{try{toast((await post('/api/chat/clear',{})).msg)}catch(e){toast(e.message)}askLoad()};
$('#askLog').addEventListener('click',e=>{const a=e.target.closest('a[href^="#"]');if(a&&innerWidth<900)askOpen(false)});
