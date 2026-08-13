import { ArrowRight, LockKey } from "@phosphor-icons/react";
import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { apiRequest, isLocalDemoMode } from "../api";
import { BrandLogo } from "../components/BrandLogo";

export function LoginPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const nextPath = safeNextPath(searchParams.get("next"));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [checkingSession, setCheckingSession] = useState(!isLocalDemoMode);

  useEffect(() => {
    if (isLocalDemoMode) return;
    let cancelled = false;
    apiRequest("/api/auth/me")
      .then(() => {
        if (!cancelled) navigate(nextPath, { replace: true });
      })
      .catch(() => {
        if (!cancelled) setCheckingSession(false);
      });
    return () => {
      cancelled = true;
    };
  }, [navigate, nextPath]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!email.trim() || !password.trim()) {
      setError("Informe email e senha para entrar.");
      return;
    }
    setLoading(true);
    try {
      if (import.meta.env.DEV && import.meta.env.VITE_USE_BACKEND !== "true") {
        navigate(nextPath);
        return;
      }
      await apiRequest("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      navigate(nextPath);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nao foi possivel entrar.");
    } finally {
      setLoading(false);
    }
  }

  if (checkingSession) {
    return (
      <main className="grid min-h-[100dvh] place-items-center bg-[#081014] text-white" role="status">
        <p className="text-sm text-slate-300">Verificando sua sessao...</p>
      </main>
    );
  }

  return (
    <main className="grid min-h-[100dvh] bg-[#081014] text-white lg:grid-cols-[1fr_520px]">
      <section className="relative hidden overflow-hidden lg:block">
        <img
          src="/hero-noturno-1600.webp"
          srcSet="/hero-noturno-1000.webp 1000w, /hero-noturno-1600.webp 1600w"
          sizes="(max-width: 1024px) 100vw, 50vw"
          alt="Loteamento visto do alto ao anoitecer"
          loading="lazy"
          decoding="async"
          className="absolute inset-0 h-full w-full object-cover"
        />
        <div className="absolute inset-0 bg-[#07100e]/62" />
        <div className="relative z-10 flex h-full flex-col justify-end p-12">
          <p className="max-w-lg text-4xl font-medium leading-tight tracking-tight">Operacao de mapas, clientes e entregas em um unico painel.</p>
        </div>
      </section>
      <section className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <Link to="/" className="mb-10 inline-flex items-center gap-3">
            <BrandLogo inverse />
          </Link>
          <div className="mb-8">
            <LockKey className="mb-5 text-emerald-300" size={30} weight="bold" />
            <h1 className="text-4xl font-medium tracking-tight">Entrar</h1>
            <p className="mt-3 text-slate-300">Acesse projetos, publicacoes e links de clientes.</p>
          </div>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <label className="block">
              <span className="mb-2 block text-sm font-medium text-slate-200">Email</span>
              <input
                name="email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                className="w-full rounded-[8px] border border-white/12 bg-white/5 px-4 py-3 outline-none transition focus:border-emerald-300"
              />
            </label>
            <label className="block">
              <span className="mb-2 block text-sm font-medium text-slate-200">Senha</span>
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="w-full rounded-[8px] border border-white/12 bg-white/5 px-4 py-3 outline-none transition focus:border-emerald-300"
              />
            </label>
            {error ? <p className="rounded-[8px] border border-orange-300/25 bg-orange-300/8 p-3 text-sm text-orange-100">{error}</p> : null}
            <button disabled={loading} className="inline-flex w-full items-center justify-center gap-2 rounded-[8px] bg-emerald-400 px-5 py-3 font-medium text-slate-950 transition hover:bg-emerald-300 active:translate-y-px disabled:cursor-wait disabled:opacity-70">
              {loading ? "Entrando..." : "Acessar painel"}
              <ArrowRight size={18} weight="bold" />
            </button>
          </form>
        </div>
      </section>
    </main>
  );
}

function safeNextPath(value: string | null) {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/app";
}
