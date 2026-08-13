# Dominio: motor de conversao, editor embutido e pipeline de jobs

Levantamento READ-ONLY, 2026-08-12, contra o estado atual (pos-correcoes de tesselacao, ranking
por area, quadra generica e realocacao por gabarito). Toda afirmacao tem saida real colada.
Tamanhos (`wc -l`): `pdf_to_map.py` 2129 · `api.py` 1176 · `app_v1/worker.py` 136 ·
`app_v1/storage.py` 66 · `tools/qa_mapa.py` 268.

## arquitetura-real

`extract_lots` (`pdf_to_map.py:1155-1200`) nao e um motor: e um **torneio de ate 7 candidatos**
julgado pela metragem impressa na propria planta. Ordem de decisao:

1. `_lot_label_points` (`:1156`) — ancoras: texto casando `LOT_RE = \bL\s*\d{1,3}[A-Z]?`
   (`:1203`), aplicado com `search`, nao `fullmatch`.
2. `_printed_area_points` (`:1157`) — gabarito de area (`AREA_RE` `:1204`).
3. `_layered_lots` (`:1165`) — so as OCGs `LOTE`/`4_fnc_*` (`:109-111`); fecha a borda da prancha
   quando a geometria nao a ultrapassa (`:271-278`); snap 0.75 pt, escalando para
   `(1.25,1.75,2.25,2.75)` se cobrir <95% dos rotulos (`:299-303`); so devolve algo com >=2
   camadas e >=70% dos rotulos (`:306`).
4. `_extract_lots_global` (`:1166`) — polygoniza a malha inteira sem snap; abaixo de 75% dos
   rotulos refaz com `_looks_like_lot` + `centered <= 0.40` e chama `_repair_lot_gaps` (`:788-810`).
5. **Com camadas CAD**, mais 5 candidatos (`:1168-1183`): `_recover_layered_gaps(layered,global)`,
   `legacy_global` (curvas reduzidas a corda, `_legacy_segments` `:93-106`), o recover dele,
   `legacy_layered` (`curve_steps=8`) e o recover dele.
6. **Sem camadas**, um unico alternativo: `_anchor_guided_lots` (`:1185`) sobre
   `_geometry_only_segments` (descarta camadas de anotacao por marcador de nome, `:115-118`),
   uma face por rotulo varrendo snaps `(None,0.50..1.75)`, mais
   `_recover_unlabelled_neighbor_lots` (`:533-644`) por escala local.
7. `_rank_lot_candidate` (`:1067-1081`): `agreement*0.75 + coverage*0.25`, onde `agreement` e a
   fracao de lotes cuja razao `area_poligono/area_impressa` fica a <=5% da mediana
   (`_area_agreement` `:1022-1049`). Sem 20 amostras de area, cai para cobertura pura.
8. Empate tecnico de 1 p.p. (`:1193-1197`): dentro de `best_score - 0.01` vence a **maior
   cobertura**, nao o maior score.
9. `_complete_with_validated_lots` (`:1101-1152`) preenche rotulos orfaos com faces dos perdedores,
   so se a metragem impressa confirmar (tolerancia 8%).

Decisao real, instrumentando `_rank_lot_candidate`:

```
=== 251021LAG (sem camadas CAD) ===        rotulos=1182  camadas_cad=False
  #1 n=1385  concordancia=0.6278  cobertura=0.9349  score=0.7046   <- global
  #2 n=1182  concordancia=0.9609  cobertura=0.9983  score=0.9702   <- anchor-guided
VENCEDOR n=1182   tempo=70.0s

=== SETOR E (com camadas CAD) ===          rotulos=1509  camadas_cad=True
  #1 n=1603  concordancia=0.9042  cobertura=0.9980  score=0.9277
  #2 n=1496  concordancia=1.0000  cobertura=0.9914  score=0.9978
  #3 n=1508  concordancia=0.9947  cobertura=0.9993  score=0.9958
  #4 n=1570  concordancia=0.9054  cobertura=0.9973  score=0.9284
  #5 n=1508  concordancia=0.9947  cobertura=0.9993  score=0.9958
  #6 n=1496  concordancia=1.0000  cobertura=0.9914  score=0.9978
  #7 n=1508  concordancia=0.9947  cobertura=0.9993  score=0.9958
VENCEDOR n=1508   tempo=49.8s
```

Le-se a regra do empate funcionando (n=1496 com concordancia 1.0000 **perde** para n=1508 por
cobertura) e que 3 dos 7 candidatos do Setor E sao identicos — ~metade do tempo e desperdicio.

Metadados (`extract_lot_metadata` `:1399-1440`): nome e area vem do texto **dentro** do poligono;
quadra vem do rotulo mais proximo com raio `max(lado_tipico*12, 60)` (`:1406`);
`_quadra_label_items` (`:1227-1254`) detecta o padrao por prancha (prefixados `Q195`/`QD-14`/`E12`
tem prioridade; numero solto so vira quadra se nenhum prefixado existir e estiver no decil
superior de altura); `_refine_quadra_with_declared` (`:1334-1396`) reatribui lote cujo numero
excede o total declarado em `"QNNN - NN LOTES"`.

## fluxos-principais

**PDF -> HTML:** `convert()` `pdf_to_map.py:1689` → `extract_lots` `:1702` (vazio ⇒
`MapConversionError` distinguindo PDF rasterizado de PDF sem lote, `:1703-1710`) →
`extract_lot_metadata` `:1711` → `render_background` `:1712` + crop pelo bbox com pad 20
`:1713-1718` → projecao para pixel `:1724-1727` → `_fit_points_to_canvas` `:1728` →
`_auto_align_points` `:1732` (angulos -180/-90/0/90/180 ±8°, refino 0.5°, so aplica com ganho
1.35x — 1.05x se quadrante, `:1612-1615`) → `_encode_background` `:1760` (WebP, fallback JPEG) →
`build_html` `:1669-1686`, que e substituicao textual de `__W__ __H__ __IMG__ __DATA__ ...` no
`HTML_TEMPLATE` (`:1779-2110`). Nao ha engine de template.

**Worker RQ:** `app_v1/api.py:461` e `:487` → `enqueue_processing_job` `worker.py:127-136`. Sem
`REDIS_URL` (ou com `SYNC_PROCESSING=true`) roda **sincrono dentro do handler HTTP**
(`worker.py:129-131`); com Redis, `Queue("pdf-processing")`, `JOB_TIMEOUT_SECONDS` default 900.
Consumidor em `compose.yaml:55` (`rq worker pdf-processing`). `run_processing_job`
(`worker.py:53-124`) copia o PDF do storage privado para tempdir (`storage.py:57`), converte, cria
`ProjectVersion`, grava sob `projects/<id>/<version>/` (`storage.py:64`, com guarda de path
traversal em `storage_path` `:16-21`), extrai `Lot`s, valida, audita, commita.

**Converter sem banco:** `api.py:run_converter_job` em `BackgroundTasks`, servido por
`/converter/jobs/{id}/map` (`api.py:1090`) com `converter_editor_controls` (`api.py:969`) injetado.

**Salvamento:** o HTML expoe `window.getMapaPayload` (`pdf_to_map.py:1955`). Consomem-no:
`project_editor_response` (`api.py:298`, POST `/render` + `/api/projects/{id}/versions/html`),
`client_edit_injection` (`api.py:577`, POST `/api/shared-edit-proposals/{link}`) e o botao `#eddl`
do template (`pdf_to_map.py:2095`, POST `/render`). `/render` (`api.py:1164-1176`) so re-renderiza
`build_html`.

## estado-dos-testes

`cd .../mvp_pdf_para_mapa && python3 -m pytest -q`:

```
.....................                                                    [100%]
=============================== warnings summary ===============================
api.py:100  DeprecationWarning: on_event is deprecated, use lifespan event handlers instead.
fastapi/applications.py:4681  DeprecationWarning: on_event is deprecated ...
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
21 passed, 2 warnings in 5.38s
---EXITCODE:0---
```

**21 passed · 0 failed · 0 skipped · exit 0.** 603 linhas de teste em 8 arquivos.

Cobertura do dominio: **nenhuma**. Grep de cada funcao corrigida nesta sessao contra `tests/`
devolveu vazio para `_bezier_steps`, `_rank_lot_candidate`, `_normalize_quadra`,
`_quadra_label_items`, `_corner_count`, `_refine_quadra_with_declared`, `_area_agreement`,
`_complete_with_validated_lots`, `declared_lot_counts`, `extract_lots`, `extract_lot_metadata`,
`build_html`, `_layered_lots`, `_filled_lot_polygons`. Unico acerto: `convert` em
`tests/test_pdf_input_validation.py`, e so para checar mensagem de erro.
`tests/test_anchor_guided_geometry.py` (124 linhas, 6 testes) cobre so o fallback sem camadas com
retangulos sinteticos. **Zero teste exercita a decisao de `extract_lots` ou a nomenclatura de quadra.**

CI (`.github/workflows/deploy-vps.yml:32-37`) roda `pytest -q`; **nao roda `tools/qa_mapa.py` nem
compara com `tmp/qa/baseline.json`**.

### tools/qa_mapa.py nas 2 plantas (exit 0 nas duas)

| metrica | SETOR E (58.4 s) | LAG (60.8 s) |
|---|---|---|
| rotulos de lote na planta | 1373 | 1182 |
| lotes extraidos | 1508 | 1182 |
| lotes a mais que rotulos | 135 | 0 |
| cobertura dos rotulos (%) | **99.9** | **99.8** |
| lotes com area impressa | 1501 | 1175 |
| area correta ate 3% (%) | 87.8 | 91.1 |
| area correta ate 5% (%) | **99.5** | **96.1** |
| area errada acima de 20% (%) | 0.4 | 1.9 |
| lotes com quadra preenchida (%) | 99.5 | 100.0 |
| lotes com nome ambiguo | 87 | 96 |
| quadras com contagem declarada | 0 | 20 |
| quadras batendo com o declarado | — | 10/20 |

Grupos declarados no LAG: VILLA DA VINCI 128 · VILLA DI CAVALCANTI 206 · VILLA MONET 151 ·
VILLA PORTINARI 190.

Contra `tmp/qa/baseline.json`: LAG identico. Setor E melhorou cobertura (99.4→99.9) e **piorou**
`area_ate_5pct` (99.9→99.5) e `area_acima_20pct` (0.0→0.4) — pelas regras de `compare()`
(tolerancia 0.5) isso ja e **regressao formal** registrada e nao detectada por ninguem.

## qualidade-da-extracao

Diagnostico proprio sobre o vencedor de cada planta:

```
=== SETOR E ===
LOT_RE(search) aceita: 1509   ^L\d+$ (qa_mapa) aceita: 1373   diff: 136
so aceito pelo motor: ['L62A150.22m²','L58A150.22m²','L01A278.47m²','L24A167.05m²', ...]
lotes=1508 | sem texto de area: 4 | sem rotulo Lxxx: 0 | sem quadra: 7
chaves (nome,quadra) repetidas: 84 -> lotes envolvidos: 171
piores: [(('E1-L01A','E1'),3), (('E1-L02A','E1'),3), (('E14-L01A','E14'),3), (('L017',''),2)]
razao mediana=10.3387 n=1501  p50=0.0024 p90=0.0366 p99=0.0366 max=0.3682
acima de 10%: 7   acima de 20%: 6   acima de 50%: 0

=== LAG ===
LOT_RE(search) aceita: 1182   ^L\d+$ aceita: 1182   diff: 0
lotes=1182 | sem texto de area: 4 | sem rotulo Lxxx: 0 | sem quadra: 0
chaves (nome,quadra) repetidas: 94 -> lotes envolvidos: 190
piores: [(('Q198-L015','Q198'),3), (('Q234-L018','Q234'),3), (('Q234-L017','Q234'),2)]
razao mediana=6.1513 n=1175  p50=0.0070 p90=0.0290 p99=0.2821 max=79.0457
acima de 10%: 36   acima de 20%: 22   acima de 50%: 3
quadras fora do declarado (declarado->extraido):
  Q181 15->19 | Q182 29->31 | Q183 26->27 | Q184 23->25 | Q185 19->21
  Q186 8->10  | Q192 19->15 | Q196 20->19 | Q197 7->6   | Q233 5->6
```

Onde o motor **ainda erra hoje**:

1. **Nome ambiguo em ~15% dos lotes** — 171/1508 (Setor E) e 190/1182 (LAG) compartilham
   `(nome, quadra)` com outro lote; `Q198-L015` aparece 3x. Causa: `_nearest_quadra` (`:1310-1326`)
   e puramente euclidiana e `_refine_quadra_with_declared` (`:1334`) so age com `"QNNN - NN LOTES"`
   — no Setor E ha **zero** declaracoes, entao a correcao e inerte por construcao.
2. **Um poligono do LAG tem 79x a area impressa** (`max=79.0457` vs mediana 6.15): face de quadra
   inteira aceita como lote, por conter um rotulo e satisfazer `fill_ratio >= 0.55`. Nao ha
   checagem final de area no caminho anchor-guided — `_filter_lots_by_area_text` (`:1443-1476`)
   faz exatamente isso (banda 0.75x-1.25x da mediana) e **nao e chamada em lugar nenhum**.
3. **10 das 20 quadras do LAG divergem do gabarito impresso**, erro de -4 a +4 lotes.
   `_refine_quadra_with_declared` so move lote cujo *numero* excede o limite (`:1364`), nao lote em
   excesso com numero valido.
4. **`lotes a mais que rotulos = 135` e defeito de medicao, nao do motor.** As 136 diferencas sao
   textos como `L62A150.22m²` (rotulo+area no mesmo span) que `LOT_RE` reconhece e o `^L\d+$` de
   `tools/qa_mapa.py:35` rejeita. A metrica mais visivel do QA esta errada e desviaria a proxima correcao.
5. **Custo: 50-70 s de CPU por planta** so em `extract_lots`, com 3 dos 7 candidatos do Setor E
   produzindo resultado identico. Conversao completa gera **1.68 MB de HTML** para 1182 lotes.

Limiares arbitrarios e o custo de cada um:

| local | limiar | custo |
|---|---|---|
| `:433` | `fill_ratio < 0.55 or vertex_count > 32 or centered > 0.65` | porta unica do motor sem camadas; `0.55` deixa entrar a face de 79x; `centered > 0.65` derruba lote em L legitimo |
| `:360` | `_looks_like_lot`: `_corner_count <= 20 and fill_ratio >= 0.62` | so no caminho global; incoerente com o `0.55` acima |
| `:919` | `fill_ratio < 0.58 or vertex_count > 28` | 3o par para a mesma pergunta; usa `len(exterior.coords)` cru, nao `_corner_count` |
| `:589` | `fill_ratio < 0.55 or vertex_count > 32` | 4o par, tambem com contagem crua |
| `:299`/`:306` | `0.95` p/ ampliar snap, `0.70` de cobertura minima | camada CAD parcial cai fora em silencio |
| `:654` | `ceil(len(label_points)*0.94)` | anchor-guided desiste inteiro se cobrir 93%; sem ele o LAG voltaria ao global de 62.8% |
| `:788` | `max(40, int(len*0.75))` | gatilho do modo adaptativo global |
| `:632`/`:933`/`:970` | `0.50..1.80`, `0.72..1.32`, `0.68..1.32` | 3 bandas de plausibilidade de area vizinha sem origem comum |
| `:875` | `0.60 <= relative_ratio <= 1.45` | 5a banda |
| `:1194` | `best_score - 0.01` | escolheu n=1508 (0.9958) em vez de n=1496 (1.0000) no Setor E |
| `:111-114` | 4 escadas de snap (`0.75` / `0.75..2.75` / `0.50..1.25` / `None..1.75`) | uma por motor |
| `:485` | `(0.75,0.70,14°)` estrito / `(0.60,0.60,20°)` frouxo | perfil de lote local |
| `:131` | `CURVE_FLATNESS_TOL = 0.08` pt, `MAX_CURVE_STEPS = 64` | o unico com justificativa geometrica |
| `:1147` | tolerancia 0.08 no complemento | unico ponto que confere metragem antes de aceitar |

Sao **~20 limiares independentes para a mesma pergunta** ("isto e um lote?"), em 5 funcoes, nenhum com teste.

## editor

`HTML_TEMPLATE` (`pdf_to_map.py:1779-2110`, 65.623 caracteres) + 4 blocos de JS em f-string em
`api.py` (`:236` `PORTAL_DELIVERY_CONTROLS`, `:298` barra de salvar, `:577`
`client_edit_injection`, `:969` `converter_editor_controls`).

**Faz hoje:** SVG unico com fundo base64; pan/zoom por pointer events com pinch de 2 dedos
(`:2053-2057`); modo edicao com 5 ferramentas — selecionar (caixa de arrasto), mover, vertices,
desenhar, apagar (`:2048`); agrupar/desagrupar (`:2064`); status, paleta por status,
opacidade/espessura/modo de rotulo; rotacao e translacao da camada (`:2099-2108`); busca e filtro;
export CSV (`:2025`); inspector contextual (`:1997-2021`); atalhos V/M/P/D/G/Ctrl+Z/Y/A/Del/Esc
(`:2082`); lista virtualizada (`:1991-1995`); rotulos so no viewport (`:1967-1983`).

**Problemas concretos:**

1. **Undo custa 453 KB por passo.** `snapshot()` (`:2060`) faz `JSON.stringify(L)` inteiro e guarda
   24. Medido no LAG: payload `INIT` = 463.462 bytes / 1182 lotes ⇒ **historico cheio = 10.6 MB**,
   serializados a cada foco de input, pointerdown de cor e inicio de arrasto.
2. **Undo cobre so metade das acoes.** `snapshot` so serializa `L`; rotacao (`R`), translacao
   (`tx`,`ty`), opacidade, espessura e modo de rotulo ficam fora — girar a camada por engano e
   irreversivel. `restore()` (`:2061`) ainda limpa a selecao inteira.
3. **Nao ha salvamento nem autosave** — nenhum `localStorage` no template; fechar a aba perde tudo.
   O `#eddl` (`:2095`) faz `fetch('/render')` **relativo**: o HTML baixado, aberto em `file://`,
   so mostra "Nao foi possivel gerar o HTML."
4. **`renderList` definida duas vezes** (`:1990` e `:1994`); a primeira, nao virtualizada, e
   sobrescrita — 721 caracteres de codigo morto que aparenta ser o caminho ativo.
5. **Rotulos truncados em silencio:** `labelLimit=420` (auto) e `max=650` ("Sempre") em `:1963`/`:1973`.
   Com 1182 lotes o usuario pede "Sempre" e recebe 650, sem aviso.
6. **Acessibilidade:** so 10 botoes tem `aria-label` (`:1938`); `<svg id="map">` nao tem `role`, nao
   e focavel e **nao ha forma de selecionar ou mover lote por teclado**; o inspector (`:2002`) e
   reconstruido por `innerHTML` a cada selecao, destruindo o foco; `#canvasStatus` sem `aria-live`.
   Ponto bom: `focus-visible` no CSS (`:1815`).
7. **Mobile:** `#edit` vira barra rolavel com `scrollbar-width:none` (`:1832`) — a affordance some.
   Abaixo de 1180px os rotulos das ferramentas desaparecem (`:1831`), restando glifos Unicode.
   Desenhar poligono exige `click` preciso, sem snap nem lupa, e so conclui com Enter (`:2082`),
   inexistente no teclado virtual.
8. **Performance com 1200 poligonos:** `redraw()` (`:1985`) recria todos os `<polygon>` e e chamado
   por `restore/redo/deleteSelection/finishDraft/dupLot`; `deleteSelection` (`:2067`) reindexa o
   array inteiro invalidando todo `data-i`; `finishDragBox` (`:2052`) chama `lotCenter(i)` para os
   1182 lotes recomputando a media dos vertices (20.830 vertices; mediana 14/lote, max 195) em vez
   de usar o `cachedCenter` que existe ao lado (`:1959`); cada `updateLotStyle` faz
   `querySelector('polygon[data-i=...]')` dentro de loops de selecao.
9. **Viewer compartilhado mostra instrucao de edicao inexistente:** `shared_map_response`
   (`api.py:617`) esconde `#side,#sideToggle,#edit,#editor,#draft,#vertices` mas **nao**
   `#canvasStatus`, que fica com "Edicao: clique em Editar" sem botao Editar. As outras duas
   guardas (`api.py:627`, `:1086`) escondem — tres copias divergentes.
10. **XSS coberto por convencao, nao por ferramenta:** `esc()` (`:1941`) e aplicada na lista e no
    inspector e `labelText` usa `textContent`; basta um `innerHTML` novo sem `esc` para abrir o furo,
    e nao ha lint que detecte.

## dividas-e-riscos

1. **`app_v1/worker.py:27` nunca cria lote nenhum.** Le `info.get("data") or info.get("lots")`, mas
   `convert()` (`pdf_to_map.py:1770`) nao retorna nenhuma das duas. Provado executando o pipeline real:
   ```
   CHAVES DE convert(): ['alinhamento','estilo','imagem','lotes','metadados','modo','saida','status','tamanho_px']
   info["lotes"] = 1182 | info.get("data") = None | info.get("lots") = None
   LOTS CRIADOS PELO WORKER: 0
   validate_lots([]) = {"lot_count":0,"issue_count":0,"error_count":0,"warning_count":0,"issues":[]}
   ```
   A tabela `Lot` fica vazia em toda conversao, `validation_summary` assina laudo verde de zero
   lotes e `version.lot_count=1182` contradiz o banco.
2. **Processamento sincrono no handler HTTP sem `REDIS_URL`** (`worker.py:129-131`, chamado de
   `app_v1/api.py:461` e `:487`, funcoes `def` nao-async). Conversao mede 50-70 s so em
   `extract_lots`: um worker do servidor trava por mais de um minuto por upload.
3. **~2.000 linhas de JS em f-string sem lint, typecheck ou teste.**
   `git ls-files | grep -iE "eslint|prettier|ruff|mypy|pyproject"` devolve **so
   `frontend/package.json`** — a raiz nao tem ferramenta nenhuma. Nas f-strings de `api.py` toda
   chave de objeto JS exige `{{`/`}}` (`api.py:1016-1075`); um `{` esquecido vira erro de runtime.
4. **`tools/qa_mapa.py` desligado do CI** (`deploy-vps.yml:32-37` roda so `pytest -q`). O
   `--baseline` existe e nada o executa; o baseline ja registra a regressao de `area_acima_20pct`.
5. **`pdf_to_map.py` com 2129 linhas** mistura 5 motores de geometria, extracao de texto,
   rasterizacao, alinhamento por imagem, CLI e um app front-end inteiro; `extract_lots` depende de
   12 funcoes privadas com semantica sobreposta.
6. **`_filter_lots_by_area_text` (`:1443-1476`) e codigo morto** — a unica validacao final de area
   contra a mediana nao e chamada por ninguem.
7. **Trabalho duplicado no torneio** (Setor E: #3=#5=#7 e #2=#6): metade do tempo de conversao.
8. **`renderList` duplicada** (`pdf_to_map.py:1990` e `:1994`).
9. **`_normalize_quadra` (`:1220-1221`)** tem condicional inerte: os dois ramos produzem o mesmo
   caractere para todo prefixo aceito por `_QUADRA_PREFIX_RE`.
10. **Tres copias divergentes do `viewer_guard`** (`api.py:617`, `:627`, `:1086`).

## oportunidades-de-melhoria

Ordenado por impacto ÷ esforco. Nada implementado.

**Motor de geometria**

1. **Corrigir `app_v1/worker.py:27`** para ler a lista de lotes de fato. Hoje o unico artefato
   utilizavel e o HTML e o banco esta vazio. ~1 linha + 1 chave nova no retorno de `convert()`.
2. **Chamar `_filter_lots_by_area_text` no fim de `extract_lots` (`:1200`)** — a funcao ja existe e
   ja implementa a banda 0.75x-1.25x da mediana; e exatamente o que mata a face de 79x do LAG e os
   22 lotes acima de 20%.
3. **Ligar `tools/qa_mapa.py --baseline` no CI** (`deploy-vps.yml`, apos a linha 37) com os 2 PDFs
   de referencia. Sem isso nenhuma metrica deste relatorio e defendida.
4. **Alinhar `LOT_LABEL_RE` (`tools/qa_mapa.py:35`) com `LOT_RE` (`pdf_to_map.py:1203`)** — a
   metrica "lotes a mais que rotulos = 135" e falsa e induziria a remover 135 lotes corretos.
5. **Deduplicar candidatos antes de ranquear** (`:1161-1183`), comparando
   `(len(lots), round(area_total,2))`. Corta ~40% do tempo no Setor E sem mudar resultado.
6. **Unificar o predicado "isto e um lote"** numa funcao com constantes nomeadas, substituindo os 4
   pares divergentes de `:360`, `:433`, `:589`, `:919` e padronizando `_corner_count` (dois deles
   ainda usam `len(exterior.coords)` cru).
7. **Resolver ambiguidade de nome por unicidade, nao por distancia** em `extract_lot_metadata`
   (`:1426`): detectar `(nome,quadra)` repetido e reatribuir pelo 2o rotulo de quadra mais proximo.
   Ataca 171+190 lotes hoje inuteis para venda e funciona tambem no Setor E, sem gabarito declarado.
8. **Testes de unidade** para `_rank_lot_candidate`, `_area_agreement`, `_normalize_quadra`,
   `_quadra_label_items` e `_refine_quadra_with_declared` — funcoes puras, nao precisam de PDF.

**Editor / UX do mapa**

9. **Undo incremental**: trocar `snapshot()` (`:2060`) por diff (indices tocados + valor anterior).
   Elimina 453 KB/passo e os 10.6 MB de historico.
10. **Autosave em `localStorage`** com chave derivada do titulo, restaurado no boot (`:2109`).
11. **Incluir `R`, `tx`, `ty`, opacidade e espessura no historico de undo**, hoje irreversiveis.
12. **Remover a `renderList` morta** (`:1990`) e usar `cachedCenter` em `finishDragBox` (`:2052`) —
    duas mudancas mecanicas com ganho direto na selecao por caixa.
13. **Fallback do `#eddl`** (`:2095`): serializar o HTML no cliente se o POST `/render` falhar; hoje
    o arquivo baixado e um beco sem saida.
14. **Extrair `HTML_TEMPLATE` para `templates/mapa.html`** e carregar por `read_text()`. Habilita
    eslint/prettier no JS do editor sem mudar logica; pre-requisito de 9-13.
15. **Uma unica `viewer_guard(...)` em `api.py`** substituindo as tres copias (`:617`, `:627`,
    `:1086`), incluindo `#canvasStatus` nas tres.
16. **Acessibilidade minima:** `role="application"` + `tabindex` no `#map`, setas movendo a selecao
    (`nudgeSelection` ja existe, `:2046`), `aria-live` no `#canvasStatus`, preservar foco ao
    reconstruir o inspector.

## fora-de-escopo

Nao investigado: autenticacao, sessoes, permissoes e RBAC (`auth.py`, `app_v1/permissions.py`);
frontend React (`frontend/`); Docker/compose/CI alem de constatar que `pytest` roda e `qa_mapa` nao;
migrations Alembic; `database.py`/`models.py`; endpoints de compartilhamento e senha alem do ponto
em que injetam JS no mapa.

Nao verificado nesta passagem: `AQUIRAZ_SETOR D.pdf` (23 MB) e `SETOR h i um`; execucao real via
fila RQ com Redis (so o codigo foi lido — a medicao usou o caminho sincrono); comportamento do
editor em navegador real (nenhuma sessao de browser foi aberta — as afirmacoes vem da leitura
integral do template, nao de execucao); `_filled_lot_polygons` numa planta com lotes coloridos.

Nota: `git status` mostra ~40 arquivos como modificados. **Nao sao desta passagem** — `git diff
--stat` de `api.py` + `pdf_to_map.py` da 3015 insercoes para 3015 delecoes, churn puro de CRLF/LF
do ambiente Windows/OneDrive. O unico arquivo escrito aqui foi este.

---

## Veredicto: CONCERNS

O **motor de geometria esta bom e a melhora e mensuravel**: 99.9% e 99.8% de cobertura de rotulos,
99.5% e 96.1% dos lotes a menos de 5% da mediana impressa, e a escolha por concordancia de area
comprovadamente rejeita a malha global inflada do LAG (62.8%) em favor da anchor-guided (96.1%).
A suite passa limpa: 21/21, exit 0.

Nao e PASS por quatro razoes verificadas:

1. `app_v1/worker.py:27` grava **zero** linhas na tabela `Lot` em toda conversao, e `validate_lots`
   assina laudo verde sobre a lista vazia — provado executando o pipeline.
2. Nenhuma funcao corrigida nesta sessao tem teste, e a unica rede real
   (`tools/qa_mapa.py --baseline`) esta fora do CI — o baseline ja registra regressao silenciosa
   (`area_acima_20pct` 0.0→0.4 no Setor E).
3. ~15% dos lotes saem com nome duplicado (171 no Setor E, 190 no LAG) e 10 das 20 quadras do LAG
   divergem do gabarito impresso: o artefato ainda nao serve para venda sem revisao manual.
4. O editor nao persiste nada, o undo consome 453 KB por passo, e a metrica mais visivel do QA
   (`lotes a mais que rotulos`) esta medindo errado.

Nao e FAIL porque nada esta quebrado em runtime, o caminho PDF→HTML entrega artefato correto e
utilizavel, e os quatro pontos acima tem correcao localizada e barata.
