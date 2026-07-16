import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { failed: boolean };

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Falha ao renderizar a aplicacao", error, info.componentStack);
  }

  render() {
    if (this.state.failed) {
      return (
        <main className="grid min-h-[100dvh] place-items-center bg-[#081014] px-5 text-white">
          <section className="w-full max-w-lg rounded-[8px] border border-white/12 bg-white/5 p-7">
            <h1 className="text-2xl font-medium">Nao foi possivel abrir esta tela</h1>
            <p className="mt-3 text-slate-300">Atualize a pagina. Se o problema continuar, volte ao painel e abra o projeto novamente.</p>
            <div className="mt-6 flex flex-wrap gap-3">
              <button onClick={() => window.location.reload()} className="rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950">Atualizar pagina</button>
              <a href="/app" className="rounded-[8px] border border-white/12 px-4 py-3 text-sm font-medium">Voltar ao painel</a>
            </div>
          </section>
        </main>
      );
    }
    return this.props.children;
  }
}
