import { Buildings, ClockCounterClockwise, GearSix, ShieldCheck, SquaresFour, UserCircle } from "@phosphor-icons/react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { BrandLogo } from "./BrandLogo";

const nav = [
  { to: "/app", label: "Projetos", icon: SquaresFour, end: true },
  { to: "/app/clientes", label: "Clientes", icon: Buildings },
  { to: "/app/atividade", label: "Atividade", icon: ClockCounterClockwise },
  { to: "/app/perfil", label: "Perfil", icon: UserCircle },
  { to: "/app/preferencias", label: "Preferencias", icon: GearSix },
  { to: "/app/admin", label: "Admin", icon: ShieldCheck },
];

export function AppShell() {
  return (
    <div className="min-h-[100dvh] bg-[#081014] text-slate-100">
      <header className="sticky top-0 z-20 border-b border-white/8 bg-[#081014]/92 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-[1500px] items-center justify-between px-5">
          <Link to="/" className="flex items-center gap-3">
            <BrandLogo inverse />
          </Link>
          <div className="flex items-center gap-3 text-sm">
            <span className="hidden text-slate-300 sm:inline">William Gabriel</span>
            <Link className="rounded-[8px] border border-white/10 px-3 py-2 text-slate-100 transition hover:bg-white/8" to="/entrar">
              Sair
            </Link>
          </div>
        </div>
      </header>
      <div className="border-b border-white/8 p-3 lg:hidden">
        <nav className="flex gap-2 overflow-x-auto">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `inline-flex shrink-0 items-center gap-2 rounded-[8px] px-3 py-2 text-sm font-medium transition ${
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
            {nav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `group flex items-center gap-3 rounded-[8px] px-3 py-3 text-sm font-medium transition ${
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
          <Outlet />
        </main>
      </div>
    </div>
  );
}
