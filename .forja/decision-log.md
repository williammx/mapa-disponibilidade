# Decision log — FORJA

## 2026-08-12 — Entrada em modo REFORMULAR
- Triagem detectou codigo-fonte sem `.forja/` => brownfield.
- Modo escolhido pelo usuario: revisao completa de front, admin, motor e editor => REFORMULAR.
- Ralph (loop autonomo) PROIBIDO: regra greenfield-only. Todo dev sera supervisionado (Fase 6).
- Branch isolada ainda NAO criada: arqueologia e read-only e nao exige branch.

## 2026-08-13 — Opcao 1 (Cirurgia de producao) executada e publicada
Usuario escolheu: Opcao 1, direto na main, com normalizacao de CRLF.
Commits: 9a8ba8f (correcoes) e 1d33623 (deploy que publica de verdade).

Achado nao previsto pela arqueologia: o passo "Activate release" rodava o script
remoto por heredoc na stdin do ssh. Ele terminava em 2 segundos, sem imprimir
uma linha, e era marcado como sucesso. Producao seguia servindo codigo antigo
depois de deploys verdes — inclusive o deploy anterior (e8c89a7). Corrigido em
1d33623 com o script em deploy/remote-release.sh e conferencia de md5 do api.py
dentro do container.

Verificado em producao apos 1d33623:
- /openapi.json e /docs -> 404 (eram publicos)
- POST /converter/jobs -> devolve owner_token; map_url carrega ?token=
- POST /converter/jobs/{id}/publish sem token -> 403 (era 200)
- backup pre-deploy gerado: 56K gzip
- health externo em https://map.eterhub.com.br/health -> 200

Pendente da Opcao 1 (nao executado): rate limit em login e senha de link
(SEC-6), guard de role em /app/admin, tela de troca de senha, aba Validacao
ligada ao backend.

Fase 5 do plano (ponto de decisao): reavaliar Opcao 2 (fundacao unica) e
Opcao 3 (site/painel/editor com ui-deil e ss-imagegen) sobre a base ja estancada.
