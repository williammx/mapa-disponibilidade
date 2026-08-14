/* ==========================================================================
   NexoLote - selecao avancada, medida na escala da planta e renomear em lote.
   Concatenado no MESMO bloco de script depois de editor.js, entao enxerga os
   globais de la (L, selected, vb, svg, lotsrot, ptsArray, cachedCenter,
   lotCenter, beginPatch, sealPatchOrDrop, syncSelection, redraw, toast...).
   Tudo que e novo entra pelos pontos de extensao declarados no nucleo:
   registerTool(), onOverlayRedraw() e o objeto SNAP.

   O painel e montado por JS dentro de #edSelectPanel (o HTML e o CSS tem outro
   dono), reaproveitando as classes que ja existem em editor.css (.panel,
   .field, .formgrid, .inspectorSection). O pouco de estilo proprio vai num
   <style id="edsel-style"> com tudo prefixado edsel-.

   Este modulo carrega ANTES de editor-transform.js e editor-vector.js (ordem
   alfabetica), entao nao pode depender de nada que eles criem no carregamento:
   a geometria daqui e propria e o ima (SNAP) e sempre opcional.

   Teclas ocupadas por este modulo (todas so em modo edicao, sem Ctrl/Alt):
     L   laco livre                    K   regua (medir distancia)
     F   abre e foca o painel          I   inverter a selecao
     Q   selecionar a quadra do lote atual
     N   renomear em lote (foca o padrao)
     W   conferir areas: marca os lotes que divergem da metragem impressa
   ========================================================================== */

/* ------------------------------------------------------------------ base */
function selViewScale(){var r=svg.getBoundingClientRect(),w=r.width||1,h=r.height||1;return Math.min(w/vb.w,h/vb.h)||1;}
function selPx(px){return px/selViewScale();}
function selUnit(){return Math.max(.35,vb.w*.004);}
function selNum(text,fallback){var v=parseFloat(String(text==null?'':text).replace(',','.'));return isFinite(v)?v:fallback;}
// Numero para o operador brasileiro: milhar com ponto, decimal com virgula.
function selFmt(v,casas){
  if(!isFinite(v))return '-';
  var d=casas==null?(Math.abs(v)>=100?0:(Math.abs(v)>=1?1:2)):Math.max(0,Math.min(6,casas)),txt=Math.abs(v).toFixed(d);
  var parte=txt.split('.'),inteiro=parte[0],out='',n=0,k;
  for(k=inteiro.length-1;k>=0;k--){out=inteiro.charAt(k)+out;if(++n%3===0&&k>0)out='.'+out;}
  return (v<0?'-':'')+out+(parte[1]?','+parte[1]:'');
}
// px2 vira "1,9 M" acima de um milhao: 1.500 lotes somam numeros ilegiveis.
function selFmtPx(v){
  if(!isFinite(v))return '-';
  if(Math.abs(v)>=1e6)return selFmt(v/1e6,2)+' M px\u00b2';
  return selFmt(v,0)+' px\u00b2';
}
function selFmtM2(v){return selFmt(v,Math.abs(v)>=1000?0:2)+' m\u00b2';}
function selMedian(values){if(!values.length)return NaN;var copy=values.slice();copy.sort(function(a,b){return a-b;});return copy[Math.floor(copy.length/2)];}

/* -------------------------------------------------------------- geometria */
// Propria de proposito: editor-vector.js pode nao estar carregado (e quando
// esta, carrega depois deste arquivo).
function selRing(i){
  if(!L[i])return[];
  var r=ptsArray(L[i].pts);
  while(r.length>1&&Math.abs(r[0].x-r[r.length-1].x)<1e-6&&Math.abs(r[0].y-r[r.length-1].y)<1e-6)r.pop();
  return r;
}
function selRingArea(ring){var a=0,n=ring.length,i,p,q;for(i=0;i<n;i++){p=ring[i];q=ring[(i+1)%n];a+=p.x*q.y-q.x*p.y;}return Math.abs(a/2);}
function selPointInRing(p,ring){
  var inside=false,n=ring.length,i,j,a,b;
  for(i=0,j=n-1;i<n;j=i++){a=ring[i];b=ring[j];
    if((a.y>p.y)!==(b.y>p.y)&&p.x<(b.x-a.x)*(p.y-a.y)/(b.y-a.y)+a.x)inside=!inside;}
  return inside;
}
function selBox(points){
  var x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity,k,p;
  for(k=0;k<points.length;k++){p=points[k];if(p.x<x0)x0=p.x;if(p.x>x1)x1=p.x;if(p.y<y0)y0=p.y;if(p.y>y1)y1=p.y;}
  if(!points.length)return null;
  return{x0:x0,y0:y0,x1:x1,y1:y1,w:x1-x0,h:y1-y0,cx:(x0+x1)/2,cy:(y0+y1)/2};
}

/* -------------------------------------------------- metragem impressa (m2) */
// O campo area e texto livre vindo do PDF ("178.86m2", "1.234,56 m2"). O
// separador muda de planta para planta: tres digitos depois do ponto com
// digito antes e milhar, o resto e decimal.
function selParseArea(text){
  var raw=String(text==null?'':text),hit=raw.match(/-?\d[\d.,]*/);
  if(!hit)return null;
  var body=hit[0],dot=body.lastIndexOf('.'),comma=body.lastIndexOf(','),sep=-1,decimals=0;
  if(dot>=0&&comma>=0)sep=Math.max(dot,comma);
  else if(dot>=0||comma>=0){var only=Math.max(dot,comma),tail=body.length-only-1;
    if(!(tail===3&&only>0))sep=only;}
  if(sep>=0)decimals=body.length-sep-1;
  var value=parseFloat(body.replace(/[.,]/g,''))/Math.pow(10,decimals);
  return isFinite(value)?value:null;
}

/* ------------------------------------------------- cache de areas por lote */
// 1.509 lotes: recalcular a area de todo mundo a cada sincronizacao de painel
// travaria a tela. O cache e reconstruido quando o mapa muda (markDirty) e os
// lotes que so mudaram de forma voltam um a um.
var SEL_SCALE_MIN=20,SEL_AREA_TOL=.05;
var selCache={ready:false,n:0,px:[],printed:[],m2:[],off:[],ratio:NaN,samples:0,agreement:0,ms:0,dirty:{}};
var selStats={lassoMs:0,lassoPts:0,queryMs:0,queryHits:0,scaleMs:0,lots:0};
function selInvalidate(){selCache.ready=false;selCache.dirty={};}
function selTouch(i){if(selCache.ready)selCache.dirty[i]=1;}
function selMeasureLot(i){
  var ring=selRing(i);
  selCache.px[i]=ring.length>2?selRingArea(ring):0;
  var printed=L[i]?selParseArea(L[i].area):null;
  selCache.printed[i]=printed&&printed>0?printed:NaN;
}
// Escala da planta: mediana entre area do poligono e metragem impressa dos
// lotes que tem as duas. E o mesmo raciocinio de _area_agreement em
// pdf_to_map.py - numa malha correta a razao e praticamente constante, porque
// as duas descrevem o mesmo lote em escalas diferentes.
function selRebuild(){
  var t0=performance.now(),i,ratios=[];
  selCache.px=new Array(L.length);selCache.printed=new Array(L.length);selCache.m2=new Array(L.length);
  for(i=0;i<L.length;i++)selMeasureLot(i);
  for(i=0;i<L.length;i++)if(selCache.px[i]>0&&selCache.printed[i]>0)ratios.push(selCache.px[i]/selCache.printed[i]);
  var median=ratios.length>=SEL_SCALE_MIN?selMedian(ratios):NaN,good=0;
  selCache.ratio=median>0?median:NaN;
  selCache.samples=ratios.length;
  selCache.off=[];
  for(i=0;i<L.length;i++){
    var px=selCache.px[i],printed=selCache.printed[i];
    if(selCache.ratio>0){
      selCache.m2[i]=printed>0?printed:px/selCache.ratio;
      if(printed>0){
        if(Math.abs((px/printed)/selCache.ratio-1)<=SEL_AREA_TOL)good++;
        else selCache.off.push(i);
      }
    }else selCache.m2[i]=NaN;
  }
  selCache.agreement=selCache.samples?good/selCache.samples:0;
  selCache.n=L.length;selCache.ready=true;selCache.dirty={};
  selCache.ms=performance.now()-t0;selStats.scaleMs=selCache.ms;selStats.lots=L.length;
}
function selEnsure(){
  if(!selCache.ready||selCache.n!==L.length){selRebuild();return;}
  var key,sujos=0;
  for(key in selCache.dirty){sujos++;}
  if(!sujos)return;
  // Mexer na forma muda a razao daquele lote; a escala e a lista de divergentes
  // saem da amostra inteira, entao o caminho honesto e refazer a conta.
  selRebuild();
}
function selScale(){
  selEnsure();
  var ok=selCache.ratio>0&&selCache.samples>=SEL_SCALE_MIN;
  return{ok:ok,pxPerM2:ok?selCache.ratio:null,pxPerM:ok?Math.sqrt(selCache.ratio):null,
         samples:selCache.samples,lots:L.length,agreement:selCache.agreement,
         divergentes:ok?selCache.off.length:0,ms:selCache.ms,minimo:SEL_SCALE_MIN,tolerancia:SEL_AREA_TOL};
}
function selUnitName(){return selScale().ok?'m\u00b2':'px\u00b2';}
// Frase que o operador le quando a planta nao traz metragem suficiente: em vez
// de inventar escala, o editor continua em pixels e diz por que.
function selScaleNote(){
  var s=selScale();
  if(s.ok)return 'Escala '+selFmt(s.pxPerM2,2)+' px\u00b2/m\u00b2 ('+selFmt(s.pxPerM,3)+' px por metro) de '
    +selFmt(s.samples,0)+' lotes com metragem impressa \u00b7 '+selFmt(s.agreement*100,1)+'% batem em '
    +Math.round(SEL_AREA_TOL*100)+'%';
  return 'Sem escala: so '+selFmt(s.samples,0)+' de '+selFmt(L.length,0)+' lotes trazem metragem impressa (minimo '
    +SEL_SCALE_MIN+'). As medidas ficam em pixels.';
}
function selLotM2(i){selEnsure();var v=selCache.m2[i];return isFinite(v)?v:NaN;}
function selLotPx(i){selEnsure();var v=selCache.px[i];return isFinite(v)?v:0;}
// Area da selecao: soma calculada, soma impressa e quantos lotes tem metragem.
function selSum(indices){
  selEnsure();
  var px=0,m2=0,impresso=0,comArea=0,n=0,k,i;
  for(k=0;k<indices.length;k++){
    i=indices[k];if(!L[i])continue;
    n++;px+=selCache.px[i]||0;
    if(isFinite(selCache.m2[i]))m2+=selCache.m2[i];
    if(isFinite(selCache.printed[i])){impresso+=selCache.printed[i];comArea++;}
  }
  return{count:n,px:px,m2:selCache.ratio>0?m2:NaN,impresso:impresso,comArea:comArea};
}

/* ------------------------------------------------------ aplicar a selecao */
// Somar (Shift), subtrair (Alt) e substituir valem para o laco, para o
// criterio, para os semelhantes e para a caixa retangular do nucleo.
function selModeOf(e,padrao){
  if(e&&e.altKey)return 'sub';
  if(e&&e.shiftKey)return 'add';
  return padrao||selValue('edselMode')||'set';
}
function selExpandGroups(list){
  var out=[],visto={},k,i,membros,m;
  for(k=0;k<list.length;k++){
    i=list[k];if(!L[i]||visto[i])continue;
    membros=L[i].group?groupMembers(L[i].group):[i];
    for(m=0;m<membros.length;m++)if(!visto[membros[m]]){visto[membros[m]]=1;out.push(membros[m]);}
  }
  return out;
}
function selApply(list,mode,label){
  var alvo=selExpandGroups(list||[]),k;
  if(mode==='sub'){for(k=0;k<alvo.length;k++)selected['delete'](alvo[k]);}
  else{if(mode!=='add')selected.clear();for(k=0;k<alvo.length;k++)selected.add(alvo[k]);}
  syncSelection();
  if(label)toast(label+' \u00b7 '+selected.size+' lote'+(selected.size===1?'':'s')+' na selecao'
    +(mode==='sub'?' (subtraiu '+alvo.length+')':''));
  return{aplicados:alvo.length,total:selected.size,mode:mode||'set'};
}

/* ------------------------------------------------------------------ laco */
// A caixa retangular nao serve para uma quadra torta ou para uma fileira que
// contorna a rua; o laco pega o desenho do proprio loteamento.
var selLasso={pts:[],mode:'set',live:false,drag:false};
function selLassoPoint(e){return c2s(e.clientX,e.clientY);}
function selLassoPush(p){
  var last=selLasso.pts.length?selLasso.pts[selLasso.pts.length-1]:null;
  // Um ponto por pixel de tela viraria um poligono de milhares de vertices: o
  // teste ponto-em-poligono roda 1.509 vezes, entao o contorno e ralo de
  // proposito.
  if(last&&Math.hypot(p.x-last.x,p.y-last.y)<selPx(4))return false;
  selLasso.pts.push({x:p.x,y:p.y});
  return true;
}
function selLassoIndices(ring){
  var t0=performance.now(),box=selBox(ring),out=[],i,c;
  if(!box||ring.length<3)return out;
  // cachedCenter guarda o centro em coordenadas locais; lotCenter releria a
  // string de pontos dos 1.509 lotes a cada laco.
  for(i=0;i<L.length;i++){
    c=fromLocal(cachedCenter(i));
    if(c.x<box.x0||c.x>box.x1||c.y<box.y0||c.y>box.y1)continue;
    if(selPointInRing(c,ring))out.push(i);
  }
  selStats.lassoMs=performance.now()-t0;selStats.lassoPts=ring.length;selStats.queryHits=out.length;
  return out;
}
function selLassoFinish(){
  var ring=selLasso.pts.slice(),mode=selLasso.mode;
  selLasso.pts=[];selLasso.live=false;selLasso.drag=false;
  if(ring.length<3){selDraw();return null;}
  var hits=selLassoIndices(ring);
  selDraw();
  selApply(hits,mode,'Laco: '+hits.length+' lote'+(hits.length===1?'':'s'));
  return{indices:hits,mode:mode,ms:selStats.lassoMs,pontos:ring.length};
}
registerTool('lasso',{
  button:'edlasso',cursor:'draw',
  status:function(){return 'Laco: arraste contornando os lotes (Shift soma, Alt subtrai)';},
  enter:function(){selLasso.pts=[];selLasso.live=false;selLasso.drag=false;selSync();},
  exit:function(){selLasso.pts=[];selLasso.live=false;selLasso.drag=false;selDraw();},
  down:function(e){
    if(ptrs.size>1||(e.button!=null&&e.button!==0))return false;
    selLasso.mode=selModeOf(e,'set');
    selLasso.pts=[];selLasso.live=true;selLasso.drag=true;
    selLassoPush(selLassoPoint(e));
    selDraw();
    return true;
  },
  move:function(e){
    if(!selLasso.drag)return false;
    if(selLassoPush(selLassoPoint(e)))selDraw();
    return true;
  },
  up:function(){
    if(!selLasso.drag)return false;
    selLassoFinish();
    return true;
  },
  click:function(){return true;},
  key:function(e){
    if(e.key==='Escape'&&(selLasso.live||selLasso.pts.length)){
      e.preventDefault();selLasso.pts=[];selLasso.live=false;selLasso.drag=false;selDraw();
      toast('Laco cancelado');return true;}
    return false;
  }
});

/* ------------------------------------------------------ selecao por criterio */
// Padrao de nome: coringa (* e ?) por padrao, /regex/ para quem sabe o que
// quer, e trecho solto quando nao tem coringa nenhum.
function selPatternRe(text){
  var raw=String(text==null?'':text).trim();
  if(!raw)return null;
  if(raw.length>2&&raw.charAt(0)==='/'&&raw.lastIndexOf('/')>0){
    var fim=raw.lastIndexOf('/'),corpo=raw.slice(1,fim),flags=raw.slice(fim+1).replace(/[^gimsuy]/g,'');
    if(flags.indexOf('i')<0)flags+='i';
    try{return new RegExp(corpo,flags);}catch(err){return null;}
  }
  var escapado=raw.replace(/[.+^${}()|[\]\\]/g,'\\$&').replace(/\*/g,'[\\s\\S]*').replace(/\?/g,'[\\s\\S]');
  try{
    if(raw.indexOf('*')<0&&raw.indexOf('?')<0)return new RegExp(escapado,'i');
    return new RegExp('^'+escapado+'$','i');
  }catch(err){return null;}
}
function selQuery(spec){
  var o=spec||{},t0=performance.now(),out=[],i,lot,re=o.nome?selPatternRe(o.nome):null;
  var usaM2=selScale().ok&&o.unidade!=='px',min=o.areaMin,max=o.areaMax;
  var quadra=o.quadra==null||o.quadra===''?null:String(o.quadra).toLowerCase();
  var status=o.status==null||o.status===''?null:+o.status;
  selEnsure();
  for(i=0;i<L.length;i++){
    lot=L[i];if(!lot)continue;
    if(status!=null&&lot.s!==status)continue;
    if(quadra!=null&&String(lot.quadra||'').toLowerCase()!==quadra)continue;
    if(re&&!re.test(String(lot.nome||'')))continue;
    if(min!=null||max!=null){
      var v=usaM2?selCache.m2[i]:selCache.px[i];
      if(!isFinite(v))continue;
      if(min!=null&&v<min)continue;
      if(max!=null&&v>max)continue;
    }
    out.push(i);
  }
  selStats.queryMs=performance.now()-t0;selStats.queryHits=out.length;
  return out;
}
function selRunQuery(spec,mode){
  var hits=selQuery(spec);
  if(!hits.length){toast('Nenhum lote atende ao criterio.',true);selSync();return{indices:[],total:selected.size};}
  var out=selApply(hits,mode||'set','Criterio: '+hits.length+' lote'+(hits.length===1?'':'s'));
  out.indices=hits;
  return out;
}
function selPanelSpec(){
  var min=selNum(selValue('edselAreaMin'),null),max=selNum(selValue('edselAreaMax'),null);
  return{status:selValue('edselStatus'),quadra:selValue('edselQuadraSel'),nome:selValue('edselName'),
         areaMin:min==null?null:min,areaMax:max==null?null:max,unidade:selScale().ok?'m2':'px'};
}

/* --------------------------------------------------------- semelhantes */
// "Este lote e os parecidos com ele": mesma quadra, mesmo status ou area
// vizinha. E o gesto que resolve a quadra inteira depois de um ajuste.
function selCurrent(){var i=firstSelected();return i!=null&&L[i]?i:null;}
function selSimilar(kind,mode,tolerancia){
  var base=selCurrent();
  if(base==null){toast('Selecione um lote para achar os semelhantes.',true);return null;}
  var lot=L[base],hits=[],i;
  if(kind==='quadra'){
    if(!String(lot.quadra||'').trim()){toast('O lote atual nao tem quadra preenchida.',true);return null;}
    hits=selQuery({quadra:lot.quadra});
  }else if(kind==='status'){
    hits=selQuery({status:lot.s});
  }else{
    var tol=tolerancia==null?selNum(selValue('edselTol'),5):tolerancia;
    tol=Math.max(0,Math.min(100,tol))/100;
    var alvo=selScale().ok?selLotM2(base):selLotPx(base);
    if(!isFinite(alvo)||alvo<=0){toast('Nao da para medir a area do lote atual.',true);return null;}
    selEnsure();
    var usaM2=selScale().ok;
    for(i=0;i<L.length;i++){
      var v=usaM2?selCache.m2[i]:selCache.px[i];
      if(isFinite(v)&&v>0&&Math.abs(v/alvo-1)<=tol)hits.push(i);
    }
    var out=selApply(hits,mode||'set','Area parecida ('+selFmt(tol*100,1)+'%): '+hits.length+' lote'+(hits.length===1?'':'s'));
    out.indices=hits;out.base=base;
    return out;
  }
  var res=selApply(hits,mode||'set','Semelhantes por '+(kind==='quadra'?'quadra':'status')+': '+hits.length+' lote'+(hits.length===1?'':'s'));
  res.indices=hits;res.base=base;
  return res;
}
function selInvert(){
  var atual=selected,out=[],i;
  for(i=0;i<L.length;i++)if(!atual.has(i))out.push(i);
  var res=selApply(out,'set','Selecao invertida');
  res.indices=out;
  return res;
}
function selQuadraAtual(mode){
  var base=selCurrent();
  if(base==null){toast('Selecione um lote da quadra que voce quer inteira.',true);return null;}
  if(!String(L[base].quadra||'').trim()){toast('O lote atual nao tem quadra preenchida.',true);return null;}
  return selSimilar('quadra',mode);
}

/* ---------------------------------------------------------------- regua */
// O editor so falava em pixels; a planta traz a metragem. Com a escala
// derivada, arrastar a regua responde em metros - e o angulo sai na direcao
// que o operador ve na tela (a camada pode estar girada).
var selRuler={a:null,b:null,drag:false,last:null};
function selSnap(p,e,opts){
  if(!SNAP||typeof SNAP.point!=='function')return p;
  var local=SNAP.point(toLocal(p),e,opts||{});
  return local?fromLocal(local):p;
}
function selMeasure(a,b){
  var dist=Math.hypot(b.x-a.x,b.y-a.y),s=selScale();
  var ang=Math.atan2(-(b.y-a.y),b.x-a.x)*180/Math.PI;
  if(ang<=-180)ang+=360;if(ang>180)ang-=360;
  return{px:dist,m:s.ok?dist/s.pxPerM:NaN,angulo:ang,escala:s.ok};
}
function selRulerText(){
  if(!selRuler.a||!selRuler.b)return 'Regua: arraste de um ponto ao outro';
  var m=selMeasure(selRuler.a,selRuler.b);
  return (m.escala?selFmt(m.m,2)+' m':selFmt(m.px,1)+' px')+' \u00b7 '+selFmt(m.angulo,1)+'\u00b0'
    +(m.escala?' ('+selFmt(m.px,1)+' px)':' (sem escala)');
}
registerTool('ruler',{
  button:'edruler',cursor:'draw',
  status:function(){return 'Regua: arraste para medir \u00b7 '+selRulerText();},
  enter:function(){selRuler.drag=false;selSync();},
  exit:function(){selRuler.drag=false;selDraw();},
  down:function(e){
    if(ptrs.size>1||(e.button!=null&&e.button!==0))return false;
    var p=selSnap(c2s(e.clientX,e.clientY),e,{});
    selRuler.a={x:p.x,y:p.y};selRuler.b=null;selRuler.drag=true;
    selDraw();
    return true;
  },
  move:function(e){
    if(!selRuler.drag)return false;
    var p=selSnap(c2s(e.clientX,e.clientY),e,{anchor:selRuler.a?toLocal(selRuler.a):null});
    selRuler.b={x:p.x,y:p.y};
    selDraw();updateCanvasStatus();selSync();
    return true;
  },
  up:function(){
    if(!selRuler.drag)return false;
    selRuler.drag=false;
    if(selRuler.a&&selRuler.b){selRuler.last=selMeasure(selRuler.a,selRuler.b);toast('Medida: '+selRulerText());}
    selDraw();selSync();
    return true;
  },
  click:function(){return true;},
  key:function(e){
    if(e.key==='Escape'&&(selRuler.a||selRuler.b)){
      e.preventDefault();selRuler.a=null;selRuler.b=null;selRuler.drag=false;selDraw();selSync();return true;}
    return false;
  }
});
function selMeasurePoints(a,b){
  selRuler.a={x:a.x,y:a.y};selRuler.b={x:b.x,y:b.y};selRuler.drag=false;
  selRuler.last=selMeasure(selRuler.a,selRuler.b);
  selDraw();selSync();
  return selRuler.last;
}

/* ------------------------------------------------------------ conferencia */
// O defeito de mapeamento mais comum e o lote que ficou com a forma errada:
// a area calculada foge da impressa. Hoje o operador nao tem como enxergar.
var selCheckOn=false,SEL_CHECK_DRAW=600;
function selCheckList(){selEnsure();return selScale().ok?selCache.off.slice():[];}
function selCheckSet(on,quiet){
  var s=selScale();
  if(on&&!s.ok){toast('Sem metragem impressa suficiente para conferir areas.',true);selCheckOn=false;selSync();return false;}
  selCheckOn=!!on;
  selDraw();selSync();
  if(!quiet)toast(selCheckOn?('Conferencia ligada: '+selCheckList().length+' lote(s) fora de '
    +Math.round(SEL_AREA_TOL*100)+'%'):'Conferencia desligada');
  if(typeof markDirty==='function')markDirty();
  return selCheckOn;
}
function selCheckSelect(mode){
  var lista=selCheckList();
  if(!lista.length){toast(selScale().ok?'Nenhum lote diverge mais que '+Math.round(SEL_AREA_TOL*100)+'%.':'Sem escala: nao da para conferir areas.',!selScale().ok);return null;}
  var out=selApply(lista,mode||'set','Divergentes: '+lista.length+' lote'+(lista.length===1?'':'s'));
  out.indices=lista;
  return out;
}
function selCheckRatio(i){
  selEnsure();
  var px=selCache.px[i],printed=selCache.printed[i];
  if(!(px>0)||!(printed>0)||!(selCache.ratio>0))return NaN;
  return (px/printed)/selCache.ratio-1;
}

/* -------------------------------------------------------- renomear em lote */
// Depois de dividir ou repetir uma fileira, renomear um a um e inviavel.
function selNameFor(pattern,value,pad,lot){
  var texto=String(Math.abs(Math.round(value))),sinal=value<0?'-':'',casas=Math.max(0,Math.min(8,pad||0));
  while(texto.length<casas)texto='0'+texto;
  return String(pattern==null?'':pattern)
    .replace(/\{n\}/g,sinal+texto)
    .replace(/\{q\}/g,lot&&lot.quadra?String(lot.quadra):'')
    .replace(/\{s\}/g,lot?NAMES[lot.s]:'');
}
function selRowSort(row){return row.slice().sort(function(a,b){return a.x-b.x||a.y-b.y;});}
// Ordem de leitura: esquerda->direita, cima->baixo. Fileira nenhuma esta
// perfeitamente alinhada, entao a linha e uma faixa de tolerancia, nao um y
// exato. Funcao pura para dar para testar fora do navegador.
function selOrderScreen(points,band){
  var b=band>0?band:1,lista=points.slice().sort(function(a,c){return a.y-c.y||a.x-c.x;});
  var out=[],row=[],base=null,k;
  for(k=0;k<lista.length;k++){
    if(base===null){base=lista[k].y;row.push(lista[k]);continue;}
    if(lista[k].y-base<=b)row.push(lista[k]);
    else{out=out.concat(selRowSort(row));row=[lista[k]];base=lista[k].y;}
  }
  if(row.length)out=out.concat(selRowSort(row));
  return out.map(function(p){return p.i;});
}
function selSelectionOrder(order){
  var lista=Array.from(selected).filter(function(i){return !!L[i];});
  if(order!=='screen')return lista;
  var pontos=[],alturas=[],k,i,ring,box,c;
  for(k=0;k<lista.length;k++){
    i=lista[k];ring=selRing(i);box=selBox(ring);
    c=fromLocal(cachedCenter(i));
    pontos.push({i:i,x:c.x,y:c.y});
    if(box)alturas.push(box.h);
  }
  var banda=alturas.length?selMedian(alturas)*.7:1;
  return selOrderScreen(pontos,banda>0?banda:1);
}
function selRenamePlan(opts){
  var o=opts||{};
  var order=o.order||selValue('edselOrder')||'screen';
  var idx=o.indices||selSelectionOrder(order);
  var pattern=o.pattern!=null?o.pattern:selValue('edselPattern');
  var start=Math.round(selNum(o.start!=null?o.start:selValue('edselStart'),1));
  var pad=Math.round(selNum(o.pad!=null?o.pad:selValue('edselPad'),0));
  var items=[],vistos={},repetidos=[],conflitos=[],meus={},k,i,para,chave;
  for(k=0;k<idx.length;k++)meus[idx[k]]=1;
  var existentes={};
  for(i=0;i<L.length;i++)if(!meus[i])existentes[String(L[i].nome||'').toLowerCase()]=i;
  for(k=0;k<idx.length;k++){
    i=idx[k];if(!L[i])continue;
    para=selNameFor(pattern,start+k,pad,L[i]);
    chave=para.toLowerCase();
    items.push({i:i,de:String(L[i].nome||''),para:para,mudou:String(L[i].nome||'')!==para});
    if(existentes[chave]!=null&&conflitos.indexOf(para)<0)conflitos.push(para);
    if(vistos[chave]){if(repetidos.indexOf(para)<0)repetidos.push(para);}
    else vistos[chave]=1;
  }
  return{items:items,conflitos:conflitos,repetidos:repetidos,order:order,start:start,pad:pad,
         pattern:String(pattern==null?'':pattern),
         semContador:String(pattern==null?'':pattern).indexOf('{n}')<0};
}
function selRenameApply(opts){
  var plano=selRenamePlan(opts);
  if(!plano.items.length){toast('Selecione os lotes que vao ser renomeados.',true);return null;}
  var indices=plano.items.map(function(it){return it.i;});
  // Um unico patch: a fileira inteira volta com UM Ctrl+Z.
  var op=beginPatch(indices,['nome']),k;
  for(k=0;k<plano.items.length;k++)L[plano.items[k].i].nome=plano.items[k].para;
  sealPatchOrDrop(op);
  for(k=0;k<indices.length;k++)updateLotStyle(indices[k]);
  scheduleListRender();renderEditor();updateLabelVisibility(true);selSync();
  toast(plano.items.length+' lote'+(plano.items.length===1?'':'s')+' renomeado'+(plano.items.length===1?'':'s')
    +' ('+plano.items[0].para+(plano.items.length>1?' ... '+plano.items[plano.items.length-1].para:'')+')'
    +(plano.conflitos.length?' \u00b7 '+plano.conflitos.length+' nome(s) ja existiam':''));
  return plano;
}

/* --------------------------------------------------------------- overlay */
// Duas camadas: a do laco e da regua vive no espaco do viewBox (as coordenadas
// vem de c2s, iguais as da caixa de selecao do nucleo); a da conferencia vive
// dentro de #lotsrot, porque desenha o contorno dos lotes.
var selMarkLayer=el('g');
selMarkLayer.setAttribute('id','edselmark');
selMarkLayer.setAttribute('pointer-events','none');
lotsrot.appendChild(selMarkLayer);
var selViewLayer=el('g');
selViewLayer.setAttribute('id','edselview');
selViewLayer.setAttribute('pointer-events','none');
svg.appendChild(selViewLayer);
function selShape(layer,tag,attrs){var node=el(tag);for(var key in attrs)node.setAttribute(key,attrs[key]);layer.appendChild(node);return node;}
function selDraw(){redrawOverlays();}
function selDrawLasso(){
  if(!selLasso.pts.length)return;
  var u=selUnit(),d=selLasso.pts.map(function(p,k){return (k?'L':'M')+p.x.toFixed(1)+' '+p.y.toFixed(1);}).join('');
  var cor=selLasso.mode==='sub'?'#e0613b':(selLasso.mode==='add'?'#12b8ff':'#36d889');
  selShape(selViewLayer,'path',{d:d+(selLasso.pts.length>2?'Z':''),fill:cor,'fill-opacity':.12,stroke:cor,
    'stroke-width':1.4,'stroke-dasharray':(u*3)+' '+(u*2),'vector-effect':'non-scaling-stroke','stroke-linejoin':'round'});
}
function selDrawRuler(){
  if(!selRuler.a)return;
  var u=selUnit(),a=selRuler.a,b=selRuler.b||selRuler.a;
  selShape(selViewLayer,'line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,stroke:'#ffb020','stroke-width':1.6,
    'vector-effect':'non-scaling-stroke','stroke-linecap':'round'});
  [a,b].forEach(function(p){selShape(selViewLayer,'circle',{cx:p.x,cy:p.y,r:u*1.4,fill:'#ffb020',stroke:'#1b1206',
    'stroke-width':1,'vector-effect':'non-scaling-stroke'});});
  if(!selRuler.b)return;
  var texto=selShape(selViewLayer,'text',{x:((a.x+b.x)/2).toFixed(1),y:((a.y+b.y)/2-u*2).toFixed(1),
    'font-size':(u*3.4).toFixed(2),'text-anchor':'middle',fill:'#3a2a05',stroke:'#ffd479','stroke-width':(u*.9).toFixed(2),
    'paint-order':'stroke','font-weight':'700'});
  texto.textContent=selRulerText();
}
function selDrawCheck(){
  if(!selCheckOn)return;
  var lista=selCheckList();
  if(!lista.length)return;
  var u=selUnit(),feitos=0,k,i,ring,pontos,c;
  var pad=vb.w*.06,x0=vb.x-pad,y0=vb.y-pad,x1=vb.x+vb.w+pad,y1=vb.y+vb.h+pad;
  for(k=0;k<lista.length&&feitos<SEL_CHECK_DRAW;k++){
    i=lista[k];if(!L[i])continue;
    c=fromLocal(cachedCenter(i));
    if(c.x<x0||c.x>x1||c.y<y0||c.y>y1)continue;
    ring=selRing(i);if(ring.length<3)continue;
    pontos=ring.map(function(p){return p.x.toFixed(1)+','+p.y.toFixed(1);}).join(' ');
    selShape(selMarkLayer,'polygon',{points:pontos,fill:'#e0613b','fill-opacity':.18,stroke:'#ff7a45',
      'stroke-width':1.6,'stroke-dasharray':(u*2.4)+' '+(u*1.6),'vector-effect':'non-scaling-stroke'});
    feitos++;
  }
}
onOverlayRedraw(function(){
  while(selMarkLayer.firstChild)selMarkLayer.removeChild(selMarkLayer.firstChild);
  while(selViewLayer.firstChild)selViewLayer.removeChild(selViewLayer.firstChild);
  if(!editMode)return;
  selDrawCheck();
  selDrawLasso();
  selDrawRuler();
});

/* ------------------------------------------------------------------ painel */
var SEL_STYLE=[
  '#edSelectPanel{position:absolute;z-index:7;left:636px;top:64px;width:300px;max-height:calc(100vh - 152px);overflow:auto;padding:0;border:1px solid #2b3842;border-radius:9px;background:#101820;box-shadow:0 22px 60px rgba(3,8,12,.3);font-size:12px}',
  '#app.side-closed #edSelectPanel{left:324px}',
  '#edSelectPanel .edsel-head{position:sticky;top:0;z-index:1;display:grid;grid-template-columns:1fr auto;align-items:center;gap:8px;padding:10px 13px 9px;border-bottom:1px solid #26313a;background:#101820}',
  '#edSelectPanel .edsel-head strong{display:block;font-size:13px;font-weight:650}',
  '#edSelectPanel .edsel-sum{display:block;margin-top:2px;color:#9facb4;font-size:10.5px;line-height:1.35}',
  '#edSelectPanel .edsel-sum.edsel-live{color:#dff8ea}',
  '#edSelectPanel.edsel-off .edsel-body{display:none}',
  '#edSelectPanel .edsel-body{padding-bottom:12px}',
  '#edSelectPanel .inspectorSection{margin:12px 0 7px}',
  '#edSelectPanel .edsel-row{display:grid;gap:6px;padding:0 13px;margin-bottom:8px}',
  '#edSelectPanel .edsel-c1{grid-template-columns:1fr}',
  '#edSelectPanel .edsel-c2{grid-template-columns:repeat(2,1fr)}',
  '#edSelectPanel .edsel-c3{grid-template-columns:repeat(3,1fr)}',
  '#edSelectPanel button{min-height:30px;padding:0 7px;border:1px solid #2c3943;border-radius:7px;background:#161f27;color:#dbe5e7;font-size:11.5px;cursor:pointer}',
  '#edSelectPanel button:hover:not(:disabled){background:#1f2a33;border-color:#3d4c57}',
  '#edSelectPanel button:disabled{opacity:.38;cursor:not-allowed}',
  '#edSelectPanel button.on{background:#36d889;border-color:#36d889;color:#052419;font-weight:650}',
  '#edSelectPanel .edsel-ico{font-size:15px;line-height:1}',
  '#edSelectPanel .formgrid{padding:0 13px 2px}',
  '#edSelectPanel .field input,#edSelectPanel .field select{width:100%}',
  '#edSelectPanel .field.full{grid-column:1/-1}',
  '#edSelectPanel .edsel-note{padding:0 13px;margin-bottom:9px;color:#8fa0a9;font-size:10.5px;line-height:1.4}',
  '#edSelectPanel .edsel-note.edsel-warn{color:#f0b49b}',
  '#edSelectPanel .edsel-prev{margin:0 13px 9px;padding:7px 8px;border:1px solid #26313a;border-radius:7px;background:#0b1116;color:#b7c4cb;font:10.5px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;max-height:132px;overflow:auto}',
  '#edSelectPanel .edsel-prev b{color:#dff8ea;font-weight:650}',
  '#edSelectPanel .edsel-prev i{color:#f0b49b;font-style:normal}',
  '@media(max-width:1320px){#edSelectPanel{left:auto;right:16px;top:auto;bottom:56px;max-height:46vh}#app.side-closed #edSelectPanel{left:auto}}',
  '@media(max-width:1180px){#edSelectPanel{left:16px;right:auto;bottom:56px;max-height:44vh}#app.side-closed #edSelectPanel{left:16px}}',
  '@media(max-width:760px){#edSelectPanel{left:8px;right:8px;width:auto;top:56px;bottom:auto;max-height:40vh}#app.side-closed #edSelectPanel{left:8px}}'
].join('\n');
function selStyle(){
  if(document.getElementById('edsel-style'))return;
  var node=document.createElement('style');
  node.id='edsel-style';node.textContent=SEL_STYLE;
  document.head.appendChild(node);
}
function selBtn(id,label,text,extra){
  return '<button type="button" id="'+id+'" title="'+label+'" aria-label="'+label+'"'+(extra||'')+'>'+text+'</button>';
}
function selField(id,label,value,extra){
  return '<label class="field'+(extra||'')+'">'+label+'<input id="'+id+'" type="text" inputmode="decimal" autocomplete="off" value="'+value+'"></label>';
}
var selPanel=null;
function selBuildPanel(){
  selStyle();
  selPanel=document.getElementById('edSelectPanel');
  if(!selPanel){
    selPanel=document.createElement('section');
    selPanel.id='edSelectPanel';
    selPanel.className='panel';
    selPanel.setAttribute('role','group');
    selPanel.setAttribute('aria-label','Selecionar, medir e renomear lotes');
    (document.getElementById('app')||document.body).appendChild(selPanel);
  }
  selPanel.hidden=true;
  selPanel.classList.add('edsel-off');
  selPanel.innerHTML=
    '<div class="edsel-head"><span><strong>Selecionar</strong>'
    +'<span class="edsel-sum" id="edselSummary" role="status" aria-live="polite">Nenhum lote selecionado</span></span>'
    +selBtn('edselFold','Abrir ou recolher o painel de selecao (F)','<span class="edsel-ico">&#9660;</span>',' aria-expanded="false"')
    +'</div><div class="edsel-body">'
    +'<div class="inspectorSection">Selecao</div>'
    +'<div class="edsel-row edsel-c3">'
    +selBtn('edlasso','Laco livre: contorne os lotes no mapa (L)','<span class="edsel-ico">&#10227;</span> Laco')
    +selBtn('edselInvert','Inverter a selecao (I)','Inverter')
    +selBtn('edselQuadra','Selecionar toda a quadra do lote atual (Q)','Quadra')
    +'</div>'
    +'<div class="edsel-row edsel-c3">'
    +selBtn('edselSimQuadra','Selecionar os lotes da mesma quadra do lote atual','= Quadra')
    +selBtn('edselSimStatus','Selecionar os lotes com o mesmo status do lote atual','= Status')
    +selBtn('edselSimArea','Selecionar os lotes com area parecida com a do lote atual','~ Area')
    +'</div>'
    +'<div class="formgrid">'
    +selField('edselTol','Tolerancia de area (%)','5')
    +'<label class="field">Modo<select id="edselMode">'
    +'<option value="set">Substituir</option><option value="add">Somar (Shift)</option>'
    +'<option value="sub">Subtrair (Alt)</option></select></label>'
    +'</div>'
    +'<p class="edsel-note">Shift no clique (ou no laco) soma; Alt subtrai. Vale tambem para a caixa retangular.</p>'
    +'<div class="inspectorSection">Por criterio</div>'
    +'<div class="formgrid">'
    +'<label class="field">Status<select id="edselStatus"><option value="">Qualquer</option>'
    +'<option value="0">Disponivel</option><option value="1">Vendido</option><option value="2">Reservado</option></select></label>'
    +'<label class="field">Quadra<select id="edselQuadraSel"><option value="">Qualquer</option></select></label>'
    +selField('edselName','Nome (use * e ?)','','full')
    +selField('edselAreaMin','Area minima','')
    +selField('edselAreaMax','Area maxima','')
    +'</div>'
    +'<div class="edsel-row edsel-c1">'+selBtn('edselRun','Selecionar os lotes que atendem ao criterio','Selecionar por criterio')+'</div>'
    +'<p class="edsel-note" id="edselCriteriaWhy"></p>'
    +'<div class="inspectorSection">Medida</div>'
    +'<p class="edsel-note" id="edselScaleWhy"></p>'
    +'<div class="edsel-row edsel-c3">'
    +selBtn('edruler','Regua: arraste no mapa para medir distancia e angulo (K)','<span class="edsel-ico">&#8596;</span> Regua')
    +selBtn('edselCheck','Marcar os lotes cuja area calculada diverge da impressa (W)','Conferir')
    +selBtn('edselCheckPick','Selecionar os lotes divergentes','Divergentes')
    +'</div>'
    +'<p class="edsel-note" id="edselCheckWhy"></p>'
    +'<div class="inspectorSection">Renomear em lote</div>'
    +'<div class="formgrid">'
    +selField('edselPattern','Padrao: {n} conta, {q} e a quadra do lote','{q}-L{n}','full')
    +selField('edselStart','Comeca em','1')
    +selField('edselPad','Zeros a esquerda','3')
    +'<label class="field full">Ordem da numeracao<select id="edselOrder">'
    +'<option value="screen">Posicao na tela (esquerda para direita)</option>'
    +'<option value="sel">Ordem de selecao</option></select></label>'
    +'</div>'
    +'<div class="edsel-prev" id="edselPreview" role="status" aria-live="polite">Selecione lotes para ver a previa.</div>'
    +'<p class="edsel-note" id="edselRenameWhy"></p>'
    +'<div class="edsel-row edsel-c1">'+selBtn('edselRename','Aplicar os nomes da previa a selecao','Renomear selecao')+'</div>'
    +'</div>';
  selWire();
  selSync();
}
function selOn(id,event,fn){var node=document.getElementById(id);if(node)node.addEventListener(event,fn);}
function selValue(id){var node=document.getElementById(id);return node?node.value:'';}
function selSet(id,value){var node=document.getElementById(id);if(node&&document.activeElement!==node)node.value=value;}
function selDisable(id,off){var node=document.getElementById(id);if(node)node.disabled=!!off;}
function selText(id,text,warn){var node=document.getElementById(id);if(!node)return;
  node.textContent=text||'';node.classList.toggle('edsel-warn',!!warn);}
function selWire(){
  selOn('edselFold','click',function(){
    var off=selPanel.classList.toggle('edsel-off');
    this.setAttribute('aria-expanded',String(!off));
    this.innerHTML='<span class="edsel-ico">'+(off?'&#9660;':'&#9650;')+'</span>';
    if(!off)selSync();
  });
  selOn('edlasso','click',function(){setTool(tool==='lasso'?'select':'lasso');});
  selOn('edruler','click',function(){setTool(tool==='ruler'?'select':'ruler');});
  selOn('edselInvert','click',function(){selInvert();});
  selOn('edselQuadra','click',function(e){selQuadraAtual(selModeOf(e));});
  selOn('edselSimQuadra','click',function(e){selSimilar('quadra',selModeOf(e));});
  selOn('edselSimStatus','click',function(e){selSimilar('status',selModeOf(e));});
  selOn('edselSimArea','click',function(e){selSimilar('area',selModeOf(e));});
  selOn('edselRun','click',function(e){selRunQuery(selPanelSpec(),selModeOf(e));});
  ['edselStatus','edselQuadraSel','edselName','edselAreaMin','edselAreaMax'].forEach(function(id){
    selOn(id,'input',selCriteriaNote);selOn(id,'change',selCriteriaNote);
  });
  selOn('edselCheck','click',function(){selCheckSet(!selCheckOn);});
  selOn('edselCheckPick','click',function(e){selCheckSelect(selModeOf(e));});
  ['edselPattern','edselStart','edselPad'].forEach(function(id){selOn(id,'input',selRenameNote);});
  selOn('edselOrder','change',selRenameNote);
  selOn('edselRename','click',function(){selRenameApply();});
}
// Lista de quadras: so muda quando o mapa muda, entao nao entra no sync de
// selecao (com 1.500 lotes seria uma varredura por clique).
function selQuadraOptions(){
  var node=document.getElementById('edselQuadraSel');
  if(!node)return;
  var vistos={},nomes=[],i,q;
  for(i=0;i<L.length;i++){q=String(L[i].quadra||'').trim();if(q&&!vistos[q]){vistos[q]=1;nomes.push(q);}}
  nomes.sort(function(a,b){return a.localeCompare(b,'pt-BR',{numeric:true});});
  var antes=node.value,html='<option value="">Qualquer</option>',k;
  for(k=0;k<nomes.length;k++)html+='<option value="'+esc(nomes[k])+'">'+esc(nomes[k])+'</option>';
  node.innerHTML=html;
  node.value=antes;
  if(node.value!==antes)node.value='';
}
function selCriteriaNote(){
  var spec=selPanelSpec(),hits=selQuery(spec).length,unidade=selUnitName();
  var partes=[];
  if(spec.status!=='')partes.push(NAMES[+spec.status]);
  if(spec.quadra)partes.push('quadra '+spec.quadra);
  if(spec.nome)partes.push('nome '+spec.nome);
  if(spec.areaMin!=null||spec.areaMax!=null)
    partes.push('area '+(spec.areaMin==null?'ate':'de '+selFmt(spec.areaMin,2))
      +(spec.areaMax==null?' para cima':(spec.areaMin==null?' '+selFmt(spec.areaMax,2):' a '+selFmt(spec.areaMax,2)))+' '+unidade);
  selText('edselCriteriaWhy',(partes.length?partes.join(' \u00b7 ')+': ':'Sem filtro: ')+selFmt(hits,0)+' lote'
    +(hits===1?'':'s')+' \u00b7 area em '+unidade+' \u00b7 busca em '+selFmt(selStats.queryMs,1)+' ms',!hits);
}
function selRenameNote(){
  var box=document.getElementById('edselPreview');
  if(!box)return;
  if(!selected.size){
    box.innerHTML='Selecione lotes para ver a previa.';
    selText('edselRenameWhy','Nada selecionado: renomear em lote trabalha sobre a selecao.',true);
    selDisable('edselRename',true);
    return;
  }
  var plano=selRenamePlan(),linhas=[],max=Math.min(plano.items.length,12),k,it;
  for(k=0;k<max;k++){
    it=plano.items[k];
    linhas.push(esc(it.de||'(sem nome)')+' &#8594; <b>'+esc(it.para)+'</b>'
      +(plano.conflitos.indexOf(it.para)>=0?' <i>ja existe</i>':'')
      +(plano.repetidos.indexOf(it.para)>=0?' <i>repetido</i>':''));
  }
  if(plano.items.length>max)linhas.push('... mais '+(plano.items.length-max)+' lote(s)');
  box.innerHTML=linhas.join('<br>');
  var avisos=[];
  if(plano.semContador)avisos.push('o padrao nao tem {n}: todos os lotes ficariam com o mesmo nome');
  if(plano.conflitos.length)avisos.push(plano.conflitos.length+' nome(s) ja existem no mapa ('+esc(plano.conflitos.slice(0,3).join(', '))+')');
  if(plano.repetidos.length)avisos.push(plano.repetidos.length+' nome(s) repetidos dentro da propria selecao');
  selText('edselRenameWhy',avisos.length?'Atencao: '+avisos.join(' \u00b7 ')+'.'
    :plano.items.length+' lote(s) na ordem '+(plano.order==='screen'?'da tela':'de selecao')
      +' \u00b7 um unico Ctrl+Z desfaz tudo.',avisos.length>0);
  selDisable('edselRename',false);
}
function selSummaryText(){
  var idx=Array.from(selected),soma=selSum(idx),s=selScale();
  if(!idx.length)return 'Nenhum lote selecionado \u00b7 '+selFmt(L.length,0)+' no mapa';
  var texto=selFmt(soma.count,0)+' lote'+(soma.count===1?'':'s')+' \u00b7 ';
  texto+=s.ok?selFmtM2(soma.m2):selFmtPx(soma.px);
  if(s.ok)texto+=' \u00b7 '+selFmtPx(soma.px);
  if(s.ok&&soma.comArea)texto+=' \u00b7 impresso '+selFmtM2(soma.impresso)+' ('+selFmt(soma.comArea,0)+')';
  return texto;
}
function selSync(){
  if(!selPanel)return;
  var temSel=selected.size>0,s=selScale();
  var resumo=document.getElementById('edselSummary');
  if(resumo){resumo.textContent=selSummaryText();resumo.classList.toggle('edsel-live',temSel);}
  // Corpo recolhido: o resumo continua vivo, mas a previa de nomes e a contagem
  // do criterio (duas varreduras nos 1.509 lotes) nao rodam por nada.
  if(selPanel.hidden||selPanel.classList.contains('edsel-off'))return;
  ['edselSimQuadra','edselSimStatus','edselSimArea','edselQuadra'].forEach(function(id){selDisable(id,!temSel);});
  selDisable('edselInvert',false);
  selDisable('edselCheck',!s.ok);
  selDisable('edselCheckPick',!s.ok||!selCheckList().length);
  var botaoCheck=document.getElementById('edselCheck');
  if(botaoCheck){botaoCheck.classList.toggle('on',selCheckOn);botaoCheck.setAttribute('aria-pressed',String(selCheckOn));}
  selText('edselScaleWhy',selScaleNote(),!s.ok);
  var divergentes=selCheckList().length;
  selText('edselCheckWhy',
    s.ok?(divergentes?divergentes+' lote(s) fora de '+Math.round(SEL_AREA_TOL*100)+'% da metragem impressa'
        +(selCheckOn?' - marcados no mapa':' - ligue Conferir para ver no mapa')
      :'Todos os lotes com metragem batem dentro de '+Math.round(SEL_AREA_TOL*100)+'%.')
    :'Conferencia de area indisponivel sem escala. '+(selRuler.a&&selRuler.b?'Regua: '+selRulerText():''),
    s.ok&&divergentes>0);
  if(s.ok&&selRuler.a&&selRuler.b)selText('edselCheckWhy',(divergentes?divergentes+' lote(s) divergentes \u00b7 ':'')+'Regua: '+selRulerText(),divergentes>0);
  selCriteriaNote();
  selRenameNote();
}
function selShow(on){
  if(!selPanel)return;
  selPanel.hidden=!on;
  if(on){selQuadraOptions();selSync();}
}
function selFocus(){
  if(!editMode){toast('Ative a edicao para usar a selecao avancada.',true);return;}
  if(selPanel.hidden)selShow(true);
  selPanel.classList.remove('edsel-off');
  var fold=document.getElementById('edselFold');
  if(fold){fold.setAttribute('aria-expanded','true');fold.innerHTML='<span class="edsel-ico">&#9650;</span>';}
  selSync();
  var node=document.getElementById('edselName');
  if(node)node.focus();
}

/* ------------------------------------------- painel acompanha o editor */
selBuildPanel();
var selCoreSetEdit=setEdit;
setEdit=function(on){var out=selCoreSetEdit(on);selShow(!!on);return out;};
var selCoreSync=syncSelection;
syncSelection=function(){var out=selCoreSync();selSync();return out;};
var selCoreRedraw=redraw;
redraw=function(){selInvalidate();var out=selCoreRedraw();selQuadraOptions();selSync();return out;};
// Arrastar vertice muda a area sem passar por redraw: o cache precisa saber.
var selCoreSetLotPoints=setLotPoints;
setLotPoints=function(i,points){var out=selCoreSetLotPoints(i,points);selTouch(i);return out;};
// markDirty e chamado depois de toda alteracao (inclusive texto de area digitado
// no inspetor), entao e o gancho honesto para invalidar a escala.
var selCoreMarkDirty=markDirty;
markDirty=function(){selInvalidate();return selCoreMarkDirty();};

/* ------------------------------------- Alt subtrai tambem na caixa do nucleo */
// finishDragBox so recebe o Shift; o Alt vem do ultimo evento de ponteiro,
// capturado no document antes de qualquer handler do mapa.
var selMods={shift:false,alt:false};
function selReadMods(e){selMods.shift=!!e.shiftKey;selMods.alt=!!e.altKey;}
document.addEventListener('pointerdown',selReadMods,true);
document.addEventListener('pointerup',selReadMods,true);
function selBoxIndices(rect){
  var out=[],x2=rect.x+rect.w,y2=rect.y+rect.h,i,c;
  for(i=0;i<L.length;i++){c=lotCenter(i);
    if(c.x>=rect.x&&c.x<=x2&&c.y>=rect.y&&c.y<=y2)out.push(i);}
  return out;
}
var selCoreFinishDragBox=finishDragBox;
finishDragBox=function(add){
  if(dragRect&&selMods.alt){
    var lista=selBoxIndices(dragRect);
    clearDragBox();
    selApply(lista,'sub','Caixa: -'+lista.length+' lote'+(lista.length===1?'':'s'));
    return;
  }
  return selCoreFinishDragBox(add||selMods.shift);
};

/* --------------------------------------------------------------- rascunho */
// O que o operador ajustou aqui volta com o mapa; o nucleo continua dono do
// rascunho, este modulo so pendura um objeto proprio.
var selCoreDraftBody=draftBody;
draftBody=function(){
  var data=JSON.parse(selCoreDraftBody());
  data.select={check:selCheckOn,pattern:selValue('edselPattern'),start:selValue('edselStart'),
               pad:selValue('edselPad'),order:selValue('edselOrder'),mode:selValue('edselMode'),
               tol:selValue('edselTol')};
  return JSON.stringify(data);
};
var selCoreDraftApply=applyDraft;
applyDraft=function(data){
  var out=selCoreDraftApply(data);
  if(data&&data.select){
    var d=data.select;
    [['edselPattern',d.pattern],['edselStart',d.start],['edselPad',d.pad],
     ['edselOrder',d.order],['edselMode',d.mode],['edselTol',d.tol]].forEach(function(par){
      if(par[1]!=null&&par[1]!=='')selSet(par[0],par[1]);
    });
    selInvalidate();
    selCheckSet(!!d.check,true);
    selQuadraOptions();selSync();
  }
  return out;
};

/* ----------------------------------------------------------------- teclas */
// Livres antes deste modulo: F I K L N Q W. O nucleo usa V M P D G A B C U S
// 1 2 3, o vetorial B C U S e o transformar T R E H e Alt+1..8.
document.addEventListener('keydown',function(e){
  if(!editMode)return;
  if(e.ctrlKey||e.metaKey||e.altKey)return;
  if(/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)||!!(e.target&&e.target.isContentEditable))return;
  var key=e.key.toLowerCase();
  if(key==='l'){e.preventDefault();setTool(tool==='lasso'?'select':'lasso');}
  if(key==='k'){e.preventDefault();setTool(tool==='ruler'?'select':'ruler');}
  if(key==='f'){e.preventDefault();if(selPanel&&!selPanel.hidden&&!selPanel.classList.contains('edsel-off'))selPanel.classList.add('edsel-off');else selFocus();}
  if(key==='i'){e.preventDefault();selInvert();}
  if(key==='q'){e.preventDefault();selQuadraAtual();}
  if(key==='w'){e.preventDefault();selCheckSet(!selCheckOn);}
  if(key==='n'){e.preventDefault();selFocus();var node=document.getElementById('edselPattern');if(node)node.focus();}
});

/* --------------------------------------------------------------------- api */
// Superficie publica para a barra de ferramentas, para os outros modulos do
// editor e para os testes de navegador.
window.nexoloteSelect={
  lasso:function(){setTool('lasso');},
  lassoSelect:function(points,mode){
    var ring=(points||[]).map(function(p){return{x:+p.x,y:+p.y};});
    if(ring.length<3)return null;
    var hits=selLassoIndices(ring);
    var out=selApply(hits,mode||'set','Laco: '+hits.length+' lote'+(hits.length===1?'':'s'));
    out.indices=hits;out.ms=selStats.lassoMs;
    return out;
  },
  query:selQuery,select:selRunQuery,similar:selSimilar,invert:selInvert,quadra:selQuadraAtual,
  apply:selApply,spec:selPanelSpec,
  ruler:function(){setTool('ruler');},
  measure:selMeasure,measurePoints:selMeasurePoints,
  rulerState:function(){return{a:selRuler.a,b:selRuler.b,last:selRuler.last,texto:selRulerText()};},
  scale:selScale,scaleNote:selScaleNote,sum:function(list){return selSum(list||Array.from(selected));},
  summary:selSummaryText,areaOf:function(i){return{px:selLotPx(i),m2:selLotM2(i),desvio:selCheckRatio(i)};},
  check:{get:function(){return selCheckOn;},set:selCheckSet,toggle:function(){return selCheckSet(!selCheckOn);},
         list:selCheckList,select:selCheckSelect,ratio:selCheckRatio},
  rename:{plan:selRenamePlan,apply:selRenameApply,order:selSelectionOrder},
  panel:{show:selShow,focus:selFocus,sync:selSync,node:function(){return selPanel;}},
  stats:function(){return{lassoMs:selStats.lassoMs,lassoPts:selStats.lassoPts,queryMs:selStats.queryMs,
    queryHits:selStats.queryHits,scaleMs:selCache.ms,lots:L.length,amostras:selCache.samples};},
  math:{parseArea:selParseArea,ringArea:selRingArea,pointInRing:selPointInRing,orderScreen:selOrderScreen,
        nameFor:selNameFor,pattern:selPatternRe,median:selMedian,box:selBox,ring:selRing,fmt:selFmt}
};
