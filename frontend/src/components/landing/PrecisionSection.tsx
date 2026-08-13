import { CheckCircle, WarningCircle } from "@phosphor-icons/react";
import { useCountUp, useInView } from "./motion";
import { Reveal, SectionLabel } from "./primitives";

const METRICS = [
  {
    value: 99.8,
    decimals: 1,
    suffix: "%",
    title: "dos lotes encontrados",
    text: "Proporção dos lotes desenhados na planta que o sistema separa sozinho, sem ninguém redesenhar.",
  },
  {
    value: 91,
    decimals: 0,
    suffix: "%",
    title: "com a área conferida",
    text: "Lotes cuja área calculada fica a até 3% da metragem impressa no próprio PDF.",
  },
  {
    value: 1182,
    decimals: 0,
    suffix: "",
    title: "lotes em uma planta",
    text: "Maior planta processada até aqui, do arquivo do CAD ao mapa navegável.",
  },
];

const CHECKS = [
  { quadra: "Q195", declarado: 34, extraido: 34, ok: true },
  { quadra: "Q193", declarado: 28, extraido: 27, ok: false },
];

export function PrecisionSection() {
  const { ref, inView } = useInView<HTMLDivElement>({ threshold: 0.3 });

  return (
    <section id="precisao" className="scroll-mt-24 border-y border-white/10 bg-[#080F14] px-4 py-24 md:px-8 md:py-28">
      <div className="mx-auto max-w-[1400px]">
        <Reveal className="max-w-[54ch]">
          <SectionLabel>precisão do mapeamento</SectionLabel>
          <h2 className="mt-5 text-4xl font-medium leading-[1.12] tracking-tight text-[#E8F1EC] md:text-[46px]">
            O sistema confere o próprio trabalho contra a planta.
          </h2>
        </Reveal>

        <div ref={ref} className="mt-14 grid gap-px overflow-hidden rounded-2xl bg-white/10 sm:grid-cols-3">
          {METRICS.map((metric, index) => (
            <Metric key={metric.title} {...metric} active={inView} delay={index * 140} />
          ))}
        </div>

        <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_1fr]">
          <Reveal className="rounded-2xl border border-white/10 bg-[#0C161B] p-7 md:p-9">
            <h3 className="text-xl font-medium text-[#E8F1EC]">
              Toda planta traz o gabarito impresso
            </h3>
            <p className="mt-4 leading-8 text-[#94A6AE]">
              Aquela linha no canto do desenho — <span className="font-mono text-[#C7D6D0]">Q195 - 34 LOTES</span>{" "}
              — diz quantos lotes cada quadra deveria ter. O NexoLote lê essa linha, compara com o
              que extraiu e mostra a quadra que não bateu, em vez de entregar um erro silencioso
              para você descobrir na frente do cliente.
            </p>
          </Reveal>

          <Reveal delay={120} className="rounded-2xl border border-white/10 bg-[#0C161B] p-7 md:p-9">
            <p className="text-[11px] uppercase tracking-[0.3em] text-[#94A6AE]">
              exemplo da conferência
            </p>
            <ul className="mt-6 space-y-3">
              {CHECKS.map((check) => (
                <li
                  key={check.quadra}
                  className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-white/10 bg-[#060C10] px-4 py-3 font-mono text-sm"
                >
                  <span className="text-[#E8F1EC]">{check.quadra}</span>
                  <span className="text-[#94A6AE]">
                    gabarito {check.declarado} · extraídos {check.extraido}
                  </span>
                  <span
                    className={`ml-auto inline-flex items-center gap-2 ${
                      check.ok ? "text-[#26D07C]" : "text-[#E0613B]"
                    }`}
                  >
                    {check.ok ? (
                      <CheckCircle size={16} weight="fill" aria-hidden="true" />
                    ) : (
                      <WarningCircle size={16} weight="fill" aria-hidden="true" />
                    )}
                    {check.ok ? "confere" : "conferir"}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-6 text-sm leading-6 text-[#94A6AE]">
              Números medidos em agosto de 2026, em duas plantas reais, com o roteiro de QA do
              próprio projeto.
            </p>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

function Metric({
  value,
  decimals,
  suffix,
  title,
  text,
  active,
  delay,
}: {
  value: number;
  decimals: number;
  suffix: string;
  title: string;
  text: string;
  active: boolean;
  delay: number;
}) {
  const display = useCountUp(value, active, decimals, 1600);

  return (
    <div className="bg-[#0C161B] p-7 md:p-9">
      <Reveal delay={delay}>
        <p className="text-5xl font-medium tracking-tight text-[#E8F1EC] md:text-6xl">
          {display}
          <span className="text-[#26D07C]">{suffix}</span>
        </p>
        <p className="mt-4 text-lg font-medium text-[#E8F1EC]">{title}</p>
        <p className="mt-2 leading-7 text-[#94A6AE]">{text}</p>
      </Reveal>
    </div>
  );
}
