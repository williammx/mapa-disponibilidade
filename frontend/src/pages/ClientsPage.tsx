import { Buildings, EnvelopeSimple, Gear, Plus } from "@phosphor-icons/react";
import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { apiRequest, isLocalDemoMode, useApi } from "../api";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/DataStates";
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
  const [notice, setNotice] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [inviting, setInviting] = useState<{ id: string; name: string } | null>(null);
  const response = useApi<OrganizationsResponse>("/api/v1/organizations");
  const demoFallback = isLocalDemoMode && Boolean(response.error?.startsWith("Modo demo local"));
  const rows = response.data?.organizations.map((org) => ({
    id: org.id,
    name: org.name,
    contacts: org.contact_count,
    projects: org.project_count,
    access: org.active ? "Ativo" : "Pausado",
  })) ?? (demoFallback ? workspace.clients : []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // currentTarget e anulado pelo React assim que o handler cede o controle
    // num await. Guardar a referencia antes e o que mantem o reset() vivo.
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const name = String(form.get("name") ?? "").trim();
    setSubmitting(true);
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
      formElement.reset();
      setNotice(`Cliente ${name} cadastrado.`);
      // Recarregar a lista basta; antes a pagina inteira era recarregada.
      if (!isLocalDemoMode) response.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nao foi possivel criar o cliente.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-9">
      <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
        <SectionHeader eyebrow="clientes" title="Imobiliarias e empreendimentos" description="Organize organizacoes, contatos, usuarios, permissoes e projetos liberados." />
        <button onClick={() => setShowForm((value) => !value)} aria-expanded={showForm} className="inline-flex w-fit items-center gap-2 rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300 active:translate-y-px">
          <Plus size={17} weight="bold" />
          Novo cliente
        </button>
      </div>

      {showForm ? (
        <form onSubmit={handleSubmit} className="grid gap-4 rounded-[8px] border border-white/10 bg-white/4 p-5 md:grid-cols-[1fr_auto] md:items-end">
          <label>
            <span className="mb-2 block text-sm font-medium text-slate-300">Nome do cliente</span>
            <input name="name" required placeholder="Ex.: Horizonte Urbanismo" className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300" />
          </label>
          <button disabled={submitting} className="rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300 disabled:cursor-not-allowed disabled:opacity-60">
            {submitting ? "Cadastrando..." : "Cadastrar"}
          </button>
          {error ? <p role="alert" className="md:col-span-2 rounded-[8px] border border-orange-300/25 bg-orange-300/8 p-3 text-sm text-orange-100">{error}</p> : null}
        </form>
      ) : null}

      {/* Regiao viva permanente para o aviso de cadastro chegar ao leitor de tela. */}
      <div role="status" aria-live="polite">
        {notice ? <p className="rounded-[8px] border border-emerald-300/25 bg-emerald-300/8 p-3 text-sm text-emerald-100">{notice}</p> : null}
      </div>

      {response.loading ? (
        <LoadingBlock label="Carregando clientes..." rows={3} />
      ) : response.error && !demoFallback ? (
        <ErrorBlock message={response.error} onRetry={response.reload} />
      ) : rows.length === 0 ? (
        <EmptyBlock
          title="Nenhum cliente cadastrado"
          description="Cada projeto pertence a um cliente. Cadastre a primeira imobiliaria ou empreendimento para conseguir criar projetos e liberar acessos."
          action={
            <button
              type="button"
              onClick={() => setShowForm(true)}
              className="inline-flex items-center gap-2 rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300"
            >
              <Plus size={17} weight="bold" />
              Cadastrar cliente
            </button>
          }
        />
      ) : (
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
              <Link to={`/app/clientes/${client.id}`} className="inline-flex items-center justify-center gap-2 rounded-[8px] border border-white/12 px-3 py-2 text-sm font-medium transition hover:bg-white/8 focus-visible:ring-2 focus-visible:ring-emerald-300">
                <Gear size={16} weight="bold" /> Gerenciar
              </Link>
              <button onClick={() => setInviting({ id: client.id, name: client.name })} className="inline-flex items-center justify-center gap-2 rounded-[8px] border border-white/12 px-3 py-2 text-sm font-medium transition hover:bg-white/8 focus-visible:ring-2 focus-visible:ring-emerald-300 active:translate-y-px">
                <EnvelopeSimple size={16} weight="bold" /> Convidar
              </button>
            </article>
          ))}
        </div>
      )}
      {inviting ? (
        <InviteUserDialog
          organizationId={inviting.id}
          organizationName={inviting.name}
          onClose={() => {
            setInviting(null);
            // Atualiza a contagem de contatos so depois de fechar, para nao
            // desmontar o dialogo antes de o operador copiar a senha.
            response.reload();
          }}
          onCreated={() => setNotice(`Usuario convidado para ${inviting.name}.`)}
        />
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
    .slice(0, 80) || "cliente";
}
