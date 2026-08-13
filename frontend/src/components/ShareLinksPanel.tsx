import { ArrowSquareOut, Copy, LinkSimple, PencilSimple, Plus, Trash, X } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { apiRequest } from "../api";
import { formatDateTime, isPastDate, toApiDateTime, toLocalInputValue } from "../format";
import { ConfirmDialog } from "./ConfirmDialog";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "./DataStates";

// Espelha share_link_dict em app_v1/serialization.py:108.
export type ShareLink = {
  id: string;
  project_id: string;
  url: string | null;
  has_password: boolean;
  access_mode: string;
  allow_edit: boolean;
  active: boolean;
  expires_at: string | null;
  last_used_at: string | null;
  access_count: number;
  created_at: string | null;
};

type PasswordAction = "keep" | "set" | "clear";

const accessModes = [
  { value: "token", label: "Link com token secreto", hint: "Endereco unico e sorteado. Quem tiver o link entra." },
  { value: "password", label: "Link protegido por senha", hint: "Alem do endereco, o visitante precisa digitar a senha." },
  { value: "public", label: "Publico pela URL do projeto", hint: "Endereco fixo do projeto, sem token e sem senha." },
  { value: "private", label: "Restrito a usuarios do cliente", hint: "Exige login de alguem com acesso ao cliente." },
];

export function ShareLinksPanel({
  projectId,
  onLinksChange,
}: {
  projectId: string;
  onLinksChange?: (links: ShareLink[]) => void;
}) {
  const [links, setLinks] = useState<ShareLink[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [createMode, setCreateMode] = useState("token");
  const [submitting, setSubmitting] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<ShareLink | null>(null);
  const [revokeBusy, setRevokeBusy] = useState(false);
  const [showRevoked, setShowRevoked] = useState(false);
  const [noticeFocusToken, setNoticeFocusToken] = useState(0);
  const noticeRef = useRef<HTMLDivElement>(null);
  // Callback do pai muda de identidade a cada render; a ref evita refazer a
  // busca em loop por causa da dependencia do efeito.
  const notify = useRef(onLinksChange);

  useEffect(() => {
    notify.current = onLinksChange;
  });

  useEffect(() => {
    // Revogar apaga o botao que abriu o dialogo; sem reposicionar, o teclado
    // voltaria para o topo da pagina.
    if (noticeFocusToken) noticeRef.current?.focus();
  }, [noticeFocusToken]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    apiRequest<{ share_links: ShareLink[] }>(`/api/v1/projects/${projectId}/share-links`)
      .then((payload) => {
        if (cancelled) return;
        setLinks(payload.share_links);
        notify.current?.(payload.share_links);
        setLoading(false);
      })
      .catch((error: Error) => {
        if (cancelled) return;
        setLinks(null);
        setLoadError(error.message);
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, nonce]);

  function commit(next: ShareLink[]) {
    setLinks(next);
    notify.current?.(next);
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // Referencia guardada antes do await: o React zera currentTarget quando o
    // handler cede o controle e o reset() depois falharia.
    const formElement = event.currentTarget;
    const data = new FormData(formElement);
    const accessMode = String(data.get("access_mode") ?? "token");
    const password = String(data.get("password") ?? "").trim();
    setSubmitting(true);
    setActionError(null);
    try {
      const payload = await apiRequest<{ share_link: ShareLink }>(`/api/v1/projects/${projectId}/share-links`, {
        method: "POST",
        body: JSON.stringify({
          access_mode: accessMode,
          password: accessMode === "password" && password ? password : null,
          allow_edit: data.get("allow_edit") === "on",
          expires_at: toApiDateTime(String(data.get("expires_at") ?? "")),
        }),
      });
      commit([payload.share_link, ...(links ?? [])]);
      formElement.reset();
      setCreateMode("token");
      setCreating(false);
      setNotice("Link criado. Copie o endereco e envie ao cliente.");
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Nao foi possivel criar o link.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleUpdate(link: ShareLink, event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const data = new FormData(formElement);
    const passwordAction = String(data.get("password_action") ?? "keep") as PasswordAction;
    const password = String(data.get("password") ?? "").trim();
    const body: Record<string, unknown> = {
      allow_edit: data.get("allow_edit") === "on",
      expires_at: toApiDateTime(String(data.get("expires_at") ?? "")),
    };
    // ShareLinkUpdate limpa a senha quando a chave chega com null
    // (app_v1/api.py:726). Por isso "manter" precisa omitir o campo.
    if (passwordAction === "set") body.password = password;
    if (passwordAction === "clear") body.password = null;
    setSubmitting(true);
    setActionError(null);
    try {
      const payload = await apiRequest<{ share_link: ShareLink }>(`/api/v1/share-links/${link.id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      commit((links ?? []).map((row) => (row.id === link.id ? payload.share_link : row)));
      setEditingId(null);
      setNotice("Link atualizado.");
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Nao foi possivel atualizar o link.");
    } finally {
      setSubmitting(false);
    }
  }

  async function confirmRevoke() {
    if (!revoking) return;
    const target = revoking;
    setRevokeBusy(true);
    setActionError(null);
    try {
      // DELETE devolve 204 e apiRequest entrega null; o estado local ja sai da
      // lista ativa para nao depender de recarregar a pagina.
      await apiRequest(`/api/v1/share-links/${target.id}`, { method: "DELETE" });
      commit((links ?? []).map((row) => (row.id === target.id ? { ...row, active: false } : row)));
      if (editingId === target.id) setEditingId(null);
      setRevoking(null);
      setNotice("Link revogado. Quem tiver o endereco antigo perde o acesso agora.");
      setNoticeFocusToken((value) => value + 1);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Nao foi possivel revogar o link.");
    } finally {
      setRevokeBusy(false);
    }
  }

  async function copyLink(link: ShareLink) {
    if (!link.url) {
      setNotice("Este link ainda nao tem endereco publico gerado.");
      return;
    }
    try {
      await navigator.clipboard.writeText(link.url);
      setNotice("Link copiado para a area de transferencia.");
    } catch {
      setNotice(`Nao foi possivel usar a area de transferencia. Copie manualmente: ${link.url}`);
    }
  }

  const activeLinks = (links ?? []).filter((link) => link.active);
  const revokedLinks = (links ?? []).filter((link) => !link.active);

  return (
    <section className="rounded-[8px] border border-white/10 bg-white/4 p-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          <h2 className="text-2xl font-medium">Links de compartilhamento</h2>
          <p className="mt-2 max-w-2xl text-slate-400">
            Cada link e um endereco independente com regra propria de acesso, senha e validade. Revogar um link nao afeta os
            outros.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setCreating((value) => !value);
            setActionError(null);
          }}
          aria-expanded={creating}
          className="inline-flex shrink-0 items-center gap-2 rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300"
        >
          {creating ? <X size={17} weight="bold" /> : <Plus size={17} weight="bold" />}
          {creating ? "Fechar formulario" : "Novo link"}
        </button>
      </div>

      {/* Regiao viva sempre montada: criada so na hora do aviso, o leitor de tela nao anunciaria. */}
      <div role="status" aria-live="polite" ref={noticeRef} tabIndex={-1} className="focus-visible:ring-2 focus-visible:ring-emerald-300">
        {notice ? (
          <p className="mt-5 rounded-[8px] border border-emerald-300/25 bg-emerald-300/8 p-3 text-sm text-emerald-100">{notice}</p>
        ) : null}
      </div>
      {/* Com o dialogo aberto o aviso vai para dentro dele; aqui atras ficaria invisivel. */}
      {actionError && !revoking ? (
        <p role="alert" className="mt-5 rounded-[8px] border border-orange-300/25 bg-orange-300/8 p-3 text-sm text-orange-100">
          {actionError}
        </p>
      ) : null}

      {creating ? (
        <form onSubmit={handleCreate} className="mt-6 grid gap-5 rounded-[8px] border border-white/10 bg-black/20 p-5">
          <label>
            <span className="mb-2 block text-sm font-medium text-slate-300">Modo de acesso</span>
            <select
              name="access_mode"
              value={createMode}
              onChange={(event) => setCreateMode(event.currentTarget.value)}
              className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300"
            >
              {accessModes.map((mode) => (
                <option key={mode.value} value={mode.value}>
                  {mode.label}
                </option>
              ))}
            </select>
            <span className="mt-2 block text-xs text-slate-500">
              {accessModes.find((mode) => mode.value === createMode)?.hint}
            </span>
          </label>
          {createMode === "password" ? (
            <label>
              <span className="mb-2 block text-sm font-medium text-slate-300">Senha do link</span>
              <input
                name="password"
                type="password"
                required
                autoComplete="new-password"
                maxLength={128}
                className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300"
              />
            </label>
          ) : null}
          <label>
            <span className="mb-2 block text-sm font-medium text-slate-300">Expira em (opcional)</span>
            <input
              name="expires_at"
              type="datetime-local"
              className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300"
            />
            <span className="mt-2 block text-xs text-slate-500">Sem data preenchida o link vale ate ser revogado.</span>
          </label>
          <label className="flex items-center justify-between gap-5 rounded-[8px] border border-white/10 p-4">
            <span>
              <span className="block font-medium">Permitir proposta de edicao</span>
              <span className="mt-1 block text-sm text-slate-400">
                O visitante edita uma copia e envia proposta para aprovacao interna.
              </span>
            </span>
            <input name="allow_edit" type="checkbox" className="size-5 accent-emerald-400 focus-visible:ring-2 focus-visible:ring-emerald-300" />
          </label>
          <div className="flex flex-wrap gap-3">
            <button
              disabled={submitting}
              className="rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? "Criando..." : "Criar link"}
            </button>
            <button
              type="button"
              onClick={() => setCreating(false)}
              className="rounded-[8px] border border-white/12 px-4 py-3 text-sm font-medium transition hover:bg-white/8 focus-visible:ring-2 focus-visible:ring-emerald-300"
            >
              Cancelar
            </button>
          </div>
        </form>
      ) : null}

      <div className="mt-6">
        {loading ? (
          <LoadingBlock label="Carregando links de compartilhamento..." rows={2} />
        ) : loadError ? (
          <ErrorBlock message={loadError} onRetry={() => setNonce((value) => value + 1)} />
        ) : activeLinks.length === 0 ? (
          <EmptyBlock
            title="Nenhum link ativo"
            description="Publique uma versao do projeto e crie um link para o cliente abrir o mapa. Cada link pode ter senha, validade e permissao de edicao proprias."
            action={
              <button
                type="button"
                onClick={() => setCreating(true)}
                className="inline-flex items-center gap-2 rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300"
              >
                <Plus size={17} weight="bold" />
                Criar primeiro link
              </button>
            }
          />
        ) : (
          <div className="divide-y divide-white/8 rounded-[8px] border border-white/10">
            {activeLinks.map((link) => (
              <LinkRow
                key={link.id}
                link={link}
                editing={editingId === link.id}
                submitting={submitting}
                onCopy={() => copyLink(link)}
                onEdit={() => {
                  setEditingId((current) => (current === link.id ? null : link.id));
                  setActionError(null);
                }}
                onCancelEdit={() => setEditingId(null)}
                onSubmitEdit={(event) => handleUpdate(link, event)}
                onRevoke={() => {
                  setRevoking(link);
                  setActionError(null);
                }}
              />
            ))}
          </div>
        )}
      </div>

      {revokedLinks.length ? (
        <div className="mt-5">
          <button
            type="button"
            onClick={() => setShowRevoked((value) => !value)}
            aria-expanded={showRevoked}
            className="rounded-[8px] border border-white/10 px-3 py-2 text-sm text-slate-300 transition hover:bg-white/8 focus-visible:ring-2 focus-visible:ring-emerald-300"
          >
            {showRevoked ? "Ocultar" : "Ver"} {revokedLinks.length} link{revokedLinks.length > 1 ? "s" : ""} revogado
            {revokedLinks.length > 1 ? "s" : ""}
          </button>
          {showRevoked ? (
            <ul className="mt-3 divide-y divide-white/8 rounded-[8px] border border-white/10">
              {revokedLinks.map((link) => (
                <li key={link.id} className="flex flex-wrap items-center justify-between gap-3 p-4 text-sm text-slate-400">
                  <span className="break-all">{link.url ?? "Endereco nao disponivel"}</span>
                  <span className="shrink-0 rounded-[8px] bg-white/6 px-2 py-1 text-xs uppercase tracking-[0.14em] text-slate-400">
                    revogado
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {revoking ? (
        <ConfirmDialog
          title="Revogar este link?"
          description={
            <>
              <p>
                O endereco <span className="break-all text-emerald-200">{revoking.url ?? revoking.id}</span> para de funcionar
                imediatamente para todo mundo que ja recebeu.
              </p>
              <p className="mt-2">Esta acao nao pode ser desfeita por esta tela. Para liberar de novo, crie um link novo.</p>
            </>
          }
          confirmLabel="Revogar link"
          cancelLabel="Manter link"
          busy={revokeBusy}
          busyLabel="Revogando..."
          error={actionError}
          onConfirm={confirmRevoke}
          onCancel={() => {
            if (!revokeBusy) setRevoking(null);
          }}
        />
      ) : null}
    </section>
  );
}

function LinkRow({
  link,
  editing,
  submitting,
  onCopy,
  onEdit,
  onCancelEdit,
  onSubmitEdit,
  onRevoke,
}: {
  link: ShareLink;
  editing: boolean;
  submitting: boolean;
  onCopy: () => void;
  onEdit: () => void;
  onCancelEdit: () => void;
  onSubmitEdit: (event: FormEvent<HTMLFormElement>) => void;
  onRevoke: () => void;
}) {
  const [passwordAction, setPasswordAction] = useState<PasswordAction>("keep");
  const expired = isPastDate(link.expires_at);

  // Fechar a edicao volta a escolha para "manter": reabrir com "trocar senha"
  // selecionado exigiria digitar uma senha nova sem o operador ter pedido isso.
  useEffect(() => {
    if (!editing) setPasswordAction("keep");
  }, [editing]);

  return (
    <article className="p-5">
      <div className="flex flex-wrap items-center gap-3">
        <LinkSimple className="text-emerald-300" size={20} weight="bold" />
        <h3 className="font-medium">{accessModeLabel(link.access_mode)}</h3>
        <Badge tone={expired ? "warn" : "ok"}>{expired ? "Expirado" : "Ativo"}</Badge>
        <Badge tone={link.has_password ? "ok" : "neutral"}>{link.has_password ? "Com senha" : "Sem senha"}</Badge>
        <Badge tone={link.allow_edit ? "warn" : "neutral"}>{link.allow_edit ? "Permite edicao" : "Somente leitura"}</Badge>
      </div>
      <p className="mt-3 break-all text-sm text-emerald-200">{link.url ?? "Endereco nao disponivel para este link."}</p>
      <p className="mt-2 text-xs leading-5 text-slate-500">
        {link.expires_at ? `${expired ? "Expirou" : "Expira"} em ${formatDateTime(link.expires_at)}` : "Sem data de expiracao"}
        {" · "}
        {link.access_count} {link.access_count === 1 ? "acesso" : "acessos"}
        {" · "}
        {link.last_used_at ? `ultimo uso em ${formatDateTime(link.last_used_at)}` : "nunca usado"}
        {link.created_at ? ` · criado em ${formatDateTime(link.created_at)}` : ""}
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onCopy}
          className="inline-flex items-center gap-2 rounded-[8px] border border-white/12 px-3 py-2 text-sm font-medium transition hover:bg-white/8 focus-visible:ring-2 focus-visible:ring-emerald-300"
        >
          <Copy size={16} weight="bold" />
          Copiar
        </button>
        {link.url ? (
          <a
            href={link.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-[8px] border border-white/12 px-3 py-2 text-sm font-medium transition hover:bg-white/8 focus-visible:ring-2 focus-visible:ring-emerald-300"
          >
            <ArrowSquareOut size={16} weight="bold" />
            Abrir
          </a>
        ) : null}
        <button
          type="button"
          onClick={onEdit}
          aria-expanded={editing}
          className="inline-flex items-center gap-2 rounded-[8px] border border-white/12 px-3 py-2 text-sm font-medium transition hover:bg-white/8 focus-visible:ring-2 focus-visible:ring-emerald-300"
        >
          <PencilSimple size={16} weight="bold" />
          {editing ? "Fechar edicao" : "Editar"}
        </button>
        <button
          type="button"
          onClick={onRevoke}
          aria-label={`Revogar link ${link.url ?? accessModeLabel(link.access_mode)}`}
          className="inline-flex items-center gap-2 rounded-[8px] border border-orange-300/30 px-3 py-2 text-sm font-medium text-orange-100 transition hover:bg-orange-300/12 focus-visible:ring-2 focus-visible:ring-emerald-300"
        >
          <Trash size={16} weight="bold" />
          Revogar
        </button>
      </div>

      {editing ? (
        <form onSubmit={onSubmitEdit} className="mt-5 grid gap-5 rounded-[8px] border border-white/10 bg-black/20 p-5">
          <p className="text-xs text-slate-500">
            O modo de acesso e definido na criacao e a API nao permite troca-lo depois. Para mudar de modo, crie outro link e
            revogue este.
          </p>
          <label>
            <span className="mb-2 block text-sm font-medium text-slate-300">Senha</span>
            <select
              name="password_action"
              value={passwordAction}
              onChange={(event) => setPasswordAction(event.currentTarget.value as PasswordAction)}
              className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300"
            >
              <option value="keep">{link.has_password ? "Manter senha atual" : "Continuar sem senha"}</option>
              <option value="set">{link.has_password ? "Trocar senha" : "Definir senha"}</option>
              {link.has_password ? <option value="clear">Remover senha</option> : null}
            </select>
          </label>
          {passwordAction === "set" ? (
            <label>
              <span className="mb-2 block text-sm font-medium text-slate-300">Nova senha</span>
              <input
                name="password"
                type="password"
                required
                autoComplete="new-password"
                maxLength={128}
                className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300"
              />
            </label>
          ) : null}
          <label>
            <span className="mb-2 block text-sm font-medium text-slate-300">Expira em</span>
            <input
              name="expires_at"
              type="datetime-local"
              defaultValue={toLocalInputValue(link.expires_at)}
              className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300"
            />
            <span className="mt-2 block text-xs text-slate-500">Apague a data para deixar o link sem prazo.</span>
          </label>
          <label className="flex items-center justify-between gap-5 rounded-[8px] border border-white/10 p-4">
            <span className="font-medium">Permitir proposta de edicao</span>
            <input
              name="allow_edit"
              type="checkbox"
              defaultChecked={link.allow_edit}
              className="size-5 accent-emerald-400 focus-visible:ring-2 focus-visible:ring-emerald-300"
            />
          </label>
          <div className="flex flex-wrap gap-3">
            <button
              disabled={submitting}
              className="rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? "Salvando..." : "Salvar link"}
            </button>
            <button
              type="button"
              onClick={onCancelEdit}
              className="rounded-[8px] border border-white/12 px-4 py-3 text-sm font-medium transition hover:bg-white/8 focus-visible:ring-2 focus-visible:ring-emerald-300"
            >
              Cancelar
            </button>
          </div>
        </form>
      ) : null}
    </article>
  );
}

function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "ok" | "warn" | "neutral" }) {
  const palette =
    tone === "ok"
      ? "bg-emerald-300/12 text-emerald-200"
      : tone === "warn"
        ? "bg-orange-300/12 text-orange-100"
        : "bg-white/8 text-slate-300";
  return <span className={`rounded-[8px] px-2 py-1 text-xs font-medium ${palette}`}>{children}</span>;
}

function accessModeLabel(mode: string) {
  return accessModes.find((item) => item.value === mode)?.label ?? mode;
}
