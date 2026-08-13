# NexoLote — entendimento consolidado (READ-ONLY)

Consolidacao das quatro passagens de arqueologia de 2026-08-12. Nada foi reexecutado: cada afirmacao e
citada do relatorio de origem, preservando a ancora `arquivo:linha` original. Onde dois relatorios
divergem, a divergencia esta registrada em vez de resolvida.

| Relatorio de origem | Linhas | Escopo | Veredicto |
|---|---|---|---|
| `docs/brownfield/dominio-backend.md` | 333 | HTTP, auth, multi-tenant, dados, migrations | **FAIL** |
| `docs/brownfield/dominio-infra.md` | 275 | compose, CI/CD, backup, TLS, observabilidade | **FAIL** |
| `docs/brownfield/dominio-motor-editor.md` | 376 | motor PDF->mapa, editor embutido, fila de jobs | **CONCERNS** |
| `docs/brownfield/dominio-frontend.md` | 317 | SPA React, site publico, painel do administrador | **CONCERNS** |

Indice: [veredicto-consolidado](#veredicto-consolidado) ·
[o-que-esta-quebrado-agora](#o-que-esta-quebrado-agora) · [arquitetura-real](#arquitetura-real) ·
[mapa-de-dividas](#mapa-de-dividas) ·
[o-que-ja-foi-corrigido-nesta-sessao](#o-que-ja-foi-corrigido-nesta-sessao) ·
[contradicoes-entre-relatorios](#contradicoes-entre-relatorios) · [fora-de-escopo](#fora-de-escopo)

---

## veredicto-consolidado

| Dominio | Veredicto | Razao em uma frase |
|---|---|---|
| Backend | **FAIL** | Depois de um `alembic upgrade head` bem-sucedido, `/api/auth/setup` e `/api/auth/login` retornam 500 (`no such table: audit_events`) — nenhum ambiente novo autentica. |
| Infra / entrega | **FAIL** | O deploy apaga a release anterior antes de construir a nova, roda migration no boot e nao tira backup nem tem rollback: uma migration defeituosa e perda permanente de dado de cliente. |
| Motor + editor | **CONCERNS** | O motor entrega 99,8-99,9% de cobertura com area correta, mas `app_v1/worker.py:27` grava zero linhas na tabela `Lot` em toda conversao e nenhuma funcao corrigida tem teste. |
| Frontend | **CONCERNS** | Build passa e a arquitetura e limpa, mas criar cliente quebra em producao, `/app/admin` nao tem guard de role e a aba "Validacao" exibe aprovacao hardcoded. |

**Leitura do estado real.** O NexoLote esta em producao e funciona *para o caminho que ja esta de pe*:
um mapa publicado continua sendo servido, e o HTML gerado pelo motor carrega geometria comprovadamente
boa. O que nao funciona e tudo que envolve *comecar de novo* ou *confiar no que o sistema diz*: ambiente
novo nao autentica (SEC-1), deploy que falhe deixa producao quebrada sem caminho de volta (infra, risco
1), a tabela de lotes fica vazia em toda conversao enquanto o `validation_summary` assina laudo verde
(motor, divida 1), e a aba de validacao do painel mostra resultado fixo em codigo antes da publicacao
(frontend, item (b)7). Somado a isso, tres rotas anonimas do `/converter` dao a qualquer pessoa com o
`job_id` controle de publicacao, senha e execucao de script na origem da aplicacao. Os dois FAIL nao sao
acumulo de itens menores: cada um e uma cadeia curta e ja reproduzida que termina em cliente sem acesso
ou dado perdido. O que atenua o quadro e o custo da saida — os cinco itens quebrados somam cerca de 40
linhas de codigo e 25 de YAML, nao uma reescrita.

---

## o-que-esta-quebrado-agora

Criterio: **comprovadamente quebrado em producao hoje, ou que quebraria num deploy limpo.** Ordenado por
gravidade.

### BRK-1 — Nenhum ambiente novo autentica (Backend, critico)

- **Sintoma:** VPS nova, restore ou staging sobem com o site respondendo, mas 100% das tentativas de
  criar a primeira conta ou logar retornam 500. Ninguem entra.
- **Causa raiz:** a migration cria 10 tabelas e `models.py` define 12; faltam `sessions`
  (`models.py:175`) e `audit_events` (`models.py:186`), as duas que o login escreve. `Dockerfile:34`
  roda `alembic upgrade head` antes do uvicorn, e `api.py:100-103` so cria tabelas com
  `AUTO_CREATE_TABLES=true` (default `false`, ausente do `.env.example`).
- **Comprovacao:** `alembic upgrade head` em banco novo -> exit 0 e 11 tabelas; `POST /api/auth/setup`
  -> 500 `no such table: audit_events`. O pytest verde nao pega: monta o schema com `create_all`.
- [Source: docs/brownfield/dominio-backend.md#seguranca] (SEC-1) +
  [Source: docs/brownfield/dominio-backend.md#modelo-de-dados]

### BRK-2 — Deploy irreversivel sobre banco sem backup (Infra, critico)

- **Sintoma:** deploy que falhe no health gate deixa o site fora do ar ate alguem entrar por SSH;
  migration defeituosa apaga dado de cliente sem ponto de restauracao.
- **Causa raiz:** `deploy-vps.yml:112` faz `rsync -a --delete` **antes** do build; `Dockerfile:34` e
  `compose.yaml:55` rodam `alembic upgrade head` no boot dos dois containers ao mesmo tempo, sem lock;
  `deploy-vps.yml:130-132` e o caminho de falha completo (imprime logs e `exit 1`, sem rollback); nenhum
  backup e invocado — `git grep 'backup.sh'` so acha `docs/PLATFORM_REBUILD.md:20` e `:42`.
- **Comprovacao:** leitura integral do workflow (133 linhas) + `git grep`; `docs/PLATFORM_REBUILD.md:42`
  admite a rotina de backup como pendencia; nenhuma migration jamais rodou contra Postgres antes de
  producao (CI usa `sqlite:///:memory:` em 6 pontos de `tests/`).
- [Source: docs/brownfield/dominio-infra.md#pipeline-de-entrega] +
  [Source: docs/brownfield/dominio-infra.md#backup-e-recuperacao]

### BRK-3 — `/converter` anonimo: qualquer um publica, troca senha e injeta script (Backend, critico)

- **Sintoma:** quem tiver o `job_id` — que trafega na URL do editor, em logs de proxy, no historico e no
  `Referer` — publica, despublica, liga `allow_edit` e troca a senha do mapa de outro cliente; e um link
  forjado executa JavaScript na origem da aplicacao.
- **Causa raiz:** `api.py:1102` (`publish_converter_job`) e `api.py:1090` (entrega o editor completo)
  nao tem `Depends(current_user)`; `api.py:970-971` interpola `json.dumps(...)` dentro de `<script>`
  (`api.py:1017`) e `json.dumps` nao escapa `</script>`; `api.py:1096-1097` persiste o `project_id` da
  query string no `job.json`.
- **Comprovacao:** `POST /converter/jobs/{id}/publish` sem cookie -> 200 com
  `"published":true,"allow_edit":true`; XSS reproduzido ponta a ponta com
  `GET /converter/jobs/{id}/map?project_id=</script><script>fetch('/api/auth/me')</script>` -> 200.
- [Source: docs/brownfield/dominio-backend.md#seguranca] (SEC-2, SEC-3)

### BRK-4 — Toda conversao grava zero lotes no banco (Motor, alto)

- **Sintoma:** o mapa HTML sai correto, mas o banco nao recebe lote nenhum: o relatorio de validacao
  aprova lista vazia, `version.lot_count` diz 1182 e a tabela `Lot` diz 0. Tudo que le do banco (status
  por lote, `PATCH /lots`, `/lots/batch`, contagens) opera sobre nada.
- **Causa raiz:** `app_v1/worker.py:27` le `info.get("data") or info.get("lots")`, e `convert()`
  (`pdf_to_map.py:1770`) nao retorna nenhuma das duas chaves — retorna `lotes`.
- **Comprovacao:** pipeline real executado — `info["lotes"] = 1182`, `info.get("data") = None`,
  `LOTS CRIADOS PELO WORKER: 0`, `validate_lots([]) = {"lot_count":0,...}`. Linha reconfirmada nesta
  consolidacao: `raw_lots = info.get("data") or info.get("lots") or []`.
- **Efeito composto:** duas garantias de qualidade mentem ao mesmo tempo — o `validation_summary` (laudo
  verde sobre lista vazia) e os 4 cartoes hardcoded da aba Validacao (`ProjectWorkspacePage.tsx:483-496`).
- [Source: docs/brownfield/dominio-motor-editor.md#dividas-e-riscos] +
  [Source: docs/brownfield/dominio-frontend.md#painel-do-administrador]

### BRK-5 — Criar cliente quebra em producao (Frontend, alto)

- **Sintoma:** o operador cria um cliente, recebe erro vermelho e a tela nao atualiza — mas o cliente
  **foi criado**. O caminho natural e tentar de novo e duplicar.
- **Causa raiz:** `ClientsPage.tsx:42` chama `event.currentTarget.reset()` **depois** do
  `await apiRequest` da linha 35; React 19 anula `currentTarget` ao fim do dispatch, entao vira
  `TypeError` capturado pelo `catch` da linha 44, e o `reload()` da linha 43 nunca roda.
- **Comprovacao:** leitura do proprio React (`react-dom-client.development.js:19114-19120`). So nao
  explode em modo demo, onde nao ha `await` antes da linha 42.
- [Source: docs/brownfield/dominio-frontend.md#dividas-e-riscos] (item 1)

### Logo abaixo da linha de corte

Confirmados por codigo, mas dependentes de uma condicao que nenhum relatorio verificou em producao:

- **SEC-4 — vazamento de PDF entre clientes.** `app_v1/api.py:422` curto-circuita a checagem de tenancy
  quando `asset.organization_id` e `NULL`, e `models.py:87` gera nulos sozinho (`ondelete="SET NULL"`).
  Com asset orfao, `GET /api/v1/files/{id}` sem membership -> 200 com o PDF. Depende de alguma
  organizacao ja ter sido apagada. [Source: docs/brownfield/dominio-backend.md#seguranca]
- **`/app/admin` sem guard de role.** Qualquer sessao autenticada, inclusive `client_member` convidado,
  ve o link e a saude da infra (host do banco, `storage_root`) — `App.tsx:34`, `AppShell.tsx:13`.
  [Source: docs/brownfield/dominio-frontend.md#dividas-e-riscos]
- **Convidado nao consegue trocar a senha.** `InviteUserDialog.tsx:79` promete a troca; nao ha UI no
  React (`grep "auth/password" frontend/src` vazio) apesar de `api.py:371` existir.
  [Source: docs/brownfield/dominio-frontend.md#painel-do-administrador]

---

## arquitetura-real

**Borda e processos.** Nginx versionado escuta **so** `:80`
(`deploy/nginx/mapa-disponibilidade.conf:2-3,22-23`) e faz `proxy_pass http://127.0.0.1:8000` (`:9`);
producao serve `https://map.eterhub.com.br` (`deploy-vps.yml:58`), logo existe config de TLS **fora do
versionamento**. Quatro containers (`postgres:16-alpine`, `redis:7-alpine`, app, worker); app e worker
compartilham a **mesma imagem** e o **mesmo volume** `/data`; porta 7860 publicada so no loopback como
8000 (`compose.yaml:45`); healthcheck do worker desativado (`compose.yaml:53-54`).
[Source: docs/brownfield/dominio-infra.md#topologia-real]

**HTTP — dois routers vivos no mesmo processo FastAPI** (`api.py:27-28`): o monolito legado `api.py` (43
rotas: auth, paginas SPA, portal legado, editor de projeto, mapas compartilhados e o pipeline anonimo
`/converter` + `/render`) e a API v1 `app_v1/api.py` (`APIRouter(prefix="/api/v1")` em `:60`, 34 rotas).
Nao ha camada de servico: rota = handler + ORM inline. **Os dois estao em uso** — o SPA chama
`/api/v1/*` (21 ocorrencias) **e** `/api/auth/*` e `/api/profile`; e o v1 devolve
`mapUrl = /projects/{id}/editor` (`app_v1/api.py:125`), rota do legado (`api.py:302`), cujo HTML chama
`/render` (`api.py:1164`) e `/api/projects/{id}/versions/html` (`api.py:509`). **O fluxo do editor
atravessa os dois routers.** [Source: docs/brownfield/dominio-backend.md#arquitetura-real]

**Tres front-ends convivem em producao:** (a) o SPA React 19.2 + router 7 + Vite 6.4.2 + Tailwind v4,
2904 linhas, **um unico chunk de 434 kB** [Source: docs/brownfield/dominio-frontend.md#arquitetura-real];
(b) o HTML cru da raiz — `index.html` em `/gerador` (`api.py:208`) e como fallback quando
`frontend/dist` nao existe (`api.py:197-200`), `portal.html` em `/portal-legado` (`api.py:277`), que
ainda tem funcoes que o React nao tem (troca de senha, `renderProfile`), e `login.html` orfao; (c) o
mapa/editor entregue ao cliente — `HTML_TEMPLATE` (`pdf_to_map.py:1779-2110`, 65.623 caracteres) mais
**4 blocos de JS em f-string dentro de `api.py`** (`:236`, `:298`, `:577`, `:969`).
[Source: docs/brownfield/dominio-motor-editor.md#editor]

**Motor, assincronia e dados.** `extract_lots` (`pdf_to_map.py:1155-1200`) e um **torneio de ate 7
candidatos** julgado pela metragem impressa na planta (`_rank_lot_candidate` `:1067-1081`), a 50-70 s de
CPU por planta. `enqueue_processing_job` (`app_v1/worker.py:127-136`) usa `Queue("pdf-processing")` com
`REDIS_URL`; **sem Redis roda sincrono dentro do handler HTTP** (`:129-131`). SQLAlchemy 2.0, default
`sqlite:///./mapa.db` (`database.py:7`), producao em `postgresql+psycopg` (`compose.yaml:32`); 12
tabelas em `models.py`, 10 na migration. O estado do `/converter` vive em **JSON no disco, fora do
banco** (`api.py:1128-1140`). [Source: docs/brownfield/dominio-motor-editor.md#arquitetura-real] +
[Source: docs/brownfield/dominio-backend.md#modelo-de-dados]

### Divergencias vs. documentacao

| Documento promete | Realidade | Fonte |
|---|---|---|
| `README.md:7-10`: so `/`, `/converter`, `/render`, `/health` | Postgres, Redis, worker, auth e `/api/v1` sao a espinha dorsal real; `README.md:23-25` manda subir sem `.env`, usando a senha default `mapa-local` publicada em `compose.yaml:9` | [Source: docs/brownfield/dominio-infra.md#topologia-real] |
| `docs/PLATFORM_REBUILD.md:8`: migrations Alembic | Cobrem 10 das 12 tabelas; `downgrade()` derruba 4 das 10 | [Source: docs/brownfield/dominio-backend.md#modelo-de-dados] |
| `docs/PRODUCT_SPEC.md:76-77`: HTTPS, backups, monitoramento e alertas | TLS nao versionado, backup sem agendamento, observabilidade zero | [Source: docs/brownfield/dominio-infra.md#observabilidade] |
| `docs/PRODUCT_SPEC.md:9-15`: 5 perfis de acesso | O frontend nao le `platform_role` em lugar nenhum | [Source: docs/brownfield/dominio-frontend.md#painel-do-administrador] |
| `docs/PRODUCT_SPEC.md:32`: expiracao de link | `GET/PATCH/DELETE .../share-links` existem (`app_v1/api.py:684-731`); nao ha UI | [Source: docs/brownfield/dominio-frontend.md#painel-do-administrador] |
| `design-qa.md:23`: "No actionable P0/P1/P2 issues remain" | As imagens citadas em `design-qa.md:7-11` estao em `output/playwright/`, ignorado pelo git e ausente | [Source: docs/brownfield/dominio-frontend.md#fora-de-escopo] |
| `.env.example:1` documenta `APP_ENV` | `APP_ENV` nao e lido por ninguem; o codigo le 8 variaveis que o `.env.example` nao documenta, entre elas `AUTO_CREATE_TABLES` e `SYNC_PROCESSING` | [Source: docs/brownfield/dominio-infra.md#higiene-do-repositorio] |
| Nenhum doc registra | Existem **quatro** vocabularios incompativeis de `access_mode` | [Source: docs/brownfield/dominio-backend.md#seguranca] |

---

## mapa-de-dividas

Dividas estruturais; o que esta quebrado agora esta na secao anterior e nao se repete aqui.

| Dominio | Divida | Ancora | Custo de manter | Fonte |
|---|---|---|---|---|
| Backend | Dois routers com regras divergentes: `client_member` recebe 200 no v1 e 403 no legado | `app_v1/api.py:353` vs `api.py:440` | Cada correcao de seguranca feita duas vezes, e o editor atravessa os dois no mesmo fluxo | [Source: docs/brownfield/dominio-backend.md#dividas-e-riscos] |
| Backend | Quatro contratos de `access_mode` + tradutor ad-hoc | `api.py:71`, `app_v1/schemas.py:34,54,89`, `app_v1/api.py:98-104` | `unlisted` criado pelo v1 nao e corrigivel pelo PATCH legado: estados de visibilidade inalcancaveis | [Source: docs/brownfield/dominio-backend.md#seguranca] (SEC-5) |
| Backend | `/converter` com modelo de dados proprio em JSON, ~350 linhas | `api.py:806-1161` | Permissao, auditoria e retencao teriam de ser escritas duas vezes; para o `/converter` nunca sao | [Source: docs/brownfield/dominio-backend.md#dividas-e-riscos] |
| Backend | Zero rate limiting em qualquer camada | `api.py:337`, `api.py:915`, `deploy/nginx/...conf` | Login sem contagem de tentativas; upload anonimo de 80 MB queimando CPU de conversao | [Source: docs/brownfield/dominio-backend.md#seguranca] (SEC-6) |
| Backend | Editor grava HTML de ate 80 MB sem sanitizacao na propria origem; `ShareLink.token` em claro; `/docs` publicos; cookie inseguro por default | `api.py:83-85,526-527`, `models.py:145-146`, `api.py:27`, `auth.py:8` | XSS armazenado permanente por um `client_admin`; um dump do banco entrega todos os links ativos | [Source: docs/brownfield/dominio-backend.md#seguranca] (SEC-7, SEC-8, SEC-10, SEC-11) |
| Backend | N+1: `project_workspace_dict` faz 6 queries por projeto, em loop, sem paginacao; caminho absoluto do host gravado no banco | `app_v1/api.py:83-95,130,314,327`; `app_v1/worker.py:92-93` | Custo linear no numero de projetos em 3 telas; mudar `DATA_DIR` ou de maquina invalida todas as versoes publicadas | [Source: docs/brownfield/dominio-backend.md#dividas-e-riscos] |
| Motor | ~20 limiares independentes para "isto e um lote?", em 5 funcoes, nenhum com teste; e `_filter_lots_by_area_text`, a unica validacao final de area, e codigo morto | `pdf_to_map.py:360,433,589,919`; `:1443-1476` | Ajuste em um limiar muda o resultado sem alarme; entra no resultado uma face de quadra com **79x** a area impressa | [Source: docs/brownfield/dominio-motor-editor.md#qualidade-da-extracao] |
| Motor | ~15% dos lotes saem com `(nome, quadra)` duplicado (171 no Setor E, 190 no LAG) | `pdf_to_map.py:1310-1326,1334` | O artefato nao serve para venda sem revisao manual | [Source: docs/brownfield/dominio-motor-editor.md#qualidade-da-extracao] |
| Motor | `tools/qa_mapa.py` fora do CI e com a metrica mais visivel medindo errado; ~2.000 linhas de JS em f-string e `pdf_to_map.py` com 2129 linhas, sem lint/typecheck/teste | `deploy-vps.yml:32-37`, `tools/qa_mapa.py:35`, `api.py:1016-1075` | Nenhuma metrica dos relatorios e defendida; "lotes a mais que rotulos = 135" induziria a remover 135 lotes corretos; um `{` esquecido vira erro de runtime | [Source: docs/brownfield/dominio-motor-editor.md#estado-dos-testes] |
| Editor | Undo custa 453 KB por passo (historico cheio = 10,6 MB) e cobre so metade das acoes; nao ha salvamento nem autosave | `pdf_to_map.py:2060-2061,2095,2109` | Girar a camada por engano e irreversivel; fechar a aba perde todo o trabalho | [Source: docs/brownfield/dominio-motor-editor.md#editor] |
| Editor | Tres copias divergentes do `viewer_guard`; sem acesso por teclado ao mapa; rotulos truncados em silencio (650 de 1182) | `api.py:617,627,1086`; `pdf_to_map.py:1938,1963,1973,2002` | O cliente ve "Edicao: clique em Editar" sem botao Editar; inacessivel para leitor de tela | [Source: docs/brownfield/dominio-motor-editor.md#editor] |
| Frontend | 5 erros de `tsc --noEmit` invisiveis ao `vite build`; sem script de typecheck ou lint | `frontend/tsconfig.json`, `package.json:6-10` | Qualquer regressao de tipo entra em producao em silencio | [Source: docs/brownfield/dominio-frontend.md#qualidade-de-codigo] |
| Frontend | Nenhum estilo de foco em 2904 linhas (`outline-none` 21x); modais sem Esc, focus trap ou nome acessivel; contraste abaixo de AA em 4 pontos | `DashboardPage.tsx:152`, `InviteUserDialog.tsx:58`, `ActivityPage.tsx:26` | Navegacao por teclado no painel inteiro e as cegas | [Source: docs/brownfield/dominio-frontend.md#acessibilidade-e-responsivo] |
| Frontend | Site publico sem preco, captura de lead, rodape, prova social ou Open Graph | `LandingPage.tsx:343-358,393`, `frontend/index.html:8-9` | O unico caminho de conversao e "Entrar"; todo link compartilhado aparece sem preview | [Source: docs/brownfield/dominio-frontend.md#site-publico] |
| Frontend | Hero de **2,6 MB** usado 4x sem `lazy`/`srcset`/WebP; chunk unico de 434 kB baixado por todo visitante | `frontend/public/hero-loteamento-aereo.png`, `App.tsx:3-15` | Maior gargalo de first-paint do site publico | [Source: docs/brownfield/dominio-frontend.md#qualidade-de-codigo] |
| Frontend | Dado pessoal versionado no bundle de producao (email e nomes reais de clientes) | `workspace.ts:61,117,135` | `isLocalDemoMode` evita o uso, nao a inclusao no arquivo publico | [Source: docs/brownfield/dominio-frontend.md#dividas-e-riscos] |
| Frontend | Duplicacao: `slugify` 3x, `statusLabel` 2x, `visibilityLabel` 2x com textos divergentes, banner de erro em 9 arquivos, `ProjectWorkspacePage.tsx` com 720 linhas | `workspace.ts:142`, `DashboardPage.tsx:222,250`, `ClientsPage.tsx:99`, `ProjectWorkspacePage.tsx:681,688` | O mesmo estado tem dois nomes na cara do cliente ("Privado" vs "Privado por login") | [Source: docs/brownfield/dominio-frontend.md#qualidade-de-codigo] |
| Frontend | Polling de job a cada 900 ms sem backoff, teto ou `AbortController` | `ProjectWorkspacePage.tsx:232` | Um job de 10 min = ~660 requisicoes | [Source: docs/brownfield/dominio-frontend.md#dividas-e-riscos] |
| Infra | Observabilidade zero: nenhum log estruturado, APM, metrica, alerta ou uptime externo | `git grep` de sentry/prometheus/logging retorna 1 falso positivo em `app_v1/api.py:307` | MTTD igual ao tempo ate um cliente reclamar; diagnostico so por SSH | [Source: docs/brownfield/dominio-infra.md#observabilidade] |
| Infra | Config de TLS fora do versionamento | `deploy/nginx/mapa-disponibilidade.conf` (so `:80`) | A VPS nao e reconstruivel a partir do repo; aplicar o arquivo versionado derruba o HTTPS | [Source: docs/brownfield/dominio-infra.md#seguranca-de-infra] |
| Infra | Health gate cego para Nginx, TLS e worker | `deploy-vps.yml:122`, `compose.yaml:53-54` | Deploy verde com site fora do ar ou fila de processamento morta | [Source: docs/brownfield/dominio-infra.md#pipeline-de-entrega] |
| Infra | Build na VPS sem limites de recurso, concorrendo com o Postgres; dependencias Python 100% `>=` sem lockfile | `deploy-vps.yml:119`, `compose.yaml`, `requirements.txt`, `Dockerfile:23` | Risco de OOM no deploy derrubando o banco; dois deploys do mesmo commit podem gerar imagens diferentes | [Source: docs/brownfield/dominio-infra.md#pipeline-de-entrega] |
| Infra | Container roda como root, sem `cap_drop`, sem `read_only` | `Dockerfile` sem `USER` | Escape a partir de parsing de PDF de terceiros vira root na VPS | [Source: docs/brownfield/dominio-infra.md#seguranca-de-infra] |
| Infra | Fallback silencioso para SQLite no alembic; logs de container sem rotacao | `alembic.ini:5` + `alembic/env.py:18`; `compose.yaml` sem `logging:` | `DATABASE_URL` ausente migra o banco errado sem falhar; disco cheio a prazo derruba tudo | [Source: docs/brownfield/dominio-infra.md#higiene-do-repositorio] |
| Infra | 56 arquivos de ruido CRLF (10.357 insercoes e 10.357 delecoes, zero mudanca real) | `.gitattributes` sem `* text=auto`; `core.autocrlf` ausente | `git diff` inutilizavel, blame futuro destruido, conflito artificial nas 5 branches `codex/*` | [Source: docs/brownfield/dominio-infra.md#higiene-do-repositorio] |
| Infra | `restore.sh:9` sem `-v ON_ERROR_STOP=1`; `backup.sh` nao roda na imagem (falta `pg_dump`) | `deploy/restore.sh:9`, `Dockerfile:18-20` | Restauracao imprime "Restore concluido" tendo restaurado parcialmente | [Source: docs/brownfield/dominio-infra.md#backup-e-recuperacao] |

---

## o-que-ja-foi-corrigido-nesta-sessao

O relatorio do motor foi levantado **contra o estado pos-correcao** e nomeia as quatro mudancas
aplicadas: tesselacao de curvas, ranking por area, quadra generica e realocacao por gabarito. Numeros
medidos por `tools/qa_mapa.py` nas duas plantas de referencia, exit 0 nas duas
[Source: docs/brownfield/dominio-motor-editor.md#estado-dos-testes]:

| Metrica | SETOR E (58,4 s) | LAG (60,8 s) |
|---|---|---|
| cobertura dos rotulos | **99,9%** | **99,8%** |
| area correta ate 3% | 87,8% | **91,1%** |
| area correta ate 5% | **99,5%** | 96,1% |
| area errada acima de 20% | 0,4% | 1,9% |
| lotes com quadra preenchida | 99,5% | 100,0% |

No LAG, o ranking por concordancia de area rejeita a malha global (0,6278) em favor da anchor-guided
(0,9609), escolhendo `n=1182` sobre `n=1385`.

**Ressalvas — quatro, todas dos relatorios:**

1. **O worker continua entregando zero lotes** (BRK-4, `app_v1/worker.py:27`). O HTML publicado carrega
   a geometria corrigida — nas palavras do relatorio, "hoje o unico artefato utilizavel e o HTML e o
   banco esta vazio". A correcao chega ao mapa que o cliente ve e **nao** chega a nenhuma funcionalidade
   que leia da tabela `Lot`. [Source: docs/brownfield/dominio-motor-editor.md#oportunidades-de-melhoria]
2. **A execucao real via fila RQ com Redis nao foi verificada** — so o codigo foi lido; a medicao usou o
   caminho sincrono. `app_v1/worker.py:27` e o mesmo nos dois caminhos.
   [Source: docs/brownfield/dominio-motor-editor.md#fora-de-escopo]
3. **Nenhuma funcao corrigida tem teste.** O grep contra `tests/` devolveu vazio para `_bezier_steps`,
   `_rank_lot_candidate`, `_normalize_quadra`, `_quadra_label_items`, `_corner_count`,
   `_refine_quadra_with_declared`, `_area_agreement`, `_complete_with_validated_lots`,
   `declared_lot_counts`, `extract_lots`, `extract_lot_metadata`, `build_html`, `_layered_lots` e
   `_filled_lot_polygons`. A unica rede real (`tools/qa_mapa.py --baseline`) esta fora do CI.
4. **O baseline ja registra uma regressao formal que ninguem detectou.** Contra `tmp/qa/baseline.json`:
   LAG **identico**; Setor E melhorou cobertura (99,4->99,9) e **piorou** `area_ate_5pct` (99,9->99,5) e
   `area_acima_20pct` (0,0->0,4) — pelas regras de `compare()` (tolerancia 0,5) isso ja e regressao.

**Sobre o numero "41% -> 91%":** esse par **nao aparece em nenhum dos quatro relatorios**. O que eles
registram e o 91,1% de area correta ate 3% no LAG e o fato de que, contra `tmp/qa/baseline.json`, o LAG
esta identico ao baseline. Consequencia pratica: **nao existe hoje artefato no repositorio que defenda a
melhoria** — `qa_mapa.py` esta fora do CI e o baseline nao guarda o estado anterior a correcao.

---

## contradicoes-entre-relatorios

Quatro. Nenhuma foi resolvida aqui.

**C-1 — `frontend/.npmrc` quebra ou nao quebra o `npm ci`?** `dominio-frontend.md` afirma (divida 14) que
`frontend/.npmrc:1` "quebra `npm ci` em qualquer outra maquina/CI". O **mesmo relatorio**, no cabecalho,
registra `npm ci` -> `added 92 packages in 18s`, `NPM_CI_EXIT=0` numa copia em `/tmp/fe_build`; e
`dominio-infra.md` registra `npm ci && npm run build` como step do job `validate` (`deploy-vps.yml:49-50`),
que serializa todo deploy, sem relatar falha. O conteudo de `frontend/.npmrc:1` foi reconfirmado nesta
consolidacao (`cache=C:\Users\willi\...\.npm-cache`); a contradicao esta na **consequencia**, nao no
conteudo. [Source: docs/brownfield/dominio-frontend.md#dividas-e-riscos] vs
[Source: docs/brownfield/dominio-infra.md#pipeline-de-entrega]

**C-2 — O cookie de sessao trafega em claro hoje?** `dominio-backend.md` (SEC-11) conclui "cookie de 30
dias em claro" a partir de `auth.py:8` (`SESSION_COOKIE_SECURE` default `false`) somado ao nginx
versionado que so escuta `:80`. `dominio-infra.md` estabelece que producao serve
`https://map.eterhub.com.br` (`deploy-vps.yml:58`) com uma config de TLS que existe na VPS e **nao esta
no repositorio**. Concordam no default inseguro (`auth.py:8`, `compose.yaml:34`); divergem sobre o efeito
real, que depende de um arquivo que nenhum dos dois inspecionou.
[Source: docs/brownfield/dominio-backend.md#seguranca] vs
[Source: docs/brownfield/dominio-infra.md#seguranca-de-infra]

**C-3 — Quantos arquivos estao com ruido de CRLF?** `dominio-motor-editor.md` diz "~40 arquivos" e mede
`git diff --stat` de dois arquivos (3015 insercoes para 3015 delecoes). `dominio-infra.md` mede o
repositorio inteiro: 56 modificados + 1 untracked, 10.357/10.357, com `git diff --ignore-cr-at-eol --stat`
vazio. Concordam que nao ha mudanca real; divergem no numero.
[Source: docs/brownfield/dominio-motor-editor.md#fora-de-escopo] vs
[Source: docs/brownfield/dominio-infra.md#higiene-do-repositorio]

**C-4 — Tensao de leitura sobre o fluxo do worker (nao e contradicao factual).** `dominio-backend.md`
descreve o fluxo v1 listando `extract_lots_from_info` (`app_v1/worker.py:94`) e `validate_lots` (`:97`)
como etapas nominais, sem registrar o que produzem; `dominio-motor-editor.md` provou por execucao que a
mesma chamada gera **zero** `Lot`. O backend nunca afirmou que lotes sao persistidos, mas o mapa dele se
le como um pipeline funcionando. Registrado para que ninguem use o fluxo (b) do backend como evidencia de
que os lotes chegam ao banco. [Source: docs/brownfield/dominio-backend.md#fluxos-principais] vs
[Source: docs/brownfield/dominio-motor-editor.md#dividas-e-riscos]

---

## fora-de-escopo

Uniao do que os quatro relatorios deixaram explicitamente de fora. **Nada aqui foi verificado.**

**Ambiente e producao (o maior buraco).** Estado real da VPS: Nginx vigente, crontab, backups em
`/backups`, RAM, versao do Docker, validade do certificado. Estado do banco de producao — se ja possui
`sessions`/`audit_events` criadas por um `AUTO_CREATE_TABLES=true` historico; **BRK-1 esta comprovado
para banco novo**. `docker compose config` nao executado (`docker` indisponivel, exit 127), logo todo o
compose vem de leitura literal. Historico do workflow no GitHub Actions nao consultado. O remote `hf`
(Hugging Face Space) existe e seu papel no fluxo de entrega nao esta documentado.
[Source: docs/brownfield/dominio-infra.md#fora-de-escopo] +
[Source: docs/brownfield/dominio-backend.md#fora-de-escopo]

**Comportamento nao exercitado.** **Nenhuma sessao de navegador foi aberta em nenhuma das quatro
passagens** — as afirmacoes sobre o editor vem da leitura integral do template e as do SPA, do codigo.
Execucao real via fila RQ com Redis. Comportamento sob Postgres: todas as execucoes do backend foram em
SQLite, e `server_default=sa.text("true")` e `compare_type=True` (`alembic/env.py:37`) nao foram
verificados. Path traversal contra `storage_path` (`app_v1/storage.py:16-21`): a checagem de raiz existe,
o ataque nao foi tentado. Plantas `AQUIRAZ_SETOR D.pdf` (23 MB) e `SETOR h i um`; `_filled_lot_polygons`
com lotes coloridos. Contraste do texto sobre o hero; `useApi` sob 401 concorrente; sobrevivencia do
cookie ao proxy do Vite. [Source: docs/brownfield/dominio-motor-editor.md#fora-de-escopo] +
[Source: docs/brownfield/dominio-frontend.md#fora-de-escopo]

**Artefatos nao auditados.** `tests/` foi executado (21 passed, exit 0) mas **nao auditado quanto a
cobertura por endpoint**. `demo/setor-e-demo.html` (105 linhas, 0,84 MiB versionados) nao inspecionado.
`docs/BRAND.md` e as partes de produto/UX de `docs/PRODUCT_SPEC.md` e `ROADMAP.md` foram lidos so onde o
codigo os contradiz.
