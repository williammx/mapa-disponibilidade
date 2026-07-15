import { Buildings, Check, EnvelopeSimple, Plus } from "@phosphor-icons/react";
import { FormEvent, useState } from "react";
import { useApi } from "../api";
import { SectionHeader } from "../components/SectionHeader";
import { createClient, useWorkspace } from "../workspace";

type OrganizationsResponse = {
  organizations: Array<{ id: string; name: string; active: boolean }>;
};

export function ClientsPage() {
  const workspace = useWorkspace();
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [invited, setInvited] = useState<string | null>(null);
  const response = useApi<OrganizationsResponse>("/api/v1/organizations");
  const rows = response.data?.organizations.map((org) => ({
    id: org.id,
    name: org.name,
    contacts: 0,
    projects: 0,
    access: org.active ? "Ativo" : "Pausado",
  })) ?? workspace.clients;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      createClient(String(form.get("name") ?? ""));
      setShowForm(false);
      setError(null);
      event.currentTarget.reset();
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
          <article key={client.id ?? client.name} className="grid gap-5 rounded-[8px] border border-white/10 p-5 transition hover:bg-white/5 md:grid-cols-[1fr_auto_auto_auto] md:items-center">
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
            <button onClick={() => setInvited(client.name)} className="inline-flex items-center justify-center gap-2 rounded-[8px] border border-white/12 px-3 py-2 text-sm font-medium transition hover:bg-white/8 active:translate-y-px">
              {invited === client.name ? <Check size={16} weight="bold" /> : <EnvelopeSimple size={16} weight="bold" />}
              {invited === client.name ? "Convite pronto" : "Convidar"}
            </button>
          </article>
        ))}
      </div>
    </div>
  );
}
