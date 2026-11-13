// ==== 构建
// ---------------- 构建：这一期在构建平台（如 Jenkins）上的产出，按分支自动对应任务
const BRES={SUCCESS:['st-已完成','成功'],FAILURE:['st-已暂停2','失败'],UNSTABLE:['st-已暂停','不稳定'],ABORTED:['','已中止'],进行中:['st-开发中','● 构建中']};
async function buildBox(name,fresh){
  const box=$('#buildBox');if(!box)return;
  if(fresh)box.innerHTML='<span class="mut small">刷新中…</span>';
  let v;try{v=await api('/api/period/builds?name='+enc(name)+(fresh?'&fresh=1':''))}catch(e){box.innerHTML=`<span class="mut small">${esc(e.message)}</span>`;return}
  if(!$('#buildBox')||curPeriod()!==name)return;
  const n=v['任务'].reduce((a,j)=>a+j['构建'].length,0),tb=document.querySelector('[data-tab="build"]');
  if(tb&&n)tb.innerHTML=`构建<span class="n">${n}</span>`;
  if(!v['插件']){box.innerHTML=`<div class="mut small">还没有挂载构建插件。把 Jenkins 地址填进「◈ 基础信息」（字段「地址」，如 http://jenkins.example.com/jenkins），再到「⚙ 设置 → 插件 → Jenkins」挂载并选这个条目；之后每一期按分支自动对应 Jenkins 任务。</div>`;return}
  const art=(b,k)=>b['产物'].filter(a=>a['类型']===k);
  const row=b=>{const r=BRES[b['进行中']?'进行中':b['结果']]||['',b['结果']||'?'],apk=art(b,'安装包'),mp=art(b,'mapping')[0],qr=art(b,'二维码')[0];
    return `<tr><td><a href="${esc(b['地址'])}" target="_blank" rel="noopener" class="mono">#${b['编号']}</a></td><td><span class="badge ${r[0]}">${esc(r[1])}</span></td>
      <td class="mono small">${esc(b['版本']||'')}</td><td class="small">${esc(b['时间'])}<div class="mut">${b['耗时']} 分钟</div></td>
      <td class="mono small" title="${esc(b['提交'])}">${esc((b['提交']||'').slice(0,10))}${b['分支']&&!v['分支'].includes(b['分支'])?`<div class="mut">${esc(b['分支'])}</div>`:''}</td>
      <td class="small">${apk.length?`<details><summary>安装包 ${apk.length} 个</summary>${apk.map(a=>`<div><a href="${esc(a['地址'])}">${esc(a['名称'])}</a></div>`).join('')}</details>`:''}
        ${qr?`<a data-qr="${esc(qr['地址'])}">二维码</a>`:''}
        ${mp?` · <a href="${esc(mp['地址'])}">mapping</a> <a data-bmap="${esc(mp['地址'])}" data-ver="${esc(b['版本'])}" title="归档到 ANR / 崩溃，这个版本的崩溃日志自动还原">归档</a>`:''}</td>
      <td class="small">${(b['Bug']||[]).length?`<a href="#/bugs" title="Bug 平台上记的提测包是这一次构建">🐞 ${b['Bug'].map(esc).join('、')}</a>`:''}</td></tr>`};
  box.innerHTML=`<div class="row small" style="gap:10px;flex-wrap:wrap;margin-bottom:8px"><span class="mut">分支 ${v['分支'].map(x=>`<b class="mono">${esc(x)}</b>`).join('、')||'（没写，在资料里加一条「分支」文字资料）'}</span>
      <span class="sp" style="flex:1"></span><button class="small" id="bdEdit">改对应任务</button><button class="small" id="bdFresh">↻ 刷新</button></div>
    ${v['任务'].length?v['任务'].map(j=>`<div style="margin-bottom:12px"><div class="small"><b>${esc(v['插件'])}</b> <a href="${esc(j['地址'])}" target="_blank" rel="noopener" class="mono">${esc(j['名称'])}</a> <span class="mut">（${j['依据']==='手动'?'手动指定':'按分支自动匹配'}）</span></div>
      ${j['错误']?`<div class="small" style="color:var(--warn)">${esc(j['错误'])}</div>`:j['构建'].length?`<div class="tw"><table><tr><th style="width:60px">构建</th><th style="width:80px">结果</th><th style="width:110px">版本</th><th style="width:130px">时间</th><th style="width:110px">提交</th><th>产物</th><th style="width:140px">这个包上的 Bug</th></tr>${j['构建'].map(row).join('')}</table></div>`:'<div class="mut small">还没有构建</div>'}</div>`).join('')
      :`<div class="mut small">没匹配到构建任务（任务名里要含分支名）。点「改对应任务」填任务名或地址。</div>`}`;
  $('#bdFresh').onclick=()=>buildBox(name,true);
  $('#bdEdit').onclick=()=>{openDlg('这一期对应的构建任务',`<div class="form"><label>任务名或地址（可多个，换行隔开；留空 = 按分支重新自动匹配）<textarea id="bdJ" rows="3" class="mono" placeholder="如：app_android_feature-x&#10;或 http://jenkins…/job/app_android_feature-x/">${esc(v['任务'].map(j=>j['地址']||j['名称']).join('\n'))}</textarea></label>
      <div class="row"><button class="pri" id="bdGo">保存</button></div></div>`);
    $('#bdGo').onclick=async()=>{try{const r=await post('/api/period/builds',{period:name,jobs:$('#bdJ').value});toast(r.msg);dlg.close();buildBox(name,true)}catch(e){toast(e.message)}}};
  box.querySelectorAll('[data-qr]').forEach(a=>a.onclick=()=>openDlg('扫码安装',`<img src="${esc(a.dataset.qr)}" style="max-width:280px;display:block;margin:auto">`));
  box.querySelectorAll('[data-bmap]').forEach(a=>a.onclick=async()=>{if(!a.dataset.ver)return toast('这次构建认不出版本号，到 ANR / 崩溃页「＋ 归档 mapping」手动填');
    if(!confirm(`把这次构建的 mapping 归档为版本 ${a.dataset.ver}？`))return;
    a.textContent='归档中…';try{const r=await post('/api/build/mapping',{url:a.dataset.bmap,version:a.dataset.ver});openDlg('已归档 mapping',`<pre style="white-space:pre-wrap">${esc(r.msg)}</pre>`)}catch(e){toast(e.message)}finally{a.textContent='归档'}});
}