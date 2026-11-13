// ==== 基础信息
// ---------------- 基础知识库：所有期共用的账号、测试账号、代理 / VPN、环境配置
async function basePage(){
  const d=await api('/api/base'),es=d['条目'];
  const field=(e,f)=>`<tr><td>${esc(f['名'])}</td><td>${f['机密']?`<span class="sec" data-sv="${esc(e['编号'])}" data-sf="${esc(f['名'])}">●●●●●●</span> <a class="small" data-show>显示</a> · <a class="small" data-copy>复制</a>`:`${/^https?:\/\//.test(f['值'])?`<a href="${esc(f['值'])}" target="_blank" rel="noopener">${esc(f['值'])}</a>`:esc(f['值'])} <a class="small" data-cp="${esc(f['值'])}">复制</a>`}</td></tr>`;
  const card=e=>`<div class="bcard"><div class="t"><b>${esc(e['名称'])}</b><span class="small"><span class="mut">${esc(e['编号'])}</span> <a data-edit="${esc(e['编号'])}">编辑</a></span></div>
    ${e['适用']?`<div class="small mut">适用：${esc(e['适用'])}</div>`:''}
    <table>${(e['字段']||[]).map(f=>field(e,f)).join('')}</table>
    ${e['附件']&&e['附件'].length?`<div class="small">附件：${e['附件'].map(a=>`<a data-rf="${esc(d.dir+'/'+a)}">${esc(a.split('/').pop())}</a>`).join('　')}</div>`:''}
    ${e['备注']?`<div class="small md" style="margin-top:4px">${md(e['备注']).html}</div>`:''}</div>`;
  app.innerHTML=`<div class="row" style="justify-content:space-between"><h1>🗂 基础知识库</h1><button class="pri" id="bAdd">＋ 新增</button></div>
    <p class="mut">所有期共用的基础上下文：网站账号、测试账号、Wi-Fi / 代理 / VPN、环境配置等。Claude 回答和开发时会自动参考。
    密码等<b>机密字段只存钥匙串（Mac）或加密文件（服务器）</b>，页面默认隐藏；也可以直接跟 Claude 说「把 XX 测试账号记到基础知识库」。</p>
    ${es.length?d.cats.filter(c=>es.some(e=>e['分类']===c)).map(c=>`<h2>${esc(c)}</h2><div class="bgrid">${es.filter(e=>e['分类']===c).map(card).join('')}</div>`).join('')
      :'<p class="mut">还没有内容，点右上角「＋ 新增」。</p>'}
    ${d.files.length?`<h2>文件</h2><ul class="files">${d.files.map(f=>`<li><a data-rf="${esc(f.path)}">${esc(f.path.slice(d.dir.length+1))}</a><span class="mut small">${size(f.size)} · ${when(f.mtime)}</span></li>`).join('')}</ul>`:''}
    <p class="mut small">目录：${esc(d.dir)}</p>`;
  app.querySelectorAll('[data-rf]').forEach(a=>a.onclick=()=>readFile(a.dataset.rf));
  app.querySelectorAll('[data-cp]').forEach(a=>a.onclick=()=>{navigator.clipboard.writeText(a.dataset.cp);toast('已复制')});
  const secret=async el=>(await post('/api/base/secret',{id:el.dataset.sv,field:el.dataset.sf})).value;
  app.querySelectorAll('[data-show]').forEach(a=>a.onclick=async()=>{const el=a.previousElementSibling;
    if(el.dataset.shown){el.textContent='●●●●●●';delete el.dataset.shown;a.textContent='显示';return}
    try{el.textContent=await secret(el);el.dataset.shown=1;a.textContent='隐藏'}catch(e){toast(e.message)}});
  app.querySelectorAll('[data-copy]').forEach(a=>a.onclick=async()=>{try{await navigator.clipboard.writeText(await secret(a.parentElement.querySelector('[data-sv]')));toast('已复制')}catch(e){toast(e.message)}});
  const edit=e=>{
    const fs=e?e['字段']:[{'名':'账号','值':'','机密':false},{'名':'密码','值':'','机密':true}];
    const row=f=>`<div class="frow"><input type="text" class="fN" placeholder="字段名，如 账号 / 密码 / 代理地址" value="${esc(f['名'])}">
      <input type="${f['机密']?'password':'text'}" class="fV" placeholder="${f['机密']&&e?'留空 = 不修改':'值'}" value="${esc(f['机密']?'':f['值'])}">
      <label class="small row"><input type="checkbox" class="fS" ${f['机密']?'checked':''}>机密</label><a class="small" data-del>删除</a></div>`;
    openDlg(e?'编辑 '+e['编号']:'新增基础信息',`<div class="form">
      <label>分类<select id="bC">${d.cats.map(c=>`<option ${e&&e['分类']===c?'selected':''}>${c}</option>`).join('')}</select></label>
      <label>名称<input type="text" id="bN" value="${esc(e?e['名称']:'')}" placeholder="如：测试账号（国内）/ 办公室 Wi-Fi / 抓包代理"></label>
      <label>适用（产品 / 场景，可空）<input type="text" id="bS" value="${esc(e?e['适用']:'')}" placeholder="如：国内版 / 测试环境 / 所有产品"></label>
      <div><div class="small mut" style="margin-bottom:4px">字段（勾选「机密」的单独加密保存）</div><div id="bF" style="display:grid;gap:6px">${fs.map(row).join('')}</div>
        <a class="small" id="bFA" style="display:inline-block;margin-top:6px">＋ 添加字段</a></div>
      <label>备注（可空，支持 Markdown）<textarea id="bR" rows="3" placeholder="如：用之前先连公司 VPN；密码每月 1 号更换">${esc(e?e['备注']:'')}</textarea></label>
      <div class="row"><button class="pri" id="bGo">保存</button>${e?'<button class="danger" id="bDel">删除这条</button>':''}</div></div>`);
    const bind=()=>{$('#bF').querySelectorAll('[data-del]').forEach(a=>a.onclick=()=>a.parentElement.remove());
      $('#bF').querySelectorAll('.fS').forEach(c=>c.onchange=()=>c.closest('.frow').querySelector('.fV').type=c.checked?'password':'text')};
    bind();$('#bFA').onclick=()=>{$('#bF').insertAdjacentHTML('beforeend',row({'名':'','值':'','机密':false}));bind()};
    $('#bGo').onclick=async()=>{const fields=[...$('#bF').querySelectorAll('.frow')].map(r=>({'名':r.querySelector('.fN').value.trim(),'值':r.querySelector('.fV').value,'机密':r.querySelector('.fS').checked})).filter(f=>f['名']);
      try{const r=await post('/api/base/save',{id:e?e['编号']:'',category:$('#bC').value,name:$('#bN').value,scope:$('#bS').value,note:$('#bR').value,fields});dlg.close();toast(r.msg.split('\n')[0]);render()}catch(x){toast(x.message)}};
    if(e)$('#bDel').onclick=async()=>{if(!confirm('删除「'+e['名称']+'」？机密字段也会一起删除。'))return;
      try{const r=await post('/api/base/save',{id:e['编号'],delete:true});dlg.close();toast(r.msg);render()}catch(x){toast(x.message)}};
    $('#bN').focus()};
  $('#bAdd').onclick=()=>edit(null);
  app.querySelectorAll('[data-edit]').forEach(a=>a.onclick=()=>edit(es.find(x=>x['编号']===a.dataset.edit)));
}
