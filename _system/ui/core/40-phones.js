// ==== 手机页、通用格式化
// 手机：所有期共用，谁在用、哪个分支
async function phonesPage(){
  const r=await api('/api/devices');navRefresh();
  app.innerHTML=`<div class="pagehead"><div><h1>手机</h1><p class="mut">所有期共用的手机。后台会话只会往申请到的手机装包、操作，不会碰别的期占着的；你自己要用就点「我在用」（4 小时内后台不碰它）。</p></div></div>
  <div class="card2"><div class="bd" id="phList">${r.items?phoneRows(r.items,''):'<span class="mut">本机找不到 adb：装好 Android SDK platform-tools 后刷新。</span>'}</div></div>`;
  bindPhones(app,()=>phonesPage());
}
const phoneRows=(items,period)=>items.length?items.map(x=>{const c=x['占用'],cls=x['空闲']?'free':!c?'':c['方式']==='本人'||x['本期']?'mine':'busy';
  const st=x['空闲']?'空闲':!c?esc(x['状态']):(c['方式']==='本人'?'本人在用':x['本期']?'本期占用':`「${esc(c['期'])}」占用${c['分支']?' · 分支 <span class="mono">'+esc(c['分支'])+'</span>':''}`)+` · 最后使用 ${esc(c['最后使用'])}${x['状态']!=='在线'?' · '+esc(x['状态']):''}`;
  return `<div class="phone ${cls}"><span class="pi"></span><div style="min-width:0"><div><b>${esc(x['型号']||'未知型号')}</b> <span class="mono mut">${esc(x['序列号'])}</span></div>
    <div class="small mut">${st}${x['agent-device']?` · agent-device 会话 ${esc(x['agent-device']['会话'])}${x['agent-device']['期']?'（'+esc(x['agent-device']['期'])+'）':''}`:''}</div></div>
    ${c?`<button class="small" data-dm="release" data-sn="${esc(x['序列号'])}" title="解除占用（后台会话还在用的话，它下次操作会重新占用）">释放</button>`:x['空闲']?`<button class="small" data-dm="mine" data-sn="${esc(x['序列号'])}" title="你自己要用这台手机：4 小时内后台会话不会往它装包、操作">我在用</button>`:'<span></span>'}</div>`}).join(''):'<div class="small mut">没有连着的手机</div>';
function bindPhones(root,after){root.querySelectorAll('[data-dm]').forEach(b=>b.onclick=async()=>{
  if(b.dataset.dm==='release'&&!confirm(`解除 ${b.dataset.sn} 的占用？`))return;
  try{const r=await post('/api/device',{serial:b.dataset.sn,action:b.dataset.dm});toast(r.msg);after()}catch(e){toast(e.message)}})}

const size=n=>n>1048576?(n/1048576).toFixed(1)+' MB':n>1024?(n/1024).toFixed(0)+' KB':n+' B';
const when=t=>new Date(t*1000).toLocaleString('zh-CN',{hour12:false}).slice(0,16);

let ptabs={};try{ptabs=JSON.parse(localStorage.getItem('kb.ptabs')||'{}')}catch(_){}
let pview='tab';try{pview=localStorage.getItem('kb.pview')||'tab'}catch(_){}