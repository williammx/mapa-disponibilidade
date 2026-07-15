import { FormEvent, useState } from "react";
import { SectionHeader } from "../components/SectionHeader";
import { updatePreferences, useWorkspace } from "../workspace";
import type { Visibility } from "../workspace";

export function PreferencesPage() {
  const { preferences } = useWorkspace();
  const [message, setMessage] = useState<string | null>(null);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    updatePreferences({
      quality: String(form.get("quality")) as "light" | "balanced" | "high",
      opacity: Number(form.get("opacity")),
      labels: String(form.get("labels")) as "auto" | "always" | "hidden",
      defaultVisibility: String(form.get("defaultVisibility")) as Visibility,
    });
    setMessage("Preferencias salvas.");
  }

  return (
    <div className="space-y-9">
      <SectionHeader eyebrow="preferencias" title="Padroes da plataforma" description="Configuracoes que afetam novos projetos, mapas e entregas." />
      {message ? <p className="rounded-[8px] border border-emerald-300/25 bg-emerald-300/8 p-3 text-sm text-emerald-100">{message}</p> : null}
      <form onSubmit={handleSubmit} className="grid max-w-3xl gap-5 rounded-[8px] border border-white/10 bg-white/4 p-6">
        <label>
          <span className="mb-2 block text-sm font-medium text-slate-300">Qualidade padrao do fundo</span>
          <select name="quality" defaultValue={preferences.quality} className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300">
            <option value="light">Leve</option>
            <option value="balanced">Equilibrada</option>
            <option value="high">Alta qualidade</option>
          </select>
        </label>
        <label>
          <span className="mb-2 block text-sm font-medium text-slate-300">Opacidade dos lotes: {preferences.opacity}%</span>
          <input name="opacity" type="range" min="20" max="100" defaultValue={preferences.opacity} className="w-full accent-emerald-400" />
        </label>
        <label>
          <span className="mb-2 block text-sm font-medium text-slate-300">Numeracao</span>
          <select name="labels" defaultValue={preferences.labels} className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300">
            <option value="auto">Auto no zoom</option>
            <option value="always">Sempre visivel</option>
            <option value="hidden">Oculta</option>
          </select>
        </label>
        <label>
          <span className="mb-2 block text-sm font-medium text-slate-300">Acesso padrao do cliente</span>
          <select name="defaultVisibility" defaultValue={preferences.defaultVisibility} className="w-full rounded-[8px] border border-white/12 bg-[#091217] px-4 py-3 outline-none focus:border-emerald-300">
            <option value="private">Privado por login</option>
            <option value="password">Link com senha</option>
            <option value="unlisted">Link sem senha</option>
            <option value="public">Publico</option>
          </select>
        </label>
        <button className="w-fit rounded-[8px] bg-emerald-400 px-5 py-3 font-medium text-slate-950">Salvar preferencias</button>
      </form>
    </div>
  );
}
