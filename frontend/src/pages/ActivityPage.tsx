import { ClockCounterClockwise } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { isLocalDemoMode, useApi } from "../api";
import { auditActionLabel } from "../audit";
import type { AuditEvent } from "../audit";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../components/DataStates";
import { SectionHeader } from "../components/SectionHeader";
import { formatDateTime } from "../format";
import { useWorkspace } from "../workspace";

type AuditResponse = { audit_events: AuditEvent[] };

export function ActivityPage() {
  const workspace = useWorkspace();
  const response = useApi<AuditResponse>("/api/v1/audit-events");
  const demoFallback = isLocalDemoMode && Boolean(response.error?.startsWith("Modo demo local"));
  const events = response.data?.audit_events ?? [];

  return (
    <div className="space-y-9">
      <SectionHeader eyebrow="auditoria" title="Atividade recente" description="Eventos importantes de processamento, edicao, publicacao, acesso e alteracao de permissao." />

      {demoFallback ? (
        <div className="divide-y divide-white/8 border-y border-white/8">
          {workspace.activity.map((item, index) => (
            <div key={`${item}-${index}`} className="grid gap-4 py-5 md:grid-cols-[44px_1fr] md:items-center">
              <span className="grid size-10 place-items-center rounded-[8px] bg-white/7 text-emerald-300">
                <ClockCounterClockwise size={18} weight="bold" />
              </span>
              <p className="font-medium text-slate-200">{item}</p>
            </div>
          ))}
        </div>
      ) : response.loading ? (
        <LoadingBlock label="Carregando eventos de auditoria..." rows={4} />
      ) : response.error ? (
        <ErrorBlock message={response.error} onRetry={response.reload} />
      ) : events.length === 0 ? (
        <EmptyBlock
          title="Nenhum evento registrado ainda"
          description="A auditoria comeca a registrar assim que alguem cria um cliente, envia um PDF, publica uma versao ou compartilha um link."
          action={
            <Link
              to="/app"
              className="inline-flex rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300"
            >
              Ir para projetos
            </Link>
          }
        />
      ) : (
        <div className="divide-y divide-white/8 border-y border-white/8">
          {events.map((event) => (
            <div key={event.id} className="grid gap-4 py-5 md:grid-cols-[44px_1fr_180px] md:items-center">
              <span className="grid size-10 place-items-center rounded-[8px] bg-white/7 text-emerald-300">
                <ClockCounterClockwise size={18} weight="bold" />
              </span>
              <p className="font-medium text-slate-200">
                <span className="text-slate-100">{event.actor_name ?? "Sistema"}</span> {auditActionLabel(event.action)}
              </p>
              {/* Horario vem do proprio evento; antes a tela estampava "Nh atras" calculado pela posicao na lista. */}
              <span className="text-sm text-slate-500">{formatDateTime(event.created_at)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
