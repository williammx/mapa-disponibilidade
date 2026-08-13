import { Link } from "react-router-dom";
import { BrandLogo } from "../BrandLogo";
import { CONTACT_EMAIL, CONTACT_MAILTO, DEMO_MAP_URL, focusRing } from "./primitives";

const SECTION_LINKS = [
  { href: "#como-funciona", label: "Como funciona" },
  { href: "#antes-depois", label: "Antes e depois" },
  { href: "#precisao", label: "Precisão do mapeamento" },
  { href: "#acesso", label: "Acesso ao link" },
  { href: "#perguntas", label: "Perguntas" },
];

const linkClass = `rounded-md text-[15px] text-[#94A6AE] transition hover:text-[#E8F1EC] ${focusRing}`;

export function SiteFooter() {
  return (
    <footer className="border-t border-white/10 bg-[#060C10] px-4 py-16 md:px-8">
      <div className="mx-auto max-w-[1400px]">
        <div className="grid gap-12 md:grid-cols-2 lg:grid-cols-[1.4fr_1fr_1fr_1.2fr]">
          <div>
            <BrandLogo inverse />
            <p className="mt-5 max-w-[34ch] leading-7 text-[#94A6AE]">
              A planta em PDF do loteamento vira um mapa de disponibilidade que a sua equipe atualiza
              e o cliente abre por um link.
            </p>
          </div>

          <nav aria-label="Seções desta página">
            <h2 className="text-[11px] uppercase tracking-[0.3em] text-[#6E8089]">Navegação</h2>
            <ul className="mt-5 space-y-3">
              {SECTION_LINKS.map((link) => (
                <li key={link.href}>
                  <a href={link.href} className={linkClass}>
                    {link.label}
                  </a>
                </li>
              ))}
            </ul>
          </nav>

          <nav aria-label="Acesso ao produto">
            <h2 className="text-[11px] uppercase tracking-[0.3em] text-[#6E8089]">Produto</h2>
            <ul className="mt-5 space-y-3">
              <li>
                <a href={DEMO_MAP_URL} className={linkClass}>
                  Mapa de demonstração
                </a>
              </li>
              <li>
                <Link to="/entrar" className={linkClass}>
                  Entrar na plataforma
                </Link>
              </li>
              <li>
                <Link to="/cliente" className={linkClass}>
                  Área do cliente
                </Link>
              </li>
            </ul>
          </nav>

          <div>
            <h2 className="text-[11px] uppercase tracking-[0.3em] text-[#6E8089]">Contato</h2>
            <p className="mt-5 leading-7 text-[#94A6AE]">
              Mande o PDF da planta e a gente responde com o mapa do seu empreendimento.
            </p>
            <a href={CONTACT_MAILTO} className={`mt-4 inline-block break-all font-medium text-[#26D07C] ${focusRing}`}>
              {CONTACT_EMAIL}
            </a>
          </div>
        </div>

        <div className="mt-14 flex flex-col gap-3 border-t border-white/10 pt-8 text-sm text-[#6E8089] md:flex-row md:items-center md:justify-between">
          <p>NexoLote · Mapas interativos para loteamentos</p>
          <p className="max-w-[62ch]">
            Produto em evolução: novas funções entram conforme os loteamentos reais pedem. A foto
            aérea usada nesta página é ilustrativa, gerada por IA.
          </p>
        </div>
      </div>
    </footer>
  );
}
