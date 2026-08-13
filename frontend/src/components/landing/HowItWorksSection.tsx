import { FilePdf, Scan, ShareNetwork, SlidersHorizontal, UploadSimple } from "@phosphor-icons/react";
import { useInView, useReducedMotion } from "./motion";
import { InlinePill, Reveal, SectionLabel, StepNumber } from "./primitives";

const STEPS = [
  {
    number: "01",
    icon: UploadSimple,
    title: "Envie o PDF da planta",
    text: "O mesmo arquivo que saiu do CAD. Se o PDF for só uma imagem escaneada, o sistema avisa na hora em vez de entregar um mapa torto.",
  },
  {
    number: "02",
    icon: Scan,
    title: "O sistema lê os lotes",
    text: "Cada lote sai com nome, quadra e metragem do jeito que está impresso no desenho, sem ninguém redesenhar nada.",
  },
  {
    number: "03",
    icon: SlidersHorizontal,
    title: "Você revisa e marca",
    text: "Disponível, reservado ou vendido, lote a lote. O que o sistema marcou como divergente aparece separado para você conferir.",
  },
  {
    number: "04",
    icon: ShareNetwork,
    title: "Compartilhe o link",
    text: "Público, não listado ou protegido por senha. O cliente abre no navegador do celular, sem instalar nada.",
  },
];

export function HowItWorksSection() {
  const reduced = useReducedMotion();
  const { ref, inView } = useInView<HTMLDivElement>({ threshold: 0.25 });
  const drawn = reduced || inView;

  return (
    <section id="como-funciona" className="scroll-mt-24 border-y border-white/10 bg-[#080F14] px-4 py-24 md:px-8 md:py-28">
      <div className="mx-auto max-w-[1400px]">
        <Reveal>
          <SectionLabel>como funciona</SectionLabel>
          <h2 className="mt-5 max-w-[22ch] text-4xl font-medium leading-[1.15] tracking-tight text-[#E8F1EC] md:text-[46px]">
            Do
            <InlinePill icon={<FilePdf size={18} weight="regular" aria-hidden="true" />}>PDF</InlinePill>
            ao mapa em minutos.
          </h2>
        </Reveal>

        <div ref={ref} className="relative mt-16">
          {/* Linha pontilhada ligando as etapas (ref-24): desenha ao entrar na viewport. */}
          <span
            aria-hidden="true"
            className="absolute left-[26px] top-0 h-full w-px origin-top bg-[repeating-linear-gradient(180deg,rgba(148,166,174,0.55)_0_5px,transparent_5px_12px)] transition-transform duration-1000 ease-out lg:hidden"
            style={{ transform: `scaleY(${drawn ? 1 : 0})` }}
          />
          <span
            aria-hidden="true"
            className="absolute left-0 top-[26px] hidden h-px w-full origin-left bg-[repeating-linear-gradient(90deg,rgba(148,166,174,0.55)_0_5px,transparent_5px_12px)] transition-transform duration-1000 ease-out lg:block"
            style={{ transform: `scaleX(${drawn ? 1 : 0})` }}
          />

          <ol className="grid gap-12 lg:grid-cols-4 lg:gap-8">
            {STEPS.map((step, index) => (
              <li key={step.number}>
                <Reveal delay={index * 130} className="flex gap-6 lg:block">
                  <span className="relative z-10 flex size-[52px] shrink-0 items-center justify-center rounded-full border border-white/12 bg-[#0C161B]">
                    <step.icon size={22} weight="regular" className="text-[#26D07C]" aria-hidden="true" />
                  </span>
                  <div className="lg:mt-7">
                    <StepNumber value={step.number} />
                    <h3 className="mt-3 text-xl font-medium text-[#E8F1EC]">{step.title}</h3>
                    <p className="mt-3 max-w-[38ch] leading-7 text-[#94A6AE]">{step.text}</p>
                  </div>
                </Reveal>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
