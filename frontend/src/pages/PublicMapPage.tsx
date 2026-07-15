import { ArrowLeft, LockKey, MagnifyingGlassMinus, MagnifyingGlassPlus, MapTrifold, PencilSimple, PaperPlaneTilt } from "@phosphor-icons/react";
import { FormEvent, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useWorkspace } from "../workspace";

export function PublicMapPage() {
  const { slug } = useParams();
  const workspace = useWorkspace();
  const project = workspace.projects.find((item) => item.slug === slug);
  const [zoom, setZoom] = useState(1);
  const [unlocked, setUnlocked] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [proposalSent, setProposalSent] = useState(false);
  const requiresPassword = project?.visibility === "password" && project.passwordEnabled && !unlocked;
  const lots = useMemo(() => Array.from({ length: 72 }, (_, index) => index + 1), []);

  if (!project) {
    return (
      <main className="grid min-h-[100dvh] place-items-center bg-[#f7f8f5] px-5 text-[#101817]">
        <div className="max-w-lg rounded-[8px] border border-slate-200 bg-white p-8">
          <h1 className="text-3xl font-medium">Mapa nao encontrado</h1>
          <p className="mt-3 text-slate-600">O link pode ter sido removido, pausado ou digitado incorretamente.</p>
          <Link to="/" className="mt-6 inline-flex items-center gap-2 rounded-[8px] bg-[#101817] px-4 py-3 text-sm font-medium text-white">
            <ArrowLeft size={17} weight="bold" />
            Voltar
          </Link>
        </div>
      </main>
    );
  }

  function handlePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const password = String(new FormData(event.currentTarget).get("password") ?? "");
    if (password.trim().length < 3) {
      setPasswordError("Informe a senha recebida para abrir este mapa.");
      return;
    }
    setUnlocked(true);
    setPasswordError(null);
  }

  return (
    <main className="min-h-[100dvh] bg-[#f7f8f5] text-[#101817]">
      <header className="flex flex-col gap-3 border-b border-slate-200 bg-white px-5 py-4 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-600">mapa publicado</p>
          <h1 className="text-xl font-medium">{project.name}</h1>
          <p className="text-sm text-slate-500">{project.client} · versao {project.version || 1}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-[8px] border border-slate-200 px-3 py-1 text-sm">{project.lots} lotes</span>
          <span className="rounded-[8px] border border-slate-200 px-3 py-1 text-sm">{project.allowEdit ? "Propostas habilitadas" : "Somente leitura"}</span>
        </div>
      </header>

      {requiresPassword ? (
        <section className="grid min-h-[calc(100dvh-89px)] place-items-center px-5">
          <form onSubmit={handlePassword} className="w-full max-w-md rounded-[8px] border border-slate-200 bg-white p-7 shadow-[0_30px_90px_-55px_rgba(0,0,0,0.45)]">
            <LockKey className="text-emerald-600" size={30} weight="bold" />
            <h2 className="mt-5 text-2xl font-medium">Este mapa tem senha</h2>
            <p className="mt-2 text-slate-600">Digite a senha enviada junto com o link para visualizar o empreendimento.</p>
            <label className="mt-6 block">
              <span className="mb-2 block text-sm font-medium text-slate-700">Senha</span>
              <input name="password" type="password" className="w-full rounded-[8px] border border-slate-300 px-4 py-3 outline-none focus:border-emerald-500" />
            </label>
            {passwordError ? <p className="mt-3 text-sm text-red-700">{passwordError}</p> : null}
            <button className="mt-5 w-full rounded-[8px] bg-emerald-500 px-4 py-3 text-sm font-medium text-slate-950">Abrir mapa</button>
          </form>
        </section>
      ) : (
        <section className="relative min-h-[calc(100dvh-89px)] overflow-hidden">
          <img src="/hero-loteamento-aereo.png" alt="Mapa publicado do empreendimento" className="absolute inset-0 h-full w-full object-cover" style={{ transform: `scale(${zoom})`, transformOrigin: "center" }} />
          <div className="absolute inset-0 bg-white/10" />
          <div className="absolute left-5 top-5 rounded-[8px] border border-white/60 bg-white/88 p-4 shadow-[0_24px_70px_-34px_rgba(0,0,0,0.55)] backdrop-blur-md">
            <div className="flex items-center gap-3">
              <MapTrifold className="text-emerald-600" size={24} weight="bold" />
              <div>
                <p className="font-medium">{project.client}</p>
                <p className="text-sm text-slate-600">Versao publicada · sem ferramentas internas</p>
              </div>
            </div>
          </div>
          <div className="absolute left-[10%] top-[18%] grid w-[78%] grid-cols-12 gap-1 transition-transform" style={{ transform: `scale(${zoom})`, transformOrigin: "center" }}>
            {lots.map((lot) => (
              <span key={lot} className={`grid aspect-[1.8/1] place-items-center border border-black/30 text-[10px] font-medium ${lot % 11 === 0 ? "bg-orange-500/72" : lot % 7 === 0 ? "bg-zinc-600/70" : "bg-emerald-500/72"}`}>
                L{String(lot).padStart(3, "0")}
              </span>
            ))}
          </div>
          {project.allowEdit ? (
            <form onSubmit={(event) => { event.preventDefault(); setProposalSent(true); }} className="absolute bottom-5 left-5 w-[min(420px,calc(100%-40px))] rounded-[8px] border border-white/60 bg-white/90 p-4 backdrop-blur-md">
              <div className="flex items-center gap-2 font-medium">
                <PencilSimple size={18} weight="bold" />
                Propor alteracao
              </div>
              <textarea name="proposal" required rows={3} placeholder="Descreva o ajuste que voce quer enviar para aprovacao." className="mt-3 w-full rounded-[8px] border border-slate-300 px-3 py-2 text-sm outline-none focus:border-emerald-500" />
              <button className="mt-3 inline-flex items-center gap-2 rounded-[8px] bg-[#101817] px-4 py-2 text-sm font-medium text-white">
                <PaperPlaneTilt size={16} weight="bold" />
                {proposalSent ? "Proposta enviada" : "Enviar proposta"}
              </button>
            </form>
          ) : null}
          <div className="absolute bottom-5 right-5 flex gap-2 rounded-[8px] border border-white/60 bg-white/88 p-2 backdrop-blur-md">
            <button onClick={() => setZoom((value) => Math.min(1.8, value + 0.1))} aria-label="Aproximar" className="grid size-10 place-items-center rounded-[8px] bg-[#101817] text-white">
              <MagnifyingGlassPlus size={20} weight="bold" />
            </button>
            <button onClick={() => setZoom((value) => Math.max(1, value - 0.1))} aria-label="Afastar" className="grid size-10 place-items-center rounded-[8px] bg-[#101817] text-white">
              <MagnifyingGlassMinus size={20} weight="bold" />
            </button>
          </div>
        </section>
      )}
    </main>
  );
}
