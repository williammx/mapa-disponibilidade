import {
  ArrowRight,
  Buildings,
  ChartLineUp,
  CheckCircle,
  Clock,
  Copy,
  FilePdf,
  Kanban,
  Key,
  LockKey,
  MapPinArea,
  MapTrifold,
  ShieldCheck,
  SlidersHorizontal,
  Sparkle,
  UsersThree,
} from "@phosphor-icons/react";
import { Link } from "react-router-dom";

const proof = [
  { icon: MapTrifold, label: "Mapa interativo" },
  { icon: Buildings, label: "Disponibilidade em tempo real" },
  { icon: Copy, label: "Compartilhe com confianca" },
  { icon: LockKey, label: "Permissoes e controle" },
];

const outcomes = [
  "Transforme PDF em mapa navegavel",
  "Controle status por lote",
  "Entregue links publicos ou privados",
  "Receba propostas sem alterar a versao publicada",
];

const workflow = [
  ["01", "Suba o PDF", "O motor processa o arquivo, identifica os lotes e gera uma base editavel."],
  ["02", "Revise o mapa", "Ajuste status, nomes, cores, divisao, opacidade e validacao antes de publicar."],
  ["03", "Publique a versao", "Cada entrega fica imutavel, com historico e link controlado por acesso."],
  ["04", "Compartilhe", "O cliente abre somente o mapa liberado, sem ferramentas internas por padrao."],
];

const featureBlocks = [
  { icon: FilePdf, title: "PDF para mapa", text: "Qualidade de fundo ajustavel, processamento otimizado e preservacao da versao original." },
  { icon: SlidersHorizontal, title: "Editor visual", text: "Ferramentas para ajustar cor, status, alinhamento, opacidade, numeros e divisao dos lotes." },
  { icon: ShieldCheck, title: "Entrega controlada", text: "Link publico, link com senha, login privado e permissao opcional para proposta de edicao." },
  { icon: Kanban, title: "Operacao interna", text: "Clientes, projetos, versoes, publicacao, acessos e atividade em uma rotina unica." },
];

const accessModes = [
  ["Privado", "Login obrigatorio para usuarios vinculados ao cliente."],
  ["Senha", "Link protegido para apresentacoes pontuais."],
  ["Nao listado", "Acesso por URL sem aparecer publicamente."],
  ["Publico", "URL previsivel para materiais comerciais."],
];

const validation = [
  "lotes sem nome",
  "geometria invalida",
  "possiveis lotes agrupados",
  "sobreposicao",
  "areas sem cobertura",
  "versao publicada sem rascunho",
];

const metrics = [
  ["1.509", "lotes em um mapa demo validado"],
  ["70%", "opacidade padrao para leitura do PDF"],
  ["4", "modelos de acesso para cliente"],
  ["0", "edicoes diretas na versao publicada"],
];

const faq = [
  ["O cliente consegue editar?", "Somente se voce permitir. Mesmo assim, ele edita uma copia e envia proposta para aprovacao."],
  ["O link pode ser privado?", "Sim. O projeto pode ficar por login, senha, link nao listado ou publico."],
  ["O mapa publicado muda sozinho?", "Nao. Publicacao gera versao imutavel. Novas alteracoes ficam como rascunho ate publicar de novo."],
];

export function LandingPage() {
  return (
    <div className="bg-[#f6f8f5] text-[#101817]">
      <section className="relative min-h-[92dvh] overflow-hidden bg-[#0b1412] text-white">
        <img
          src="/hero-loteamento-aereo.png"
          alt="Mapa aereo de loteamento com quadras e ruas"
          className="absolute inset-0 h-full w-full object-cover"
        />
        <div className="absolute inset-0 bg-[linear-gradient(90deg,rgba(4,9,8,0.9)_0%,rgba(4,9,8,0.7)_34%,rgba(4,9,8,0.15)_72%,rgba(4,9,8,0.04)_100%)]" />
        <nav className="relative z-10 mx-4 mt-4 flex items-center justify-between rounded-[8px] border border-white/14 bg-[#08100e]/70 px-5 py-4 shadow-[0_24px_80px_-32px_rgba(0,0,0,0.8)] backdrop-blur-xl md:mx-6 lg:mx-10">
          <Link to="/" className="flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-[8px] bg-emerald-400 text-lg font-medium text-slate-950">M</span>
            <span className="text-lg font-medium tracking-tight">Mapa de Disponibilidade</span>
          </Link>
          <div className="hidden items-center gap-8 text-sm text-slate-200 md:flex">
            <a href="#solucao" className="transition hover:text-white">Solucao</a>
            <a href="#fluxo" className="transition hover:text-white">Fluxo</a>
            <a href="#recursos" className="transition hover:text-white">Recursos</a>
            <a href="#acesso" className="transition hover:text-white">Acesso</a>
            <a href="#precos" className="transition hover:text-white">Planos</a>
          </div>
          <div className="flex items-center gap-3">
            <Link to="/entrar" className="hidden rounded-[8px] px-4 py-3 text-sm font-medium text-white transition hover:bg-white/8 sm:inline-flex">
              Entrar
            </Link>
            <a href="#demo" className="rounded-[8px] bg-emerald-400 px-5 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300 active:translate-y-px">
              Ver demonstracao
            </a>
          </div>
        </nav>
        <div className="relative z-10 mx-auto grid min-h-[calc(92dvh-92px)] max-w-[1500px] content-center px-6 pb-20 pt-12 md:px-10">
          <div className="max-w-3xl">
            <h1 className="max-w-[13ch] text-5xl font-medium leading-[1.04] tracking-tight md:text-7xl">
              Seu loteamento claro em cada decisao.
            </h1>
            <p className="mt-7 max-w-xl text-xl leading-9 text-slate-100/88">
              Publique disponibilidade, organize sua operacao e compartilhe um mapa que seus clientes entendem.
            </p>
            <div className="mt-9 flex flex-col gap-4 sm:flex-row">
              <a href="#demo" className="inline-flex items-center justify-center gap-2 rounded-[8px] bg-emerald-400 px-8 py-4 font-medium text-slate-950 transition hover:bg-emerald-300 active:translate-y-px">
                Ver demonstracao
                <ArrowRight size={18} weight="regular" />
              </a>
              <Link to="/entrar" className="inline-flex items-center justify-center rounded-[8px] border border-white/28 px-8 py-4 font-medium text-white transition hover:bg-white/10 active:translate-y-px">
                Entrar
              </Link>
            </div>
            <div className="mt-12 grid max-w-xl grid-cols-2 gap-5 sm:grid-cols-4">
              {proof.map((item) => (
                <div key={item.label} className="text-sm text-slate-100/82">
                  <item.icon className="mb-3 text-emerald-300" size={28} weight="regular" />
                  {item.label}
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="absolute bottom-10 right-8 hidden rounded-[8px] border border-white/22 bg-[#06100e]/70 px-5 py-3 text-sm shadow-[0_18px_60px_-26px_rgba(0,0,0,0.8)] backdrop-blur-lg lg:flex lg:gap-7">
          <span className="flex items-center gap-2"><i className="size-3 rounded-full bg-emerald-400" />Disponivel</span>
          <span className="flex items-center gap-2"><i className="size-3 rounded-full bg-slate-500" />Indisponivel</span>
          <span className="flex items-center gap-2"><i className="size-3 rounded-full bg-orange-400" />Reservado</span>
        </div>
      </section>

      <section id="solucao" className="px-6 py-24 md:px-10">
        <div className="mx-auto grid max-w-[1320px] gap-12 lg:grid-cols-[0.92fr_1.08fr] lg:items-end">
          <div>
            <Eyebrow>feito para quem lidera</Eyebrow>
            <h2 className="mt-5 max-w-xl text-4xl font-medium leading-tight tracking-tight md:text-6xl">
              Mais clareza para vender melhor.
            </h2>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {outcomes.map((text) => (
              <div key={text} className="flex items-start gap-3 border-t border-slate-300 pt-5">
                <CheckCircle className="mt-1 text-emerald-600" size={22} weight="regular" />
                <p className="text-lg font-medium leading-7">{text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="border-y border-slate-200 bg-white px-6 py-20 md:px-10">
        <div className="mx-auto grid max-w-[1320px] gap-5 md:grid-cols-4">
          {metrics.map(([value, label]) => (
            <div key={label} className="border-t border-slate-300 pt-5">
              <p className="text-5xl font-medium tracking-tight">{value}</p>
              <p className="mt-3 leading-7 text-slate-600">{label}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="fluxo" className="px-6 py-24 md:px-10">
        <div className="mx-auto max-w-[1320px]">
          <Eyebrow>fluxo operacional</Eyebrow>
          <h2 className="mt-5 max-w-3xl text-4xl font-medium leading-tight tracking-tight md:text-6xl">
            Do PDF ao link entregue sem perder controle.
          </h2>
          <div className="mt-14 grid gap-5 md:grid-cols-2 xl:grid-cols-4">
            {workflow.map(([step, title, text]) => (
              <article key={step} className="rounded-[8px] border border-slate-200 bg-white p-6">
                <p className="text-sm text-emerald-700">{step}</p>
                <h3 className="mt-8 text-2xl font-medium tracking-tight">{title}</h3>
                <p className="mt-4 leading-7 text-slate-600">{text}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="recursos" className="bg-[#101817] px-6 py-24 text-white md:px-10">
        <div className="mx-auto grid max-w-[1320px] gap-12 lg:grid-cols-[0.75fr_1.25fr]">
          <div>
            <Eyebrow dark>recursos principais</Eyebrow>
            <h2 className="mt-5 text-4xl font-medium leading-tight tracking-tight md:text-6xl">
              Ferramentas para operar, revisar e entregar.
            </h2>
          </div>
          <div className="grid gap-5 md:grid-cols-2">
            {featureBlocks.map((item) => (
              <article key={item.title} className="rounded-[8px] border border-white/12 bg-white/5 p-6">
                <item.icon className="text-emerald-300" size={30} weight="regular" />
                <h3 className="mt-8 text-2xl font-medium">{item.title}</h3>
                <p className="mt-4 leading-7 text-slate-300">{item.text}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="px-6 py-24 md:px-10">
        <div className="mx-auto grid max-w-[1320px] gap-10 lg:grid-cols-[1fr_1fr] lg:items-center">
          <div className="overflow-hidden rounded-[8px] border border-slate-200 bg-white">
            <img src="/hero-loteamento-aereo.png" alt="Mapa com lotes coloridos para disponibilidade" className="aspect-[4/3] w-full object-cover" />
          </div>
          <div>
            <Eyebrow>editor de mapa</Eyebrow>
            <h2 className="mt-5 text-4xl font-medium leading-tight tracking-tight md:text-6xl">
              Ajuste o mapa antes de publicar.
            </h2>
            <p className="mt-6 max-w-xl text-lg leading-8 text-slate-600">
              O time revisa lotes, status, rotulos, alinhamento, opacidade e divisoes. O cliente recebe uma versao limpa, pronta para consulta.
            </p>
          </div>
        </div>
      </section>

      <section id="validacao" className="border-y border-slate-200 bg-white px-6 py-24 md:px-10">
        <div className="mx-auto grid max-w-[1320px] gap-10 lg:grid-cols-[0.8fr_1.2fr]">
          <div>
            <Eyebrow>validacao</Eyebrow>
            <h2 className="mt-5 text-4xl font-medium leading-tight tracking-tight md:text-6xl">
              Publique com uma lista de riscos visiveis.
            </h2>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {validation.map((item) => (
              <div key={item} className="flex items-center gap-3 rounded-[8px] border border-slate-200 p-4">
                <Sparkle className="text-emerald-600" size={20} weight="regular" />
                <span className="font-medium">{item}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="acesso" className="px-6 py-24 md:px-10">
        <div className="mx-auto max-w-[1320px]">
          <Eyebrow>acessos</Eyebrow>
          <div className="mt-5 grid gap-10 lg:grid-cols-[0.9fr_1.1fr]">
            <h2 className="text-4xl font-medium leading-tight tracking-tight md:text-6xl">
              Cada cliente recebe o nivel certo de acesso.
            </h2>
            <div className="divide-y divide-slate-200 border-y border-slate-200">
              {accessModes.map(([title, text]) => (
                <div key={title} className="grid gap-3 py-6 md:grid-cols-[180px_1fr]">
                  <p className="font-medium">{title}</p>
                  <p className="leading-7 text-slate-600">{text}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="bg-[#e9eee9] px-6 py-24 md:px-10">
        <div className="mx-auto grid max-w-[1320px] gap-6 lg:grid-cols-[1.15fr_0.85fr]">
          <div className="rounded-[8px] bg-[#101817] p-8 text-white">
            <Eyebrow dark>portal do cliente</Eyebrow>
            <h2 className="mt-24 max-w-2xl text-4xl font-medium leading-tight tracking-tight md:text-6xl">
              O cliente ve o mapa, nao a sua operacao interna.
            </h2>
          </div>
          <div className="rounded-[8px] bg-white p-8">
            <UsersThree className="text-emerald-600" size={34} weight="regular" />
            <p className="mt-20 text-2xl leading-9 text-slate-700">
              Quando a edicao for permitida, a alteracao vira proposta. A versao publicada permanece intacta ate aprovacao.
            </p>
          </div>
        </div>
      </section>

      <section className="px-6 py-24 md:px-10">
        <div className="mx-auto grid max-w-[1320px] gap-10 lg:grid-cols-[0.7fr_1.3fr]">
          <div>
            <Eyebrow>versoes</Eyebrow>
            <h2 className="mt-5 text-4xl font-medium leading-tight tracking-tight md:text-6xl">
              Historico para trabalhar sem medo.
            </h2>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            {["Rascunho salvo", "Versao publicada", "Proposta recebida"].map((item, index) => (
              <article key={item} className="rounded-[8px] border border-slate-200 bg-white p-6">
                <Clock className="text-emerald-600" size={26} weight="regular" />
                <h3 className="mt-10 text-xl font-medium">{item}</h3>
                <p className="mt-3 text-slate-600">Etapa {index + 1} do ciclo de entrega.</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="border-y border-slate-200 bg-white px-6 py-24 md:px-10">
        <div className="mx-auto grid max-w-[1320px] gap-10 lg:grid-cols-[1fr_1fr]">
          <div>
            <Eyebrow>para imobiliarias</Eyebrow>
            <h2 className="mt-5 text-4xl font-medium leading-tight tracking-tight md:text-6xl">
              Menos planilha solta. Mais contexto para vender.
            </h2>
          </div>
          <p className="text-xl leading-9 text-slate-600">
            O mapa vira uma peca comercial consultavel, com status visual e permissao controlada. A equipe interna mantem governanca sobre publicacao, cliente e historico.
          </p>
        </div>
      </section>

      <section id="demo" className="bg-[#101817] px-6 py-24 text-white md:px-10">
        <div className="mx-auto grid max-w-[1320px] gap-10 lg:grid-cols-[0.9fr_1.1fr]">
          <div>
            <Eyebrow dark>demonstracao</Eyebrow>
            <h2 className="mt-5 text-4xl font-medium leading-tight tracking-tight md:text-6xl">
              Veja como uma entrega fica pronta para cliente.
            </h2>
          </div>
          <div className="rounded-[8px] border border-white/12 bg-white/5 p-6">
            <div className="grid gap-4 sm:grid-cols-3">
              {["Disponivel", "Vendido", "Reservado"].map((item, index) => (
                <div key={item} className="rounded-[8px] border border-white/12 p-4">
                  <span className={`mb-8 block size-3 rounded-full ${index === 0 ? "bg-emerald-400" : index === 1 ? "bg-slate-500" : "bg-orange-400"}`} />
                  <p className="font-medium">{item}</p>
                  <p className="mt-2 text-sm text-slate-400">Status aplicado no lote.</p>
                </div>
              ))}
            </div>
            <a href="/mapas/setor-e-demo" className="mt-6 inline-flex items-center gap-2 rounded-[8px] bg-emerald-400 px-5 py-3 font-medium text-slate-950">
              Abrir exemplo
              <ArrowRight size={18} weight="regular" />
            </a>
          </div>
        </div>
      </section>

      <section id="precos" className="px-6 py-24 md:px-10">
        <div className="mx-auto grid max-w-[1320px] gap-10 lg:grid-cols-[0.75fr_1.25fr]">
          <div>
            <Eyebrow>planos</Eyebrow>
            <h2 className="mt-5 text-4xl font-medium leading-tight tracking-tight md:text-6xl">
              Comece com operacao assistida.
            </h2>
          </div>
          <div className="rounded-[8px] border border-slate-200 bg-white p-8">
            <p className="text-2xl font-medium">MVP operacional</p>
            <p className="mt-4 max-w-2xl leading-8 text-slate-600">
              Ideal para validar empreendimentos reais: processamento, revisao, publicacao e link de cliente. Pagamentos, CRM e automacoes comerciais entram depois do fluxo ficar estavel.
            </p>
          </div>
        </div>
      </section>

      <section className="border-y border-slate-200 bg-white px-6 py-24 md:px-10">
        <div className="mx-auto max-w-[1320px]">
          <Eyebrow>perguntas comuns</Eyebrow>
          <div className="mt-8 divide-y divide-slate-200 border-y border-slate-200">
            {faq.map(([question, answer]) => (
              <div key={question} className="grid gap-4 py-7 md:grid-cols-[0.7fr_1.3fr]">
                <p className="text-xl font-medium">{question}</p>
                <p className="leading-8 text-slate-600">{answer}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="px-6 py-24 md:px-10">
        <div className="mx-auto grid max-w-[1320px] gap-10 rounded-[8px] bg-[#101817] p-8 text-white md:p-12 lg:grid-cols-[1fr_auto] lg:items-center">
          <div>
            <Eyebrow dark>proximo passo</Eyebrow>
            <h2 className="mt-5 max-w-3xl text-4xl font-medium leading-tight tracking-tight md:text-6xl">
              Publique seu primeiro mapa com acesso controlado.
            </h2>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row">
            <Link to="/entrar" className="inline-flex items-center justify-center gap-2 rounded-[8px] bg-emerald-400 px-6 py-4 font-medium text-slate-950">
              Entrar
              <Key size={18} weight="regular" />
            </Link>
            <a href="#demo" className="inline-flex items-center justify-center gap-2 rounded-[8px] border border-white/18 px-6 py-4 font-medium">
              Ver demonstracao
              <ArrowRight size={18} weight="regular" />
            </a>
          </div>
        </div>
      </section>
    </div>
  );
}

function Eyebrow({ children, dark = false }: { children: string; dark?: boolean }) {
  return (
    <p className={`text-xs font-medium uppercase tracking-[0.24em] ${dark ? "text-emerald-300" : "text-emerald-600"}`}>
      {children}
    </p>
  );
}
