"use client";

/**
 * A modal dialog, for the create forms on the admin screens (D117).
 *
 * Built on the native `<dialog>` and `showModal()`, not a library: the
 * browser already puts it in the top layer, makes the page behind it inert,
 * keeps focus inside it, returns focus to the button that opened it, and
 * closes it on Escape. Everything here is styling and the open/close wiring.
 *
 * Its own file, not `components/ui.tsx`, because it needs an effect, and
 * that file is deliberately free of client code (§8.5's parent pages import
 * it).
 *
 * **Closing never submits and never clears.** A half-typed form survives an
 * accidental Escape or a backdrop click, because the page owns the form state
 * and this only hides it.
 */

import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";

const WIDTHS = {
  md: "sm:max-w-xl",
  lg: "sm:max-w-3xl",
} as const;

export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  size?: keyof typeof WIDTHS;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);

  return (
    <dialog
      ref={dialog}
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
      // Escape fires `cancel` then `close`; either way the page's state must
      // follow, or the next click on the opener would find it already "open".
      onClose={onClose}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      // A click whose target is the dialog itself landed on the backdrop: the
      // content fills the box, so nothing inside it is the dialog element.
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      className={`portal-modal m-auto w-[calc(100%-2rem)] ${WIDTHS[size]} max-h-[calc(100dvh-2rem)] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)] p-0 text-[var(--foreground)] shadow-2xl`}
    >
      {open ? (
        <div className="flex max-h-[calc(100dvh-2rem)] flex-col">
          <header className="flex items-start justify-between gap-3 border-b border-[var(--border)] px-5 py-4">
            <div className="min-w-0">
              <h2 id={titleId} className="text-base font-semibold tracking-tight">
                {title}
              </h2>
              {description ? (
                <p id={descriptionId} className="mt-0.5 text-sm text-[var(--muted)]">
                  {description}
                </p>
              ) : null}
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="-mr-1.5 -mt-0.5 rounded-lg p-1.5 text-[var(--muted)] transition hover:bg-[var(--surface-raised)] hover:text-[var(--foreground)]"
            >
              <X aria-hidden className="size-4" />
            </button>
          </header>
          <div className="overflow-y-auto px-5 py-4">{children}</div>
        </div>
      ) : null}
    </dialog>
  );
}
