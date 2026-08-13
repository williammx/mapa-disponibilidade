import { Buildings, EnvelopeSimple, FolderOpen, Pause, Play, UserCircle } from "@phosphor-icons/react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiRequest, useApi } from "../api";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/DataStates";
import { InviteUserDialog } from "../components/InviteUserDialog";
import type { Project } from "../workspace";

type ClientDetail = {
  organization: { id: string; name: string; slug: string; active: boolean };
  members: Array<{ membership_id: string; role: string; user: { id: string; name: string; email: string; active: boolean } }>;
  projects: Project[];
};

export function ClientDetailPage() {
  const { organizationId } = useParams();
  const [inviteOpen, setInviteOpen] = useState(false);
  const [patch, setPatch] = useState<{ name?: string; active?: boolean }>({});
  const [message, setMessage] = useState<string | null>(null);
  const [toggling, setToggling] = useState(false);
  const response = useApi<ClientDetail>(`/api/v1/organizations/${organizationId}`);
  const organization = response.data?.organization ? { ...response.data.organization, ...patch } : null;

  async function toggleActive() {
    if (!organization) return;
    setToggling(true);
    try {
      const active = !organization.active;
      await apiRequest(`/api/v1/organizations/${organization.id}`, { method: "PATCH", body: JSON.stringify({ active }) });
      setPatch((current) => ({ ...current, active }));
      setMessage(active ? "Cliente reativado." : "Cliente pausado. Os dados foram preservados.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Nao foi possivel atualizar o cliente.");
    } finally {
      setToggling(false);
    }
  }

  if (response.loading) return <LoadingBlock label="Carregando cliente..." />;
  if (!organization) {
    return (
      <div className="space-y-5">
        <ErrorBlock message={response.error ?? "Cliente nao encontrado."} onRetry={response.reload} />
        <Link
          to="/app/clientes"
          className="inline-flex rounded-[8px] border border-white/12 px-4 py-3 text-sm font-medium transition hover:bg-white/8 focus-visible:ring-2 focus-visible:ring-emerald-300"
        >
          Voltar para clientes
        </Link>
      </div>
    );
  }

  const members = response.data?.members ?? [];
  const projects = response.data?.projects ?? [];

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.22em] text-emerald-300">cliente</p>
          <h1 className="mt-3 text-4xl font-medium">{organization.name}</h1>
          <p className="mt-2 text-slate-400">{members.length} usuarios · {projects.length} projetos · {organization.active ? "Ativo" : "Pausado"}</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Link to="/app/clientes" className="rounded-[8px] border border-white/12 px-4 py-3 text-sm font-medium transition hover:bg-white/8 focus-visible:ring-2 focus-visible:ring-emerald-300">Voltar</Link>
          <button onClick={() => setInviteOpen(true)} className="inline-flex items-center gap-2 rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300"><EnvelopeSimple size={17} /> Convidar usuario</button>
        </div>
      </div>
      {/* Regiao viva permanente: o aviso nasce depois da acao e precisa ser anunciado. */}
      <div role="status" aria-live="polite">
        {message ? <p className="rounded-[8px] border border-emerald-300/25 bg-emerald-300/8 p-3 text-sm text-emerald-100">{message}</p> : null}
      </div>

      <section className="grid gap-5 lg:grid-cols-[1fr_320px]">
        <div className="rounded-[8px] border border-white/10">
          <div className="border-b border-white/10 p-5"><h2 className="text-xl font-medium">Usuarios e permissoes</h2></div>
          {members.length ? (
            <div className="divide-y divide-white/8">
              {members.map((member) => (
                <div key={member.membership_id} className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-center gap-3"><span className="grid size-10 place-items-center rounded-[8px] bg-white/7 text-emerald-300"><UserCircle size={21} /></span><div><p className="font-medium">{member.user.name}</p><p className="text-sm text-slate-400">{member.user.email}</p></div></div>
                  <span className="text-sm text-slate-300">{member.role === "client_admin" ? "Administrador do cliente" : "Colaborador"}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="p-5">
              <EmptyBlock
                title="Nenhum usuario vinculado"
                description="Sem usuario vinculado ninguem deste cliente consegue entrar no portal. Convide alguem para gerar o acesso e a senha temporaria."
                action={
                  <button
                    type="button"
                    onClick={() => setInviteOpen(true)}
                    className="inline-flex items-center gap-2 rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300"
                  >
                    <EnvelopeSimple size={17} /> Convidar usuario
                  </button>
                }
              />
            </div>
          )}
        </div>
        <aside className="rounded-[8px] border border-white/10 p-5">
          <Buildings size={23} className="text-emerald-300" />
          <h2 className="mt-5 text-xl font-medium">Situacao do cliente</h2>
          <p className="mt-2 text-sm leading-6 text-slate-400">Pausar bloqueia a operacao sem apagar projetos, mapas ou historico.</p>
          <button onClick={toggleActive} disabled={toggling} className="mt-6 inline-flex w-full items-center justify-center gap-2 rounded-[8px] border border-white/12 px-4 py-3 text-sm font-medium transition hover:bg-white/8 focus-visible:ring-2 focus-visible:ring-emerald-300 disabled:cursor-not-allowed disabled:opacity-60">{organization.active ? <Pause size={17} /> : <Play size={17} />} {toggling ? "Salvando..." : organization.active ? "Pausar cliente" : "Reativar cliente"}</button>
        </aside>
      </section>

      <section>
        <div className="flex items-center justify-between"><h2 className="text-xl font-medium">Projetos</h2><span className="text-sm text-slate-400">{projects.length} cadastrados</span></div>
        {projects.length ? (
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            {projects.map((project) => (
              <Link key={project.id} to={`/app/projetos/${project.id}`} className="flex items-center justify-between gap-4 rounded-[8px] border border-white/10 p-5 transition hover:bg-white/5 focus-visible:ring-2 focus-visible:ring-emerald-300">
                <div><p className="font-medium">{project.name}</p><p className="mt-1 text-sm text-slate-400">{project.lots} lotes · {project.status}</p></div><FolderOpen size={21} className="text-emerald-300" />
              </Link>
            ))}
          </div>
        ) : (
          <div className="mt-4">
            <EmptyBlock
              title="Nenhum projeto para este cliente"
              description="Projetos sao criados na tela de projetos, escolhendo este cliente e anexando o PDF do empreendimento."
              action={
                <Link
                  to="/app"
                  className="inline-flex rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300"
                >
                  Criar projeto
                </Link>
              }
            />
          </div>
        )}
      </section>
      {inviteOpen ? (
        <InviteUserDialog
          organizationId={organization.id}
          organizationName={organization.name}
          onClose={() => {
            setInviteOpen(false);
            // A atualizacao da lista espera o fechamento: recarregar com o
            // dialogo aberto o desmontaria antes de mostrar a senha temporaria.
            response.reload();
          }}
          onCreated={() => setMessage("Usuario convidado com sucesso.")}
        />
      ) : null}
    </div>
  );
}
