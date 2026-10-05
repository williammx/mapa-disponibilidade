import { Buildings, PlugsConnected, ClockCounterClockwise, GearSix, ShieldCheck, SquaresFour, UserCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate, useOutletContext } from "react-router-dom";
import { apiRequest, isLocalDemoMode } from "../api";
import { BrandLogo } from "./BrandLogo";
import { SectionHeader } from "./SectionHeader";

export const PLATFORM_ADMIN_ROLE = "platform_admin";

// Espelha exatamente quem o backend deixa entrar na area tecnica: o endpoint
// que a AdminPage consome (`admin_health`, app_v1/api.py:299) aceita os dois
// papeis. Liberar so `platform_admin` aqui esconderia o menu de um operador que
// a API atende normalmente.
export const INTERNAL_ROLES = [PLATFORM_ADMIN_ROLE, "operator"];

export function isInternalRole(role: string): boolean {
  return INTERNAL_ROLES.includes(role);
}

export type SessionUser = { name: string; platformRole: string };
export type SessionContext = { user: SessionUser };

type NavItem = { to: string; label: string; icon: typeof SquaresFour; end?: boolean; adminOnly?: boolean; platformAdminOnly?: boolean };

const nav: NavItem[] = [
  { to: "/app", label: "Projetos", icon: SquaresFour, end: true },
  { to: "/app/clientes", label: "Clientes", icon: Buildings },
  { to: "/app/atividade", label: "Atividade", icon: ClockCounterClockwise },
  { to: "/app/perfil", label: "Perfil", icon: UserCircle },
  { to: "/app/preferencias", label: "Preferencias", icon: GearSix },
  { to: "/app/integracoes", label: "Integracoes", icon: PlugsConnected, platformAdminOnly: true },
  { to: "/app/admin", label: "Admin", icon: ShieldCheck, adminOnly: true },
];

// Sem backend o painel de demonstracao nao tem sessao real; o papel de administrador
// mantem a area tecnica navegavel durante o desenvolvimento local.
const demoUser: SessionUser = { name: "William Gabriel", platformRole: PLATFORM_ADMIN_ROLE };

export function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const [user, setUser] = useState<SessionUser | null>(isLocalDemoMode ? demoUser : null);
  const [checkingSession, setCheckingSession] = useState(!isLocalDemoMode);

  useEffect(() => {
    if (isLocalDemoMode) return;
    let cancelled = false;
    apiRequest<{ user: { name: string; platform_role: string } }>("/api/auth/me")
      .then((payload) => {
        if (cancelled) return;
        setUser({ name: payload.user.name, platformRole: payload.user.platform_role });
        setCheckingSession(false);
      })
      .catch(() => {
        if (!cancelled) navigate(`/entrar?next=${encodeURIComponent(location.pathname + location.search)}`, { replace: true });
      });
    return () => {
      cancelled = true;
    };
  }, [location.pathname, location.search, navigate]);

  async function logout() {
    try {
      if (!isLocalDemoMode) await apiRequest("/api/auth/logout", { method: "POST" });
    } finally {
      navigate("/entrar", { replace: true });
    }
  }

  if (checkingSession || !user) {
    return (
      <div role="status" className="grid min-h-[100dvh] place-items-center bg-[#081014] text-sm text-slate-300">
        Carregando painel...
      </div>
    );
  }

  const visibleNav = nav.filter((item) => (!item.adminOnly || isInternalRole(user.platformRole)) && (!item.platformAdminOnly || user.platformRole === PLATFORM_ADMIN_ROLE));

  return (
    <div className="min-h-[100dvh] bg-[#081014] text-slate-100">
      <header className="sticky top-0 z-20 border-b border-white/8 bg-[#081014]/92 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-[1500px] items-center justify-between px-5">
          <Link to="/" className="flex items-center gap-3">
            <BrandLogo inverse />
          </Link>
          <div className="flex items-center gap-3 text-sm">
            <span className="hidden text-slate-300 sm:inline">{user.name}</span>
            <button
              className="rounded-[8px] border border-white/10 px-3 py-2 text-slate-100 transition hover:bg-white/8 focus-visible:ring-2 focus-visible:ring-emerald-300"
              onClick={logout}
            >
              Sair
            </button>
          </div>
        </div>
      </header>
      <div className="border-b border-white/8 p-3 lg:hidden">
        <nav className="flex gap-2 overflow-x-auto">
          {visibleNav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `inline-flex shrink-0 items-center gap-2 rounded-[8px] px-3 py-2 text-sm font-medium transition focus-visible:ring-2 focus-visible:ring-emerald-300 ${
                  isActive ? "bg-emerald-400/10 text-emerald-300" : "text-slate-300 hover:bg-white/6 hover:text-white"
                }`
              }
            >
              <item.icon size={17} weight="bold" />
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>
      <div className="mx-auto grid max-w-[1500px] grid-cols-1 lg:grid-cols-[248px_minmax(0,1fr)]">
        <aside className="hidden min-h-[calc(100dvh-64px)] border-r border-white/8 p-4 lg:block">
          <nav className="space-y-1">
            {visibleNav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `group flex items-center gap-3 rounded-[8px] px-3 py-3 text-sm font-medium transition focus-visible:ring-2 focus-visible:ring-emerald-300 ${
                    isActive ? "bg-emerald-400/10 text-emerald-300" : "text-slate-300 hover:bg-white/6 hover:text-white"
                  }`
                }
              >
                <item.icon size={18} weight="bold" />
                {item.label}
              </NavLink>
            ))}
          </nav>
        </aside>
        <main className="min-w-0 px-5 py-8 md:px-8 lg:px-12">
          <Outlet context={{ user }} />
        </main>
      </div>
    </div>
  );
}

export function useSession() {
  return useOutletContext<SessionContext>();
}

export function RequirePlatformAdmin({ children, strict = false }: { children: ReactNode; strict?: boolean }) {
  const { user } = useSession();

  if (strict ? user.platformRole !== PLATFORM_ADMIN_ROLE : !isInternalRole(user.platformRole)) {
    return (
      <div className="space-y-8">
        <SectionHeader
          eyebrow="acesso restrito"
          title="Acesso negado"
          description="Esta area e exclusiva de administradores da plataforma."
        />
        <div role="status" className="max-w-2xl rounded-[8px] border border-orange-300/25 bg-orange-300/8 p-6">
          <p className="text-sm leading-6 text-orange-100">
            Seu usuario nao tem o papel de administrador da plataforma. Peca a liberacao a quem administra o NexoLote se
            precisar acompanhar banco, fila e storage.
          </p>
          <Link
            to="/app"
            className="mt-5 inline-flex rounded-[8px] bg-emerald-400 px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-300"
          >
            Voltar aos projetos
          </Link>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
