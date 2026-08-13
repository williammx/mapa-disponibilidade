# Dominio: Infraestrutura, Entrega, Observabilidade e Higiene

Passagem de arqueologia READ-ONLY. Tudo abaixo tem evidencia fresca (arquivo:linha ou saida de comando).
Data da passagem: 2026-08-12. Commit HEAD: `e8c89a7` ("Improve curved lot extraction and map QA").

Limite conhecido desta passagem: **`docker` nao existe no ambiente de inspecao** (`docker --version` -> `command not found`, exit=127).
Portanto `docker compose config` **nao foi executado**. Toda afirmacao sobre compose vem da leitura literal de `compose.yaml`.

---

## topologia-real

Quatro processos declarados em `compose.yaml`, todos com `restart: unless-stopped`:

| Servico | Imagem/Origem | Container | Exposicao | Volume |
|---|---|---|---|---|
| `db` | `postgres:16-alpine` (`compose.yaml:3`) | `mapa-postgres` | nenhuma porta publicada | `mapa_postgres_data:/var/lib/postgresql/data` (`:11`) |
| `redis` | `redis:7-alpine` (`:19`), `--appendonly yes` (`:22`) | `mapa-redis` | nenhuma porta publicada | `mapa_redis_data:/data` (`:24`) |
| `mapa-disponibilidade` | `build: .` (`:27`) | `mapa-disponibilidade` | `127.0.0.1:8000:7860` (`:45`) | `mapa_project_data:/data` (`:47`) |
| `worker` | `build: .` (`:50`) | `mapa-worker` | nenhuma | `mapa_project_data:/data` (`:67`) |

- App e worker compartilham a **mesma imagem** (`build: .` duas vezes) e o **mesmo volume** `/data`.
- Porta interna 7860 (`Dockerfile:13,31`), publicada apenas no loopback como 8000 (`compose.yaml:45`). Nao ha exposicao direta a internet.
- Proxy: `deploy/nginx/mapa-disponibilidade.conf:9` faz `proxy_pass http://127.0.0.1:8000`, casando com a publicacao acima. `client_max_body_size 100m` (`:6`) e timeouts de 10m para upload/leitura (`:16-17`).
- Servidor default `return 444` para Host desconhecido (`:21-27`) — bom, bloqueia acesso por IP cru.
- Dominio de producao: `https://map.eterhub.com.br` (`.github/workflows/deploy-vps.yml:58`).
- Diretorio de aplicacao na VPS: `/opt/mapa-disponibilidade` (`deploy-vps.yml:103`).

**Ordem de subida:** app e worker dependem de `db` com `condition: service_healthy` (`compose.yaml:40-41`, `:62-63`) e de `redis` com `service_started` (`:42-43`, `:64-65`). Ou seja, Redis pode estar aceitando conexoes sem estar pronto; nao ha healthcheck para Redis em lugar nenhum.

**Migrations rodam no boot, em dois lugares simultaneos:** `Dockerfile:34` (`alembic upgrade head && uvicorn ...`) e `compose.yaml:55` (`alembic upgrade head && rq worker ...`). App e worker sobem juntos e ambos tentam migrar o mesmo banco ao mesmo tempo. Nao ha lock explicito no repo.

### Divergencias vs. documentacao

- **`README.md` descreve outro produto.** Lista apenas `GET /`, `POST /converter`, `POST /render`, `GET /health` (`README.md:7-10`). Nao menciona Postgres, Redis, worker, autenticacao nem `/api/v1` — que sao a espinha dorsal real (`ROADMAP.md:15`, `docs/PLATFORM_REBUILD.md:7-11`).
- **`README.md:23-25`** manda `docker compose up -d --build` sem qualquer mencao a `.env`. Mas `compose.yaml:37` exige `SETUP_TOKEN` e `deploy-vps.yml:111` aborta o deploy se `$APP_DIR/.env` nao existir (`test -f`). O README, seguido literalmente, sobe um ambiente com senha default `mapa-local` (`compose.yaml:9`).
- **`README.md` nunca cita HTTPS nem `map.eterhub.com.br`.** O unico lugar do repo que sabe o dominio de producao e o workflow.
- **`docs/PRODUCT_SPEC.md:76`** promete "Nginx na VPS, Cloudflare para DNS, HTTPS, protecao e cache". `docs/PRODUCT_SPEC.md:77` promete "Backups de banco e arquivos, monitoramento de erros e alertas". Nenhum dos tres (HTTPS versionado, backup automatico, monitoramento) existe no repositorio — detalhado abaixo.

---

## pipeline-de-entrega

Arquivo unico: `.github/workflows/deploy-vps.yml` (133 linhas). E o unico workflow (`ls .github/workflows/` -> so `deploy-vps.yml`).

Gatilho: `push` em `main` + `workflow_dispatch` (`:4-6`). `permissions: contents: read` (`:8-9`). `concurrency` com `cancel-in-progress: false` (`:11-13`) — serializa deploys, correto para producao.

**Job `validate` (`:16-50`)** — o que garante:
1. `python -m py_compile api.py pdf_to_map.py` (`:36`) — garante que dois arquivos parseiam. Nao cobre `app_v1/`, `models.py`, `auth.py`, `database.py`.
2. `python -m pytest -q` (`:37`) — roda os 8 arquivos em `tests/`.
3. `npm ci && npm run build` (`:49-50`) — garante que o bundle Vite compila.

**O que o `validate` NAO garante:**
- **Nao testa contra Postgres.** Todos os testes que tocam banco usam `create_engine("sqlite:///:memory:")` — `tests/test_client_management.py:12`, `tests/test_project_publication.py:48,89,118`, `tests/test_project_workspace_serialization.py:10`, `tests/test_security_regressions.py:33`. Producao roda `postgresql+psycopg` (`compose.yaml:32`). O CI nao sobe service container de Postgres.
- **Nao executa `alembic upgrade head` nunca.** Nao ha step de migration no workflow. A primeira execucao de qualquer migration nova acontece **em producao**, no boot do container (`Dockerfile:34`).
- **Nao roda type-check.** `frontend/package.json:8` define `"build": "vite build"` — sem `tsc --noEmit`. Vite/esbuild apagam tipos sem verifica-los. **ALEGACAO CONFIRMADA.**
- **Nao roda lint.** Nao ha script de lint em `frontend/package.json:6-10` e nao ha eslint nas devDependencies (`:19-26`). **ALEGACAO CONFIRMADA.**

**Job `deploy` (`:52-133`)** — `needs: validate`, `environment: {name: production, url: https://map.eterhub.com.br}` (`:56-58`). **ALEGACAO CONFIRMADA:** o workflow existe, esta completo e usa `environment: production`.

Sequencia real:
1. Escreve chave SSH e `known_hosts` a partir de secrets (`:63-72`). `known_hosts` presente = sem `StrictHostKeyChecking=no`. Bom.
2. `tar` com exclusoes de `.git`, `.github`, `node_modules`, `frontend/dist`, `data`, `*.db` (`:76-83`).
3. `scp` do tarball (`:90-92`).
4. Script remoto via `ssh ... "bash -s -- '${GITHUB_SHA}'"` com `set -euo pipefail` (`:99-100`).

Dentro do script remoto:
- `test -f "$APP_DIR/.env"` (`:111`) — pre-condicao antes de mexer em qualquer coisa. Bom.
- `sudo rsync -a --delete --exclude=.env "$RELEASE_DIR/" "$APP_DIR/"` (`:112-114`). **ALEGACAO CONFIRMADA** quanto ao `--delete` (embora o transporte CI->VPS seja `scp` de tarball, nao rsync).
- `docker compose config -q` (`:118`) — valida sintaxe.
- `docker compose up -d --build --remove-orphans` (`:119`). **ALEGACAO CONFIRMADA: o build acontece na VPS.** E o build e caro: `Dockerfile:1-7` roda `npm ci` + `npm run build` (Node 22) e `Dockerfile:23` roda `pip install` de `opencv-python-headless`, `pymupdf`, `shapely`, `numpy` — tudo na maquina de producao, concorrendo com o Postgres e o app em execucao. Risco de OOM real; nao medido nesta passagem.
- Health gate: ate 30 tentativas x 4s (120s) contra `http://127.0.0.1:8000/health` (`:121-128`).
- Em falha: `docker compose ps`, `docker compose logs --tail=120`, `exit 1` (`:130-132`).

**ALEGACAO CONFIRMADA — nao ha rollback.** As linhas `:130-132` sao o caminho de falha completo: imprime e morre. Nao ha `RELEASE_DIR` anterior guardado, nao ha tag de imagem anterior, nao ha `docker compose down` + restauracao. E o agravante: o `--delete` da linha `:112` **ja destruiu o codigo antigo antes do build**. Falhou o health check, producao fica no estado quebrado ate intervencao manual por SSH.

**ALEGACAO CONFIRMADA — nao ha backup do Postgres antes do deploy.** `git grep -n 'backup\.sh'` retorna exatamente duas ocorrencias, ambas em `docs/PLATFORM_REBUILD.md:20` e `:42`. O workflow nunca invoca `deploy/backup.sh`. Combinado com o item anterior: uma migration destrutiva ruim = perda permanente.

**ALEGACAO PARCIALMENTE REFUTADA — o health check nao e trivial, mas e insuficiente.** `api.py:191-194` mostra que `/health` executa `db.execute(text("SELECT 1"))` antes de retornar `{"status": "ok"}`. Logo, valida conectividade real com Postgres — melhor que um 200 estatico. **Mas a parte central da alegacao se confirma:** o alvo e `127.0.0.1:8000` (`deploy-vps.yml:122`), dentro da VPS, **sem passar por Nginx, TLS ou DNS**. Certificado expirado, Nginx parado ou config invalida -> deploy verde, site fora do ar.

**Buraco adicional no health gate (nao alegado antes):** `compose.yaml:53-54` desativa o healthcheck do worker (`healthcheck: disable: true`). O gate so consulta o container do app. Um worker em crash-loop passa despercebido: deploy verde, processamento de PDF completamente morto.

**Desperdicio:** o frontend e compilado duas vezes por deploy — em `validate` (`:46-50`, artefato descartado) e de novo na VPS via `Dockerfile:5-7`.

---

## seguranca-de-infra

**Segredos — higiene boa.** `git ls-files | grep '\.env'` retorna apenas `.env.example`; nenhum `.env` versionado. `.gitignore:41-44` cobre `.env` e `.env.*` com excecao para `.env.example`. Varredura por literais tipo segredo em `*.py|*.yaml|*.ini|*.sh` so encontrou fixtures de teste (`tests/test_security_regressions.py:88,105,128`, etc.). Todos os valores de `.env.example` sao placeholders explicitos ("troque-por-uma-senha-longa-e-unica", `:7`). Segredos do deploy vem de GitHub Secrets: `VPS_SSH_KEY`, `VPS_KNOWN_HOSTS`, `VPS_HOST`, `VPS_USER` (`deploy-vps.yml:65-66,87-88`).

**Defaults inseguros no compose:**
- `SESSION_COOKIE_SECURE: ${SESSION_COOKIE_SECURE:-false}` (`compose.yaml:34`). **ALEGACAO CONFIRMADA.** `.env.example:2` corrige para `true`, mas o default do compose vale sempre que a var faltar no `.env` — falha silenciosa e insegura (cookie de sessao trafega sem flag Secure).
- `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-mapa-local}` (`compose.yaml:9`) e a mesma credencial embutida na `DATABASE_URL` default (`:32`, `:57`). Sem `.env`, sobe com senha conhecida e publicada no repositorio.
- `SETUP_TOKEN: ${SETUP_TOKEN:-}` (`:37`) — default vazio.

**Container roda como root. ALEGACAO CONFIRMADA.** `grep -nE '^USER|adduser|useradd|--chown' Dockerfile` -> exit=1, nenhuma ocorrencia nas 34 linhas. Nao ha `user:` em `compose.yaml` (grep -> exit=1). Uvicorn, o worker RQ e todo o processamento de PDF de terceiros rodam como uid 0.

**Sem limites de recurso. ALEGACAO CONFIRMADA.** `grep -nE 'deploy:|resources|mem_limit|cpus|read_only|cap_drop|security_opt' compose.yaml` -> exit=1. Nenhum limite de CPU/memoria, nenhum `cap_drop`, nenhum `read_only`, nenhum `security_opt`. Um PDF malicioso ou muito grande pode consumir toda a RAM da VPS e derrubar o Postgres junto.

**Superficie exposta:** apenas Nginx :80 (e, na VPS real, :443 — nao versionado). Postgres e Redis nao publicam portas. Redis sem `requirepass` (`compose.yaml:22` so define `--appendonly yes`) — aceitavel enquanto ficar em rede interna do compose, fragil se alguem publicar a porta.

**Divergencia critica de TLS. ALEGACAO CONFIRMADA.** `deploy/nginx/mapa-disponibilidade.conf` tem 27 linhas e **somente blocos `listen 80`** (`:2-3`, `:22-23`). Nao ha `listen 443 ssl`, `ssl_certificate`, redirect 301 para HTTPS, HSTS, nem qualquer referencia a certbot/letsencrypt (`git grep -Ei 'certbot|letsencrypt'` -> sem resultado em todo o repo). Como `deploy-vps.yml:58` declara producao em `https://map.eterhub.com.br`, a VPS real tem uma configuracao de TLS que **nao existe no versionamento**. Consequencias concretas: (a) a config real nunca foi revisada em PR; (b) se alguem aplicar o arquivo versionado na VPS, derruba o HTTPS; (c) reconstruir a VPS do zero a partir do repo produz um site sem TLS servindo cookies de sessao.

---

## backup-e-recuperacao

**O que existe:** `deploy/backup.sh` (16 linhas) e `deploy/restore.sh` (16 linhas), ambos `sh` com `set -eu`.

`backup.sh` faz `pg_dump | gzip` para `$BACKUP_DIR/postgres-<stamp>.sql.gz` (`:11`), empacota `storage` e `projects` de `$DATA_DIR` (`:12`) e aplica retencao de 30 dias com `find -mtime +30 -delete` (`:14`). `BACKUP_DIR` default `/backups/mapa-disponibilidade` (`:4`) — fora de `/opt/mapa-disponibilidade`, logo **os backups nao sao destruidos pelo `rsync --delete` do deploy**. Detalhe favoravel.

**O que e automatico: nada.** Nenhum cron, systemd timer, `.timer`, ou agendador esta versionado (`git grep -Ei 'crontab|systemd|\.timer'` retorna apenas `docs/PLATFORM_REBUILD.md:42`). E o proprio documento admite: `docs/PLATFORM_REBUILD.md:42` lista "Ativar rotina real de backup via cron/systemd timer" como **pendencia**. `ROADMAP.md:91` empurra "backups testados" para a Fase 5.

**RPO real observavel: indeterminado, e potencialmente infinito.** Nao ha nada no repositorio que dispare um backup. Se ninguem executou `backup.sh` manualmente na VPS, o RPO e "desde o inicio do projeto". Nao e possivel determinar o estado real da VPS a partir do repositorio — **nao verificado nesta passagem**.

**RTO real observavel: indeterminado.** `restore.sh` nunca foi exercitado no CI e nao ha registro de teste de restauracao. `ROADMAP.md:91` trata "backups testados" como trabalho futuro.

**Dois defeitos concretos nos scripts (leitura estatica; nao executados nesta passagem):**
1. **`backup.sh` nao roda dentro da imagem da aplicacao.** Requer `pg_dump`, e `Dockerfile:18-20` instala apenas `libglib2.0-0 libgl1 libgomp1`. Nao ha `postgresql-client`. O script so funciona no host (se tiver client instalado) ou dentro do container `postgres:16-alpine` — o que exige ajustar `DATA_DIR`, ja que o volume `/data` nao esta montado la (`compose.yaml:10-11`). Nao ha documentacao de como invoca-lo.
2. **`restore.sh:9` (`gunzip -c "$SQL_BACKUP" | psql "$DATABASE_URL"`) nao usa `-v ON_ERROR_STOP=1`** nem limpa o schema antes. `psql` sem essa flag retorna exit 0 mesmo acumulando erros, e um dump plano aplicado sobre um banco povoado gera "relation already exists" em massa. O `set -eu` do `:2` nao protege contra isso. Restauracao pode "concluir" (`:16` imprime "Restore concluido") tendo restaurado parcialmente.

---

## observabilidade

**Achado: o vazio e total.** `git grep -Ei 'sentry|prometheus|opentelemetry|structlog|logging\.(basicConfig|getLogger)|metrics'` em `*.py`, `compose.yaml`, `Dockerfile` e `deploy/` retorna **uma unica linha**: `app_v1/api.py:307`, que e a chave `"metrics"` de um payload JSON de resposta — dado de negocio, nao instrumentacao.

Consequencias verificadas:
- **Sem logging estruturado.** Nenhum `logging.basicConfig` em todo o codigo Python. `ROADMAP.md:25` lista "logs estruturados" como item da Fase 0 — nao entregue.
- **Sem APM / rastreamento de erro.** Nenhum Sentry. Uma excecao 500 em producao so aparece se alguem rodar `docker compose logs` manualmente.
- **Sem metricas.** Sem Prometheus, sem `/metrics`.
- **Sem alertas.** Nada notifica ninguem quando algo cai. `docs/PRODUCT_SPEC.md:77` promete "monitoramento de erros e alertas" — inexistente.
- **Sem uptime check externo.** O unico health check e o interno do deploy (`deploy-vps.yml:122`) e o `HEALTHCHECK` do Docker (`Dockerfile:32-33`), ambos dentro da maquina.
- **Sem rotacao de log dos containers.** `compose.yaml` nao tem chave `logging:` (grep -> exit=1), entao vale o driver default `json-file` **sem `max-size` nem `max-file`**. Em VPS pequena, os logs crescem sem limite ate encher o disco — modo de falha que derruba Postgres e app juntos.
- Nginx grava access/error log no padrao da distro; `deploy/nginx/mapa-disponibilidade.conf` nao customiza nem referencia logrotate.

Diagnostico operacional: hoje a deteccao de incidente depende de um humano abrir o site e reparar que quebrou.

---

## higiene-do-repositorio

**Estado do git:** branch `main`, sincronizada com `origin/main`. 84 arquivos versionados, 4.04 MiB de blobs. Sem stashes, sem tags.

**Dois remotes:** `origin` -> `github.com/williammx/mapa-disponibilidade.git` e `hf` -> `huggingface.co/spaces/owillgab/mapa-disponibilidade`. O remote Hugging Face explica o `.gitattributes` (abaixo) e e um destino de publicacao paralelo que nenhuma documentacao menciona.

**Branches:** 5 branches `codex/*` locais, todas tambem em `origin` (`fix-production-project-data`, `fix-worker-health`, `ignore-vite-cache`, `platform-rebuild`, `polish-project-loading`). Sao restos de trabalho ja integrado em `main`; ninguem as podou.

### Ruido de CRLF — ALEGACAO CONFIRMADA, com numeros

```
git status --porcelain | wc -l      -> 57   (56 modificados + 1 untracked ".forja/")
git diff --stat | tail -1           -> 56 files changed, 10357 insertions(+), 10357 deletions(-)
git diff --numstat  (somado)        -> added=10357  deleted=10357
git diff --ignore-cr-at-eol --stat  -> (saida vazia)
git diff --ignore-cr-at-eol --numstat | wc -l -> 0
```

**56 arquivos, 10.357 linhas adicionadas e exatamente 10.357 removidas, e zero arquivos com qualquer alteracao real.** A simetria perfeita e a assinatura de reescrita pura de fim de linha.

Causa raiz, confirmada em dois pontos:
1. `git config core.autocrlf` -> exit=1 (nao definido). `git config --list --show-origin | grep -E 'autocrlf|eol|safecrlf'` -> exit=1, nenhuma configuracao de fim de linha em nenhum escopo.
2. `grep -nE 'text=auto|\* text' .gitattributes` -> exit=1, **ausente**. O `.gitattributes` tem 35 linhas e e integralmente boilerplate de Git LFS do Hugging Face (`*.safetensors`, `*.ckpt`, `*tfevents*`, `saved_model/**/*`) — padroes que nao correspondem a nenhum arquivo deste projeto. **ALEGACAO CONFIRMADA.**

Detalhe revelador: o proprio `.gitattributes` esta gravado com CRLF (`cat -A` mostra `^M` em todas as 35 linhas), e `.gitignore` tem **fins de linha misturados** — as linhas `!frontend/public/*.webp` e `!demo/*.html` terminam em LF puro enquanto as demais terminam em CRLF. Contraprova util: `.env.example` e integralmente LF e **nao aparece** na lista de modificados.

Custo concreto: `git diff` e inutilizavel para revisao, `git blame` sera destruido no dia em que alguem commitar esse ruido, e qualquer merge das 5 branches `codex/*` gera conflito artificial em 56 arquivos.

### Arquivos grandes versionados

| Bytes | Arquivo |
|---|---|
| 2.718.884 (2,59 MiB) | `frontend/public/hero-loteamento-aereo.png` |
| 875.892 (0,84 MiB) | `demo/setor-e-demo.html` |
| 140.489 | `pdf_to_map.py` |

Os dois primeiros somam **85% dos 4,04 MiB do repositorio**. Ambos sao deliberados: `.gitignore:23` ignora `*.html` mas `.gitignore:32` reabre `!demo/*.html`; `.gitignore:20` ignora `*.png` e `.gitignore:28` reabre `!frontend/public/*.png`. Nao ha LFS ativo para eles apesar do `.gitattributes` de LFS estar presente.

### `.gitignore` / `.dockerignore`

`.gitignore` (44 linhas) cobre corretamente `__pycache__`, `.venv`, `output/`, `data/`, `*.db`, `node_modules`, `dist`, `.vite`, `*.log`, `.env*`. Adequado. Nao cobre `.forja/` (aparece como `??`).

`.dockerignore` (20 linhas) foi escrito com semantica de **gitignore**, nao de dockerignore. Docker usa `filepath.Match` do Go, onde `*` nao atravessa `/`: logo `*.html` (`:11`) so casa arquivos na raiz, e as excecoes `!frontend/index.html` (`:15`) e `!frontend/public/**` (`:16`) sao redundantes. O efeito pratico parece benigno — `demo/*.html` entra no contexto, que e o necessario para `Dockerfile:28` (`COPY demo ./demo`) funcionar — mas o arquivo depende de um acidente de semantica, nao de intencao. **Nao verificado por build nesta passagem** (docker indisponivel).

### Configuracao orfa e nao documentada

- `APP_ENV` existe em `.env.example:1` e **nao e lido em lugar nenhum**: `git grep -n 'APP_ENV'` retorna apenas a propria linha do `.env.example`.
- Inversamente, o codigo le 8 variaveis que `.env.example` **nao documenta**: `AUTO_CREATE_TABLES`, `CONVERTER_JOB_DIR`, `DATA_DIR`, `JOB_TIMEOUT_SECONDS`, `MAX_UPLOAD_BYTES`, `PRIVATE_STORAGE_DIR`, `REDIS_URL`, `SYNC_PROCESSING`. Pelo menos `AUTO_CREATE_TABLES` e `SYNC_PROCESSING` alteram comportamento estrutural e ficam invisiveis para quem provisiona a VPS.
- `alembic.ini:5` fixa `sqlalchemy.url = sqlite:///./mapa.db`. `alembic/env.py:18` usa `os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url"))` — ou seja, **se `DATABASE_URL` faltar, o `alembic upgrade head` do boot migra silenciosamente um SQLite local em vez de falhar**. Falha silenciosa que produz um app aparentemente saudavel apontando para banco vazio.

### Dependencias

`requirements.txt` (17 linhas): **todas as 16 dependencias usam `>=` sem teto** (`pymupdf>=1.24`, `fastapi>=0.110`, `sqlalchemy>=2.0`, `opencv-python-headless>=4.10`, ...). Nao existe lockfile Python — `git ls-files | grep -Ei 'lock|constraint|poetry|pipfile|pyproject|uv\.'` retorna somente `frontend/package-lock.json`. **ALEGACAO CONFIRMADA.** Como o build ocorre na VPS a cada deploy (`deploy-vps.yml:119`) e `Dockerfile:23` roda `pip install` sem constraints, **dois deploys do mesmo commit podem produzir imagens diferentes**, e o CI valida um conjunto de versoes enquanto producao instala outro. O frontend esta melhor servido: `package-lock.json` versionado e `npm ci` tanto no CI (`:49`) quanto no Dockerfile (`:5`).

`design-qa.md:2-11` versiona caminhos absolutos da maquina do desenvolvedor (`C:\Users\willi\...`, incluindo um arquivo de clipboard em `Temp`) e aponta como evidencia arquivos em `output/`, que e ignorado pelo git (`.gitignore:9`). O documento cita provas que nao existem para mais ninguem.

---

## dividas-e-riscos

Priorizado por dano esperado.

1. **Deploy irreversivel sobre banco sem backup.** `deploy-vps.yml:112` (`rsync --delete`) + `:130-132` (falha sem rollback) + zero invocacao de `backup.sh` + `alembic upgrade head` automatico no boot (`Dockerfile:34`). Custo de manter: uma migration ruim = perda permanente de dados de clientes, sem ponto de restauracao e sem caminho de volta. Recuperacao so por reconstrucao manual.
2. **Migrations nunca testadas contra Postgres.** CI usa SQLite em memoria (6 ocorrencias em `tests/`), producao usa Postgres (`compose.yaml:32`), e o CI nao roda alembic. A primeira execucao real de toda migration e em producao. Custo: o `validate` verde nao diz nada sobre o risco que mais importa.
3. **Backup inexistente na pratica.** Scripts existem, agendamento nao (`docs/PLATFORM_REBUILD.md:42` admite). RPO indeterminado/infinito, RTO indeterminado, `restore.sh` nunca exercitado e com o defeito de `ON_ERROR_STOP` (`restore.sh:9`). Custo: nao existe garantia de recuperacao, so a aparencia dela.
4. **Observabilidade zero.** Nenhum log estruturado, APM, metrica, alerta ou uptime externo. Custo: MTTD igual ao tempo ate um cliente reclamar; diagnostico so por SSH.
5. **Config de TLS fora do versionamento.** `deploy/nginx/mapa-disponibilidade.conf` so tem `:80` enquanto producao serve HTTPS. Custo: a VPS nao e reconstruivel a partir do repo, e a config real nunca passou por revisao.
6. **Health gate cego para Nginx, TLS e worker.** `deploy-vps.yml:122` bate em `127.0.0.1:8000`; `compose.yaml:53-54` desliga o healthcheck do worker. Custo: deploy verde com site fora do ar ou fila de processamento morta.
7. **Build na VPS sem limites de recurso.** `deploy-vps.yml:119` + `compose.yaml` sem `mem_limit`/`cpus`. Node 22 + `npm ci` + compilacao de opencv/pymupdf concorrendo com Postgres em producao. Custo: risco de OOM durante o deploy, derrubando o banco.
8. **Build Python nao reproduzivel.** `requirements.txt` 100% `>=`, sem lockfile. Custo: quebras espontaneas em deploys que nao mudaram uma linha de codigo.
9. **56 arquivos de ruido CRLF.** `core.autocrlf` ausente + `.gitattributes` sem `* text=auto`. Custo: diffs ilegiveis, blame futuro destruido, conflito artificial nas 5 branches `codex/*`.
10. **Container root, sem `cap_drop`, sem `read_only`.** `Dockerfile` sem `USER`. Custo: escape de container a partir de parsing de PDF de terceiros vira root na VPS.
11. **Defaults inseguros no compose.** `SESSION_COOKIE_SECURE:-false` (`:34`), `POSTGRES_PASSWORD:-mapa-local` (`:9`). Custo: um `.env` incompleto degrada seguranca em silencio, sem erro.
12. **Fallback de SQLite no alembic.** `alembic.ini:5` + `alembic/env.py:18`. Custo: `DATABASE_URL` ausente nao falha — migra o banco errado.
13. **Logs de container sem rotacao.** Sem `logging:` em `compose.yaml`. Custo: disco cheio a prazo, derrubando tudo.
14. **README descreve outro sistema.** Custo: onboarding errado; seguir o README sobe ambiente com senha default publicada.
15. **Branches `codex/*` e remote `hf` orfaos.** Custo baixo, mas ambiguidade sobre onde producao realmente vive.

---

## oportunidades-de-melhoria

Ordenado por impacto ÷ esforco. **Nada implementado nesta passagem — sao recomendacoes.**

1. **Backup antes do `rsync`, dentro do script remoto.** Em `deploy-vps.yml`, entre `:111` e `:112`, invocar `deploy/backup.sh` (via `docker compose exec -T db pg_dump`, ja que a imagem do app nao tem `pg_dump`) e abortar o deploy se falhar. Uma dezena de linhas transforma o item de risco #1 em recuperavel. **Maior ganho por linha em todo o repositorio.**
2. **Neutralizar o CRLF de uma vez.** Adicionar `* text=auto eol=lf` ao `.gitattributes` (que hoje e so boilerplate de LFS irrelevante) e normalizar em um commit unico e isolado. Elimina 56 arquivos de ruido e devolve utilidade ao `git diff`. Esforco: um commit.
3. **Health check externo no gate.** Em `deploy-vps.yml:121-128`, acrescentar uma verificacao a `https://map.eterhub.com.br/health` a partir do runner do GitHub, depois do check em loopback. Passa a cobrir Nginx, TLS e DNS. Esforco: ~4 linhas.
4. **Rodar migrations no CI contra Postgres real.** Adicionar `services: postgres:16` ao job `validate` e um step `alembic upgrade head`. Fecha a lacuna #2 sem tocar em codigo de aplicacao. Esforco: ~10 linhas de YAML.
5. **Rotacao de log dos containers.** Adicionar bloco `logging: {driver: json-file, options: {max-size: "10m", max-file: "3"}}` aos quatro servicos de `compose.yaml`. Remove um modo de falha de disco cheio. Esforco: 4 blocos identicos.
6. **`SESSION_COOKIE_SECURE` default seguro.** Trocar `compose.yaml:34` para `${SESSION_COOKIE_SECURE:-true}` e remover o default `mapa-local` de `:9`, `:32`, `:57` para forcar erro explicito quando o `.env` estiver incompleto. Esforco: 4 linhas.
7. **Limites de recurso.** Adicionar `mem_limit`/`cpus` ao servico `worker` e ao `mapa-disponibilidade` em `compose.yaml`. Impede que um PDF patologico ou o build derrube o Postgres. Esforco: 4 linhas.
8. **Type-check no CI.** Acrescentar `npx tsc --noEmit` ao job `validate` (apos `:49`) ou compor em `frontend/package.json:8`. Como `vite build` nao verifica tipos, hoje erros de TS chegam a producao. Esforco: 1 linha.
9. **Versionar a config real de TLS.** Trazer o bloco `:443` efetivo da VPS para `deploy/nginx/mapa-disponibilidade.conf`, com redirect 301 de `:80` e HSTS. Torna a VPS reconstruivel e revisavel. Esforco: baixo; exige acesso a VPS para copiar a config vigente.
10. **Congelar dependencias Python.** Gerar `requirements.lock` (pip-compile ou `uv pip compile`) a partir de `requirements.txt` e usa-lo em `Dockerfile:23`. Torna o build reproduzivel entre CI e VPS. Esforco: medio (uma vez), manutencao continua.
11. **Usuario nao-root.** Adicionar `useradd` + `USER` ao final do `Dockerfile` e `--chown` nos `COPY` das linhas `:25-29`. Esforco: medio (precisa acertar permissoes de `/data`).
12. **Mover o build para o CI.** Construir a imagem no runner, publicar em registry (GHCR) e a VPS so fazer `docker compose pull && up -d`. Resolve OOM (#7), acelera o deploy e **viabiliza rollback por tag de imagem** — o caminho estrutural para o risco #1. Maior esforco da lista, maior retorno arquitetural.
13. **Reativar healthcheck do worker.** Substituir `compose.yaml:53-54` (`disable: true`) por uma sonda real de RQ. Torna visivel a fila morta.
14. **Sincronizar `.env.example` com o codigo.** Documentar as 8 variaveis lidas e ausentes; remover `APP_ENV`, que nao e lido por ninguem. Esforco: minutos.
15. **Endurecer `restore.sh:9`** com `psql -v ON_ERROR_STOP=1` e exercitar a restauracao ao menos uma vez, registrando o RTO medido.
16. **Podar as 5 branches `codex/*`** (locais e em `origin`) apos confirmar integracao em `main`.

---

## fora-de-escopo

Nao inspecionado nesta passagem, por pertencer a outros dominios ou por indisponibilidade de ambiente:

- Logica de `api.py`, `app_v1/*`, `pdf_to_map.py`, `auth.py`, `models.py`, `database.py` — outros arqueologos. `api.py:191-194` foi lido apenas para determinar o que o health check do deploy realmente valida.
- `frontend/src/**` — outro arqueologo. `frontend/package.json` foi lido apenas para determinar o que o CI executa.
- Conteudo e cobertura dos testes em `tests/` — lidos somente para identificar o backend de banco usado pelo CI (SQLite).
- `docs/BRAND.md` e as partes de produto/UX de `docs/PRODUCT_SPEC.md` e `ROADMAP.md`.
- **Estado real da VPS**: config de Nginx vigente, existencia de crontab, presenca de backups em `/backups`, RAM disponivel, versao do Docker, validade do certificado. Nada disso e observavel a partir do repositorio — **nao verificado nesta passagem**.
- **`docker compose config` nao executado**: `docker` indisponivel no ambiente de inspecao (exit=127).
- Historico de execucoes do workflow no GitHub Actions (taxa de sucesso, duracao, incidencia de OOM) — requer acesso a API do GitHub.
- O remote `hf` (Hugging Face Space): existe, mas seu papel no fluxo de entrega nao esta documentado em lugar nenhum do repo — **nao verificado**.

---

## veredicto

**FAIL**

Justificativa. O pipeline nao e amador — ha `validate` antes de `deploy`, `environment: production`, concorrencia serializada, `known_hosts` fixado, pre-condicao de `.env`, health check que toca o banco de verdade, segredos fora do versionamento e volumes nomeados que protegem os dados do `rsync --delete`. Isso e mais rigor do que a media de projetos deste porte.

O veredicto e FAIL por causa de uma combinacao especifica e demonstrada, nao por acumulo de itens menores:

1. `deploy-vps.yml:112` apaga a release anterior (`rsync --delete`) **antes** de construir a nova;
2. `Dockerfile:34` e `compose.yaml:55` executam `alembic upgrade head` automaticamente no boot;
3. nenhuma migration jamais roda contra Postgres antes de producao (CI usa `sqlite:///:memory:`);
4. nenhum backup e tirado antes do deploy, e nenhum backup automatico existe (`docs/PLATFORM_REBUILD.md:42` confirma a pendencia);
5. `deploy-vps.yml:130-132` nao tem rollback.

Encadeados, esses cinco fatos descrevem um sistema em que **uma unica migration defeituosa provoca perda irreversivel de dados de clientes reais**, sem ponto de restauracao, sem caminho de volta e sem alerta — porque a observabilidade tambem e nula. Para um MVP interno seria CONCERNS. Para a plataforma B2B com dados de imobiliarias descrita em `ROADMAP.md:5`, e FAIL.

O caminho de saida e curto e desproporcionalmente barato: as oportunidades 1, 3 e 4 (backup pre-deploy, health check externo, migrations no CI contra Postgres) somam algo em torno de 25 linhas de YAML e desarmam os riscos 1, 2 e 6. A oportunidade 12 (build no CI + registry) converte o rollback de inexistente em um `docker compose pull` de tag anterior.
