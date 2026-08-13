"""Garantias sobre o HTML do editor gerado por `pdf_to_map.build_html`.

O template e uma string gigante de HTML+CSS+JS sem lint nem typecheck: erro so
aparece no navegador do operador. Estes testes travam os pontos que ja quebraram
ou que custam caro em producao:

* o historico de desfazer nao pode voltar a serializar o mapa inteiro por passo;
* o rascunho automatico precisa continuar chaveado por mapa e comparado com a
  hora de geracao do HTML, senao ele sobrescreve o que o servidor mandou;
* o bloco do modo visualizador vive num lugar so (`viewer_guard_html`), porque
  as tres copias que existiam em api.py ja tinham divergido entre si.
"""
import re

import pdf_to_map


LOTES = [
    {"s": 0, "pts": "0,0 10,0 10,10 0,10", "nome": "L01", "quadra": "Q1", "area": "250m2"},
    {"s": 1, "pts": "20,0 30,0 30,10 20,10", "nome": "L02", "quadra": "Q1", "area": "250m2"},
]


def montar(**kwargs):
    return pdf_to_map.build_html("QUFB", 100, 80, LOTES, **kwargs)


# ---------------------------------------------------------------- template base

def test_template_nao_deixa_placeholder_para_tras():
    """Um `__NOME__` esquecido vira JS invalido e o editor abre em branco."""
    html = montar(title="Mapa de teste")
    assert not re.findall(r"__[A-Z][A-Z0-9_]*__", html)


def test_contrato_com_api_py_continua_de_pe():
    """api.py chama window.getMapaPayload() para salvar; sem isso nada e gravado."""
    assert "window.getMapaPayload=currentPayload" in montar()


# ------------------------------------------------------- historico incremental

def test_historico_nao_serializa_o_mapa_inteiro():
    html = montar()
    assert "hist.push(JSON.stringify(L))" not in html
    assert "L=JSON.parse(hist.pop())" not in html


def test_historico_guarda_operacoes_reversiveis():
    html = montar()
    for trecho in ("function pushHist(op)", "function beginPatch(indices,keys)",
                   "function sealPatch(op)", "function undoOp(op)", "function redoOp(op)"):
        assert trecho in html, trecho
    # patch (valor antes/depois por lote), insert (duplicar/desenhar) e remove (apagar)
    for tipo in ("'patch'", "'insert'", "'remove'"):
        assert tipo in html, tipo


def test_limite_de_24_niveis_de_desfazer():
    html = montar()
    assert "HIST_LIMIT=24" in html
    assert "if(hist.length>HIST_LIMIT)hist.shift()" in html


def test_desfazer_e_refazer_continuam_nos_mesmos_atalhos():
    html = montar()
    # Ctrl+Z desfaz, Ctrl+Shift+Z e Ctrl+Y refazem.
    assert "if(e.shiftKey)redo();else restore();" in html
    assert "&&e.key.toLowerCase()==='y'){e.preventDefault();redo()" in html


def test_nenhuma_operacao_ficou_sem_entrar_no_historico():
    """snapshot() era o unico registro do editor; nenhuma chamada pode ter sobrado."""
    html = montar()
    assert "snapshot()" not in html


# ---------------------------------------------------------------- rascunho local

def test_rascunho_usa_localstorage_com_chave_por_mapa():
    html = montar()
    assert "DRAFT_PREFIX='nexolote:rascunho:'" in html
    assert "draftKey=DRAFT_PREFIX+draftHash(location.pathname+'|'+mapTitle()" in html


def test_rascunho_tem_debounce_e_nao_grava_a_cada_movimento():
    html = montar()
    assert "DRAFT_DEBOUNCE=1200" in html
    assert "draftTimer=setTimeout(writeDraft,DRAFT_DEBOUNCE)" in html


def test_html_carrega_a_hora_de_geracao_para_comparar_com_o_rascunho():
    html = montar()
    marca = re.search(r"MAP_BUILT_AT=(\d+)", html)
    assert marca, "o editor precisa saber quando este HTML foi gerado"
    assert int(marca.group(1)) > 1_600_000_000_000  # epoch em milissegundos
    assert "if(!(data.savedAt>MAP_BUILT_AT)){clearDraft();return;}" in html


def test_rascunho_nunca_entra_sozinho():
    """A barra so oferece; quem restaura e o operador."""
    html = montar()
    assert 'id="draftBar"' in html
    assert 'id="draftRestore"' in html and 'id="draftDiscard"' in html
    assert "document.getElementById('draftRestore').onclick=function(){applyDraft(data);" in html
    # showDraftBar so aparece dentro de initDraft; nada chama applyDraft na carga.
    assert "initDraft();" in html
    assert html.count("applyDraft(") == 2  # a definicao e o clique em Restaurar


def test_rascunho_aguenta_localstorage_indisponivel_e_quota_estourada():
    html = montar()
    assert "function openDraftStore(){try{" in html and "catch(err){return null;}" in html
    assert "if(dropOtherDrafts()){try{draftStore.setItem(draftKey,body);return;}catch(err2){}}" in html
    assert "draftBlocked=true" in html


def test_rascunho_e_limpo_depois_de_salvar_de_verdade():
    html = montar()
    assert "a.click();clearDraft();hideDraftBar();" in html
    assert "document.addEventListener('nexolote:saved',clearDraft)" in html
    assert "window.nexoloteDraft={clear:clearDraft" in html


def test_visualizador_nao_grava_rascunho():
    """No link compartilhado nao ha edicao: nem barra, nem escrita no navegador."""
    html = montar()
    assert "function viewerMode(){if(document.getElementById('shared-viewer'))return true;" in html
    assert "if(viewerMode())return;" in html


# ------------------------------------------------------------------- teclado

def test_atalhos_de_status_1_2_3():
    html = montar()
    assert "(e.key==='1'||e.key==='2'||e.key==='3')){e.preventDefault();chooseStatus(+e.key-1);" in html
    assert "function chooseStatus(s)" in html


def test_atalhos_antigos_continuam_valendo():
    html = montar()
    for trecho in ("if(key==='v')setTool('select')", "if(key==='m')setTool('move')",
                   "if(key==='p')setTool('vertex')", "if(key==='d')setTool('draw')",
                   "if(key==='g'&&!e.shiftKey)groupSelected()",
                   "if(key==='g'&&e.shiftKey)ungroupSelected()",
                   "if(e.key==='Enter'&&tool==='draw')finishDraft()"):
        assert trecho in html, trecho


def test_escape_sai_do_modo_e_limpa_selecao():
    html = montar()
    assert "if(e.key==='Escape'){draft=[];redrawDraft();clearDragBox();if(tool!=='select')setTool('select');if(selected.size){selected.clear();" in html


def test_delete_apaga_lote_e_ponto_do_desenho():
    html = montar()
    assert "&&tool==='draw'&&draft.length){e.preventDefault();draft.pop();redrawDraft();return;}" in html
    assert "&&selected.size)deleteSelection();" in html


def test_atalho_nao_dispara_dentro_de_campo_de_texto():
    html = montar()
    assert "/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)||!!(e.target&&e.target.isContentEditable)" in html


# ------------------------------------------------------------- acessibilidade

def test_botao_so_de_icone_tem_aria_label():
    html = montar()
    for identificador in ("zin", "zout", "zr", "edundo", "edredo", "lrm", "lrp",
                          "lmleft", "lmright", "lmup", "lmdown", "draftRestore", "draftDiscard"):
        assert "['%s'," % identificador in html, identificador
    # os tres botoes de status sao pontinhos coloridos sem texto
    assert "b.setAttribute('aria-label','Marcar como '+NAMES[s].toLowerCase()" in html
    assert 'aria-label="Fechar inspetor"' in html


def test_foco_pelo_teclado_continua_visivel():
    html = montar()
    assert "button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid #36d889" in html
    assert "outline:none" not in html and "outline:0" not in html


# --------------------------------------------------------------- viewer guard

# As tres copias que api.py mantinha (linhas ~655, ~665 e ~1169). Nenhuma pode
# esconder algo que a funcao unica deixe de esconder.
COPIAS_ANTIGAS_DE_API = (
    ("side", "sideToggle", "edit", "editor", "draft", "vertices"),
    ("side", "sideToggle", "edit", "editor", "draft", "vertices", "canvasStatus", "lrot"),
    ("side", "sideToggle", "edit", "editor", "draft", "vertices", "canvasStatus"),
)


def test_viewer_guard_cobre_as_tres_copias_de_api_py():
    bloco = pdf_to_map.viewer_guard_html()
    for copia in COPIAS_ANTIGAS_DE_API:
        for identificador in copia:
            assert "#%s" % identificador in bloco, identificador


def test_viewer_guard_desliga_a_edicao_e_marca_o_app():
    bloco = pdf_to_map.viewer_guard_html()
    assert bloco.startswith('<style id="shared-viewer">')
    assert "{display:none!important}" in bloco
    assert "#lots{pointer-events:none!important}" in bloco
    assert ".lot{cursor:default!important}" in bloco
    assert "app.classList.add('shared-viewer')" in bloco
    assert bloco.endswith("</script>")


def test_viewer_guard_esconde_tambem_a_barra_de_rascunho():
    """A barra de restaurar rascunho e do operador; o cliente nao pode ver."""
    assert "#draftBar" in pdf_to_map.viewer_guard_html()


def test_viewer_guard_sem_rotulo_nao_mexe_no_contador():
    assert "getElementById('cnt')" not in pdf_to_map.viewer_guard_html()


def test_viewer_guard_com_rotulo_troca_o_contador():
    bloco = pdf_to_map.viewer_guard_html(count_label="demonstracao")
    assert 'count.textContent="demonstracao"' in bloco


def test_viewer_guard_escapa_o_rotulo():
    """O rotulo entra dentro de <script>; aspas soltas quebrariam a pagina."""
    bloco = pdf_to_map.viewer_guard_html(count_label='pre"visualizacao')
    assert 'count.textContent="pre\\"visualizacao"' in bloco


def test_viewer_guard_aceita_lista_propria_de_ids():
    bloco = pdf_to_map.viewer_guard_html(hidden_ids=("edit", "editor"))
    assert '<style id="shared-viewer">#edit,#editor{display:none!important}' in bloco


def test_ids_escondidos_existem_no_template():
    """Id renomeado no template sem atualizar a lista deixa controle a mostra."""
    html = montar()
    for identificador in pdf_to_map.VIEWER_GUARD_HIDDEN_IDS:
        assert 'id="%s"' % identificador in html, identificador
