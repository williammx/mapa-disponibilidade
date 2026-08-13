import { FormEvent, useEffect, useState } from "react";
import { apiRequest, isLocalDemoMode, useApi } from "../api";
import { SectionHeader } from "../components/SectionHeader";
import { updateProfile, useWorkspace } from "../workspace";

type MeResponse = { user: { name: string; email: string } };
type Feedback = { kind: "success" | "error"; text: string };

// Espelha PasswordPayload em api.py: new_password = Field(min_length=12, max_length=128).
const MIN_PASSWORD_LENGTH = 12;
const MAX_PASSWORD_LENGTH = 128;

export function ProfilePage() {
  const { profile } = useWorkspace();
  const response = useApi<MeResponse>("/api/auth/me");
  const [name, setName] = useState(profile.name);
  const [profileFeedback, setProfileFeedback] = useState<Feedback | null>(null);
  const [savingProfile, setSavingProfile] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordFeedback, setPasswordFeedback] = useState<Feedback | null>(null);
  const [changingPassword, setChangingPassword] = useState(false);

  useEffect(() => {
    if (response.data?.user.name) setName(response.data.user.name);
  }, [response.data?.user.name]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProfileFeedback(null);
    setSavingProfile(true);
    try {
      if (!isLocalDemoMode) {
        await apiRequest("/api/profile", { method: "PATCH", body: JSON.stringify({ name }) });
      }
      updateProfile({ name, email: response.data?.user.email ?? profile.email });
      setProfileFeedback({ kind: "success", text: "Perfil salvo." });
    } catch (error) {
      setProfileFeedback({ kind: "error", text: error instanceof Error ? error.message : "Nao foi possivel salvar o perfil." });
    } finally {
      setSavingProfile(false);
    }
  }

  async function handlePasswordSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const problem = passwordProblem(currentPassword, newPassword, confirmPassword);
    if (problem) {
      setPasswordFeedback({ kind: "error", text: problem });
      return;
    }
    if (isLocalDemoMode) {
      setPasswordFeedback({ kind: "error", text: "Modo demo local: conecte o backend para trocar a senha." });
      return;
    }
    setPasswordFeedback(null);
    setChangingPassword(true);
    try {
      await apiRequest("/api/auth/password", {
        method: "POST",
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setPasswordFeedback({ kind: "success", text: "Senha atualizada. Use a nova senha no proximo acesso." });
    } catch (error) {
      setPasswordFeedback({ kind: "error", text: error instanceof Error ? error.message : "Nao foi possivel trocar a senha." });
    } finally {
      setChangingPassword(false);
    }
  }

  return (
    <div className="space-y-9">
      <SectionHeader eyebrow="conta" title="Perfil" description="Dados do usuario administrador e informacoes de acesso." />

      <form onSubmit={handleSubmit} className="grid max-w-2xl gap-5">
        <Field name="name" label="Nome" value={name} onChange={setName} autoComplete="name" />
        <Field name="email" label="Email" value={response.data?.user.email ?? profile.email} type="email" disabled />
        {profileFeedback ? <FeedbackMessage feedback={profileFeedback} /> : null}
        <button
          disabled={savingProfile}
          className="w-fit rounded-[8px] bg-emerald-400 px-5 py-3 font-medium text-slate-950 transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300 disabled:cursor-wait disabled:opacity-70"
        >
          {savingProfile ? "Salvando..." : "Salvar perfil"}
        </button>
      </form>

      <section className="max-w-2xl rounded-[8px] border border-white/10 bg-white/4 p-6">
        <h2 className="text-xl font-medium text-white">Alterar senha</h2>
        <p className="mt-2 text-sm leading-6 text-slate-400">
          Confirme a senha atual e escolha uma nova com pelo menos {MIN_PASSWORD_LENGTH} caracteres. As sessoes abertas
          continuam validas.
        </p>
        <form onSubmit={handlePasswordSubmit} className="mt-6 grid gap-5">
          <Field
            name="current_password"
            label="Senha atual"
            type="password"
            value={currentPassword}
            onChange={setCurrentPassword}
            autoComplete="current-password"
            disabled={changingPassword}
          />
          <Field
            name="new_password"
            label={`Nova senha (minimo ${MIN_PASSWORD_LENGTH} caracteres)`}
            type="password"
            value={newPassword}
            onChange={setNewPassword}
            autoComplete="new-password"
            disabled={changingPassword}
          />
          <Field
            name="confirm_password"
            label="Confirmar nova senha"
            type="password"
            value={confirmPassword}
            onChange={setConfirmPassword}
            autoComplete="new-password"
            disabled={changingPassword}
          />
          {passwordFeedback ? <FeedbackMessage feedback={passwordFeedback} /> : null}
          <button
            disabled={changingPassword}
            className="w-fit rounded-[8px] bg-emerald-400 px-5 py-3 font-medium text-slate-950 transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300 disabled:cursor-wait disabled:opacity-70"
          >
            {changingPassword ? "Atualizando senha..." : "Atualizar senha"}
          </button>
        </form>
      </section>
    </div>
  );
}

function passwordProblem(current: string, next: string, confirmation: string) {
  if (!current) return "Informe a senha atual.";
  if (next.length < MIN_PASSWORD_LENGTH) return `A nova senha precisa de pelo menos ${MIN_PASSWORD_LENGTH} caracteres.`;
  if (next.length > MAX_PASSWORD_LENGTH) return `A nova senha pode ter no maximo ${MAX_PASSWORD_LENGTH} caracteres.`;
  if (next === current) return "A nova senha precisa ser diferente da senha atual.";
  if (next !== confirmation) return "A confirmacao nao confere com a nova senha.";
  return null;
}

function FeedbackMessage({ feedback }: { feedback: Feedback }) {
  const tone =
    feedback.kind === "success"
      ? "border-emerald-300/25 bg-emerald-300/8 text-emerald-100"
      : "border-orange-300/25 bg-orange-300/8 text-orange-100";
  return (
    <p role="status" className={`rounded-[8px] border p-3 text-sm ${tone}`}>
      {feedback.text}
    </p>
  );
}

function Field({
  name,
  label,
  value,
  type = "text",
  disabled = false,
  autoComplete,
  onChange,
}: {
  name: string;
  label: string;
  value: string;
  type?: string;
  disabled?: boolean;
  autoComplete?: string;
  onChange?: (value: string) => void;
}) {
  return (
    <label>
      <span className="mb-2 block text-sm font-medium text-slate-300">{label}</span>
      <input
        name={name}
        type={type}
        value={value}
        disabled={disabled}
        autoComplete={autoComplete}
        onChange={(event) => onChange?.(event.target.value)}
        className="w-full rounded-[8px] border border-white/12 bg-white/5 px-4 py-3 outline-none focus:border-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300 disabled:cursor-not-allowed disabled:opacity-60"
      />
    </label>
  );
}
