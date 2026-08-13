import { CheckCircle, Copy, X } from "@phosphor-icons/react";
import { FormEvent, useEffect, useRef, useState } from "react";
import { apiRequest } from "../api";

type InviteResult = {
  membership: { id: string; role: string; user: { name: string; email: string } };
  temporary_password: string | null;
  login_url: string;
};

export function InviteUserDialog({ organizationId, organizationName, onClose, onCreated }: {
  organizationId: string;
  organizationName: string;
  onClose: () => void;
  onCreated?: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<InviteResult | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [copied, setCopied] = useState(false);
  // Handler novo a cada render do pai; a ref mantem o efeito de teclado unico.
  const closeHandler = useRef(onClose);

  useEffect(() => {
    closeHandler.current = onClose;
  });

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") closeHandler.current();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      opener?.focus();
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setSubmitting(true);
    setError(null);
    try {
      const payload = await apiRequest<InviteResult>(`/api/v1/organizations/${organizationId}/invitations`, {
        method: "POST",
        body: JSON.stringify({
          name: String(data.get("name") ?? "").trim(),
          email: String(data.get("email") ?? "").trim(),
          role: String(data.get("role") ?? "client_member"),
        }),
      });
      setResult(payload);
      onCreated?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nao foi possivel criar o acesso.");
    } finally {
      setSubmitting(false);
    }
  }

  async function copyCredentials() {
    if (!result) return;
    const lines = [
      `Acesso NexoLote - ${organizationName}`,
      `Link: ${window.location.origin}${result.login_url}`,
      `Email: ${result.membership.user.email}`,
      result.temporary_password ? `Senha temporaria: ${result.temporary_password}` : "Use a senha atual da conta.",
    ];
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopied(true);
    } catch {
      // Sem area de transferencia (navegador antigo ou contexto inseguro) o
      // erro precisa aparecer, senao o clique parece nao ter feito nada.
      setError("Nao foi possivel copiar automaticamente. Selecione os dados acima e copie manualmente.");
    }
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4" role="presentation">
      <section role="dialog" aria-modal="true" aria-labelledby="invite-title" className="w-full max-w-lg rounded-[8px] border border-white/12 bg-[#10191f] p-6 shadow-2xl">
        <div className="flex items-start justify-between gap-5">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.2em] text-emerald-300">acesso do cliente</p>
            <h2 id="invite-title" className="mt-2 text-2xl font-medium">Convidar para {organizationName}</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Fechar convite" className="grid size-9 place-items-center rounded-[8px] border border-white/10 text-slate-300 transition hover:bg-white/8 focus-visible:ring-2 focus-visible:ring-emerald-300">
            <X size={18} />
          </button>
        </div>

        {result ? (
          <div className="mt-6 space-y-5">
            <div className="rounded-[8px] border border-emerald-300/25 bg-emerald-300/8 p-4">
              <p className="flex items-center gap-2 font-medium text-emerald-100"><CheckCircle size={19} weight="fill" /> Acesso criado</p>
              <p className="mt-2 text-sm text-slate-300">{result.membership.user.name} ja pode acessar os projetos liberados deste cliente.</p>
            </div>
            <div className="grid gap-3 rounded-[8px] border border-white/10 bg-black/20 p-4 text-sm">
              <p><span className="text-slate-400">Email</span><br />{result.membership.user.email}</p>
              <p><span className="text-slate-400">Senha</span><br />{result.temporary_password ?? "A conta ja existia e manteve a senha atual."}</p>
              {result.temporary_password ? <p className="text-xs text-orange-100">A senha aparece somente agora. O usuario devera troca-la no primeiro acesso.</p> : null}
            </div>
            {error ? <p role="alert" className="rounded-[8px] border border-orange-300/25 bg-orange-300/8 p-3 text-sm text-orange-100">{error}</p> : null}
            <div role="status" aria-live="polite" className="sr-only">
              {copied ? "Credenciais copiadas para a area de transferencia." : ""}
            </div>
            <div className="flex justify-end gap-3">
              <button type="button" onClick={copyCredentials} className="inline-flex items-center gap-2 rounded-[8px] border border-white/12 px-4 py-3 text-sm font-medium transition hover:bg-white/8 focus-visible:ring-2 focus-visible:ring-emerald-300">
                <Copy size={17} /> {copied ? "Copiado" : "Copiar credenciais"}
              </button>
              <button type="button" onClick={onClose} className="rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300">Concluir</button>
            </div>
          </div>
        ) : (
          <form onSubmit={submit} className="mt-6 grid gap-5">
            <p className="text-sm leading-6 text-slate-400">O convite cria o usuario e o vincula ao cliente. Depois, envie as credenciais geradas para a pessoa.</p>
            <label>
              <span className="mb-2 block text-sm font-medium text-slate-300">Nome</span>
              <input name="name" required autoComplete="name" className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300" />
            </label>
            <label>
              <span className="mb-2 block text-sm font-medium text-slate-300">Email</span>
              <input name="email" type="email" required autoComplete="email" className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300" />
            </label>
            <label>
              <span className="mb-2 block text-sm font-medium text-slate-300">Permissao</span>
              <select name="role" defaultValue="client_member" className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300">
                <option value="client_member">Colaborador - visualizar projetos</option>
                <option value="client_admin">Administrador do cliente</option>
              </select>
            </label>
            {error ? <p className="rounded-[8px] border border-orange-300/25 bg-orange-300/8 p-3 text-sm text-orange-100">{error}</p> : null}
            <div className="flex justify-end gap-3">
              <button type="button" onClick={onClose} className="rounded-[8px] border border-white/12 px-4 py-3 text-sm font-medium">Cancelar</button>
              <button disabled={submitting} className="rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950 disabled:opacity-60">{submitting ? "Criando..." : "Criar acesso"}</button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}
