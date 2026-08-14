"""Garantias sobre as ferramentas de caminho do editor (templates/editor/editor-vector.js).

O modulo vetorial (caneta bezier, vertices, ima, dividir e unir) nao passa por
lint nem typecheck: erro so aparece no navegador do operador. Estes testes
travam o que ja custa caro em producao:

* a costura precisa continuar entregando um HTML unico, com o modulo dentro do
  mesmo bloco de script - se ele cair fora, o editor abre sem as ferramentas;
* os pontos de extensao (registerTool/onOverlayRedraw/SNAP) sao o contrato com
  os outros modulos do editor; sumindo um deles, ferramenta nova para de existir
  sem erro visivel;
* a tesselacao da caneta tem que usar a MESMA regra do motor (`_bezier_steps`),
  senao o lote desenhado a mao sai com contorno diferente do extraido do PDF;
* dividir e unir mexem em area e nome: elas precisam recusar em voz alta em vez
  de gravar geometria errada.
"""
import json
import math
import os
import re
import shutil
import subprocess
import tempfile

import pytest

import pdf_to_map


RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDITOR = os.path.join(RAIZ, "templates", "editor")
VETOR = open(os.path.join(EDITOR, "editor-vector.js"), encoding="utf-8").read()
NUCLEO = open(os.path.join(EDITOR, "editor.js"), encoding="utf-8").read()
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


# ------------------------------------------------------------------ costura

def test_modulo_vetorial_existe_e_nao_esta_vazio():
    caminho = os.path.join(EDITOR, "editor-vector.js")
    assert os.path.isfile(caminho), "editor-vector.js sumiu de templates/editor"
    assert os.path.getsize(caminho) > 5000


def test_costura_le_o_nucleo_primeiro_e_depois_os_modulos():
    montado = pdf_to_map._editor_scripts()
    assert montado.index("window.getMapaPayload=currentPayload") < montado.index("window.nexoloteVector")


def test_modulo_entra_no_mesmo_bloco_de_script_do_editor():
    assert HTML.count("<script>") == 1 and HTML.count("</script>") == 1
    assert "window.nexoloteVector" in HTML
    assert HTML.index("window.getMapaPayload=currentPayload") < HTML.index("window.nexoloteVector")


def test_qualquer_editor_modulo_novo_entra_na_costura_sozinho():
    """A costura varre editor-*.js: modulo novo nao pode exigir mexer em pdf_to_map."""
    with tempfile.NamedTemporaryFile("w", suffix=".js", prefix="editor-zz-teste",
                                     dir=EDITOR, delete=False, encoding="utf-8") as arquivo:
        arquivo.write("var marcaDoTesteDeCostura=1;\n")
        temporario = arquivo.name
    try:
        assert "marcaDoTesteDeCostura" in pdf_to_map._editor_scripts()
    finally:
        os.remove(temporario)


# -------------------------------------------------------- pontos de extensao

def test_nucleo_declara_os_pontos_de_extensao():
    for trecho in ("function registerTool(name,spec)", "function toolHook(name,e)",
                   "function onOverlayRedraw(fn)", "function redrawOverlays()",
                   "var SNAP={point:", "function batchOps(ops)", "function makePatch(indices,keys)",
                   "function sealPatchOrDrop(op)"):
        assert trecho in NUCLEO, trecho


def test_nucleo_chama_os_ganchos_nos_quatro_eventos():
    for trecho in ("if(editMode&&toolHook('down',e))return;",
                   "if(editMode&&toolHook('move',e))return;",
                   "if(editMode&&toolHook('up',e))",
                   "if(toolHook('click',e))return;",
                   "if(toolHook('key',e))return;"):
        assert trecho in NUCLEO, trecho


def test_ima_e_chamado_pelo_arrasto_de_vertice_e_pelo_mover():
    assert "SNAP.point(toLocal(c2s(e.clientX,e.clientY)),e,{lot:vertexDrag.i,vertex:vertexDrag.v})" in NUCLEO
    assert "step=SNAP.translation(current.x-movePrevious.x,current.y-movePrevious.y,e)" in NUCLEO
    assert "SNAP.begin('move',Array.from(selected))" in NUCLEO
    assert "SNAP.end();" in NUCLEO


def test_ferramentas_antigas_continuam_registradas_no_setTool():
    """setTool ganhou ganchos; os cinco botoes de sempre nao podem ter sumido."""
    assert "edsel:'select',edmove:'move',edvertex:'vertex',eddraw:'draw',eddel:'delete'" in NUCLEO
    for trecho in ("if(key==='v')setTool('select')", "if(key==='m')setTool('move')",
                   "if(key==='p')setTool('vertex')", "if(key==='d')setTool('draw')",
                   "if(e.key==='Enter'&&tool==='draw')finishDraft()"):
        assert trecho in HTML, trecho


# ------------------------------------------------------------- ferramentas

def test_caneta_e_corte_se_registram_pelo_ponto_de_extensao():
    for nome in ("registerTool('pen',", "registerTool('cut',", "registerTool('vertex',"):
        assert nome in VETOR, nome
    # botoes reservados para quem cuida da barra de ferramentas
    assert "button:'edpen'" in VETOR and "button:'edcut'" in VETOR


def test_caneta_tem_reto_curva_fechar_apagar_e_cancelar():
    assert "if(vecPenNearFirst(p)&&vecPen.nodes.length>=3){vecPenFinish();return true;}" in VETOR
    assert "if(e.key==='Enter')" in VETOR
    assert "if(e.key==='Backspace'||e.key==='Delete')" in VETOR
    assert "if(e.key==='Escape')" in VETOR
    # alt quebra a simetria da alca, como no Illustrator
    assert "node.i=e.altKey?node.i:{x:2*node.x-p.x,y:2*node.y-p.y};" in VETOR


def test_caneta_reaproveita_o_historico_do_desenho_antigo():
    """finishDraft ja empilha {k:'insert'}; a caneta nao pode ter historico proprio."""
    assert "draft=points.map(" in VETOR and "finishDraft();" in VETOR


def test_atalhos_novos_nao_pisam_nos_antigos():
    novos = re.findall(r"if\(key==='([a-z])'\)\{e\.preventDefault\(\);", VETOR)
    assert set(novos) == {"b", "c", "u", "s"}
    antigos = set(re.findall(r"if\(key==='([a-z])'\)setTool", NUCLEO)) | {"g"}
    assert not (set(novos) & antigos)


# ------------------------------------------------------------------ vertices

def test_vertice_entra_e_sai_com_clique_duplo():
    assert "svg.addEventListener('dblclick'" in VETOR
    assert "function vecVertexInsert(i,p)" in VETOR
    assert "function vecVertexRemove(i,index)" in VETOR


def test_lote_nunca_fica_com_menos_de_tres_pontos():
    remover = corpo_da_funcao(VETOR, "vecVertexRemove")
    assert "if(ring.length<=3)" in remover
    assert "return out.length>=3?out:ring.slice();" in VETOR


def test_vertice_usa_o_historico_incremental():
    aplicar = corpo_da_funcao(VETOR, "vecVertexApply")
    assert "beginPatch([i],['pts'])" in aplicar and "sealPatch(op)" in aplicar


# ---------------------------------------------------------------------- ima

def test_tolerancia_do_ima_e_em_pixel_de_tela():
    """Em coordenada de mapa o ima grudaria tudo no zoom afastado e nada no fechado."""
    assert "VEC_SNAP_PX=10" in VETOR
    assert "function vecPx(px){return px/vecScale();}" in VETOR
    assert "tol=vecPx(VEC_SNAP_PX)" in corpo_da_funcao(VETOR, "vecSnapQuery")


def test_ima_cobre_vertice_meio_de_aresta_projecao_e_angulo():
    consulta = corpo_da_funcao(VETOR, "vecSnapQuery")
    for tipo in ("k:'vertex'", "k:'mid'", "k:'edge'"):
        assert tipo in consulta, tipo
    trava = corpo_da_funcao(VETOR, "vecAngleLock")
    assert "Math.PI/4" in trava  # 0, 45 e 90 graus


def test_ima_nao_varre_todos_os_lotes_a_cada_mousemove():
    """Com 1.500 lotes, varrer L inteiro por evento derruba o arrasto."""
    consulta = corpo_da_funcao(VETOR, "vecSnapQuery")
    assert "vecGridEach(" in consulta
    assert "L.length" not in consulta
    assert "function vecGridEach(x,y,r,visit)" in VETOR
    # a grade e construida uma vez e atualizada por operacao
    assert "function vecGridBuild()" in VETOR
    assert "redraw=function(){vecGridInvalidate();" in VETOR
    assert "setLotPoints=function(i,points){vecCoreSetLotPoints(i,points);if(vecGrid.built)vecDirty[i]=1;};" in VETOR


def test_guia_do_ima_some_ao_soltar():
    fim = corpo_da_funcao(VETOR, "vecSnapEnd")
    assert "vecGuide=null" in fim and "vecGuideDraw()" in fim


def test_estado_do_ima_acompanha_o_rascunho():
    assert "data.vector={snap:vecSnapOn};" in VETOR
    assert "if(data&&data.vector)vecSnapSet(!!data.vector.snap,true);" in VETOR
    # o rascunho continua sendo escrito pelo nucleo, sem copia paralela
    assert HTML.count("applyDraft(") == 2


# ------------------------------------------------------------------ dividir

def test_divisao_usa_sutherland_hodgman_por_semiplano():
    assert "function vecClipHalfPlane(ring,a,b,side)" in VETOR
    corte = corpo_da_funcao(VETOR, "vecSplitRing")
    assert "vecClipHalfPlane(ring,a,b,1)" in corte and "vecClipHalfPlane(ring,a,b,-1)" in corte


def test_divisao_recusa_corte_que_o_algoritmo_nao_resolve():
    """Poligono concavo cortado em mais de dois pontos gera aresta falsa no S-H."""
    corte = corpo_da_funcao(VETOR, "vecSplitRing")
    assert "if(crossings>2)return{ok:false" in corte
    assert "if(crossings===0)return{ok:false" in corte
    # rede de seguranca: a soma das partes tem que reproduzir o original
    assert "if(Math.abs(al+ar-total)>Math.max(1e-6,total*1e-4))return{ok:false" in corte


def test_divisao_herda_nome_quadra_e_status_com_sufixo():
    dividir = corpo_da_funcao(VETOR, "vecSplitLot")
    assert "lot.nome=baseName+'-A';" in dividir
    assert "second.nome=baseName+'-B';" in dividir
    # quadra, status e cor vem do clone, entao nao podem ser reescritos
    assert "second=JSON.parse(JSON.stringify(lot))" in dividir
    assert "second.quadra=" not in dividir and "second.s=" not in dividir
    # area em texto e repartida na proporcao das areas geometricas
    assert "shape.value*cut.areas[0]/cut.total" in dividir


def test_divisao_e_uniao_gastam_um_unico_passo_de_desfazer():
    assert "batchOps([before,{k:'insert',at:index+1,item:second}])" in VETOR
    assert "batchOps([patch,{k:'remove',items:removed}])" in VETOR
    assert "if(op.k==='batch'){for(var b=op.ops.length-1;b>=0;b--)undoOp(op.ops[b]);}" in NUCLEO
    assert "if(op.k==='batch'){for(var b=0;b<op.ops.length;b++)redoOp(op.ops[b]);}" in NUCLEO


# --------------------------------------------------------------------- unir

def test_uniao_e_varredura_de_arestas_com_validacao_de_area():
    uniao = corpo_da_funcao(VETOR, "vecUnionRings")
    assert "vecSegHit(a,b,c,d)" in uniao          # quebra nos cruzamentos
    assert "vecProject(c,a,b)" in uniao           # e nos vertices em T
    assert "vecOnRing(mid,polys[j],tol)||vecPointInRing(mid,polys[j])" in uniao
    assert "if(area<biggest*0.999||area>sum*1.003)" in uniao
    # a area de referencia sai dos contornos originais: a propria solda entra na conta
    assert "for(i=0;i<rings.length;i++){var pa=Math.abs(vecArea(rings[i]));" in uniao


def test_uniao_afrouxa_a_solda_por_etapas_e_valida_cada_uma():
    """Divisa do CAD chega com sobra de decimo; a solda abre, a validacao nao."""
    assert "VEC_WELD_STEPS=[0.25,0.6,1.2]" in VETOR
    juntar = corpo_da_funcao(VETOR, "vecMergeLots")
    assert "for(var t=0;t<VEC_WELD_STEPS.length;t++)" in juntar
    assert "if(union.ok)break;" in juntar


def test_uniao_recusa_em_voz_alta_em_vez_de_inventar_geometria():
    uniao = corpo_da_funcao(VETOR, "vecUnionRings")
    recusas = re.findall(r"return\{ok:false,reason:'([^']+)'", uniao)
    assert len(recusas) >= 5
    assert any("vizinhos" in motivo for motivo in recusas)
    # toda recusa aparece para o operador
    juntar = corpo_da_funcao(VETOR, "vecMergeLots")
    assert "if(!union.ok){toast(union.reason,true);return union;}" in juntar


def test_uniao_mantem_o_nome_do_primeiro_e_soma_a_area():
    juntar = corpo_da_funcao(VETOR, "vecMergeLots")
    assert "var keep=list[0]" in juntar
    assert "if(shape&&parsed===list.length)lot.area=vecAreaFormat(shape,total);" in juntar


# --------------------------------------------------------------- tesselacao

def constante_js(nome):
    achado = re.search(nome + r"=([0-9.]+)", VETOR)
    assert achado, nome
    return float(achado.group(1))


def test_tesselacao_usa_a_mesma_tolerancia_do_motor():
    """Tolerancia diferente no JS faz a curva desenhada divergir da extraida."""
    assert constante_js("CURVE_FLATNESS_TOL") == pdf_to_map.CURVE_FLATNESS_TOL
    assert constante_js("MAX_CURVE_STEPS") == pdf_to_map.MAX_CURVE_STEPS


CURVAS = [
    ((0, 0), (10, 0), (20, 0), (30, 0)),          # reta: um segmento so
    ((0, 0), (0, 0), (0, 0), (0, 0)),             # corda nula
    ((0, 0), (10, 1), (20, -1), (30, 0)),         # quase reta
    ((0, 0), (0, 40), (60, 40), (60, 0)),         # arco de frente de lote
    ((0, 0), (0, 400), (600, 400), (600, 0)),     # arco fechado, bate no teto
    ((5, 5), (30, 90), (90, 30), (120, 5)),
]


class Ponto:
    def __init__(self, x, y):
        self.x, self.y = x, y


@pytest.mark.skipif(shutil.which("node") is None, reason="node nao esta disponivel")
def test_tesselacao_do_js_bate_com_bezier_steps_do_motor():
    """Roda a funcao do editor no node e compara com o Python, curva por curva."""
    constantes = re.search(r"var CURVE_FLATNESS_TOL=[^;]+;", VETOR).group(0)
    harness = "\n".join([
        constantes,
        corpo_da_funcao(VETOR, "vecBezierSteps"),
        "var casos=JSON.parse(process.argv[1]);",
        "console.log(JSON.stringify(casos.map(function(c){",
        "  return vecBezierSteps({x:c[0][0],y:c[0][1]},{x:c[1][0],y:c[1][1]},",
        "                        {x:c[2][0],y:c[2][1]},{x:c[3][0],y:c[3][1]});})));",
    ])
    saida = subprocess.run(["node", "-e", harness, json.dumps(CURVAS)],
                           capture_output=True, text=True, timeout=60)
    assert saida.returncode == 0, saida.stderr
    do_js = json.loads(saida.stdout)
    do_python = [pdf_to_map._bezier_steps(*[Ponto(*par) for par in curva]) for curva in CURVAS]
    assert do_js == do_python


@pytest.mark.skipif(shutil.which("node") is None, reason="node nao esta disponivel")
def test_pontos_da_curva_do_js_batem_com_o_laco_do_motor():
    """Mesma quantidade de passos nao basta: os pontos tem que cair no mesmo lugar."""
    constantes = re.search(r"var CURVE_FLATNESS_TOL=[^;]+;", VETOR).group(0)
    curva = ((0, 0), (0, 40), (60, 40), (60, 0))
    harness = "\n".join([
        constantes,
        corpo_da_funcao(VETOR, "vecBezierSteps"),
        corpo_da_funcao(VETOR, "vecBezierPoints"),
        "var c=JSON.parse(process.argv[1]);",
        "console.log(JSON.stringify(vecBezierPoints({x:c[0][0],y:c[0][1]},{x:c[1][0],y:c[1][1]},",
        "                                           {x:c[2][0],y:c[2][1]},{x:c[3][0],y:c[3][1]})));",
    ])
    saida = subprocess.run(["node", "-e", harness, json.dumps(curva)],
                           capture_output=True, text=True, timeout=60)
    assert saida.returncode == 0, saida.stderr
    do_js = json.loads(saida.stdout)
    p0, p1, p2, p3 = [Ponto(*par) for par in curva]
    passos = pdf_to_map._bezier_steps(p0, p1, p2, p3)
    esperado = []
    for passo in range(1, passos + 1):
        t = passo / passos
        u = 1.0 - t
        esperado.append((u**3 * p0.x + 3*u*u*t * p1.x + 3*u*t*t * p2.x + t**3 * p3.x,
                         u**3 * p0.y + 3*u*u*t * p1.y + 3*u*t*t * p2.y + t**3 * p3.y))
    assert len(do_js) == len(esperado)
    for atual, alvo in zip(do_js, esperado):
        assert math.isclose(atual["x"], alvo[0], abs_tol=1e-9)
        assert math.isclose(atual["y"], alvo[1], abs_tol=1e-9)
