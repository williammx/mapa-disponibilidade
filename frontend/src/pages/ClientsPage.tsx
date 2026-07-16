import { Buildings, EnvelopeSimple, Gear, Plus } from "@phosphor-icons/react";
import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { apiRequest, isLocalDemoMode, useApi } from "../api";
import { InviteUserDialog } from "../components/InviteUserDialog";
import { SectionHeader } from "../components/SectionHeader";
import { createClient, useWorkspace } from "../workspace";

type OrganizationsResponse = {
  organizations: Array<{ id: string; name: string; active: boolean; project_count: number; contact_count: number }>;
};

export function ClientsPage() {
  const workspace = useWorkspace();
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inviting, setInviting] = useState<{ id: string; name: string } | null>(null);
  const response = useApi<OrganizationsResponse>("/api/v1/organizations");
  const rows = response.data?.organizations.map((org) => ({
    id: org.id,
    name: org.name,
    contacts: org.contact_count,
    projects: org.project_count,
    access: org.active ? "Ativo" : "Pausado",
  })) ?? (isLocalDemoMode ? workspace.clients : []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const name = String(form.get("name") ?? "").trim();
    try {
      if (isLocalDemoMode) {
        createClient(name);
      } else {
        await apiRequest("/api/v1/organizations", {
          method: "POST",
          body: JSON.stringify({ name, slug: slugify(name) }),
        });
      }
      setShowForm(false);
      setError(null);
      event.currentTarget.reset();
      if (!isLocalDemoMode) window.location.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nao foi possivel criar o cliente.");
    }
  }

  return (
    <div className="space-y-9">
      <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
        <SectionHeader eyebrow="clientes" title="Imobiliarias e empreendimentos" description="Organize organizacoes, contatos, usuarios, permissoes e projetos liberados." />
        <button onClick={() => setShowForm((value) => !value)} className="inline-flex w-fit items-center gap-2 rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300 active:translate-y-px">
          <Plus size={17} weight="bold" />
          Novo cliente
        </button>
      </div>

      {showForm ? (
        <form onSubmit={handleSubmit} className="grid gap-4 rounded-[8px] border border-white/10 bg-white/4 p-5 md:grid-cols-[1fr_auto] md:items-end">
          <label>
            <span className="mb-2 block text-sm font-medium text-slate-300">Nome do cliente</span>
            <input name="name" required placeholder="Ex.: Horizonte Urbanismo" className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300" />
          </label>
          <button className="rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950">Cadastrar</button>
          {error ? <p className="md:col-span-2 rounded-[8px] border border-orange-300/25 bg-orange-300/8 p-3 text-sm text-orange-100">{error}</p> : null}
        </form>
      ) : null}

      {response.error ? <p className="rounded-[8px] border border-orange-300/25 bg-orange-300/8 p-3 text-sm text-orange-100">{response.error}</p> : null}
      <div className="grid gap-4">
        {rows.map((client) => (
          <article key={client.id ?? client.name} className="grid gap-5 rounded-[8px] border border-white/10 p-5 transition hover:bg-white/5 md:grid-cols-[1fr_auto_auto_auto_auto] md:items-center">
            <div className="flex items-center gap-4">
              <span className="grid size-11 place-items-center rounded-[8px] bg-white/8 text-emerald-300">
                <Buildings size={22} weight="bold" />
              </span>
              <div>
                <h2 className="font-medium">{client.name}</h2>
                <p className="text-sm text-slate-400">{client.contacts} contatos cadastrados</p>
              </div>
            </div>
            <span className="text-sm text-slate-300">{client.projects} projetos</span>
            <span className="text-sm text-slate-300">{client.access}</span>
            <Link to={`/app/clientes/${client.id}`} className="inline-flex items-center justify-center gap-2 rounded-[8px] border border-white/12 px-3 py-2 text-sm font-medium transition hover:bg-white/8">
              <Gear size={16} weight="bold" /> Gerenciar
            </Link>
            <button onClick={() => setInviting({ id: client.id, name: client.name })} className="inline-flex items-center justify-center gap-2 rounded-[8px] border border-white/12 px-3 py-2 text-sm font-medium transition hover:bg-white/8 active:translate-y-px">
              <EnvelopeSimple size={16} weight="bold" /> Convidar
            </button>
          </article>
        ))}
      </div>
      {inviting ? <InviteUserDialog organizationId={inviting.id} organizationName={inviting.name} onClose={() => setInviting(null)} /> : null}
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
    .slice(0, 80) || "cliente";
}
