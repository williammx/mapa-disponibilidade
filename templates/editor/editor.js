var W=__W__,H=__H__,INIT=__DATA__,NS="http://www.w3.org/2000/svg",NAMES=["Disponivel","Vendido","Reservado","Bloqueado"],STATUS_KEYS=["disponivel","vendido","reservado","bloqueado"],statusColors=["#26d07c","#6e6d67","#e0613b","#7c838b"];
var app=document.getElementById('app'),mapSettings={opacity:__OPACITY__,strokeWidth:__STROKE__,labelMode:__LABEL_MODE__,imgMime:__IMG_MIME_JSON__};
  [['sideToggle','Mostrar ou ocultar a lista'],['zin','Aumentar zoom'],['zout','Diminuir zoom'],['zr','Repor zoom'],['clearSel','Limpar selecao'],['selectVisible','Selecionar lotes visiveis'],['csvBtn','Baixar dados CSV'],['edt','Ativar edicao'],['edundo','Desfazer ultima alteracao'],['edredo','Refazer ultima alteracao'],
  ['lotSearch','Buscar lote, quadra ou area'],['edsel','Ferramenta selecionar lotes (V)'],['edmove','Ferramenta mover lotes (M)'],['edvertex','Editar os pontos do lote (P)'],['eddraw','Desenhar um novo lote (D)'],['eddel','Apagar lotes'],['edgroup','Agrupar lotes selecionados (G)'],['edungroup','Desagrupar lotes (Shift+G)'],['eddl','Baixar HTML editado'],
  ['lr','Angulo da camada de lotes'],['lrm','Girar camada 0,5 grau para a esquerda'],['lrp','Girar camada 0,5 grau para a direita'],['lr0','Repor angulo e posicao da camada'],['lmove','Mover a camada arrastando o mapa'],['lmleft','Mover camada para a esquerda'],['lmright','Mover camada para a direita'],['lmup','Mover camada para cima'],['lmdown','Mover camada para baixo'],
  ['draftRestore','Restaurar o rascunho local'],['draftDiscard','Descartar o rascunho local']].forEach(function(pair){var b=document.getElementById(pair[0]);if(b)b.setAttribute('aria-label',pair[1]);});
  var svg=document.getElementById('map'),g=document.getElementById('lots'),gl=document.getElementById('labels'),gd=document.getElementById('draft'),gv=document.getElementById('vertices'),gui=document.getElementById('ui'),listEl=document.getElementById('lotList'),editor=document.getElementById('editor');
  function norm(d,i){if(Array.isArray(d)){return{s:+d[0]||0,pts:d[1]||'',color:statusColors[+d[0]||0],nome:'Lote '+(i+1),quadra:'',area:'',group:'',extraido:false,index:i};}return{s:+(d.s||0),pts:d.pts||'',color:d.color||statusColors[+(d.s||0)],nome:d.nome||('Lote '+(i+1)),quadra:d.quadra||'',area:d.area||'',group:d.group||'',extraido:!!d.extraido,index:d.index==null?i:d.index};}
  function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c];});}
  var L=INIT.map(norm),filterMode='all',query='';
  var toastTimer=null;function toast(message,error){var box=document.getElementById('toast');box.textContent=message;box.classList.toggle('error',!!error);box.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(function(){box.classList.remove('show');},2200);}
  function groupMembers(group){var out=[];if(!group)return out;for(var i=0;i<L.length;i++)if(L[i].group===group)out.push(i);return out;}
  function selectionHasGroup(){var yes=false;selected.forEach(function(i){if(L[i]&&L[i].group)yes=true;});return yes;}
  var selected=new Set(),editMode=false,tool="select",curStatus=1,draft=[],sel=null,dragSel=false,dragStart=null,dragRect=null,groupCounter=0;
  var moveDrag=false,movePrevious=null,vertexDrag=null,moveOp=null;
var lotsrot=document.getElementById("lotsrot"),R=0,tx=0,ty=0,moveMode=false,cxi=W/2,cyi=H/2;
function applyLotRot(){lotsrot.setAttribute("transform","translate("+tx+" "+ty+") rotate("+R+" "+cxi+" "+cyi+")");document.getElementById("lrval").textContent=R.toFixed(1)+"\u00b0";document.getElementById("lr").value=R;document.getElementById("xyval").textContent=Math.round(tx)+","+Math.round(ty)+" px";updateLabelVisibility();markDirty();}
function toLocal(p){var x=p.x-tx,y=p.y-ty,t=-R*Math.PI/180,c=Math.cos(t),si=Math.sin(t),dx=x-cxi,dy=y-cyi;return{x:cxi+dx*c-dy*si,y:cyi+dx*si+dy*c};}
function fromLocal(p){var t=R*Math.PI/180,c=Math.cos(t),si=Math.sin(t),dx=p.x-cxi,dy=p.y-cyi;return{x:tx+cxi+dx*c-dy*si,y:ty+cyi+dx*si+dy*c};}
function bakePts(str){return str.split(' ').filter(Boolean).map(function(pair){var a=pair.split(','),p=fromLocal({x:parseFloat(a[0]),y:parseFloat(a[1])});return p.x.toFixed(1)+','+p.y.toFixed(1);}).join(' ');}
  function currentLots(){return L.map(function(o,i){return{s:o.s,pts:bakePts(o.pts),color:o.color,nome:o.nome,quadra:o.quadra,area:o.area,group:o.group||'',extraido:o.extraido,index:o.index==null?i:o.index};});}
function currentPayload(){return{img:svg.querySelector('image').getAttribute('href').split(',')[1],img_mime:mapSettings.imgMime,w:W,h:H,title:(document.getElementById('title').childNodes[0].textContent||'mapa').trim(),lots:currentLots(),opacity:mapSettings.opacity,stroke_width:mapSettings.strokeWidth,label_mode:mapSettings.labelMode};}
window.getMapaPayload=currentPayload;
function el(t){return document.createElementNS(NS,t);}
function labelText(o,i){var n=(o.nome||'').trim();return n&&!/^Lote\s+\d+$/i.test(n)?n:'#'+(i+1);}
function localCenter(i){var pts=ptsArray(L[i].pts);if(pts.length>1){var a=pts[0],b=pts[pts.length-1];if(Math.abs(a.x-b.x)<.01&&Math.abs(a.y-b.y)<.01)pts.pop();}if(!pts.length)return{x:0,y:0};var sx=0,sy=0;pts.forEach(function(p){sx+=p.x;sy+=p.y;});return{x:sx/pts.length,y:sy/pts.length};}
function cachedCenter(i){var o=L[i];if(!o)return{x:0,y:0};if(o._cx==null||o._cy==null){var c=localCenter(i);o._cx=c.x;o._cy=c.y;}return{x:o._cx,y:o._cy};}
function updateLotStyle(i){var o=L[i];if(!o)return;var p=g.querySelector('polygon[data-i="'+i+'"]');if(p){p.dataset.s=o.s;p.setAttribute('class','lot'+(selected.has(i)?' sel':''));p.style.fill=o.color;}var t=gl.querySelector('text[data-i="'+i+'"]');if(t)t.textContent=labelText(o,i);}
  function syncSelection(){Array.prototype.forEach.call(g.children,function(p){var i=parseInt(p.dataset.i);p.classList.toggle('sel',selected.has(i));});Array.prototype.forEach.call(listEl.querySelectorAll('.lotrow'),function(r){r.classList.toggle('on',selected.has(parseInt(r.dataset.i)));});counts();renderEditor();redrawVertices();}
function applyMapStyle(){mapSettings.opacity=Math.max(.2,Math.min(1,parseFloat(mapSettings.opacity)||.7));mapSettings.strokeWidth=Math.max(.2,Math.min(2.5,parseFloat(mapSettings.strokeWidth)||.6));app.style.setProperty('--lot-opacity',mapSettings.opacity.toFixed(2));app.style.setProperty('--lot-stroke',mapSettings.strokeWidth.toFixed(1)+'px');document.getElementById('opacityVal').textContent=Math.round(mapSettings.opacity*100)+'%';document.getElementById('strokeVal').textContent=mapSettings.strokeWidth.toFixed(1)+'px';updateLabelVisibility();markDirty();}
var labelFrame=0,labelLimit=420,labelIdleTimer=null,fastMapTimer=null;
function clearLabels(){while(gl.firstChild)gl.removeChild(gl.firstChild);}
function suspendLabels(){clearTimeout(labelIdleTimer);gl.style.display='none';clearLabels();labelIdleTimer=setTimeout(function(){updateLabelVisibility(true);},180);}
function suspendMapDetails(){clearTimeout(fastMapTimer);suspendLabels();lotsrot.style.visibility='hidden';fastMapTimer=setTimeout(function(){lotsrot.style.visibility='';updateLabelVisibility(true);},180);}
function renderVisibleLabels(){
  labelFrame=0;
  var show=mapSettings.labelMode==='always'||(mapSettings.labelMode==='auto'&&vb.w<=W*.38);
  if(!show){gl.style.display='none';clearLabels();return;}
  gl.style.display='';
  var pad=Math.max(30,vb.w*.08),x0=vb.x-pad,y0=vb.y-pad,x1=vb.x+vb.w+pad,y1=vb.y+vb.h+pad;
  var max=mapSettings.labelMode==='always'?650:labelLimit,keep={},made=0;
  for(var i=0;i<L.length&&made<max;i++){
    var c=cachedCenter(i),p=fromLocal(c);
    if(p.x<x0||p.x>x1||p.y<y0||p.y>y1)continue;
    keep[i]=true;made++;
    var t=gl.querySelector('text[data-i="'+i+'"]');
    if(!t){t=el('text');t.setAttribute('class','lotlabel');t.dataset.i=i;gl.appendChild(t);}
    t.setAttribute('x',c.x.toFixed(1));t.setAttribute('y',c.y.toFixed(1));t.textContent=labelText(L[i],i);
  }
  Array.prototype.slice.call(gl.children).forEach(function(t){if(!keep[t.dataset.i])gl.removeChild(t);});
}
function updateLabelVisibility(force){if(typeof vb==='undefined')return;if(force)labelFrame=0;if(labelFrame)return;labelFrame=requestAnimationFrame(renderVisibleLabels);}
  function redraw(){while(g.firstChild)g.removeChild(g.firstChild);clearLabels();for(var i=0;i<L.length;i++){var p=el('polygon');p.setAttribute('points',L[i].pts);p.setAttribute('class','lot'+(selected.has(i)?' sel':''));p.dataset.i=i;p.dataset.s=L[i].s;p.style.fill=L[i].color;cachedCenter(i);g.appendChild(p);}counts();renderList();renderEditor();redrawVertices();updateLabelVisibility();}
  function updateCanvasStatus(){var box=document.getElementById('canvasStatus');if(!box)return;var selectedText=selected.size?selected.size+' lote'+(selected.size>1?'s':'')+' selecionado'+(selected.size>1?'s':''):'nenhum lote';var mode='Pan: arraste o mapa · Zoom: scroll';if(editMode){if(tool==='select')mode='Selecionar: clique no lote ou arraste uma caixa';else if(tool==='move')mode='Mover: arraste a selecao no mapa';else if(tool==='vertex')mode='Pontos: arraste vertices do lote selecionado';else if(tool==='draw')mode='Desenhar: clique nos cantos e Enter para concluir';else if(tool==='delete')mode='Apagar: clique em um lote para remover';else if(TOOLS[tool]&&typeof TOOLS[tool].status==='function')mode=TOOLS[tool].status();}box.textContent=mode+' · '+selectedText;}
  function counts(){var n=[0,0,0];for(var i=0;i<L.length;i++)n[L[i].s]++;document.getElementById('n0').textContent=n[0];document.getElementById('n1').textContent=n[1];document.getElementById('n2').textContent=n[2];document.getElementById('cnt').textContent=selected.size?(selected.size+' selecionado'+(selected.size>1?'s':'')):'lista editavel';var summary=document.getElementById('selectionSummary');if(summary){summary.textContent=selected.size?(selected.size+' lote'+(selected.size>1?'s':'')):'Nenhum lote';summary.classList.toggle('active',selected.size>0);}var groupBtn=document.getElementById('edgroup'),ungroupBtn=document.getElementById('edungroup'),vertexBtn=document.getElementById('edvertex'),moveBtn=document.getElementById('edmove');if(groupBtn)groupBtn.disabled=selected.size<2;if(ungroupBtn)ungroupBtn.disabled=!selectionHasGroup();if(vertexBtn)vertexBtn.disabled=selected.size!==1;if(moveBtn)moveBtn.disabled=!selected.size;updateCanvasStatus();}
var listTimer=null;function scheduleListRender(){clearTimeout(listTimer);listTimer=setTimeout(renderList,80);}
function matches(i){var o=L[i],hay=(o.nome+' '+o.quadra+' '+o.area+' '+NAMES[o.s]).toLowerCase();if(query&&hay.indexOf(query)<0)return false;if(filterMode==='missing')return !o.extraido||/^Lote \d+$/.test(o.nome);if(filterMode!=='all'&&String(o.s)!==filterMode)return false;return true;}
function renderList(){var frag=document.createDocumentFragment(),visible=0;for(var i=0;i<L.length;i++){if(!matches(i))continue;visible++;var o=L[i],b=document.createElement('button');b.className='lotrow'+(selected.has(i)?' on':'');b.dataset.i=i;b.innerHTML='<span class="sw" style="background:'+esc(o.color)+'"></span><span><span class="lt">'+esc((o.quadra?o.quadra+' \u00b7 ':'')+o.nome)+'</span><span class="lm">'+esc((o.area||'sem area')+' \u00b7 '+NAMES[o.s]+(o.group?' \u00b7 agrupado':''))+'</span></span><span class="tag">#'+(i+1)+'</span>';b.onclick=function(e){selectIndex(+this.dataset.i,e.shiftKey);};frag.appendChild(b);}listEl.replaceChildren(frag);document.getElementById('listCount').textContent=visible;}
var listWindowFrame=0,listMatches=[],LIST_ROW_H=54;
function renderListWindow(){if(!listEl.firstChild)return;var inner=listEl.firstChild,start=Math.max(0,Math.floor(listEl.scrollTop/LIST_ROW_H)-6),end=Math.min(listMatches.length,start+Math.ceil((listEl.clientHeight||400)/LIST_ROW_H)+12),frag=document.createDocumentFragment();for(var k=start;k<end;k++){var i=listMatches[k],o=L[i],b=document.createElement('button');b.className='lotrow'+(selected.has(i)?' on':'');b.dataset.i=i;b.style.top=(k*LIST_ROW_H+3)+'px';b.style.height=(LIST_ROW_H-6)+'px';b.innerHTML='<span class="sw" style="background:'+esc(o.color)+'"></span><span><span class="lt">'+esc((o.quadra?o.quadra+' \u00b7 ':'')+o.nome)+'</span><span class="lm">'+esc((o.area||'sem area')+' \u00b7 '+NAMES[o.s]+(o.group?' \u00b7 agrupado':''))+'</span></span><span class="tag">#'+(i+1)+'</span>';b.onclick=function(e){selectIndex(+this.dataset.i,e.shiftKey);};frag.appendChild(b);}inner.replaceChildren(frag);}
function scheduleListWindow(){if(listWindowFrame)return;listWindowFrame=requestAnimationFrame(function(){listWindowFrame=0;renderListWindow();});}
function renderList(){listMatches=[];for(var i=0;i<L.length;i++){if(matches(i))listMatches.push(i);}var inner=document.createElement('div');inner.style.position='relative';inner.style.height=(listMatches.length*LIST_ROW_H)+'px';listEl.replaceChildren(inner);document.getElementById('listCount').textContent=listMatches.length;renderListWindow();}
listEl.addEventListener('scroll',scheduleListWindow,{passive:true});
function firstSelected(){var a=Array.from(selected);return a.length?a[0]:null;}
function renderEditor(){
  var idx=firstSelected();
  if(idx==null||!L[idx]){editor.classList.remove('show');editor.innerHTML='<div class="empty">Selecione um lote.</div>';return;}
  var o=L[idx],multi=selected.size>1,grouped=selectionHasGroup(),badge=grouped?'Grupo ativo':(multi?selected.size+' lotes':'Lote #'+(idx+1));
  editor.classList.add('show');
  editor.innerHTML='<div class="selectionHead"><strong>'+(multi?selected.size+' lotes selecionados':esc(o.nome))+'</strong><span class="selectionHeadActions"><span class="groupBadge">'+badge+'</span><button class="inspectorClose" id="clearInspector" title="Fechar inspetor" aria-label="Fechar inspetor">&times;</button></span></div><div class="inspectorSection">Dados do lote</div><div class="formgrid"><label class="field full">Nome do lote<input id="lotName" '+(multi?'disabled ':'')+'value="'+esc(multi?selected.size+' lotes selecionados':o.nome)+'"></label><label class="field">Quadra<input id="lotQuadra" '+(multi?'disabled ':'')+'value="'+esc(o.quadra)+'"></label><label class="field">Area<input id="lotArea" '+(multi?'disabled ':'')+'value="'+esc(o.area)+'"></label><label class="field">Status<select id="lotStatus"><option value="0">Disponivel</option><option value="1">Vendido</option><option value="2">Reservado</option></select></label><label class="field">Cor<input id="lotColor" type="color" value="'+esc(o.color)+'"></label></div><div class="inspectorSection">Geometria e grupo</div><div class="editBtns"><button id="zoomLot" class="primary">Enquadrar</button><button id="editPoints" '+(multi?'disabled':'')+'>Pontos</button><button id="dupLot" '+(multi?'disabled':'')+'>Duplicar</button><button id="groupLots" '+(selected.size<2?'disabled':'')+'>Agrupar</button><button id="ungroupLots" '+(!grouped?'disabled':'')+'>Desagrupar</button><button id="delLot" class="danger">Apagar</button></div><div class="nudgeRow"><span>Mover selecao</span><div class="nudgeGrid"><button data-nudge="-1,0" title="Mover para esquerda" aria-label="Mover selecao para a esquerda">&#8592;</button><button data-nudge="0,-1" title="Mover para cima" aria-label="Mover selecao para cima">&#8593;</button><button data-nudge="0,1" title="Mover para baixo" aria-label="Mover selecao para baixo">&#8595;</button><button data-nudge="1,0" title="Mover para direita" aria-label="Mover selecao para a direita">&#8594;</button></div></div>';
  document.getElementById('clearInspector').onclick=function(){selected.clear();syncSelection();};
  document.getElementById('lotStatus').value=o.s;
  if(!multi){
    [['lotName','nome'],['lotQuadra','quadra'],['lotArea','area']].forEach(function(pair){document.getElementById(pair[0]).onfocus=function(){beginLivePatch([idx],[pair[1]]);};});
    document.getElementById('lotName').oninput=function(){o.nome=this.value;sealLivePatch();updateLotStyle(idx);scheduleListRender();};
    document.getElementById('lotQuadra').oninput=function(){o.quadra=this.value;sealLivePatch();scheduleListRender();};
    document.getElementById('lotArea').oninput=function(){o.area=this.value;sealLivePatch();scheduleListRender();};
    document.getElementById('dupLot').onclick=function(){var cp=JSON.parse(JSON.stringify(o));cp.nome=cp.nome+' copia';cp.group='';L.splice(idx+1,0,cp);pushHist({k:'insert',at:idx+1,item:cp});selected.clear();selected.add(idx+1);redraw();toast('Lote duplicado');};
  }
  document.getElementById('lotStatus').onchange=function(){applyStatusToSelection(+this.value);};
  document.getElementById('lotColor').onpointerdown=function(){beginLivePatch(Array.from(selected),['color']);};
  document.getElementById('lotColor').oninput=function(){var color=this.value;selected.forEach(function(i){if(L[i]){L[i].color=color;updateLotStyle(i);}});sealLivePatch();scheduleListRender();};
  document.getElementById('zoomLot').onclick=zoomToSelection;
  document.getElementById('editPoints').onclick=function(){setTool('vertex');};
  document.getElementById('groupLots').onclick=groupSelected;
  document.getElementById('ungroupLots').onclick=ungroupSelected;
  document.getElementById('delLot').onclick=function(){deleteSelection();};
  Array.prototype.forEach.call(editor.querySelectorAll('[data-nudge]'),function(button){button.onclick=function(){var d=this.dataset.nudge.split(',');nudgeSelection(+d[0],+d[1]);};});
}
function ptsArray(str){return str.split(' ').filter(Boolean).map(function(pair){var a=pair.split(',');return{x:+a[0],y:+a[1]};});}
function zoomToLot(i){var pts=ptsArray(L[i].pts);if(!pts.length)return;var xs=pts.map(function(p){return p.x;}),ys=pts.map(function(p){return p.y;}),minx=Math.min.apply(null,xs),maxx=Math.max.apply(null,xs),miny=Math.min.apply(null,ys),maxy=Math.max.apply(null,ys),pad=Math.max(40,(maxx-minx+maxy-miny)*.9);vb={x:minx-pad,y:miny-pad,w:Math.max(120,maxx-minx+pad*2),h:Math.max(120,maxy-miny+pad*2)};ap();}
function zoomToSelection(){var all=[];selected.forEach(function(i){if(L[i])all=all.concat(ptsArray(L[i].pts));});if(!all.length)return;var xs=all.map(function(p){return p.x;}),ys=all.map(function(p){return p.y;}),minx=Math.min.apply(null,xs),maxx=Math.max.apply(null,xs),miny=Math.min.apply(null,ys),maxy=Math.max.apply(null,ys),pad=Math.max(30,(maxx-minx+maxy-miny)*.24);vb={x:minx-pad,y:miny-pad,w:Math.max(100,maxx-minx+pad*2),h:Math.max(100,maxy-miny+pad*2)};ap();}
function csv(){var rows=[['index','quadra','lote','area','status','cor','grupo','pontos']].concat(currentLots().map(function(o,i){return[i,o.quadra,o.nome,o.area,STATUS_KEYS[o.s],o.color,o.group||'',o.pts];}));return rows.map(function(r){return r.map(function(v){return '"'+String(v==null?'':v).replace(/"/g,'""')+'"';}).join(',');}).join('\n');}
document.getElementById('lotSearch').oninput=function(){query=this.value.toLowerCase().trim();scheduleListRender();};Array.prototype.forEach.call(document.querySelectorAll('.filter button'),function(b){b.onclick=function(){filterMode=this.dataset.f;Array.prototype.forEach.call(document.querySelectorAll('.filter button'),function(x){x.classList.remove('on');});this.classList.add('on');scheduleListRender();};});
function setSidePanel(name){Array.prototype.forEach.call(document.querySelectorAll('.sideTab'),function(button){var active=button.dataset.panel===name;button.classList.toggle('on',active);button.setAttribute('aria-pressed',String(active));});['lots','visual','align'].forEach(function(panel){document.getElementById('panel'+panel.charAt(0).toUpperCase()+panel.slice(1)).hidden=panel!==name;});}
Array.prototype.forEach.call(document.querySelectorAll('.sideTab'),function(button){button.onclick=function(){setSidePanel(this.dataset.panel);};});
Array.prototype.forEach.call(document.querySelectorAll('[data-pal]'),function(inp){inp.onpointerdown=function(){var s=+this.dataset.pal,idx=[];for(var i=0;i<L.length;i++)if(L[i].s===s)idx.push(i);beginLivePatch(idx,['color']);};inp.oninput=function(){var s=+this.dataset.pal;statusColors[s]=this.value;this.parentElement.querySelector('.sw').style.background=this.value;L.forEach(function(o,i){if(o.s===s){o.color=statusColors[s];updateLotStyle(i);}});sealLivePatch();scheduleListRender();};});
document.getElementById('opacityCtrl').oninput=function(){mapSettings.opacity=parseInt(this.value,10)/100;applyMapStyle();};
document.getElementById('strokeCtrl').oninput=function(){mapSettings.strokeWidth=parseFloat(this.value);applyMapStyle();};
document.getElementById('labelMode').value=mapSettings.labelMode;
document.getElementById('labelMode').onchange=function(){mapSettings.labelMode=this.value;updateLabelVisibility();markDirty();};
document.getElementById('csvBtn').onclick=function(){var a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv()],{type:'text/csv;charset=utf-8'}));a.download='lotes.csv';a.click();};
document.getElementById('selectVisible').onclick=function(){selected=new Set(listMatches);expandSelectedGroups();syncSelection();toast(selected.size+' lotes selecionados');};
document.getElementById('clearSel').onclick=function(){selected.clear();document.getElementById('info').style.display='none';syncSelection();};
function setSideClosed(closed){document.getElementById('side').classList.toggle('closed',closed);app.classList.toggle('side-closed',closed);document.getElementById('sideToggle').setAttribute('aria-expanded',String(!closed));}
document.getElementById('sideToggle').onclick=function(){setSideClosed(!document.getElementById('side').classList.contains('closed'));};
document.getElementById('sideScrim').onclick=function(){setSideClosed(true);};
var vb={x:0,y:0,w:W,h:H},viewFrame=0;function ap(){if(viewFrame)return;viewFrame=requestAnimationFrame(function(){viewFrame=0;svg.setAttribute('viewBox',vb.x+' '+vb.y+' '+vb.w+' '+vb.h);updateLabelVisibility();redrawVertices();});}
function c2s(px,py){var r=svg.getBoundingClientRect(),sc=Math.min(r.width/vb.w,r.height/vb.h);var ox=(r.width-vb.w*sc)/2,oy=(r.height-vb.h*sc)/2;return{x:vb.x+(px-r.left-ox)/sc,y:vb.y+(py-r.top-oy)/sc};}
function zoomAt(px,py,f){suspendLabels();var p=c2s(px,py),nw=vb.w*f;nw=Math.max(W*0.03,Math.min(W*2.5,nw));var rf=nw/vb.w;vb.x=p.x-(p.x-vb.x)*rf;vb.y=p.y-(p.y-vb.y)*rf;vb.w=nw;vb.h=vb.h*rf;ap();}
function lotCenter(i){var pts=L[i].pts.split(' ').filter(Boolean),sx=0,sy=0,n=0;pts.forEach(function(pair){var a=pair.split(',');sx+=parseFloat(a[0]);sy+=parseFloat(a[1]);n++;});return fromLocal({x:sx/n,y:sy/n});}
function setLotPoints(i,points){if(!L[i])return;L[i].pts=points.map(function(p){return p.x.toFixed(1)+','+p.y.toFixed(1);}).join(' ');L[i]._cx=null;L[i]._cy=null;var poly=g.querySelector('polygon[data-i="'+i+'"]');if(poly)poly.setAttribute('points',L[i].pts);var text=gl.querySelector('text[data-i="'+i+'"]');if(text){var c=cachedCenter(i);text.setAttribute('x',c.x);text.setAttribute('y',c.y);}}
function translateSelection(dx,dy,record){if(!selected.size)return;var op=record?beginPatch(Array.from(selected),['pts']):null;selected.forEach(function(i){setLotPoints(i,ptsArray(L[i].pts).map(function(p){return{x:p.x+dx,y:p.y+dy};}));});if(op)sealPatch(op);redrawVertices();if(record)updateLabelVisibility(true);}
function nudgeSelection(dx,dy){translateSelection(dx,dy,true);}
function redrawVertices(){redrawOverlays();while(gv.firstChild)gv.removeChild(gv.firstChild);if(!editMode||tool!=='vertex'||selected.size!==1)return;var i=firstSelected(),points=ptsArray(L[i].pts);if(points.length>1&&Math.hypot(points[0].x-points[points.length-1].x,points[0].y-points[points.length-1].y)<.01)points.pop();var radius=Math.max(.7,vb.w*.004);points.forEach(function(p,index){var c=el('circle');c.setAttribute('class','vertexpt');c.setAttribute('cx',p.x);c.setAttribute('cy',p.y);c.setAttribute('r',radius);c.dataset.i=i;c.dataset.v=index;gv.appendChild(c);});}
// ---- pontos de extensao das ferramentas ----
// Ferramenta nova (caneta, corte, medicao, transformacao) se registra aqui em
// vez de espalhar if(tool==='x') por setTool, ponteiro e teclado. O spec aceita
// {button:'edpen',cursor:'draw',status:fn,ready:fn,enter:fn,exit:fn,down:fn,
//  move:fn,up:fn,click:fn,key:fn}; down/move/up/click/key devolvem true quando
// ja trataram o evento e o editor nao segue adiante.
var TOOLS={};
function registerTool(name,spec){TOOLS[name]=spec;return spec;}
function toolHook(name,e){var s=TOOLS[tool];return !!(s&&typeof s[name]==='function'&&s[name](e)===true);}
// Camadas extras redesenhadas junto com os vertices: guia do ima, previa da
// caneta, alcas de transformacao. Cada dono se inscreve uma vez.
var overlayHooks=[];
function onOverlayRedraw(fn){overlayHooks.push(fn);}
function redrawOverlays(){for(var n=0;n<overlayHooks.length;n++)overlayHooks[n]();}
// Ima. Sem editor-vector.js carregado o editor funciona como antes: o ponto e o
// deslocamento voltam intactos.
var SNAP={point:function(p){return p;},translation:function(dx,dy){return{x:dx,y:dy};},begin:function(){},end:function(){}};
function setTool(t){var wanted=TOOLS[t];if(wanted&&typeof wanted.ready==='function'&&wanted.ready()!==true)t='select';if(t==='vertex'&&selected.size!==1){toast('Selecione um unico lote para editar os pontos.',true);t='select';}if(t==='move'&&!selected.size){toast('Selecione ao menos um lote para mover.',true);t='select';}var previous=tool;if(previous!==t&&TOOLS[previous]&&typeof TOOLS[previous].exit==='function')TOOLS[previous].exit(t);tool=t;['edsel','edmove','edvertex','eddraw','eddel'].forEach(function(id){var modes={edsel:'select',edmove:'move',edvertex:'vertex',eddraw:'draw',eddel:'delete'},active=modes[id]===t,button=document.getElementById(id);button.classList.toggle('on',active);button.setAttribute('aria-pressed',String(active));});Object.keys(TOOLS).forEach(function(name){var id=TOOLS[name].button,button=id?document.getElementById(id):null;if(button){button.classList.toggle('on',name===t);button.setAttribute('aria-pressed',String(name===t));}});draft=[];redrawDraft();var cursor=(TOOLS[t]&&TOOLS[t].cursor)||'';svg.classList.toggle('draw',editMode&&(t==='draw'||cursor==='draw'));svg.classList.toggle('move-lots',editMode&&(t==='move'||cursor==='move-lots'));svg.classList.toggle('vertex-edit',editMode&&(t==='vertex'||cursor==='vertex-edit'));if(previous!==t&&TOOLS[t]&&typeof TOOLS[t].enter==='function')TOOLS[t].enter(previous);redrawVertices();updateCanvasStatus();}
function clearDragBox(){while(gui.firstChild)gui.removeChild(gui.firstChild);dragRect=null;dragStart=null;dragSel=false;}
function drawDragBox(a,b){while(gui.firstChild)gui.removeChild(gui.firstChild);var r=el('rect'),x=Math.min(a.x,b.x),y=Math.min(a.y,b.y),w=Math.abs(a.x-b.x),h=Math.abs(a.y-b.y);r.setAttribute('x',x);r.setAttribute('y',y);r.setAttribute('width',w);r.setAttribute('height',h);r.setAttribute('class','selectbox');gui.appendChild(r);dragRect={x:x,y:y,w:w,h:h};}
function expandSelectedGroups(){var groups={};selected.forEach(function(i){if(L[i]&&L[i].group)groups[L[i].group]=true;});Object.keys(groups).forEach(function(group){groupMembers(group).forEach(function(i){selected.add(i);});});}
function finishDragBox(add){if(!dragRect)return;var x2=dragRect.x+dragRect.w,y2=dragRect.y+dragRect.h;if(!add)selected.clear();for(var i=0;i<L.length;i++){var c=lotCenter(i);if(c.x>=dragRect.x&&c.x<=x2&&c.y>=dragRect.y&&c.y<=y2)selected.add(i);}expandSelectedGroups();clearDragBox();syncSelection();}
svg.addEventListener('wheel',function(e){e.preventDefault();suspendMapDetails();zoomAt(e.clientX,e.clientY,e.deltaY>0?1.12:.892);},{passive:false});
var ptrs=new Map(),moved=false,dn=null,ld=0,lotPress=false;
svg.addEventListener('pointerdown',function(e){ptrs.set(e.pointerId,{x:e.clientX,y:e.clientY});moved=false;lotPress=false;dn={x:e.clientX,y:e.clientY};var cls=e.target.getAttribute?e.target.getAttribute('class')||'':'';if(cls.indexOf('lot')>=0&&(!editMode||tool==='select'||tool==='vertex'||tool==='delete')){lotPress=true;return;}svg.setPointerCapture(e.pointerId);if(editMode&&toolHook('down',e))return;if(editMode&&tool==='vertex'&&cls.indexOf('vertexpt')>=0){suspendLabels();vertexDrag={i:+e.target.dataset.i,v:+e.target.dataset.v,op:beginPatch([+e.target.dataset.i],['pts'])};SNAP.begin('vertex',[vertexDrag.i]);return;}if(editMode&&tool==='move'){var lot=cls.indexOf('lot')>=0?e.target:null;if(lot){var index=+lot.dataset.i;if(!selected.has(index))selectIndex(index,e.shiftKey);moveOp=beginPatch(Array.from(selected),['pts']);SNAP.begin('move',Array.from(selected));suspendLabels();moveDrag=true;movePrevious=toLocal(c2s(e.clientX,e.clientY));return;}}if(editMode&&tool==='select'){dragSel=true;dragStart=c2s(e.clientX,e.clientY);}});
svg.addEventListener('pointermove',function(e){if(!ptrs.has(e.pointerId))return;var pv=ptrs.get(e.pointerId);ptrs.set(e.pointerId,{x:e.clientX,y:e.clientY});if(lotPress)return;if(dn&&Math.abs(e.clientX-dn.x)+Math.abs(e.clientY-dn.y)>4)moved=true;if(editMode&&toolHook('move',e))return;if(vertexDrag){var point=SNAP.point(toLocal(c2s(e.clientX,e.clientY)),e,{lot:vertexDrag.i,vertex:vertexDrag.v}),points=ptsArray(L[vertexDrag.i].pts),closed=points.length>1&&Math.hypot(points[0].x-points[points.length-1].x,points[0].y-points[points.length-1].y)<.01;points[vertexDrag.v]={x:point.x,y:point.y};if(closed&&vertexDrag.v===0)points[points.length-1]={x:point.x,y:point.y};setLotPoints(vertexDrag.i,points);redrawVertices();return;}if(moveDrag){var current=toLocal(c2s(e.clientX,e.clientY)),step=SNAP.translation(current.x-movePrevious.x,current.y-movePrevious.y,e);translateSelection(step.x,step.y,false);movePrevious=current;return;}if(dragSel&&ptrs.size===1){suspendLabels();drawDragBox(dragStart,c2s(e.clientX,e.clientY));return;}if(ptrs.size===1){suspendMapDetails();var r=svg.getBoundingClientRect(),sc=Math.min(r.width/vb.w,r.height/vb.h);if(moveMode){tx+=(e.clientX-pv.x)/sc;ty+=(e.clientY-pv.y)/sc;applyLotRot();}else{vb.x-=(e.clientX-pv.x)/sc;vb.y-=(e.clientY-pv.y)/sc;ap();}}else if(ptrs.size===2){suspendMapDetails();var ar=Array.from(ptrs.values()),d=Math.hypot(ar[0].x-ar[1].x,ar[0].y-ar[1].y);if(ld)zoomAt((ar[0].x+ar[1].x)/2,(ar[0].y+ar[1].y)/2,ld/d);ld=d;}});
function up(e){if(editMode&&toolHook('up',e)){lotPress=false;ptrs.delete(e.pointerId);if(ptrs.size<2)ld=0;return;}if(dragSel&&moved)finishDragBox(e.shiftKey);else if(dragSel)clearDragBox();if(moveDrag||vertexDrag){SNAP.end();sealPatchOrDrop(vertexDrag?vertexDrag.op:moveOp);moveOp=null;moveDrag=false;movePrevious=null;vertexDrag=null;scheduleListRender();renderEditor();updateLabelVisibility(true);}lotPress=false;ptrs.delete(e.pointerId);if(ptrs.size<2)ld=0;}svg.addEventListener('pointerup',up);svg.addEventListener('pointercancel',up);
// ---- edicao ----
// Historico de operacoes reversiveis. Antes cada passo empilhava JSON.stringify(L)
// inteiro: com 1.182 lotes sao ~450 kB por passo e ~10 MB de historico. Agora cada
// entrada guarda so os lotes tocados (indice + valor antes + valor depois).
var hist=[],future=[],HIST_LIMIT=24,livePatch=null;
function pushHist(op){hist.push(op);if(hist.length>HIST_LIMIT)hist.shift();future=[];markDirty();return op;}
// beginPatch entra no historico ANTES da alteracao (Ctrl+Z precisa funcionar no meio
// de uma digitacao); sealPatch so carimba o valor final de cada lote tocado.
function makePatch(indices,keys){var items=[];for(var n=0;n<indices.length;n++){var i=indices[n],o=L[i];if(!o)continue;var before={},after={};for(var k=0;k<keys.length;k++){before[keys[k]]=o[keys[k]];after[keys[k]]=o[keys[k]];}items.push({i:i,before:before,after:after});}return{k:'patch',keys:keys,items:items};}
function beginPatch(indices,keys){return pushHist(makePatch(indices,keys));}
// Operacao composta: dividir um lote e um patch + um insert, unir e um patch +
// um remove. Sem isto cada uma custaria dois Ctrl+Z e o mapa ficaria no meio do
// caminho. Os passos sao desfeitos na ordem inversa da aplicacao.
function batchOps(ops){var real=[];for(var n=0;n<ops.length;n++)if(ops[n])real.push(ops[n]);return pushHist({k:'batch',ops:real});}
function sealPatch(op){if(!op)return;for(var n=0;n<op.items.length;n++){var it=op.items[n],o=L[it.i];if(!o)continue;for(var k=0;k<op.keys.length;k++)it.after[op.keys[k]]=o[op.keys[k]];}markDirty();}
// Clique sem arrastar nao pode gastar um passo de desfazer: se nada mudou, a
// operacao sai do historico (so quando ela ainda e a ultima).
function sealPatchOrDrop(op){if(!op)return;sealPatch(op);for(var n=0;n<op.items.length;n++)for(var k=0;k<op.keys.length;k++)if(op.items[n].before[op.keys[k]]!==op.items[n].after[op.keys[k]])return;if(hist[hist.length-1]===op){hist.pop();if(livePatch===op)livePatch=null;}}
function beginLivePatch(indices,keys){livePatch=beginPatch(indices,keys);}
function sealLivePatch(){if(livePatch&&hist[hist.length-1]===livePatch)sealPatch(livePatch);else livePatch=null;}
function applyPatch(op,undoing){var resetCenter=op.keys.indexOf('pts')>=0;for(var n=0;n<op.items.length;n++){var it=op.items[n],o=L[it.i];if(!o)continue;var src=undoing?it.before:it.after;for(var k=0;k<op.keys.length;k++)o[op.keys[k]]=src[op.keys[k]];if(resetCenter){o._cx=null;o._cy=null;}}}
function undoOp(op){if(op.k==='batch'){for(var b=op.ops.length-1;b>=0;b--)undoOp(op.ops[b]);}else if(op.k==='patch')applyPatch(op,true);else if(op.k==='insert')L.splice(op.at,1);else if(op.k==='remove')for(var n=0;n<op.items.length;n++)L.splice(op.items[n].i,0,op.items[n].item);}
function redoOp(op){if(op.k==='batch'){for(var b=0;b<op.ops.length;b++)redoOp(op.ops[b]);}else if(op.k==='patch')applyPatch(op,false);else if(op.k==='insert')L.splice(op.at,0,op.item);else if(op.k==='remove')for(var n=op.items.length-1;n>=0;n--)L.splice(op.items[n].i,1);}
function restore(){if(!hist.length){toast('Nao ha alteracoes para desfazer.',true);return;}livePatch=null;var op=hist.pop();undoOp(op);future.push(op);selected.clear();draft=[];redrawDraft();redraw();markDirty();toast('Alteracao desfeita');}
function redo(){if(!future.length){toast('Nao ha alteracoes para refazer.',true);return;}livePatch=null;var op=future.pop();redoOp(op);hist.push(op);selected.clear();draft=[];redrawDraft();redraw();markDirty();toast('Alteracao refeita');}
function selectIndex(i,add){if(!L[i])return;var members=L[i].group?groupMembers(L[i].group):[i],allSelected=members.every(function(index){return selected.has(index);});if(!add)selected.clear();if(add&&allSelected)members.forEach(function(index){selected.delete(index);});else members.forEach(function(index){selected.add(index);});var o=L[i];document.getElementById('ih').textContent=(o.quadra?o.quadra+' \u00b7 ':'')+o.nome;document.getElementById('is').innerHTML='Status: <b>'+NAMES[o.s]+'</b><br>Area: <b>'+(esc(o.area)||'-')+'</b>';document.getElementById('info').style.display='block';syncSelection();}
function groupSelected(){if(selected.size<2){toast('Selecione pelo menos dois lotes.',true);return;}var op=beginPatch(Array.from(selected),['group']),id='grupo-'+Date.now().toString(36)+'-'+(++groupCounter);selected.forEach(function(i){if(L[i])L[i].group=id;});sealPatch(op);scheduleListRender();syncSelection();toast(selected.size+' lotes agrupados');}
function ungroupSelected(){var groups={};selected.forEach(function(i){if(L[i]&&L[i].group)groups[L[i].group]=true;});var names=Object.keys(groups);if(!names.length){toast('A selecao nao possui grupo.',true);return;}var idx=[];for(var i=0;i<L.length;i++)if(L[i].group&&groups[L[i].group])idx.push(i);var op=beginPatch(idx,['group']);idx.forEach(function(i){L[i].group='';});sealPatch(op);scheduleListRender();syncSelection();toast('Grupo removido');}
function applyStatusToSelection(s){if(!selected.size)return;var op=beginPatch(Array.from(selected),['s','color']);selected.forEach(function(i){if(L[i]){L[i].s=s;L[i].color=statusColors[s];updateLotStyle(i);}});sealPatch(op);counts();scheduleListRender();renderEditor();}
function deleteSelection(){if(!selected.size)return;var total=selected.size,removed=[];for(var i=0;i<L.length;i++)if(selected.has(i))removed.push({i:i,item:L[i]});L=L.filter(function(_,i){return !selected.has(i);});pushHist({k:'remove',items:removed});selected.clear();if(tool==='vertex'||tool==='move')setTool('select');redraw();toast(total+' lote'+(total>1?'s':'')+' apagado'+(total>1?'s':''));}
function redrawDraft(){while(gd.firstChild)gd.removeChild(gd.firstChild);if(draft.length){var pl=el('polyline');pl.setAttribute('points',draft.map(function(v){return v.x+','+v.y;}).join(' '));pl.setAttribute('class','draftline');gd.appendChild(pl);draft.forEach(function(v){var c=el('circle');c.setAttribute('cx',v.x);c.setAttribute('cy',v.y);c.setAttribute('r',Math.max(2,vb.w*0.004));c.setAttribute('class','draftpt');gd.appendChild(c);});}}
function finishDraft(){if(draft.length<3){toast('Marque pelo menos tres pontos.',true);return;}var lot={s:curStatus,pts:draft.map(function(v){return v.x.toFixed(1)+','+v.y.toFixed(1);}).join(' '),color:statusColors[curStatus],nome:'Lote '+(L.length+1),quadra:'',area:'',group:'',extraido:false,index:L.length};L.push(lot);pushHist({k:'insert',at:L.length-1,item:lot});selected.clear();selected.add(L.length-1);draft=[];redrawDraft();redraw();toast('Novo lote criado');}
svg.addEventListener('click',function(e){
  if(moved)return;
  var lot=(e.target.getAttribute&&(e.target.getAttribute('class')||'').indexOf('lot')>=0)?e.target:null;
  if(!editMode){ if(lot){selectIndex(parseInt(lot.dataset.i),false);} return; }
  if(toolHook('click',e))return;
  if(tool==='select'){ if(lot)selectIndex(parseInt(lot.dataset.i),e.shiftKey); return; }
  if(tool==='delete'){ if(lot){selectIndex(parseInt(lot.dataset.i),false);deleteSelection();} return; }
  if(tool==='vertex'){if(lot)selectIndex(parseInt(lot.dataset.i),false);return;}
  if(tool==='move'||tool!=='draw')return;
  var p=toLocal(c2s(e.clientX,e.clientY));
  if(draft.length>=3){var f=draft[0];if(Math.hypot(p.x-f.x,p.y-f.y)<vb.w*0.012){finishDraft();return;}}
  draft.push({x:+p.x.toFixed(1),y:+p.y.toFixed(1)});redrawDraft();
});
document.addEventListener('keydown',function(e){if(!editMode)return;var typing=/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)||!!(e.target&&e.target.isContentEditable);if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();if(e.shiftKey)redo();else restore();return;}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='y'){e.preventDefault();redo();return;}if(typing)return;if(toolHook('key',e))return;var key=e.key.toLowerCase();if((e.ctrlKey||e.metaKey)&&key==='a'){e.preventDefault();selected=new Set(listMatches);expandSelectedGroups();syncSelection();return;}if(!e.ctrlKey&&!e.metaKey&&!e.altKey&&(e.key==='1'||e.key==='2'||e.key==='3')){e.preventDefault();chooseStatus(+e.key-1);return;}if(key==='v')setTool('select');if(key==='m')setTool('move');if(key==='p')setTool('vertex');if(key==='d')setTool('draw');if(key==='g'&&!e.shiftKey)groupSelected();if(key==='g'&&e.shiftKey)ungroupSelected();if(e.key==='Enter'&&tool==='draw')finishDraft();if(e.key==='Escape'){draft=[];redrawDraft();clearDragBox();if(tool!=='select')setTool('select');if(selected.size){selected.clear();document.getElementById('info').style.display='none';syncSelection();}return;}
// Apagar durante o desenho tira o ultimo ponto marcado; fora do desenho continua apagando os lotes selecionados.
if((e.key==='Delete'||e.key==='Backspace')&&tool==='draw'&&draft.length){e.preventDefault();draft.pop();redrawDraft();return;}if((e.key==='Delete'||e.key==='Backspace')&&selected.size)deleteSelection();});
function setEdit(on){editMode=on;document.getElementById('edtools').hidden=!on;document.getElementById('edt').classList.toggle('on',on);document.getElementById('edt').setAttribute('aria-pressed',String(on));if(on)setTool('select');else{if(TOOLS[tool]&&typeof TOOLS[tool].exit==='function')TOOLS[tool].exit('select');tool='select';draft=[];redrawDraft();clearDragBox();while(gv.firstChild)gv.removeChild(gv.firstChild);redrawOverlays();svg.classList.remove('draw','move-lots','vertex-edit');updateCanvasStatus();}}
document.getElementById('edt').onclick=function(){setEdit(!editMode);};
function chooseStatus(s){if(!(s>=0&&s<NAMES.length))return;curStatus=s;Array.prototype.forEach.call(document.querySelectorAll('#edit .st'),function(x){x.classList.toggle('on',+x.dataset.s===s);});applyStatusToSelection(s);}
Array.prototype.forEach.call(document.querySelectorAll('#edit .st'),function(b){var s=parseInt(b.dataset.s);b.setAttribute('aria-label','Marcar como '+NAMES[s].toLowerCase()+' (tecla '+(s+1)+')');b.setAttribute('title','Marcar como '+NAMES[s].toLowerCase()+' (tecla '+(s+1)+')');b.onclick=function(){chooseStatus(s);};});
document.getElementById('edsel').onclick=function(){setTool('select');};
document.getElementById('edmove').onclick=function(){setTool('move');};
document.getElementById('edvertex').onclick=function(){setTool('vertex');};
document.getElementById('eddraw').onclick=function(){setTool('draw');};
document.getElementById('eddel').onclick=function(){if(selected.size)deleteSelection();else setTool('delete');};
document.getElementById('edundo').onclick=function(){if(draft.length){draft.pop();redrawDraft();}else restore();};
document.getElementById('edredo').onclick=redo;
document.getElementById('edgroup').onclick=groupSelected;
document.getElementById('edungroup').onclick=ungroupSelected;
document.getElementById('eddl').onclick=function(){fetch('/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(currentPayload())}).then(function(r){if(!r.ok)throw new Error();return r.text();}).then(function(html){var a=document.createElement('a');a.href=URL.createObjectURL(new Blob([html],{type:'text/html'}));a.download='mapa.html';a.click();clearDraft();hideDraftBar();toast('HTML atualizado gerado');}).catch(function(){toast('Nao foi possivel gerar o HTML.',true);});};
document.getElementById('zin').onclick=function(){var r=svg.getBoundingClientRect();zoomAt(r.left+r.width/2,r.top+r.height/2,.8);};
document.getElementById('zout').onclick=function(){var r=svg.getBoundingClientRect();zoomAt(r.left+r.width/2,r.top+r.height/2,1.25);};
document.getElementById('zr').onclick=function(){vb={x:0,y:0,w:W,h:H};ap();document.getElementById('info').style.display='none';if(sel){sel.classList.remove('sel');sel=null;}};
document.getElementById("lr").addEventListener("input",function(){R=parseFloat(this.value);applyLotRot();});
document.getElementById("lrm").onclick=function(){R-=0.5;if(R<-180)R+=360;applyLotRot();};
document.getElementById("lrp").onclick=function(){R+=0.5;if(R>180)R-=360;applyLotRot();};
document.getElementById("lr0").onclick=function(){R=0;tx=0;ty=0;applyLotRot();};
document.getElementById("lmove").onclick=function(){moveMode=!moveMode;this.classList.toggle("on",moveMode);svg.style.cursor=moveMode?"move":"";};
function nudge(dx,dy){tx+=dx;ty+=dy;applyLotRot();}
document.getElementById("lmleft").onclick=function(){nudge(-5,0);};
document.getElementById("lmright").onclick=function(){nudge(5,0);};
document.getElementById("lmup").onclick=function(){nudge(0,-5);};
document.getElementById("lmdown").onclick=function(){nudge(0,5);};
// ---- rascunho local ----
// Autosave por mapa em localStorage, com debounce: quem fechava a aba perdia tudo.
// O rascunho nunca entra sozinho - o que o servidor mandou continua na tela ate o
// operador clicar em Restaurar.
var DRAFT_PREFIX='nexolote:rascunho:',DRAFT_VERSION=1,DRAFT_DEBOUNCE=1200,MAP_BUILT_AT=__GENERATED_AT__;
var draftKey='',draftStore=null,draftTimer=null,draftReady=false,draftBlocked=false;
// No modo visualizador (api.py injeta <style id="shared-viewer">) nao existe edicao:
// nada de gravar rascunho nem de mostrar a barra de restaurar.
function viewerMode(){if(document.getElementById('shared-viewer'))return true;var b=document.getElementById('edt');return !!b&&getComputedStyle(b).display==='none';}
function openDraftStore(){try{var store=window.localStorage;if(!store)return null;var probe=DRAFT_PREFIX+'probe';store.setItem(probe,'1');store.removeItem(probe);return store;}catch(err){return null;}}
function draftHash(text){var h=5381;for(var i=0;i<text.length;i++)h=((h<<5)+h+text.charCodeAt(i))>>>0;return h.toString(36);}
function mapTitle(){var box=document.getElementById('title');return box?String(box.childNodes[0].textContent||'').trim():'';}
function draftBody(){return JSON.stringify({v:DRAFT_VERSION,savedAt:Date.now(),builtAt:MAP_BUILT_AT,rot:{r:R,tx:tx,ty:ty},style:{opacity:mapSettings.opacity,strokeWidth:mapSettings.strokeWidth,labelMode:mapSettings.labelMode},palette:statusColors.slice(),lots:L.map(function(o,i){return{s:o.s,pts:o.pts,color:o.color,nome:o.nome,quadra:o.quadra,area:o.area,group:o.group||'',extraido:!!o.extraido,index:o.index==null?i:o.index};})});}
function dropOtherDrafts(){var freed=false;try{for(var i=draftStore.length-1;i>=0;i--){var k=draftStore.key(i);if(k&&k.indexOf(DRAFT_PREFIX)===0&&k!==draftKey){draftStore.removeItem(k);freed=true;}}}catch(err){return false;}return freed;}
function writeDraft(){if(!draftStore||draftBlocked)return;var body=draftBody();try{draftStore.setItem(draftKey,body);return;}catch(err){}
  // QuotaExceededError: solta os rascunhos dos outros mapas e tenta uma vez so.
  if(dropOtherDrafts()){try{draftStore.setItem(draftKey,body);return;}catch(err2){}}
  draftBlocked=true;toast('Sem espaco no navegador para o rascunho automatico.',true);}
function markDirty(){if(!draftReady||!draftStore||draftBlocked)return;clearTimeout(draftTimer);draftTimer=setTimeout(writeDraft,DRAFT_DEBOUNCE);}
function clearDraft(){clearTimeout(draftTimer);if(!draftStore)return;try{draftStore.removeItem(draftKey);}catch(err){}}
function hideDraftBar(){var bar=document.getElementById('draftBar');if(bar)bar.classList.remove('show');}
function applyDraft(data){
  L=data.lots.map(norm);
  if(Array.isArray(data.palette))for(var i=0;i<statusColors.length&&i<data.palette.length;i++){statusColors[i]=data.palette[i];var pal=document.querySelector('[data-pal="'+i+'"]');if(pal){pal.value=data.palette[i];pal.parentElement.querySelector('.sw').style.background=data.palette[i];}}
  if(data.style){if(data.style.opacity)mapSettings.opacity=data.style.opacity;if(data.style.strokeWidth)mapSettings.strokeWidth=data.style.strokeWidth;if(data.style.labelMode)mapSettings.labelMode=data.style.labelMode;}
  if(data.rot){R=+data.rot.r||0;tx=+data.rot.tx||0;ty=+data.rot.ty||0;}
  hist=[];future=[];livePatch=null;selected.clear();draft=[];
  applyMapStyle();document.getElementById('opacityCtrl').value=Math.round(mapSettings.opacity*100);document.getElementById('strokeCtrl').value=mapSettings.strokeWidth;document.getElementById('labelMode').value=mapSettings.labelMode;
  redrawDraft();redraw();applyLotRot();toast('Rascunho restaurado');}
function showDraftBar(data){
  var bar=document.getElementById('draftBar');if(!bar)return;
  var when=new Date(data.savedAt),pad=function(v){return ('0'+v).slice(-2);};
  document.getElementById('draftBarText').textContent='Rascunho salvo neste navegador em '+pad(when.getDate())+'/'+pad(when.getMonth()+1)+' '+pad(when.getHours())+':'+pad(when.getMinutes())+' com '+data.lots.length+' lotes.';
  document.getElementById('draftRestore').onclick=function(){applyDraft(data);hideDraftBar();};
  document.getElementById('draftDiscard').onclick=function(){clearDraft();hideDraftBar();toast('Rascunho descartado');};
  bar.classList.add('show');}
function initDraft(){
  if(viewerMode())return;
  draftStore=openDraftStore();
  if(!draftStore)return;
  draftKey=DRAFT_PREFIX+draftHash(location.pathname+'|'+mapTitle()+'|'+L.length+'|'+W+'x'+H);
  draftReady=true;
  var raw=null;try{raw=draftStore.getItem(draftKey);}catch(err){raw=null;}
  if(!raw)return;
  var data=null;try{data=JSON.parse(raw);}catch(err){data=null;}
  if(!data||data.v!==DRAFT_VERSION||!Array.isArray(data.lots)||!data.savedAt){clearDraft();return;}
  // Rascunho mais velho que o HTML entregue pelo servidor ja foi superado.
  if(!(data.savedAt>MAP_BUILT_AT)){clearDraft();return;}
  showDraftBar(data);}
// Gancho para quem embute o editor (api.py injeta a barra "Salvar alteracoes"):
// depois de salvar de verdade, chame window.nexoloteDraft.clear() ou dispare o
// evento 'nexolote:saved' no document.
window.nexoloteDraft={clear:clearDraft,save:writeDraft,key:function(){return draftKey;}};
document.addEventListener('nexolote:saved',clearDraft);
if(window.matchMedia&&window.matchMedia('(max-width:760px)').matches)setSideClosed(true);applyMapStyle();redraw();ap();applyLotRot();initDraft();
