import { ArrowRight, EnvelopeSimple } from "@phosphor-icons/react";
import { CONTACT_MAILTO, DEMO_MAP_URL, Reveal, ghostCta, primaryCta } from "./primitives";

export function FinalCtaSection() {
  return (
    <section className="relative isolate overflow-hidden">
      <img
        src="/hero-noturno-1600.webp"
        srcSet="/hero-noturno-1000.webp 1000w, /hero-noturno-1600.webp 1600w"
        sizes="100vw"
        alt=""
        aria-hidden="true"
        loading="lazy"
        decoding="async"
        className="absolute inset-0 -z-10 h-full w-full object-cover"
      />
      <div
        aria-hidden="true"
        className="absolute inset-0 -z-10 bg-[linear-gradient(180deg,rgba(6,12,16,0.90)_0%,rgba(6,12,16,0.60)_48%,rgba(6,12,16,0.93)_100%)]"
      />

      <div className="mx-auto max-w-[1400px] px-4 py-28 md:px-8 md:py-36">
        <Reveal>
          <h2 className="max-w-[19ch] text-4xl font-medium leading-[1.1] tracking-tight text-[#E8F1EC] md:text-[54px]">
            Mande a planta do seu loteamento e veja o mapa{" "}
            <span className="font-serif italic text-[#26D07C]">acontecer</span>.
          </h2>
          <p className="mt-6 max-w-[48ch] text-lg leading-8 text-[#C7D6D0]">
            Envie o PDF por e-mail e a gente devolve o mapa do seu empreendimento com os lotes
            separados, para você conferir antes de qualquer coisa ir ao ar.
          </p>
          <div className="mt-10 flex flex-col gap-3 sm:flex-row">
            <a href={CONTACT_MAILTO} className={primaryCta}>
              <EnvelopeSimple size={18} weight="regular" aria-hidden="true" />
              Enviar minha planta
            </a>
            <a href={DEMO_MAP_URL} className={ghostCta}>
              Ver o mapa de demonstração
              <ArrowRight size={18} weight="bold" aria-hidden="true" />
            </a>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
