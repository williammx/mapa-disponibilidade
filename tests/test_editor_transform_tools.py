"""Garantias sobre alinhar/transformar/repetir do editor (templates/editor/editor-transform.js).

O modulo nasce de um problema concreto: numa quadra os lotes sao o mesmo
retangulo repetido ao longo da rua, e quando o mapeamento automatico perde uma
fileira inteira nao da para redesenhar lote a lote. Estes testes travam o que
custa caro em producao:

* a costura precisa continuar entregando um HTML unico com o modulo no MESMO
  bloco de script - fora dele o editor abre sem os comandos;
* toda operacao tem que entrar no historico incremental e sair com UM Ctrl+Z;
  repetir 40 lotes que gastasse 40 passos seria pior que nao existir;
* a nomeacao sequencial detecta o padrao do nome (Q195-L003 -> Q195-L004) em
  vez de presumir formato, senao renomeia errado a quadra inteira;
* o painel e montado por JS, sem tocar em editor.css nem editor.html (outro
  dono), entao o estilo proprio fica preso ao prefixo edtr-;
* as teclas novas nao podem pisar nas que ja existem.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

import pdf_to_map


RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDITOR = os.path.join(RAIZ, "templates", "editor")
CAMINHO = os.path.join(EDITOR, "editor-transform.js")
TRANSFORMA = open(CAMINHO, encoding="utf-8").read()
NUCLEO = open(os.path.join(EDITOR, "editor.js"), encoding="utf-8").read()
CSS = open(os.path.join(EDITOR, "editor.css"), encoding="utf-8").read()
CORPO_HTML = open(os.path.join(EDITOR, "editor.html"), encoding="utf-8").read()
HTML = pdf_to_map.HTML_TEMPLATE


def corpo_da_funcao(fonte, nome):
    """Recorta `function nome(...){...}` equilibrando as chaves."""
    inicio = fonte.index("function %s(" % nome)
    abertura = fonte.index("{", inicio)
    nivel, fim = 0, None
    for pos in range(abertura, len(fonte)):
        if fonte[pos] == "{":
            nivel += 1
        elif fonte[pos] == "}":
            nivel -= 1
            if nivel == 0:
                fim = pos + 1
                break
    assert fim, "funcao %s nao fecha" % nome
    return fonte[inicio:fim]


def no(*funcoes, **kwargs):
    """Roda funcoes puras do modulo no node e devolve o JSON impresso."""
    corpo = kwargs["corpo"]
    extra = kwargs.get("prefixo", "")
    fonte = "\n".join([extra] + [corpo_da_funcao(TRANSFORMA, nome) for nome in funcoes] + [corpo])
    saida = subprocess.run(["node", "-e", fonte], capture_output=True, text=True, timeout=60)
    assert saida.returncode == 0, saida.stderr
    return json.loads(saida.stdout)


# ------------------------------------------------------------------ costura

def test_modulo_existe_e_nao_esta_vazio():
    assert os.path.isfile(CAMINHO), "editor-transform.js sumiu de templates/editor"
    assert os.path.getsize(CAMINHO) > 5000


def test_modulo_entra_sozinho_na_costura_depois_do_nucleo():
    montado = pdf_to_map._editor_scripts()
    assert "window.nexoloteTransform" in montado
    assert montado.index("window.getMapaPayload=currentPayload") < montado.index("window.nexoloteTransform")


def test_modulo_fica_no_mesmo_bloco_de_script_do_editor():
    assert HTML.count("<script>") == 1 and HTML.count("</script>") == 1
    assert "window.nexoloteTransform" in HTML


def test_modulo_nao_precisou_de_css_nem_de_html_de_terceiros():
    """O layout tem outro dono: o painel nasce por JS e o estilo proprio e prefixado."""
    assert "edTransformPanel" not in CORPO_HTML and "edTransformPanel" not in CSS
    assert "edtr-" not in CSS
    assert "document.createElement('section')" in TRANSFORMA
    assert "trPanel.id='edTransformPanel'" in TRANSFORMA
    assert "node.id='edtr-style'" in TRANSFORMA


def test_estilo_proprio_so_alcanca_o_proprio_painel():
    regras = re.findall(r"^\s*'([^']+?)\{", TRANSFORMA, re.M)
    seletores = [r for r in regras if not r.startswith("@media")]
    assert seletores, "nenhuma regra encontrada em TR_STYLE"
    for seletor in seletores:
        assert seletor.startswith("#edTransformPanel") or seletor.startswith("#app.side-closed #edTransformPanel"), seletor


# -------------------------------------------------------- pontos de extensao

def test_ferramenta_de_repetir_usa_o_ponto_de_extensao():
    assert "registerTool('array',{" in TRANSFORMA
    assert "button:'edarray'" in TRANSFORMA
    # os botoes reservados por quem cuida da barra continuam intocados
    assert "edpen" not in TRANSFORMA and "edcut" not in TRANSFORMA


def test_previa_e_caixa_da_selecao_entram_pelo_gancho_de_overlay():
    assert "onOverlayRedraw(function(){" in TRANSFORMA
    assert "trLayer.setAttribute('id','troverlay')" in TRANSFORMA
    # a previa desenha copia por copia antes de confirmar
    previa = corpo_da_funcao(TRANSFORMA, "trDrawArray")
    assert "for(k=1;k<=count;k++)" in previa and "polygon" in previa


def test_vizinho_e_procurado_pelo_ima():
    """SNAP e quem sabe o que esta encostado; o laco proprio e so a rede de baixo."""
    consulta = corpo_da_funcao(TRANSFORMA, "trSnapQuery")
    assert "SNAP.query" in consulta and "nexolotevector" in consulta.lower()
    assert "trSnapNeighbour(i,u,sign,ring)" in corpo_da_funcao(TRANSFORMA, "trNeighbour")
    # o arrasto da direcao tambem passa pelo ima, para encostar no vizinho exato
    assert "SNAP.point(raw,e,{lot:trAnchor()})" in TRANSFORMA


def test_modulo_nao_captura_funcoes_do_nucleo_no_carregamento():
    """editor-vector.js embrulha redraw/setLotPoints DEPOIS; guardar a referencia
    antiga faria a grade do ima parar de acompanhar as transformacoes."""
    for proibido in ("var trSetPoints=setLotPoints", "var trRedrawCore=redraw;\nredraw"):
        assert proibido not in TRANSFORMA
    assert "setLotPoints(i,out)" in corpo_da_funcao(TRANSFORMA, "trEdit")


# ------------------------------------------------------------- historico

def test_toda_transformacao_entra_no_historico_incremental():
    edit = corpo_da_funcao(TRANSFORMA, "trEdit")
    assert "beginPatch(indices,['pts'])" in edit
    assert "sealPatchOrDrop(op)" in edit
    # e nenhuma operacao empilha estado inteiro por fora
    assert "pushHist(" not in TRANSFORMA and "hist.push" not in TRANSFORMA
    assert "JSON.stringify(L)" not in TRANSFORMA


def test_alinhar_distribuir_girar_escalar_e_espelhar_passam_pelo_mesmo_caminho():
    for nome in ("trAlign", "trDistribute", "trRotate", "trScale", "trFlip", "trFit"):
        assert "trEdit(" in corpo_da_funcao(TRANSFORMA, nome), nome


def test_repetir_gasta_um_unico_ctrl_z():
    repetir = corpo_da_funcao(TRANSFORMA, "trArrayApply")
    assert "ops.push({k:'insert',at:at,item:copy})" in repetir
    assert repetir.count("batchOps(ops)") == 1
    assert "batchOps(" in NUCLEO  # o composto e do nucleo, nao inventado aqui


def test_clique_que_nao_muda_nada_nao_gasta_passo_de_desfazer():
    assert "function sealPatchOrDrop(op)" in NUCLEO
    assert "sealPatchOrDrop(op);" in corpo_da_funcao(TRANSFORMA, "trEdit")


# ---------------------------------------------------- 1.500 lotes no mapa

def test_um_clique_nao_pode_dobrar_o_tamanho_do_mapa():
    assert "TR_ARRAY_MAX=800" in TRANSFORMA
    assert "if(src.length*count>TR_ARRAY_MAX)" in corpo_da_funcao(TRANSFORMA, "trArrayApply")


def test_painel_nao_mede_o_mapa_inteiro_a_cada_sincronizacao():
    """Ctrl+A seleciona os 1.500 lotes; medir todos a cada evento travaria a tela."""
    assert "TR_MEASURE_MAX=600" in TRANSFORMA
    assert "if(idx.length>TR_MEASURE_MAX)" in corpo_da_funcao(TRANSFORMA, "trMetrics")
    # e a caixa da selecao nunca junta os aneis num array unico (concat em laco)
    caixa = corpo_da_funcao(TRANSFORMA, "trBoxOf")
    assert "concat" not in caixa
    previa = corpo_da_funcao(TRANSFORMA, "trDrawArray")
    assert "src.length*count<=300" in previa  # previa vira caixa quando explode


def test_modulo_funciona_sem_o_modulo_vetorial_carregado():
    """editor-vector.js pode nao existir: o ima e opcional, o resto nao pode cair."""
    for uso in re.findall(r"[^\n]*nexoloteVector[^\n]*", TRANSFORMA):
        assert "vec&&" in uso or "var vec=window.nexoloteVector;" in uso, uso
    assert "if(!vec||!vec.snap||typeof vec.snap.tolerancePx!=='function')return null;" in TRANSFORMA


# ---------------------------------------------------------------- teclas

def teclas_simples(fonte):
    return set(re.findall(r"if\(key==='([a-z])'\)", fonte))


def test_teclas_novas_nao_pisam_nas_antigas():
    minhas = teclas_simples(TRANSFORMA)
    assert minhas == {"t", "r", "e", "h"}, minhas
    ocupadas = {"v", "m", "p", "d", "g", "b", "c", "u", "s", "a", "z", "y"}
    assert not (minhas & ocupadas)


def test_alinhar_pelo_teclado_usa_alt_e_o_nucleo_exige_digito_sem_alt():
    assert "TR_ALIGN_KEY={'1':'left','2':'centerx','3':'right','4':'top','5':'middley','6':'bottom'}" in TRANSFORMA
    assert "if(e.key==='7')" in TRANSFORMA and "if(e.key==='8')" in TRANSFORMA
    # o nucleo so trata 1/2/3 SEM alt, entao Alt+digito e terreno livre
    assert "!e.ctrlKey&&!e.metaKey&&!e.altKey&&(e.key==='1'||e.key==='2'||e.key==='3')" in NUCLEO


def test_atalho_nao_dispara_dentro_de_campo_de_texto():
    assert "/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)" in TRANSFORMA
    assert "if(e.ctrlKey||e.metaKey)return;" in TRANSFORMA


# ------------------------------------------------------------------ painel

def test_botao_so_de_icone_sai_com_aria_label_e_titulo():
    assert 'title="\'+label+\'" aria-label="\'+label+\'"' in TRANSFORMA
    # todo botao do painel nasce pelo helper, nunca solto no innerHTML
    assert re.findall(r"<button(?![^>]*aria-label)", TRANSFORMA) == []


def test_campo_numerico_declara_teclado_decimal():
    assert 'inputmode="decimal"' in corpo_da_funcao(TRANSFORMA, "trField")
    for campo in ("edtrRotStep", "edtrFactor"):
        assert 'id="%s" type="text" inputmode="decimal"' % campo in TRANSFORMA


def test_com_um_lote_so_os_botoes_ficam_desabilitados_com_motivo():
    sync = corpo_da_funcao(TRANSFORMA, "trSync")
    assert "alignOff=count<2" in sync and "distOff=count<3" in sync
    assert "trDisable(id,alignOff)" in sync and "trDisable(id,distOff)" in sync
    assert "Com um lote so nao ha o que alinhar" in sync
    assert "trText('edtrAlignWhy'" in sync


def test_painel_mostra_largura_altura_e_angulo_e_deixa_editar():
    sync = corpo_da_funcao(TRANSFORMA, "trSync")
    for campo in ("edtrW", "edtrH", "edtrA"):
        assert "trSet('%s'" % campo in sync, campo
    assert "trOn('edtrW','change'" in TRANSFORMA and "trResize(this.value,null,trPanelLock())" in TRANSFORMA
    assert "trOn('edtrA','change'" in TRANSFORMA and "trSetAngle(this.value)" in TRANSFORMA


def test_painel_acompanha_selecao_e_modo_edicao_sem_mexer_no_nucleo():
    assert "setEdit=function(on){var out=trCoreSetEdit(on);trShow(!!on);return out;};" in TRANSFORMA
    assert "syncSelection=function(){var out=trCoreSync();trSync();return out;};" in TRANSFORMA
    # o rascunho continua sendo escrito pelo nucleo; este modulo so pendura um objeto
    assert "data.transform={count:trArray.count" in TRANSFORMA
    assert HTML.count("applyDraft(") == 2


# --------------------------------------------------- matematica pura (node)

pytestmark_node = pytest.mark.skipif(shutil.which("node") is None, reason="node nao esta disponivel")


@pytestmark_node
def test_nome_sequencial_detecta_o_padrao_em_vez_de_presumir():
    casos = ["Q195-L003", "Q195-L003", "L009", "Lote 12", "Casa", "Q7-L098", "12A", "L1"]
    passos = [1, 2, 1, 1, 1, 5, 3, 9]
    corpo = ("var casos=%s,passos=%s;console.log(JSON.stringify("
             "casos.map(function(n,i){return trNextName(n,passos[i]);})));"
             % (json.dumps(casos), json.dumps(passos)))
    assert no("trNameParts", "trNextName", corpo=corpo) == [
        "Q195-L004",   # ultima sequencia de digitos, zero a esquerda preservado
        "Q195-L005",
        "L010",        # o zero some quando o numero cresce de casa
        "Lote 13",
        "Casa 2",      # sem digito nenhum entra sufixo
        "Q7-L103",
        "15A",         # o digito nao precisa estar no fim
        "L10",
    ]


@pytestmark_node
def test_distribuir_deixa_vao_igual_sem_mexer_nas_pontas():
    caixas = [{"lo": 0, "hi": 10}, {"lo": 50, "hi": 54}, {"lo": 18, "hi": 30}, {"lo": 90, "hi": 100}]
    corpo = ("var r=trSpreadDeltas(%s),caixas=%s;"
             "var finais=caixas.map(function(b,i){return{lo:b.lo+r.deltas[i],hi:b.hi+r.deltas[i]};});"
             "finais.sort(function(a,b){return a.lo-b.lo;});"
             "var vaos=[];for(var k=0;k+1<finais.length;k++)vaos.push(Math.round((finais[k+1].lo-finais[k].hi)*1e9)/1e9);"
             "console.log(JSON.stringify({gap:Math.round(r.gap*1e9)/1e9,vaos:vaos,"
             "primeiro:Math.round(finais[0].lo*1e6)/1e6,"
             "ultimo:Math.round(finais[finais.length-1].hi*1e6)/1e6}));"
             % (json.dumps(caixas), json.dumps(caixas)))
    saida = no("trSpreadDeltas", corpo=corpo)
    assert saida["vaos"] == [saida["gap"]] * 3
    assert saida["primeiro"] == 0 and saida["ultimo"] == 100  # pontas ficam onde estavam
    # 100 de vao total menos 36 de largura somada, repartido em tres frestas
    assert abs(saida["gap"] - (100 - 36) / 3) < 1e-9


@pytestmark_node
def test_distribuir_aceita_caixa_que_se_sobrepoe():
    """Fileira apertada da vao negativo; o que nao pode e vao diferente entre pares."""
    caixas = [{"lo": 0, "hi": 40}, {"lo": 10, "hi": 50}, {"lo": 20, "hi": 60}]
    corpo = ("var r=trSpreadDeltas(%s);console.log(JSON.stringify({gap:r.gap}));" % json.dumps(caixas))
    assert no("trSpreadDeltas", corpo=corpo)["gap"] < 0


@pytestmark_node
def test_angulo_do_lote_sai_da_maior_aresta():
    retangulo = [{"x": 0, "y": 0}, {"x": 100, "y": 0}, {"x": 100, "y": 20}, {"x": 0, "y": 20}]
    girado = ("var a=30*Math.PI/180,c=Math.cos(a),s=Math.sin(a);"
              "var r=%s.map(function(p){return{x:p.x*c-p.y*s,y:p.x*s+p.y*c};});" % json.dumps(retangulo))
    corpo = (girado + "console.log(JSON.stringify({reto:Math.round(trRingAngle(%s)*1e6)/1e6,"
             "girado:Math.round(trRingAngle(r)*1e6)/1e6}));" % json.dumps(retangulo))
    saida = no("trRingAngle", corpo=corpo)
    assert saida["reto"] == 0
    assert abs(saida["girado"] - 30) < 1e-6


@pytestmark_node
def test_encaixe_mapeia_o_lote_no_vao_e_recusa_esticao_absurdo():
    corpo = ("var ok=trFitMap(10,30,12,34),curto=trFitMap(10,30,12,90),nulo=trFitMap(10,10,0,5);"
             "console.log(JSON.stringify({ok:ok,lo:ok.s*10+ok.t,hi:ok.s*30+ok.t,"
             "curto:curto,nulo:nulo}));")
    saida = no("trFitMap", corpo="var TR_FIT_MIN=.5,TR_FIT_MAX=1.8;" + corpo)
    assert abs(saida["lo"] - 12) < 1e-9 and abs(saida["hi"] - 34) < 1e-9
    assert abs(saida["ok"]["s"] - 1.1) < 1e-9
    assert saida["curto"] is None and saida["nulo"] is None


@pytestmark_node
def test_alinhar_leva_a_borda_certa_para_a_referencia():
    ref = {"x0": 10, "y0": 100, "x1": 50, "y1": 140, "cx": 30, "cy": 120}
    caixa = {"x0": 0, "y0": 0, "x1": 20, "y1": 10, "cx": 10, "cy": 5}
    corpo = ("var ref=%s,box=%s,modos=['left','centerx','right','top','middley','bottom'],out={};"
             "modos.forEach(function(m){out[m]=trAlignDelta(m,ref,box);});"
             "console.log(JSON.stringify(out));" % (json.dumps(ref), json.dumps(caixa)))
    saida = no("trAlignDelta", corpo=corpo)
    assert saida["left"] == {"x": 10, "y": 0}
    assert saida["right"] == {"x": 30, "y": 0}
    assert saida["centerx"] == {"x": 20, "y": 0}
    assert saida["top"] == {"x": 0, "y": 100}
    assert saida["bottom"] == {"x": 0, "y": 130}
    assert saida["middley"] == {"x": 0, "y": 115}


@pytestmark_node
def test_o_modulo_inteiro_e_javascript_valido():
    """Nao ha lint no caminho: erro de sintaxe so apareceria no navegador do operador."""
    montado = re.sub(r"__[A-Z][A-Z0-9_]*__", "0", pdf_to_map._editor_scripts())
    saida = subprocess.run(["node", "--check", "-"], input=montado,
                           capture_output=True, text=True, timeout=60)
    assert saida.returncode == 0, saida.stderr
