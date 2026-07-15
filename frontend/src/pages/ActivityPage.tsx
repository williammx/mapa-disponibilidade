import { ClockCounterClockwise } from "@phosphor-icons/react";
import { useApi } from "../api";
import { SectionHeader } from "../components/SectionHeader";
import { useWorkspace } from "../workspace";

type AuditResponse = {
  audit_events: Array<{ id: string; action: string; target_type: string; actor_name: string | null; created_at: string }>;
};

export function ActivityPage() {
  const workspace = useWorkspace();
  const response = useApi<AuditResponse>("/api/v1/audit-events");
  const rows = response.data?.audit_events.map((event) => `${event.actor_name ?? "Sistema"} executou ${event.action} em ${event.target_type}.`) ?? workspace.activity;

  return (
    <div className="space-y-9">
      <SectionHeader eyebrow="auditoria" title="Atividade recente" description="Eventos importantes de processamento, edicao, publicacao, acesso e alteracao de permissao." />
      {response.error ? <p className="rounded-[8px] border border-orange-300/25 bg-orange-300/8 p-3 text-sm text-orange-100">{response.error}</p> : null}
      <div className="divide-y divide-white/8 border-y border-white/8">
        {rows.map((item, index) => (
          <div key={`${item}-${index}`} className="grid gap-4 py-5 md:grid-cols-[44px_1fr_140px] md:items-center">
            <span className="grid size-10 place-items-center rounded-[8px] bg-white/7 text-emerald-300">
              <ClockCounterClockwise size={18} weight="bold" />
            </span>
            <p className="font-medium text-slate-200">{item}</p>
            <span className="text-sm text-slate-500">{index === 0 ? "Agora" : `${index + 1}h atras`}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
