import { ArrowRight, Check, LinkSimple, X } from "@phosphor-icons/react";
import { PlantSchematic } from "./PlantSchematic";
import { DEMO_MAP_URL, Reveal, SectionLabel, StatusDot, primaryCta } from "./primitives";

const SEES = [
  "O mapa do loteamento com cada lote na cor do seu status",
  "O nome do lote escrito em cima do próprio lote",
  "O desenho original da planta por baixo e o zoom para chegar perto",
];

const DOES_NOT_SEE = [
  "As suas ferramentas de edição do mapa",
  "Os seus outros empreendimentos e clientes",
  "Qualquer parte da sua operação interna",
];

export function ClientViewSection() {
  return (
    <section className="px-4 py-24 md:px-8 md:py-28">
      <div className="mx-auto grid max-w-[1400px] gap-12 lg:grid-cols-[1.05fr_0.95fr] lg:items-center">
        <Reveal>
          <figure className="overflow-hidden rounded-2xl border border-white/10 bg-[#0A1116]">
            <div className="flex items-center gap-3 border-b border-white/10 px-4 py-3">
              <span aria-hidden="true" className="flex gap-1.5">
                <span className="size-2.5 rounded-full bg-white/15" />
                <span className="size-2.5 rounded-full bg-white/15" />
                <span className="size-2.5 rounded-full bg-white/15" />
              </span>
              <span className="flex min-w-0 items-center gap-2 rounded-full border border-white/10 bg-[#060C10] px-3 py-1.5 font-mono text-xs text-[#94A6AE]">
                <LinkSimple size={13} weight="bold" aria-hidden="true" />
                <span className="truncate">/mapas/setor-e-demo</span>
              </span>
            </div>
            <div className="relative aspect-[16/10] p-5 sm:p-8">
              <PlantSchematic mode="map" />
              <span className="absolute left-[14%] top-[22%] flex items-center gap-2 whitespace-nowrap rounded-full border border-white/15 bg-[#060C10]/80 px-3.5 py-2 text-[12px] shadow-[0_12px_34px_-14px_rgba(0,0,0,0.95)] backdrop-blur-md">
                <StatusDot status="disponivel" />
                <span className="font-mono text-[#E8F1EC]">Q195-L003</span>
                <span className="text-[#94A6AE]">· 178 m² ·</span>
                <span className="text-[#26D07C]">disponível</span>
              </span>
            </div>
            <figcaption className="flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-white/10 px-5 py-4 text-sm text-[#94A6AE]">
              <span className="flex items-center gap-2">
                <StatusDot status="disponivel" /> disponível
              </span>
              <span className="flex items-center gap-2">
                <StatusDot status="reservado" /> reservado
              </span>
              <span className="flex items-center gap-2">
                <StatusDot status="vendido" /> vendido
              </span>
            </figcaption>
          </figure>
        </Reveal>

        <Reveal delay={140}>
          <SectionLabel>o que o cliente final vê</SectionLabel>
          <h2 className="mt-5 max-w-[18ch] text-4xl font-medium leading-[1.12] tracking-tight text-[#E8F1EC] md:text-[46px]">
            Do outro lado do link, só o mapa.
          </h2>

          <p className="mt-9 text-[11px] uppercase tracking-[0.3em] text-[#26D07C]">ele vê</p>
          <ul className="mt-4 space-y-3">
            {SEES.map((item) => (
              <li key={item} className="flex items-start gap-3 text-[17px] leading-8 text-[#E8F1EC]">
                <Check size={18} weight="bold" className="mt-1.5 shrink-0 text-[#26D07C]" aria-hidden="true" />
                {item}
              </li>
            ))}
          </ul>

          <p className="mt-8 border-t border-white/10 pt-8 text-[11px] uppercase tracking-[0.3em] text-[#94A6AE]">
            ele não vê
          </p>
          <ul className="mt-4 space-y-3">
            {DOES_NOT_SEE.map((item) => (
              <li key={item} className="flex items-start gap-3 leading-8 text-[#94A6AE]">
                <X size={18} weight="bold" className="mt-1.5 shrink-0 text-[#6E6D67]" aria-hidden="true" />
                {item}
              </li>
            ))}
          </ul>

          <a href={DEMO_MAP_URL} className={`mt-10 ${primaryCta}`}>
            Abrir o mapa de demonstração
            <ArrowRight size={18} weight="bold" aria-hidden="true" />
          </a>
        </Reveal>
      </div>
    </section>
  );
}
