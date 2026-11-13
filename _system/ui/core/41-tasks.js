// ==== 事项表格和新建表单
// ---- 事项：和期一样的资料 / 确认 / 开发能力，默认轻量流程，单独列出
let taskNames=[];
const PRI_C={高:'st-已暂停2',中:'st-收集中',低:'st-已完成'};
function taskTable(ts){
  if(!ts.length)return '<p class="mut">还没有事项。用户上报的 ANR、要加的埋点、线上问题……点「＋ 新建事项」，或在 🐞 Bug 页把待归纳的 Bug 归入事项。</p>';
  const open=ts.filter(t=>t.status!=='已完成'),done=ts.filter(t=>t.status==='已完成');
  const row=t=>`<tr><td><a href="#/p/${enc(t.name)}"><b>${esc(t.name)}</b></a>${sideOn()&&t.batch&&!(t.plugins||[]).length?` <a class="small mut" data-tnav="${esc(t.name)}" data-show="${t.batch['侧栏']?'':'1'}">${t.batch['侧栏']?'从侧栏移除':'加回侧栏'}</a>`:''}<div class="mut small">${esc(t.summary||'')}</div></td>
    <td><span class="badge st-收集中">${esc(t.taskKind||'其他')}</span></td><td><span class="badge ${PRI_C[t.priority]||''}">${esc(t.priority||'中')}</span></td>
    <td>${badge(t.status)}${t.running?' <span class="badge st-开发中">● 处理中</span>':''}${t.pendingQ?` <span class="badge st-已批准开发">🔔 ${t.pendingQ}</span>`:''}</td>
    <td>${t.bugs?`🐞 ${t.bugs}`:''}</td><td class="small mut">${esc(t.from||'')}</td><td class="small mut">${esc(t.lastLog?t.lastLog.time:t.created)}</td></tr>`;
  const head='<tr><th>事项</th><th style="width:96px">类型</th><th style="width:72px">优先级</th><th style="width:170px">状态</th><th style="width:60px">Bug</th><th style="width:150px">来自</th><th style="width:130px">最近</th></tr>';
  const order=a=>a.slice().sort((x,y)=>(['高','中','低'].indexOf(x.priority)-['高','中','低'].indexOf(y.priority))||String(y.updated||'').localeCompare(String(x.updated||'')));
  return `<div class="tw"><table>${head}${order(open).map(row).join('')||'<tr><td colspan="7" class="mut">没有进行中的事项</td></tr>'}</table></div>
    ${done.length?`<details style="margin-top:6px"><summary class="small mut">已完成 ${done.length}</summary><div class="tw"><table>${head}${done.map(row).join('')}</table></div></details>`:''}`}
function taskForm(o){return `<label>名称<input type="text" id="tkN" value="${esc(o.name||'')}" placeholder="简短说清是什么，如：歌房进房 ANR / 礼物面板曝光埋点" ${o.edit?'disabled':''}></label>
  <div class="row"><label style="flex:1">类型<select id="tkK">${o.edit?'':'<option value="">自动判断</option>'}${o.kinds.map(k=>`<option ${k===o.kind?'selected':''}>${k}</option>`).join('')}</select></label>
    <label style="flex:1">优先级<select id="tkP">${o.pris.map(k=>`<option ${k===(o.priority||'中')?'selected':''}>${k}</option>`).join('')}</select></label></div>
  <label>来自（可空）<input type="text" id="tkF" value="${esc(o.from||'')}" placeholder="如：用户反馈 vv号 123 / Bugly / 产品 小王"></label>
  <label>说明（可空）<textarea id="tkS" rows="3" placeholder="现象 / 要做什么、影响范围；日志、截图建好后拖进资料">${esc(o.summary||'')}</textarea></label>`}
