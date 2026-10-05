import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { apiRequest, useApi } from "../api";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/DataStates";
import { SectionHeader } from "../components/SectionHeader";

const scopes = [
  ["capabilities:read", "Consultar capacidades"],
  ["jobs:write", "Enviar processamento"],
  ["jobs:read", "Consultar processamento"],
  ["jobs:cancel", "Cancelar processamento"],
  ["results:read", "Consultar resultados"],
  ["projects:read", "Consultar projetos"],
  ["projects:write", "Criar e editar projetos"],
  ["publications:write", "Publicar mapas"],
  ["shares:read", "Consultar links compartilhados"],
  ["shares:write", "Criar e revogar links compartilhados"],
] as const;

type Organization = { id: string; name: string; active: boolean };
type KeyMetadata = {
  id: string; name: string; organization_id: string; project_id: string | null;
  scopes: string[]; created_at: string; expires_at: string | null; revoked_at: string | null;
};
const field = "w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300 disabled:opacity-50";
const button = "rounded-[8px] border border-white/12 px-4 py-3 text-sm font-medium transition hover:bg-white/8 focus-visible:ring-2 focus-visible:ring-emerald-300 disabled:cursor-not-allowed disabled:opacity-50";
const primary = "rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300 disabled:cursor-not-allowed disabled:opacity-50";

function dateLabel(value: string | null) {
  if (!value) return "Sem expiracao";
  // The API serializes UTC database timestamps without a timezone suffix.
  const date = new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? "Data indisponivel" : date.toLocaleString("pt-BR");
}
function expired(value: string | null) {
  return value ? new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`).getTime() <= Date.now() : false;
}

export function IntegrationsPage() {
  const organizations = useApi<{ organizations: Organization[] }>("/api/v1/organizations");
  const [organizationId, setOrganizationId] = useState("");
  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
        <SectionHeader eyebrow="administracao" title="Integracoes" description="Crie acessos para sistemas externos com permissoes limitadas por organizacao e projeto." />
        <a href="/api/integrations/v1/docs" target="_blank" rel="noopener noreferrer" className={`${button} w-fit shrink-0`}>Documentacao OpenAPI</a>
      </div>
      <p className="max-w-3xl text-sm leading-6 text-slate-400">A chave funciona como uma senha. Compartilhe somente com o sistema autorizado e revogue acessos que nao sao mais usados.</p>
      {organizations.loading ? <LoadingBlock label="Carregando organizacoes..." rows={2} /> : organizations.error ? <ErrorBlock message={organizations.error} onRetry={organizations.reload} /> : !organizations.data?.organizations.length ? <EmptyBlock title="Nenhuma organizacao cadastrada" description="Cadastre um cliente antes de configurar uma integracao." /> : (
        <>
          <label className="block max-w-xl">
            <span className="mb-2 block text-sm font-medium text-slate-300">Organizacao</span>
            <select aria-label="Organizacao" className={field} value={organizationId} onChange={event => setOrganizationId(event.target.value)}>
              <option value="">Selecione uma organizacao</option>
              {organizations.data.organizations.map(org => <option key={org.id} value={org.id}>{org.name}{org.active ? "" : " (pausada)"}</option>)}
            </select>
          </label>
          {organizationId ? <OrganizationKeys key={organizationId} organizationId={organizationId} active={organizations.data.organizations.find(org => org.id === organizationId)?.active ?? false} /> : <EmptyBlock title="Selecione uma organizacao" description="As chaves e os projetos exibidos pertencem apenas a organizacao selecionada." />}
        </>
      )}
    </div>
  );
}

function OrganizationKeys({ organizationId, active }: { organizationId: string; active: boolean }) {
  const keys = useApi<{ api_keys: KeyMetadata[] }>(`/api/v1/integration-api-keys?organization_id=${encodeURIComponent(organizationId)}`);
  const [creating, setCreating] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<KeyMetadata | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  async function revoke() {
    if (!revoking || busy) return;
    setBusy(true);
    setError(null);
    try {
      await apiRequest(`/api/v1/integration-api-keys/${encodeURIComponent(revoking.id)}`, { method: "DELETE" });
      if (!mounted.current) return;
      setRevoking(null);
      setNotice("Chave revogada. O acesso foi encerrado.");
      keys.reload();
    } catch (err) {
      if (mounted.current) setError(err instanceof Error ? err.message : "Nao foi possivel revogar a chave.");
    } finally { if (mounted.current) setBusy(false); }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-xl font-medium">Chaves de API</h2>
        <button className={primary} disabled={!active || creating || Boolean(secret)} onClick={() => { setCreating(true); setNotice(null); }}>Nova chave</button>
      </div>
      {!active ? <p role="status" className="text-sm text-orange-100">Organizacao pausada: novas chaves nao podem ser criadas.</p> : null}
      <div role="status" aria-live="polite">{notice ? <p className="rounded-[8px] border border-emerald-300/25 bg-emerald-300/8 p-3 text-sm text-emerald-100">{notice}</p> : null}</div>
      {creating ? <CreateKeyForm organizationId={organizationId} onCancel={() => setCreating(false)} onCreated={value => { setCreating(false); setSecret(value); keys.reload(); }} /> : null}
      {keys.loading ? <LoadingBlock label="Carregando chaves..." /> : keys.error ? <ErrorBlock message={keys.error} onRetry={keys.reload} /> : !keys.data?.api_keys.length ? <EmptyBlock title="Nenhuma chave cadastrada" description="Crie uma chave com apenas as permissoes necessarias para a integracao." /> : (
        <div className="grid gap-4">
          {keys.data.api_keys.map(key => (
            <article key={key.id} className="min-w-0 rounded-[8px] border border-white/10 p-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0"><h3 className="break-words font-medium">{key.name}</h3><p className="mt-1 text-sm text-slate-400">{key.revoked_at ? "Revogada" : expired(key.expires_at) ? "Expirada" : "Ativa"}</p></div>
                <button className={button} disabled={Boolean(key.revoked_at) || busy} aria-label={`Revogar ${key.name}`} onClick={() => { setError(null); setRevoking(key); }}>Revogar</button>
              </div>
              <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
                <div><dt className="text-slate-400">Criada em</dt><dd className="mt-1">{dateLabel(key.created_at)}</dd></div>
                <div><dt className="text-slate-400">Expira em</dt><dd className="mt-1">{dateLabel(key.expires_at)}</dd></div>
                <div><dt className="text-slate-400">Restricao de projeto</dt><dd className="mt-1 break-all">{key.project_id ?? "Todos os projetos da organizacao"}</dd></div>
                <div><dt className="text-slate-400">ID da chave</dt><dd className="mt-1 break-all">{key.id}</dd></div>
                {key.revoked_at ? <div><dt className="text-slate-400">Revogada em</dt><dd className="mt-1">{dateLabel(key.revoked_at)}</dd></div> : null}
              </dl>
              <div className="mt-4 flex flex-wrap gap-2" aria-label="Permissoes">{key.scopes.map(scope => <span key={scope} className="rounded-[6px] bg-white/6 px-2 py-1 text-xs text-slate-300">{scope}</span>)}</div>
            </article>
          ))}
        </div>
      )}
      {secret ? <SecretDialog secret={secret} onClose={() => { setSecret(null); setNotice("Chave criada. O segredo nao sera exibido novamente."); }} /> : null}
      {revoking ? <ConfirmDialog title="Revogar chave?" description={<>O sistema que usa a chave <span className="font-medium">{revoking.name}</span> perdera o acesso imediatamente. Esta acao nao pode ser desfeita.</>} confirmLabel="Revogar chave" busyLabel="Revogando..." busy={busy} error={error} onConfirm={revoke} onCancel={() => { if (!busy) { setRevoking(null); setError(null); } }} /> : null}
    </div>
  );
}

function CreateKeyForm({ organizationId, onCancel, onCreated }: { organizationId: string; onCancel: () => void; onCreated: (secret: string) => void }) {
  const projects = useApi<{ projects: Array<{ id: string; name: string }> }>(`/api/v1/organizations/${encodeURIComponent(organizationId)}`);
  const [selectedScopes, setSelectedScopes] = useState<string[]>(["capabilities:read"]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setError(null);
    const form = new FormData(event.currentTarget);
    const name = String(form.get("name") ?? "").trim();
    const expiry = String(form.get("expiry") ?? "");
    if (!name || !selectedScopes.length) { setError("Informe um nome e selecione pelo menos uma permissao."); return; }
    if (expiry && new Date(expiry).getTime() <= Date.now()) { setError("A expiracao deve ser uma data futura."); return; }
    setBusy(true);
    try {
      const response = await apiRequest<{ key: string; api_key: KeyMetadata }>("/api/v1/integration-api-keys", {
        method: "POST", body: JSON.stringify({ name, organization_id: organizationId, project_id: String(form.get("project") ?? "") || null, scopes: selectedScopes, ...(expiry ? { expires_at: new Date(expiry).toISOString() } : {}) }),
      });
      if (mounted.current) onCreated(response.key);
    } catch (err) { if (mounted.current) setError(err instanceof Error ? err.message : "Nao foi possivel criar a chave."); }
    finally { if (mounted.current) setBusy(false); }
  }
  return (
    <form onSubmit={submit} className="space-y-5 rounded-[8px] border border-white/10 bg-white/4 p-5">
      <h3 className="text-lg font-medium">Nova chave de integracao</h3>
      <fieldset disabled={busy} className="space-y-5">
        <div className="grid gap-4 md:grid-cols-2">
          <label><span className="mb-2 block text-sm text-slate-300">Nome da chave</span><input name="name" required maxLength={160} className={field} placeholder="Ex.: CRM comercial" /></label>
          <label><span className="mb-2 block text-sm text-slate-300">Expiracao (opcional)</span><input name="expiry" type="datetime-local" className={field} /><span className="mt-2 block text-xs text-slate-400">Horario local. Em branco: validade padrao do servidor (90 dias).</span></label>
        </div>
        {projects.loading ? <LoadingBlock label="Carregando projetos..." rows={1} /> : projects.error ? <ErrorBlock message={projects.error} onRetry={projects.reload} /> : (
          <label className="block"><span className="mb-2 block text-sm text-slate-300">Projeto (opcional)</span><select aria-label="Projeto (opcional)" name="project" className={field}><option value="">Todos os projetos da organizacao</option>{projects.data?.projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
        )}
        <fieldset><legend className="mb-3 text-sm font-medium text-slate-300">Permissoes</legend><div className="grid gap-3 sm:grid-cols-2">{scopes.map(([scope, description]) => <label key={scope} className="flex items-start gap-3 rounded-[8px] border border-white/8 p-3"><input type="checkbox" className="mt-1 accent-emerald-400" checked={selectedScopes.includes(scope)} onChange={event => setSelectedScopes(current => event.target.checked ? [...current, scope] : current.filter(value => value !== scope))} /><span className="min-w-0 text-sm"><span className="block text-slate-100">{scope}</span><span className="mt-1 block text-xs text-slate-400">{description}</span></span></label>)}</div></fieldset>
      </fieldset>
      {error ? <p role="alert" className="rounded-[8px] border border-orange-300/25 bg-orange-300/8 p-3 text-sm text-orange-100">{error}</p> : null}
      <div className="flex flex-wrap gap-3"><button disabled={busy || !selectedScopes.length || projects.loading || Boolean(projects.error)} className={primary}>{busy ? "Criando..." : "Criar chave"}</button><button type="button" disabled={busy} className={button} onClick={onCancel}>Cancelar criacao</button></div>
    </form>
  );
}

function SecretDialog({ secret, onClose }: { secret: string; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  async function copy() {
    setError(null);
    try { await navigator.clipboard.writeText(secret); setCopied(true); }
    catch { setError("Nao foi possivel copiar. Selecione a chave e copie manualmente."); }
  }
  return (
    <dialog ref={dialog} aria-labelledby="integration-secret-title" onCancel={event => { event.preventDefault(); onClose(); }} onClick={event => { if (event.target === event.currentTarget) { const rect = event.currentTarget.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose(); } }} className="m-auto w-[calc(100%-2rem)] max-w-xl rounded-[8px] border border-white/12 bg-[#10191f] p-6 text-slate-100 shadow-xl backdrop:bg-black/70">
      <h2 id="integration-secret-title" className="text-xl font-medium">Copie sua chave agora</h2>
      <p className="mt-3 text-sm leading-6 text-slate-300">Este segredo aparece somente uma vez. Salve em um gerenciador de segredos antes de fechar. Ao sair desta tela, ele sera descartado.</p>
      <code className="mt-5 block select-all break-all rounded-[8px] bg-[#091217] p-4 text-sm text-emerald-200">{secret}</code>
      <div role="status" aria-live="polite" className="mt-3 text-sm text-emerald-200">{copied ? "Chave copiada." : ""}</div>
      {error ? <p role="alert" className="mt-3 text-sm text-orange-100">{error}</p> : null}
      <div className="mt-5 flex flex-wrap gap-3"><button type="button" className={primary} onClick={copy}>Copiar chave</button><button type="button" className={button} onClick={onClose}>Ja salvei a chave</button></div>
    </dialog>
  );
}
