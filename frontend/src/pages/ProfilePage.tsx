import { FormEvent, useState } from "react";
import { SectionHeader } from "../components/SectionHeader";
import { updateProfile, useWorkspace } from "../workspace";

export function ProfilePage() {
  const { profile } = useWorkspace();
  const [message, setMessage] = useState<string | null>(null);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    updateProfile({
      name: String(form.get("name") ?? profile.name),
      email: String(form.get("email") ?? profile.email),
    });
    setMessage("Perfil salvo.");
  }

  return (
    <div className="space-y-9">
      <SectionHeader eyebrow="conta" title="Perfil" description="Dados do usuario administrador e informacoes de acesso." />
      {message ? <p className="rounded-[8px] border border-emerald-300/25 bg-emerald-300/8 p-3 text-sm text-emerald-100">{message}</p> : null}
      <form onSubmit={handleSubmit} className="grid max-w-2xl gap-5">
        <Field name="name" label="Nome" value={profile.name} />
        <Field name="email" label="Email" value={profile.email} type="email" />
        <button className="w-fit rounded-[8px] bg-emerald-400 px-5 py-3 font-medium text-slate-950">Salvar perfil</button>
      </form>
    </div>
  );
}

function Field({ name, label, value, type = "text" }: { name: string; label: string; value: string; type?: string }) {
  return (
    <label>
      <span className="mb-2 block text-sm font-medium text-slate-300">{label}</span>
      <input name={name} type={type} defaultValue={value} className="w-full rounded-[8px] border border-white/12 bg-white/5 px-4 py-3 outline-none focus:border-emerald-300" />
    </label>
  );
}
