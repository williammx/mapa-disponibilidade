import { useEffect, useState } from "react";
import { ArrowRight, Check, EnvelopeSimple } from "@phosphor-icons/react";
import { useParallax, useReducedMotion } from "./motion";
import {
  CONTACT_MAILTO,
  DEMO_MAP_URL,
  LivePill,
  STATUS_COLORS,
  STATUS_LABEL,
  STATUS_TEXT,
  type LotStatus,
  ghostCta,
  primaryCta,
} from "./primitives";

type FloatingLabel = {
  lot: string;
  area: string;
  status: LotStatus;
  top: string;
  left: string;
  compact?: boolean;
};

/**
 * Assinatura da ref-24: as etiquetas de lote entram uma a uma sobre a foto,
 * como se o mapeamento estivesse acontecendo ao vivo.
 */
const FLOATING_LABELS: FloatingLabel[] = [
  { lot: "Q195-L003", area: "178 m²", status: "disponivel", top: "10%", left: "6%" },
  { lot: "Q195-L004", area: "206 m²", status: "vendido", top: "27%", left: "42%", compact: true },
  { lot: "Q193-L002", area: "245 m²", status: "reservado", top: "46%", left: "2%" },
  { lot: "Q194-L011", area: "312 m²", status: "disponivel", top: "65%", left: "38%", compact: true },
  { lot: "Q193-L008", area: "198 m²", status: "disponivel", top: "82%", left: "8%" },
];

const MICRO_PROOFS = ["Sem instalar nada", "Link pronto em minutos", "Você aprova antes de publicar"];

export function HeroSection() {
  const reduced = useReducedMotion();
  const parallax = useParallax(0.05);
  const [revealed, setRevealed] = useState(0);

  useEffect(() => {
    if (reduced) {
      setRevealed(FLOATING_LABELS.length);
      return;
    }
    let index = 0;
    let interval = 0;
    const start = window.setTimeout(() => {
      interval = window.setInterval(() => {
        index += 1;
        setRevealed(index);
        if (index >= FLOATING_LABELS.length) {
          window.clearInterval(interval);
        }
      }, 280);
    }, 520);
    return () => {
      window.clearTimeout(start);
      window.clearInterval(interval);
    };
  }, [reduced]);

  return (
    <section className="px-4 pb-6 pt-20 md:px-8 md:pt-24">
      <div className="mx-auto max-w-[1400px]">
        <div className="relative overflow-hidden rounded-[28px] border border-white/10 bg-[#0A1116]">
          <img
            src="/hero-noturno-1600.webp"
            srcSet="/hero-noturno-1000.webp 1000w, /hero-noturno-1600.webp 1600w"
            sizes="(min-width: 1440px) 1400px, 100vw"
            alt="Vista aérea noturna de um loteamento, com ruas iluminadas separando as quadras de lotes"
            loading="eager"
            decoding="async"
            className="absolute inset-x-0 -top-[10%] h-[120%] w-full object-cover"
            style={{ transform: `translate3d(0, ${parallax}px, 0)` }}
          />
          <div
            aria-hidden="true"
            className="absolute inset-0 bg-[linear-gradient(105deg,rgba(6,12,16,0.94)_0%,rgba(6,12,16,0.82)_40%,rgba(6,12,16,0.48)_66%,rgba(6,12,16,0.28)_100%)]"
          />

          <p className="absolute left-6 top-6 z-10 hidden text-[11px] uppercase leading-5 tracking-[0.22em] text-[#94A6AE] md:left-12 md:top-10 md:block">
            PDF do CAD //
            <br />
            Lote, quadra e metragem //
            <br />
            Link para o cliente //
          </p>

          <div className="relative z-10 grid lg:grid-cols-[minmax(0,1fr)_minmax(0,0.8fr)]">
            <div className="px-6 pb-12 pt-16 md:px-12 md:pb-16 md:pt-36">
              <LivePill>1.182 lotes lidos de uma única planta</LivePill>

              <h1 className="mt-7 max-w-[620px] text-[38px] font-medium leading-[1.06] tracking-tight text-[#E8F1EC] sm:text-5xl lg:text-[60px]">
                Sua planta em PDF vira um mapa que o cliente{" "}
                <span className="font-serif italic text-[#26D07C]">entende</span>.
              </h1>

              <p className="mt-6 max-w-[520px] text-lg leading-8 text-[#94A6AE]">
                Você envia o PDF do loteamento. O NexoLote extrai cada lote com nome, quadra e
                metragem e devolve um mapa onde disponível, reservado e vendido ficam claros em um
                link só.
              </p>

              <div className="mt-9 flex flex-col gap-3 sm:flex-row">
                <a href={DEMO_MAP_URL} className={primaryCta}>
                  Ver a demonstração
                  <ArrowRight size={18} weight="bold" aria-hidden="true" />
                </a>
                <a href={CONTACT_MAILTO} className={ghostCta}>
                  <EnvelopeSimple size={18} weight="regular" aria-hidden="true" />
                  Enviar minha planta
                </a>
              </div>

              <ul className="mt-9 flex flex-wrap gap-x-7 gap-y-3">
                {MICRO_PROOFS.map((proof) => (
                  <li key={proof} className="flex items-center gap-2 text-sm text-[#C7D6D0]">
                    <Check size={15} weight="bold" className="text-[#26D07C]" aria-hidden="true" />
                    {proof}
                  </li>
                ))}
              </ul>
            </div>

            <ul
              aria-label="Exemplo das etiquetas que o NexoLote gera sobre a planta"
              className="relative mx-2 mb-6 h-[260px] lg:mx-0 lg:mb-0 lg:h-auto lg:min-h-[520px]"
            >
              {FLOATING_LABELS.map((label, index) => {
                const visible = index < revealed;
                return (
                  <li
                    key={label.lot}
                    style={{ top: label.top, left: label.left }}
                    className={`absolute items-center gap-2 whitespace-nowrap rounded-full border border-white/15 bg-[#060C10]/70 px-3.5 py-2 text-[12px] shadow-[0_12px_34px_-14px_rgba(0,0,0,0.95)] backdrop-blur-md transition-[opacity,transform] duration-500 ease-out ${
                      visible ? "translate-y-0 scale-100 opacity-100" : "translate-y-3 scale-95 opacity-0"
                    } ${label.compact ? "hidden sm:flex" : "flex"}`}
                  >
                    <span
                      aria-hidden="true"
                      className="size-2 shrink-0 rounded-full"
                      style={{ backgroundColor: STATUS_COLORS[label.status] }}
                    />
                    <span className="font-mono tracking-tight text-[#E8F1EC]">{label.lot}</span>
                    <span className="text-[#94A6AE]">· {label.area} ·</span>
                    <span style={{ color: STATUS_TEXT[label.status] }}>
                      {STATUS_LABEL[label.status]}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}
