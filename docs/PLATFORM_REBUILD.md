# Reconstrucao da plataforma

## Entregue nesta iteracao

- Frontend React/Vite com rotas publicas e internas.
- Landing page principal no dominio raiz.
- FastAPI modular com novas rotas em `/api/v1`.
- Migrations Alembic em `alembic/`.
- Redis + RQ configurados no `compose.yaml`.
- Worker de processamento em `app_v1.worker`.
- Armazenamento privado em `PRIVATE_STORAGE_DIR`.
- Novos recursos persistentes:
  - `file_assets`
  - `processing_jobs`
  - `lots`
  - `edit_proposals`
  - campos novos em `project_versions` e `share_links`
- Links de compartilhamento com senha, expiracao, revogacao, contagem de acesso e permissao de proposta.
- Validacao de lotes persistidos com problemas navegaveis pela API.
- Scripts de backup/restauracao em `deploy/backup.sh` e `deploy/restore.sh`.

## Fluxo operacional v1

1. Criar organizacao.
2. Criar projeto.
3. Enviar PDF em `/api/v1/projects/{project_id}/files`.
4. Criar job em `/api/v1/projects/{project_id}/processing-jobs`.
5. Acompanhar progresso em `/api/v1/processing-jobs/{job_id}`.
6. Validar versao em `/api/v1/project-versions/{version_id}/validate`.
7. Corrigir lotes em `/api/v1/lots/{lot_id}` ou `/api/v1/lots/batch`.
8. Publicar versao em `/api/v1/project-versions/{version_id}/publish`.
9. Criar link em `/api/v1/projects/{project_id}/share-links`.
10. Receber proposta em `/api/v1/projects/{project_id}/edit-proposals`.

## Pendencias para a entrega comercial completa

- Trocar completamente o dashboard mockado por dados v1 em todos os estados.
- Implementar frontend do wizard de criacao de projeto e tela real de progresso do job.
- Migrar o editor HTML legado para salvar lotes via `/api/v1/lots`.
- Criar UI do painel de problemas e propostas de edicao.
- Rodar migrations e testes dentro do ambiente da VPS.
- Ativar rotina real de backup via cron/systemd timer.
