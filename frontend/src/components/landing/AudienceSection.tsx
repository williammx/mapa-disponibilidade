import { Buildings, DeviceMobile, UsersThree } from "@phosphor-icons/react";
import { Reveal, SectionLabel, StepNumber } from "./primitives";

const AUDIENCES = [
  {
    number: "01",
    icon: Buildings,
    role: "Loteadora",
    text: "O desenho oficial é seu e a palavra final sobre o que já foi vendido também. O mapa nasce do seu PDF e só vai para o ar quando você aprova.",
    panel: "h-[220px]",
    offset: "",
  },
  {
    number: "02",
    icon: UsersThree,
    role: "Imobiliária",
    text: "A equipe inteira consulta o mesmo mapa. Quando um lote muda de status, muda para todo mundo no mesmo link — não em seis cópias de planilha.",
    panel: "h-[300px]",
    offset: "lg:mt-14",
  },
  {
    number: "03",
    icon: DeviceMobile,
    role: "Corretor",
    text: "No plantão de vendas, abre o link no celular e mostra na hora quais lotes daquela quadra ainda estão livres.",
    panel: "h-[260px]",
    offset: "lg:mt-6",
  },
];

export function AudienceSection() {
  return (
    <section className="px-4 py-24 md:px-8 md:py-28">
      <div className="mx-auto max-w-[1400px]">
        <Reveal className="max-w-[46ch]">
          <SectionLabel>para quem é</SectionLabel>
          <h2 className="mt-5 text-4xl font-medium leading-[1.12] tracking-tight text-[#E8F1EC] md:text-[46px]">
            Três pessoas olham o mesmo lote e precisam da mesma resposta.
          </h2>
        </Reveal>

        <div className="mt-16 grid gap-10 lg:grid-cols-3 lg:gap-8">
          {AUDIENCES.map((item, index) => (
            <Reveal key={item.role} delay={index * 130} className={item.offset}>
              <div
                aria-hidden="true"
                className={`flex items-end justify-start rounded-2xl border border-white/10 bg-[linear-gradient(160deg,rgba(38,208,124,0.10)_0%,rgba(12,22,27,0.9)_55%)] p-7 ${item.panel}`}
              >
                <item.icon size={40} weight="light" className="text-[#26D07C]" />
              </div>
              <div className="mt-6 flex items-baseline gap-4">
                <StepNumber value={item.number} />
                <h3 className="text-2xl font-medium text-[#E8F1EC]">{item.role}</h3>
              </div>
              <p className="mt-3 max-w-[42ch] leading-7 text-[#94A6AE]">{item.text}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
