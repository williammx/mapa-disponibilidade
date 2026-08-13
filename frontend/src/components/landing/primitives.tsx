import type { ReactNode } from "react";
import { useInView, useReducedMotion } from "./motion";

/**
 * Endereco de contato do produto. Ainda nao existe endpoint de lead nem caixa
 * comercial dedicada, entao o CTA vai por e-mail; trocar aqui quando existir.
 */
export const CONTACT_EMAIL = "supremoesportesmt@gmail.com";
export const CONTACT_MAILTO = `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(
  "Quero mapear a planta do meu loteamento",
)}`;
export const DEMO_MAP_URL = "/mapas/setor-e-demo";

export const STATUS_COLORS = {
  disponivel: "#26D07C",
  reservado: "#E0613B",
  vendido: "#6E6D67",
} as const;

export type LotStatus = keyof typeof STATUS_COLORS;

// Cinza de lote vendido nao passa em contraste como texto sobre fundo escuro:
// a cor fica na bolinha e o rotulo usa um cinza claro.
export const STATUS_TEXT: Record<LotStatus, string> = {
  disponivel: "#26D07C",
  reservado: "#E0613B",
  vendido: "#B4B3AC",
};

export const STATUS_LABEL: Record<LotStatus, string> = {
  disponivel: "disponível",
  reservado: "reservado",
  vendido: "vendido",
};

export const focusRing =
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#26D07C]";

export const primaryCta = `inline-flex items-center justify-center gap-2 rounded-full bg-[#26D07C] px-7 py-4 text-[15px] font-semibold text-[#03150C] transition hover:bg-[#4BE097] active:translate-y-px ${focusRing}`;

export const ghostCta = `inline-flex items-center justify-center gap-2 rounded-full border border-white/15 px-7 py-4 text-[15px] font-medium text-[#E8F1EC] transition hover:border-white/35 hover:bg-white/[0.06] active:translate-y-px ${focusRing}`;

export function Reveal({
  children,
  delay = 0,
  className = "",
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  const reduced = useReducedMotion();
  const { ref, inView } = useInView<HTMLDivElement>();
  const visible = reduced || inView;

  return (
    <div
      ref={ref}
      className={`transition-[opacity,transform] duration-700 ease-out ${
        visible ? "translate-y-0 opacity-100" : "translate-y-6 opacity-0"
      } ${className}`}
      style={reduced ? undefined : { transitionDelay: `${delay}ms` }}
    >
      {children}
    </div>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <p className="text-[11px] font-medium uppercase tracking-[0.3em] text-[#94A6AE]">{children}</p>
  );
}

export function StepNumber({ value }: { value: string }) {
  return (
    <span className="font-mono text-sm tracking-[0.14em] text-[#26D07C]">
      <span aria-hidden="true">\</span>
      {value}
    </span>
  );
}

export function StatusDot({ status, className = "" }: { status: LotStatus; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block size-2.5 shrink-0 rounded-full ${className}`}
      style={{ backgroundColor: STATUS_COLORS[status] }}
    />
  );
}

export function LivePill({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-2.5 rounded-full border border-white/15 bg-white/[0.04] px-4 py-2 text-[13px] text-[#C7D6D0] backdrop-blur-sm">
      <span className="relative flex size-2">
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-[#26D07C] opacity-75 motion-reduce:hidden" />
        <span className="relative inline-flex size-2 rounded-full bg-[#26D07C]" />
      </span>
      {children}
    </span>
  );
}

/**
 * Assinatura da ref-24: uma palavra da frase vira pill com icone,
 * dentro da propria headline.
 */
export function InlinePill({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <span className="mx-1 inline-flex translate-y-[-0.06em] items-center gap-2 rounded-full border border-[#26D07C]/35 bg-[#26D07C]/10 px-4 py-1 align-middle text-[0.78em] font-medium text-[#26D07C]">
      {icon}
      {children}
    </span>
  );
}
