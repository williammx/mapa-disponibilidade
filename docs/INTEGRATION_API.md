# NexoLote — API de integrações v1

## Estado
Implementada no código local. Exige migration Alembic antes do uso. Não confundir disponibilidade local com deploy em produção.

## Autenticação
Envie `Authorization: Bearer <chave>` em todas as chamadas externas. Nunca inclua a chave em URL, frontend público ou repositório. Cada chave é limitada a uma organização e opcionalmente a um projeto; o servidor guarda somente seu hash. O segredo é entregue uma única vez.

Um administrador autenticado pelo portal cria a chave em `POST /api/v1/integration-api-keys` com JSON:

```json
{"name":"ERP","organization_id":"ID_ORGANIZACAO","project_id":"ID_PROJETO","scopes":["capabilities:read","jobs:write","jobs:read","jobs:cancel","results:read"]}
```

Validade padrão 90 dias; `expires_at` opcional em ISO 8601, no máximo 365 dias. Liste metadados em `GET /api/v1/integration-api-keys?organization_id=...`; revogue em `DELETE /api/v1/integration-api-keys/{key_id}`. A gestão usa sessão administrativa, não a chave externa.

## Fluxo
1. Crie o cliente no portal e a chave em `/app/integracoes`. Crie o projeto via `POST /api/integrations/v1/projects` com `name`, `slug` e `description` opcional, ou use um projeto existente.
2. Envie o PDF por multipart para `POST /api/integrations/v1/projects/{project_id}/jobs?quality=balanced`, campo `upload`. Resposta 202 com `job.id`.
3. Consulte `GET /api/integrations/v1/jobs/{job_id}` periodicamente até `status=succeeded` ou `failed`.
4. Baixe `GET /api/integrations/v1/jobs/{job_id}/results/html` ou consulte `/results/lots`.

### Exemplo curl
```bash
# Configure NEXOLOTE_API_KEY no ambiente, sem gravar a chave neste arquivo.
BASE=https://map.eterhub.com.br
curl --fail-with-body -H "Authorization: Bearer $NEXOLOTE_API_KEY" "$BASE/api/integrations/v1/capabilities"
curl --fail-with-body -H "Authorization: Bearer $NEXOLOTE_API_KEY" -F 'upload=@planta.pdf;type=application/pdf' "$BASE/api/integrations/v1/projects/ID_PROJETO/jobs?quality=balanced"
curl --fail-with-body -H "Authorization: Bearer $NEXOLOTE_API_KEY" "$BASE/api/integrations/v1/jobs/ID_JOB"
curl --fail-with-body -H "Authorization: Bearer $NEXOLOTE_API_KEY" "$BASE/api/integrations/v1/jobs/ID_JOB/results/html" -o mapa.html
```

## Contratos e limites
- `GET /capabilities`: formatos, qualidades, teto de upload e permissões.
- Qualidades: light, balanced, sharp, high, optimized.
- Teto padrão 80 MiB, configurável por `MAX_UPLOAD_BYTES`; o proxy também deve limitar o corpo antes da leitura multipart.
- PDFs inválidos, danificados ou criptografados são recusados.
- `POST /jobs/{job_id}/cancel`: somente queued; processamento já em execução retorna 409.
- Resultados antes do término retornam 409.
- 401: chave ausente/inválida/expirada/revogada; 403: escopo insuficiente; 404: recurso inexistente ou fora do limite da chave; 413: arquivo acima do teto; 422: entrada inválida.
- JSON de lotes contém geometria em coordenadas locais da página PDF, não latitude/longitude. GeoJSON georreferenciado não está disponível.
- O HTML é artefato para download com CSP sandbox. Não é link publicado nem convite de cliente; publicação segue o fluxo do portal.
- Esta versão inclui criação externa de projetos, idempotência e limite persistido por chave. Não inclui webhooks nem SDK: use HTTP e polling.

## Implantação
Aplicar `alembic upgrade head` com backup antes de ativar app e worker. Migrations até `20261005_0004_integration_requests.py`. Não criar chaves de produção em testes nem guardar segredos na documentação.

## Recursos adicionais da versão concluída
- GET/POST `/api/integrations/v1/projects`: listar/criar; GET/PATCH `/projects/{id}`: consultar/alterar nome e descrição. Escopos `projects:read` e `projects:write`. Chave vinculada a projeto não cria outros.
- Header `Idempotency-Key` no upload: mesma chave, projeto, PDF e opções retornam o job original; conteúdo divergente retorna 409. Reserva interrompida antes de criar job pode exigir revisão operacional para não arriscar duplicação.
- POST `/jobs/{id}/retry`: repete jobs failed/cancelled, escopo `jobs:write`.
- POST `/projects/{id}/publish`: escopo `publications:write`, corpo `access_mode` (private/unlisted/password/public), `password` quando necessário, `allow_edit=false`, `require_clean_validation=true`. Publicação reutiliza o fluxo transacional existente.
- GET/POST `/projects/{id}/share-links` e DELETE `/share-links/{id}`: escopos `shares:read/write`. Corpo de criação: `access_mode` token/password/private, `password`, `expires_at` opcional, `allow_edit=false`. Use a URL retornada pela API.
- Lotes paginados: `limit` 1–500, `offset` e `next_offset`. Não confundir total com tamanho da página.
- Export `/results/geojson?page_local=true`: formato semelhante a GeoJSON explicitamente não geográfico, `non_geographic=true`, `rfc7946_compliant=false`, coordenadas do canvas e page_index 0. Nunca tratar como WGS84.
- Limite padrão 120 chamadas/minuto/chave (`INTEGRATION_RATE_LIMIT_PER_MINUTE`); HTTP 429 inclui Retry-After. HTTP 503 indica indisponibilidade.
- Console OpenAPI em `/api/integrations/v1/docs`, contrato em `/api/integrations/v1/openapi.json`, expondo somente a API externa. O segredo vem do ambiente via `Authorization: Bearer $NEXOLOTE_API_KEY`, nunca embutido no frontend público.
