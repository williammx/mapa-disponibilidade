import {
  ClockCountdown,
  Globe,
  LinkSimple,
  LockKey,
  PencilSimple,
  Prohibit,
  SignIn,
} from "@phosphor-icons/react";
import { Reveal, SectionLabel } from "./primitives";

const MODES = [
  {
    icon: Globe,
    name: "Público",
    text: "Endereço fixo e previsível, do jeito que você coloca num anúncio ou num QR code de placa.",
  },
  {
    icon: LinkSimple,
    name: "Não listado",
    text: "Link com código aleatório: abre para quem recebeu, não aparece para quem sai adivinhando.",
  },
  {
    icon: LockKey,
    name: "Com senha",
    text: "Além do link, o visitante digita a senha que você definiu. Serve para apresentação pontual.",
  },
  {
    icon: SignIn,
    name: "Privado",
    text: "Só entra quem tem login vinculado ao cliente. Nada de mapa circulando em grupo de WhatsApp.",
  },
];

export function AccessSection() {
  return (
    <section id="acesso" className="scroll-mt-24 border-y border-white/10 bg-[#080F14] px-4 py-24 md:px-8 md:py-28">
      <div className="mx-auto max-w-[1400px]">
        <div className="grid gap-12 lg:grid-cols-[0.9fr_1.1fr] lg:items-start">
          <Reveal>
            <SectionLabel>acesso ao link</SectionLabel>
            <h2 className="mt-5 max-w-[18ch] text-4xl font-medium leading-[1.12] tracking-tight text-[#E8F1EC] md:text-[46px]">
              Você decide quem abre o{" "}
              <span className="font-serif italic text-[#26D07C]">mapa</span>.
            </h2>
            <p className="mt-6 max-w-[44ch] text-lg leading-8 text-[#94A6AE]">
              O mesmo mapa pode virar peça de campanha ou material reservado de uma negociação. O
              modo de acesso é escolhido na hora de compartilhar e pode mudar depois.
            </p>
          </Reveal>

          <div className="grid gap-4 sm:grid-cols-2">
            {MODES.map((mode, index) => (
              <Reveal
                key={mode.name}
                delay={index * 100}
                className="rounded-2xl border border-white/10 bg-[#0C161B] p-6"
              >
                <mode.icon size={24} weight="regular" className="text-[#26D07C]" aria-hidden="true" />
                <h3 className="mt-6 text-lg font-medium text-[#E8F1EC]">{mode.name}</h3>
                <p className="mt-2 leading-7 text-[#94A6AE]">{mode.text}</p>
              </Reveal>
            ))}
          </div>
        </div>

        <Reveal
          delay={120}
          className="mt-6 flex flex-col gap-6 rounded-2xl border border-[#26D07C]/25 bg-[linear-gradient(120deg,rgba(38,208,124,0.12)_0%,rgba(12,22,27,0.9)_60%)] p-7 md:flex-row md:items-center md:gap-10 md:p-9"
        >
          <PencilSimple size={30} weight="regular" className="shrink-0 text-[#26D07C]" aria-hidden="true" />
          <div>
            <h3 className="text-xl font-medium text-[#E8F1EC]">O cliente edita, você aprova</h3>
            <p className="mt-2 max-w-[70ch] leading-7 text-[#94A6AE]">
              Quando você libera edição no link, o que o cliente mexe entra como proposta. A versão
              publicada continua exatamente como está até você aceitar a alteração.
            </p>
          </div>
        </Reveal>

        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          <Reveal className="flex items-center gap-4 rounded-2xl border border-white/10 bg-[#0C161B] px-6 py-5">
            <ClockCountdown size={22} weight="regular" className="shrink-0 text-[#94A6AE]" aria-hidden="true" />
            <p className="leading-7 text-[#94A6AE]">
              O link não expira sozinho — você define uma data de validade se quiser.
            </p>
          </Reveal>
          <Reveal delay={100} className="flex items-center gap-4 rounded-2xl border border-white/10 bg-[#0C161B] px-6 py-5">
            <Prohibit size={22} weight="regular" className="shrink-0 text-[#94A6AE]" aria-hidden="true" />
            <p className="leading-7 text-[#94A6AE]">
              Revogar o acesso é imediato: o link revogado para de abrir na hora.
            </p>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
