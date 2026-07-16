type BrandLogoProps = {
  compact?: boolean;
  className?: string;
  inverse?: boolean;
};

export function BrandLogo({ compact = false, className = "", inverse = false }: BrandLogoProps) {
  return (
    <span className={`inline-flex items-center gap-3 ${className}`.trim()} aria-label="NexoLote">
      <svg
        aria-hidden="true"
        className="size-9 shrink-0"
        viewBox="0 0 36 36"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path d="M3 8.25 11 4v19.5L3 28V8.25Z" fill="#34D399" />
        <path d="m11 4 22 20.25L25 32 11 18.75V4Z" fill="#10B981" />
        <path d="m25 8.25 8-4.25v20.25L25 32V8.25Z" fill="#6EE7B7" />
        <path d="M11 18.75 25 32v-7.75L11 11.25v7.5Z" fill="#059669" />
      </svg>
      {!compact ? (
        <span className={`text-[19px] font-medium tracking-[0] ${inverse ? "text-white" : "text-[#101817]"}`}>
          Nexo<span className="text-emerald-400">Lote</span>
        </span>
      ) : null}
    </span>
  );
}
