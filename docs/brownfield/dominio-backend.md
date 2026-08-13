# Dominio Backend — mapa arqueologico (READ-ONLY)

Passagem: HTTP, autenticacao, autorizacao multi-tenant e dados.
Escopo: `api.py`, `app_v1/*`, `auth.py`, `models.py`, `database.py`, `alembic/`.
Toda afirmacao abaixo tem execucao ou leitura correspondente feita nesta passagem.

## arquitetura-real

Dois routers HTTP vivos no mesmo processo, montados no mesmo `FastAPI` (`api.py:27-28`):

1. **Monolito legado** — `api.py`, 43 rotas (`grep -c "^@app\.(get|post|patch|delete|put)"` -> 43).
   Concentra auth (`/api/auth/*`), paginas SPA, portal legado, editor de projeto, mapas
   publicos/compartilhados, e o pipeline publico `/converter` + `/render`.
2. **API v1** — `app_v1/api.py`, `APIRouter(prefix="/api/v1")` (`app_v1/api.py:60`), 34 rotas:
   projetos, uploads, jobs, versoes, lotes, share links, propostas e auditoria.

Nao ha camada de servico: cada rota e handler + ORM inline. A unica extracao real e `app_v1/`
(permissions, schemas, serialization, storage, validation, worker). `auth.py` e infraestrutura
compartilhada pelos dois (`api.py:21`, `app_v1/api.py:10`).

**Os dois routers estao em uso — nao ha legado morto:**
- O SPA chama `/api/v1/*` (21 ocorrencias em `frontend/src`) **e** `/api/auth/me|login|logout`
  (`frontend/src/components/AppShell.tsx:25,41`, `frontend/src/pages/LoginPage.tsx:20,45`) e
  `/api/profile` (`frontend/src/pages/ProfilePage.tsx:23`).
- O v1 devolve `mapUrl = /projects/{id}/editor` (`app_v1/api.py:125`), rota do legado
  (`api.py:302`), cujo HTML injetado chama `/render` (`api.py:298` -> `api.py:1164`) e
  `/api/projects/{id}/versions/html` (`api.py:509`). O fluxo do editor atravessa os dois.
- O SPA nao chama nenhuma rota legada de projeto/organizacao
  (`grep -rn "/api/" frontend/src | grep -v "/api/v1"` -> so auth e profile).

Persistencia: SQLAlchemy 2.0 declarativo (`models.py`), `sessionmaker` global e dependencia
`get_db()` (`database.py:17-22`), default `sqlite:///./mapa.db` (`database.py:7`). Processamento
assincrono cai em execucao **sincrona dentro do request** quando falta `REDIS_URL`
(`app_v1/worker.py:127-136`).

### divergencias vs. docs
- `docs/PLATFORM_REBUILD.md:8` ("Migrations Alembic em `alembic/`") sugere schema completo; as
  migrations cobrem 10 das 12 tabelas de `models.py` (secao modelo-de-dados).
- `README.md:8` documenta `POST /converter` como recurso simples; o codigo tem pipeline publico
  completo (upload, publicacao, senha, link) sem autenticacao e fora do banco.
- Nenhum doc registra que existem quatro contratos incompativeis de `access_mode` (SEC-5).

## fluxos-principais

**(a) Login e sessao.** `POST /api/auth/login` (`api.py:337`) -> `validate_email` (`api.py:142`)
-> query por email (`api.py:340`) -> `password_hash.verify` (`api.py:341`; pwdlib
`PasswordHash.recommended()`, `auth.py:11`) -> `audit()` insere em `audit_events` (`api.py:344`
-> `auth.py:48-56`) -> `set_session` gera `token_urlsafe(48)`, grava `Session(token_hash=sha256)`
e seta cookie httponly `mapa_session` (`auth.py:29-41`) -> `db.commit()` (`api.py:346`).
Leitura: `current_user` (`auth.py:60-74`) le cookie -> `hash_token` -> busca por `token_hash` ->
checa `expires_at` -> `db.get(User)` -> checa `active` -> atualiza `last_seen_at` com `commit()`
a cada 5 min (`auth.py:70-73`). Logout revoga **todas** as sessoes (`api.py:353`, intencional).

**(b) Projeto -> upload -> processamento -> publicacao (caminho v1, o do SPA).**
`POST /api/v1/projects` (`app_v1/api.py:330`, `user_can_manage_org` em `permissions.py:11`) ->
`POST /api/v1/projects/{id}/files` (`app_v1/api.py:377`): `require_project_manager` (`:142`),
valida content-type/extensao (`:381`), `write_stream` com sha256 (`storage.py:24-37`), magic bytes
`%PDF-` (`:389-395`), limite `MAX_UPLOAD_BYTES` **apos** gravar (`:396-400`) -> `FileAsset` ->
`POST /api/v1/projects/{id}/processing-jobs` (`:427`), resolve `FileAsset` restrito ao projeto
(`:434-443`), `ProcessingJob(status="queued")`, `enqueue_processing_job` (`worker.py:127`) ->
`run_processing_job` (`worker.py:53`): copia PDF (`:74`), `pdf_to_map.convert` (`:76`), cria
`ProjectVersion` (`:77-86`), grava artefatos no storage privado (`:88-93`), `extract_lots_from_info`
(`:94`), `validate_lots` (`:97`), `succeeded` + `AuditEvent` (`:100-112`) ->
`POST /api/v1/projects/{id}/publish` (`:548`): revalida (`:557-564`), zera `is_published` das
outras versoes (`:572`), marca projeto/versao (`:574-578`), **reaproveita o `ShareLink`
preservando o token** (`:580-599`), desativa links antigos (`:600-605`), `audit`, commit.
O caminho legado paralelo existe e nao e usado pelo SPA: `api.py:474` (generate), `:533` (publish),
`:549` (share).

**(c) Acesso do cliente por share link.** `GET /s/{token}` (`api.py:658`) -> busca `ShareLink` pelo
**token em texto puro** (`:660`) -> se inativo, decide entre 410 e redirect para o substituto
(`:663-680`) -> `expires_at` (`:681`) -> exige `project.status == "published"` (`:684`) -> se
`access_mode == "private"`, resolve sessao por `authenticated_request_user` (`api.py:180`) e exige
membership (`:686-691`) -> `latest_version(published_only=True)` (`:692`) -> se ha senha, checa
cookie de unlock (`:695`, `share_is_unlocked` em `:572`) e devolve formulario -> incrementa
`access_count` (`:697-699`) -> `shared_map_response` (`:609`) le o HTML do disco e injeta guard de
leitura ou barra de edicao (`:614-618`). `POST /s/{token}` (`:703`) valida senha e seta cookie de
unlock por 8h (`:726-734`). Proposta do cliente: `POST /api/shared-edit-proposals/{id}` (`:738`),
sem sessao obrigatoria, guardado por `allow_edit` + unlock (`:741-753`). Rota por slug:
`/p/{slug}` e `/mapas/{slug}` (`:637,653`), so `published` + `access_mode == "public"` (`:639`).

**(d) `/converter` publico — existe e e totalmente anonimo.** `POST /converter/jobs` (`api.py:915`)
valida extensao e `quality` (`:921-925`), grava `source.pdf` com limite por chunk (`:930-939`),
checa magic bytes (`:940-943`), escreve `job.json` (`:959`) e dispara `BackgroundTasks` (`:960`).
`GET /converter/jobs/{id}` (`:964`), `GET /converter/jobs/{id}/map` (`:1090`),
`POST /converter/jobs/{id}/publish` (`:1102`), `GET|POST /map/{token}` (`:1148,1156`) e
`POST /render` (`:1164`) **nao tem dependencia de sessao**. O estado vive em JSON no disco, fora do
banco; `/map/{token}` varre linearmente todos os diretorios de job por requisicao (`:1128-1140`).

Inspecionando o objeto `app` em runtime, as rotas sem `current_user`/`require_platform_admin` sao:
`/health`, `/`, `/gerador`, `/hero-loteamento-aereo.png`, `/entrar`, `/cliente`, `/login`,
`/portal-legado`, `/app`, `/app/{path}`, `/api/auth/setup`, `/api/auth/login`,
`/mapas/setor-e-demo`, `/p/{slug}`, `/mapas/{slug}`, `GET|POST /s/{token}`,
`/api/shared-edit-proposals/{id}`, `/converter`, `/converter/jobs`, `/converter/jobs/{id}`,
`/converter/jobs/{id}/map`, `/converter/jobs/{id}/publish`, `GET|POST /map/{token}`, `/render`,
mais `/docs`, `/redoc`, `/openapi.json` (defaults do FastAPI, nao desabilitados).

## modelo-de-dados

`models.py` define **12** tabelas; a unica migration cria **10**. Divergencia alegada: CONFIRMADA.

```
$ grep -c '__tablename__' models.py                                               -> 12
$ grep -c 'op.create_table(' alembic/versions/20260715_0001_platform_rebuild.py   -> 10
$ DATABASE_URL=sqlite:////tmp/fresh.db python -m alembic upgrade head             -> exit 0
$ select name from sqlite_master where type='table':
['alembic_version','edit_proposals','file_assets','lots','memberships','organizations',
 'processing_jobs','project_versions','projects','share_links','users']           -> total 11
```

Faltam **`sessions`** (`models.py:175`) e **`audit_events`** (`models.py:186`) — as duas tabelas
que o login escreve. Consequencia em SEC-1. `downgrade()` derruba so 4 das 10 tabelas
(`alembic/versions/20260715_0001_platform_rebuild.py:233-236`): rollback nao e reversivel.

Outras observacoes de modelagem:
- `ShareLink` guarda `token` em claro **e** `token_hash` (`models.py:145-146`); `api.py:660`
  consulta pelo campo em claro — o hash e decorativo.
- `FileAsset.organization_id` e nullable com `ondelete="SET NULL"` (`models.py:87`) — origem de SEC-4.
- `ProjectVersion.map_html_path` guarda caminho absoluto do host (`app_v1/worker.py:92-93`).
- `utcnow()` usa `datetime.utcnow()` (`models.py:14-15`), deprecado no Python 3.12 — a imagem base
  (`Dockerfile:9`).

## seguranca

**SEC-1 — Critico — Login impossivel em banco novo.** `Dockerfile:34` roda `alembic upgrade head`
antes do uvicorn; `api.py:100-103` so cria tabelas se `AUTO_CREATE_TABLES=true` (default `false`,
ausente do `.env.example`). Com o schema da migration, o primeiro `audit()` mata a requisicao:
```
POST /api/auth/setup -> 500
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table: audit_events
[SQL: INSERT INTO audit_events (id, actor_user_id, organization_id, action, ...)]
POST /api/auth/login -> mesma OperationalError; set_session ainda dependeria de `sessions`
```
Todo deploy limpo (VPS nova, restore, staging) sobe com 100% de falha de autenticacao. O pytest
verde nao pega porque monta o schema com `Base.metadata.create_all(engine)`
(`tests/test_security_regressions.py:34` e outros 5 pontos).

**SEC-2 — Critico — `/converter` sem dono: qualquer um publica, despublica e troca a senha.**
`api.py:1102` (`publish_converter_job`) nao tem `Depends(current_user)`. Reproduzido sem cookie:
```
POST /converter/jobs/{id}/publish  (sem sessao) -> 200
{"job":{"id":"86a5...","status":"completed",...,"published":true,"allow_edit":true}}
```
Quem tiver o `job_id` — que trafega na URL do editor, em logs de proxy, no historico e no Referer —
controla publicacao, `allow_edit` e senha do mapa alheio. `api.py:1090` tambem entrega o editor
completo sem sessao.

**SEC-3 — Critico — XSS armazenado via `project_id` em `converter_editor_controls`.**
`api.py:970-971`:
```python
    job_id = json.dumps(job["id"])
    project_id = json.dumps(job.get("project_id"))
```
Interpolado dentro de `<script>` em `api.py:1017` (`var jobId={job_id}, projectId={project_id};`).
`json.dumps` nao escapa `</script>`. `api.py:1096-1097` persiste o `project_id` vindo da query
string no `job.json` e `api.py:1099` re-serve. Reproduzido ponta a ponta, sem autenticacao:
```
GET /converter/jobs/{id}/map?project_id=</script><script>fetch('/api/auth/me')</script> -> 200
payload presente no HTML: True
render: var jobId="000...", projectId="</script><script>fetch('/api/auth/me')</script>";
```
O cookie e httponly (`auth.py:36`), entao nao vaza por `document.cookie`, mas o script roda na
origem da aplicacao e pode chamar `/api/v1/*` com `credentials: same-origin`.

**SEC-4 — Alto — `download_file` ignora tenancy quando `organization_id` e NULL.**
`app_v1/api.py:422`:
```python
    if not asset or (asset.organization_id and not user_can_access_org(db, user, asset.organization_id)):
```
Com `organization_id` nulo o segundo termo curto-circuita. Nulos surgem sozinhos: `models.py:87`
usa `ondelete="SET NULL"`, entao apagar uma organizacao torna os PDFs dela globalmente legiveis.
```
GET /api/v1/files/{asset_orfao} como usuario sem membership -> 200 b'%PDF-CONTEUDO-SIGILOSO'
GET /api/v1/files/{asset_de_outra_org} (org preenchida)     -> 404   # o check funciona
```

**SEC-5 — Alto — `access_mode` tem quatro contratos para o mesmo campo.** Verificado instanciando
os modelos (`api.py:71`, `app_v1/schemas.py:34,54,89`):
```
api.ProjectUpdatePayload   aceita: private, link, public
v1.ProjectUpdate           aceita: private, link, public, password, unlisted
v1.ProjectPublishPayload   aceita: private, public, password, unlisted
v1.ShareLinkCreate         aceita: private, public, password, token
```
O gate de leitura publica so entende `"public"` (`api.py:639`) e existe um tradutor ad-hoc para
reconciliar vocabularios (`app_v1/api.py:98-104`). Projeto marcado `unlisted` pelo v1 nao pode ser
corrigido pelo PATCH legado: estados de visibilidade inalcancaveis por um dos lados.

**SEC-6 — Alto — Zero rate limiting em qualquer camada.**
`git ls-files | xargs grep -iE "slowapi|limit_req|ratelimit|rate_limit|Limiter\("` -> nenhum hit
(xargs exit 123 = grep sem match); `deploy/nginx/mapa-disponibilidade.conf` tambem nao tem
`limit_req`. `POST /api/auth/login` (`api.py:337`) nao conta tentativas nem bloqueia conta;
`POST /converter/jobs` (`api.py:915`) aceita PDFs de ate 80MB anonimos e queima CPU de conversao.
Alegacao anterior CONFIRMADA.

**SEC-7 — Alto — Editor grava HTML arbitrario servido na propria origem.**
`HtmlVersionPayload.html` aceita ate 80MB sem sanitizacao (`api.py:83-85`); `save_editor_version`
escreve direto no disco (`api.py:526-527`) e `shared_map_response` devolve como `text/html`
(`api.py:612-619`). Um `client_admin` consegue XSS armazenado permanente em `/mapas/{slug}`,
`/s/{token}` e `/projects/{id}/editor`, na mesma origem do cookie.

**SEC-8 — Medio — Token de share em texto puro.** `models.py:145` coexiste com `:146`; `api.py:660`
e `api.py:705` filtram por `ShareLink.token`. Um dump do banco entrega todos os links ativos.

**SEC-9 — Medio — URL publica derivada de header nao confiavel.** `app_v1/api.py:149-159`: sem
`PUBLIC_BASE_URL`, `link_url` monta a base com `x-forwarded-host`/`x-forwarded-proto` do request —
o link enviado ao cliente pode apontar para o host do atacante.

**SEC-10 — Medio — `/docs`, `/redoc` e `/openapi.json` publicos.** `GET /docs` sem auth -> 200;
`FastAPI(title="NexoLote")` (`api.py:27`) nao desabilita os docs.

**SEC-11 — Medio — Cookie de sessao inseguro por default.** `auth.py:8`
(`SESSION_COOKIE_SECURE`, default `"false"`). O `.env.example:2` traz `true`, mas o default do
codigo e falso e o nginx versionado so escuta `:80`
(`deploy/nginx/mapa-disponibilidade.conf:2-3`) — cookie de 30 dias em claro.

**SEC-12 — Baixo — `/map/{token}` varre o diretorio de jobs por request.** `api.py:1128-1140`
percorre `os.scandir` e abre cada `job.json` ate achar o token, sem autenticacao.

**SEC-13 — Baixo — `validate_email` aceita quase tudo.** `api.py:142-146` so verifica `@` fora das
pontas.

## coding-standards

Convencoes efetivamente praticadas:

- **Dependencia de sessao declarada rota a rota**, nunca middleware global:
  `user: User = Depends(current_user)` (`app_v1/api.py:163,175,190,...`; `api.py:360,372,...`).
  Esquecer o parametro = rota publica silenciosa — raiz de SEC-2.
- **Sessao de banco sempre por dependencia** `db: DbSession = Depends(get_db)` (`database.py:17-22`);
  unica excecao e o worker, que abre `SessionLocal()` e fecha em `finally` (`app_v1/worker.py:54,123`).
- **Erro sempre via `HTTPException` com `detail` em portugues sem acento**, sem excecao custom
  (`app_v1/api.py:138`). Recurso de outro tenant devolve **404, nao 403** (`app_v1/api.py:137-145`).
- **Autorizacao em duas camadas**: `user_can_access_org` (leitura) vs `user_can_manage_org`
  (escrita), com `platform_admin`/`operator` sempre passando (`app_v1/permissions.py:6-22`). O
  legado duplica o par com outro nome (`api.py:167-177`).
- **Serializacao manual em funcoes `*_dict`**, sem `response_model` (`app_v1/serialization.py`
  inteiro; o legado repete inline em `api.py:106-132`).
- **Validacao so por Pydantic com `pattern=` regex, nunca Enum** (`app_v1/schemas.py:33,42,54,89`;
  `api.py:70-71,97`) — o que permitiu os quatro vocabularios de SEC-5.
- **Ordem de escrita: `db.add` -> `db.flush()` (quando precisa do id) -> `audit(...)` -> `db.commit()`**
  (`app_v1/api.py:196-201,343-347,457-460`). `audit()` so faz `db.add` (`auth.py:48-56`).
- **JSON em coluna Text, serializado a mao com `ensure_ascii=False`** (`app_v1/api.py:650-652`,
  `app_v1/serialization.py:144,173,193`).
- **Config exclusivamente por `os.getenv` com default inline**, sem objeto de settings
  (`database.py:6`, `auth.py:6-8`, `api.py:30-31`, `app_v1/storage.py:8-9`).
- **Imports no topo, absolutos da raiz**; relativos so dentro de `app_v1` (`app_v1/api.py:27`).
  Excecoes: import dentro de funcao em `app_v1/api.py:64-65` e `app_v1/worker.py:132-133`.
- **Docstring so onde a decisao nao e obvia**, em ingles, uma linha (`app_v1/api.py:82,551`;
  `api.py:150`).

## dividas-e-riscos

1. **Migration incompleta (SEC-1)** — `alembic/versions/20260715_0001_platform_rebuild.py`.
   Custo: nenhum ambiente novo sobe; a recuperacao de desastre esta quebrada hoje e so se descobre
   na hora em que ela e necessaria.
2. **`/converter` anonimo e fora do banco (SEC-2, SEC-3)** — `api.py:806-1161`, ~350 linhas com
   modelo de dados proprio em JSON. Custo: permissao, auditoria e retencao teriam de ser escritas
   duas vezes; para o `/converter` nunca sao.
3. **Dois routers com regras divergentes para o mesmo recurso (SEC-5)** — tambem na permissao:
   `GET /api/v1/projects/{id}` como `client_member` -> **200** (`app_v1/api.py:353`);
   `GET /api/projects/{id}`, mesmo usuario -> **403** (`api.py:440`). Custo: cada correcao de
   seguranca precisa ser feita em dois lugares, e o editor atravessa os dois no mesmo fluxo.
4. **`project_workspace_dict` faz 6 queries por projeto** (`app_v1/api.py:83-95,130`), chamado em
   loop por `/api/v1/projects` (`:327`), `/api/v1/dashboard` (`:314`) e
   `/api/v1/organizations/{id}` (`:226`), nenhum paginado. Custo: N+1 linear no numero de projetos.
5. **Processamento sincrono no request sem `REDIS_URL`** (`app_v1/worker.py:129-130`). Custo: um
   PDF pesado prende um worker uvicorn pela conversao inteira.
6. **`current_user` escreve no banco em GET** (`auth.py:70-73`). Custo: toda leitura vira potencial
   escrita; impede replica read-only.
7. **Caminho absoluto do host no banco** (`app_v1/worker.py:92-93`). Custo: mudar `DATA_DIR` ou de
   maquina invalida todas as versoes publicadas.
8. **`@app.on_event("startup")` deprecado** (`api.py:100`, warning ja emitido pelo pytest). Custo:
   quebra na proxima major do FastAPI.
9. **Auditoria desigual** — `retry_processing_job` (`app_v1/api.py:474-489`) nao gera `AuditEvent`
   como os pares. Custo: a trilha nao serve como fonte de verdade.
10. **`downgrade()` parcial** (`alembic/versions/...:233-236`). Custo: rollback deixa o banco num
    estado que nenhuma migration sabe descrever.

## oportunidades-de-melhoria

Ordenado por impacto / esforco. **Nada foi implementado nesta passagem.**

1. **Nova revision Alembic com `sessions` e `audit_events`**, espelhando `models.py:174-195`.
   ~40 linhas; move o produto de "nao sobe" para "sobe". Corrige SEC-1.
2. **Fechar o cluster `/converter`** — `Depends(current_user)` em `api.py:1102` e `:1090`, e gravar
   o dono no `job.json` (`api.py:945-959`) verificando-o em `read_converter_job`. ~15 linhas. SEC-2.
3. **Escapar a interpolacao em `<script>`** — em `api.py:970-971`, aplicar
   `.replace("</", "<\\/")` sobre o `json.dumps`, ou emitir via `<script type="application/json">`
   lido com `JSON.parse`. 2 linhas. SEC-3.
4. **Inverter o curto-circuito de `download_file`** — `app_v1/api.py:422` deve negar quando
   `asset.organization_id is None`. 1 linha. SEC-4.
5. **Vocabulario unico de `access_mode`** — um `Literal`/Enum compartilhado por `api.py:71`,
   `app_v1/schemas.py:34,54,89` e pelo gate `api.py:639`, eliminando o tradutor de
   `app_v1/api.py:98-104`. ~30 linhas em 3 arquivos. SEC-5.
6. **Rate limit em `/api/auth/login`, `/converter` e `/converter/jobs`** — `slowapi` em `api.py:27`
   ou `limit_req` em `deploy/nginx/mapa-disponibilidade.conf`. SEC-6.
7. **Docs fechados fora de dev** — `docs_url=None, redoc_url=None, openapi_url=None` em `api.py:27`.
   1 linha. SEC-10.
8. **Default seguro do cookie** — inverter `auth.py:8` para `!= "false"` e forcar `secure` quando
   `APP_ENV=production`. 1 linha. SEC-11.
9. **Parar de guardar `ShareLink.token` em claro** — consultar por `token_hash` (`api.py:660,705`)
   e parar de popular `token` (`api.py:557`, `app_v1/api.py:699`). SEC-8.
10. **Paginar `/api/v1/projects` e `/api/v1/project-versions/{id}/lots`** (`app_v1/api.py:318,626`)
    e resolver o N+1 de `project_workspace_dict` com `joinedload`/agregacao.
11. **Consolidar os dois routers** — mover `/api/auth/*` e `/api/profile` para `app_v1` e apontar
    `mapUrl` (`app_v1/api.py:125`) para um editor v1, aposentando `api.py:423-561`. Maior reducao
    de superficie possivel, e o unico item de esforco alto da lista.

## fora-de-escopo

- `pdf_to_map.py`, `frontend/` (lido so para provar quais rotas o SPA consome), `Dockerfile`,
  `compose.yaml`, CI e `deploy/*` — outros dominios; citados apenas onde determinam o
  comportamento do backend (`Dockerfile:34` roda a migration; nginx sem TLS nem rate limit).
- `app_v1/storage.py` foi lido por completo, mas **nao houve teste dinamico de path traversal**
  contra `storage_path` (`app_v1/storage.py:16-21`) nesta passagem; a checagem de raiz existe.
- Todas as execucoes foram em SQLite. Comportamento de `server_default=sa.text("true")` e de
  `compare_type=True` (`alembic/env.py:37`) sob Postgres: **nao verificado nesta passagem**.
- Estado do banco de producao (se ja possui `sessions`/`audit_events` criadas por um
  `AUTO_CREATE_TABLES=true` historico): **nao verificado nesta passagem**. SEC-1 esta comprovado
  para banco novo.
- `tests/` foi executado (`21 passed`) mas nao auditado quanto a cobertura por endpoint.

---

**VEREDICTO: FAIL.** Nao e julgamento de estilo: o backend nao autentica em banco novo —
`/api/auth/setup` e `/api/auth/login` retornam 500 com `no such table: audit_events` depois de um
`alembic upgrade head` bem-sucedido, que e exatamente a sequencia do `Dockerfile:34`. Somado a isso,
tres rotas anonimas dao controle de publicacao e execucao de script na origem da aplicacao
(`api.py:1090`, `:1102`, `:969-971`, todas reproduzidas com 200 sem cookie) e o download de
arquivos ignora tenancy num caminho que o proprio schema cria sozinho (`app_v1/api.py:422` +
`models.py:87`). A suite verde nao contradiz nada disso: ela monta o schema com
`Base.metadata.create_all`, o unico caminho onde as 12 tabelas existem.
