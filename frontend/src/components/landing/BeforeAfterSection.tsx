import { useState } from "react";
import { ArrowsHorizontal } from "@phosphor-icons/react";
import { PlantSchematic } from "./PlantSchematic";
import { Reveal, SectionLabel } from "./primitives";

export function BeforeAfterSection() {
  const [position, setPosition] = useState(52);

  return (
    <section id="antes-depois" className="scroll-mt-24 px-4 py-24 md:px-8 md:py-28">
      <div className="mx-auto max-w-[1400px]">
        <Reveal className="max-w-[52ch]">
          <SectionLabel>antes e depois</SectionLabel>
          <h2 className="mt-5 text-4xl font-medium leading-[1.12] tracking-tight text-[#E8F1EC] md:text-[46px]">
            A mesma geometria, agora com{" "}
            <span className="font-serif italic text-[#26D07C]">resposta</span>.
          </h2>
          <p className="mt-6 text-lg leading-8 text-[#94A6AE]">
            Arraste o divisor. À esquerda, o traço que o PDF entrega: quadras, lotes e o gabarito
            impresso. À direita, o mesmo traço depois de virar mapa, com o status de cada lote.
          </p>
        </Reveal>

        <Reveal delay={120} className="mt-12">
          <figure className="overflow-hidden rounded-2xl border border-white/10 bg-[#0A1116]">
            <div className="relative aspect-[16/9] w-full sm:aspect-[620/298]">
              <div className="absolute inset-0 p-4 sm:p-8">
                <PlantSchematic mode="map" />
              </div>
              <div
                className="absolute inset-0 bg-[#0A1116] p-4 sm:p-8"
                style={{ clipPath: `inset(0 ${100 - position}% 0 0)` }}
              >
                <PlantSchematic mode="blueprint" />
              </div>

              <span className="pointer-events-none absolute left-4 top-4 rounded-full border border-white/10 bg-[#060C10]/80 px-3 py-1.5 text-[11px] uppercase tracking-[0.18em] text-[#94A6AE] backdrop-blur-sm">
                planta em PDF
              </span>
              <span className="pointer-events-none absolute right-4 top-4 rounded-full border border-[#26D07C]/30 bg-[#060C10]/80 px-3 py-1.5 text-[11px] uppercase tracking-[0.18em] text-[#26D07C] backdrop-blur-sm">
                mapa interativo
              </span>

              <input
                type="range"
                min={0}
                max={100}
                step={1}
                value={position}
                onChange={(event) => setPosition(Number(event.target.value))}
                aria-label="Comparar a planta em PDF com o mapa interativo"
                aria-valuetext={`${position}% da planta em PDF visível`}
                className="peer absolute inset-0 z-20 h-full w-full cursor-col-resize appearance-none bg-transparent opacity-0 [&::-moz-range-thumb]:h-full [&::-moz-range-thumb]:w-px [&::-moz-range-thumb]:border-0 [&::-webkit-slider-thumb]:h-full [&::-webkit-slider-thumb]:w-px [&::-webkit-slider-thumb]:appearance-none"
              />
              {/* O input acima e invisivel: o foco do teclado aparece aqui, na propria alca. */}
              <div
                aria-hidden="true"
                className="pointer-events-none absolute inset-y-0 z-10 w-px -translate-x-1/2 bg-white/60 transition-colors peer-focus-visible:w-[3px] peer-focus-visible:bg-[#26D07C]"
                style={{ left: `${position}%` }}
              >
                <span className="absolute left-1/2 top-1/2 flex size-11 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-white/25 bg-[#060C10]/85 text-[#E8F1EC] shadow-[0_12px_34px_-14px_rgba(0,0,0,0.95)] backdrop-blur-md">
                  <ArrowsHorizontal size={18} weight="bold" />
                </span>
              </div>
            </div>
            <figcaption className="border-t border-white/10 px-5 py-4 text-sm text-[#94A6AE]">
              Esquema ilustrativo do mesmo conjunto de quadras: à esquerda o desenho técnico, à
              direita as cores de status. Não é captura do produto.
            </figcaption>
          </figure>
        </Reveal>
      </div>
    </section>
  );
}
