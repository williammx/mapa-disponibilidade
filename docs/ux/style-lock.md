# Style Lock — site público NexoLote

**Marcha:** Flash (3) · **Seed:** 8132026 · **Refs sorteadas:** 29 (nicho), 13 (nicho), 24 (curinga)

---

## Prova visual — o que eu VI em cada referência

### ref-29 · Verdant (SaaS de IA/dados, família Dark/Tech) — **dominante**
Plataforma de dados que se vende pela sensação de "inteligência que cresce".
**Prova visual:** fundo é uma **macro-fotografia de musgo quase preta** (~`#0A0E0B`) com verde-limão
(~`#C8E86A`) emergindo da própria foto — não é cor chapada, é a imagem que dá a cor. Navbar é uma
**pill flutuante central** de vidro escuro com borda hairline clara e CTA verde-limão com seta `→`.
Acima da headline há um **badge pill outline** com bolinha verde: "New · Verdant 2.0 is now available".
A headline mistura tipografias na mesma frase: "Intelligence that" em **sans branca** e *grows* em
**serif itálica verde-limão** — esse contraste é a assinatura. Sob o CTA, **três micro-provas com
check verde** em linha ("No credit card · 14-day free trial · Cancel anytime"). Na dobra, **três cards
de vidro escuro** (raio ~16px, borda hairline) com ícone em quadrado outline e, dentro de cada um,
uma **mini-ilustração funcional**: nós conectados por linha pontilhada, gráfico de linha com badge
`↑ 32%`, e um radar circular concêntrico. Fecha com faixa `TRUSTED BY INNOVATIVE TEAMS` em
letterspacing largo e 5 logos monocromáticos.

### ref-13 · Nuffo (real estate premium, família Editorial Luxo) — **ritmo e estrutura**
Imobiliária de alto padrão.
**Prova visual:** **wordmark gigante "nuffo"** em branco atrás do hero, com a **foto da casa cobrindo
parcialmente as letras** — o "u" e o "ff" ficam meio escondidos pela construção. Hero é full-bleed com
**cantos arredondados grandes** no container, não sangra até a borda da janela. Canto superior esquerdo
traz micro-texto em três linhas curtas separadas por `//`: "Excellence // Modern Living // Responsible
Future //"; canto superior direito traz o endereço em duas linhas. Logo abaixo, "Trusted by" com **5 logos,
cada um precedido de um ícone circular**. A seção "Why Choose Us for Your Next Project?" usa **grid de 3
imagens em alturas diferentes** com numeração `\01`, `\02` alinhada à legenda. Depois vem um **bloco preto
"Looks"** com carrossel de miniaturas.

### ref-24 · skysavvy (app de clima, família Clean Corp/SaaS) — **assinatura (curinga)**
App de previsão do tempo.
**Prova visual:** a headline **embute um elemento dentro da própria frase**: "Don't `[guess ⊙]` the
weather!" — a palavra "guess" vira uma **pill com ícone**; no hero, "Precise ✧ weather, precisely for you."
tem um símbolo no meio da frase. Os cards de UI aparecem em **colagem de alturas e larguras diferentes,
ligados por linha pontilhada curva**. Sobre as fotos há **labels flutuantes de vidro**: "UV Index",
"Wind 3.4 km/h" em pills semitransparentes. O rodapé repete o truque com uma headline gigante
"Know `[imagem]` more about skysavvy", com a imagem embutida no meio da frase.

---

## Blend intencional (não é média)

| Camada | Vem de | O que exatamente |
|---|---|---|
| Família dominante | ref-29 | Dark/Tech: fundo quase preto onde a **imagem do produto** dá a cor |
| Hero | ref-29 | Badge pill → headline mista sans + serif-itálica → CTA pill → 3 micro-provas com check → 3 cards de vidro sobre a imagem |
| Contenção do hero | ref-13 | Container com cantos arredondados grandes, micro-texto `//` no canto, não sangra na janela |
| Ritmo | ref-13 | Trusted-by logo após o hero; seção "por que" em grid de alturas diferentes com numeração `\01` |
| **Assinatura** | ref-24 | **Pill com ícone embutida dentro da headline** + **labels de vidro flutuando sobre o mapa** + linha pontilhada ligando as etapas |

**Por que a assinatura da ref-24 é a certa aqui:** os "labels flutuantes de vidro sobre a imagem" são
literalmente o que o produto faz — etiqueta de lote sobre a planta. A assinatura sai do produto, não de
enfeite.

---

## Tokens travados

Paleta ancorada nas **cores reais de status do produto** (`pdf_to_map.STATUS_HEX`), não inventada:

| Token | Hex | Origem |
|---|---|---|
| `fundo` | `#060C10` | Um degrau abaixo do painel (`#081014`) para separar site de app |
| `superficie` | `#0C161B` | Card de vidro escuro |
| `borda` | `rgba(255,255,255,.10)` | Hairline da ref-29 |
| `acento` (disponível) | `#26D07C` | `STATUS_HEX[0]` — verde de lote disponível |
| `acento-2` (reservado) | `#E0613B` | `STATUS_HEX[2]` — laranja de lote reservado |
| `neutro` (vendido) | `#6E6D67` | `STATUS_HEX[1]` — cinza de lote vendido |
| `texto` | `#E8F1EC` | — |
| `texto-fraco` | `#94A6AE` | — |

- **Raio:** 16px nos cards, 999px nas pills, 28px no container do hero (ref-13).
- **Tipografia:** sans do sistema (já é o padrão do projeto) + `font-serif` **itálica** para a palavra
  destacada da headline. Zero fonte importada — não adiciona peso nem requisição.
- **Superfície:** vidro escuro com `backdrop-blur` e borda hairline; sombra sempre difusa e baixa.

## Intensidade de animação
**Média-alta, sem carnaval.** 1 protagonista por seção, 1 fundo vivo na página inteira.
Sem GSAP: o site vive dentro do bundle do app (443 kB hoje) e uma dependência de motion só para a
landing sairia cara. O movimento usa `IntersectionObserver` + transições CSS, com
`prefers-reduced-motion` respeitado em todas as seções.

## Momentos "uau" (2, não mais)
1. **Hero:** os labels de lote aparecem um a um sobre o mapa, em cascata, como se o mapeamento
   estivesse acontecendo ao vivo — é a promessa do produto acontecendo na tela.
2. **Antes/depois:** divisor arrastável entre a planta em PDF e o mapa interativo.
