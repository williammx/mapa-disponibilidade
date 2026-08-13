import { ArrowRight } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { BrandLogo } from "../BrandLogo";
import { useScrolledPast } from "./motion";
import { DEMO_MAP_URL, focusRing } from "./primitives";

const LINKS = [
  { href: "#como-funciona", label: "Como funciona" },
  { href: "#precisao", label: "Precisão" },
  { href: "#acesso", label: "Acesso ao link" },
  { href: "#perguntas", label: "Perguntas" },
];

export function LandingNav() {
  const solid = useScrolledPast(40);

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-[background-color,border-color,backdrop-filter] duration-300 ${
        solid
          ? "border-b border-white/10 bg-[#060C10]/85 backdrop-blur-xl"
          : "border-b border-transparent bg-transparent"
      }`}
    >
      <div className="mx-auto flex max-w-[1400px] items-center justify-between gap-6 px-4 py-4 md:px-8">
        <Link to="/" className={`flex items-center rounded-lg ${focusRing}`}>
          <BrandLogo inverse />
        </Link>

        <nav aria-label="Seções do site" className="hidden items-center gap-8 lg:flex">
          {LINKS.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className={`rounded-md text-sm text-[#94A6AE] transition hover:text-[#E8F1EC] ${focusRing}`}
            >
              {link.label}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <Link
            to="/entrar"
            className={`hidden rounded-full px-4 py-2.5 text-sm font-medium text-[#E8F1EC] transition hover:bg-white/[0.06] sm:inline-flex ${focusRing}`}
          >
            Entrar
          </Link>
          <a
            href={DEMO_MAP_URL}
            className={`inline-flex items-center gap-2 whitespace-nowrap rounded-full bg-[#26D07C] px-4 py-2.5 text-sm font-semibold text-[#03150C] transition hover:bg-[#4BE097] sm:px-5 ${focusRing}`}
          >
            Ver demonstração
            <ArrowRight size={16} weight="bold" aria-hidden="true" className="hidden sm:block" />
          </a>
        </div>
      </div>
    </header>
  );
}
