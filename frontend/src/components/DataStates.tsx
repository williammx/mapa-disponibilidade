import { ArrowClockwise } from "@phosphor-icons/react";
import type { ReactNode } from "react";

export function LoadingBlock({ label, rows = 3 }: { label: string; rows?: number }) {
  return (
    <div role="status" aria-live="polite" className="rounded-[8px] border border-white/10 bg-white/4 p-6">
      <p className="text-sm text-slate-400">{label}</p>
      {/* O esqueleto e decorativo: quem usa leitor de tela ja recebeu o texto acima. */}
      <div className="mt-4 space-y-3" aria-hidden="true">
        {Array.from({ length: rows }, (_, index) => (
          <div
            key={index}
            className="h-4 animate-pulse rounded-[8px] bg-white/8"
            style={{ width: `${Math.max(38, 100 - index * 14)}%` }}
          />
        ))}
      </div>
    </div>
  );
}

export function EmptyBlock({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return (
    <div className="rounded-[8px] border border-dashed border-white/12 bg-white/3 p-6">
      <h3 className="text-lg font-medium text-slate-100">{title}</h3>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">{description}</p>
      {action ? <div className="mt-5 flex flex-wrap gap-3">{action}</div> : null}
    </div>
  );
}

export function ErrorBlock({
  message,
  onRetry,
  retryLabel = "Tentar de novo",
}: {
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <div role="alert" className="rounded-[8px] border border-orange-300/25 bg-orange-300/8 p-6">
      <p className="text-sm leading-6 text-orange-100">{message}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-4 inline-flex items-center gap-2 rounded-[8px] border border-orange-200/30 px-4 py-2 text-sm font-medium text-orange-50 transition hover:bg-orange-300/12 focus-visible:ring-2 focus-visible:ring-emerald-300"
        >
          <ArrowClockwise size={16} weight="bold" />
          {retryLabel}
        </button>
      ) : null}
    </div>
  );
}
