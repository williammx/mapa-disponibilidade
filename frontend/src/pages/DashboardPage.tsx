import { ArrowRight, CheckCircle, FilePdf, FilePlus, Plus, UploadSimple } from "@phosphor-icons/react";
import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiRequest, isLocalDemoMode, useApi } from "../api";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/DataStates";
import { SectionHeader } from "../components/SectionHeader";
import { createClient, createProject, stashProjectPdf, useWorkspace } from "../workspace";
import type { Project } from "../workspace";

type DashboardResponse = {
  metrics: {
    projects: number;
    in_review: number;
    published: number;
    failed_jobs: number;
    pending_proposals: number;
  };
  recent_projects: Project[];
};

type OrganizationsResponse = {
  organizations: Array<{ id: string; name: string; active: boolean }>;
};

export function DashboardPage() {
  const navigate = useNavigate();
  const workspace = useWorkspace();
  const [modal, setModal] = useState<"client" | "project" | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [selectedPdf, setSelectedPdf] = useState<File | null>(null);
  const dashboard = useApi<DashboardResponse>("/api/v1/dashboard");
  const organizations = useApi<OrganizationsResponse>("/api/v1/organizations");
  const demoFallback = isLocalDemoMode && Boolean(dashboard.error?.startsWith("Modo demo local"));
  const recentProjects = dashboard.data?.recent_projects ?? (demoFallback ? workspace.projects : []);
  // Sem resposta do backend nao ha metrica para mostrar: zerar tudo seria
  // afirmar que a operacao esta vazia quando o que houve foi uma falha.
  const metrics = dashboard.data?.metrics ?? (demoFallback
    ? {
        projects: workspace.projects.length,
        in_review: workspace.projects.filter((project) => project.status === "review").length,
        published: workspace.projects.filter((project) => project.status === "published").length,
        failed_jobs: 0,
        pending_proposals: 0,
      }
    : null);
  const organizationOptions = organizations.data?.organizations ?? (isLocalDemoMode && organizations.error?.startsWith("Modo demo local") ? workspace.clients : []);

  function closeModal() {
    setModal(null);
    setFormError(null);
    setSelectedPdf(null);
  }

  useEffect(() => {
    if (!modal) return;
    // Esc fecha o modal: sem isso o teclado ficava preso no formulario.
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setModal(null);
        setFormError(null);
        setSelectedPdf(null);
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [modal]);

  async function handleClientSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const name = String(form.get("name") ?? "").trim();
    try {
      await apiRequest("/api/v1/organizations", {
        method: "POST",
        body: JSON.stringify({ name, slug: slugify(name) }),
      });
      closeModal();
      // Refazer as duas buscas basta; recarregar a pagina inteira perdia o
      // PDF ja escolhido no formulario de projeto.
      organizations.reload();
      dashboard.reload();
    } catch (error) {
      if (error instanceof Error && error.message.startsWith("Modo demo local")) {
        // createClient recusa nome repetido; sem este try a excecao escapava do
        // handler e o formulario ficava sem explicacao nenhuma.
        try {
          createClient(name);
          closeModal();
        } catch (demoError) {
          setFormError(demoError instanceof Error ? demoError.message : "Nao foi possivel criar o cliente.");
        }
        return;
      }
      setFormError(error instanceof Error ? error.message : "Nao foi possivel criar o cliente.");
    }
  }

  async function handleProjectSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const name = String(form.get("name") ?? "").trim();
    const organizationId = String(form.get("client") ?? "");
    const description = String(form.get("description") ?? "");
    const quality = String(form.get("quality") ?? "balanced") as "light" | "balanced" | "high";
    try {
      const payload = await apiRequest<{ project: Project }>("/api/v1/projects", {
        method: "POST",
        body: JSON.stringify({ organization_id: organizationId, name, slug: slugify(name), description }),
      });
      if (selectedPdf) stashProjectPdf(payload.project.id, selectedPdf);
      closeModal();
      navigate(`/app/projetos/${payload.project.id}`);
    } catch (error) {
      if (error instanceof Error && error.message.startsWith("Modo demo local")) {
        // createProject valida nome e cliente e lanca; a excecao precisa virar
        // mensagem no formulario em vez de sumir como promessa rejeitada.
        try {
          const client = workspace.clients.find((row) => row.id === organizationId)?.name ?? organizationId;
          const project = createProject({ name, client, description, pdfName: selectedPdf?.name, quality });
          if (selectedPdf) stashProjectPdf(project.id, selectedPdf);
          closeModal();
          navigate(`/app/projetos/${project.id}`);
        } catch (demoError) {
          setFormError(demoError instanceof Error ? demoError.message : "Nao foi possivel criar o projeto.");
        }
        return;
      }
      setFormError(error instanceof Error ? error.message : "Nao foi possivel criar o projeto.");
    }
  }

  return (
    <div className="space-y-10">
      <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
        <SectionHeader eyebrow="operacao interna" title="Projetos e entregas" description="Gerencie clientes, rascunhos, revisoes, publicacoes e links compartilhados." />
        <div className="flex gap-3">
          <button onClick={() => setModal("client")} className="inline-flex items-center gap-2 rounded-[8px] border border-white/12 px-4 py-3 text-sm font-medium transition hover:bg-white/8 focus-visible:ring-2 focus-visible:ring-emerald-300 active:translate-y-px">
            <Plus size={17} weight="bold" />
            Novo cliente
          </button>
          <button onClick={() => setModal("project")} className="inline-flex items-center gap-2 rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300 active:translate-y-px">
            <FilePlus size={17} weight="bold" />
            Novo projeto
          </button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3" aria-busy={dashboard.loading}>
        <Metric label="Projetos ativos" value={metrics?.projects} loading={dashboard.loading} />
        <Metric label="Em revisao" value={metrics?.in_review} loading={dashboard.loading} />
        <Metric label="Publicados" value={metrics?.published} loading={dashboard.loading} />
      </div>

      <section className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <div>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-xl font-medium">Projetos recentes</h2>
            <span className="text-sm text-slate-400">{dashboard.loading ? "" : `${recentProjects.length} projetos`}</span>
          </div>
          {dashboard.loading ? (
            <LoadingBlock label="Carregando projetos recentes..." rows={3} />
          ) : dashboard.error && !demoFallback ? (
            <ErrorBlock message={dashboard.error} onRetry={dashboard.reload} />
          ) : recentProjects.length === 0 ? (
            <EmptyBlock
              title="Nenhum projeto ainda"
              description="Crie o projeto, anexe o PDF do empreendimento e o mapa e gerado automaticamente. Depois e so revisar, publicar e enviar o link."
              action={
                <button
                  type="button"
                  onClick={() => setModal("project")}
                  className="inline-flex items-center gap-2 rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300"
                >
                  <FilePlus size={17} weight="bold" />
                  Criar primeiro projeto
                </button>
              }
            />
          ) : (
            <div className="divide-y divide-white/8 rounded-[8px] border border-white/10">
              {recentProjects.map((project) => (
                <Link key={project.id} to={`/app/projetos/${project.id}`} className="group grid gap-4 p-5 transition hover:bg-white/5 focus-visible:ring-2 focus-visible:ring-emerald-300 md:grid-cols-[1fr_auto]">
                  <div>
                    <div className="mb-3 inline-flex rounded-[8px] border border-white/12 px-3 py-1 text-xs text-slate-300">{statusLabel(project.status)}</div>
                    <h3 className="font-medium">{project.name}</h3>
                    <p className="mt-1 text-sm text-slate-400">
                      {project.client} · {project.lots} lotes · {project.updatedAt}
                    </p>
                  </div>
                  <ArrowRight className="self-center text-slate-400 transition group-hover:translate-x-1 group-hover:text-emerald-300" size={22} weight="bold" />
                </Link>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-[8px] border border-emerald-300/20 bg-emerald-300/7 p-6">
          <UploadSimple className="mb-8 text-emerald-300" size={30} weight="bold" />
          <h2 className="text-2xl font-medium">Comece pelo PDF</h2>
          <p className="mt-3 leading-7 text-slate-300">
            O caminho correto e: novo projeto, anexar PDF, gerar mapa, revisar lotes, publicar versao e compartilhar o link do cliente.
          </p>
          <button onClick={() => setModal("project")} className="mt-6 rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300 active:translate-y-px">Criar e subir PDF</button>
        </div>
      </section>

      {modal ? (
        <div className="fixed inset-0 z-40 grid place-items-center bg-black/60 px-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="dashboard-modal-title">
          <form onSubmit={modal === "client" ? handleClientSubmit : handleProjectSubmit} className="w-full max-w-2xl rounded-[8px] border border-white/12 bg-[#10191f] p-6 shadow-[0_30px_90px_-40px_rgba(0,0,0,0.9)]">
            <div className="mb-6">
              <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-300">{modal === "client" ? "novo cliente" : "novo projeto"}</p>
              <h2 id="dashboard-modal-title" className="mt-2 text-2xl font-medium">{modal === "client" ? "Cadastrar cliente" : "Criar projeto e anexar PDF"}</h2>
              {modal === "project" ? <p className="mt-2 text-sm text-slate-400">Depois de salvar, voce cai direto na tela de processamento do mapa.</p> : null}
            </div>
            <div className="grid gap-4">
              {modal === "client" ? (
                <Field name="name" label="Nome do cliente" placeholder="Ex.: Nova Costa Urbanismo" />
              ) : (
                <>
                  <label>
                    <span className="mb-2 block text-sm font-medium text-slate-300">Cliente</span>
                    <select name="client" required disabled={organizations.loading} className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300 disabled:opacity-60">
                      <option value="">{organizations.loading ? "Carregando clientes..." : "Selecione"}</option>
                      {organizationOptions.map((client) => (
                        <option key={client.id} value={client.id}>{client.name}</option>
                      ))}
                    </select>
                    {!organizations.loading && organizations.error && !organizations.error.startsWith("Modo demo local") ? (
                      <span role="alert" className="mt-2 block text-xs text-orange-200">
                        {organizations.error}{" "}
                        <button type="button" onClick={organizations.reload} className="underline focus-visible:ring-2 focus-visible:ring-emerald-300">
                          Tentar de novo
                        </button>
                      </span>
                    ) : null}
                    {!organizations.loading && !organizations.error && organizationOptions.length === 0 ? (
                      <span className="mt-2 block text-xs text-slate-400">
                        Nenhum cliente cadastrado. Cadastre um cliente antes de criar o projeto.
                      </span>
                    ) : null}
                  </label>
                  <Field name="name" label="Nome do projeto" placeholder="Ex.: Setor E - Julho" />
                  <label>
                    <span className="mb-2 block text-sm font-medium text-slate-300">PDF do empreendimento</span>
                    <input
                      name="pdf"
                      type="file"
                      accept="application/pdf,.pdf"
                      onChange={(event) => setSelectedPdf(event.currentTarget.files?.[0] ?? null)}
                      className="sr-only"
                      id="project-pdf"
                    />
                    <label htmlFor="project-pdf" className="flex cursor-pointer items-center justify-between gap-4 rounded-[8px] border border-dashed border-emerald-300/35 bg-emerald-300/7 p-4 transition hover:bg-emerald-300/10">
                      <span className="flex min-w-0 items-center gap-3">
                        {selectedPdf ? <CheckCircle className="shrink-0 text-emerald-300" size={22} weight="fill" /> : <FilePdf className="shrink-0 text-emerald-300" size={22} weight="bold" />}
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium">{selectedPdf?.name || "Escolher arquivo PDF"}</span>
                          <span className="mt-1 block text-xs text-slate-400">Este arquivo sera usado para gerar o mapa automaticamente.</span>
                        </span>
                      </span>
                      <span className="shrink-0 rounded-[8px] border border-white/12 px-3 py-2 text-xs font-medium">Selecionar</span>
                    </label>
                  </label>
                  <label>
                    <span className="mb-2 block text-sm font-medium text-slate-300">Qualidade do fundo</span>
                    <select name="quality" defaultValue={workspace.preferences.quality} className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300">
                      <option value="light">Leve</option>
                      <option value="balanced">Equilibrada</option>
                      <option value="high">Alta qualidade</option>
                    </select>
                  </label>
                  <label>
                    <span className="mb-2 block text-sm font-medium text-slate-300">Descricao</span>
                    <textarea name="description" rows={3} className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300" />
                  </label>
                </>
              )}
            </div>
            {formError ? <p role="alert" className="mt-4 rounded-[8px] border border-orange-300/25 bg-orange-300/8 p-3 text-sm text-orange-100">{formError}</p> : null}
            <div className="mt-6 flex justify-end gap-3">
              <button type="button" onClick={closeModal} className="rounded-[8px] border border-white/12 px-4 py-3 text-sm font-medium transition hover:bg-white/8 focus-visible:ring-2 focus-visible:ring-emerald-300">Cancelar</button>
              <button className="rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300">{modal === "client" ? "Criar cliente" : "Criar e continuar"}</button>
            </div>
          </form>
        </div>
      ) : null}
    </div>
  );
}

function slugify(value: string) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "")
    .slice(0, 80) || "projeto";
}

function Metric({ label, value, loading = false }: { label: string; value?: number; loading?: boolean }) {
  return (
    <div className="rounded-[8px] border border-white/10 p-5">
      <p className="text-sm text-slate-400">{label}</p>
      {/* Numero indisponivel vira travessao: mostrar zero seria inventar contagem. */}
      <p className="mt-4 text-4xl font-medium">{loading ? "..." : value ?? "—"}</p>
    </div>
  );
}

function Field({ name, label, placeholder }: { name: string; label: string; placeholder?: string }) {
  return (
    <label>
      <span className="mb-2 block text-sm font-medium text-slate-300">{label}</span>
      <input name={name} required placeholder={placeholder} className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300" />
    </label>
  );
}

function statusLabel(status: string) {
  if (status === "published") return "Publicado";
  if (status === "review") return "Em revisao";
  if (status === "paused") return "Pausado";
  return "Rascunho";
}
