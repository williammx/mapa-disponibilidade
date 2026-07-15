import { ArrowRight, LockKey, MapTrifold } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { useApi } from "../api";
import { useWorkspace } from "../workspace";
import type { Project } from "../workspace";

type ProjectListResponse = {
  projects: Project[];
};

export function ClientPortalPage() {
  const workspace = useWorkspace();
  const response = useApi<ProjectListResponse>("/api/v1/projects");
  const rows = response.data?.projects ?? workspace.projects.filter((project) => project.status !== "draft" && project.status !== "paused");

  return (
    <main className="min-h-[100dvh] bg-[#081014] text-white">
      <header className="border-b border-white/8 px-5 py-5">
        <div className="mx-auto flex max-w-[1320px] items-center justify-between">
          <Link to="/" className="flex items-center gap-3">
            <span className="grid size-9 place-items-center rounded-[8px] bg-emerald-400 font-medium text-slate-950">M</span>
            <span className="font-medium">Portal do cliente</span>
          </Link>
          <Link to="/entrar" className="rounded-[8px] border border-white/12 px-4 py-2 text-sm font-medium">Entrar</Link>
        </div>
      </header>
      <section className="mx-auto max-w-[1320px] px-5 py-14">
        <p className="text-xs font-medium uppercase tracking-[0.22em] text-emerald-300">mapas liberados</p>
        <h1 className="mt-4 max-w-2xl text-4xl font-medium tracking-tight md:text-6xl">Consulte os empreendimentos publicados para sua organizacao.</h1>
        <p className="mt-5 max-w-2xl leading-8 text-slate-300">Links de cliente abrem somente o mapa e os detalhes liberados. Quando edicao estiver habilitada, a mudanca vira proposta para aprovacao interna.</p>
        {response.error ? <p className="mt-6 rounded-[8px] border border-orange-300/25 bg-orange-300/8 p-3 text-sm text-orange-100">{response.error}</p> : null}
        <div className="mt-12 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {rows.map((project) => (
            <article key={project.id} className="rounded-[8px] border border-white/10 bg-white/5 p-6">
              <MapTrifold className="text-emerald-300" size={28} weight="regular" />
              <h2 className="mt-10 text-2xl font-medium">{project.name}</h2>
              <p className="mt-2 text-slate-400">{project.client} · {project.lots} lotes</p>
              <div className="mt-8 flex items-center justify-between gap-3">
                <span className="inline-flex items-center gap-2 rounded-[8px] border border-white/12 px-3 py-1 text-xs text-slate-300">
                  <LockKey size={14} weight="regular" />
                  {visibilityLabel(project.visibility)}
                </span>
                <Link to={`/mapas/${project.slug}`} className="inline-flex items-center gap-2 text-sm font-medium text-emerald-300">
                  Abrir
                  <ArrowRight size={16} weight="regular" />
                </Link>
              </div>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}

function visibilityLabel(value: string) {
  if (value === "private") return "Privado";
  if (value === "password") return "Com senha";
  if (value === "public") return "Publico";
  return "Por link";
}
