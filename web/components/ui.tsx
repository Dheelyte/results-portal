"use client";

/**
 * The small set of pieces every admin screen is built from.
 *
 * Deliberately plain. §8 puts the design effort into the score grid and the
 * narrative screen, which teachers use for hours on a phone; the setup
 * screens are used by one administrator a few times a term, so they are
 * legible forms and tables and nothing more.
 */

import type { ReactNode } from "react";

export function Panel({
  title,
  description,
  children,
  actions,
}: {
  title: string;
  description?: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-[var(--border)] bg-[var(--surface)]">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--border)] px-5 py-4">
        <div className="min-w-0">
          <h2 className="text-base font-semibold tracking-tight">{title}</h2>
          {description ? (
            <p className="mt-1 text-sm text-[var(--muted)]">{description}</p>
          ) : null}
        </div>
        {actions}
      </header>
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}

export function Button({
  children,
  variant = "primary",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost";
}) {
  const styles = {
    primary: "bg-[var(--accent)] text-white hover:opacity-90",
    secondary:
      "border border-[var(--border)] bg-[var(--surface)] hover:bg-[var(--surface-raised)]",
    ghost: "text-[var(--accent)] hover:underline",
  }[variant];

  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${props.className ?? ""}`}
    >
      {children}
    </button>
  );
}

export function Field({
  label,
  hint,
  children,
  required,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
  required?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1.5 text-sm">
      <span className="font-medium">
        {label}
        {required ? <span className="text-[var(--danger)]"> *</span> : null}
      </span>
      {children}
      {hint ? <span className="text-xs text-[var(--muted)]">{hint}</span> : null}
    </label>
  );
}

const CONTROL =
  "w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm outline-none focus:border-[var(--accent)]";

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${CONTROL} ${props.className ?? ""}`} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`${CONTROL} ${props.className ?? ""}`} />;
}

export function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`${CONTROL} ${props.className ?? ""}`} />;
}

/**
 * The API's refusal, shown verbatim.
 *
 * The service layer writes these messages for the person who caused them —
 * "Marks obtainable must be greater than zero", not "422" — so paraphrasing
 * them in the browser would lose the useful half.
 */
export function Notice({
  tone = "error",
  children,
}: {
  tone?: "error" | "success" | "info";
  children: ReactNode;
}) {
  if (!children) return null;
  const styles = {
    error: "border-[var(--danger)] text-[var(--danger)]",
    success: "border-[var(--success)] text-[var(--success)]",
    info: "border-[var(--border)] text-[var(--muted)]",
  }[tone];

  return (
    <p role={tone === "error" ? "alert" : "status"} className={`rounded-md border px-3 py-2 text-sm ${styles}`}>
      {children}
    </p>
  );
}

export function Table({
  head,
  children,
  empty,
}: {
  head: ReactNode[];
  children: ReactNode;
  empty?: ReactNode;
}) {
  const hasRows = Array.isArray(children) ? children.length > 0 : Boolean(children);
  if (!hasRows && empty) {
    return <p className="text-sm text-[var(--muted)]">{empty}</p>;
  }

  return (
    <div className="-mx-5 overflow-x-auto px-5">
      <table className="w-full min-w-[32rem] border-collapse text-sm">
        <thead>
          <tr className="border-b border-[var(--border)] text-left">
            {head.map((cell, index) => (
              <th key={index} className="py-2 pr-4 font-medium text-[var(--muted)]">
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Row({ children }: { children: ReactNode }) {
  return <tr className="border-b border-[var(--border)] last:border-0">{children}</tr>;
}

export function Cell({ children, className }: { children: ReactNode; className?: string }) {
  return <td className={`py-2.5 pr-4 align-top ${className ?? ""}`}>{children}</td>;
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "good" | "warn" | "bad";
}) {
  const styles = {
    neutral: "border-[var(--border)] text-[var(--muted)]",
    good: "border-[var(--success)] text-[var(--success)]",
    warn: "border-[var(--warning)] text-[var(--warning)]",
    bad: "border-[var(--danger)] text-[var(--danger)]",
  }[tone];
  return (
    <span className={`inline-block rounded-full border px-2 py-0.5 text-xs ${styles}`}>
      {children}
    </span>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <p role="status" className="text-sm text-[var(--muted)]">
      {label}
    </p>
  );
}

/**
 * Shows a value an admin must copy before it is gone.
 *
 * A temporary password is returned once by the API and stored nowhere
 * readable (§5.1), so losing it means another reset. The panel says so.
 */
export function OneTimeSecret({
  value,
  onDismiss,
  children,
}: {
  value: string;
  onDismiss: () => void;
  children: ReactNode;
}) {
  return (
    <div className="rounded-md border border-[var(--warning)] px-4 py-3 text-sm">
      <p className="font-medium">{children}</p>
      <p className="mt-2 break-all rounded bg-[var(--surface-raised)] px-3 py-2 font-mono text-base">
        {value}
      </p>
      <p className="mt-2 text-xs text-[var(--muted)]">
        Shown once. Give it to them directly — they must change it before they can use the
        portal. If it is lost, reset the account again.
      </p>
      <Button variant="secondary" className="mt-3" onClick={onDismiss}>
        I have passed it on
      </Button>
    </div>
  );
}
