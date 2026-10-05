# NexoLote — API de integrações v1

## Estado
Disponível em produção em `https://map.eterhub.com.br/api/integrations/v1`. A implantação aplica as migrations Alembic com backup. Gestão de chaves em `/app/integracoes`, exclusiva de administradores da plataforma.

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
- O HTML é artefato para download com CSP sandbox. Não é link publicado nem convite de cliente; use `/projects/{id}/publish` e os endpoints de compartilhamento para entregar o mapa somente leitura.
- Esta versão inclui criação externa de projetos, idempotência, disponibilidade comercial, eventos e webhooks. Não inclui SDK nem adaptador de fornecedor específico.

## Implantação
Aplicar `alembic upgrade head` com backup antes de ativar app, worker e `webhook-dispatcher`. Migrations até `20261005_0006_integration_webhooks.py`. Testes de produção usam somente chaves temporárias revogadas ao terminar, sem registrar seus segredos.

Aplicação e dispatcher compartilham `WEBHOOK_MASTER_KEY_FILE=/data/private/webhook-master.key` no volume persistente `mapa_project_data`. O arquivo é privado e não deve ser apagado, substituído ou incluído em repositórios. O backup operacional precisa incluir esse arquivo protegido além do banco; perder a chave muda os segredos derivados das assinaturas.

## Sincronização de disponibilidade

Todos os caminhos abaixo são relativos a `/api/integrations/v1`.

| Operação | Caminho | Escopo |
|---|---|---|
| Listar unidades canônicas | `GET /projects/{project_id}/units` | `units:read` |
| Vincular unidade externa a um lote | `POST /projects/{project_id}/units/bind` | `units:write` |
| Definir referência externa | `PUT /projects/{project_id}/units/{unit_id}/external-reference` | `units:write` |
| Atualizar disponibilidade | `PATCH /projects/{project_id}/units/{unit_id}/availability` | `units:write` |
| Consultar eventos | `GET /projects/{project_id}/events` | `events:read` |

1. Consulte os lotes persistidos da conversão e confirme sua identidade comercial. Um índice extraído do PDF não identifica a mesma unidade em futuras versões.
2. Vincule com `{"external_system":"crm","external_unit_id":"UNIDADE-01","lot_id":"ID_LOTE"}`. Guarde o `unit.id` retornado.
3. Na venda, envie `{"status":"sold","expected_revision":0,"event_id":"VENDA-123","source":"crm","reason":"Venda confirmada"}` para a unidade. Use a revisão realmente consultada, não sempre zero.
4. Estados aceitos: `available`, `reserved`, `sold`, `blocked`. Cada mudança incrementa a revisão e registra evento na mesma transação. HTTP 409 exige consultar o estado atual e resolver o conflito; não sobrescrever cegamente.
5. Repetir o mesmo evento e conteúdo devolve a resposta registrada sem reaplicar o estado antigo. Reutilizar seu identificador com conteúdo diferente é conflito.

Unidades pertencem ao projeto e mantêm vínculos históricos. Correspondência entre versões depende de nomes/quadras únicos confiáveis ou de reconciliação explícita. Lotes incertos ficam bloqueados até resolução; uma nova conversão ou edição desatualizada não deve reabrir vendas. A listagem usa `limit` 1–200, `offset`, `total` e `next_offset`. Eventos usam `after`, `limit`, `next_cursor` e `has_more`.

Mapas públicos e downloads consultam a disponibilidade atual ao serem carregados. Uma aba já aberta precisa ser recarregada pelo consumidor; não há atualização automática por WebSocket. Mudanças de geometria continuam exigindo uma nova versão/publicação.

## Webhooks

- `GET/POST /projects/{project_id}/webhooks`, escopo `webhooks:write`. Criação: `{"url":"https://seu-dominio.example/webhook","event_types":["unit.availability.changed"]}`.
- A criação retorna `{webhook,secret}`; o segredo aparece somente nessa resposta. Armazene-o no backend receptor. Não é a chave Bearer da API.
- `DELETE /webhooks/{webhook_id}` desativa a assinatura.
- `GET /webhooks/{webhook_id}/deliveries`, escopo `events:read`, lista entregas paginadas com `limit` 1–200, `offset`, `total` e `next_offset`.
- `POST /webhooks/{webhook_id}/deliveries/{delivery_id}/retry`, escopo `webhooks:write`, solicita reenvio de entrega elegível.
- O portal `/app/integracoes` permite gestão administrativa via cookie de sessão, sem expor Bearer no navegador.

Envelope: `{id,type,organization_id,project_id,created_at,data}`. O tipo atual é `unit.availability.changed`; `data` conserva a proveniência da alteração. Eventos anteriores retidos também podem ser entregues ao criar uma assinatura.

Assinatura HMAC-SHA256 sobre `timestamp + "." + corpo_JSON_original`, usando os bytes UTF-8 do segredo retornado. Cabeçalhos: `X-NexoLote-Timestamp`, `X-NexoLote-Signature` no formato `v1=<hex>`, `X-NexoLote-Delivery-Id` e `X-NexoLote-Event-Id`. Verifique antes de interpretar o JSON, compare em tempo constante e rejeite timestamps fora de uma janela curta, por exemplo cinco minutos.

O receptor deve registrar o evento de maneira durável e responder 2xx. A entrega é pelo menos uma vez: deduplique por evento e não gere uma atualização de retorno para o mesmo evento sem necessidade. O dispatcher independente tenta até oito vezes, com espera exponencial limitada a uma hora. Entrega duplicada após falha ou reinício é possível; não existe garantia de exatamente uma vez.

Destinos precisam ser HTTPS na porta 443, sem credenciais ou fragmentos. Endereços privados, locais e reservados são bloqueados, incluindo resolução DNS na entrega; redirecionamentos não são seguidos. Revogar a chave que criou uma assinatura impede futuras entregas dela: recrie a assinatura ao trocar essa chave.

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
