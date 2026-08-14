/* ==========================================================================
   NexoLote - geometria e ferramentas de caminho.
   Este arquivo e concatenado depois de editor.js dentro do MESMO bloco de
   script, e por isso enxerga os globais de la (L, vb, svg, lotsrot, toLocal,
   ptsArray, setLotPoints, makePatch, batchOps, redraw...). Tudo que e novo
   entra pelos pontos de extensao declarados em editor.js: registerTool(),
   onOverlayRedraw() e o objeto SNAP.
   ========================================================================== */

/* ------------------------------------------------------------------ escala */
// Tolerancia de ima e tamanho de alca sao em pixels de tela: em zoom afastado
// um lote inteiro cabe em 10 px e em zoom fechado um vertice ocupa a tela toda.
function vecScale(){var r=svg.getBoundingClientRect(),w=r.width||1,h=r.height||1;return Math.min(w/vb.w,h/vb.h)||1;}
function vecPx(px){return px/vecScale();}
function vecUnit(){return Math.max(.35,vb.w*.004);}
function vecNum(v){return Math.round(v*100)/100;}
function vecLocal(e){return toLocal(c2s(e.clientX,e.clientY));}

/* -------------------------------------------------------------- geometria */
var VEC_EPS=1e-9;
function vecOpenRing(points){var r=points.slice();while(r.length>1&&Math.abs(r[0].x-r[r.length-1].x)<1e-6&&Math.abs(r[0].y-r[r.length-1].y)<1e-6)r.pop();return r;}
function vecLotRing(i){return L[i]?vecOpenRing(ptsArray(L[i].pts)):[];}
function vecArea(ring){var a=0,n=ring.length;for(var i=0;i<n;i++){var p=ring[i],q=ring[(i+1)%n];a+=p.x*q.y-q.x*p.y;}return a/2;}
function vecCentroid(ring){var a=vecArea(ring),n=ring.length;if(Math.abs(a)<1e-9){var sx=0,sy=0;for(var k=0;k<n;k++){sx+=ring[k].x;sy+=ring[k].y;}return{x:sx/n,y:sy/n};}
  var cx=0,cy=0;for(var i=0;i<n;i++){var p=ring[i],q=ring[(i+1)%n],f=p.x*q.y-q.x*p.y;cx+=(p.x+q.x)*f;cy+=(p.y+q.y)*f;}return{x:cx/(6*a),y:cy/(6*a)};}
function vecCross(a,b,p){return (b.x-a.x)*(p.y-a.y)-(b.y-a.y)*(p.x-a.x);}
function vecLerp(a,b,t){return{x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t};}
function vecSame(a,b,eps){return Math.abs(a.x-b.x)<=eps&&Math.abs(a.y-b.y)<=eps;}
function vecPointInRing(p,ring){var inside=false,n=ring.length;for(var i=0,j=n-1;i<n;j=i++){var a=ring[i],b=ring[j];
  if((a.y>p.y)!==(b.y>p.y)&&p.x<(b.x-a.x)*(p.y-a.y)/(b.y-a.y)+a.x)inside=!inside;}return inside;}
// Projecao do ponto no segmento: devolve distancia, parametro e o pe da perpendicular.
function vecProject(p,a,b){var dx=b.x-a.x,dy=b.y-a.y,len=dx*dx+dy*dy;
  if(len<VEC_EPS)return{d:Math.hypot(p.x-a.x,p.y-a.y),t:0,x:a.x,y:a.y};
  var t=((p.x-a.x)*dx+(p.y-a.y)*dy)/len,ct=t<0?0:(t>1?1:t),x=a.x+dx*ct,y=a.y+dy*ct;
  return{d:Math.hypot(p.x-x,p.y-y),t:t,x:x,y:y};}
function vecOnRing(p,ring,eps){var n=ring.length;for(var i=0;i<n;i++){if(vecProject(p,ring[i],ring[(i+1)%n]).d<=eps)return true;}return false;}
// Cruzamento proprio de dois segmentos (ignora encostar so na ponta).
function vecSegHit(a,b,c,d){var r1=b.x-a.x,r2=b.y-a.y,s1=d.x-c.x,s2=d.y-c.y,den=r1*s2-r2*s1;
  if(Math.abs(den)<1e-12)return null;
  var t=((c.x-a.x)*s2-(c.y-a.y)*s1)/den,u=((c.x-a.x)*r2-(c.y-a.y)*r1)/den;
  if(t<1e-9||t>1-1e-9||u<1e-9||u>1-1e-9)return null;
  return{t:t,u:u,x:a.x+r1*t,y:a.y+r2*t};}

/* ----------------------------------------------------------------- bezier */
// Mesma logica do _bezier_steps de pdf_to_map.py: a flecha e estimada pelos
// pontos de controle e vira numero de segmentos. Manter o mesmo criterio faz o
// traco da caneta bater com o que o motor extrai do PDF.
var CURVE_FLATNESS_TOL=0.08,MAX_CURVE_STEPS=64;
function vecBezierSteps(p0,p1,p2,p3,tolerance){
  var tol=tolerance||CURVE_FLATNESS_TOL,chord=Math.hypot(p3.x-p0.x,p3.y-p0.y);
  if(chord<=1e-6)return 1;
  var first=Math.abs((p1.x-p0.x)*(p3.y-p0.y)-(p1.y-p0.y)*(p3.x-p0.x));
  var second=Math.abs((p2.x-p0.x)*(p3.y-p0.y)-(p2.y-p0.y)*(p3.x-p0.x));
  var sagitta=(first+second)/chord;
  if(sagitta<=tol)return 1;
  return Math.min(MAX_CURVE_STEPS,Math.max(2,Math.ceil(Math.sqrt(sagitta/tol)*4)));
}
// Pontos da curva sem repetir p0, igual ao laco do lado Python.
function vecBezierPoints(p0,p1,p2,p3,tolerance){
  var steps=vecBezierSteps(p0,p1,p2,p3,tolerance),out=[];
  for(var s=1;s<=steps;s++){var t=s/steps,u=1-t,uu=u*u,tt=t*t;
    out.push({x:uu*u*p0.x+3*uu*t*p1.x+3*u*tt*p2.x+tt*t*p3.x,
              y:uu*u*p0.y+3*uu*t*p1.y+3*u*tt*p2.y+tt*t*p3.y});}
  return out;
}

/* ------------------------------------------------- area em texto (m2 etc) */
// O campo area e texto livre ("312,50 m2"). Dividir e unir precisam somar e
// repartir esse numero sem perder o sufixo que o operador digitou.
function vecAreaParse(text){
  var raw=String(text==null?'':text),hit=raw.match(/-?\d[\d.,]*/);
  if(!hit)return null;
  var body=hit[0],before=raw.slice(0,hit.index),after=raw.slice(hit.index+body.length);
  var dot=body.lastIndexOf('.'),comma=body.lastIndexOf(','),sep=-1,decimals=0;
  if(dot>=0&&comma>=0)sep=Math.max(dot,comma);
  else if(dot>=0||comma>=0){var only=Math.max(dot,comma),tail=body.length-only-1;
    // "1.234" e milhar; "312.5" e decimal. Tres digitos depois so e milhar se
    // existir digito antes do separador.
    if(!(tail===3&&only>0))sep=only;}
  var digits=body.replace(/[.,]/g,'');
  if(sep>=0){decimals=body.length-sep-1;}
  var value=parseFloat(digits)/Math.pow(10,decimals);
  if(!isFinite(value))return null;
  return{value:value,decimals:decimals,sep:sep>=0?body.charAt(sep):',',before:before,after:after};
}
function vecAreaFormat(shape,value){
  if(!shape)return '';
  var text=value.toFixed(shape.decimals);
  if(shape.sep!=='.')text=text.replace('.',shape.sep);
  return shape.before+text+shape.after;
}

/* ------------------------------------------------------- indice espacial  */
// 1.500 lotes x 8 vertices = 12 mil arestas. Varrer tudo a cada mousemove
// custaria dezenas de ms; a grade responde olhando so as celulas vizinhas.
var VEC_MAX_CELLS=49,VEC_MAX_EDGE_CELLS=256;
var vecGrid={built:false,cell:32,map:{},keys:[],rings:[],ms:0,lots:0};
var vecDirty={},vecSkip=null,vecStats={queries:0,candidates:0,ms:0,last:0};
function vecGridInvalidate(){vecGrid.built=false;vecGrid.map={};vecGrid.keys=[];vecGrid.rings=[];vecDirty={};}
function vecGridIndex(i){
  var ring=vecLotRing(i),n=ring.length;
  if(n<2){vecGrid.keys[i]=[];vecGrid.rings[i]=null;return;}
  var flat=new Float64Array(n*2);
  for(var k=0;k<n;k++){flat[k*2]=ring[k].x;flat[k*2+1]=ring[k].y;}
  vecGrid.rings[i]=flat;
  var cell=vecGrid.cell,map=vecGrid.map,keys=[];
  for(var e=0;e<n;e++){
    var f=((e+1)%n)*2,ax=flat[e*2],ay=flat[e*2+1],bx=flat[f],by=flat[f+1];
    var i0=Math.floor(Math.min(ax,bx)/cell),i1=Math.floor(Math.max(ax,bx)/cell);
    var j0=Math.floor(Math.min(ay,by)/cell),j1=Math.floor(Math.max(ay,by)/cell);
    // Lote deformado com aresta atravessando o mapa nao pode explodir a grade.
    if((i1-i0+1)*(j1-j0+1)>VEC_MAX_EDGE_CELLS){i1=i0;j1=j0;}
    for(var ci=i0;ci<=i1;ci++)for(var cj=j0;cj<=j1;cj++){
      var key=ci+':'+cj,bucket=map[key]||(map[key]=[]);bucket.push(i,e);keys.push(key);}
  }
  vecGrid.keys[i]=keys;
}
function vecGridDrop(i){
  var keys=vecGrid.keys[i];if(!keys)return;
  for(var n=0;n<keys.length;n++){var bucket=vecGrid.map[keys[n]];if(!bucket)continue;
    for(var q=0;q<bucket.length;q+=2)if(bucket[q]===i){bucket.splice(q,2);q-=2;}}
  vecGrid.keys[i]=null;vecGrid.rings[i]=null;
}
function vecGridBuild(){
  var t0=performance.now();
  vecGrid={built:true,cell:Math.max(4,Math.min(W,H)/140),map:{},keys:[],rings:[],ms:0,lots:L.length};
  for(var i=0;i<L.length;i++)vecGridIndex(i);
  vecDirty={};vecGrid.ms=performance.now()-t0;
}
// Arrastar 300 lotes chamaria setLotPoints 300 vezes por mousemove: os lotes
// tocados so voltam para a grade quando param de se mexer.
function vecGridFlush(){
  for(var key in vecDirty){
    if(vecSkip&&vecSkip[key])continue;
    var i=+key;delete vecDirty[key];
    vecGridDrop(i);
    if(L[i])vecGridIndex(i);
  }
}
function vecGridEnsure(){if(!vecGrid.built)vecGridBuild();else vecGridFlush();}
function vecGridEach(x,y,r,visit){
  vecGridEnsure();
  var cell=vecGrid.cell,map=vecGrid.map;
  var i0=Math.floor((x-r)/cell),i1=Math.floor((x+r)/cell),j0=Math.floor((y-r)/cell),j1=Math.floor((y+r)/cell);
  if((i1-i0+1)*(j1-j0+1)>VEC_MAX_CELLS){
    // Zoom bem afastado: 10 px de tela viram centenas de unidades locais. Em
    // vez de varrer o mapa inteiro, limita a vizinhanca imediata do cursor.
    var ci=Math.floor(x/cell),cj=Math.floor(y/cell),k=Math.floor((Math.sqrt(VEC_MAX_CELLS)-1)/2);
    i0=ci-k;i1=ci+k;j0=cj-k;j1=cj+k;}
  for(var i=i0;i<=i1;i++)for(var j=j0;j<=j1;j++){
    var bucket=map[i+':'+j];if(!bucket)continue;
    for(var n=0;n<bucket.length;n+=2)visit(bucket[n],bucket[n+1]);}
}

/* ------------------------------------------------------------------- ima  */
var vecSnapOn=true,VEC_SNAP_PX=10,vecGuide=null;
var VEC_KIND_ORDER={vertex:0,mid:1,edge:2,angle:0};
function vecSnapQuery(p,options){
  var opts=options||{},tol=vecPx(VEC_SNAP_PX),skip=opts.skip||null,best=null,seen=0,t0=performance.now();
  vecGridEach(p.x,p.y,tol,function(lot,edge){
    if(skip&&skip[lot])return;
    var flat=vecGrid.rings[lot];if(!flat)return;
    seen++;
    var n=flat.length/2,f=((edge+1)%n)*2,a={x:flat[edge*2],y:flat[edge*2+1]},b={x:flat[f],y:flat[f+1]};
    var dv=Math.hypot(p.x-a.x,p.y-a.y);
    if(dv<=tol)best=vecBetter(best,{k:'vertex',x:a.x,y:a.y,d:dv,lot:lot,edge:edge});
    var mx=(a.x+b.x)/2,my=(a.y+b.y)/2,dm=Math.hypot(p.x-mx,p.y-my);
    if(dm<=tol)best=vecBetter(best,{k:'mid',x:mx,y:my,d:dm,lot:lot,edge:edge,ax:a.x,ay:a.y,bx:b.x,by:b.y});
    var pr=vecProject(p,a,b);
    if(pr.d<=tol&&pr.t>0.02&&pr.t<0.98)best=vecBetter(best,{k:'edge',x:pr.x,y:pr.y,d:pr.d,lot:lot,edge:edge,ax:a.x,ay:a.y,bx:b.x,by:b.y});
  });
  vecStats.queries++;vecStats.candidates+=seen;vecStats.last=performance.now()-t0;vecStats.ms+=vecStats.last;
  return best;
}
function vecBetter(current,candidate){
  if(!current)return candidate;
  var a=VEC_KIND_ORDER[current.k],b=VEC_KIND_ORDER[candidate.k];
  if(b!==a)return b<a?candidate:current;
  return candidate.d<current.d?candidate:current;
}
// Trava de angulo: projeta no eixo de 0/45/90 mais proximo em vez de girar o
// ponto, assim ele continua acompanhando o cursor.
function vecAngleLock(anchor,p){
  var dx=p.x-anchor.x,dy=p.y-anchor.y;
  if(Math.abs(dx)<1e-9&&Math.abs(dy)<1e-9)return{x:p.x,y:p.y};
  var step=Math.PI/4,angle=Math.round(Math.atan2(dy,dx)/step)*step,ux=Math.cos(angle),uy=Math.sin(angle);
  var d=dx*ux+dy*uy;
  return{x:anchor.x+ux*d,y:anchor.y+uy*d};
}
function vecSnapPoint(p,ev,options){
  var opts=options||{},out={x:p.x,y:p.y},anchor=null;
  vecGuide=null;
  if(ev&&ev.shiftKey)anchor=opts.anchor||vecAnchorOf(opts);
  if(anchor){
    out=vecAngleLock(anchor,p);
    vecGuide={k:'angle',x:out.x,y:out.y,ax:anchor.x,ay:anchor.y};
  }else if(vecSnapOn){
    var skip=opts.skip;
    if(!skip&&opts.lot!=null){skip={};skip[opts.lot]=1;}
    var hit=vecSnapQuery(p,{skip:skip});
    if(hit){out={x:hit.x,y:hit.y};vecGuide=hit;}
  }
  vecGuideDraw();
  return out;
}
// Ancora do angulo quando quem chama nao informa: o vizinho do vertice.
function vecAnchorOf(opts){
  if(opts.lot==null||opts.vertex==null)return null;
  var ring=vecLotRing(opts.lot);if(ring.length<2)return null;
  return ring[(opts.vertex-1+ring.length)%ring.length];
}
function vecSnapSet(on,quiet){
  vecSnapOn=!!on;
  if(!vecSnapOn){vecGuide=null;vecGuideDraw();}
  if(typeof markDirty==='function')markDirty();
  if(!quiet)toast(vecSnapOn?'Ima ligado (S)':'Ima desligado (S)');
  return vecSnapOn;
}

/* ---------------------------------------------------- ima ao mover lotes  */
var vecMove=null;
function vecSnapBegin(kind,indices){
  vecGuide=null;
  if(kind!=='move'||!indices||!indices.length){vecMove=null;return;}
  var skip={},pts=[],max=16,targets=[],n;
  for(n=0;n<indices.length;n++)skip[indices[n]]=1;
  // Selecao grande nao pode custar centenas de leituras no pointerdown nem
  // dezenas de consultas por mousemove. Ate quatro lotes entram inteiros (o caso
  // real de encostar no vizinho); acima disso vai um vertice por lote amostrado.
  if(indices.length<=max){targets=indices.slice();}
  else{var stride=indices.length/max;for(n=0;n<max;n++)targets.push(indices[Math.floor(n*stride)]);}
  var whole=indices.length<=4;
  for(n=0;n<targets.length&&pts.length<max;n++){
    var ring=vecLotRing(targets[n]);
    if(!ring.length)continue;
    if(whole)pts=pts.concat(ring.slice(0,max-pts.length));
    else pts.push(ring[0]);
  }
  vecSkip=skip;
  // Sonda: setLotPoints grava com uma casa decimal, entao o deslocamento
  // aplicado de verdade nao e o pedido. Sem ler de volta um vertice conhecido o
  // erro de arredondamento acumula passo a passo e o lote nunca encosta exato.
  var probe=vecLotRing(indices[0]);
  vecMove={skip:skip,pts:pts,raw:{x:0,y:0},probe:probe.length?{i:indices[0],x:probe[0].x,y:probe[0].y}:null};
}
function vecSnapEnd(){
  vecMove=null;vecSkip=null;vecGridFlush();
  vecGuide=null;vecGuideDraw();
}
function vecSnapTranslation(dx,dy,ev){
  if(!vecMove)return{x:dx,y:dy};
  vecMove.raw.x+=dx;vecMove.raw.y+=dy;
  var want={x:vecMove.raw.x,y:vecMove.raw.y},guide=null;
  if(ev&&ev.shiftKey){
    want=vecAngleLock({x:0,y:0},want);
  }else if(vecSnapOn){
    var best=null,tol=vecPx(VEC_SNAP_PX);
    for(var n=0;n<vecMove.pts.length;n++){
      var moved={x:vecMove.pts[n].x+want.x,y:vecMove.pts[n].y+want.y};
      var hit=vecSnapQuery(moved,{skip:vecMove.skip});
      if(hit&&(!best||hit.d<best.d))best={d:hit.d,dx:hit.x-moved.x,dy:hit.y-moved.y,hit:hit};
      if(best&&best.d<tol*.15)break;
    }
    if(best){want.x+=best.dx;want.y+=best.dy;guide=best.hit;}
  }
  vecGuide=guide;vecGuideDraw();
  var applied={x:0,y:0};
  if(vecMove.probe){
    var now=vecLotRing(vecMove.probe.i);
    if(now.length){applied.x=now[0].x-vecMove.probe.x;applied.y=now[0].y-vecMove.probe.y;}
  }
  return{x:want.x-applied.x,y:want.y-applied.y};
}

/* -------------------------------------------------------------- overlay   */
// Camada propria: nao da para usar as classes de editor.css (outro dono) nem
// mexer no editor.html, entao os estilos vao inline no atributo.
var vecLayer=el('g');
vecLayer.setAttribute('id','vecoverlay');
vecLayer.setAttribute('pointer-events','none');
lotsrot.appendChild(vecLayer);
function vecClear(){while(vecLayer.firstChild)vecLayer.removeChild(vecLayer.firstChild);}
function vecShape(tag,attrs){var node=el(tag);for(var key in attrs)node.setAttribute(key,attrs[key]);vecLayer.appendChild(node);return node;}
function vecLine(a,b,color,width,dash){
  return vecShape('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,stroke:color,'stroke-width':width,
    'stroke-dasharray':dash||'','vector-effect':'non-scaling-stroke','stroke-linecap':'round'});
}
function vecDot(p,fill,radius,stroke){
  return vecShape('circle',{cx:p.x,cy:p.y,r:radius,fill:fill,stroke:stroke||'#ffffff','stroke-width':1,'vector-effect':'non-scaling-stroke'});
}
function vecDiamond(p,size,color){
  var d='M'+(p.x-size)+' '+p.y+'L'+p.x+' '+(p.y-size)+'L'+(p.x+size)+' '+p.y+'L'+p.x+' '+(p.y+size)+'Z';
  return vecShape('path',{d:d,fill:'none',stroke:color,'stroke-width':1.6,'vector-effect':'non-scaling-stroke'});
}
var VEC_GUIDE_COLOR={vertex:'#ff3d8b',mid:'#ffb020',edge:'#12b8ff',angle:'#ff3d8b'};
function vecGuideDraw(){redrawOverlays();}
function vecDrawGuide(){
  if(!vecGuide)return;
  var u=vecUnit(),color=VEC_GUIDE_COLOR[vecGuide.k]||'#ff3d8b';
  if(vecGuide.k==='angle')vecLine({x:vecGuide.ax,y:vecGuide.ay},{x:vecGuide.x,y:vecGuide.y},color,1,(u*3)+' '+(u*2));
  if(vecGuide.k==='edge'||vecGuide.k==='mid')vecLine({x:vecGuide.ax,y:vecGuide.ay},{x:vecGuide.bx,y:vecGuide.by},color,1.4,'');
  vecDiamond({x:vecGuide.x,y:vecGuide.y},u*2.2,color);
}

/* ---------------------------------------------------------------- caneta  */
// No = ponto do caminho com alca de entrada (i) e de saida (o) absolutas.
// Clique cria canto (sem alca); clique-e-arrasta cria curva simetrica; com Alt
// so a alca de saida se move e o canto fica quebrado, como no Illustrator.
var vecPen={nodes:[],drag:null,hover:null,closing:false};
function vecPenReset(){vecPen.nodes=[];vecPen.drag=null;vecPen.hover=null;vecPen.closing=false;vecGuide=null;}
function vecPenNode(x,y){return{x:x,y:y,i:null,o:null};}
function vecPenAnchor(){return vecPen.nodes.length?vecPen.nodes[vecPen.nodes.length-1]:null;}
function vecPenSnap(e){
  var anchor=vecPen.nodes.length?{x:vecPenAnchor().x,y:vecPenAnchor().y}:null;
  return vecSnapPoint(vecLocal(e),e,{anchor:anchor});
}
function vecPenNearFirst(p){
  if(vecPen.nodes.length<2)return false;
  var first=vecPen.nodes[0];
  return Math.hypot(p.x-first.x,p.y-first.y)<=vecPx(12);
}
function vecPenDown(e){
  // Segundo dedo (pinca) e botao direito continuam sendo do mapa.
  if(ptrs.size>1||(e.button!=null&&e.button!==0))return false;
  var p=vecPenSnap(e);
  if(vecPenNearFirst(p)&&vecPen.nodes.length>=3){vecPenFinish();return true;}
  vecPen.nodes.push(vecPenNode(p.x,p.y));
  vecPen.drag={index:vecPen.nodes.length-1,moved:false,start:{x:e.clientX,y:e.clientY}};
  vecPen.hover=null;
  vecGuideDraw();
  return true;
}
// O pointermove de editor.js so trata ponteiro que ja passou pelo pointerdown
// (ele guarda os ids em ptrs). A previa da caneta precisa acompanhar o mouse
// solto, entao a ferramenta tambem recebe um gancho de hover.
svg.addEventListener('pointermove',function(e){
  if(!editMode||ptrs.size)return;
  var spec=TOOLS[tool];
  if(spec&&typeof spec.hover==='function')spec.hover(e);
});
function vecPenMove(e){
  if(ptrs.size>1)return false;
  if(vecPen.drag){
    var node=vecPen.nodes[vecPen.drag.index],p=vecLocal(e);
    if(Math.abs(e.clientX-vecPen.drag.start.x)+Math.abs(e.clientY-vecPen.drag.start.y)>3)vecPen.drag.moved=true;
    if(vecPen.drag.moved){
      node.o={x:p.x,y:p.y};
      node.i=e.altKey?node.i:{x:2*node.x-p.x,y:2*node.y-p.y};
    }
    vecGuideDraw();
    return true;
  }
  // O ima tem que aparecer antes do primeiro clique: e nele que o operador
  // encosta o inicio do lote novo no vertice do vizinho.
  var hover=vecPenSnap(e);
  vecPen.hover=vecPen.nodes.length?hover:null;
  vecPen.closing=vecPen.nodes.length?vecPenNearFirst(hover):false;
  vecGuideDraw();
  return true;
}
function vecPenUp(){
  if(!vecPen.drag)return true;
  var node=vecPen.nodes[vecPen.drag.index];
  if(!vecPen.drag.moved){node.i=null;node.o=null;}
  vecPen.drag=null;vecGuideDraw();
  return true;
}
// Segmento cubico entre dois nos; sem alca dos dois lados vira reta.
function vecPenSegment(a,b){
  if(!a.o&&!b.i)return[{x:b.x,y:b.y}];
  return vecBezierPoints({x:a.x,y:a.y},a.o||{x:a.x,y:a.y},b.i||{x:b.x,y:b.y},{x:b.x,y:b.y});
}
function vecPenTessellate(nodes,closed){
  if(nodes.length<2)return nodes.map(function(n){return{x:n.x,y:n.y};});
  var out=[{x:nodes[0].x,y:nodes[0].y}],last=closed?nodes.length:nodes.length-1;
  for(var k=0;k<last;k++)out=out.concat(vecPenSegment(nodes[k],nodes[(k+1)%nodes.length]));
  if(closed&&out.length>1&&vecSame(out[0],out[out.length-1],1e-6))out.pop();
  return out;
}
function vecPenPathD(nodes,extra,closed){
  var list=nodes.slice();
  if(extra)list.push(vecPenNode(extra.x,extra.y));
  if(!list.length)return '';
  var d='M'+vecNum(list[0].x)+' '+vecNum(list[0].y),last=closed?list.length:list.length-1;
  for(var k=0;k<last;k++){
    var a=list[k],b=list[(k+1)%list.length];
    if(!a.o&&!b.i)d+='L'+vecNum(b.x)+' '+vecNum(b.y);
    else{var c1=a.o||a,c2=b.i||b;
      d+='C'+vecNum(c1.x)+' '+vecNum(c1.y)+' '+vecNum(c2.x)+' '+vecNum(c2.y)+' '+vecNum(b.x)+' '+vecNum(b.y);}
  }
  return d;
}
function vecPenDraw(){
  if(!vecPen.nodes.length)return;
  var u=vecUnit(),preview=vecPen.drag?null:vecPen.hover;
  var d=vecPenPathD(vecPen.nodes,preview,false);
  if(d)vecShape('path',{d:d,fill:'none',stroke:'#36d889','stroke-width':1.6,'vector-effect':'non-scaling-stroke'});
  if(vecPen.closing&&vecPen.nodes.length>=3)
    vecLine(vecPen.nodes[vecPen.nodes.length-1],vecPen.nodes[0],'#36d889',1.2,(u*3)+' '+(u*2));
  for(var k=0;k<vecPen.nodes.length;k++){
    var node=vecPen.nodes[k];
    if(node.o){vecLine(node,node.o,'#12b8ff',1,'');vecDot(node.o,'#12b8ff',u*1.4);}
    if(node.i){vecLine(node,node.i,'#12b8ff',1,'');vecDot(node.i,'#12b8ff',u*1.4);}
    vecDot(node,k===0?'#36d889':'#ffffff',u*1.8,'#0d2f22');
  }
  if(preview)vecDiamond(preview,u*1.6,'#36d889');
}
function vecPenFinish(){
  if(vecPen.nodes.length<3){toast('Marque pelo menos tres pontos.',true);return false;}
  var points=vecPenTessellate(vecPen.nodes,true);
  if(points.length<3){toast('Caminho muito curto para virar lote.',true);return false;}
  vecPenReset();
  // Reaproveita finishDraft: mesmo registro no historico, mesmo nome e mesma
  // selecao que o desenho manual antigo.
  draft=points.map(function(p){return{x:+p.x.toFixed(1),y:+p.y.toFixed(1)};});
  finishDraft();
  vecGuideDraw();
  return true;
}
function vecPenKey(e){
  if(e.key==='Enter'){e.preventDefault();vecPenFinish();return true;}
  if(e.key==='Backspace'||e.key==='Delete'){
    if(!vecPen.nodes.length)return false;
    e.preventDefault();vecPen.nodes.pop();vecPen.drag=null;vecGuideDraw();return true;}
  if(e.key==='Escape'){
    if(!vecPen.nodes.length)return false;
    e.preventDefault();vecPenReset();vecGuideDraw();toast('Caminho cancelado');return true;}
  return false;
}
registerTool('pen',{
  button:'edpen',cursor:'draw',
  status:function(){return 'Caneta: clique reto, arraste para curva, Enter fecha';},
  enter:function(){vecPenReset();},
  exit:function(){vecPenReset();vecGuide=null;},
  down:vecPenDown,move:vecPenMove,up:vecPenUp,key:vecPenKey,hover:vecPenMove,
  click:function(){return true;}
});

/* ---------------------------------------------- vertices: inserir/remover */
function vecVertexApply(i,ring,label){
  var op=beginPatch([i],['pts']);
  setLotPoints(i,ring);
  sealPatch(op);
  redrawVertices();scheduleListRender();
  if(label)toast(label);
}
function vecVertexInsert(i,p){
  var ring=vecLotRing(i);if(ring.length<2)return false;
  var best=null;
  for(var k=0;k<ring.length;k++){
    var pr=vecProject(p,ring[k],ring[(k+1)%ring.length]);
    if(!best||pr.d<best.d)best={d:pr.d,at:k+1,x:pr.x,y:pr.y};
  }
  if(!best||best.d>vecPx(14)){toast('Clique duplo em cima da aresta para inserir o ponto.',true);return false;}
  ring.splice(best.at,0,{x:best.x,y:best.y});
  vecVertexApply(i,ring,'Ponto inserido');
  return true;
}
function vecVertexRemove(i,index){
  var ring=vecLotRing(i);
  if(ring.length<=3){toast('Um lote precisa de pelo menos tres pontos.',true);return false;}
  if(index<0||index>=ring.length)return false;
  ring.splice(index,1);
  vecVertexApply(i,ring,'Ponto removido');
  return true;
}
svg.addEventListener('dblclick',function(e){
  if(!editMode||tool!=='vertex'||selected.size!==1)return;
  var i=firstSelected();if(i==null||!L[i])return;
  var cls=e.target.getAttribute?e.target.getAttribute('class')||'':'';
  e.preventDefault();
  if(cls.indexOf('vertexpt')>=0&&+e.target.dataset.i===i){vecVertexRemove(i,+e.target.dataset.v);return;}
  var p=vecLocal(e),ring=vecLotRing(i),near=-1;
  for(var k=0;k<ring.length;k++)if(Math.hypot(p.x-ring[k].x,p.y-ring[k].y)<=vecPx(10)){near=k;break;}
  if(near>=0)vecVertexRemove(i,near);
  else vecVertexInsert(i,p);
});
/* --------------------------------------- Alt+arrastar: canto vira curva   */
// O formato de armazenamento e lista de pontos, sem alca. Alt+arrastar num
// vertice quebra a simetria do canto trocando as duas arestas vizinhas por uma
// curva que passa pelo cursor, tesselada com a mesma tolerancia do motor.
var vecBend=null;
function vecBendRing(ring,index,through){
  var n=ring.length,prev=ring[(index-1+n)%n],next=ring[(index+1)%n];
  var q={x:2*through.x-(prev.x+next.x)/2,y:2*through.y-(prev.y+next.y)/2};
  var c1={x:prev.x+2/3*(q.x-prev.x),y:prev.y+2/3*(q.y-prev.y)};
  var c2={x:next.x+2/3*(q.x-next.x),y:next.y+2/3*(q.y-next.y)};
  var curve=vecBezierPoints(prev,c1,c2,next),out=[];
  for(var k=0;k<n;k++){
    if(k===index){for(var c=0;c+1<curve.length;c++)out.push(curve[c]);}
    else out.push(ring[k]);
  }
  // Arrastar em cima da corda apagaria o vertice; um lote nunca fica com menos
  // de tres pontos.
  return out.length>=3?out:ring.slice();
}
registerTool('vertex',{
  down:function(e){
    var cls=e.target.getAttribute?e.target.getAttribute('class')||'':'';
    if(!e.altKey||cls.indexOf('vertexpt')<0)return false;
    var i=+e.target.dataset.i,ring=vecLotRing(i);
    if(ring.length<3)return false;
    suspendLabels();
    vecBend={i:i,v:+e.target.dataset.v,ring:ring,op:beginPatch([i],['pts'])};
    return true;
  },
  move:function(e){
    if(!vecBend)return false;
    setLotPoints(vecBend.i,vecBendRing(vecBend.ring,vecBend.v,vecLocal(e)));
    redrawVertices();
    return true;
  },
  up:function(){
    if(!vecBend)return false;
    sealPatchOrDrop(vecBend.op);vecBend=null;
    scheduleListRender();renderEditor();updateLabelVisibility(true);
    return true;
  }
});

/* --------------------------------------------------------------- dividir */
// Sutherland-Hodgman com um semiplano de cada vez: a regiao de corte e convexa,
// entao o resultado e exato para lote convexo. Lote concavo pode gerar as
// arestas falsas classicas do algoritmo, e por isso o corte e recusado quando a
// reta atravessa o contorno em mais de dois pontos.
function vecClipHalfPlane(ring,a,b,side){
  var out=[],n=ring.length;
  for(var i=0;i<n;i++){
    var cur=ring[i],nxt=ring[(i+1)%n],dc=vecCross(a,b,cur)*side,dn=vecCross(a,b,nxt)*side;
    if(dc>=0)out.push({x:cur.x,y:cur.y});
    if((dc>0&&dn<0)||(dc<0&&dn>0)){var t=dc/(dc-dn);out.push(vecLerp(cur,nxt,t));}
  }
  return out;
}
function vecLineCrossings(ring,a,b){
  var signs=[],n=ring.length,eps=1e-7;
  for(var i=0;i<n;i++){var d=vecCross(a,b,ring[i]);if(d>eps)signs.push(1);else if(d<-eps)signs.push(-1);}
  if(signs.length<2)return 0;
  var changes=0;
  for(var k=0;k<signs.length;k++)if(signs[k]!==signs[(k+1)%signs.length])changes++;
  return changes;
}
function vecDedupe(ring,eps){
  var out=[];
  for(var i=0;i<ring.length;i++){var p=ring[i];if(!out.length||!vecSame(out[out.length-1],p,eps))out.push(p);}
  while(out.length>1&&vecSame(out[0],out[out.length-1],eps))out.pop();
  return out;
}
function vecSplitRing(ring,a,b){
  if(ring.length<3)return{ok:false,reason:'O lote nao tem contorno valido.'};
  if(Math.hypot(b.x-a.x,b.y-a.y)<1e-6)return{ok:false,reason:'Trace a linha de corte atravessando o lote.'};
  var crossings=vecLineCrossings(ring,a,b);
  if(crossings===0)return{ok:false,reason:'A linha de corte nao atravessa o lote.'};
  if(crossings>2)return{ok:false,reason:'A linha corta o lote em '+crossings+' pontos; use um corte que atravesse uma vez so.'};
  var left=vecDedupe(vecClipHalfPlane(ring,a,b,1),1e-6),right=vecDedupe(vecClipHalfPlane(ring,a,b,-1),1e-6);
  if(left.length<3||right.length<3)return{ok:false,reason:'O corte precisa entrar e sair do lote.'};
  var total=Math.abs(vecArea(ring)),al=Math.abs(vecArea(left)),ar=Math.abs(vecArea(right));
  if(al<total*0.005||ar<total*0.005)return{ok:false,reason:'Uma das partes ficaria sem area; passe a linha mais pelo meio.'};
  // Rede de seguranca: soma das partes tem que reproduzir o original.
  if(Math.abs(al+ar-total)>Math.max(1e-6,total*1e-4))return{ok:false,reason:'O corte nao fechou a geometria; refaca a linha.'};
  return{ok:true,parts:[left,right],areas:[al,ar],total:total};
}
function vecSplitLot(index,a,b){
  var lot=L[index];
  if(!lot)return{ok:false,reason:'Selecione um lote para dividir.'};
  var ring=vecLotRing(index),cut=vecSplitRing(ring,a,b);
  if(!cut.ok){toast(cut.reason,true);return cut;}
  var shape=vecAreaParse(lot.area),before=makePatch([index],['pts','nome','area']);
  var second=JSON.parse(JSON.stringify(lot));
  delete second._cx;delete second._cy;
  var baseName=lot.nome||('Lote '+(index+1));
  setLotPoints(index,cut.parts[0]);
  lot.nome=baseName+'-A';
  second.nome=baseName+'-B';
  second.pts=cut.parts[1].map(function(p){return p.x.toFixed(1)+','+p.y.toFixed(1);}).join(' ');
  second.index=L.length;
  if(shape){
    lot.area=vecAreaFormat(shape,shape.value*cut.areas[0]/cut.total);
    second.area=vecAreaFormat(shape,shape.value*cut.areas[1]/cut.total);
  }
  sealPatch(before);
  L.splice(index+1,0,second);
  batchOps([before,{k:'insert',at:index+1,item:second}]);
  selected.clear();selected.add(index);selected.add(index+1);
  redraw();
  toast('Lote dividido em '+lot.nome+' e '+second.nome);
  return{ok:true,indices:[index,index+1]};
}

/* ------------------------------------------------------------------ unir */
// Varredura de arestas: cada aresta e quebrada nos cruzamentos e nos vertices
// dos outros poligonos, os pedacos internos (ou em cima da divisa) somem e o
// que sobra e costurado num contorno unico. Sem biblioteca no HTML, esta e a
// uniao que da para garantir; qualquer caso que nao fechar e recusado.
var VEC_WELD_STEPS=[0.25,0.6,1.2];
function vecWeldNodes(points,eps){
  var nodes=[],ids=[];
  for(var i=0;i<points.length;i++){
    var p=points[i],found=-1;
    for(var k=0;k<nodes.length;k++)if(vecSame(nodes[k],p,eps)){found=k;break;}
    if(found<0){found=nodes.length;nodes.push({x:p.x,y:p.y});}
    ids.push(found);
  }
  return{nodes:nodes,ids:ids};
}
function vecUnionRings(rings,eps){
  var tol=eps||0.25,polys=[],i,k,j,m;
  for(i=0;i<rings.length;i++){
    var ring=vecDedupe(rings[i],1e-6);
    if(ring.length<3)return{ok:false,reason:'Um dos lotes nao tem contorno valido.'};
    if(vecArea(ring)<0)ring.reverse();
    polys.push(ring);
  }
  // Solda de vertices: lotes vizinhos vem do mesmo desenho, mas os pontos sao
  // gravados com uma casa decimal e podem nao bater no ultimo digito.
  var all=[];
  for(i=0;i<polys.length;i++)for(k=0;k<polys[i].length;k++)all.push(polys[i][k]);
  var weld=vecWeldNodes(all,tol),cursor=0;
  for(i=0;i<polys.length;i++)for(k=0;k<polys[i].length;k++)polys[i][k]=weld.nodes[weld.ids[cursor++]];
  for(i=0;i<polys.length;i++){polys[i]=vecDedupe(polys[i],tol);if(polys[i].length<3)return{ok:false,reason:'Um dos lotes ficou degenerado.'};}
  // Quebra das arestas.
  var frags=[];
  for(i=0;i<polys.length;i++){
    var poly=polys[i];
    for(k=0;k<poly.length;k++){
      var a=poly[k],b=poly[(k+1)%poly.length],cuts=[0,1];
      for(j=0;j<polys.length;j++){
        if(j===i)continue;
        var other=polys[j];
        for(m=0;m<other.length;m++){
          var c=other[m],d=other[(m+1)%other.length],hit=vecSegHit(a,b,c,d);
          if(hit)cuts.push(hit.t);
          var pr=vecProject(c,a,b);
          if(pr.d<=tol&&pr.t>1e-6&&pr.t<1-1e-6)cuts.push(pr.t);
        }
      }
      cuts.sort(function(x,y){return x-y;});
      for(m=0;m+1<cuts.length;m++){
        if(cuts[m+1]-cuts[m]<1e-7)continue;
        frags.push({a:vecLerp(a,b,cuts[m]),b:vecLerp(a,b,cuts[m+1]),owner:i});
      }
    }
  }
  // Fica so o que esta na borda de fora: pedaco dentro de outro lote ou em cima
  // da divisa e interior da uniao.
  var keep=[];
  for(i=0;i<frags.length;i++){
    var f=frags[i],mid={x:(f.a.x+f.b.x)/2,y:(f.a.y+f.b.y)/2},drop=false;
    for(j=0;j<polys.length&&!drop;j++){
      if(j===f.owner)continue;
      if(vecOnRing(mid,polys[j],tol)||vecPointInRing(mid,polys[j]))drop=true;
    }
    if(!drop)keep.push(f);
  }
  if(keep.length<3)return{ok:false,reason:'Os lotes se sobrepoem demais para virar um contorno.'};
  // Costura: os pedacos viram arestas dirigidas entre nos soldados.
  var ends=[];
  for(i=0;i<keep.length;i++){ends.push(keep[i].a);ends.push(keep[i].b);}
  var net=vecWeldNodes(ends,tol),adjacency={},edges=[];
  for(i=0;i<keep.length;i++){
    var n0=net.ids[i*2],n1=net.ids[i*2+1];
    if(n0===n1)continue;
    edges.push({n0:n0,n1:n1,used:false});
    (adjacency[n0]=adjacency[n0]||[]).push(edges.length-1);
  }
  if(!edges.length)return{ok:false,reason:'Nao sobrou contorno para unir.'};
  var startEdge=0;
  for(i=1;i<edges.length;i++){
    var s=net.nodes[edges[i].n0],cur=net.nodes[edges[startEdge].n0];
    if(s.x<cur.x-1e-9||(Math.abs(s.x-cur.x)<=1e-9&&s.y<cur.y))startEdge=i;
  }
  var ringOut=[],guard=edges.length+4,edge=startEdge,first=edges[startEdge].n0,used=0;
  while(guard-- > 0){
    var current=edges[edge];
    current.used=true;used++;
    ringOut.push({x:net.nodes[current.n0].x,y:net.nodes[current.n0].y});
    if(current.n1===first)break;
    var candidates=adjacency[current.n1]||[],pick=-1,bestAngle=Infinity;
    var back=Math.atan2(net.nodes[current.n0].y-net.nodes[current.n1].y,net.nodes[current.n0].x-net.nodes[current.n1].x);
    for(i=0;i<candidates.length;i++){
      var candidate=edges[candidates[i]];
      if(candidate.used)continue;
      var angle=Math.atan2(net.nodes[candidate.n1].y-net.nodes[current.n1].y,net.nodes[candidate.n1].x-net.nodes[current.n1].x)-back;
      while(angle<=1e-9)angle+=Math.PI*2;
      while(angle>Math.PI*2)angle-=Math.PI*2;
      // Giro mais fechado no sentido horario mantem o interior a esquerda e
      // desenha o contorno externo mesmo quando tres lotes se encontram.
      if(angle<bestAngle){bestAngle=angle;pick=candidates[i];}
    }
    if(pick<0)return{ok:false,reason:'Os lotes precisam ser vizinhos (encostados) para unir.'};
    edge=pick;
  }
  if(used!==edges.length)return{ok:false,reason:'Os lotes precisam ser vizinhos (encostados) para unir.'};
  // Tira os pontos que sobraram alinhados nas antigas divisas.
  var clean=[],n=ringOut.length;
  for(i=0;i<n;i++){
    var prev=clean.length?clean[clean.length-1]:ringOut[(i-1+n)%n],point=ringOut[i],next=ringOut[(i+1)%n];
    if(vecProject(point,prev,next).d>0.01)clean.push(point);
  }
  clean=vecDedupe(clean.length>=3?clean:ringOut,1e-6);
  if(clean.length<3)return{ok:false,reason:'A uniao nao formou um contorno fechado.'};
  if(vecArea(clean)<0)clean.reverse();
  // A area de referencia vem dos contornos ORIGINAIS, nao dos soldados: assim a
  // propria solda entra na conta e um encaixe forcado e recusado.
  var area=Math.abs(vecArea(clean)),sum=0,biggest=0;
  for(i=0;i<rings.length;i++){var pa=Math.abs(vecArea(rings[i]));sum+=pa;if(pa>biggest)biggest=pa;}
  if(area<biggest*0.999||area>sum*1.003)return{ok:false,reason:'A uniao daria uma area errada; confira se os lotes sao vizinhos.'};
  for(i=0;i<polys.length;i++){
    var center=vecCentroid(polys[i]);
    if(vecPointInRing(center,polys[i])&&!vecPointInRing(center,clean))
      return{ok:false,reason:'Um dos lotes ficaria de fora da uniao.'};
  }
  return{ok:true,ring:clean,area:area,sum:sum};
}
function vecMergeLots(indices){
  var list=indices.slice().sort(function(a,b){return a-b;}),rings=[],i;
  if(list.length<2){toast('Selecione dois ou mais lotes vizinhos.',true);return{ok:false,reason:'selecao'};}
  for(i=0;i<list.length;i++){
    if(!L[list[i]])return{ok:false,reason:'lote inexistente'};
    rings.push(vecLotRing(list[i]));
  }
  // Lote vizinho nem sempre encosta no mesmo ponto: as divisas do CAD chegam com
  // sobra de decimo. A solda comeca fina e vai abrindo, mas cada tentativa passa
  // pela mesma validacao de area, entao afrouxar nao deixa passar geometria ruim.
  var union=null;
  for(var t=0;t<VEC_WELD_STEPS.length;t++){
    union=vecUnionRings(rings,VEC_WELD_STEPS[t]);
    if(union.ok)break;
  }
  if(!union.ok){toast(union.reason,true);return union;}
  var keep=list[0],lot=L[keep],shape=vecAreaParse(lot.area),total=0,parsed=0;
  for(i=0;i<list.length;i++){var piece=vecAreaParse(L[list[i]].area);if(piece){total+=piece.value;parsed++;}}
  var patch=makePatch([keep],['pts','area']),removed=[];
  setLotPoints(keep,union.ring);
  if(shape&&parsed===list.length)lot.area=vecAreaFormat(shape,total);
  sealPatch(patch);
  for(i=1;i<list.length;i++)removed.push({i:list[i],item:L[list[i]]});
  var drop={};
  for(i=1;i<list.length;i++)drop[list[i]]=1;
  L=L.filter(function(_,index){return !drop[index];});
  batchOps([patch,{k:'remove',items:removed}]);
  selected.clear();selected.add(keep);
  redraw();
  toast(list.length+' lotes unidos em '+(lot.nome||('#'+(keep+1)))+(parsed===list.length?'':' (area nao somada: texto livre)'));
  return{ok:true,index:keep};
}
function vecMergeSelection(){
  if(selected.size<2){toast('Selecione dois ou mais lotes vizinhos para unir.',true);return{ok:false,reason:'selecao'};}
  return vecMergeLots(Array.from(selected));
}

/* ------------------------------------------------------- ferramenta corte */
var vecCut=null;
registerTool('cut',{
  button:'edcut',cursor:'draw',
  status:function(){return 'Dividir: arraste a linha de corte de ponta a ponta';},
  ready:function(){
    if(selected.size!==1){toast('Selecione um unico lote para dividir.',true);return false;}
    return true;
  },
  enter:function(){vecCut=null;},
  exit:function(){vecCut=null;vecGuide=null;},
  down:function(e){
    var index=firstSelected();
    if(index==null||selected.size!==1){toast('Selecione um unico lote para dividir.',true);return true;}
    vecCut={index:index,a:vecSnapPoint(vecLocal(e),e,{lot:index}),b:null};
    vecGuideDraw();
    return true;
  },
  move:function(e){
    if(!vecCut)return true;
    vecCut.b=vecSnapPoint(vecLocal(e),e,{lot:vecCut.index,anchor:vecCut.a});
    vecGuideDraw();
    return true;
  },
  up:function(){
    if(!vecCut)return true;
    var cut=vecCut;vecCut=null;vecGuide=null;
    if(!cut.b||Math.hypot(cut.b.x-cut.a.x,cut.b.y-cut.a.y)<vecPx(6)){vecGuideDraw();toast('Arraste a linha de corte atravessando o lote.',true);return true;}
    vecSplitLot(cut.index,cut.a,cut.b);
    vecGuideDraw();
    return true;
  },
  click:function(){return true;}
});
function vecCutDraw(){
  if(!vecCut||!vecCut.b)return;
  var u=vecUnit();
  vecLine(vecCut.a,vecCut.b,'#ff3d8b',1.6,(u*4)+' '+(u*2.5));
  vecDot(vecCut.a,'#ff3d8b',u*1.5);vecDot(vecCut.b,'#ff3d8b',u*1.5);
}

/* --------------------------------------------------------------- overlay  */
onOverlayRedraw(function(){
  vecClear();
  if(!editMode)return;
  vecPenDraw();
  vecCutDraw();
  vecDrawGuide();
});

/* ------------------------------------------- indice sempre acompanhando L */
var vecCoreRedraw=redraw;
redraw=function(){vecGridInvalidate();return vecCoreRedraw();};
var vecCoreSetLotPoints=setLotPoints;
setLotPoints=function(i,points){vecCoreSetLotPoints(i,points);if(vecGrid.built)vecDirty[i]=1;};

/* ------------------------------------------------------- rascunho e teclas */
// O estado do ima acompanha o rascunho: quem desligou o ima nao quer ele de
// volta ao reabrir o mapa.
var vecCoreDraftBody=draftBody;
draftBody=function(){
  var data=JSON.parse(vecCoreDraftBody());
  data.vector={snap:vecSnapOn};
  return JSON.stringify(data);
};
var vecCoreDraftRestore=applyDraft;
applyDraft=function(data){
  var out=vecCoreDraftRestore(data);
  if(data&&data.vector)vecSnapSet(!!data.vector.snap,true);
  return out;
};
document.addEventListener('keydown',function(e){
  if(!editMode)return;
  if(e.ctrlKey||e.metaKey||e.altKey)return;
  if(/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)||!!(e.target&&e.target.isContentEditable))return;
  var key=e.key.toLowerCase();
  if(key==='b'){e.preventDefault();setTool('pen');}
  if(key==='c'){e.preventDefault();setTool('cut');}
  if(key==='u'){e.preventDefault();vecMergeSelection();}
  if(key==='s'){e.preventDefault();vecSnapSet(!vecSnapOn);}
});

/* --------------------------------------------------------- liga o ima     */
SNAP.point=vecSnapPoint;
SNAP.translation=vecSnapTranslation;
SNAP.begin=vecSnapBegin;
SNAP.end=vecSnapEnd;

/* ---------------------------------------------------------------- api     */
// Superficie publica para a barra de ferramentas (botoes edpen/edcut), para os
// outros modulos do editor e para os testes de navegador.
window.nexoloteVector={
  pen:function(){setTool('pen');},
  cut:function(){setTool('cut');},
  merge:vecMergeSelection,
  mergeLots:vecMergeLots,
  splitLot:vecSplitLot,
  insertVertex:vecVertexInsert,
  removeVertex:vecVertexRemove,
  bendVertex:function(i,v,through){
    var ring=vecLotRing(i);if(ring.length<3)return false;
    var op=beginPatch([i],['pts']);
    setLotPoints(i,vecBendRing(ring,v,through));
    sealPatchOrDrop(op);redrawVertices();return true;},
  snap:{
    get:function(){return vecSnapOn;},
    set:function(on){return vecSnapSet(on);},
    toggle:function(){return vecSnapSet(!vecSnapOn);},
    tolerancePx:function(px){if(px!=null)VEC_SNAP_PX=Math.max(1,+px||10);return VEC_SNAP_PX;},
    query:vecSnapQuery,
    stats:function(){return{queries:vecStats.queries,candidates:vecStats.candidates,
      lastMs:vecStats.last,avgMs:vecStats.queries?vecStats.ms/vecStats.queries:0,
      buildMs:vecGrid.ms,lots:vecGrid.lots,cell:vecGrid.cell};},
    reset:function(){vecStats={queries:0,candidates:0,ms:0,last:0};}
  },
  geometry:{
    ring:vecLotRing,area:vecArea,centroid:vecCentroid,pointInRing:vecPointInRing,
    bezierSteps:vecBezierSteps,bezierPoints:vecBezierPoints,
    clipHalfPlane:vecClipHalfPlane,splitRing:vecSplitRing,unionRings:vecUnionRings,
    areaParse:vecAreaParse,areaFormat:vecAreaFormat,tessellate:vecPenTessellate
  },
  penState:function(){return{nodes:vecPen.nodes.length,dragging:!!vecPen.drag,
    pts:vecPen.nodes.map(function(n){return{x:n.x,y:n.y,curved:!!(n.i||n.o)};}),
    guide:vecGuide?vecGuide.k:null};}
};
