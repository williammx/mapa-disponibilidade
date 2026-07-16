import { FormEvent, useEffect, useState } from "react";
import { apiRequest, isLocalDemoMode, useApi } from "../api";
import { SectionHeader } from "../components/SectionHeader";
import { updateProfile, useWorkspace } from "../workspace";

type MeResponse = { user: { name: string; email: string } };

export function ProfilePage() {
  const { profile } = useWorkspace();
  const response = useApi<MeResponse>("/api/auth/me");
  const [name, setName] = useState(profile.name);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (response.data?.user.name) setName(response.data.user.name);
  }, [response.data?.user.name]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    try {
      if (!isLocalDemoMode) {
        await apiRequest("/api/profile", { method: "PATCH", body: JSON.stringify({ name }) });
      }
      updateProfile({ name, email: response.data?.user.email ?? profile.email });
      setMessage("Perfil salvo.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Nao foi possivel salvar o perfil.");
    }
  }

  return (
    <div className="space-y-9">
      <SectionHeader eyebrow="conta" title="Perfil" description="Dados do usuario administrador e informacoes de acesso." />
      {message ? <p className="rounded-[8px] border border-emerald-300/25 bg-emerald-300/8 p-3 text-sm text-emerald-100">{message}</p> : null}
      <form onSubmit={handleSubmit} className="grid max-w-2xl gap-5">
        <Field name="name" label="Nome" value={name} onChange={setName} />
        <Field name="email" label="Email" value={response.data?.user.email ?? profile.email} type="email" disabled />
        <button className="w-fit rounded-[8px] bg-emerald-400 px-5 py-3 font-medium text-slate-950">Salvar perfil</button>
      </form>
    </div>
  );
}

function Field({ name, label, value, type = "text", disabled = false, onChange }: { name: string; label: string; value: string; type?: string; disabled?: boolean; onChange?: (value: string) => void }) {
  return (
    <label>
      <span className="mb-2 block text-sm font-medium text-slate-300">{label}</span>
      <input name={name} type={type} value={value} disabled={disabled} onChange={(event) => onChange?.(event.target.value)} className="w-full rounded-[8px] border border-white/12 bg-white/5 px-4 py-3 outline-none focus:border-emerald-300 disabled:cursor-not-allowed disabled:opacity-60" />
    </label>
  );
}
