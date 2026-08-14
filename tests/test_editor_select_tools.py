"""Garantias sobre selecao avancada, medida e renomear em lote (templates/editor/editor-select.js).

O modulo nasce de tres problemas concretos do operador que corrige o mapeamento
de uma planta com 1.500 lotes:

* clique e caixa retangular nao pegam uma quadra torta nem uma fileira que
  contorna a rua - falta laco, criterio e "os semelhantes a este";
* o editor so falava em pixels, mas cada lote traz a metragem impressa no PDF:
  sem derivar a escala nao da para medir em metros nem enxergar o lote cuja
  area calculada diverge da impressa (o defeito de mapeamento mais comum);
* depois de dividir ou repetir uma fileira, renomear lote a lote e inviavel.

Estes testes travam o que custa caro em producao:

* a costura precisa continuar entregando um HTML unico com o modulo no MESMO
  bloco de script - fora dele o editor abre sem os comandos;
* renomear a selecao inteira tem que sair com UM Ctrl+Z;
* a escala vem da mediana entre area vetorial e metragem impressa, com o mesmo
  criterio de `_area_agreement` em pdf_to_map.py; sem amostra suficiente o
  editor precisa DIZER que continua em pixels em vez de inventar escala;
* o painel e montado por JS, sem tocar em editor.css nem editor.html (outro
  dono), entao o estilo proprio fica preso ao prefixo edsel-;
* as teclas novas nao podem pisar nas que ja existem.
"""
import inspect
import json
import os
import re
import shutil
import subprocess

import pytest

import pdf_to_map


RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDITOR = os.path.join(RAIZ, "templates", "editor")
CAMINHO = os.path.join(EDITOR, "editor-select.js")
SELECAO = open(CAMINHO, encoding="utf-8").read()
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
    fonte = "\n".join([extra] + [corpo_da_funcao(SELECAO, nome) for nome in funcoes] + [corpo])
    saida = subprocess.run(["node", "-e", fonte], capture_output=True, text=True, timeout=60)
    assert saida.returncode == 0, saida.stderr
    return json.loads(saida.stdout)


# ------------------------------------------------------------------ costura

def test_modulo_existe_e_nao_esta_vazio():
    assert os.path.isfile(CAMINHO), "editor-select.js sumiu de templates/editor"
    assert os.path.getsize(CAMINHO) > 5000


def test_modulo_entra_sozinho_na_costura_depois_do_nucleo():
    montado = pdf_to_map._editor_scripts()
    assert "window.nexoloteSelect" in montado
    assert montado.index("window.getMapaPayload=currentPayload") < montado.index("window.nexoloteSelect")


def test_modulo_fica_no_mesmo_bloco_de_script_do_editor():
    assert HTML.count("<script>") == 1 and HTML.count("</script>") == 1
    assert "window.nexoloteSelect" in HTML


def test_modulo_nao_deixa_marcador_de_substituicao_no_html():
    """Um `__NOME__` esquecido no modulo vira JS invalido e o editor abre em branco."""
    assert not re.findall(r"__[A-Z][A-Z0-9_]*__", SELECAO)


def test_modulo_nao_precisou_de_css_nem_de_html_de_terceiros():
    """O layout tem outro dono: o painel nasce por JS e o estilo proprio e prefixado."""
    assert "edSelectPanel" not in CORPO_HTML and "edSelectPanel" not in CSS
    assert "edsel-" not in CSS
    assert "document.createElement('section')" in SELECAO
    assert "selPanel.id='edSelectPanel'" in SELECAO
    assert "node.id='edsel-style'" in SELECAO


def test_estilo_proprio_so_alcanca_o_proprio_painel():
    regras = re.findall(r"^\s*'([^']+?)\{", SELECAO, re.M)
    seletores = [r for r in regras if not r.startswith("@media")]
    assert seletores, "nenhuma regra encontrada em SEL_STYLE"
    for seletor in seletores:
        assert "#edSelectPanel" in seletor, seletor
    # o foco visivel do nucleo nao pode ser desligado por este modulo
    assert "outline:none" not in SELECAO and "outline:0" not in SELECAO


def test_modulo_nao_reescreve_o_rascunho_do_nucleo():
    """draftBody/applyDraft continuam do nucleo; este modulo so pendura um objeto."""
    assert "data.select={check:selCheckOn" in SELECAO
    assert "selCoreDraftApply=applyDraft" in SELECAO
    # a definicao e o clique em Restaurar - nenhum modulo pode chamar applyDraft de novo
    assert HTML.count("applyDraft(") == 2


# -------------------------------------------------------- pontos de extensao

def test_laco_e_regua_usam_o_ponto_de_extensao():
    assert "registerTool('lasso',{" in SELECAO and "button:'edlasso'" in SELECAO
    assert "registerTool('ruler',{" in SELECAO and "button:'edruler'" in SELECAO
    # os botoes reservados por quem cuida da barra continuam intocados
    for reservado in ("edpen", "edcut", "edarray"):
        assert reservado not in SELECAO, reservado


def test_laco_regua_e_conferencia_entram_pelo_gancho_de_overlay():
    assert "onOverlayRedraw(function(){" in SELECAO
    assert "selMarkLayer.setAttribute('id','edselmark')" in SELECAO
    assert "selViewLayer.setAttribute('id','edselview')" in SELECAO
    # a marca da conferencia desenha o contorno do lote (dentro de #lotsrot)
    assert "lotsrot.appendChild(selMarkLayer)" in SELECAO
    assert "polygon" in corpo_da_funcao(SELECAO, "selDrawCheck")


def test_modulo_funciona_sem_o_vetorial_e_sem_o_transformar():
    """editor-select.js carrega ANTES dos outros dois: nao pode depender deles."""
    assert "nexoloteVector" not in SELECAO and "nexoloteTransform" not in SELECAO
    # geometria propria, e o ima e sempre opcional
    for nome in ("selRing", "selRingArea", "selPointInRing"):
        assert "function %s(" % nome in SELECAO, nome
    assert "if(!SNAP||typeof SNAP.point!=='function')return p;" in SELECAO


def test_modulo_embrulha_o_nucleo_em_vez_de_edita_lo():
    for gancho in ("selCoreSetEdit=setEdit", "selCoreSync=syncSelection", "selCoreRedraw=redraw",
                   "selCoreSetLotPoints=setLotPoints", "selCoreMarkDirty=markDirty",
                   "selCoreFinishDragBox=finishDragBox"):
        assert gancho in SELECAO, gancho
    assert "setEdit=function(on){var out=selCoreSetEdit(on);selShow(!!on);return out;};" in SELECAO


# ------------------------------------------------------------- historico

def test_renomear_em_lote_gasta_um_unico_ctrl_z():
    renomear = corpo_da_funcao(SELECAO, "selRenameApply")
    assert renomear.count("beginPatch(indices,['nome'])") == 1
    assert "sealPatchOrDrop(op)" in renomear
    assert "function sealPatchOrDrop(op)" in NUCLEO  # o carimbo e do nucleo
    # e nenhuma operacao empilha estado inteiro por fora
    assert "pushHist(" not in SELECAO and "hist.push" not in SELECAO
    assert "JSON.stringify(L)" not in SELECAO


def test_selecionar_nao_gasta_passo_de_desfazer():
    """Selecionar nao muda o mapa: nada de patch em selApply, laco ou criterio."""
    for nome in ("selApply", "selLassoFinish", "selRunQuery", "selSimilar", "selInvert"):
        assert "beginPatch" not in corpo_da_funcao(SELECAO, nome), nome


def test_renomear_avisa_antes_de_criar_nome_repetido():
    plano = corpo_da_funcao(SELECAO, "selRenamePlan")
    assert "conflitos" in plano and "repetidos" in plano
    assert "semContador" in plano  # padrao sem {n} daria o mesmo nome para todos
    previa = corpo_da_funcao(SELECAO, "selRenameNote")
    assert "ja existe" in previa and "repetido" in previa
    assert "um unico Ctrl+Z desfaz tudo" in previa


# ---------------------------------------------------- 1.509 lotes no mapa

def test_area_de_1500_lotes_nao_e_recalculada_a_cada_clique():
    assert "var selCache=" in SELECAO
    assert "function selEnsure()" in SELECAO
    # o cache so cai quando o mapa muda de verdade
    assert "markDirty=function(){selInvalidate();return selCoreMarkDirty();};" in SELECAO
    assert "setLotPoints=function(i,points){var out=selCoreSetLotPoints(i,points);selTouch(i);return out;};" in SELECAO


def test_painel_recolhido_nao_varre_o_mapa_por_nada():
    sync = corpo_da_funcao(SELECAO, "selSync")
    assert "if(selPanel.hidden||selPanel.classList.contains('edsel-off'))return;" in sync
    # o resumo (contagem + area) e atualizado ANTES desse corte
    assert sync.index("edselSummary") < sync.index("edsel-off")


def test_laco_nao_guarda_um_ponto_por_pixel_nem_relê_o_mapa_inteiro():
    push = corpo_da_funcao(SELECAO, "selLassoPush")
    assert "selPx(4)" in push
    indices = corpo_da_funcao(SELECAO, "selLassoIndices")
    assert "fromLocal(cachedCenter(i))" in indices  # centro em cache, sem reparsear os pontos
    assert "if(c.x<box.x0||c.x>box.x1||c.y<box.y0||c.y>box.y1)continue;" in indices


def test_marca_de_conferencia_tem_teto_e_corta_pelo_que_esta_na_tela():
    assert "SEL_CHECK_DRAW=600" in SELECAO
    desenho = corpo_da_funcao(SELECAO, "selDrawCheck")
    assert "feitos<SEL_CHECK_DRAW" in desenho
    assert "if(c.x<x0||c.x>x1||c.y<y0||c.y>y1)continue;" in desenho


# --------------------------------------------------- escala real da planta

def test_escala_sai_da_mediana_entre_area_vetorial_e_metragem_impressa():
    reconstroi = corpo_da_funcao(SELECAO, "selRebuild")
    assert "ratios.push(selCache.px[i]/selCache.printed[i])" in reconstroi
    assert "selMedian(ratios)" in reconstroi
    assert "Math.sqrt(selCache.ratio)" in corpo_da_funcao(SELECAO, "selScale")


def test_criterio_da_escala_e_o_mesmo_de_area_agreement():
    """Se um lado mudar de tolerancia ou de amostra minima, o outro precisa saber."""
    fonte = inspect.getsource(pdf_to_map._area_agreement)
    assert "tolerance=0.05" in fonte
    assert "len(printed_areas) < 20" in fonte and "len(ratios) < 20" in fonte
    assert "sorted(ratios)[len(ratios) // 2]" in fonte
    assert "SEL_AREA_TOL=.05" in SELECAO and "SEL_SCALE_MIN=20" in SELECAO


def test_sem_metragem_suficiente_o_editor_diz_e_continua_em_pixels():
    nota = corpo_da_funcao(SELECAO, "selScaleNote")
    assert "Sem escala" in nota and "As medidas ficam em pixels." in nota
    escala = corpo_da_funcao(SELECAO, "selScale")
    assert "ok?selCache.ratio:null" in escala  # nada de escala inventada
    assert "selScale().ok?'m\\u00b2':'px\\u00b2'" in SELECAO


def test_regua_responde_em_metros_e_com_angulo():
    medir = corpo_da_funcao(SELECAO, "selMeasure")
    assert "dist/s.pxPerM" in medir and "Math.atan2" in medir
    assert "escala:s.ok" in medir  # sem escala a regua nao finge metro


def test_conferencia_marca_quem_diverge_mais_de_cinco_por_cento():
    reconstroi = corpo_da_funcao(SELECAO, "selRebuild")
    assert "Math.abs((px/printed)/selCache.ratio-1)<=SEL_AREA_TOL" in reconstroi
    assert "selCache.off.push(i)" in reconstroi


# ---------------------------------------------------------------- teclas

def teclas_simples(fonte):
    return set(re.findall(r"if\(key==='([a-z])'\)", fonte))


def test_teclas_novas_nao_pisam_nas_antigas():
    minhas = teclas_simples(SELECAO)
    assert minhas == {"f", "i", "k", "l", "n", "q", "w"}, minhas
    ocupadas = {"v", "m", "p", "d", "g", "a", "b", "c", "u", "s", "t", "r", "e", "h", "z", "y"}
    assert not (minhas & ocupadas)
    # e nenhum outro modulo do editor pode ter pego as mesmas letras
    for vizinho in ("editor-transform.js", "editor-vector.js"):
        caminho = os.path.join(EDITOR, vizinho)
        if os.path.isfile(caminho):
            assert not (minhas & teclas_simples(open(caminho, encoding="utf-8").read())), vizinho


def test_atalho_nao_dispara_dentro_de_campo_de_texto_nem_com_modificador():
    assert "/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)" in SELECAO
    assert "if(e.ctrlKey||e.metaKey||e.altKey)return;" in SELECAO


def test_shift_soma_e_alt_subtrai_em_todos_os_modos():
    modo = corpo_da_funcao(SELECAO, "selModeOf")
    assert "e.altKey" in modo and "e.shiftKey" in modo
    # a caixa retangular do nucleo so recebe o Shift; o Alt vem do ultimo ponteiro
    assert "document.addEventListener('pointerdown',selReadMods,true)" in SELECAO
    assert "selApply(lista,'sub'" in SELECAO
    for botao in ("edselQuadra", "edselSimQuadra", "edselSimStatus", "edselSimArea", "edselRun"):
        assert "selOn('%s','click',function(e){" % botao in SELECAO, botao


# ------------------------------------------------------------------ painel

def test_botao_so_de_icone_sai_com_aria_label_e_titulo():
    assert 'title="\'+label+\'" aria-label="\'+label+\'"' in SELECAO
    # todo botao do painel nasce pelo helper, nunca solto no innerHTML
    assert re.findall(r"<button(?![^>]*aria-label)", SELECAO) == []


def test_resumo_da_selecao_e_uma_regiao_viva_para_leitor_de_tela():
    assert 'id="edselSummary" role="status" aria-live="polite"' in SELECAO
    resumo = corpo_da_funcao(SELECAO, "selSummaryText")
    assert "soma.count" in resumo and "selFmtM2(soma.m2)" in resumo and "selFmtPx(soma.px)" in resumo


def test_previa_de_nomes_aparece_antes_de_aplicar():
    assert 'id="edselPreview"' in SELECAO
    assert "selOn('edselRename','click',function(){selRenameApply();});" in SELECAO
    nota = corpo_da_funcao(SELECAO, "selRenameNote")
    assert "selRenamePlan()" in nota and "'... mais '" in nota


def test_painel_oferece_status_quadra_area_e_padrao_de_nome():
    # select nasce inline; campo de texto nasce pelo helper selField (que carimba o id)
    for campo in ("edselStatus", "edselQuadraSel"):
        assert 'id="%s"' % campo in SELECAO, campo
    for campo in ("edselName", "edselAreaMin", "edselAreaMax", "edselPattern", "edselStart", "edselPad"):
        assert "selField('%s'" % campo in SELECAO, campo
    assert 'id="'+"'+id+'"+'"' in corpo_da_funcao(SELECAO, "selField")
    assert "function selQuadraOptions()" in SELECAO


# --------------------------------------------------- matematica pura (node)

pytestmark_node = pytest.mark.skipif(shutil.which("node") is None, reason="node nao esta disponivel")


@pytestmark_node
def test_metragem_impressa_e_lida_com_o_separador_da_planta():
    casos = ["178.86m2", "1.234,56 m2", "1.234 m2", "312,5", "45", "", "sem numero", "2.750,00m2"]
    corpo = ("console.log(JSON.stringify(%s.map(function(t){return selParseArea(t);})));"
             % json.dumps(casos))
    assert no("selParseArea", corpo=corpo) == [178.86, 1234.56, 1234, 312.5, 45, None, None, 2750]


@pytestmark_node
def test_mediana_e_a_mesma_do_lado_python():
    valores = [5, 1, 4, 2, 3]
    corpo = ("console.log(JSON.stringify({impar:selMedian(%s),par:selMedian([1,2,3,4]),vazio:selMedian([])}));"
             % json.dumps(valores))
    saida = no("selMedian", corpo=corpo)
    assert saida["impar"] == 3
    assert saida["par"] == 3  # sorted(v)[len//2], igual a _area_agreement
    assert saida["vazio"] is None  # NaN nao sobrevive ao JSON


@pytestmark_node
def test_area_do_poligono_e_ponto_dentro_do_contorno():
    ring = [{"x": 0, "y": 0}, {"x": 20, "y": 0}, {"x": 20, "y": 10}, {"x": 0, "y": 10}]
    corpo = ("var r=%s;console.log(JSON.stringify({area:selRingArea(r),"
             "dentro:selPointInRing({x:10,y:5},r),fora:selPointInRing({x:30,y:5},r),"
             "invertido:selRingArea(r.slice().reverse())}));" % json.dumps(ring))
    saida = no("selRingArea", "selPointInRing", corpo=corpo)
    assert saida["area"] == 200 and saida["invertido"] == 200  # sentido nao muda a area
    assert saida["dentro"] is True and saida["fora"] is False


@pytestmark_node
def test_ordem_de_leitura_tolera_fileira_desalinhada():
    """Numa quadra real os centros nao ficam no mesmo y; a linha e uma faixa."""
    pontos = [
        {"i": 3, "x": 30, "y": 101},
        {"i": 1, "x": 10, "y": 100},
        {"i": 2, "x": 20, "y": 99},
        {"i": 6, "x": 30, "y": 160},
        {"i": 4, "x": 10, "y": 161},
        {"i": 5, "x": 20, "y": 159},
    ]
    corpo = ("console.log(JSON.stringify({faixa:selOrderScreen(%s,20),"
             "semFaixa:selOrderScreen(%s,0.5)}));" % (json.dumps(pontos), json.dumps(pontos)))
    saida = no("selOrderScreen", "selRowSort", corpo=corpo)
    assert saida["faixa"] == [1, 2, 3, 4, 5, 6]
    # faixa apertada demais volta a ser ordem por y (cada lote vira uma linha)
    assert saida["semFaixa"] != [1, 2, 3, 4, 5, 6]


@pytestmark_node
def test_padrao_de_nome_conta_com_zero_a_esquerda_e_conhece_a_quadra():
    corpo = ("var lot={quadra:'Q195',s:1};console.log(JSON.stringify(["
             "selNameFor('Q195-L{n}',4,3,lot),selNameFor('Q195-L{n}',4,0,lot),"
             "selNameFor('{q}-L{n}',12,2,lot),selNameFor('L{n}',1000,3,lot),"
             "selNameFor('Lote unico',7,3,lot),selNameFor('{q}-{s}-{n}',1,2,lot)]));")
    assert no("selNameFor", corpo="var NAMES=['Disponivel','Vendido','Reservado'];" + corpo) == [
        "Q195-L004",
        "Q195-L4",
        "Q195-L12",
        "L1000",       # o zero a esquerda nao corta o numero quando ele cresce
        "Lote unico",  # padrao sem {n}: a previa avisa que todos ficariam iguais
        "Q195-Vendido-01",
    ]


@pytestmark_node
def test_padrao_de_busca_aceita_coringa_trecho_e_regex():
    nomes = ["Q195-L001", "Q195-L002", "Q7-L001", "Casa 3"]
    corpo = ("var nomes=%s;function casa(p){var re=selPatternRe(p);"
             "return nomes.filter(function(n){return re&&re.test(n);});}"
             "console.log(JSON.stringify({coringa:casa('Q195-*'),interrogacao:casa('Q?-L001'),"
             "trecho:casa('l00'),regex:casa('/^Q\\\\d+-L002$/'),vazio:selPatternRe('   ')}));"
             % json.dumps(nomes))
    saida = no("selPatternRe", corpo=corpo)
    assert saida["coringa"] == ["Q195-L001", "Q195-L002"]
    assert saida["interrogacao"] == ["Q7-L001"]
    assert saida["trecho"] == ["Q195-L001", "Q195-L002", "Q7-L001"]  # sem coringa = trecho, sem caixa
    assert saida["regex"] == ["Q195-L002"]
    assert saida["vazio"] is None


@pytestmark_node
def test_numero_sai_no_formato_do_operador_brasileiro():
    corpo = ("console.log(JSON.stringify([selFmt(1509,0),selFmt(41230.5,2),selFmt(-12.345,1),"
             "selFmt(0.5,2),selFmt(1/0,2)]));")
    assert no("selFmt", corpo=corpo) == ["1.509", "41.230,50", "-12,3", "0,50", "-"]


@pytestmark_node
def test_o_modulo_inteiro_e_javascript_valido():
    """Nao ha lint no caminho: erro de sintaxe so apareceria no navegador do operador."""
    montado = re.sub(r"__[A-Z][A-Z0-9_]*__", "0", pdf_to_map._editor_scripts())
    saida = subprocess.run(["node", "--check", "-"], input=montado,
                           capture_output=True, text=True, timeout=60)
    assert saida.returncode == 0, saida.stderr
