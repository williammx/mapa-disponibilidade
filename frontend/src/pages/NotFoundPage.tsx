import { ArrowLeft } from "@phosphor-icons/react";
import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <main className="grid min-h-[100dvh] place-items-center bg-[#081014] px-5 text-white">
      <div className="max-w-lg rounded-[8px] border border-white/10 bg-white/5 p-8">
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-300">rota nao encontrada</p>
        <h1 className="mt-3 text-3xl font-medium">Essa pagina nao existe no app.</h1>
        <p className="mt-3 text-slate-300">Volte para o painel ou para a pagina principal para continuar.</p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link to="/app" className="inline-flex items-center gap-2 rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950">
            <ArrowLeft size={17} weight="bold" />
            Ir para o painel
          </Link>
          <Link to="/" className="rounded-[8px] border border-white/12 px-4 py-3 text-sm font-medium">Pagina principal</Link>
        </div>
      </div>
    </main>
  );
}
