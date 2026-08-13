import { useState } from "react";
import { Plus } from "@phosphor-icons/react";
import { Reveal, SectionLabel, focusRing } from "./primitives";

const QUESTIONS = [
  {
    question: "Que tipo de PDF eu preciso enviar?",
    answer:
      "O PDF vetorial que sai do CAD, o mesmo arquivo do projeto. Se o PDF for apenas uma imagem escaneada, o sistema recusa com um aviso claro em vez de tentar adivinhar onde estão os lotes. O limite de tamanho padrão é de 80 MB por arquivo.",
  },
  {
    question: "E se o mapeamento errar algum lote?",
    answer:
      "O sistema compara o que extraiu com o gabarito impresso na própria planta — aquela linha \"Q195 - 34 LOTES\" — e marca a quadra que não bateu. Você revisa e ajusta antes de publicar: nada chega ao cliente sem passar por você.",
  },
  {
    question: "Quem pode editar o mapa?",
    answer:
      "Por padrão, só a sua equipe. Se você liberar edição no link compartilhado, o que o cliente alterar entra como proposta; a versão publicada continua igual até você aprovar.",
  },
  {
    question: "O link expira?",
    answer:
      "Não expira sozinho. Você pode definir uma data de validade quando cria o link e revogar o acesso quando quiser — o link revogado para de abrir na hora.",
  },
  {
    question: "Funciona no celular?",
    answer:
      "Sim. O mapa abre no navegador do celular, que é onde o cliente costuma receber o link. Não existe aplicativo para baixar nem cadastro obrigatório, a menos que você escolha o modo privado, que pede login.",
  },
  {
    question: "Preciso instalar alguma coisa?",
    answer:
      "Não. Você envia o PDF pelo navegador e recebe um link. Não há plugin de CAD, extensão ou programa para instalar em nenhuma ponta.",
  },
  {
    question: "O mapa publicado muda sozinho?",
    answer:
      "Não. Publicar gera uma versão do mapa. Alterações posteriores ficam como rascunho até você publicar de novo, então o link que já está com o cliente não muda pelas suas costas.",
  },
];

export function FaqSection() {
  const [openIndex, setOpenIndex] = useState<number | null>(0);

  return (
    <section id="perguntas" className="scroll-mt-24 border-y border-white/10 bg-[#080F14] px-4 py-24 md:px-8 md:py-28">
      <div className="mx-auto grid max-w-[1400px] gap-12 lg:grid-cols-[0.7fr_1.3fr] lg:items-start">
        <Reveal>
          <SectionLabel>perguntas</SectionLabel>
          <h2 className="mt-5 max-w-[14ch] text-4xl font-medium leading-[1.12] tracking-tight text-[#E8F1EC] md:text-[46px]">
            O que perguntam antes de mandar a planta.
          </h2>
        </Reveal>

        <Reveal delay={120}>
          <ul className="divide-y divide-white/10 border-y border-white/10">
            {QUESTIONS.map((item, index) => {
              const isOpen = openIndex === index;
              return (
                <li key={item.question}>
                  <h3>
                    <button
                      type="button"
                      id={`faq-botao-${index}`}
                      aria-expanded={isOpen}
                      aria-controls={`faq-painel-${index}`}
                      onClick={() => setOpenIndex(isOpen ? null : index)}
                      className={`flex w-full items-center justify-between gap-6 py-6 text-left text-lg font-medium text-[#E8F1EC] transition hover:text-[#26D07C] ${focusRing}`}
                    >
                      {item.question}
                      <Plus
                        size={20}
                        weight="bold"
                        aria-hidden="true"
                        className={`shrink-0 text-[#26D07C] transition-transform duration-300 motion-reduce:transition-none ${
                          isOpen ? "rotate-45" : "rotate-0"
                        }`}
                      />
                    </button>
                  </h3>
                  <div
                    id={`faq-painel-${index}`}
                    role="region"
                    aria-labelledby={`faq-botao-${index}`}
                    aria-hidden={!isOpen}
                    className={`grid transition-[grid-template-rows] duration-300 ease-out motion-reduce:transition-none ${
                      isOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
                    }`}
                  >
                    <div className="overflow-hidden">
                      <p className="max-w-[70ch] pb-7 pr-10 leading-8 text-[#94A6AE]">{item.answer}</p>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </Reveal>
      </div>
    </section>
  );
}
