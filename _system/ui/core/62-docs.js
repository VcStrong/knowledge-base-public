// ==== Markdown 渲染、文档页
// 轻量 Markdown 渲染：标题、列表（可嵌套）、表格、代码块、引用、行内代码 / 粗体 / 链接
function mdInline(t){
  const codes=[];t=esc(t).replace(/`([^`]+)`/g,(_,c)=>{codes.push(c);return '\u0000'+(codes.length-1)+'\u0000'});
  t=t.replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>')
     .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g,(_,a,u)=>`<a href="${u}" target="_blank" rel="noopener">${a}</a>`)
     .replace(/(^|[\s（(：:])(https?:\/\/[^\s<）)，。]+)/g,'$1<a href="$2" target="_blank" rel="noopener">$2</a>');
  return t.replace(/\u0000(\d+)\u0000/g,(_,i)=>`<code>${codes[i]}</code>`);
}
function md(src){
  const L=src.replace(/\r/g,'').split('\n'),out=[],toc=[];let i=0;
  const isList=l=>/^\s*([-*+]|\d+\.)\s+/.test(l);
  while(i<L.length){
    const l=L[i];
    if(/^```/.test(l)){const b=[];i++;while(i<L.length&&!/^```/.test(L[i]))b.push(L[i++]);i++;out.push(`<pre><code>${esc(b.join('\n'))}</code></pre>`);continue}
    let m=l.match(/^(#{1,4})\s+(.*)$/);
    if(m){const n=m[1].length,id='h'+toc.length;toc.push({n,id,t:m[2].replace(/[`*]/g,'')});out.push(`<h${n} id="${id}">${mdInline(m[2])}</h${n}>`);i++;continue}
    if(/^\s*(---+|\*\*\*+)\s*$/.test(l)){out.push('<hr>');i++;continue}
    if(/^>/.test(l)){const b=[];while(i<L.length&&/^>/.test(L[i]))b.push(L[i++].replace(/^>\s?/,''));out.push(`<blockquote>${b.map(mdInline).join('<br>')}</blockquote>`);continue}
    if(/^\|/.test(l)&&i+1<L.length&&/^\|?\s*:?-+/.test(L[i+1])){
      const row=r=>r.trim().replace(/^\||\|$/g,'').split(/(?<!\\)\|/).map(c=>mdInline(c.trim().replace(/\\\|/g,'|')));
      const h=row(l);i+=2;const rs=[];while(i<L.length&&/^\|/.test(L[i]))rs.push(row(L[i++]));
      out.push(`<div class="tw"><table><tr>${h.map(c=>`<th>${c}</th>`).join('')}</tr>${rs.map(r=>`<tr>${r.map(c=>`<td>${c}</td>`).join('')}</tr>`).join('')}</table></div>`);continue}
    if(isList(l)){
      const items=[];while(i<L.length&&(isList(L[i])||(/^\s{2,}\S/.test(L[i])&&items.length))){
        const mm=L[i].match(/^(\s*)([-*+]|\d+\.)\s+(.*)$/);
        if(mm)items.push({d:Math.floor(mm[1].length/2),o:/\d/.test(mm[2]),t:mm[3]});else items[items.length-1].t+=' '+L[i].trim();i++}
      let h='',st=[];
      for(const it of items){
        while(st.length>it.d+1)h+=`</li></${st.pop()}>`;
        if(st.length<it.d+1){const tg=it.o?'ol':'ul';h+=`<${tg}>`;st.push(tg)}else h+='</li>';
        h+=`<li>${mdInline(it.t)}`}
      while(st.length)h+=`</li></${st.pop()}>`;out.push(h);continue}
    if(!l.trim()){i++;continue}
    const p=[];while(i<L.length&&L[i].trim()&&!/^(#{1,4}\s|```|>|\|)/.test(L[i])&&!isList(L[i]))p.push(L[i++]);
    out.push(`<p>${p.map(mdInline).join('<br>')}</p>`);
  }
  return {html:out.join('\n'),toc};
}
async function docs(name){
  const list=(await api('/api/docs')).docs;
  if(!list.length){app.innerHTML='<p class="mut">知识库根目录下还没有说明文档（.md）。</p>';return}
  const cur=list.find(x=>x.name===name)||list[0];
  const d=await api('/api/doc?name='+enc(cur.name)),r=md(d.text);
  app.innerHTML=`<div class="docs"><nav class="dnav">${list.map(x=>`<a href="#/d/${enc(x.name)}" class="${x.name===cur.name?'on':''}">${esc(x.name)}</a>
    ${x.name===cur.name?`<div class="toc">${r.toc.filter(t=>t.n>1&&t.n<4).map(t=>`<a class="h${t.n}" data-id="${t.id}">${esc(t.t)}</a>`).join('')}</div>`:''}`).join('')}</nav>
    <article class="md">${r.html}<p class="mut small" style="margin-top:24px">${esc(d.path)}　·　更新于 ${when(d.mtime)}</p></article></div>`;
  app.querySelectorAll('.toc a').forEach(a=>a.onclick=()=>document.getElementById(a.dataset.id).scrollIntoView({behavior:'smooth'}));
}

