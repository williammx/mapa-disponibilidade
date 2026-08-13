# Dominio frontend — mapa brownfield (READ-ONLY)

Passagem em 2026-08-12. Base: `git ls-files` (84 arquivos versionados; 35 em `frontend/`).
Verificacao executada em copia temporaria (`/tmp/fe_build`) para nao tocar no projeto:
`npm ci` → `added 92 packages in 18s`, `NPM_CI_EXIT=0`.

## arquitetura-real

SPA React 19.2 + react-router-dom 7 + Vite 6.4.2 + Tailwind CSS v4 (plugin `@tailwindcss/vite`).
Sem Redux/Zustand/React Query. Sem code-splitting (`grep "lazy(\|Suspense" frontend/src` → nenhum resultado).

- `frontend/src/main.tsx:7-13` — `createRoot` + `React.StrictMode` + `BrowserRouter`. Nada mais.
- `frontend/src/App.tsx:19-41` — todas as rotas em um unico `<Routes>`, envoltas por `AppErrorBoundary`.
  Publicas: `/`, `/entrar`, `/cliente`. Privadas sob `/app` (layout `AppShell` via `<Outlet/>`).
  `/mapas/:slug` **so existe em modo demo** (`App.tsx:26`) — em producao o backend serve
  `@app.get("/mapas/{slug}")` (`api.py:653`) e `@app.get("/p/{slug}")` (`api.py:637`).

Dois caminhos de dados coexistem e brigam:

1. **API real** — `frontend/src/api.ts:11-37` (`apiRequest`) e `:39-58` (`useApi`, hook de fetch
   com `{data, loading, error}`). Sempre `credentials: "same-origin"` (cookie de sessao).
2. **Store local** — `frontend/src/workspace.ts` (337 linhas): `useSyncExternalStore` sobre um
   objeto em memoria persistido em `localStorage` na chave `maplot.workspace.v2` (`:54`), com
   dados-semente hardcoded (`:56-137`), incluindo o email pessoal `williammx50@gmail.com` (`:135`).
   `frontend/src/data.ts` e apenas um re-export de 8 linhas.

O chaveamento e a flag `isLocalDemoMode = import.meta.env.DEV && VITE_USE_BACKEND !== "true"`
(`api.ts:3`). Quando ligada, `apiRequest` **lanca** `"Modo demo local: backend nao conectado."`
para qualquer path `/api` (`api.ts:12-14`), e cada pagina decide sozinha se cai no store local.
Resultado: a mesma condicao esta reimplementada em 12 lugares e o tratamento e inconsistente
(ver `## dividas-e-riscos`).

Autenticacao: `AppShell.tsx:22-37` chama `/api/auth/me` no mount; erro → redirect para
`/entrar?next=...`. Nao ha guard de rota nem contexto de usuario/role — o `role` do
`PRODUCT_SPEC.md:9-15` (5 perfis) nao existe no frontend. `/app/admin` e visivel para
qualquer sessao autenticada (`AppShell.tsx:13`).

Sobreposicao com HTML legado da raiz (mapeada, nao coberta):
`index.html` (66 linhas, gerador standalone com XHR + progresso) e servido em `/gerador`
(`api.py:208`) e como fallback quando `frontend/dist` nao existe (`api.py:197-200`);
`login.html` (22 linhas) esta **orfao** — `/login` redireciona 307 para `/entrar` (`api.py:231`);
`portal.html` (47 linhas, painel completo em JS puro) sobrevive em `/portal-legado`
(`api.py:277`) e ainda tem funcoes que o React nao tem (troca de senha, `renderProfile`).

## inventario-de-telas

| rota | arquivo | o que faz | quem acessa | loading / vazio / erro |
| --- | --- | --- | --- | --- |
| `/` | `pages/LandingPage.tsx` (404) | marketing, 15 secoes, 100% estatico | publico | n/a — sem dados |
| `/entrar` | `pages/LoginPage.tsx` (121) | login email+senha, `next` sanitizado (`:119-121`) | publico | loading ok (`:57-63`) / vazio n/a / erro ok (`:107`) |
| `/cliente` | `pages/ClientPortalPage.tsx` (69) | lista mapas liberados ao cliente | cliente | **loading ausente** / **vazio ausente** / erro ok (`:39`) |
| `/mapas/:slug` | `pages/PublicMapPage.tsx` (116) | visualizador mock (72 lotes fake, `:15`) + senha + proposta | visitante (so demo) | n/a / 404 ok (`:17-30`) / erro so de senha |
| `/app` | `pages/DashboardPage.tsx` (255) | metricas, projetos recentes, modais novo cliente/projeto | operador/admin | parcial (so metricas, `:113-115`) / **vazio ausente** (`:125`) / erro ok (`:117`) |
| `/app/clientes` | `pages/ClientsPage.tsx` (107) | lista organizacoes, criar, convidar | operador/admin | **loading ausente** / **vazio ausente** (`:72`) / erro ok (`:70`) |
| `/app/clientes/:id` | `pages/ClientDetailPage.tsx` (85) | membros, pausar/reativar, projetos | operador/admin | loading ok (`:34`) / vazio parcial (`:61`, projetos sem) / erro ok (`:35`) |
| `/app/atividade` | `pages/ActivityPage.tsx` (32) | trilha de auditoria | operador/admin | **loading ausente** / **vazio ausente** / erro ok (`:18`) |
| `/app/perfil` | `pages/ProfilePage.tsx` (52) | nome (editavel) e email (bloqueado) | qualquer sessao | **loading ausente** / n/a / erro no `message` (`:35`) |
| `/app/preferencias` | `pages/PreferencesPage.tsx` (60) | qualidade, opacidade, rotulos, visibilidade | qualquer sessao | n/a — **grava so em localStorage** (`:13`) |
| `/app/admin` | `pages/AdminPage.tsx` (51) | saude: API, banco, Redis, storage | qualquer sessao (sem guard) | **loading ausente** / n/a / erro ok (`:24`) |
| `/app/projetos/:id` | `pages/ProjectWorkspacePage.tsx` (720) | 7 abas: dados, PDF→mapa, validacao, versoes, publicacao, acessos, atividade | operador/admin | loading ok (`:239`) / vazio parcial (so `:524`) / erro ok (`:293`) |
| `*` | `pages/NotFoundPage.tsx` (21) | 404 | todos | n/a |

Componentes: `AppShell.tsx` (111), `InviteUserDialog.tsx` (116), `AppErrorBoundary.tsx` (34),
`BrandLogo.tsx` (29), `SectionHeader.tsx` (15).

## site-publico

**O que existe.** `LandingPage.tsx` tem 404 linhas e 15 secoes: hero com imagem aerea + nav
flutuante, provas, metricas, fluxo em 4 passos, 4 blocos de recurso, editor, validacao, modos de
acesso, portal do cliente, versoes, pitch, demo, planos, FAQ e CTA final. Todo o conteudo esta em
arrays no topo do arquivo (`:22-77`) — nao ha CMS nem i18n. Login (`LoginPage.tsx`) e split-screen
com imagem a esquerda e formulario a direita.

**Nivel visual — avaliacao honesta.** A composicao e competente e coerente: paleta unica, raio de
canto constante (`rounded-[8px]` em todo lugar), tipografia com peso maximo `medium`, ritmo de
`py-24`. Nao parece um template generico. Mas e **estatico e plano**: nenhuma animacao, nenhum
`transition` alem de `hover`, nenhum scroll-reveal, nenhum componente interativo. Duas das tres
imagens da pagina sao **o mesmo arquivo** (`:86` e `:214`), e o "editor de mapa" e ilustrado com a
foto do hero em vez de um print real do produto. A secao demo (`:326-338`) mostra tres quadradinhos
coloridos, nao um mapa. Nao ha screenshot do produto em lugar nenhum.

**Aderencia a `docs/BRAND.md`.** O que a marca promete e o que o codigo entrega:

- Nome/descritor/frase: entregue. `Seu loteamento claro em cada decisao.` esta literal em `:112`.
- Cores: entregues. `#10B981/#34D399/#6EE7B7/#059669` estao no simbolo (`BrandLogo.tsx:17-20`);
  `#101817` e `#081014` sao os fundos.
- Peso `500`, nunca bold (`BRAND.md:35`): **entregue na landing**, mas violado no app —
  `weight="bold"` aparece em 40+ icones (`AppShell.tsx:79`, `DashboardPage.tsx:102`, etc.).
- Arquivos de assinatura (`BRAND.md:18-20`): **nao usados**. `nexolote-logo-dark.svg` e
  `nexolote-logo-light.svg` nao aparecem em nenhum lugar de `frontend/src`; `BrandLogo.tsx:10-21`
  reimplementa o simbolo inline em SVG. So `nexolote-mark.svg` e usado, como favicon
  (`frontend/index.html:6`). Ha risco de divergencia entre a marca oficial e o componente.
- `ClientPortalPage.tsx:29` ainda usa um quadrado com a letra **"M"** (heranca de "Mapa de
  Disponibilidade") em vez da marca NexoLote.

**O que falta para parecer SaaS vendavel.** Prova social zero (nenhum logo de cliente, nenhum
depoimento, nenhum numero real — `metrics` em `:66-71` sao especificacoes tecnicas, nao tracao).
Preco nao existe: a secao `#precos` (`:343-358`) tem um paragrafo dizendo "MVP operacional" e
nenhum valor, nenhum plano, nenhum botao de compra. Nao ha captura de lead: o unico CTA e "Ver
demonstracao" (ancora `#demo` na propria pagina) e "Entrar". Nao ha formulario de contato, nao ha
agendamento, nao ha trial. Nao ha rodape — a pagina termina no CTA (`:393`), sem CNPJ, contato,
politica de privacidade ou LGPD. SEO minimo: um `<title>` e uma `<meta description>` em
`frontend/index.html:8-9`, sem Open Graph, sem `og:image`, sem dados estruturados. Sem analytics.

## painel-do-administrador

**`AdminPage.tsx` (51 linhas) e a tela mais fraca do produto.** Ela faz uma unica chamada,
`/api/v1/admin/health` (`:13`), e mostra 4 cartoes de status mais uma lista **hardcoded** de 4
frases de recomendacao operacional (`:34`). Nao ha nenhuma acao — e um painel de leitura.

Confrontando com `PRODUCT_SPEC.md:46` ("Administracao: usuarios internos, configuracoes, auditoria
e saude do sistema"), faltam: gestao de usuarios internos (operadores/admins), configuracoes da
plataforma, e a auditoria (existe, mas em outra rota, `/app/atividade`). Alem disso, faltam:

- **Guard de permissao.** `/app/admin` nao verifica role nenhum. `PRODUCT_SPEC.md:9-15` define 5
  perfis; o frontend nao le `platform_role` em lugar algum (o `portal.html` legado lia —
  `['platform_admin','operator'].includes(user.platform_role)`).
- **Troca de senha.** `InviteUserDialog.tsx:79` promete "O usuario devera troca-la no primeiro
  acesso", mas **nao existe tela de troca de senha no React** (`grep "auth/password" frontend/src`
  → nenhum resultado). O endpoint existe (`api.py:371`) e so o `portal.html` legado o consome.
  Convite emitido hoje = usuario preso com senha temporaria.
- **Recuperacao de senha.** `PRODUCT_SPEC.md:50` pede; `LoginPage.tsx` nao tem link "esqueci".
- **Fila de processamento.** `AdminPage` mostra "Redis/RQ: configurado" mas nao lista jobs, nao
  permite retry nem cancel — apesar de `/api/v1/processing-jobs/{id}/retry` e `/cancel` existirem
  (`app_v1/api.py:474,492`). `DashboardPage` busca `failed_jobs` (`:14`) e **nunca renderiza**.
- **Share links.** `GET/PATCH/DELETE /api/v1/projects/{id}/share-links` existem
  (`app_v1/api.py:684-731`); o React so le `share_links` (`ProjectWorkspacePage.tsx:34`) e nunca
  revoga, expira nem lista multiplos links. `PRODUCT_SPEC.md:32` promete expiracao — sem UI.
- **Lotes.** `PATCH /api/v1/lots/{id}` e `/lots/batch` (`app_v1/api.py:642,661`) nao tem tela; a
  edicao acontece fora do React, num HTML injetado pelo backend (`api.py:302`, `project_editor_url`
  em `ProjectWorkspacePage.tsx:707-711`).

**Fricoes de fluxo concretas.**
- `DashboardPage.tsx:57` e `ClientsPage.tsx:43` chamam `window.location.reload()` depois de criar
  — recarga total da pagina em vez de refetch. `useApi` nao expoe `refetch`.
- `ProjectWorkspacePage.tsx:232` faz polling do job a cada **900 ms** com `setInterval`, sem
  backoff e sem teto de tentativas. Um job de 10 min = ~660 requisicoes.
- A aba inicial e "Mapa e editor" (`:18`), nao "Visao geral" — decisao razoavel, mas a lista de
  abas (`:9`) e um array de strings usado como chave de estado e como rotulo, sem rota; o F5 perde
  a aba e nao ha deep-link para "Publicacao".
- A tela "Validacao" (`:483-496`) mostra 4 cartoes com resultados **hardcoded** (`false, true,
  false, true`), passando por diagnostico real. `POST /project-versions/{id}/validate` existe
  (`app_v1/api.py:514`) e nao e chamado.
- `PreferencesPage` salva somente em `localStorage` (`workspace.ts:178`): trocar de navegador ou
  limpar cache perde as preferencias, e outro operador nao ve as mesmas configuracoes.

## qualidade-de-codigo

**`npx tsc --noEmit` (typescript 7.0.2, `Version 7.0.2`) — exit code 1:**

```
src/api.ts(3,44): error TS2339: Property 'env' does not exist on type 'ImportMeta'.
src/api.ts(3,67): error TS2339: Property 'env' does not exist on type 'ImportMeta'.
src/main.tsx(5,8): error TS2882: Cannot find module or type declarations for side-effect import of './styles.css'.
src/pages/LoginPage.tsx(41,23): error TS2339: Property 'env' does not exist on type 'ImportMeta'.
src/pages/LoginPage.tsx(41,46): error TS2339: Property 'env' does not exist on type 'ImportMeta'.
```

`npm run build` (Vite) — **exit 0**, `built in 8.45s`. Confirma que o build **nao faz typecheck**:
5 erros passam despercebidos. Nao ha script `typecheck` nem `lint` em `package.json:6-10`
(so `dev`, `build`, `preview`). Nao ha ESLint, nao ha Prettier, nao ha teste de frontend
(`playwright` esta em `devDependencies` mas nao ha nenhum arquivo de spec versionado).

**Sobre `typescript: "^7.0.2"`** — a alegacao de pin equivocado **nao se confirma**. TS 7 e a porta
nativa em Go; `package-lock.json` resolve `node_modules/typescript@7.0.2` mais os 20 binarios
`@typescript/typescript-<plataforma>`, e `npx tsc --version` responde `Version 7.0.2` com exit 0.
A causa dos erros e outra: `tsconfig.json` **nao inclui `"types": ["vite/client"]`** nem ha
`src/vite-env.d.ts`. Sem isso, `import.meta.env` e o import de CSS ficam sem tipos.

**Padroes observados (bons).** Tudo function component + hooks; nenhum `any` no codigo
(`grep ": any\|as any\|<any>" frontend/src` → nenhum resultado); `unknown` usado corretamente em
`ProjectWorkspacePage.tsx:713`; `strict: true` no tsconfig; um unico Error Boundary de classe
(`AppErrorBoundary.tsx`) — uso apropriado; `safeNextPath` (`LoginPage.tsx:119-121`) previne
open-redirect.

**Duplicacao concreta.**
- `slugify` copiada 3x: `workspace.ts:142`, `DashboardPage.tsx:222`, `ClientsPage.tsx:99`
  (identicas exceto o `.slice(0,64)` vs `(0,80)` e o fallback `"projeto"` vs `"cliente"`).
- `statusLabel` copiada 2x: `DashboardPage.tsx:250` e `ProjectWorkspacePage.tsx:681` — **corpos
  identicos**.
- `visibilityLabel` 2x com strings **diferentes** para o mesmo estado: `ClientPortalPage.tsx:64`
  retorna `"Privado"`, `ProjectWorkspacePage.tsx:688` retorna `"Privado por login"`.
- Componente `Field` reimplementado 3x com assinaturas diferentes: `DashboardPage.tsx:241`,
  `ProfilePage.tsx:45`, `ProjectWorkspacePage.tsx:654`.
- Componente `Metric` 2x: `DashboardPage.tsx:232` (value: number) e
  `ProjectWorkspacePage.tsx:663` (value: ReactNode).
- O banner de erro laranja (`border-orange-300/25 bg-orange-300/8 p-3 text-sm text-orange-100`)
  esta copiado literalmente em 9 arquivos. Nao ha componente `<Alert>`.

**Componentes grandes demais (linhas por arquivo).**
`ProjectWorkspacePage.tsx` **720** — 12 componentes e 6 funcoes auxiliares num arquivo so; o
componente raiz sozinho vai da linha 15 a 313 com 3 `useEffect`, 5 handlers async e 3 `useMemo`.
`LandingPage.tsx` **404** — uma unica funcao com 15 `<section>` inline.
`workspace.ts` **337**, `DashboardPage.tsx` **255**. Total `frontend/src` = **2904 linhas**.

**Fetch bruto fora do wrapper `apiRequest`** — 3 ocorrencias, todas em
`ProjectWorkspacePage.tsx`: `:156` (upload do PDF), `:164` (criar job) e `:194` (polling). Cada uma
reimplementa `credentials`, parse de JSON e extracao de `detail`. Ha justificativa parcial (`:156`
envia `FormData` e `apiRequest` forca `Content-Type: application/json`, `api.ts:18`), mas `:164` e
`:194` nao tem motivo — sao chamadas JSON comuns.

**Chaves de lista com indice** — 3 ocorrencias, todas no padrao mitigado `` `${item}-${index}` ``:
`ActivityPage.tsx:21`, `ProjectWorkspacePage.tsx:414` e `:611`. Como as listas sao append-no-topo
(`workspace.ts:211,244`), a chave muda a cada insercao e remonta todos os itens.

**Bundle.** Um unico chunk: `dist/assets/index-DD1kLoK5.js` **434 kB** (120 kB gzip) +
`index-BdlnTWGA.css` 39,6 kB. Sem `React.lazy`. A landing page publica baixa o painel admin
inteiro. `public/hero-loteamento-aereo.png` tem **2.718.884 bytes (2,6 MB)**, e usado 4x
(`LandingPage.tsx:85,214`, `LoginPage.tsx:68`, `PublicMapPage.tsx:73`) sem `loading="lazy"`, sem
`srcset` e sem versao WebP/AVIF. E o maior gargalo de first-paint do site publico.

## acessibilidade-e-responsivo

- **Foco invisivel em inputs.** `outline-none` aparece 21x (3 em `InviteUserDialog`, 5 em
  `ProjectWorkspacePage`, 4 em `DashboardPage`, 3 em `PreferencesPage`, 2 em `LoginPage`, 2 em
  `PublicMapPage`, 1 em `ClientsPage`, 1 em `ProfilePage`) e o substituto e apenas
  `focus:border-emerald-300`. `grep "focus-visible\|focus:ring\|focus:outline" frontend/src` →
  **nenhum resultado**. Botoes e links nao tem nenhum estilo de foco: navegacao por teclado no
  painel inteiro e as cegas. Contraste com `login.html:11` legado, que tinha
  `button:focus-visible{outline:2px solid var(--accent)}`.
- **Modais sem teclado.** `grep "onKeyDown\|Escape\|keydown" frontend/src` → **nenhum resultado**.
  `DashboardPage.tsx:152` e `InviteUserDialog.tsx:58` nao fecham no Esc, nao prendem foco, nao
  devolvem foco ao fechar e nao bloqueiam scroll do body. `DashboardPage.tsx:152` ainda tem
  `role="dialog" aria-modal="true"` **sem `aria-labelledby`** — o dialogo abre sem nome acessivel.
- **Contraste abaixo de AA.** `text-slate-500` (`#64748b`) sobre `#081014` da **4,03:1**, abaixo
  dos 4,5:1 exigidos para texto normal. Ocorre em `ActivityPage.tsx:26` (timestamp),
  `ProjectWorkspacePage.tsx:436`, `:438`, `:573` e `PublicMapPage.tsx:49` (cliente/versao do mapa
  publicado — texto sobre `#f7f8f5`, ai passa; os quatro primeiros falham).
- **`aria-label` em elemento generico.** `BrandLogo.tsx:9` poe `aria-label="NexoLote"` num `<span>`
  sem role. Em role `generic`, `aria-label` e ignorado pelas ATs; como o `<svg>` interno tem
  `aria-hidden="true"` (`:11`) e o texto so aparece quando `compact === false`, o logo em modo
  compacto fica **completamente invisivel** para leitor de tela.
- **Status por cor apenas.** `PublicMapPage.tsx:86` pinta os 72 lotes com
  `bg-emerald-500/72` / `bg-orange-500/72` / `bg-zinc-600/70` e o unico texto e `L001`. Nao ha
  `title`, `aria-label` nem legenda associada: disponivel/reservado/vendido e informacao
  exclusivamente cromatica. Os `<span>` tambem nao sao focaveis nem clicaveis.
- **Landing sem landmarks.** `LandingPage.tsx:81` abre com `<div>`; nao ha `<main>`, nao ha
  `<header>`/`<footer>`, e a `<nav>` (`:89`) nao tem `aria-label`. Nao ha skip-link em nenhuma
  tela. Os `<h2>` estao corretos, mas o `<h1>` unico esta so no hero.
- **Sobreposicao em mobile.** Em `PublicMapPage`, o formulario de proposta e
  `absolute bottom-5 left-5 w-[min(420px,calc(100%-40px))]` (`:92`) e o controle de zoom e
  `absolute bottom-5 right-5` (`:104`). Numa viewport de 390 px o formulario vai ate x≈370 e o
  bloco de zoom comeca em x≈270: **~100 px de sobreposicao**, com o zoom por cima do textarea.
- **Alvos de toque.** `ClientsPage.tsx:85,88` usam `px-3 py-2 text-sm` → altura efetiva ~34 px,
  abaixo dos 44 px recomendados; mesmo padrao em `SharePanel` (`ProjectWorkspacePage.tsx:625,630`).
- **Responsivo — o que funciona.** `AppShell.tsx:66-84` troca a sidebar por uma faixa horizontal
  rolavel; as abas do workspace usam `overflow-x-auto` (`:296`); todos os grids tem breakpoint
  `md:`/`lg:`; `styles.css:13` fixa `min-width: 320px`. A estrutura responsiva e solida — o
  problema e foco, contraste e sobreposicao, nao layout.

## dividas-e-riscos

Ordem = maior risco primeiro.

1. **Criar cliente quebra em producao.** `ClientsPage.tsx:42` chama `event.currentTarget.reset()`
   **depois** do `await apiRequest` da linha 35. React 19 anula `currentTarget` ao fim do dispatch
   (`react-dom/cjs/react-dom-client.development.js:19114-19120`:
   `event.currentTarget = currentTarget; try { listener(event) } ... event.currentTarget = null;`).
   Logo, apos o await o valor e `null` → `TypeError`, capturado pelo `catch` da linha 44, que
   exibe erro ao operador **mesmo com o cliente criado com sucesso**, e o `window.location.reload()`
   da linha 43 nunca roda. So nao explode em modo demo, onde nao ha `await` antes da linha 42.
2. **`/app/admin` sem controle de acesso.** `App.tsx:34` + `AppShell.tsx:13`: qualquer usuario
   autenticado, inclusive um `client_member` convidado, ve o link "Admin" e a saude da
   infraestrutura (host do banco, `storage_root`). Contraria `PRODUCT_SPEC.md:9-15`.
3. **Usuario convidado nao consegue trocar a senha.** `InviteUserDialog.tsx:79` promete a troca;
   nao existe UI (`grep "auth/password" frontend/src` vazio) apesar de `api.py:371`.
   Impede o criterio de aceite `PRODUCT_SPEC.md:83`.
4. **`ClientDetailPage` inutilizavel em modo demo.** `:34-35` — quando `useApi` lanca
   "Modo demo local", `organization` fica `null` e a tela vira um banner de erro. Sem fallback
   para `workspace.clients`, ao contrario de `ClientsPage.tsx:25`. Idem `AdminPage.tsx:14`, que
   exibe "indisponivel" como se a infra estivesse caida.
5. **Erro de demo vaza como erro real.** `ClientsPage.tsx:70`, `ActivityPage.tsx:18`,
   `AdminPage.tsx:24`, `ClientPortalPage.tsx:39` e `ClientDetailPage.tsx:35` renderizam
   `response.error` cru. Apenas `DashboardPage.tsx:117` e `ProjectWorkspacePage.tsx:293` filtram
   com `!error.startsWith("Modo demo local")`. Guarda replicada, nao centralizada em `api.ts`.
6. **5 erros de tipo escondidos.** O build passa mesmo assim (ver `## qualidade-de-codigo`). Sem
   `typecheck` no `package.json` e sem CI de frontend, qualquer regressao de tipo entra silenciosa.
7. **Dados pessoais versionados.** `workspace.ts:135` tem `williammx50@gmail.com` e `:61,117`
   nomes reais de clientes ("William Empreendimentos", "Costa Urbanismo"). Vao para o bundle de
   producao — `isLocalDemoMode` so evita o *uso*, nao a *inclusao* no `initialWorkspace`.
8. **`localStorage` sem versionamento de schema.** `workspace.ts:167` faz
   `{ ...initialWorkspace, ...JSON.parse(raw) }` — merge raso. Qualquer mudanca em campos aninhados
   (`preferences`, `profile`) resulta em objeto meio-antigo sem erro visivel.
9. **Estado local diverge do servidor.** `ProjectWorkspacePage.tsx:20` mantem `runtimePatch` que
   e mesclado sobre o projeto (`:30`) e nunca invalidado apos refetch — o operador pode continuar
   vendo um estado que o backend rejeitou.
10. **Polling de 900 ms sem backoff** (`ProjectWorkspacePage.tsx:232`), sem `AbortController` e
    sem limite. Combinado com `React.StrictMode` (`main.tsx:8`), os efeitos rodam em dobro em dev.
11. **`sharePath` gera `/mapas/:slug` que so existe em demo.** `workspace.ts:196-200` +
    `App.tsx:26`: em producao, um link gerado pelo caminho de demo depende do backend
    (`api.py:653`) — funciona, mas as duas fontes de verdade podem divergir sem aviso.
12. **Aba nao esta na URL.** `ProjectWorkspacePage.tsx:18` — F5 volta para "Mapa e editor";
    impossivel compartilhar link para "Publicacao".
13. **`react-router-dom: "^7.18.1"` com caret** contra `react: "19.2.0"` e `vite: "6.4.2"` pinados
    (`package.json:12-17`). Politica de versionamento inconsistente.
14. **`.npmrc` com caminho absoluto do Windows.** `frontend/.npmrc:1` aponta o cache para
    `C:\Users\willi\...` — arquivo versionado que quebra `npm ci` em qualquer outra maquina/CI.

## oportunidades-de-melhoria

Ordenadas por impacto ÷ esforco dentro de cada bloco. **Nada foi implementado.**

### (a) site publico / marketing

1. **Comprimir e servir o hero em formatos modernos.** `frontend/public/hero-loteamento-aereo.png`
   (2,6 MB) → AVIF/WebP com `srcset` e `loading="lazy"` nas 3 ocorrencias secundarias
   (`LandingPage.tsx:214`, `LoginPage.tsx:68`, `PublicMapPage.tsx:73`). Ganho de LCP imediato,
   ~2 h de trabalho. Maior relacao impacto/esforco do repositorio inteiro.
2. **Preco e captura de lead.** `LandingPage.tsx:343-358` — trocar o paragrafo "MVP operacional"
   por 2-3 planos com valor e um CTA que leve a formulario ou agendamento. Hoje a pagina nao tem
   nenhum caminho de conversao alem de "Entrar".
3. **Rodape.** Nao existe (a pagina termina em `:393`). Adicionar contato, CNPJ, privacidade/LGPD e
   links das secoes — requisito de credibilidade B2B, custo baixo.
4. **Substituir a foto do "editor" por screenshot real.** `LandingPage.tsx:214` repete o hero;
   `:326-338` simula a demo com 3 quadrados. Um print do `ProjectWorkspacePage` e do mapa publicado
   vende mais que qualquer copy.
5. **Meta tags sociais.** `frontend/index.html` — adicionar `og:title`, `og:description`,
   `og:image`, `twitter:card`. Sem isso, todo link compartilhado aparece sem preview.
6. **Prova social.** Reservar uma faixa para logos/depoimentos entre `#solucao` e `#fluxo`; hoje
   `metrics` (`:66-71`) sao specs tecnicas apresentadas como se fossem tracao.
7. **Landmarks + skip-link.** `LandingPage.tsx:81` de `<div>` para `<main>`, `<nav aria-label>` em
   `:89`, `<footer>` novo. Baixo esforco, corrige a11y e ajuda SEO.

### (b) painel do operador / admin

1. **Corrigir `ClientsPage.tsx:42`** — capturar `event.currentTarget` antes do `await`. Uma linha;
   destrava a criacao de clientes em producao.
2. **Guard de role.** Ler `platform_role` de `/api/auth/me` no `AppShell` e (i) esconder o item
   "Admin" (`AppShell.tsx:13`) e (ii) bloquear `/app/admin` (`App.tsx:34`) para nao-operadores.
3. **Tela de troca de senha.** Nova secao em `ProfilePage.tsx` consumindo `POST /api/auth/password`
   (`api.py:371`) — o `portal.html` legado ja tem o formulario pronto para portar.
4. **Estados de carregando e vazio.** `ClientsPage.tsx:72`, `ActivityPage.tsx:20`,
   `ClientPortalPage.tsx:41`, `DashboardPage.tsx:126` e `ClientDetailPage.tsx:75` — skeleton +
   mensagem de lista vazia com CTA. Sem isso a tela em branco parece bug.
5. **Fechar `useApi` com `refetch`** (`api.ts:39-58`) e eliminar os dois
   `window.location.reload()` (`DashboardPage.tsx:57`, `ClientsPage.tsx:43`).
6. **Aba na URL.** `ProjectWorkspacePage.tsx:18` → `useSearchParams` (`?aba=publicacao`).
   Deep-link + F5 preservado; ~1 h.
7. **Ligar a aba Validacao ao backend.** `ProjectWorkspacePage.tsx:483-496` esta hardcoded;
   `POST /api/v1/project-versions/{id}/validate` (`app_v1/api.py:514`) ja existe. Hoje a tela
   **mente** sobre a qualidade do mapa antes da publicacao — risco comercial direto.
8. **Gestao de share links.** Listar, revogar e expirar usando
   `app_v1/api.py:684-731`. `PRODUCT_SPEC.md:32` promete expiracao e nao ha UI.
9. **Fila de jobs no `AdminPage`.** Expor `failed_jobs` (ja buscado e descartado em
   `DashboardPage.tsx:14`) e ligar retry/cancel (`app_v1/api.py:474,492`).
10. **Preferencias no servidor.** `PreferencesPage.tsx:13` grava so em `localStorage`
    (`workspace.ts:178`) — promover a configuracao de organizacao.
11. **Backoff no polling.** `ProjectWorkspacePage.tsx:232`: 900 ms → progressivo (1s→2s→5s) com
    teto e `AbortController`.

### (c) fundacao tecnica

1. **`vite/client` nos tipos.** Adicionar `"types": ["vite/client"]` em `frontend/tsconfig.json`
   (ou criar `src/vite-env.d.ts`). Resolve os 5 erros de `tsc --noEmit` de uma vez. ~5 minutos.
2. **Script `typecheck` + gate no CI.** `package.json:6-10` nao tem; `.github/workflows/` nao roda
   nada de frontend. Sem isso o item 1 regride na semana seguinte.
3. **Remover `frontend/.npmrc` do versionamento** (caminho absoluto do Windows na linha 1) — hoje
   quebra `npm ci` fora da maquina do autor.
4. **Extrair primitivos de UI.** `components/ui/`: `<Alert>` (o bloco laranja duplicado em 9
   arquivos), `<Field>` (3 versoes), `<Metric>` (2), `<Modal>` (com Esc + focus trap + scroll lock),
   `<EmptyState>`, `<Skeleton>`. Resolve simultaneamente duplicacao e as falhas de a11y dos modais.
5. **Token de foco global.** Uma regra em `styles.css` (`:34-37` ja agrupa `button, a`) com
   `:focus-visible { outline: 2px solid #34D399; outline-offset: 2px }`. Corrige as 21 ocorrencias
   de `outline-none` de um golpe. Maior ganho de a11y por linha escrita.
6. **Centralizar o modo demo.** Fazer `useApi` devolver `{ demo: true }` em vez de `error`
   (`api.ts:12-14`), eliminando as 5 telas que exibem a mensagem interna ao usuario.
7. **Consolidar helpers.** `src/lib/` com `slugify` (hoje 3x), `statusLabel` (2x),
   `visibilityLabel` (2x, com textos divergentes) e `processingLabel`.
8. **Quebrar `ProjectWorkspacePage.tsx` (720 linhas)** em `pages/project/{Overview,Editor,
   Validation,Versions,Publication,Access,Activity}.tsx` + um hook `useProjectProcessing` para os
   dois `useEffect` de upload/polling. Extrair tambem as 15 secoes de `LandingPage.tsx` (404) para
   `components/landing/`.
9. **Code-splitting por rota.** `React.lazy` em `App.tsx:3-15` separando o bloco `/app` do publico.
   O chunk unico de 434 kB e baixado por todo visitante da landing.
10. **Purgar o `initialWorkspace`.** `workspace.ts:56-137` — mover a semente para um arquivo
    carregado so em `import.meta.env.DEV`, tirando email e nomes reais do bundle de producao.
11. **ESLint + `eslint-plugin-jsx-a11y` + `react-hooks`.** Pegaria automaticamente o
    `aria-labelledby` faltante, o `aria-label` em `<span>` e a dependencia parcial de
    `applyProjectPatch` (`ProjectWorkspacePage.tsx:137` usa `baseProject?.id` no array mas
    `baseProject` no corpo).
12. **Aposentar `login.html`.** Orfao — `/login` ja e 307 para `/entrar` (`api.py:231`) e nenhuma
    rota o serve.

## fora-de-escopo

- Backend Python (`api.py`, `app_v1/`, `auth.py`, `models.py`, `database.py`, `alembic/`),
  `pdf_to_map.py`, Docker/compose, `.github/workflows/deploy-vps.yml`, `deploy/`, `tools/`.
  Rotas do backend so foram lidas para provar sobreposicao com o React.
- `demo/setor-e-demo.html` (105 linhas) e `tests/` — nao inspecionados.
- **Nao verificado nesta passagem:** renderizacao real no navegador (nenhum screenshot novo foi
  produzido; `design-qa.md:23` afirma "No actionable P0/P1/P2 issues remain", porem as imagens
  citadas em `design-qa.md:7-11` estao em `output/playwright/`, diretorio nao versionado e ausente).
- **Nao verificado:** contraste do texto sobre a imagem do hero (`LandingPage.tsx:114`,
  `text-slate-100/88` sobre gradiente + foto) — exige medicao de pixel renderizado.
- **Nao verificado:** comportamento do `useApi` sob 401 concorrente em multiplas telas, e se o
  cookie de sessao sobrevive ao proxy do Vite (`vite.config.mjs:10-19`).
- **Nao verificado:** `npm ci` na maquina do autor com o `.npmrc` apontando para
  `frontend/.npm-cache` (diretorio existe no host; nao foi lido, conforme instrucao).

---

## Veredicto: **CONCERNS**

O build de producao passa (exit 0) e a arquitetura tem qualidades reais: zero `any`, `strict: true`,
Error Boundary, roteamento limpo, layout responsivo consistente e uma landing page com identidade
propria alinhada a `docs/BRAND.md`. Nao e um FAIL.

Mas nao e PASS por tres razoes com evidencia:

1. **Um bug funcional confirmado em caminho critico.** `ClientsPage.tsx:42` quebra a criacao de
   cliente em producao — provado pelo `event.currentTarget = null` do React
   (`react-dom-client.development.js:19120`).
2. **Falhas de contrato com a propria especificacao.** Sem guard de role em `/app/admin`
   (`App.tsx:34` vs `PRODUCT_SPEC.md:9-15`), sem troca de senha para o usuario convidado
   (promessa em `InviteUserDialog.tsx:79`, endpoint ocioso em `api.py:371`), e a aba Validacao com
   resultados hardcoded (`ProjectWorkspacePage.tsx:483-496`) exibindo garantia de qualidade falsa
   antes da publicacao.
3. **Rede de seguranca ausente.** 5 erros de `tsc --noEmit` invisiveis ao `vite build`, nenhum
   script de typecheck ou lint em `package.json:6-10`, nenhum teste de frontend e nenhum estilo de
   `:focus-visible` em 2904 linhas.

Nenhum desses pontos exige reescrita. Os itens (c)1, (c)5, (b)1 e (b)2 somados sao menos de um dia
de trabalho e movem o veredicto para PASS.
