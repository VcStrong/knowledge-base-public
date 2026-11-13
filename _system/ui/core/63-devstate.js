// ==== 开发面板的状态缓存
// ---------------- 开发面板：开始/停止、免打扰、待确认、进度、最近动作
const drafts={};let devPending='';
// 开发面板每 5 秒刷新：内容没变不重画；鼠标停在「最近动作」上时暂停；重画后保留滚动位置和展开状态
const devCache={name:'',html:'',sig:''};
const actLine=a=>a['类型']==='工具'?`<div class="tool">${a['子任务']?'↳ ':''}🔧 ${esc(a['工具'])}　${esc(a['内容'])}</div>`
  :a['类型']==='结束'?`<div class="end">${a['出错']?'❌':'🏁'} ${esc(a['内容'])}</div>`
  :a['类型']==='会话'?`<div class="sess">── 会话 ${esc(a['内容'])} ──</div>`:`<div>💬 ${esc(a['内容'])}</div>`;
async function allActs(name){
  let a;try{a=await api('/api/dev/activity?name='+enc(name))}catch(e){return toast(e.message)}
  openDlg('全部开发动作（不自动刷新）',a.length?`<div class="small mut" style="margin-bottom:6px">共 ${a.length} 条，最新的在最下面</div><div class="act" style="max-height:70vh">${a.map(actLine).join('')}</div>`:'<span class="mut">暂无</span>');
  const el=$('#dlgB').querySelector('.act');if(el)el.scrollTop=el.scrollHeight;
}