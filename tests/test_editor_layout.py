"""Contrato entre o layout (editor.html + editor.css) e o JS do editor.

O HTML do editor nao passa por lint nem por typecheck: um id renomeado no
esqueleto vira ferramenta morta, sem erro nenhum no console - o operador so
descobre quando clica e nada acontece. Estes testes travam os dois lados:

* todo id que `editor.js` ou um `editor-*.js` procura precisa existir no HTML
  (ou ser montado pelo proprio JS, como os paineis Transformar e Selecionar);
* toda regra de CSS que aponta para um `#id` precisa achar esse id em algum
  lugar - regra orfa e sinal de renomeacao pela metade;
* os botoes que nenhum modulo liga sozinho (caneta, dividir, unir, encaixar,
  ima, laco, regua, repetir) precisam continuar chamando as funcoes globais,
  senao viram enfeite.
"""
import os
import re

import pytest


RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDITOR = os.path.join(RAIZ, "templates", "editor")
HTML = open(os.path.join(EDITOR, "editor.html"), encoding="utf-8").read()
CSS = open(os.path.join(EDITOR, "editor.css"), encoding="utf-8").read()
MODULOS = sorted(nome for nome in os.listdir(EDITOR) if nome.endswith(".js"))
FONTES = {nome: open(os.path.join(EDITOR, nome), encoding="utf-8").read() for nome in MODULOS}

# id que so aparece noutro modo: o guard do visualizador injeta este <style>.
FORA_DO_ESQUELETO = {"shared-viewer"}
# ids de quem hospeda o editor (api.py prega a barra de salvar por cima).
DO_HOSPEDEIRO = {"project-save-bar"}


def ids_no_html():
    return set(re.findall(r"""\bid=["']([^"']+)["']""", HTML))


def ids_consumidos():
    """`getElementById('x')` e o botao declarado por cada ferramenta registrada."""
    achados = {}
    for nome, fonte in FONTES.items():
        for ident in re.findall(r"""getElementById\(['"]([^'"]+)['"]\)""", fonte):
            achados.setdefault(ident, set()).add(nome)
        for ident in re.findall(r"""button:\s*['"]([^'"]+)['"]""", fonte):
            achados.setdefault(ident, set()).add(nome)
    return achados


def ids_criados_pelo_js():
    """O que nasce em tempo de execucao: innerHTML, node.id=... e os helpers."""
    achados = set()
    for fonte in FONTES.values():
        achados |= set(re.findall(r"""id=["']([A-Za-z][\w-]*)["']""", fonte))
        achados |= set(re.findall(r"""\.id\s*=\s*['"]([\w-]+)['"]""", fonte))
        achados |= set(re.findall(r"""\b(?:selBtn|trBtn|trField|selField)\(\s*['"]([\w-]+)['"]""",
                                  fonte))
    return achados


def seletores_do_css():
    limpo = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    return re.findall(r"(?:^|[{}])([^{}]*)\{", limpo, flags=re.M)


# ------------------------------------------------------------------ inventario

def test_todo_id_procurado_pelo_js_existe():
    presentes = ids_no_html() | ids_criados_pelo_js() | FORA_DO_ESQUELETO
    faltando = {ident: sorted(donos) for ident, donos in ids_consumidos().items()
                if ident not in presentes}
    assert not faltando, "id sumiu do esqueleto (ferramenta morta): %s" % faltando


def test_o_esqueleto_tem_os_ids_de_sempre():
    """Lista explicita: pega ate o caso de alguem passar a criar o id por JS."""
    presentes = ids_no_html()
    essenciais = [
        # moldura
        "app", "topbar", "canvas", "map", "side", "inspector", "editor",
        "sideScrim", "sideToggle", "canvasStatus",
        # camadas do SVG
        "lotsrot", "lots", "labels", "draft", "vertices", "ui",
        # barra de ferramentas e acoes
        "edit", "edt", "edtools", "edsel", "edmove", "edvertex", "eddraw",
        "edpen", "edcut", "eddel", "edgroup", "edungroup", "edundo", "edredo",
        "eddl", "selectionSummary",
        # lista de lotes
        "panelLots", "lotSearch", "lotList", "listCount", "selectVisible",
        "csvBtn", "clearSel",
        # inspetor: mapa, visual e camada
        "panelVisual", "panelAlign", "n0", "n1", "n2", "opacityCtrl", "opacityVal",
        "strokeCtrl", "strokeVal", "labelMode", "lrot", "lr", "lrm", "lrp", "lr0",
        "lrval", "lmove", "lmleft", "lmright", "lmup", "lmdown", "xyval",
        # topo, avisos e legado
        "title", "cnt", "zoom", "zin", "zout", "zr", "toast", "draftBar",
        "draftBarText", "draftRestore", "draftDiscard", "info", "ih", "is", "legend",
    ]
    faltando = [ident for ident in essenciais if ident not in presentes]
    assert not faltando, "id essencial fora do editor.html: %s" % faltando


def test_nenhum_id_repetido_no_esqueleto():
    """getElementById devolve o primeiro: id repetido mata o segundo em silencio."""
    todos = re.findall(r"""\bid=["']([^"']+)["']""", HTML)
    repetidos = sorted({ident for ident in todos if todos.count(ident) > 1})
    assert not repetidos, "id repetido no editor.html: %s" % repetidos


def test_esqueleto_nao_briga_com_os_ids_montados_por_js():
    """Os paineis T e F nascem por JS; repetir os ids deles aqui mataria os dois."""
    for ident in ("edTransformPanel", "edSelectPanel", "edlasso", "edruler", "edarray"):
        assert ('id="%s"' % ident) not in HTML, ident


# ------------------------------------------------------------------------ css

def test_css_nao_tem_regra_orfa():
    conhecidos = ids_no_html() | ids_criados_pelo_js() | FORA_DO_ESQUELETO | DO_HOSPEDEIRO
    orfas = sorted({ident for seletor in seletores_do_css()
                    for ident in re.findall(r"#([A-Za-z][\w-]*)", seletor)
                    if ident not in conhecidos})
    assert not orfas, "regra de CSS aponta para id que nao existe: %s" % orfas


def test_css_reserva_lugar_para_os_paineis_montados_por_js():
    """Eles se penduram em #app; o layout precisa saber onde eles caem."""
    assert 'id="app"' in HTML
    assert '#app>section[role="group"]' in CSS or '#app.side-closed>section[role="group"]' in CSS


def test_modo_visualizador_esconde_o_inspetor_novo():
    """viewer_guard_html() nao conhece #inspector: quem esconde e esta folha."""
    assert "#app.shared-viewer #inspector{display:none}" in CSS


def test_foco_visivel_continua_ligado():
    assert "button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid #36d889" in CSS
    assert "outline:none" not in CSS and "outline:0" not in CSS


# --------------------------------------------------------------- ferramentas

FERRAMENTAS = [
    ("edsel", "V"), ("edmove", "M"), ("edvertex", "P"), ("eddraw", "D"),
    ("edpen", "B"), ("edcut", "C"), ("tbMerge", "U"), ("tbLasso", "L"),
    ("tbRuler", "K"), ("tbArray", "R"), ("tbFit", "E"), ("tbSnap", "S"),
]


def botao(ident):
    achado = re.search(r"<button[^>]*\bid=\"%s\"[^>]*>" % re.escape(ident), HTML)
    assert achado, "botao %s sumiu da barra" % ident
    return achado.group(0)


@pytest.mark.parametrize("ident,tecla", FERRAMENTAS)
def test_barra_tem_as_doze_ferramentas_com_rotulo_e_atalho(ident, tecla):
    tag = botao(ident)
    assert "aria-label=" in tag, ident
    dica = re.search(r'data-tip="([^"]+)"', tag)
    assert dica, "%s sem tooltip" % ident
    assert dica.group(1).rstrip().endswith(tecla), (ident, dica.group(1))


# Estes cinco ninguem liga: editor.js so cuida do clique de edsel/edmove/
# edvertex/eddraw/eddel, e os modulos so ligam o que eles mesmos montam.
SEM_DONO = ["edpen", "edcut", "tbMerge", "tbLasso", "tbRuler", "tbArray", "tbFit", "tbSnap"]


@pytest.mark.parametrize("ident", SEM_DONO)
def test_ferramenta_sem_dono_no_js_continua_ligada_pelo_html(ident):
    assert "onclick=" in botao(ident), (
        "%s ficaria sem acao: nenhum editor-*.js liga este botao" % ident)


def test_ferramentas_do_nucleo_nao_ganharam_onclick_duplicado():
    """editor.js ja liga estas cinco; um onclick aqui dispararia duas vezes."""
    for ident in ("edsel", "edmove", "edvertex", "eddraw", "eddel", "edundo",
                  "edredo", "edgroup", "edungroup", "eddl", "zin", "zout", "zr"):
        assert "onclick=" not in botao(ident), ident


def test_botao_so_de_icone_tem_nome_acessivel():
    """Sem texto e sem aria-label o leitor de tela anuncia 'botao' e mais nada."""
    mudos = []
    for tag, miolo in re.findall(r"(<button[^>]*>)(.*?)</button>", HTML, flags=re.S):
        texto = re.sub(r"<svg.*?</svg>", "", miolo, flags=re.S)
        texto = re.sub(r"<[^>]+>", "", texto).strip()
        if texto or "aria-label=" in tag:
            continue
        # os tres pontinhos de status recebem rotulo de editor.js, com o nome
        # do status e a tecla, para nao repetir a lista NAMES aqui.
        if 'class="st' in tag:
            continue
        mudos.append(tag)
    assert not mudos, mudos


def test_inspetor_muda_com_a_selecao():
    """0 lotes mostra o mapa, 1 ou mais mostra #editor, 2 ou mais abre a massa.
    O sinal vem de counts(): #edmove so liga com selecao e #edgroup com duas."""
    assert "#app:has(#edmove:not(:disabled)) #inspMap{display:none}" in CSS
    assert "#app:has(#edgroup:not(:disabled)) #inspBulk{display:block}" in CSS
    assert "#editor.show{display:block}" in CSS


def test_barra_horizontal_no_celular_e_gaveta_no_inspetor():
    corte = CSS[CSS.index("@media(max-width:760px)"):]
    assert "#edtools{display:flex;position:fixed" in corte
    assert "flex-direction:row" in corte
    assert "#inspector{left:0;right:0;top:auto" in corte


def test_esqueleto_nao_traz_bloco_de_script():
    """A costura de pdf_to_map.py entrega um <script> so, montado no fim."""
    assert "<script" not in HTML and "</script" not in HTML
