import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";

type Props = {
  title: string;
  description: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  busy?: boolean;
  busyLabel?: string;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
};

export function ConfirmDialog({
  title,
  description,
  confirmLabel,
  cancelLabel = "Cancelar",
  busy = false,
  busyLabel,
  error = null,
  onConfirm,
  onCancel,
}: Props) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  // O handler chega como funcao nova a cada render do pai; guardar em ref
  // mantem o efeito de teclado montado uma unica vez, sem roubar o foco de
  // volta para Cancelar a cada re-render.
  const cancelHandler = useRef(onCancel);

  useEffect(() => {
    cancelHandler.current = onCancel;
  });

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    // O foco comeca na acao segura: confirmar e destrutivo e nao pode ser
    // disparado por um Enter apressado logo depois de abrir.
    cancelRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        cancelHandler.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = dialogRef.current?.querySelectorAll<HTMLElement>("button:not([disabled])");
      if (!focusable || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
      // So devolve o foco se o gatilho continuar na pagina: confirmar uma acao
      // destrutiva costuma remover o proprio botao, e focar um no solto joga o
      // foco para o body, atropelando quem for reposiciona-lo depois.
      if (opener?.isConnected) opener.focus();
    };
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onCancel();
      }}
    >
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        className="w-full max-w-md rounded-[8px] border border-white/12 bg-[#10191f] p-6 shadow-[0_30px_90px_-40px_rgba(0,0,0,0.9)]"
      >
        <h2 id={titleId} className="text-xl font-medium text-white">
          {title}
        </h2>
        <div id={descriptionId} className="mt-3 text-sm leading-6 text-slate-300">
          {description}
        </div>
        {/* A falha precisa aparecer aqui dentro: o overlay esconde qualquer
            aviso que ficasse na pagina atras do dialogo. */}
        {error ? (
          <p role="alert" className="mt-4 rounded-[8px] border border-orange-300/25 bg-orange-300/8 p-3 text-sm text-orange-100">
            {error}
          </p>
        ) : null}
        <div className="mt-6 flex flex-wrap justify-end gap-3">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded-[8px] border border-white/12 px-4 py-3 text-sm font-medium text-slate-100 transition hover:bg-white/8 focus-visible:ring-2 focus-visible:ring-emerald-300 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="rounded-[8px] bg-orange-300 px-4 py-3 text-sm font-medium text-slate-950 transition hover:bg-orange-200 focus-visible:ring-2 focus-visible:ring-emerald-300 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {busy ? busyLabel ?? "Processando..." : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
