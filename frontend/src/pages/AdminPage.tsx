import { Database, HardDrives, Pulse, Queue } from "@phosphor-icons/react";
import { useApi } from "../api";
import { ErrorBlock, LoadingBlock } from "../components/DataStates";
import { SectionHeader } from "../components/SectionHeader";

type HealthResponse = {
  status: string;
  database: string;
  redis_configured: boolean;
  storage_root: string;
};

export function AdminPage() {
  const health = useApi<HealthResponse>("/api/v1/admin/health");

  return (
    <div className="space-y-9">
      <SectionHeader eyebrow="administracao" title="Saude da plataforma" description="Visao tecnica para acompanhar banco, fila, storage e capacidade da VPS." />

      {health.loading ? (
        <LoadingBlock label="Consultando a saude da plataforma..." rows={2} />
      ) : health.error ? (
        <ErrorBlock message={health.error} onRetry={health.reload} />
      ) : health.data ? (
        // Sem dado real nao ha card: antes a tela chutava "indisponivel" e "/data"
        // como se fossem a resposta do servidor.
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <StatusCard icon={Pulse} label="API" value={health.data.status} />
          <StatusCard icon={Database} label="Banco" value={health.data.database} />
          <StatusCard icon={Queue} label="Redis/RQ" value={health.data.redis_configured ? "configurado" : "pendente"} />
          <StatusCard icon={HardDrives} label="Storage" value={health.data.storage_root} />
        </div>
      ) : null}

      <section className="rounded-[8px] border border-white/10 p-6">
        <h2 className="text-xl font-medium">Operacao recomendada</h2>
        <div className="mt-5 divide-y divide-white/8">
          {["Rodar migrations antes da API subir", "Executar worker RQ separado do web", "Agendar backup diario do PostgreSQL e arquivos", "Testar restore antes da primeira entrega comercial"].map((item) => (
            <div key={item} className="py-4 text-slate-300">{item}</div>
          ))}
        </div>
      </section>
    </div>
  );
}

function StatusCard({ icon: Icon, label, value }: { icon: typeof Pulse; label: string; value: string }) {
  return (
    <article className="rounded-[8px] border border-white/10 p-5">
      <Icon className="text-emerald-300" size={24} weight="bold" />
      <p className="mt-8 text-sm text-slate-400">{label}</p>
      <p className="mt-2 break-all text-xl font-medium">{value}</p>
    </article>
  );
}
