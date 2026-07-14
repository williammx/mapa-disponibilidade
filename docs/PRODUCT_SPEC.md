# Especificacao do produto

## Proposta

A plataforma entrega mapas de disponibilidade para imobiliarias. A operacao interna recebe o PDF, gera o mapa, corrige o que for necessario e publica uma versao controlada. O cliente acessa somente os seus empreendimentos pelo portal.

## Perfis de acesso

| Perfil | Pode fazer |
| --- | --- |
| Administrador da plataforma | Gerenciar toda a operacao, clientes, usuarios, projetos, configuracoes e acessos. |
| Operador interno | Criar projetos, processar PDFs, editar mapas e publicar conforme permissao. |
| Administrador do cliente | Ver projetos da propria organizacao, convidar colaboradores e administrar links do cliente. |
| Colaborador do cliente | Consultar os projetos liberados, usar filtros e exportar quando permitido. |
| Visitante de link | Consultar somente um projeto publicado por link, sem editar. |

## Ciclo de vida de um projeto

1. O administrador cria a imobiliaria e seus usuarios.
2. Um operador cria o empreendimento e o projeto.
3. O PDF e enviado e entra na fila de processamento.
4. O operador revisa o resultado e corrige a geometria no editor.
5. O projeto fica `em revisao` ate ser aprovado.
6. Ao publicar, o sistema cria uma versao imutavel e libera o acesso configurado.
7. O cliente recebe convite de conta ou link compartilhavel.
8. O administrador pode pausar, substituir por nova versao ou arquivar o projeto a qualquer momento.

## Regras de acesso e entrega

- A senha pertence a uma pessoa, nunca ao link do projeto.
- O acesso privado exige login e associacao do usuario a uma organizacao.
- Link compartilhavel usa token aleatorio, pode ter senha, data de expiracao e somente leitura.
- Projeto pausado retorna uma pagina de indisponibilidade, sem apagar seus dados.
- Projeto publico deve ser uma escolha explicita do administrador da plataforma.
- Todo acesso, publicacao, alteracao de permissao e download relevante entra em trilha de auditoria.

## Areas da aplicacao

### Portal interno

- Dashboard de operacao: fila, falhas, projetos pendentes e atividade recente.
- Clientes: organizacoes, contatos, usuarios, marca e situacao de acesso.
- Projetos: empreendimentos, PDFs, versoes, status de entrega e links.
- Editor de mapa: ferramentas de cor, selecao, desenho, divisao, uniao, vertices e validacao.
- Publicacao: permissao, estado, URL, expiracao e historico de versoes.
- Administracao: usuarios internos, configuracoes, auditoria e saude do sistema.

### Portal do cliente

- Login e recuperacao de senha.
- Pagina inicial com os empreendimentos liberados.
- Visualizador responsivo do mapa com busca, filtros e detalhes dos lotes.
- Indicacao clara da data e versao publicada.
- Gestao de equipe para administradores do cliente, se liberada.

## Dados principais

- `organizations`: imobiliarias ou clientes.
- `users`: pessoas que entram na plataforma.
- `memberships`: vinculo entre usuario, organizacao e perfil.
- `projects`: empreendimento, estado de entrega e configuracao de acesso.
- `project_versions`: rascunhos e versoes publicadas do mapa.
- `lots`: geometria, identificacao, status e metadados por versao.
- `files`: PDF original, imagem de fundo, exportacoes e anexos.
- `share_links`: tokens de compartilhamento, permissoes e expiracao.
- `audit_events`: eventos de seguranca e alteracoes relevantes.
- `processing_jobs`: processamento, progresso, logs e resultado.

## Arquitetura alvo

- Frontend web com area interna e portal do cliente.
- API FastAPI na VPS, mantendo o motor Python atual como servico de processamento.
- PostgreSQL para dados transacionais.
- Worker de fila para conversoes, fora das requisicoes HTTP.
- Armazenamento privado compativel com S3 para PDFs e artefatos gerados.
- Nginx na VPS, Cloudflare para DNS, HTTPS, protecao e cache de arquivos publicos.
- Backups de banco e arquivos, monitoramento de erros e alertas.

## Criterios de aceite da primeira entrega comercial

- Um administrador cria uma imobiliaria, seus usuarios e um projeto.
- Um operador envia PDF, revisa o mapa e publica uma versao.
- Um cliente entra com conta propria e acessa apenas seus projetos.
- Um link pode ser pausado e reativado sem perder o projeto.
- Outro cliente nao consegue descobrir nem acessar dados de organizacao diferente.
- O administrador consegue saber quem publicou, alterou e acessou um projeto.
