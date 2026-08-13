# NexoLote — proposta de reformulacao: 3 opcoes

Base factual: `docs/brownfield/entendimento.md` e os quatro relatorios de dominio. Os identificadores
`BRK-n` e `SEC-n` sao os de `entendimento.md#o-que-esta-quebrado-agora` e
`docs/brownfield/dominio-backend.md#seguranca`. As tres opcoes sao estrategias diferentes, nao
tamanhos diferentes da mesma coisa. Nenhuma foi iniciada.

---

## Opcao 1 — Cirurgia de producao **(RECOMENDADA)**

Corrigir exclusivamente o que esta quebrado ou expondo cliente, mais os tres portoes de entrega que
tornam essa propria correcao segura de aplicar. Nada de funcionalidade nova, nada de refatoracao
estrutural, nada de unificar API. O escopo e fechado por definicao: os 5 itens de
`o-que-esta-quebrado-agora`, os 3 logo abaixo da linha de corte, e o minimo de rede para que a
migration de BRK-1 nao seja aplicada as cegas em producao.

- **Esforco:** baixo. ~40 linhas de codigo (1 revision Alembic de ~40 linhas, 1 linha em `worker.py`,
  2 de escape, 1 de tenancy, 1 no `ClientsPage`) e ~25 linhas de YAML.
- **Risco:** baixo, **desde que na ordem certa** — a Fase 0 existe porque a Fase 1 embarca uma
  migration nova, e nenhuma migration jamais rodou contra Postgres antes de producao
  [Source: docs/brownfield/dominio-infra.md#pipeline-de-entrega].
- **Beneficio:** o produto volta a ser reimplantavel (hoje um ambiente novo nao autentica), para de
  expor mapa de cliente a quem tem um `job_id`, o banco volta a receber lotes e um deploy que falhe
  deixa de ser irreversivel. Cliente real deixa de estar em risco.
- **O que fica de fora:** site publico (preco, captura de lead, rodape, prova social), painel alem do
  guard de role e da troca de senha, todo o trabalho de editor (autosave, undo incremental, teclado),
  unificacao dos dois routers, `/converter` continua existindo como pipeline paralelo, observabilidade
  continua zero, dependencias Python sem lock, CRLF intocado.
- **Achados que resolve:** BRK-1 (`alembic/versions/20260715_0001_platform_rebuild.py` +
  `models.py:175,186`) · BRK-2 (`deploy-vps.yml:112,119,130-132` + `deploy/backup.sh`) · BRK-3
  (`api.py:1090`, `:1102`, `:970-971`) · BRK-4 (`app_v1/worker.py:27`) · BRK-5 (`ClientsPage.tsx:42`) ·
  SEC-4 (`app_v1/api.py:422`) · SEC-6 parcial (`api.py:337`, `:915`) · SEC-10 (`api.py:27`) · SEC-11
  (`auth.py:8`, `compose.yaml:34`) · guard de role (`App.tsx:34`, `AppShell.tsx:13`) · troca de senha
  (`api.py:371` sem UI) · aba Validacao hardcoded (`ProjectWorkspacePage.tsx:483-496` ->
  `app_v1/api.py:514`) · `qa_mapa.py --baseline` no CI (`deploy-vps.yml:32-37`).

**Por que ela vence as outras duas neste contexto.** O sistema tem clientes reais em
`https://map.eterhub.com.br` e um unico desenvolvedor: qualquer opcao que consuma meses antes do
primeiro ganho deixa BRK-1, BRK-3 e BRK-4 vivos durante todo esse periodo, e sao exatamente esses tres
que hoje impedem recuperacao de desastre, expoem mapa de cliente e esvaziam o banco. A Opcao 2 exige
tocar no ponto mais arriscado do repositorio — o fluxo do editor, que atravessa os dois routers
(`app_v1/api.py:125` -> `api.py:302` -> `api.py:1164`) — sem nenhum teste cobrindo essa travessia, e
faz isso *antes* de o ambiente sequer autenticar num deploy limpo. A Opcao 3 constroi superficie de
venda sobre uma base em que o painel exibe validacao hardcoded e a tabela `Lot` esta vazia: o produto
ficaria mais bonito e continuaria mentindo sobre a qualidade do mapa na tela que antecede a publicacao.
Ha ainda um argumento de oportunidade: a correcao de geometria acabou de ser feita e **nao existe
artefato que a defenda** — `qa_mapa.py` esta fora do CI e o baseline ja registra uma regressao
silenciosa [Source: docs/brownfield/dominio-motor-editor.md#estado-dos-testes] — de modo que qualquer
semana gasta em feature pode apaga-la sem ninguem notar. Por fim, a Opcao 1 nao fecha portas: ela e
pre-requisito das outras duas e termina num ponto de decisao real.

---

## Opcao 2 — Fundacao unica antes de qualquer coisa nova

Reduzir o sistema a uma unica fonte de verdade antes de escrever qualquer feature: mover
`/api/auth/*` e `/api/profile` para `app_v1`, apontar `mapUrl` para um editor v1 e aposentar
`api.py:423-561`, matar o `/converter` e o `/portal-legado`, unificar o vocabulario de `access_mode`,
extrair `HTML_TEMPLATE` para `templates/mapa.html` (habilita lint no JS do editor), mover o build para
o CI com registry (rollback por tag de imagem), congelar dependencias Python, normalizar CRLF e ligar
pytest + `tsc --noEmit` + `qa_mapa --baseline` + migration contra Postgres no CI.

- **Esforco:** alto. E o unico item de esforco alto da lista do backend
  [Source: docs/brownfield/dominio-backend.md#oportunidades-de-melhoria] (item 11), somado ao item de
  maior esforco da lista de infra (item 12, build no CI + registry).
- **Risco:** medio-alto. O fluxo do editor atravessa os dois routers e nao ha **nenhum** teste sobre essa
  travessia; a suite atual (21 testes, 603 linhas) monta o schema com `create_all` e nao cobre funcao
  nenhuma do motor. Refatorar com essa cobertura e trabalhar sem rede.
- **Beneficio:** cada correcao de seguranca passa a ser feita uma vez em vez de duas; os quatro
  vocabularios de `access_mode` viram um; o deploy ganha rollback; o build vira reproduzivel.
- **O que fica de fora:** tudo que o usuario ve — nenhum ganho perceptivel para cliente ou para venda
  durante toda a execucao. E, na ordem pura, BRK-1/BRK-3/BRK-4 seguem vivos enquanto a fundacao sobe.
- **Achados que resolve:** dois routers divergentes (`app_v1/api.py:353` vs `api.py:440`) · SEC-5
  (`api.py:71`, `app_v1/schemas.py:34,54,89`, `app_v1/api.py:98-104`) · cluster `/converter`
  (`api.py:806-1161`, incluindo BRK-3 por remocao) · SEC-7 (`api.py:83-85,526-527`) · SEC-8
  (`models.py:145-146`) · rollback e build reproduzivel (`deploy-vps.yml:119`, `requirements.txt`) ·
  CRLF (`.gitattributes`) · CI sem typecheck/lint/migration (`deploy-vps.yml:32-37`) · 3 copias de
  `viewer_guard` (`api.py:617,627,1086`) · JS em f-string sem ferramenta (`api.py:1016-1075`).

---

## Opcao 3 — Produto vendavel primeiro, divida assumida

Atacar as tres superficies que o usuario pediu, aceitando conscientemente a divida estrutural:
**site publico** (preco e captura de lead em `LandingPage.tsx:343-358`, rodape, prova social, Open
Graph, hero de 2,6 MB comprimido, screenshot real do produto); **painel** (guard de role, troca de
senha, gestao de share links, fila de jobs com retry/cancel, aba Validacao ligada ao backend, estados
de carregando e vazio); **editor** (autosave em `localStorage`, undo incremental, undo de
rotacao/translacao, `viewer_guard` unico, acesso por teclado).

- **Esforco:** alto — a de maior superficie: 3 frentes, dezenas de telas e ~2.000 linhas de JS em
  f-string sem lint no caminho do editor.
- **Risco:** alto, e comercial antes de tecnico. Sem BRK-1, uma VPS nova ou um restore nao autentica; sem
  BRK-4, o painel novo continua lendo uma tabela `Lot` vazia; sem BRK-3, o mapa que o site publico
  promete pode ser despublicado por terceiro; sem BRK-2, o ritmo maior de deploys aumenta a exposicao.
- **Beneficio:** e a unica opcao que gera material de venda. Hoje o site nao tem preco, formulario,
  rodape nem prova social, e o unico CTA e "Entrar"
  [Source: docs/brownfield/dominio-frontend.md#site-publico]; o editor nao persiste nada
  [Source: docs/brownfield/dominio-motor-editor.md#editor].
- **O que fica de fora:** os dois FAIL inteiros. Backend e infra permanecem como estao.
- **Achados que resolve:** site sem conversao (`LandingPage.tsx:343-358,393`,
  `frontend/index.html:8-9`, `hero-loteamento-aereo.png`) · painel sem acao (`AdminPage.tsx:34`,
  `app_v1/api.py:474,492,684-731`) · aba Validacao hardcoded (`ProjectWorkspacePage.tsx:483-496`) ·
  troca de senha (`InviteUserDialog.tsx:79` vs `api.py:371`) · guard de role (`App.tsx:34`) · undo de
  453 KB e ausencia de autosave (`pdf_to_map.py:2060,2095,2109`) · `viewer_guard` divergente
  (`api.py:617`) · foco invisivel e modais sem teclado (`DashboardPage.tsx:152`,
  `InviteUserDialog.tsx:58`).

---

## Sequencia de execucao sugerida — Opcao 1

**Fase 0 — Rede antes do primeiro deploy.** Nao entrega nada ao usuario; existe porque a Fase 1 embarca
uma migration. Backup do Postgres no script remoto, entre `deploy-vps.yml:111` e `:112`, abortando o
deploy se falhar; `services: postgres:16` + `alembic upgrade head` no job `validate`; health check
externo contra `https://map.eterhub.com.br/health` apos o check em loopback (~25 linhas de YAML).
Endurecer `restore.sh:9` com `-v ON_ERROR_STOP=1` e exercitar uma restauracao, registrando o RTO.

**Fase 1 — Voltar a ser reimplantavel (BRK-1).** Nova revision Alembic com `sessions` e `audit_events`
espelhando `models.py:174-195`; validar em banco limpo que `POST /api/auth/setup` e
`POST /api/auth/login` respondem 200; so entao aplicar em producao.

**Fase 2 — Fazer o motor chegar ao banco (BRK-4).** Corrigir `app_v1/worker.py:27` e a chave
correspondente no retorno de `convert()`; reprocessar uma planta de referencia e conferir que a tabela
`Lot` recebe linhas e que o `validation_summary` para de assinar laudo verde sobre lista vazia. Ligar
`tools/qa_mapa.py --baseline` no CI com os 2 PDFs de referencia, dando defesa automatica a geometria.

**Fase 3 — Fechar a superficie exposta (BRK-3 e vizinhos).** `Depends(current_user)` em `api.py:1090` e
`:1102`, com dono gravado no `job.json`; escape da interpolacao em `api.py:970-971`; inverter o
curto-circuito de `app_v1/api.py:422` (SEC-4); `docs_url=None` em `api.py:27` (SEC-10); default seguro
do cookie em `auth.py:8` e `compose.yaml:34` (SEC-11); rate limit em `api.py:337` e `:915` (SEC-6).

**Fase 4 — Destravar o operador (BRK-5 e os 3 itens abaixo do corte).** Capturar `event.currentTarget`
antes do `await` em `ClientsPage.tsx:42`; ler `platform_role` no `AppShell` e bloquear `/app/admin`
(`App.tsx:34`, `AppShell.tsx:13`); tela de troca de senha consumindo `api.py:371` (o formulario do
`portal.html` legado ja existe para portar); ligar a aba Validacao a
`POST /api/v1/project-versions/{id}/validate` (`app_v1/api.py:514`), para que ela pare de exibir
aprovacao hardcoded antes da publicacao.

**Fase 5 — Ponto de decisao.** Com o sistema reimplantavel, nao exposto e com deploy reversivel,
reavaliar Opcao 2 e Opcao 3 sobre uma base que ja nao sangra; a escolha entre elas passa a ser de
estrategia comercial, nao de contencao.

---

**A decisao e sua.** Este documento nao escolhe prioridade, prazo nem orcamento — nenhum dos tres foi
definido. Ele apresenta as tres estrategias com o custo e o que cada uma deixa para tras; a recomendacao
acima e uma leitura tecnica do risco atual, nao uma instrucao. Nada foi implementado.
