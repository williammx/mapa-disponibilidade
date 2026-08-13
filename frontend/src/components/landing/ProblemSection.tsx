import { FilePdf, Table, WarningCircle } from "@phosphor-icons/react";
import { Reveal, SectionLabel } from "./primitives";

const SCENES = [
  {
    icon: Table,
    title: "A planilha é de ontem",
    text: "Cada corretor tem uma cópia. A que está aberta no computador do plantão quase nunca é a mais nova.",
  },
  {
    icon: FilePdf,
    title: "O PDF não sabe o que foi vendido",
    text: "A planta impressa mostra o desenho dos lotes, mas nada nela muda quando um lote sai da mesa.",
  },
  {
    icon: WarningCircle,
    title: "O cliente ouve um sim que já era não",
    text: "O corretor oferece um lote reservado na semana passada e a conversa começa com um desmentido.",
  },
];

export function ProblemSection() {
  return (
    <section className="px-4 py-24 md:px-8 md:py-28">
      <div className="mx-auto grid max-w-[1400px] gap-14 lg:grid-cols-[0.85fr_1.15fr] lg:items-start">
        <Reveal>
          <SectionLabel>o problema</SectionLabel>
          <h2 className="mt-5 max-w-[16ch] text-4xl font-medium leading-[1.1] tracking-tight text-[#E8F1EC] md:text-[46px]">
            A disponibilidade some entre a planta e a{" "}
            <span className="font-serif italic text-[#E0613B]">planilha</span>.
          </h2>
          <p className="mt-6 max-w-[46ch] text-lg leading-8 text-[#94A6AE]">
            O desenho do loteamento vive num arquivo, o status de cada lote vive em outro, e quem
            está na frente do cliente precisa juntar os dois de cabeça.
          </p>
        </Reveal>

        <ul className="space-y-4">
          {SCENES.map((scene, index) => (
            <li key={scene.title}>
              <Reveal
                delay={index * 110}
                className="flex gap-5 rounded-2xl border border-white/10 bg-[#0C161B]/80 p-6 md:p-7"
              >
                <span className="mt-0.5 flex size-11 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-[#060C10]">
                  <scene.icon size={20} weight="regular" className="text-[#E0613B]" aria-hidden="true" />
                </span>
                <div>
                  <h3 className="text-lg font-medium text-[#E8F1EC]">{scene.title}</h3>
                  <p className="mt-2 leading-7 text-[#94A6AE]">{scene.text}</p>
                </div>
              </Reveal>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
