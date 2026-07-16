import { ArrowSquareOut, CheckCircle, Copy, Eye, FilePdf, FloppyDisk, LockKey, Play, UploadSimple, WarningCircle } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useApi } from "../api";
import { attachProjectPdf, publishProject, setProjectProcessing, sharePath, takeProjectPdf, updateProject, useWorkspace } from "../workspace";
import type { Project, Visibility } from "../workspace";

const tabs = ["Visao geral", "Mapa e editor", "Validacao", "Versoes", "Publicacao", "Acessos", "Atividade"] as const;
type Tab = (typeof tabs)[number];

export function ProjectWorkspacePage() {
  const { projectId } = useParams();
  const workspace = useWorkspace();
  const [activeTab, setActiveTab] = useState<Tab>("Mapa e editor");
  const [message, setMessage] = useState<string | null>(null);
  const [runtimePatch, setRuntimePatch] = useState<Partial<Project>>({});
  const startedPendingPdf = useRef(false);
  const response = useApi<{
    project: Project;
    latest_version: { id: string; lot_count: number; is_published: boolean } | null;
    share_links: Array<{ id: string; url: string | null; has_password: boolean; allow_edit: boolean; active: boolean }>;
  }>(`/api/v1/projects/${projectId}`);

  const baseProject = response.data?.project ?? workspace.projects.find((item) => item.id === projectId);
  const project = useMemo(() => baseProject ? { ...baseProject, ...runtimePatch } : undefined, [baseProject, runtimePatch]);
  const shareUrl = useMemo(() => {
    if (!project) return "";
    const backendUrl = response.data?.share_links.find((link) => link.active)?.url;
    if (backendUrl) return backendUrl;
    const path = sharePath(project);
    return path.startsWith("http") ? path : `${window.location.origin}${path}`;
  }, [project, response.data?.share_links]);

  function handleDetailsSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!project) return;
    const form = new FormData(event.currentTarget);
    updateProject(project.id, {
      name: String(form.get("name") ?? project.name),
      description: String(form.get("description") ?? project.description),
      status: String(form.get("status") ?? project.status) as Project["status"],
    });
    setMessage("Alteracoes do projeto salvas.");
  }

  function handleAccessSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!project) return;
    const form = new FormData(event.currentTarget);
    const visibility = String(form.get("visibility") ?? project.visibility) as Visibility;
    const password = String(form.get("password") ?? "");
    updateProject(project.id, {
      visibility,
      allowEdit: form.get("allowEdit") === "on",
      passwordEnabled: visibility === "password" && password.trim().length > 0,
    });
    setMessage("Acesso salvo. O link publico foi atualizado.");
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setMessage("Link copiado.");
    } catch {
      setMessage(`Copie o link manualmente: ${shareUrl}`);
    }
  }

  function publish() {
    if (!project) return;
    publishProject(project.id);
    setMessage("Versao publicada. O link ja pode ser enviado ao cliente.");
  }

  const applyProjectPatch = useCallback((patch: Partial<Project>) => {
    setRuntimePatch((current) => ({ ...current, ...patch }));
    if (baseProject) setProjectProcessing(baseProject.id, patch);
  }, [baseProject?.id]);

  const startProcessing = useCallback(async (file: File, selectedQuality?: Project["quality"]) => {
    if (!project) return;
    const quality = selectedQuality ?? project.quality ?? "balanced";
    attachProjectPdf(project.id, file.name, quality);
    applyProjectPatch({
      pdfName: file.name,
      quality,
      processingStatus: "processing",
      processingProgress: 2,
      processingError: undefined,
      mapUrl: undefined,
      processingLog: ["Enviando PDF para o motor de mapeamento."],
    });
    setMessage(null);
    const body = new FormData();
    body.append("upload", file);
    try {
      const uploadResponse = await fetch(`/api/v1/projects/${project.id}/files?kind=source_pdf`, {
        method: "POST",
        credentials: "same-origin",
        body,
      });
      const uploadPayload = await uploadResponse.json();
      if (!uploadResponse.ok) throw new Error(uploadPayload.detail ?? "Nao foi possivel enviar o PDF.");
      const query = new URLSearchParams({ quality, source_file_id: uploadPayload.file.id });
      const jobResponse = await fetch(`/api/v1/projects/${project.id}/processing-jobs?${query}`, {
        method: "POST",
        credentials: "same-origin",
      });
      const payload = await jobResponse.json();
      if (!jobResponse.ok) throw new Error(payload.detail ?? "Nao foi possivel iniciar o processamento.");
      applyProjectPatch({
        processingJobId: payload.job.id,
        processingProgress: payload.job.progress ?? 0,
        processingLog: jobLogLines(payload.job.logs),
      });
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Nao foi possivel processar o PDF.";
      applyProjectPatch({ processingStatus: "failed", processingError: detail, processingLog: [detail] });
      setMessage(detail);
    }
  }, [project, applyProjectPatch]);

  useEffect(() => {
    if (!project || startedPendingPdf.current) return;
    startedPendingPdf.current = true;
    const pendingFile = takeProjectPdf(project.id);
    if (pendingFile) void startProcessing(pendingFile, project.quality);
  }, [project, startProcessing]);

  useEffect(() => {
    if (!project?.processingJobId || project.processingStatus !== "processing") return;
    let cancelled = false;
    const poll = async () => {
      try {
        const response = await fetch(`/api/v1/processing-jobs/${project.processingJobId}`, { cache: "no-store", credentials: "same-origin" });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail ?? "Nao foi possivel consultar o processamento.");
        if (cancelled) return;
        const job = payload.job;
        if (job.status === "succeeded") {
          applyProjectPatch({
            status: "review",
            processingStatus: "processed",
            processingProgress: 100,
            processingLog: jobLogLines(job.logs),
            processingError: undefined,
            mapUrl: `/projects/${project.id}/editor`,
            version: Math.max(project.version, 1),
          });
          setMessage("Mapa concluido. O editor esta pronto para revisao.");
          return;
        }
        if (job.status === "failed") {
          applyProjectPatch({
            processingStatus: "failed",
            processingProgress: job.progress,
            processingLog: jobLogLines(job.logs),
            processingError: job.error_message,
          });
          setMessage(job.error_message ?? "O processamento falhou.");
          return;
        }
        applyProjectPatch({
          processingStatus: "processing",
          processingProgress: job.progress,
          processingLog: jobLogLines(job.logs),
        });
      } catch (error) {
        if (!cancelled) setMessage(error instanceof Error ? error.message : "Falha ao acompanhar o processamento.");
      }
    };
    void poll();
    const timer = window.setInterval(poll, 900);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [project?.id, project?.processingJobId, project?.processingStatus, project?.version, applyProjectPatch]);

  if (!project) {
    return (
      <div className="rounded-[8px] border border-orange-300/25 bg-orange-300/8 p-6">
        <h1 className="text-2xl font-medium text-orange-100">Projeto nao encontrado</h1>
        <p className="mt-2 text-slate-300">Volte para a lista e escolha um projeto existente.</p>
        <Link to="/app" className="mt-5 inline-flex rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950">Voltar aos projetos</Link>
      </div>
    );
  }

  function handlePdfChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    if (file) void startProcessing(file, project?.quality);
    event.currentTarget.value = "";
  }

  function handleQualityChange(event: ChangeEvent<HTMLSelectElement>) {
    if (!project) return;
    updateProject(project.id, { quality: event.currentTarget.value as Project["quality"] });
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.22em] text-emerald-300">projeto</p>
          <h1 className="mt-3 text-4xl font-medium tracking-tight text-white">{project.name}</h1>
          <p className="mt-2 text-slate-400">{project.client} · {project.lots} lotes · {project.updatedAt}</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Link to="/app" className="rounded-[8px] border border-white/12 px-4 py-3 text-sm font-medium">Voltar</Link>
          {project.mapUrl ? (
            <a href={projectEditorUrl(project)} className="inline-flex items-center gap-2 rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950">
              <Play size={17} weight="bold" />
              Abrir editor
            </a>
          ) : (
            <span className="inline-flex items-center gap-2 rounded-[8px] border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium text-slate-400">
              <Play size={17} weight="bold" />
              {project.processingStatus === "processing" ? "Processando mapa" : "Aguardando PDF"}
            </span>
          )}
        </div>
      </div>
      {response.error && !response.error.startsWith("Modo demo local") ? <p className="rounded-[8px] border border-orange-300/25 bg-orange-300/8 p-3 text-sm text-orange-100">{response.error}</p> : null}
      {message ? <p className="rounded-[8px] border border-emerald-300/25 bg-emerald-300/8 p-3 text-sm text-emerald-100">{message}</p> : null}

      <div className="flex gap-2 overflow-x-auto border-b border-white/10 pb-2">
        {tabs.map((tab) => (
          <button key={tab} onClick={() => setActiveTab(tab)} className={`shrink-0 rounded-[8px] px-4 py-2 text-sm font-medium transition ${activeTab === tab ? "bg-emerald-400 text-slate-950" : "bg-white/6 text-slate-300 hover:bg-white/10"}`}>
            {tab}
          </button>
        ))}
      </div>

      {activeTab === "Visao geral" ? <Overview project={project} onSubmit={handleDetailsSubmit} /> : null}
      {activeTab === "Mapa e editor" ? <Editor project={project} onPdfChange={handlePdfChange} onQualityChange={handleQualityChange} onRetry={() => document.getElementById("workspace-pdf")?.click()} /> : null}
      {activeTab === "Validacao" ? <Validation /> : null}
      {activeTab === "Versoes" ? <Versions project={project} onPublish={publish} /> : null}
      {activeTab === "Publicacao" ? <Publication project={project} shareUrl={shareUrl} onSubmit={handleAccessSubmit} onCopy={copyLink} onPublish={publish} /> : null}
      {activeTab === "Acessos" ? <Access project={project} shareUrl={shareUrl} /> : null}
      {activeTab === "Atividade" ? <ActivityList /> : null}
    </div>
  );
}

function Overview({ project, onSubmit }: { project: Project; onSubmit: (event: FormEvent<HTMLFormElement>) => void }) {
  return (
    <section className="grid gap-6 xl:grid-cols-[1fr_360px]">
      <form onSubmit={onSubmit} className="rounded-[8px] border border-white/10 bg-white/4 p-6">
        <h2 className="text-2xl font-medium">Dados do projeto</h2>
        <div className="mt-6 grid gap-5">
          <Field name="name" label="Nome" defaultValue={project.name} />
          <label>
            <span className="mb-2 block text-sm font-medium text-slate-300">Descricao</span>
            <textarea name="description" defaultValue={project.description} rows={4} className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300" />
          </label>
          <label>
            <span className="mb-2 block text-sm font-medium text-slate-300">Estado</span>
            <select name="status" defaultValue={project.status} className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300">
              <option value="draft">Rascunho</option>
              <option value="review">Em revisao</option>
              <option value="published">Publicado</option>
              <option value="paused">Pausado</option>
            </select>
          </label>
          <button className="w-fit rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950">Salvar alteracoes</button>
        </div>
      </form>
      <div className="grid gap-4">
        <Metric label="Lotes" value={project.lots || 0} />
        <Metric label="Versao" value={project.version} />
        <Metric label="Status" value={statusLabel(project.status)} />
      </div>
    </section>
  );
}

function Editor({ project, onPdfChange, onQualityChange, onRetry }: { project: Project; onPdfChange: (event: ChangeEvent<HTMLInputElement>) => void; onQualityChange: (event: ChangeEvent<HTMLSelectElement>) => void; onRetry: () => void }) {
  const progress = project.processingProgress ?? 0;
  const status = project.processingStatus ?? "empty";
  return (
    <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
      <div className="rounded-[8px] border border-white/10 bg-white/4 p-6">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div>
            <h2 className="text-2xl font-medium">Gerar mapa a partir do PDF</h2>
            <p className="mt-2 max-w-2xl text-slate-400">
              Escolha a qualidade e selecione o PDF. O mapeamento comeca automaticamente; ao concluir, o editor fica disponivel para revisao.
            </p>
          </div>
          <span className={`rounded-[8px] px-3 py-2 text-xs font-medium ${status === "processed" ? "bg-emerald-300/12 text-emerald-200" : "bg-orange-300/12 text-orange-100"}`}>
            {processingLabel(status)}
          </span>
        </div>

        <div className="mt-7 grid gap-5">
          <div>
            <span className="mb-2 block text-sm font-medium text-slate-300">PDF do empreendimento</span>
            <input id="workspace-pdf" name="pdf" type="file" accept="application/pdf,.pdf" onChange={onPdfChange} disabled={status === "processing"} className="sr-only" />
            <label htmlFor="workspace-pdf" className="flex cursor-pointer items-center justify-between gap-4 rounded-[8px] border border-dashed border-emerald-300/35 bg-emerald-300/7 p-4 transition hover:bg-emerald-300/10">
              <span className="flex min-w-0 items-center gap-3">
                <FilePdf className="shrink-0 text-emerald-300" size={24} weight="bold" />
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{project.pdfName || "Escolher arquivo PDF"}</span>
                  <span className="mt-1 block text-xs text-slate-400">Arquivo usado para gerar ou substituir o mapa deste projeto.</span>
                </span>
              </span>
              <span className="shrink-0 rounded-[8px] border border-white/12 px-3 py-2 text-xs font-medium">Selecionar</span>
            </label>
          </div>

          <label>
            <span className="mb-2 block text-sm font-medium text-slate-300">Qualidade do fundo</span>
            <select name="quality" value={project.quality ?? "balanced"} onChange={onQualityChange} disabled={status === "processing"} className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300 disabled:opacity-50">
              <option value="light">Leve</option>
              <option value="balanced">Equilibrada</option>
              <option value="high">Alta qualidade</option>
            </select>
          </label>

          <div className="flex flex-wrap gap-3">
            <button type="button" onClick={onRetry} disabled={status === "processing"} className="inline-flex items-center gap-2 rounded-[8px] border border-white/12 px-4 py-3 text-sm font-medium transition hover:bg-white/8 disabled:cursor-not-allowed disabled:opacity-50">
              <UploadSimple size={17} weight="bold" />
              {status === "failed" ? "Tentar com outro PDF" : project.pdfName ? "Substituir PDF" : "Selecionar PDF"}
            </button>
            {project.mapUrl ? (
              <a href={projectEditorUrl(project)} className="inline-flex items-center gap-2 rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300">
                <Play size={17} weight="bold" />
                Abrir editor
              </a>
            ) : null}
          </div>
        </div>

        <div className="mt-7 rounded-[8px] border border-white/10 bg-black/20 p-4">
          <div className="flex items-center justify-between gap-4 text-sm">
            <span className="text-slate-300">Progresso</span>
            <span className="font-medium text-emerald-200">{progress}%</span>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
            <div className={`h-full rounded-full bg-emerald-400 transition-all duration-500 ${status === "processing" ? "animate-pulse" : ""}`} style={{ width: `${progress}%` }} />
          </div>
          <div className="mt-4 space-y-2 text-sm text-slate-300">
            {(project.processingLog?.length ? project.processingLog : ["Nenhum PDF processado ainda."]).map((line, index) => (
              <p key={`${line}-${index}`} className="flex gap-2">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-emerald-300" />
                <span>{line}</span>
              </p>
            ))}
            {project.processingError ? <p className="text-orange-200">{project.processingError}</p> : null}
          </div>
        </div>
      </div>

      <div className="rounded-[8px] border border-white/10 bg-white/4 p-6">
        <h3 className="text-xl font-medium">Depois de gerar</h3>
        <div className="mt-5 space-y-4 text-sm text-slate-300">
          <Step done={Boolean(project.pdfName)} label="PDF anexado" />
          <Step done={status === "processed"} label="Mapa processado" />
          <Step done={project.status === "published"} label="Versao publicada" />
          <Step done={project.visibility !== "private" || project.passwordEnabled} label="Link configurado" />
        </div>
        <div className="mt-6 grid gap-3">
          <Link to={`/mapas/${project.slug}`} className="rounded-[8px] border border-white/12 px-4 py-3 text-center text-sm font-medium">Ver link do cliente</Link>
          <p className="text-xs leading-5 text-slate-500">O link do cliente abre somente o mapa. Ferramentas de edicao ficam escondidas por padrao.</p>
        </div>
      </div>
    </section>
  );
}

function Step({ done, label }: { done: boolean; label: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className={`grid size-6 place-items-center rounded-[8px] ${done ? "bg-emerald-300/15 text-emerald-200" : "bg-white/8 text-slate-400"}`}>
        {done ? <CheckCircle size={16} weight="fill" /> : <span className="size-2 rounded-full bg-current" />}
      </span>
      <span>{label}</span>
    </div>
  );
}

function processingLabel(status: Project["processingStatus"]) {
  if (status === "processed") return "Mapa gerado";
  if (status === "processing") return "Processando";
  if (status === "ready") return "PDF pronto";
  if (status === "failed") return "Falhou";
  return "Sem PDF";
}

function Validation() {
  return (
    <section className="grid gap-4 md:grid-cols-2">
      {[
        ["Lotes sem nome", "12 itens para revisar", false],
        ["Geometrias invalidas", "Nenhum erro critico", true],
        ["Possiveis lotes agrupados", "3 pontos suspeitos", false],
        ["Sobreposicoes", "Dentro do limite esperado", true],
      ].map(([label, detail, ok]) => (
        <div key={String(label)} className="rounded-[8px] border border-white/10 p-5">
          <div className="flex items-center gap-3">
            {ok ? <CheckCircle className="text-emerald-300" size={22} weight="fill" /> : <WarningCircle className="text-orange-300" size={22} weight="bold" />}
            <h3 className="font-medium">{label}</h3>
          </div>
          <p className="mt-3 text-sm text-slate-400">{detail}</p>
        </div>
      ))}
    </section>
  );
}

function Versions({ project, onPublish }: { project: Project; onPublish: () => void }) {
  return (
    <section className="rounded-[8px] border border-white/10 bg-white/4 p-6">
      <h2 className="text-2xl font-medium">Versoes</h2>
      <div className="mt-5 divide-y divide-white/8">
        <div className="flex items-center justify-between gap-4 py-4">
          <div>
            <p className="font-medium">Versao {project.version || 1}</p>
            <p className="text-sm text-slate-400">{project.status === "published" ? "Publicada" : "Rascunho atual"}</p>
          </div>
          <button onClick={onPublish} className="rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950">Publicar esta versao</button>
        </div>
      </div>
    </section>
  );
}

function Publication({ project, shareUrl, onSubmit, onCopy, onPublish }: { project: Project; shareUrl: string; onSubmit: (event: FormEvent<HTMLFormElement>) => void; onCopy: () => void; onPublish: () => void }) {
  return (
    <section className="grid gap-6 xl:grid-cols-[1fr_420px]">
      <form onSubmit={onSubmit} className="rounded-[8px] border border-white/10 bg-white/4 p-6">
        <h2 className="text-2xl font-medium">Entrega ao cliente</h2>
        <p className="mt-2 text-slate-400">Controle quem acessa, se precisa senha e se o cliente pode enviar proposta de edicao.</p>
        <div className="mt-7 grid gap-5">
          <label>
            <span className="mb-2 block text-sm font-medium text-slate-300">Visibilidade</span>
            <select name="visibility" defaultValue={project.visibility} className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300">
              <option value="private">Privado por login</option>
              <option value="password">Link protegido por senha</option>
              <option value="unlisted">Por link sem senha</option>
              <option value="public">Publico por URL</option>
            </select>
          </label>
          <Field name="password" label="Senha opcional" type="password" placeholder="Defina ou atualize a senha" />
          <label className="flex items-center justify-between gap-5 rounded-[8px] border border-white/10 p-4">
            <span>
              <span className="block font-medium">Permitir edicao pelo cliente</span>
              <span className="mt-1 block text-sm text-slate-400">Quando ligado, o cliente edita uma copia e envia proposta para aprovacao interna.</span>
            </span>
            <input name="allowEdit" type="checkbox" defaultChecked={project.allowEdit} className="size-5 accent-emerald-400" />
          </label>
          <div className="flex flex-wrap gap-3">
            <button className="inline-flex items-center gap-2 rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950">
              <FloppyDisk size={17} weight="bold" />
              Salvar acesso
            </button>
            <button type="button" onClick={onPublish} className="inline-flex items-center gap-2 rounded-[8px] border border-white/12 px-4 py-3 text-sm font-medium">
              <UploadSimple size={17} weight="bold" />
              Publicar versao
            </button>
          </div>
        </div>
      </form>
      <SharePanel project={project} shareUrl={shareUrl} onCopy={onCopy} />
    </section>
  );
}

function Access({ project, shareUrl }: { project: Project; shareUrl: string }) {
  return (
    <section className="rounded-[8px] border border-white/10 bg-white/4 p-6">
      <h2 className="text-2xl font-medium">Acessos ativos</h2>
      <div className="mt-5 grid gap-4">
        <div className="rounded-[8px] border border-white/10 p-4">
          <p className="font-medium">{visibilityLabel(project.visibility)}</p>
          <p className="mt-2 break-all text-sm text-emerald-200">{shareUrl}</p>
          <p className="mt-2 text-sm text-slate-400">{project.allowEdit ? "Cliente pode enviar proposta de edicao." : "Somente leitura para o cliente."}</p>
        </div>
      </div>
    </section>
  );
}

function ActivityList() {
  const workspace = useWorkspace();
  return (
    <section className="divide-y divide-white/8 rounded-[8px] border border-white/10">
      {workspace.activity.map((item, index) => (
        <div key={`${item}-${index}`} className="p-4 text-slate-300">{item}</div>
      ))}
    </section>
  );
}

function SharePanel({ project, shareUrl, onCopy }: { project: Project; shareUrl: string; onCopy: () => void }) {
  return (
    <aside className="space-y-5">
      <div className="rounded-[8px] border border-white/10 p-5">
        <h3 className="font-medium">Compartilhar</h3>
        <p className="mt-2 text-sm text-slate-400">Link atual da versao publicada.</p>
        <div className="mt-4 break-all rounded-[8px] border border-white/10 bg-black/20 p-3 text-sm text-emerald-200">{shareUrl}</div>
        <div className="mt-4 grid grid-cols-2 gap-3">
          <button onClick={onCopy} className="inline-flex items-center justify-center gap-2 rounded-[8px] border border-white/12 px-3 py-2 text-sm font-medium">
            <Copy size={16} weight="bold" />
            Copiar
          </button>
          <Link to={`/mapas/${project.slug}`} className="inline-flex items-center justify-center gap-2 rounded-[8px] border border-white/12 px-3 py-2 text-sm font-medium">
            <ArrowSquareOut size={16} weight="bold" />
            Abrir
          </Link>
        </div>
      </div>
      <div className="rounded-[8px] border border-white/10 p-5">
        <h3 className="font-medium">Checklist</h3>
        <div className="mt-4 space-y-3 text-sm">
          <Row icon={<Eye size={16} weight="bold" />} label="Visualizador somente leitura" ok={!project.allowEdit} />
          <Row icon={<LockKey size={16} weight="bold" />} label="Senha configuravel" ok={project.visibility !== "password" || project.passwordEnabled} />
          <Row icon={<CheckCircle size={16} weight="fill" />} label="Versao publicada" ok={project.status === "published"} />
        </div>
      </div>
    </aside>
  );
}

function Field({ name, label, defaultValue, type = "text", placeholder }: { name: string; label: string; defaultValue?: string; type?: string; placeholder?: string }) {
  return (
    <label>
      <span className="mb-2 block text-sm font-medium text-slate-300">{label}</span>
      <input name={name} type={type} defaultValue={defaultValue} placeholder={placeholder} className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300" />
    </label>
  );
}

function Metric({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-[8px] border border-white/10 p-5">
      <p className="text-sm text-slate-400">{label}</p>
      <p className="mt-3 text-2xl font-medium">{value}</p>
    </div>
  );
}

function Row({ icon, label, ok = false }: { icon: ReactNode; label: string; ok?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="flex items-center gap-2 text-slate-300">{icon}{label}</span>
      <span className={ok ? "text-emerald-300" : "text-orange-300"}>{ok ? "pronto" : "pendente"}</span>
    </div>
  );
}

function statusLabel(status: string) {
  if (status === "published") return "Publicado";
  if (status === "review") return "Em revisao";
  if (status === "paused") return "Pausado";
  return "Rascunho";
}

function visibilityLabel(visibility: Visibility) {
  if (visibility === "private") return "Privado por login";
  if (visibility === "password") return "Link protegido por senha";
  if (visibility === "public") return "Publico";
  return "Link sem senha";
}

function projectEditorUrl(project: Project) {
  if (!project.mapUrl) return "/gerador";
  const separator = project.mapUrl.includes("?") ? "&" : "?";
  return `${project.mapUrl}${separator}project_id=${encodeURIComponent(project.id)}`;
}

function jobLogLines(logs: unknown): string[] {
  if (!Array.isArray(logs)) return [];
  return logs.map((entry) => {
    if (typeof entry === "string") return entry;
    if (entry && typeof entry === "object" && "message" in entry) return String(entry.message);
    return String(entry);
  });
}
