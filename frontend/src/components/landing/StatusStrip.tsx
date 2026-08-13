import { Reveal, StatusDot, type LotStatus } from "./primitives";

const STATUSES: { status: LotStatus; name: string; description: string }[] = [
  { status: "disponivel", name: "Disponível", description: "pode ser oferecido agora" },
  { status: "reservado", name: "Reservado", description: "está segurado para um cliente" },
  { status: "vendido", name: "Vendido", description: "sai da mesa do corretor" },
];

export function StatusStrip() {
  return (
    <section className="border-y border-white/10 bg-[#080F14] px-4 py-10 md:px-8">
      <div className="mx-auto flex max-w-[1400px] flex-col gap-8 lg:flex-row lg:items-center lg:justify-between">
        <p className="max-w-[15rem] text-[11px] uppercase leading-5 tracking-[0.3em] text-[#94A6AE]">
          O mapa fala por três cores
        </p>
        <ul className="grid gap-6 sm:grid-cols-3 lg:flex lg:gap-14">
          {STATUSES.map((item, index) => (
            <li key={item.status}>
              <Reveal delay={index * 90} className="flex items-baseline gap-3">
                <StatusDot status={item.status} className="translate-y-[-1px]" />
                <span className="text-lg font-medium text-[#E8F1EC]">{item.name}</span>
                <span className="text-sm text-[#94A6AE]">{item.description}</span>
              </Reveal>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
