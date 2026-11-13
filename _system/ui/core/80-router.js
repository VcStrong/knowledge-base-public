// ==== 路由、实时更新、选择本地路径、KB 对象和启动
// 路由：hash → 页面。模板可以在 KB.routes 里加自己的路由，或替换 KB.pages 里的页面（比如 KB.pages.home）
const curHash=()=>decodeURIComponent(location.hash.slice(1)||'/');
async function route(h){
  if(h==null)h=curHash();else if(h.startsWith('#'))h=decodeURIComponent(h.slice(1))||'/';
  const P=KB.pages,R=KB.routes;
  const k=Object.keys(R).sort((a,b)=>b.length-a.length).find(k=>k.length>1&&k.endsWith('/')?h.startsWith(k):h===k);
  if(k!==undefined)return R[k](k.length>1&&k.endsWith('/')?h.slice(k.length):h);
  if(h.startsWith('/p/'))return P.period(h.slice(3));
  if(h.startsWith('/d/'))return P.docs(h.slice(3));
  if(h==='/base')return P.base();
  if(h==='/settings')return P.settings();
  if(h==='/phones')return P.phones();
  if(h==='/bugs')return P.bugs();
  if(h==='/anr')return P.anr();
  if(h.startsWith('/tool/'))return P.tool(h.slice(6));
  if(h.startsWith('/s/')){const [q,s]=h.slice(3).split('\u0001');return P.search(q,s)}
  if(h==='/classic')return P.overview();
  return P.home();
}
async function render(){
  const h=curHash();
  try{await route(h)}catch(e){if(app)app.innerHTML=`<p>出错：${esc(e.message)}</p><p><a href="#/">返回首页</a></p>`;else console.error(e)}
  sideNav();
  if(KB.hooks.afterRender){try{KB.hooks.afterRender(h)}catch(e){console.error(e)}}
}
// 实时更新：服务端有变化才推送（SSE），只刷新对应部分；不再定时轮询
let pagePending=false;
const curPeriod=()=>{const h=decodeURIComponent(location.hash.slice(1)||'/');return h.startsWith('/p/')?h.slice(3):null};
const canRender=()=>!Object.values(drafts).some(x=>x)&&!dlg.open&&!document.activeElement.matches('input,textarea,select');
function softRender(){if(!canRender()){pagePending=true;return}pagePending=false;const y=scrollY;render().then(()=>scrollTo(0,y))}
function onEvt(ev){
  const h=decodeURIComponent(location.hash.slice(1)||'/'), p=curPeriod();
  if(ev.kind==='dev'&&p===ev.period){if($('#pushBox')){pushBox(p);if($('#tkMsg'))talkBox(p)}else{devBox(p);talkBox(p)}}
  if(ev.kind==='overview'&&p&&$('#tkMsg'))talkBox(p);
  else if(ev.kind==='page'&&p===ev.period)softRender();
  else if(ev.kind==='overview'&&(h==='/'||h==='/bugs'||h==='/anr'))softRender();
  if(ev.kind==='overview'&&(h!=='/'||KB.hooks.nav))navRefresh();   // 经典总览自己会刷侧栏；模板的首页不一定，总是刷
  else if(ev.kind==='adds'){if(dlg.open&&$('#adList'))addList();else if(h==='/')softRender()}
}
function connectEvents(){
  const es=new EventSource('/api/events'),dot=()=>$('#live')||{};
  es.onopen=()=>{const d=dot();d.className='live on';d.title='实时连接中：有变化会自动更新';emit({kind:'live',on:true})};
  es.onmessage=e=>{let ev;try{ev=JSON.parse(e.data)}catch(_){return}try{onEvt(ev)}catch(x){console.error(x)}emit(ev)};
  es.onerror=()=>{const d=dot();d.className='live';d.title='实时连接断开，正在重连…';emit({kind:'live',on:false})};   // EventSource 会自动重连
}
// 刚才因为在输入 / 弹窗开着而推迟的刷新，空下来再补上
function startLate(){
document.addEventListener('focusout',()=>setTimeout(()=>{if(pagePending)softRender();else if(devPending&&curPeriod()===devPending){const n=devPending;devPending='';devBox(n)}},300));
dlg.addEventListener('close',()=>{if(pagePending)setTimeout(softRender,100)});
setInterval(()=>document.querySelectorAll('[data-since]').forEach(x=>x.textContent=since(x.dataset.since)),30000);   // 只更新「已运行」文字，不请求服务器
}

// 事件订阅：KB.on(kind, fn)，kind 是 overview / page / dev / adds / live（连接状态）或 *（全部）
const evSubs={};
function emit(ev){[...(evSubs[ev.kind]||[]),...(evSubs['*']||[])].forEach(f=>{try{f(ev)}catch(e){console.error(e)}})}

// ================================================================ 对外：全局 KB
// 「📁 选择本地路径」：所有选工程 / 仓库的下拉框都带这一项。知识库可能装在服务器上，浏览器的文件夹选择拿不到服务器路径，
// 所以由知识库列目录（/api/fs/dirs），逐级点进去，标出 git / svn 仓库；也可以直接输入路径。选中后像普通选项一样触发 change。
const PICK_OPT='<option value="__pick">📁 选择本地路径…</option>';
function pickDir(start){return new Promise(done=>{
  let d=document.getElementById('kbDirDlg');
  if(!d){d=document.createElement('dialog');d.id='kbDirDlg';d.className='mini';d.style.width='min(560px,calc(100vw - 32px))';document.body.appendChild(d)}
  let chosen=null;d.onclose=()=>done(chosen);
  const load=async p=>{let r;try{r=await api('/api/fs/dirs?path='+enc(p||''))}catch(e){toast(e.message);return}
    d.innerHTML=`<div class="hd"><b>选择本地路径</b><button data-x>取消</button></div><div class="bd" style="display:grid;gap:8px">
      <div class="row" style="gap:6px"><input type="text" id="kbDirP" class="mono" value="${esc(r['路径'])}" style="flex:1;min-width:0"><button id="kbDirGo">打开</button></div>
      <div class="small ${r['版本库']?'':'mut'}">${r['版本库']?`✓ 这是 ${esc(r['版本库'])} 仓库，可以直接选`:'点目录进入；标了 git / svn 的是代码仓库'}　<a id="kbDirHome">回家目录</a></div>
      <div style="max-height:min(52vh,420px);overflow:auto;border:1px solid var(--line);border-radius:8px">
        ${r['上级']?`<a class="kbdir" data-p="${esc(r['上级'])}" style="display:block;padding:6px 10px">⬆ 上一级</a>`:''}
        ${r['目录'].map(x=>`<a class="kbdir" data-p="${esc(x['路径'])}" style="display:flex;gap:8px;align-items:center;padding:6px 10px;border-top:1px solid var(--line)"><span>📁 ${esc(x['名称'])}</span>${x['版本库']?`<span class="badge st-开发中">${esc(x['版本库'])}</span>`:''}</a>`).join('')||'<div class="mut small" style="padding:10px">没有子目录</div>'}</div>
      <div class="row" style="justify-content:flex-end;gap:8px"><button data-x>取消</button><button class="pri" id="kbDirOk">选这个目录</button></div></div>`;
    d.querySelectorAll('[data-x]').forEach(b=>b.onclick=()=>d.close());
    d.querySelectorAll('[data-p]').forEach(a=>a.onclick=()=>load(a.dataset.p));
    d.querySelector('#kbDirHome').onclick=()=>load(r['家目录']);
    const inp=d.querySelector('#kbDirP');d.querySelector('#kbDirGo').onclick=()=>load(inp.value.trim());
    inp.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();load(inp.value.trim())}};
    d.querySelector('#kbDirOk').onclick=()=>{chosen=inp.value.trim()||r['路径'];d.close()}};
  load(start||'');if(!d.open)d.showModal()})}
document.addEventListener('focusin',e=>{const s=e.target;if(s&&s.tagName==='SELECT'&&s.value!=='__pick')s.dataset.prev=s.value},true);
document.addEventListener('change',async e=>{const s=e.target;if(!s||s.tagName!=='SELECT'||s.value!=='__pick')return;
  e.stopImmediatePropagation();const prev=s.dataset.prev||'';s.value=prev;
  const p=await pickDir(prev&&prev.startsWith('/')?prev:'');if(!p)return;
  let o=[...s.options].find(x=>x.value===p);
  if(!o){o=document.createElement('option');o.value=p;o.textContent='📁 '+p.replace(/^\/Users\/[^/]+/,'~');s.insertBefore(o,s.querySelector('option[value="__pick"]'))}
  s.value=p;s.dataset.prev=p;s.dispatchEvent(new Event('change',{bubbles:true}))},true);

const KB={
  version:1,
  get app(){return app},
  setApp(el){app=typeof el==='string'?$(el):el;return app},
  pages:{home,overview,brief:briefPage,period,bugs:bugsPage,anr:anrPage,phones:phonesPage,base:basePage,settings:settingsPage,docs,tool:toolPage,search},
  routes:{},
  route,render,softRender,canRender,navRefresh,curHash,
  hooks:{afterRender:null,nav:null},
  on(kind,fn){(evSubs[kind]=evSubs[kind]||[]).push(fn);return()=>{evSubs[kind]=evSubs[kind].filter(f=>f!==fn)}},
  api,post,esc,enc,toast,openDlg,md,mdInline,badge,fileUrl,readFile,showImg,since,when,size,
  askOpen,addDlg,taskNav,logout,pickDir,PICK_OPT,   // pickDir(起始路径) → 选中的本地路径或 null；PICK_OPT 放进模板自己的仓库下拉框
  site:()=>api('/api/site').then(s=>(KB.siteCache=s)),siteCache:null,   // 最近一次 /api/site 的结果（模板在 afterRender 里可直接用）
  get briefOpts(){return briefOpts},   // 执行判断 / 交给管家 / 理解预览：配合 KBUI.judg、KBUI.bind 用
  template:uiTemplate,setTemplate,
  get periods(){return ovPeriods},get entries(){return entries},get periodNames(){return periodNames},get taskNames(){return taskNames},get auth(){return authOn},
  ORDER,DOT,
  manualStart:false,_started:false,
  start(){
    if(KB._started)return;KB._started=true;
    navGroups();
    if($('#sf'))$('#sf').onsubmit=e=>{e.preventDefault();const q=$('#q').value.trim();if(q)location.hash='#/s/'+enc(q+'\u0001'+($('#scope')?$('#scope').value:'all'))};
    if($('#addBtn'))$('#addBtn').onclick=()=>askOpen(true);   // 「＋ 添加」= 交给管家（新建一期 / 事项在总览和侧栏里）
    window.addEventListener('hashchange',render);render();navRefresh();
    connectEvents();startLate();
  }
};
window.KB=KB;
// 脚本都执行完（模板的 app.js 设好 setApp / hooks）再启动；模板要先做异步准备就设 KB.manualStart=true，准备好后自己调 KB.start()
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>{if(!KB.manualStart)KB.start()});
else setTimeout(()=>{if(!KB.manualStart)KB.start()});
