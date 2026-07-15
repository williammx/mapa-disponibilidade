type Props = {
  eyebrow?: string;
  title: string;
  description?: string;
};

export function SectionHeader({ eyebrow, title, description }: Props) {
  return (
    <div className="max-w-3xl">
      {eyebrow ? <p className="mb-3 text-xs font-medium uppercase tracking-[0.22em] text-emerald-300">{eyebrow}</p> : null}
      <h1 className="text-3xl font-medium leading-tight tracking-tight text-white md:text-5xl">{title}</h1>
      {description ? <p className="mt-4 max-w-2xl text-base leading-7 text-slate-300">{description}</p> : null}
    </div>
  );
}
