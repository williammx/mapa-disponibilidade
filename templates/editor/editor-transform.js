/* ==========================================================================
   NexoLote - alinhar, transformar, repetir e encaixar.
   Concatenado no MESMO bloco de script depois de editor.js, entao enxerga os
   globais de la (L, selected, vb, svg, lotsrot, ptsArray, setLotPoints,
   beginPatch, sealPatchOrDrop, batchOps, redraw, toast...). Tudo que e novo
   entra pelos pontos de extensao declarados no nucleo: registerTool(),
   onOverlayRedraw() e o objeto SNAP.

   O painel e montado por JS dentro de #edTransformPanel (o HTML e o CSS tem
   outro dono), reaproveitando as classes que ja existem em editor.css
   (.panel, .field, .formgrid, .inspectorSection). O pouco de estilo proprio
   vai num <style id="edtr-style"> com tudo prefixado edtr-.

   Teclas ocupadas por este modulo (todas so em modo edicao):
     T          mostra/oculta o painel Transformar e foca a largura
     R          ferramenta Repetir (arrastar o vetor no mapa)
     E          encaixar o lote entre os vizinhos
     H          espelhar horizontal      Shift+H  espelhar vertical
     Alt+1..6   alinhar esquerda/centro/direita/topo/meio/base
     Alt+7 / Alt+8  distribuir horizontal / vertical
   ========================================================================== */

/* ------------------------------------------------------------------ base */
function trUnit(){return Math.max(.35,vb.w*.004);}
function trViewScale(){var r=svg.getBoundingClientRect(),w=r.width||1,h=r.height||1;return Math.min(w/vb.w,h/vb.h)||1;}
// O operador digita 1,5 tanto quanto 1.5: os dois viram numero.
function trNum(text,fallback){var v=parseFloat(String(text==null?'':text).replace(',','.'));return isFinite(v)?v:(fallback===undefined?null:fallback);}
function trFmt(v){return String(Math.round(v*100)/100);}
function trRing(i){if(!L[i])return[];var r=ptsArray(L[i].pts);
  while(r.length>1&&Math.abs(r[0].x-r[r.length-1].x)<1e-6&&Math.abs(r[0].y-r[r.length-1].y)<1e-6)r.pop();return r;}
function trRingBox(ring){var x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
  for(var k=0;k<ring.length;k++){var p=ring[k];if(p.x<x0)x0=p.x;if(p.x>x1)x1=p.x;if(p.y<y0)y0=p.y;if(p.y>y1)y1=p.y;}
  if(!ring.length)return null;
  return{x0:x0,y0:y0,x1:x1,y1:y1,w:x1-x0,h:y1-y0,cx:(x0+x1)/2,cy:(y0+y1)/2};}
// Sem juntar os aneis num array so: com 1.500 lotes selecionados o concat em
// laco copiaria milhoes de pontos a cada redesenho.
function trBoxOf(indices){
  var x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity,vazio=true,n,ring,k,p;
  for(n=0;n<indices.length;n++){
    ring=trRing(indices[n]);
    for(k=0;k<ring.length;k++){p=ring[k];vazio=false;
      if(p.x<x0)x0=p.x;if(p.x>x1)x1=p.x;if(p.y<y0)y0=p.y;if(p.y>y1)y1=p.y;}
  }
  if(vazio)return null;
  return{x0:x0,y0:y0,x1:x1,y1:y1,w:x1-x0,h:y1-y0,cx:(x0+x1)/2,cy:(y0+y1)/2};}
// Selecao em ordem de indice para operar; ancora e o PRIMEIRO que entrou no Set.
function trSel(){var a=Array.from(selected);a.sort(function(x,y){return x-y;});return a;}
function trAnchor(){var a=Array.from(selected);return a.length?a[0]:-1;}
function trProj(ring,u){var lo=Infinity,hi=-Infinity;
  for(var k=0;k<ring.length;k++){var d=ring[k].x*u.x+ring[k].y*u.y;if(d<lo)lo=d;if(d>hi)hi=d;}
  return{lo:lo,hi:hi,mid:(lo+hi)/2,len:hi-lo};}
// Angulo do lote = direcao da maior aresta, normalizada em (-90,90].
function trRingAngle(ring){var n=ring.length,best=-1,ang=0;
  for(var k=0;k<n;k++){var a=ring[k],b=ring[(k+1)%n],d=Math.hypot(b.x-a.x,b.y-a.y);
    if(d>best){best=d;ang=Math.atan2(b.y-a.y,b.x-a.x);}}
  var deg=ang*180/Math.PI;
  while(deg<=-90)deg+=180;
  while(deg>90)deg-=180;
  return deg;}
function trAxes(ring){var a=trRingAngle(ring)*Math.PI/180,u={x:Math.cos(a),y:Math.sin(a)};return[u,{x:-u.y,y:u.x}];}

/* ------------------------------------------------------- uma operacao = um Ctrl+Z */
// beginPatch entra no historico ANTES da alteracao e sealPatchOrDrop carimba o
// valor final (ou joga a operacao fora quando nada mudou). Um clique que nao
// move nada nao pode gastar um passo de desfazer.
function trEdit(indices,make,label){
  if(!indices.length)return null;
  var op=beginPatch(indices,['pts']),moved=0,n,i,fn,ring,out,k;
  for(n=0;n<indices.length;n++){
    i=indices[n];if(!L[i])continue;
    fn=make(i);if(!fn)continue;
    ring=trRing(i);if(!ring.length)continue;
    out=[];for(k=0;k<ring.length;k++)out.push(fn(ring[k],i));
    setLotPoints(i,out);moved++;
  }
  sealPatchOrDrop(op);
  trAfter();
  if(label&&moved)toast(label);
  return{op:op,moved:moved};
}
function trAfter(){redrawVertices();scheduleListRender();renderEditor();updateLabelVisibility(true);trSync();}
function trNeedSel(min,motivo){
  if(selected.size>=min)return true;
  toast(motivo,true);return false;}

/* -------------------------------------------------------------- alinhar */
var TR_ALIGN_LABEL={left:'esquerda',centerx:'centro horizontal',right:'direita',
                    top:'topo',middley:'meio vertical',bottom:'base'};
function trAlignDelta(mode,ref,box){
  if(mode==='left')return{x:ref.x0-box.x0,y:0};
  if(mode==='right')return{x:ref.x1-box.x1,y:0};
  if(mode==='centerx')return{x:ref.cx-box.cx,y:0};
  if(mode==='top')return{x:0,y:ref.y0-box.y0};
  if(mode==='bottom')return{x:0,y:ref.y1-box.y1};
  if(mode==='middley')return{x:0,y:ref.cy-box.cy};
  return{x:0,y:0};}
function trAlign(mode,useAnchor){
  if(!TR_ALIGN_LABEL[mode])return null;
  if(!trNeedSel(2,'Selecione dois ou mais lotes para alinhar.'))return null;
  var idx=trSel(),anchor=(useAnchor===undefined?trPanelAnchor():!!useAnchor)?trAnchor():-1;
  var ref=anchor>=0?trBoxOf([anchor]):trBoxOf(idx);
  if(!ref)return null;
  trEdit(idx,function(i){
    if(i===anchor)return null;
    var box=trBoxOf([i]);if(!box)return null;
    var d=trAlignDelta(mode,ref,box);
    if(Math.abs(d.x)<1e-9&&Math.abs(d.y)<1e-9)return null;
    return function(p){return{x:p.x+d.x,y:p.y+d.y};};
  },idx.length+' lotes alinhados pela '+TR_ALIGN_LABEL[mode]+(anchor>=0?' do lote ancora':''));
  return{mode:mode,ref:ref,anchor:anchor};
}

/* ----------------------------------------------------------- distribuir */
// Vao igual entre caixas vizinhas: o primeiro e o ultimo ficam onde estao e o
// espaco que sobra e repartido. Funcao pura (recebe intervalos, devolve
// deslocamentos) para dar para testar fora do navegador.
function trSpreadDeltas(boxes){
  var n=boxes.length,order=[],k;
  for(k=0;k<n;k++)order.push(k);
  order.sort(function(a,b){return boxes[a].lo-boxes[b].lo;});
  var lo=Infinity,hi=-Infinity,sum=0;
  for(k=0;k<n;k++){if(boxes[k].lo<lo)lo=boxes[k].lo;if(boxes[k].hi>hi)hi=boxes[k].hi;sum+=boxes[k].hi-boxes[k].lo;}
  var gap=n>1?((hi-lo)-sum)/(n-1):0,cursor=lo,deltas=new Array(n);
  for(k=0;k<n;k++){var i=order[k];deltas[i]=cursor-boxes[i].lo;cursor+=(boxes[i].hi-boxes[i].lo)+gap;}
  return{gap:gap,deltas:deltas,order:order};
}
function trDistribute(axis){
  if(!trNeedSel(3,'Distribuir precisa de tres ou mais lotes selecionados.'))return null;
  var idx=trSel(),boxes=[],n,box;
  for(n=0;n<idx.length;n++){box=trBoxOf([idx[n]]);if(!box)return null;
    boxes.push(axis==='y'?{lo:box.y0,hi:box.y1}:{lo:box.x0,hi:box.x1});}
  var spread=trSpreadDeltas(boxes),map={};
  for(n=0;n<idx.length;n++)map[idx[n]]=spread.deltas[n];
  trEdit(idx,function(i){
    var d=map[i];if(!d||Math.abs(d)<1e-9)return null;
    if(axis==='y')return function(p){return{x:p.x,y:p.y+d};};
    return function(p){return{x:p.x+d,y:p.y};};
  },idx.length+' lotes distribuidos ('+(axis==='y'?'vertical':'horizontal')+', vao '+trFmt(spread.gap)+')');
  return{axis:axis,gap:spread.gap};
}

/* ------------------------------------------------- transformacao numerica */
// Origem comum de girar e escalar: centro da selecao (padrao) ou um canto.
function trOrigin(box,name){
  if(name==='tl')return{x:box.x0,y:box.y0};
  if(name==='tr')return{x:box.x1,y:box.y0};
  if(name==='bl')return{x:box.x0,y:box.y1};
  if(name==='br')return{x:box.x1,y:box.y1};
  return{x:box.cx,y:box.cy};}
function trRotate(deg,origin){
  if(!trNeedSel(1,'Selecione ao menos um lote para girar.'))return null;
  var value=trNum(deg,NaN);
  if(!isFinite(value)||!value){toast('Informe um angulo diferente de zero.',true);return null;}
  var idx=trSel(),box=trBoxOf(idx);if(!box)return null;
  var o=trOrigin(box,origin===undefined?trPanelOrigin():origin),a=value*Math.PI/180,c=Math.cos(a),s=Math.sin(a);
  var turn=function(p){var dx=p.x-o.x,dy=p.y-o.y;return{x:o.x+dx*c-dy*s,y:o.y+dx*s+dy*c};};
  trEdit(idx,function(){return turn;},'Selecao girada '+trFmt(value)+'°');
  return{angle:value,origin:o};
}
function trScale(fx,fy,origin){
  if(!trNeedSel(1,'Selecione ao menos um lote para escalar.'))return null;
  var sx=trNum(fx,NaN),sy=fy===undefined||fy===null?sx:trNum(fy,NaN);
  if(!isFinite(sx)||!isFinite(sy)||Math.abs(sx)<1e-6||Math.abs(sy)<1e-6){toast('Fator de escala invalido.',true);return null;}
  var idx=trSel(),box=trBoxOf(idx);if(!box)return null;
  var o=trOrigin(box,origin===undefined?trPanelOrigin():origin);
  trEdit(idx,function(){return function(p){return{x:o.x+(p.x-o.x)*sx,y:o.y+(p.y-o.y)*sy};};},
    'Selecao escalada '+trFmt(sx)+'x'+(sx===sy?'':' / '+trFmt(sy)+'x'));
  return{sx:sx,sy:sy,origin:o};
}
// Escalar por dimensao alvo: o fator sai da caixa atual. Com a trava ligada, a
// dimensao que o operador nao digitou acompanha.
function trResize(w,h,lock,origin){
  if(!trNeedSel(1,'Selecione ao menos um lote para redimensionar.'))return null;
  var idx=trSel(),box=trBoxOf(idx);if(!box)return null;
  var tw=w==null?null:trNum(w,NaN),th=h==null?null:trNum(h,NaN),sx=1,sy=1;
  if(tw!=null&&isFinite(tw)&&tw>0&&box.w>1e-6)sx=tw/box.w;
  if(th!=null&&isFinite(th)&&th>0&&box.h>1e-6)sy=th/box.h;
  if(lock){if(tw!=null&&isFinite(tw)&&tw>0)sy=sx;else sx=sy;}
  if(Math.abs(sx-1)<1e-9&&Math.abs(sy-1)<1e-9)return null;
  return trScale(sx,sy,origin);
}
function trFlip(axis){
  if(!trNeedSel(1,'Selecione ao menos um lote para espelhar.'))return null;
  var idx=trSel(),box=trBoxOf(idx);if(!box)return null;
  var horizontal=axis!=='v';
  trEdit(idx,function(){return function(p){
    return horizontal?{x:2*box.cx-p.x,y:p.y}:{x:p.x,y:2*box.cy-p.y};};},
    'Selecao espelhada na '+(horizontal?'horizontal':'vertical'));
  return{axis:horizontal?'h':'v',box:box};
}
// Ctrl+A seleciona o mapa inteiro: medir 1.500 contornos a cada sincronizacao
// do painel travaria a tela por nada, entao acima do limite so vai a contagem.
var TR_MEASURE_MAX=600;
function trMetrics(){
  var idx=trSel();if(!idx.length)return null;
  var anchor=trAnchor();
  if(idx.length>TR_MEASURE_MAX)return{count:idx.length,muitos:true,indices:idx,anchor:anchor};
  var box=trBoxOf(idx);if(!box)return null;
  return{count:idx.length,muitos:false,x:box.x0,y:box.y0,w:box.w,h:box.h,cx:box.cx,cy:box.cy,
         angle:trRingAngle(trRing(anchor>=0?anchor:idx[0])),indices:idx,anchor:anchor};
}
// Angulo digitado e ABSOLUTO: gira a selecao pela diferenca do angulo atual.
function trSetAngle(deg,origin){
  var target=trNum(deg,NaN),m=trMetrics();
  if(!m||!isFinite(target))return null;
  var atual=m.muitos?trRingAngle(trRing(m.anchor>=0?m.anchor:m.indices[0])):m.angle;
  var delta=target-atual;
  while(delta<=-180)delta+=360;
  while(delta>180)delta-=360;
  if(Math.abs(delta)<1e-6)return null;
  return trRotate(delta,origin);
}

/* --------------------------------------------------------------- vizinhos */
// Quem responde "qual lote esta encostado ali" e o indice espacial do ima
// (SNAP). Sem o modulo vetorial carregado, so o laco de proximidade responde.
function trSnapQuery(p,skip){
  if(typeof SNAP==='object'&&SNAP&&typeof SNAP.query==='function')return SNAP.query(p,{skip:skip});
  var vec=window.nexoloteVector;
  if(vec&&vec.snap&&typeof vec.snap.query==='function')return vec.snap.query(p,{skip:skip});
  return null;
}
function trSnapReach(px){
  var vec=window.nexoloteVector;
  if(!vec||!vec.snap||typeof vec.snap.tolerancePx!=='function')return null;
  var antes=vec.snap.tolerancePx();
  vec.snap.tolerancePx(px);
  return antes;
}
// Pergunta ao ima quem esta do lado de fora da face: ele responde com o lote da
// aresta mais proxima, que e exatamente o vizinho da fileira.
function trSnapNeighbour(i,u,sign,ring){
  var v={x:-u.y,y:u.x},pu=trProj(ring,u),pv=trProj(ring,v);
  var face=sign>0?pu.hi:pu.lo,out=face+sign*Math.max(pu.len*.04,1e-3);
  var p={x:u.x*out+v.x*pv.mid,y:u.y*out+v.y*pv.mid},skip={};
  skip[i]=1;
  var wide=trSnapReach(Math.max(10,Math.min(400,pu.len*.9*trViewScale()))),hit=null;
  try{hit=trSnapQuery(p,skip);}catch(err){hit=null;}
  if(wide!=null)trSnapReach(wide);
  return hit&&hit.lot!=null&&hit.lot!==i?hit.lot:-1;
}
// Vizinho na direcao u (sign=+1 a frente, -1 atras): mesma fileira (as
// projecoes perpendiculares tem que se cobrir) e do lado certo.
function trNeighbour(i,u,sign){
  var ring=trRing(i);if(ring.length<3)return null;
  var v={x:-u.y,y:u.x},pu=trProj(ring,u),pv=trProj(ring,v);
  var face=sign>0?pu.hi:pu.lo,reach=Math.max(pu.len*2.5,pv.len,4),lim=reach+pu.len+pv.len;
  var mine=cachedCenter(i),hint=trSnapNeighbour(i,u,sign,ring),best=null,j,c,other,qv,qu,over,gap,score;
  for(j=0;j<L.length;j++){
    if(j===i||!L[j])continue;
    c=cachedCenter(j);
    if(Math.abs(c.x-mine.x)>lim||Math.abs(c.y-mine.y)>lim)continue;
    other=trRing(j);if(other.length<3)continue;
    qv=trProj(other,v);
    over=Math.min(pv.hi,qv.hi)-Math.max(pv.lo,qv.lo);
    if(over<Math.min(pv.len,qv.len)*.35)continue;
    qu=trProj(other,u);
    if((qu.mid-pu.mid)*sign<=0)continue;
    gap=sign>0?qu.lo-face:face-qu.hi;
    if(gap>reach)continue;
    score=Math.abs(gap)-(j===hint?pu.len:0);
    if(!best||score<best.score)best={i:j,gap:gap,edge:sign>0?qu.lo:qu.hi,hinted:j===hint,score:score};
  }
  return best;
}
// Mapa afim ao longo do eixo: [lo,hi] vira [a,b] sem mexer no perpendicular.
// Encaixar e para acertar folga de mapeamento, nao para inventar lote: um
// esticao alem de 1,8x (ou um encolhimento abaixo de 0,5x) e recusado.
var TR_FIT_MIN=.5,TR_FIT_MAX=1.8;
function trFitMap(lo,hi,a,b){
  var len=hi-lo,alvo=b-a;
  if(len<1e-6||alvo<1e-6)return null;
  var s=alvo/len;
  if(s<TR_FIT_MIN||s>TR_FIT_MAX)return null;
  return{s:s,t:a-lo*s};
}
function trFit(i){
  var ring=trRing(i);
  if(ring.length<3){toast('O lote nao tem contorno para encaixar.',true);return null;}
  var axes=trAxes(ring),best=null,n,u,plus,minus,found,cost;
  for(n=0;n<axes.length;n++){
    u=axes[n];plus=trNeighbour(i,u,1);minus=trNeighbour(i,u,-1);
    found=(plus?1:0)+(minus?1:0);
    if(!found)continue;
    cost=(plus?Math.abs(plus.gap):0)+(minus?Math.abs(minus.gap):0);
    if(!best||found>best.found||(found===best.found&&cost<best.cost))
      best={u:u,plus:plus,minus:minus,found:found,cost:cost};
  }
  if(!best){toast('Nao encontrei lotes vizinhos alinhados com este.',true);return null;}
  var eixo=best.u,pu=trProj(ring,eixo),a=best.minus?best.minus.edge:pu.lo,b=best.plus?best.plus.edge:pu.hi;
  if(!best.minus)a=pu.lo+(b-pu.hi);
  if(!best.plus)b=pu.hi+(a-pu.lo);
  var map=trFitMap(pu.lo,pu.hi,a,b);
  if(!map){toast('O vao entre os vizinhos daria um lote '+trFmt((b-a)/(pu.hi-pu.lo))+'x maior; use Repetir em vez de encaixar.',true);return null;}
  var gaps={minus:best.minus?best.minus.gap:null,plus:best.plus?best.plus.gap:null};
  trEdit([i],function(){return function(p){
    var d=p.x*eixo.x+p.y*eixo.y,alvo=d*map.s+map.t,delta=alvo-d;
    return{x:p.x+eixo.x*delta,y:p.y+eixo.y*delta};};},
    'Lote encaixado entre '+best.found+' vizinho'+(best.found>1?'s':'')
    +' (vao '+trFmt(Math.max(Math.abs(gaps.minus||0),Math.abs(gaps.plus||0)))+' zerado'
    +(Math.abs(map.s-1)>.02?', lote ajustado '+trFmt(map.s)+'x':'')+')');
  return{lot:i,found:best.found,scale:map.s,gaps:gaps,axis:{x:eixo.x,y:eixo.y},
         neighbours:{minus:best.minus?best.minus.i:null,plus:best.plus?best.plus.i:null}};
}
function trFitSelection(){
  if(selected.size!==1){toast('Selecione um unico lote para encaixar na malha.',true);return null;}
  return trFit(trAnchor());
}

/* ---------------------------------------------------------------- repetir */
// Numa quadra o lote e o mesmo retangulo repetido ao longo da rua. Quando o
// mapeamento perde a fileira inteira, redesenhar um a um e inviavel.
var trArray={count:3,angle:0,gap:0,src:[],drag:null,live:false},TR_ARRAY_MAX=800;
// Nome sequencial: pega a ULTIMA sequencia de digitos do nome (Q195-L003 ->
// 003) e conta a partir dela, mantendo o zero a esquerda. Sem digito nenhum,
// entra um sufixo numerico.
function trNameParts(name){
  var s=String(name==null?'':name),re=/\d+/g,hit,last=null;
  while((hit=re.exec(s)))last={digits:hit[0],at:hit.index};
  if(!last)return null;
  return{head:s.slice(0,last.at),digits:last.digits,tail:s.slice(last.at+last.digits.length)};
}
function trNextName(name,step){
  var p=trNameParts(name);
  if(!p)return String(name==null?'':name)+' '+(step+1);
  var value=parseInt(p.digits,10)+step,text=String(Math.abs(value));
  while(text.length<p.digits.length)text='0'+text;
  return p.head+(value<0?'-':'')+text+p.tail;
}
// Com a ferramenta ligada vale o conjunto congelado no enter (o arrasto nao
// pode trocar de fonte no meio); fora dela, vale a selecao de agora.
function trArraySource(){
  var base=(tool==='array'&&trArray.src.length)?trArray.src:trSel(),out=[],n;
  for(n=0;n<base.length;n++)if(L[base[n]])out.push(base[n]);
  return out;
}
function trArrayExtent(u,src){
  var lo=Infinity,hi=-Infinity,n,ring,k,d;
  for(n=0;n<src.length;n++){
    ring=trRing(src[n]);
    for(k=0;k<ring.length;k++){d=ring[k].x*u.x+ring[k].y*u.y;if(d<lo)lo=d;if(d>hi)hi=d;}
  }
  return hi>=lo?hi-lo:0;
}
// Passo = quanto o lote ocupa NA DIRECAO escolhida + o vao pedido. Vao zero
// deixa as copias encostadas, que e o caso da fileira de lotes.
function trArrayVector(src){
  var list=src||trArraySource(),a=trArray.angle*Math.PI/180,u={x:Math.cos(a),y:Math.sin(a)};
  var extent=trArrayExtent(u,list),step=extent+trArray.gap;
  return{u:u,extent:extent,step:step,x:u.x*step,y:u.y*step};
}
function trArraySet(opts){
  if(!opts)return trArray;
  if(opts.count!=null)trArray.count=Math.max(1,Math.min(200,Math.round(trNum(opts.count,trArray.count))));
  if(opts.angle!=null)trArray.angle=trNum(opts.angle,trArray.angle);
  if(opts.gap!=null)trArray.gap=trNum(opts.gap,trArray.gap);
  trArrayFields();trOverlay();
  return trArray;
}
function trArrayApply(opts){
  if(opts)trArraySet(opts);
  var src=trArraySource();
  if(!src.length){toast('Selecione o lote que deve ser repetido.',true);return null;}
  var count=Math.max(1,Math.round(trArray.count)),vec=trArrayVector(src);
  if(Math.abs(vec.step)<1e-6){toast('O passo ficou zero; ajuste o espacamento.',true);return null;}
  // Rede de seguranca: um clique nao pode dobrar o mapa de tamanho.
  if(src.length*count>TR_ARRAY_MAX){
    toast('Isso criaria '+(src.length*count)+' lotes de uma vez (limite '+TR_ARRAY_MAX+'); reduza a selecao ou as copias.',true);
    return null;}
  var base=Math.max.apply(null,src)+1,at=base,ops=[],made=[],names=[],n,k,ring,copy,out,p;
  for(n=0;n<src.length;n++){
    ring=trRing(src[n]);
    for(k=1;k<=count;k++){
      copy=JSON.parse(JSON.stringify(L[src[n]]));
      delete copy._cx;delete copy._cy;
      copy.group='';copy.extraido=false;copy.index=L.length;
      copy.nome=trNextName(L[src[n]].nome,k);
      out=[];
      for(p=0;p<ring.length;p++)out.push((ring[p].x+vec.x*k).toFixed(1)+','+(ring[p].y+vec.y*k).toFixed(1));
      copy.pts=out.join(' ');
      L.splice(at,0,copy);
      ops.push({k:'insert',at:at,item:copy});
      made.push(at);names.push(copy.nome);at++;
    }
  }
  // Um unico passo de desfazer para a fileira inteira.
  batchOps(ops);
  selected.clear();
  for(n=0;n<made.length;n++)selected.add(made[n]);
  trArray.src=made.slice();
  redraw();
  toast(made.length+' lote'+(made.length>1?'s':'')+' criado'+(made.length>1?'s':'')+' ('+names[0]+' ... '+names[names.length-1]+')');
  return{created:made,names:names,step:vec.step,angle:trArray.angle,gap:trArray.gap};
}

/* ------------------------------------------------- ferramenta de repetir */
// Direcao livre: em vez de digitar o angulo, arrasta-se o vetor na tela. O
// ponto solto passa pelo ima, entao da para encostar exatamente no vizinho.
registerTool('array',{
  button:'edarray',cursor:'draw',
  status:function(){return 'Repetir: arraste a direcao no mapa, Enter confirma ('+trArray.count+'x)';},
  ready:function(){
    if(!selected.size){toast('Selecione o lote que deve ser repetido.',true);return false;}
    return true;
  },
  enter:function(){
    trArray.src=trSel();trArray.drag=null;trArray.live=true;
    if(!trArray.angle)trArrayGuessDirection();
    trArrayFields();trOverlay();updateCanvasStatus();
  },
  exit:function(){trArray.drag=null;trArray.live=false;trOverlay();},
  down:function(e){
    if(ptrs.size>1||(e.button!=null&&e.button!==0))return false;
    trArray.src=trSel();
    trArray.drag={from:toLocal(c2s(e.clientX,e.clientY)),moved:false};
    return true;
  },
  move:function(e){
    if(!trArray.drag)return false;
    // O ponto solto passa pelo ima: da para encostar o passo exatamente no
    // vertice do vizinho em vez de acertar no olho.
    var raw=toLocal(c2s(e.clientX,e.clientY)),p=SNAP.point(raw,e,{lot:trAnchor()}),src=trArraySource();
    var dx=p.x-trArray.drag.from.x,dy=p.y-trArray.drag.from.y,len=Math.hypot(dx,dy);
    if(len>1e-6){
      trArray.drag.moved=true;
      trArray.angle=Math.atan2(dy,dx)*180/Math.PI;
      trArray.gap=len-trArrayExtent({x:dx/len,y:dy/len},src);
    }
    trArrayFields();trOverlay();
    return true;
  },
  up:function(){
    if(!trArray.drag)return false;
    var moved=trArray.drag.moved;
    trArray.drag=null;trOverlay();
    if(moved)toast('Direcao definida. Enter (ou o botao Repetir) confirma.');
    return true;
  },
  click:function(){return true;},
  key:function(e){
    if(e.key==='Enter'){e.preventDefault();trArrayApply();return true;}
    if(e.key==='Escape'){e.preventDefault();setTool('select');return true;}
    return false;
  }
});
// Direcao inicial: o vizinho mais proximo da fileira. Numa quadra e sempre a
// rua, entao o padrao ja nasce util.
function trArrayGuessDirection(){
  var src=trArraySource();if(!src.length)return;
  var i=src[0],ring=trRing(i);if(ring.length<3)return;
  var axes=trAxes(ring),n,s,hit,best=null;
  for(n=0;n<axes.length;n++)for(s=1;s>=-1;s-=2){
    hit=trNeighbour(i,axes[n],s);
    if(hit&&(!best||Math.abs(hit.gap)<Math.abs(best.gap)))best={hit:hit,u:axes[n],s:s};
  }
  if(!best){trArray.angle=trRingAngle(ring);return;}
  trArray.angle=Math.atan2(best.u.y*best.s,best.u.x*best.s)*180/Math.PI;
  trArray.gap=0;
}

/* ---------------------------------------------------------------- overlay */
// Camada propria (as classes do editor.css tem outro dono): previa das copias,
// caixa da selecao e marca da origem de giro/escala.
var trLayer=el('g');
trLayer.setAttribute('id','troverlay');
trLayer.setAttribute('pointer-events','none');
lotsrot.appendChild(trLayer);
function trShape(tag,attrs){var node=el(tag);for(var key in attrs)node.setAttribute(key,attrs[key]);trLayer.appendChild(node);return node;}
function trOverlay(){redrawOverlays();}
function trDrawSelection(){
  if(!trPanel||trPanel.hidden||!selected.size||selected.size>200)return;
  var box=trBoxOf(trSel());if(!box)return;
  var u=trUnit();
  trShape('rect',{x:box.x0,y:box.y0,width:Math.max(box.w,1e-3),height:Math.max(box.h,1e-3),
    fill:'none',stroke:'#12b8ff','stroke-width':1,'stroke-dasharray':(u*3)+' '+(u*2),'vector-effect':'non-scaling-stroke'});
  var o=trOrigin(box,trPanelOrigin());
  trShape('path',{d:'M'+(o.x-u*2)+' '+o.y+'H'+(o.x+u*2)+'M'+o.x+' '+(o.y-u*2)+'V'+(o.y+u*2),
    stroke:'#12b8ff','stroke-width':1.4,'vector-effect':'non-scaling-stroke'});
}
function trDrawArray(){
  if(!trArray.live||!trPanel||trPanel.hidden)return;
  var src=trArraySource();if(!src.length||src.length>TR_MEASURE_MAX)return;
  var vec=trArrayVector(src),count=Math.max(1,Math.round(trArray.count)),u=trUnit(),n,k,ring,pts,p;
  if(Math.abs(vec.step)<1e-6)return;
  var box=trBoxOf(src),cheio=box&&src.length*count<=300;
  // Selecao grande com muitas copias viraria milhares de poligonos por quadro:
  // acima do limite a previa mostra so a caixa de cada copia.
  for(k=1;k<=count&&!cheio&&box;k++)
    trShape('rect',{x:box.x0+vec.x*k,y:box.y0+vec.y*k,width:Math.max(box.w,1e-3),height:Math.max(box.h,1e-3),
      fill:'#36d889','fill-opacity':.1,stroke:'#36d889','stroke-width':1.2,
      'stroke-dasharray':(u*3)+' '+(u*2),'vector-effect':'non-scaling-stroke'});
  for(n=0;n<src.length&&cheio;n++){
    ring=trRing(src[n]);if(ring.length<3)continue;
    for(k=1;k<=count;k++){
      pts=[];
      for(p=0;p<ring.length;p++)pts.push((ring[p].x+vec.x*k).toFixed(1)+','+(ring[p].y+vec.y*k).toFixed(1));
      trShape('polygon',{points:pts.join(' '),fill:'#36d889','fill-opacity':.16,stroke:'#36d889',
        'stroke-width':1.2,'stroke-dasharray':(u*3)+' '+(u*2),'vector-effect':'non-scaling-stroke'});
    }
  }
  if(box)trShape('line',{x1:box.cx,y1:box.cy,x2:box.cx+vec.x*count,y2:box.cy+vec.y*count,
    stroke:'#36d889','stroke-width':1.4,'stroke-dasharray':(u*4)+' '+(u*2.5),'vector-effect':'non-scaling-stroke'});
}
onOverlayRedraw(function(){
  while(trLayer.firstChild)trLayer.removeChild(trLayer.firstChild);
  if(!editMode)return;
  trDrawSelection();
  trDrawArray();
});

/* ------------------------------------------------------------------ painel */
var TR_STYLE=[
  '#edTransformPanel{position:absolute;z-index:7;left:328px;top:64px;width:296px;max-height:calc(100vh - 152px);overflow:auto;padding:0;border:1px solid #2b3842;border-radius:9px;background:#101820;box-shadow:0 22px 60px rgba(3,8,12,.3);font-size:12px}',
  '#app.side-closed #edTransformPanel{left:16px}',
  '#edTransformPanel .edtr-head{position:sticky;top:0;z-index:1;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:11px 13px 9px;border-bottom:1px solid #26313a;background:#101820}',
  '#edTransformPanel .edtr-head strong{font-size:13px;font-weight:650}',
  '#edTransformPanel.edtr-off .edtr-body{display:none}',
  '#edTransformPanel .edtr-body{padding-bottom:12px}',
  '#edTransformPanel .inspectorSection{margin:12px 0 7px}',
  '#edTransformPanel .edtr-row{display:grid;gap:6px;padding:0 13px;margin-bottom:8px}',
  '#edTransformPanel .edtr-c6{grid-template-columns:repeat(6,1fr)}',
  '#edTransformPanel .edtr-c3{grid-template-columns:repeat(3,1fr)}',
  '#edTransformPanel .edtr-c2{grid-template-columns:repeat(2,1fr)}',
  '#edTransformPanel button{min-height:30px;padding:0 7px;border:1px solid #2c3943;border-radius:7px;background:#161f27;color:#dbe5e7;font-size:11.5px;cursor:pointer}',
  '#edTransformPanel button:hover:not(:disabled){background:#1f2a33;border-color:#3d4c57}',
  '#edTransformPanel button:disabled{opacity:.38;cursor:not-allowed}',
  '#edTransformPanel button.on{background:#36d889;border-color:#36d889;color:#052419;font-weight:650}',
  '#edTransformPanel .edtr-ico{font-size:15px;line-height:1}',
  '#edTransformPanel .formgrid{padding:0 13px 2px}',
  '#edTransformPanel .field input{width:100%}',
  '#edTransformPanel .edtr-note{padding:0 13px;margin-bottom:9px;color:#8fa0a9;font-size:10.5px;line-height:1.4}',
  '#edTransformPanel .edtr-note.edtr-warn{color:#f0b49b}',
  '#edTransformPanel .edtr-check{display:flex;align-items:center;gap:7px;padding:0 13px;margin-bottom:9px;color:#a9b6bd;font-size:11px;cursor:pointer}',
  '#edTransformPanel .edtr-check input{accent-color:#36d889}',
  '@media(max-width:1180px){#edTransformPanel{left:auto;right:16px;top:auto;bottom:56px;max-height:52vh}}',
  '@media(max-width:760px){#edTransformPanel{left:8px;right:8px;width:auto;bottom:8px;max-height:46vh}}'
].join('\n');
function trStyle(){
  if(document.getElementById('edtr-style'))return;
  var node=document.createElement('style');
  node.id='edtr-style';node.textContent=TR_STYLE;
  document.head.appendChild(node);
}
function trBtn(id,label,text,extra){
  return '<button type="button" id="'+id+'" title="'+label+'" aria-label="'+label+'"'+(extra||'')+'>'+text+'</button>';
}
function trField(id,label,value){
  return '<label class="field">'+label+'<input id="'+id+'" type="text" inputmode="decimal" autocomplete="off" value="'+value+'"></label>';
}
var trPanel=null;
function trBuildPanel(){
  trStyle();
  trPanel=document.getElementById('edTransformPanel');
  if(!trPanel){
    trPanel=document.createElement('section');
    trPanel.id='edTransformPanel';
    trPanel.className='panel';
    trPanel.setAttribute('role','group');
    trPanel.setAttribute('aria-label','Transformar selecao');
    (document.getElementById('app')||document.body).appendChild(trPanel);
  }
  trPanel.hidden=true;
  trPanel.innerHTML=
    '<div class="edtr-head"><strong>Transformar</strong>'
    +trBtn('edtrFold','Recolher ou abrir o painel de transformacao','<span class="edtr-ico">&#9650;</span>')
    +'</div><div class="edtr-body">'
    +'<div class="inspectorSection">Alinhar</div>'
    +'<div class="edtr-row edtr-c6">'
    +trBtn('edtrAlLeft','Alinhar a esquerda (Alt+1)','<span class="edtr-ico">&#8676;</span>')
    +trBtn('edtrAlCx','Centralizar na horizontal (Alt+2)','<span class="edtr-ico">&#8596;</span>')
    +trBtn('edtrAlRight','Alinhar a direita (Alt+3)','<span class="edtr-ico">&#8677;</span>')
    +trBtn('edtrAlTop','Alinhar pelo topo (Alt+4)','<span class="edtr-ico">&#8679;</span>')
    +trBtn('edtrAlCy','Centralizar na vertical (Alt+5)','<span class="edtr-ico">&#8597;</span>')
    +trBtn('edtrAlBottom','Alinhar pela base (Alt+6)','<span class="edtr-ico">&#8681;</span>')
    +'</div>'
    +'<div class="edtr-row edtr-c2">'
    +trBtn('edtrDistX','Distribuir com vao igual na horizontal (Alt+7)','Distribuir H')
    +trBtn('edtrDistY','Distribuir com vao igual na vertical (Alt+8)','Distribuir V')
    +'</div>'
    +'<label class="edtr-check"><input type="checkbox" id="edtrAnchor"> Alinhar pelo lote ancora (o primeiro selecionado)</label>'
    +'<p class="edtr-note" id="edtrAlignWhy"></p>'
    +'<div class="inspectorSection">Medidas da selecao</div>'
    +'<div class="formgrid">'
    +trField('edtrW','Largura','')
    +trField('edtrH','Altura','')
    +trField('edtrA','Angulo','')
    +'<label class="field">Origem<select id="edtrOrigin">'
    +'<option value="center">Centro</option><option value="tl">Canto sup. esq.</option>'
    +'<option value="tr">Canto sup. dir.</option><option value="bl">Canto inf. esq.</option>'
    +'<option value="br">Canto inf. dir.</option></select></label>'
    +'</div>'
    +'<label class="edtr-check"><input type="checkbox" id="edtrLock" checked> Travar proporcao</label>'
    +'<div class="edtr-row edtr-c3">'
    +'<label class="field">Girar<input id="edtrRotStep" type="text" inputmode="decimal" autocomplete="off" value="90"></label>'
    +trBtn('edtrRotL','Girar a selecao no sentido anti-horario','<span class="edtr-ico">&#8634;</span>',' style="align-self:end"')
    +trBtn('edtrRotR','Girar a selecao no sentido horario','<span class="edtr-ico">&#8635;</span>',' style="align-self:end"')
    +'</div>'
    +'<div class="edtr-row edtr-c3">'
    +'<label class="field">Escala<input id="edtrFactor" type="text" inputmode="decimal" autocomplete="off" value="2"></label>'
    +trBtn('edtrScale','Escalar a selecao pelo fator digitado','Escalar',' style="align-self:end"')
    +trBtn('edtrScaleInv','Escalar a selecao pelo inverso do fator','1/fator',' style="align-self:end"')
    +'</div>'
    +'<div class="edtr-row edtr-c2">'
    +trBtn('edtrFlipH','Espelhar na horizontal (H)','Espelhar H')
    +trBtn('edtrFlipV','Espelhar na vertical (Shift+H)','Espelhar V')
    +'</div>'
    +'<p class="edtr-note" id="edtrSizeWhy"></p>'
    +'<div class="inspectorSection">Repetir (array)</div>'
    +'<div class="formgrid">'
    +trField('edtrCount','Copias','3')
    +trField('edtrAngle','Direcao (graus)','0')
    +trField('edtrGap','Espacamento','0')
    +'</div>'
    +'<div class="edtr-row edtr-c3">'
    +trBtn('edarray','Definir a direcao arrastando no mapa (R)','Direcao')
    +trBtn('edtrRepeat','Repetir a selecao com o passo definido','Repetir')
    +trBtn('edtrFit','Encaixar o lote entre os vizinhos (E)','Encaixar')
    +'</div>'
    +'<p class="edtr-note" id="edtrArrayWhy"></p>'
    +'</div>';
  trWire();
  trSync();
}
function trOn(id,event,fn){var node=document.getElementById(id);if(node)node.addEventListener(event,fn);}
function trWire(){
  trOn('edtrFold','click',function(){
    var off=trPanel.classList.toggle('edtr-off');
    this.setAttribute('aria-expanded',String(!off));
    this.innerHTML='<span class="edtr-ico">'+(off?'&#9660;':'&#9650;')+'</span>';
    trOverlay();
  });
  [['edtrAlLeft','left'],['edtrAlCx','centerx'],['edtrAlRight','right'],
   ['edtrAlTop','top'],['edtrAlCy','middley'],['edtrAlBottom','bottom']].forEach(function(pair){
    trOn(pair[0],'click',function(){trAlign(pair[1]);});
  });
  trOn('edtrDistX','click',function(){trDistribute('x');});
  trOn('edtrDistY','click',function(){trDistribute('y');});
  trOn('edtrAnchor','change',function(){trSync();});
  trOn('edtrOrigin','change',function(){trOverlay();});
  trOn('edtrW','change',function(){trResize(this.value,null,trPanelLock());trSync();});
  trOn('edtrH','change',function(){trResize(null,this.value,trPanelLock());trSync();});
  trOn('edtrA','change',function(){trSetAngle(this.value);trSync();});
  trOn('edtrRotL','click',function(){trRotate(-trNum(trValue('edtrRotStep'),90));});
  trOn('edtrRotR','click',function(){trRotate(trNum(trValue('edtrRotStep'),90));});
  trOn('edtrScale','click',function(){trScale(trNum(trValue('edtrFactor'),1));});
  trOn('edtrScaleInv','click',function(){var f=trNum(trValue('edtrFactor'),1);if(f)trScale(1/f);});
  trOn('edtrFlipH','click',function(){trFlip('h');});
  trOn('edtrFlipV','click',function(){trFlip('v');});
  ['edtrCount','edtrAngle','edtrGap'].forEach(function(id){
    trOn(id,'input',function(){
      trArray.count=Math.max(1,Math.min(200,Math.round(trNum(trValue('edtrCount'),trArray.count))));
      trArray.angle=trNum(trValue('edtrAngle'),trArray.angle);
      trArray.gap=trNum(trValue('edtrGap'),trArray.gap);
      // Mexeu nos campos, quer ver a previa mesmo sem a ferramenta ligada.
      trArray.live=true;
      trArrayNote();trOverlay();
    });
  });
  trOn('edarray','click',function(){setTool(tool==='array'?'select':'array');});
  trOn('edtrRepeat','click',function(){trArrayApply();});
  trOn('edtrFit','click',function(){trFitSelection();});
}
function trValue(id){var node=document.getElementById(id);return node?node.value:'';}
function trSet(id,value){var node=document.getElementById(id);if(node&&document.activeElement!==node)node.value=value;}
function trDisable(id,off){var node=document.getElementById(id);if(node)node.disabled=!!off;}
function trText(id,text,warn){var node=document.getElementById(id);if(!node)return;
  node.textContent=text||'';node.classList.toggle('edtr-warn',!!warn);}
function trPanelAnchor(){var node=document.getElementById('edtrAnchor');return !!(node&&node.checked);}
function trPanelLock(){var node=document.getElementById('edtrLock');return !node||node.checked;}
function trPanelOrigin(){var node=document.getElementById('edtrOrigin');return node?node.value:'center';}
function trArrayFields(){
  trSet('edtrCount',String(Math.max(1,Math.round(trArray.count))));
  trSet('edtrAngle',trFmt(trArray.angle));
  trSet('edtrGap',trFmt(trArray.gap));
  trArrayNote();
}
function trArrayNote(){
  var src=trArraySource();
  if(!src.length){trText('edtrArrayWhy','Selecione o lote que deve ser repetido.',true);return;}
  if(src.length>TR_MEASURE_MAX){
    trText('edtrArrayWhy',src.length+' lotes selecionados: repetir tudo criaria '
      +(src.length*Math.max(1,Math.round(trArray.count)))+' lotes de uma vez.',true);return;}
  var vec=trArrayVector(src),count=Math.max(1,Math.round(trArray.count));
  var nome=L[src[0]]?trNextName(L[src[0]].nome,1):'';
  trText('edtrArrayWhy',count+' copia'+(count>1?'s':'')+' · passo '+trFmt(vec.step)
    +' · vao '+trFmt(trArray.gap)+(nome?' · proximo nome '+nome:''),false);
}
// Botao desabilitado sem motivo na tela vira suporte: o porque fica escrito.
function trSync(){
  if(!trPanel)return;
  var m=trMetrics(),count=selected.size;
  var alignOff=count<2,distOff=count<3,sizeOff=!count,fitOff=count!==1;
  ['edtrAlLeft','edtrAlCx','edtrAlRight','edtrAlTop','edtrAlCy','edtrAlBottom'].forEach(function(id){trDisable(id,alignOff);});
  ['edtrDistX','edtrDistY'].forEach(function(id){trDisable(id,distOff);});
  ['edtrRotL','edtrRotR','edtrScale','edtrScaleInv','edtrFlipH','edtrFlipV','edtrW','edtrH','edtrA','edtrRepeat','edarray'].forEach(function(id){trDisable(id,sizeOff);});
  trDisable('edtrFit',fitOff);
  trText('edtrAlignWhy',
    count===0?'Nenhum lote selecionado: alinhar e distribuir precisam de selecao.':
    count===1?'Com um lote so nao ha o que alinhar - selecione dois ou mais (tres para distribuir).':
    count===2?'Distribuir fica livre a partir de tres lotes.':'',count<3);
  if(m&&!m.muitos){
    trSet('edtrW',trFmt(m.w));trSet('edtrH',trFmt(m.h));trSet('edtrA',trFmt(m.angle));
    trText('edtrSizeWhy',m.count+' lote'+(m.count>1?'s':'')+' · caixa '+trFmt(m.w)+' x '+trFmt(m.h)
      +' · angulo '+trFmt(m.angle)+'°'+(m.count>1?' (angulo do lote ancora)':''),false);
  }else if(m){
    trSet('edtrW','');trSet('edtrH','');trSet('edtrA','');
    trText('edtrSizeWhy',m.count+' lotes selecionados: as medidas ficam ocultas acima de '+TR_MEASURE_MAX
      +' lotes para nao travar o painel. Girar, escalar e espelhar continuam valendo.',false);
  }else{
    trSet('edtrW','');trSet('edtrH','');trSet('edtrA','');
    trText('edtrSizeWhy','Selecione ao menos um lote para medir, girar, escalar ou espelhar.',true);
  }
  if(!count)trText('edtrArrayWhy','Selecione o lote que deve ser repetido; encaixar na malha trabalha com um lote de cada vez.',true);
  else trArrayNote();
}
function trShow(on){
  if(!trPanel)return;
  trPanel.hidden=!on;
  if(on)trSync();
  trOverlay();
}
function trFocus(){
  if(!editMode){toast('Ative a edicao para transformar a selecao.',true);return;}
  if(trPanel.hidden)trShow(true);
  trPanel.classList.remove('edtr-off');
  var node=document.getElementById('edtrW');
  if(node&&!node.disabled)node.focus();
}

/* ------------------------------------------- painel acompanha o editor */
trBuildPanel();
var trCoreSetEdit=setEdit;
setEdit=function(on){var out=trCoreSetEdit(on);trShow(!!on);return out;};
var trCoreSync=syncSelection;
syncSelection=function(){var out=trCoreSync();trSync();return out;};
var trCoreRedraw=redraw;
redraw=function(){var out=trCoreRedraw();trSync();return out;};

/* --------------------------------------------------------------- rascunho */
// O que o operador ajustou no painel volta com o mapa; o nucleo continua dono
// do rascunho, este modulo so pendura um objeto proprio.
var trCoreDraftBody=draftBody;
draftBody=function(){
  var data=JSON.parse(trCoreDraftBody());
  data.transform={count:trArray.count,angle:trArray.angle,gap:trArray.gap,
                  anchor:trPanelAnchor(),lock:trPanelLock(),origin:trPanelOrigin()};
  return JSON.stringify(data);
};
var trCoreDraftApply=applyDraft;
applyDraft=function(data){
  var out=trCoreDraftApply(data);
  if(data&&data.transform){
    trArray.count=+data.transform.count||3;
    trArray.angle=+data.transform.angle||0;
    trArray.gap=+data.transform.gap||0;
    var anchor=document.getElementById('edtrAnchor'),lock=document.getElementById('edtrLock'),origin=document.getElementById('edtrOrigin');
    if(anchor)anchor.checked=!!data.transform.anchor;
    if(lock)lock.checked=data.transform.lock!==false;
    if(origin&&data.transform.origin)origin.value=data.transform.origin;
    trArrayFields();trSync();
  }
  return out;
};

/* ----------------------------------------------------------------- teclas */
// Alt+digito nao colide com nada: o nucleo so trata 1/2/3 SEM alt e o modulo
// vetorial ignora qualquer tecla com alt.
var TR_ALIGN_KEY={'1':'left','2':'centerx','3':'right','4':'top','5':'middley','6':'bottom'};
document.addEventListener('keydown',function(e){
  if(!editMode)return;
  if(/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)||!!(e.target&&e.target.isContentEditable))return;
  if(e.ctrlKey||e.metaKey)return;
  if(e.altKey){
    if(TR_ALIGN_KEY[e.key]){e.preventDefault();trAlign(TR_ALIGN_KEY[e.key]);return;}
    if(e.key==='7'){e.preventDefault();trDistribute('x');return;}
    if(e.key==='8'){e.preventDefault();trDistribute('y');return;}
    return;
  }
  var key=e.key.toLowerCase();
  if(key==='t'){e.preventDefault();if(trPanel&&!trPanel.hidden)trShow(false);else trFocus();}
  if(key==='r'){e.preventDefault();setTool(tool==='array'?'select':'array');}
  if(key==='e'){e.preventDefault();trFitSelection();}
  if(key==='h'){e.preventDefault();trFlip(e.shiftKey?'v':'h');}
});

/* --------------------------------------------------------------------- api */
// Superficie publica para a barra de ferramentas, para os outros modulos do
// editor e para os testes de navegador.
window.nexoloteTransform={
  align:trAlign,distribute:trDistribute,rotate:trRotate,scale:trScale,resize:trResize,
  flip:trFlip,setAngle:trSetAngle,metrics:trMetrics,box:trBoxOf,ring:trRing,
  repeat:trArrayApply,arraySet:trArraySet,arrayVector:function(){return trArrayVector();},
  arrayState:function(){return{count:trArray.count,angle:trArray.angle,gap:trArray.gap,
    src:trArray.src.slice(),live:trArray.live};},
  fit:trFitSelection,fitLot:trFit,neighbour:trNeighbour,
  panel:{show:trShow,focus:trFocus,sync:trSync,node:function(){return trPanel;}},
  math:{nameParts:trNameParts,nextName:trNextName,spread:trSpreadDeltas,ringAngle:trRingAngle,
        fitMap:trFitMap,alignDelta:trAlignDelta,ringBox:trRingBox,project:trProj}
};
