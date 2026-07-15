import { useSyncExternalStore } from "react";

export type ProjectStatus = "draft" | "review" | "published" | "paused";
export type Visibility = "private" | "password" | "unlisted" | "public";

export type Project = {
  id: string;
  name: string;
  client: string;
  slug: string;
  status: ProjectStatus;
  lots: number;
  pdfName?: string;
  quality?: "light" | "balanced" | "high";
  processingStatus?: "empty" | "ready" | "processing" | "processed" | "failed";
  processingProgress?: number;
  processingLog?: string[];
  processingJobId?: string;
  processingError?: string;
  mapUrl?: string;
  shareUrl?: string;
  visibility: Visibility;
  allowEdit: boolean;
  passwordEnabled: boolean;
  description: string;
  updatedAt: string;
  version: number;
};

export type Client = {
  id: string;
  name: string;
  contacts: number;
  projects: number;
  access: "Ativo" | "Pendente" | "Pausado";
};

export type Workspace = {
  projects: Project[];
  clients: Client[];
  activity: string[];
  preferences: {
    quality: "light" | "balanced" | "high";
    opacity: number;
    labels: "auto" | "always" | "hidden";
    defaultVisibility: Visibility;
  };
  profile: {
    name: string;
    email: string;
  };
};

const STORAGE_KEY = "maplot.workspace.v2";

export const initialWorkspace: Workspace = {
  projects: [
    {
      id: "teste",
      name: "Mapa Setor E",
      client: "William Empreendimentos",
      slug: "setor-e-demo",
      status: "published",
      lots: 1509,
      pdfName: "20240502_MST_ARQ_MapaExterno_SETOR E_R00.pdf",
      quality: "high",
      processingStatus: "processed",
      processingProgress: 100,
      processingLog: ["PDF carregado.", "Lotes detectados.", "Versao publicada."],
      visibility: "password",
      allowEdit: false,
      passwordEnabled: true,
      description: "Mapa de disponibilidade publicado para demonstracao.",
      updatedAt: "Hoje, 14:38",
      version: 3,
    },
    {
      id: "aquiraz-d",
      name: "Aquiraz Setor D",
      client: "Costa Urbanismo",
      slug: "aquiraz-setor-d",
      status: "review",
      lots: 1602,
      pdfName: "AQUIRAZ_SETOR D.pdf",
      quality: "high",
      processingStatus: "processed",
      processingProgress: 100,
      processingLog: ["PDF carregado.", "Processamento concluido.", "Validacao pendente."],
      visibility: "private",
      allowEdit: false,
      passwordEnabled: false,
      description: "Projeto em revisao com pontos de validacao pendentes.",
      updatedAt: "Ontem, 19:04",
      version: 1,
    },
    {
      id: "setor-hi",
      name: "Setor H e I",
      client: "Reserva Litoral",
      slug: "setor-hi",
      status: "draft",
      lots: 1455,
      pdfName: "20240502_MST_ARQ_MapaExterno_SETOR h i um_R00.pdf",
      quality: "balanced",
      processingStatus: "ready",
      processingProgress: 0,
      processingLog: ["PDF anexado. Aguardando processamento."],
      visibility: "unlisted",
      allowEdit: false,
      passwordEnabled: false,
      description: "Rascunho aguardando publicacao.",
      updatedAt: "12 jul, 09:16",
      version: 1,
    },
  ],
  clients: [
    { id: "william-empreendimentos", name: "William Empreendimentos", contacts: 3, projects: 4, access: "Ativo" },
    { id: "costa-urbanismo", name: "Costa Urbanismo", contacts: 2, projects: 2, access: "Pendente" },
    { id: "reserva-litoral", name: "Reserva Litoral", contacts: 1, projects: 1, access: "Ativo" },
  ],
  activity: [
    "Mapa Setor E publicado em link protegido por senha.",
    "Aquiraz Setor D recebeu 17 pontos de validacao para revisar.",
    "Cliente Costa Urbanismo criado por William Gabriel.",
    "Versao anterior de Setor H e I preservada como historico.",
  ],
  preferences: {
    quality: "balanced",
    opacity: 70,
    labels: "auto",
    defaultVisibility: "unlisted",
  },
  profile: {
    name: "William Gabriel",
    email: "williammx50@gmail.com",
  },
};

const listeners = new Set<() => void>();
const pendingProjectPdfs = new Map<string, File>();

function slugify(value: string) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "")
    .slice(0, 64) || "projeto";
}

function uniqueSlug(base: string, projects: Project[]) {
  let slug = slugify(base);
  let count = 2;
  while (projects.some((project) => project.slug === slug)) {
    slug = `${slugify(base)}-${count}`;
    count += 1;
  }
  return slug;
}

function loadWorkspace(): Workspace {
  if (typeof window === "undefined") return initialWorkspace;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return initialWorkspace;
    return { ...initialWorkspace, ...JSON.parse(raw) };
  } catch {
    return initialWorkspace;
  }
}

let currentWorkspace = loadWorkspace();

function emit(next: Workspace) {
  currentWorkspace = next;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useWorkspace() {
  return useSyncExternalStore(subscribe, () => currentWorkspace, () => initialWorkspace);
}

export function getWorkspace() {
  return currentWorkspace;
}

export function sharePath(project: Project) {
  if (project.shareUrl) return project.shareUrl;
  if (project.visibility === "public") return `/p/${project.slug}`;
  return `/mapas/${project.slug}`;
}

export function createClient(name: string) {
  const cleanName = name.trim();
  if (!cleanName) throw new Error("Informe o nome do cliente.");
  const exists = currentWorkspace.clients.some((client) => client.name.toLowerCase() === cleanName.toLowerCase());
  if (exists) throw new Error("Esse cliente ja existe.");
  const client: Client = { id: slugify(cleanName), name: cleanName, contacts: 0, projects: 0, access: "Ativo" };
  emit({
    ...currentWorkspace,
    clients: [client, ...currentWorkspace.clients],
    activity: [`Cliente ${cleanName} criado.`, ...currentWorkspace.activity],
  });
  return client;
}

export function createProject(input: { name: string; client: string; description?: string; pdfName?: string; quality?: "light" | "balanced" | "high" }) {
  const name = input.name.trim();
  const client = input.client.trim();
  if (!name) throw new Error("Informe o nome do projeto.");
  if (!client) throw new Error("Selecione um cliente.");
  const project: Project = {
    id: `${slugify(name)}-${Date.now().toString(36)}`,
    name,
    client,
    slug: uniqueSlug(name, currentWorkspace.projects),
    status: "draft",
    lots: 0,
    pdfName: input.pdfName?.trim() || undefined,
    quality: input.quality ?? currentWorkspace.preferences.quality,
    processingStatus: input.pdfName ? "ready" : "empty",
    processingProgress: 0,
    processingLog: input.pdfName ? [`PDF ${input.pdfName} anexado.`] : ["Projeto criado sem PDF."],
    visibility: currentWorkspace.preferences.defaultVisibility,
    allowEdit: false,
    passwordEnabled: false,
    description: input.description?.trim() || "Projeto criado para processamento do mapa.",
    updatedAt: "Agora",
    version: 0,
  };
  emit({
    ...currentWorkspace,
    projects: [project, ...currentWorkspace.projects],
    clients: currentWorkspace.clients.map((row) => (row.name === client ? { ...row, projects: row.projects + 1 } : row)),
    activity: [`Projeto ${name} criado para ${client}.`, ...currentWorkspace.activity],
  });
  return project;
}

export function attachProjectPdf(id: string, pdfName: string, quality: "light" | "balanced" | "high") {
  const cleanName = pdfName.trim();
  if (!cleanName) throw new Error("Selecione um PDF.");
  return updateProject(id, {
    pdfName: cleanName,
    quality,
    processingStatus: "ready",
    processingProgress: 0,
    processingLog: [`PDF ${cleanName} anexado.`, "Pronto para gerar o mapa."],
  });
}

export function stashProjectPdf(id: string, file: File) {
  pendingProjectPdfs.set(id, file);
}

export function takeProjectPdf(id: string) {
  const file = pendingProjectPdfs.get(id);
  pendingProjectPdfs.delete(id);
  return file;
}

export function setProjectProcessing(id: string, patch: Partial<Project>) {
  let updated: Project | null = null;
  emit({
    ...currentWorkspace,
    projects: currentWorkspace.projects.map((project) => {
      if (project.id !== id) return project;
      updated = { ...project, ...patch, updatedAt: "Agora" };
      return updated;
    }),
  });
  return updated;
}

export function startDemoProcessing(id: string) {
  const project = currentWorkspace.projects.find((item) => item.id === id);
  if (!project) throw new Error("Projeto nao encontrado.");
  if (!project.pdfName) throw new Error("Anexe um PDF antes de gerar o mapa.");
  return updateProject(id, {
    status: "review",
    lots: project.lots || 1509,
    processingStatus: "processed",
    processingProgress: 100,
    processingLog: [
      `PDF ${project.pdfName} carregado.`,
      "Fundo renderizado na qualidade selecionada.",
      "Lotes detectados e numeracao aplicada.",
      "Mapa salvo como rascunho para revisao.",
    ],
    version: Math.max(project.version, 1),
  });
}

export function updateProject(id: string, patch: Partial<Project>) {
  let updated: Project | null = null;
  emit({
    ...currentWorkspace,
    projects: currentWorkspace.projects.map((project) => {
      if (project.id !== id) return project;
      updated = { ...project, ...patch, updatedAt: "Agora" };
      return updated;
    }),
    activity: [`Projeto ${patch.name ?? id} atualizado.`, ...currentWorkspace.activity],
  });
  return updated;
}

export function publishProject(id: string) {
  const project = currentWorkspace.projects.find((item) => item.id === id);
  if (!project) throw new Error("Projeto nao encontrado.");
  return updateProject(id, { status: "published", version: project.version + 1, lots: project.lots || 1509 });
}

export function updatePreferences(patch: Partial<Workspace["preferences"]>) {
  emit({
    ...currentWorkspace,
    preferences: { ...currentWorkspace.preferences, ...patch },
    activity: ["Preferencias da plataforma atualizadas.", ...currentWorkspace.activity],
  });
}

export function updateProfile(patch: Partial<Workspace["profile"]>) {
  emit({
    ...currentWorkspace,
    profile: { ...currentWorkspace.profile, ...patch },
    activity: ["Perfil do administrador atualizado.", ...currentWorkspace.activity],
  });
}
