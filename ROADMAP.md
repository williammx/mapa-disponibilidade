# Roadmap

## Fase 1 - Publicacao do MVP

- Containerizar a API e publicar na VPS.
- Usar Nginx como proxy reverso e Cloudflare para DNS, HTTPS e protecao.
- Configurar logs, reinicio automatico, monitoramento e backup basico.

## Fase 2 - Projetos persistentes

- Login, permissoes e organizacoes.
- Banco PostgreSQL para projetos, lotes e historico.
- Armazenamento privado de PDFs e mapas gerados.

## Fase 3 - Confiabilidade do mapeamento

- Fila de processamento com progresso real e recuperacao de falhas.
- Revisao de lotes ausentes, agrupados ou com geometria invalida.
- Edicao manual: dividir, unir, redesenhar e ajustar vertices.
- Regressao automatizada com PDFs de referencia.

## Fase 4 - Operacao comercial

- Importacao CSV/XLSX, compartilhamento e trilha de auditoria.
- Exportacoes, integracoes e relatorios.
- Monitoramento, limites de uso, backups testados e atualizacoes seguras.
