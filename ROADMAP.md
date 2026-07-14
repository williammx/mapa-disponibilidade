# Roadmap do produto

## Objetivo

Transformar o conversor de PDFs em uma plataforma B2B para imobiliarias. A equipe interna gera, revisa e publica mapas. Cada cliente acessa somente os seus empreendimentos por um link personalizado e por uma conta protegida.

## Marco atual

- Conversor de PDF vetorial para mapa interativo.
- Editor manual de lotes, cores, opacidade, rotulos e status.
- Publicacao inicial em VPS com Docker e Nginx.
- Ainda sem banco de dados, login, projetos persistentes ou portal do cliente.

## Fase 0 - Base de produto e seguranca

**Objetivo:** preparar a aplicacao para dados persistentes e acesso privado.

- Separar interface, API e motor de processamento sem alterar o algoritmo validado.
- Criar banco PostgreSQL, migrations e ambiente de configuracao por variaveis.
- Criar armazenamento privado para PDFs, imagens de fundo e versoes publicadas.
- Adicionar logs estruturados, limites de upload, validacao de PDF, rate limit e backups.
- Configurar dominio, HTTPS e Cloudflare antes de liberar clientes externos.

**Entrega:** ambiente seguro e reproduzivel, pronto para guardar dados reais.

## Fase 1 - Identidade, clientes e permissoes

**Objetivo:** cada pessoa entra em uma conta e ve somente o que foi autorizado.

- Login, logout, recuperar senha, convite por email e troca obrigatoria de senha inicial.
- Organizacoes para representar cada imobiliaria ou cliente.
- Perfis: administrador da plataforma, operador interno, administrador do cliente, colaborador do cliente e visitante de link.
- Isolamento total por organizacao: uma imobiliaria nunca consulta projetos de outra.
- Sessao segura, senha com hash, expiracao de convite, auditoria de login e bloqueio de conta.

**Entrega:** portal privado com usuarios e clientes separados.

## Fase 2 - Projetos e fluxo operacional interno

**Objetivo:** transformar a geracao atual em um processo controlado de entrega.

- Cadastro de cliente, empreendimento e projeto.
- Upload do PDF, configuracao de qualidade e criacao de tarefa de processamento.
- Fila com progresso real, logs, cancelamento, reprocessamento e tratamento de falha.
- Editor interno para revisar geometria, corrigir lotes, importar status e salvar rascunhos.
- Versoes do mapa: rascunho, em revisao, publicado, pausado e arquivado.
- Checklist de qualidade antes da publicacao: lotes sem nome, geometrias invalidas, lotes agrupados e lotes nao mapeados.

**Entrega:** a equipe consegue produzir um mapa, revisar e aprovar sem depender de arquivos HTML soltos.

## Fase 3 - Publicacao e portal do cliente

**Objetivo:** entregar o mapa pronto ao cliente por um endereco profissional e controlado.

- URL previsivel por projeto, por exemplo `app.seudominio.com/p/residencial-aurora`.
- Acesso privado por login individual para usuarios da imobiliaria.
- Links compartilhaveis opcionais com token, expiracao, senha e permissao somente leitura.
- Controles de acesso do projeto: privado, compartilhado por link, publico ou pausado.
- Botao de bloquear/desbloquear a entrega sem excluir o projeto nem perder historico.
- Area do cliente com lista de empreendimentos, busca, mapa, filtros, detalhes do lote e status atual.
- Personalizacao por cliente: nome, logotipo, cor e dominio proprio em etapa posterior.

**Entrega:** o cliente recebe um link, entra com sua conta e ve apenas os mapas liberados para ele.

## Fase 4 - Edicao e confiabilidade do mapa

**Objetivo:** reduzir falhas de extracao e dar controle suficiente para concluir qualquer mapa.

- Detecao de cobertura incompleta e indicacao visual de areas que exigem revisao.
- Ferramentas de editar, selecionar por caixa, desenhar, apagar, dividir, unir e ajustar vertices.
- Edicao em lote de status, cor, nome e metadados.
- Historico de alteracoes e restauracao de versao publicada anterior.
- Conjunto de PDFs de regressao com metricas de lotes, cobertura, tempo e memoria.
- Processamento em segundo plano para nao travar a interface nem a requisicao web.

**Entrega:** cada projeto pode ser corrigido e publicado com rastreabilidade, mesmo quando a extracao automatica nao for perfeita.

## Fase 5 - Operacao comercial e escala

**Objetivo:** suportar varios clientes e uma operacao recorrente.

- Painel administrativo: clientes, usuarios, projetos, fila, capacidade, erros e acessos.
- Importacao CSV/XLSX de disponibilidade e exportacoes.
- Comentarios, solicitacoes de alteracao e notificacoes por email.
- Relatorios por projeto e cliente: acessos, lotes por status e atividade recente.
- API e webhooks para CRM, site da imobiliaria ou outras integracoes.
- Politica de retencao de arquivos, backups testados, monitoramento e plano de recuperacao.

**Entrega:** produto operavel por equipe, com visibilidade comercial e tecnica.

## Ordem de implementacao recomendada

1. Fase 0: banco, arquivos privados, dominio e seguranca basica.
2. Fase 1: login, organizacoes e permissoes.
3. Fase 2: projetos persistentes e fluxo de producao interno.
4. Fase 3: link de entrega e portal do cliente.
5. Fase 4: aprimoramentos do motor e do editor.
6. Fase 5: automacao, escala e integracoes.

Nao vale iniciar por pagamentos, CRM ou integracoes antes de as fases 0 a 3 entregarem um fluxo confiavel de criar, publicar e consultar um projeto privado.
