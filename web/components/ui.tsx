/**
 * The pieces every screen in the portal is built from.
 *
 * **Not a client component, deliberately.** It used to be, and that put the
 * whole kit out of reach of §8.5's parent pages, which are server-rendered
 * and must stay that way: `"use client"` here would have made a `<Badge>` on
 * a parent's card cost a JavaScript chunk. Nothing in this file uses a hook,
 * so nothing in it needs the directive — a client page importing `Button` and
 * handing it an `onClick` still works, because the *page* is the boundary.
 *
 * Anything that genuinely needs state lives elsewhere and says so:
 * `components/shell/` for the sidebar, `components/submit-button.tsx` for the
 * parent's server-action forms.
 */

import Link from "next/link";
import {
  ArrowLeft,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  Info,
  Loader2,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import { hueOf, initialsOf } from "@/lib/initials";

/* ---------------------------------------------------------------------------
   Surfaces
   --------------------------------------------------------------------------- */

export function Card({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-sm ${
        className ?? ""
      }`}
    >
      {children}
    </section>
  );
}

/**
 * A titled card.
 *
 * The signature is the one every screen built before the redesign already
 * passes — `title`, `description`, `actions`, `children` — with an optional
 * icon and footer added. Changing it would have meant touching twenty-odd
 * pages to gain nothing.
 */
export function Panel({
  title,
  description,
  children,
  actions,
  icon: Icon,
  footer,
  bare,
}: {
  title: string;
  description?: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
  icon?: LucideIcon;
  footer?: ReactNode;
  /** No inner padding — for a table or list that should meet the edges. */
  bare?: boolean;
}) {
  return (
    <Card>
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--border)] px-5 py-4">
        <div className="flex min-w-0 gap-3">
          {Icon ? (
            <span
              aria-hidden
              className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-[var(--brand-soft)] text-[var(--brand)]"
            >
              <Icon className="size-4" />
            </span>
          ) : null}
          <div className="min-w-0">
            <h2 className="text-base font-semibold tracking-tight">{title}</h2>
            {description ? (
              <p className="mt-0.5 text-sm text-[var(--muted)]">{description}</p>
            ) : null}
          </div>
        </div>
        {actions}
      </header>
      <div className={bare ? "" : "px-5 py-4"}>{children}</div>
      {footer ? (
        <footer className="border-t border-[var(--border)] bg-[var(--surface-raised)] px-5 py-3">
          {footer}
        </footer>
      ) : null}
    </Card>
  );
}

/* ---------------------------------------------------------------------------
   Page furniture
   --------------------------------------------------------------------------- */

export interface Crumb {
  label: string;
  href?: string;
}

/**
 * Where you are, and the way back up.
 *
 * The last crumb is the current page and carries no link, which is also what
 * `aria-current="page"` says to a screen reader.
 */
export function Breadcrumbs({ items }: { items: Crumb[] }) {
  if (items.length === 0) return null;
  return (
    <nav aria-label="Breadcrumb">
      <ol className="flex flex-wrap items-center gap-1 text-xs text-[var(--muted)]">
        {items.map((crumb, index) => {
          const last = index === items.length - 1;
          return (
            <li key={`${crumb.label}-${index}`} className="flex items-center gap-1">
              {index > 0 ? (
                <ChevronRight aria-hidden className="size-3 shrink-0 opacity-60" />
              ) : null}
              {crumb.href && !last ? (
                <Link href={crumb.href} className="hover:text-[var(--foreground)] hover:underline">
                  {crumb.label}
                </Link>
              ) : (
                <span aria-current={last ? "page" : undefined} className={last ? "text-[var(--foreground)]" : ""}>
                  {crumb.label}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export function BackLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--surface)] px-2.5 py-1.5 text-sm text-[var(--muted)] transition hover:bg-[var(--surface-raised)] hover:text-[var(--foreground)]"
    >
      <ArrowLeft aria-hidden className="size-4" />
      {label}
    </Link>
  );
}

/**
 * The top of a page: breadcrumbs, a back button, the title, and whatever
 * acts on the whole page.
 *
 * `back` is given even though the browser has a back button of its own,
 * because §8.1 and §8.5 both assume a phone — where the browser's is a
 * gesture or a system bar, and the one thing a teacher holding thirty sheets
 * should not have to find.
 */
export function PageHeader({
  title,
  description,
  breadcrumbs,
  back,
  actions,
  badge,
}: {
  title: ReactNode;
  description?: ReactNode;
  breadcrumbs?: Crumb[];
  back?: { href: string; label: string };
  actions?: ReactNode;
  badge?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3">
      {breadcrumbs?.length ? <Breadcrumbs items={breadcrumbs} /> : null}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-2">
          {back ? (
            <div>
              <BackLink href={back.href} label={back.label} />
            </div>
          ) : null}
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
              {badge}
            </div>
            {description ? (
              <p className="mt-1 text-sm text-[var(--muted)]">{description}</p>
            ) : null}
          </div>
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Controls
   --------------------------------------------------------------------------- */

const BUTTON_VARIANTS = {
  primary:
    "bg-[var(--brand)] text-[var(--brand-contrast)] hover:bg-[var(--brand-strong)] shadow-sm",
  secondary:
    "border border-[var(--border)] bg-[var(--surface)] hover:bg-[var(--surface-raised)]",
  ghost: "text-[var(--brand)] hover:bg-[var(--brand-soft)]",
  danger: "border border-[var(--danger)] text-[var(--danger)] hover:bg-[var(--danger-soft)]",
} as const;

const BUTTON_SIZES = {
  sm: "px-2.5 py-1.5 text-xs",
  md: "px-3.5 py-2 text-sm",
} as const;

/**
 * A button that says when it is working.
 *
 * `loading` disables it, marks it `aria-busy` and swaps the leading icon for
 * a spinner **without changing the label** — a label that changes to
 * "Saving…" moves the button under the finger that is still on it, and makes
 * every test that finds the button by its name race the request.
 */
export function Button({
  children,
  variant = "primary",
  size = "md",
  loading = false,
  icon: Icon,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof BUTTON_VARIANTS;
  size?: keyof typeof BUTTON_SIZES;
  loading?: boolean;
  icon?: LucideIcon;
}) {
  return (
    <button
      {...props}
      disabled={props.disabled || loading}
      aria-busy={loading || undefined}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${
        BUTTON_VARIANTS[variant]
      } ${BUTTON_SIZES[size]} ${props.className ?? ""}`}
    >
      {loading ? (
        <Loader2 aria-hidden className="spin size-4 shrink-0" />
      ) : Icon ? (
        <Icon aria-hidden className="size-4 shrink-0" />
      ) : null}
      {children}
    </button>
  );
}

/** A link styled as a button, for a navigation that looks like an action. */
export function ButtonLink({
  href,
  children,
  variant = "secondary",
  size = "md",
  icon: Icon,
  className,
}: {
  href: string;
  children: ReactNode;
  variant?: keyof typeof BUTTON_VARIANTS;
  size?: keyof typeof BUTTON_SIZES;
  icon?: LucideIcon;
  className?: string;
}) {
  return (
    <Link
      href={href}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition ${
        BUTTON_VARIANTS[variant]
      } ${BUTTON_SIZES[size]} ${className ?? ""}`}
    >
      {Icon ? <Icon aria-hidden className="size-4 shrink-0" /> : null}
      {children}
    </Link>
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
  "w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm outline-none transition focus:border-[var(--brand)]";

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${CONTROL} ${props.className ?? ""}`} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`${CONTROL} ${props.className ?? ""}`} />;
}

export function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`${CONTROL} ${props.className ?? ""}`} />;
}

/* ---------------------------------------------------------------------------
   Messages
   --------------------------------------------------------------------------- */

const NOTICE_TONES = {
  error: {
    className: "border-[var(--danger)] bg-[var(--danger-soft)] text-[var(--danger)]",
    icon: CircleAlert,
  },
  success: {
    className: "border-[var(--success)] bg-[var(--success-soft)] text-[var(--success)]",
    icon: CircleCheck,
  },
  warning: {
    className: "border-[var(--warning)] bg-[var(--warning-soft)] text-[var(--warning)]",
    icon: TriangleAlert,
  },
  info: {
    className: "border-[var(--border)] bg-[var(--surface-raised)] text-[var(--muted)]",
    icon: Info,
  },
} as const;

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
  tone?: keyof typeof NOTICE_TONES;
  children: ReactNode;
}) {
  if (!children) return null;
  const { className, icon: Icon } = NOTICE_TONES[tone];

  // A div rather than a paragraph: a notice may carry its own buttons — the
  // draft-recovery one in the score grid does — and a <p> may not contain
  // them.
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-sm ${className}`}
    >
      <Icon aria-hidden className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

// Solid borders rather than opacity modifiers: Tailwind v4 compiles
// `border-[var(--x)]/40` to `color-mix()`, which an older WebView drops —
// and a badge with no border is a badge with no edge against its card.
const BADGE_TONES = {
  neutral: "border-[var(--border)] bg-[var(--surface-raised)] text-[var(--muted)]",
  good: "border-[var(--success)] bg-[var(--success-soft)] text-[var(--success)]",
  warn: "border-[var(--warning)] bg-[var(--warning-soft)] text-[var(--warning)]",
  bad: "border-[var(--danger)] bg-[var(--danger-soft)] text-[var(--danger)]",
  brand: "border-[var(--brand)] bg-[var(--brand-soft)] text-[var(--brand)]",
  gold: "border-[var(--gold)] bg-[var(--gold-soft)] text-[var(--gold)]",
} as const;

export function Badge({
  children,
  tone = "neutral",
  icon: Icon,
}: {
  children: ReactNode;
  tone?: keyof typeof BADGE_TONES;
  icon?: LucideIcon;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium ${BADGE_TONES[tone]}`}
    >
      {Icon ? <Icon aria-hidden className="size-3" /> : null}
      {children}
    </span>
  );
}

/* ---------------------------------------------------------------------------
   Stat cards
   --------------------------------------------------------------------------- */

const STAT_TONES = {
  brand: {
    card: "border-[var(--brand)] bg-[var(--brand-soft)]",
    chip: "bg-[var(--brand)] text-[var(--brand-contrast)]",
  },
  good: {
    card: "border-[var(--success)] bg-[var(--success-soft)]",
    chip: "bg-[var(--success)] text-[var(--surface)]",
  },
  warn: {
    card: "border-[var(--warning)] bg-[var(--warning-soft)]",
    chip: "bg-[var(--warning)] text-[var(--surface)]",
  },
  bad: {
    card: "border-[var(--danger)] bg-[var(--danger-soft)]",
    chip: "bg-[var(--danger)] text-[var(--surface)]",
  },
  gold: {
    card: "border-[var(--gold)] bg-[var(--gold-soft)]",
    chip: "bg-[var(--gold)] text-[var(--surface)]",
  },
  neutral: {
    card: "border-[var(--border)] bg-[var(--surface-raised)]",
    chip: "bg-[var(--muted)] text-[var(--surface)]",
  },
} as const;

/**
 * One headline number (§7, §8.4).
 *
 * A stat tile, not a one-bar chart: a handful of current values read at a
 * glance is what this form is for. Three rules it follows that are easy to
 * get wrong, and all three come from the project's data-visualisation
 * guidance:
 *
 * - **The icon is not optional.** These tiles are coloured by *state* —
 *   ready, outstanding, waiting — and a status colour must always carry an
 *   icon and a label beside it, never stand alone. Colour-blind readers, a
 *   greyscale print and `forced-colors` all lose the hue; none of them loses
 *   the icon or the word.
 * - **The text wears text tokens, never the tone.** The value is
 *   `--foreground` and the label `--muted` on every tile, measured at 4.5:1
 *   or better against all six tints in both themes. The coloured chip beside
 *   them carries the meaning; tinting the words as well would spend
 *   contrast to repeat it.
 * - **No `tabular-nums` on the value.** Tabular figures give every digit the
 *   width of a zero, which at display size makes a number like 121 look
 *   loose and gappy. Tabular belongs in columns that must align — the score
 *   grid and the tables — not here.
 *
 * `tone` is chosen by what the number *means*, not by what it is: a plain
 * count is `brand`, and `good`/`warn`/`bad` are reserved for an actual state,
 * so a green tile always means something is finished.
 */
export function StatCard({
  label,
  value,
  hint,
  tone = "brand",
  icon: Icon,
  href,
}: {
  /** Sentence case, no trailing colon. */
  label: string;
  value: ReactNode;
  /** One short line of context beneath the value. */
  hint?: ReactNode;
  tone?: keyof typeof STAT_TONES;
  icon: LucideIcon;
  /** Where this number is managed, if anywhere. */
  href?: string;
}) {
  const { card, chip } = STAT_TONES[tone];

  const body = (
    <>
      <span className="flex items-start justify-between gap-3">
        <span
          aria-hidden
          className={`flex size-9 shrink-0 items-center justify-center rounded-lg ${chip}`}
        >
          <Icon className="size-[1.1rem]" />
        </span>
        {href ? (
          <ChevronRight aria-hidden className="size-4 shrink-0 text-[var(--muted)]" />
        ) : null}
      </span>

      <span className="mt-3 block text-[1.75rem] font-semibold leading-none tracking-tight text-[var(--foreground)]">
        {value}
      </span>
      <span className="mt-1.5 block text-sm font-medium text-[var(--foreground)]">{label}</span>
      {hint ? (
        <span className="mt-0.5 block text-xs text-[var(--muted)]">{hint}</span>
      ) : null}
    </>
  );

  const shell = `flex flex-col rounded-xl border p-4 ${card}`;

  if (!href) {
    return <div className={shell}>{body}</div>;
  }

  return (
    <Link href={href} className={`${shell} transition hover:brightness-[0.97]`}>
      {body}
    </Link>
  );
}

/** A row of stat cards. Wraps to two columns on a phone, never one. */
export function StatRow({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{children}</div>;
}

/* ---------------------------------------------------------------------------
   Tables
   --------------------------------------------------------------------------- */

export function Table({
  head,
  children,
  empty,
}: {
  head: ReactNode[];
  children: ReactNode;
  empty?: ReactNode;
}) {
  const hasRows = Array.isArray(children) ? children.flat().some(Boolean) : Boolean(children);
  if (!hasRows && empty) {
    return <p className="py-2 text-sm text-[var(--muted)]">{empty}</p>;
  }

  return (
    <div className="-mx-5 overflow-x-auto px-5">
      <table className="w-full min-w-[32rem] border-collapse text-sm">
        <thead>
          <tr className="border-b border-[var(--border)] text-left">
            {head.map((cell, index) => (
              <th
                key={index}
                className="whitespace-nowrap py-2 pr-4 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]"
              >
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
  return (
    <tr className="border-b border-[var(--border)] transition last:border-0 hover:bg-[var(--surface-raised)]">
      {children}
    </tr>
  );
}

export function Cell({ children, className }: { children: ReactNode; className?: string }) {
  return <td className={`py-2.5 pr-4 align-middle ${className ?? ""}`}>{children}</td>;
}

/* ---------------------------------------------------------------------------
   Waiting
   --------------------------------------------------------------------------- */

/** One grey block. Sized by the caller, because only the caller knows. */
export function Skeleton({ className }: { className?: string }) {
  return <span aria-hidden className={`skeleton block ${className ?? "h-4 w-full"}`} />;
}

/**
 * A screen that is still arriving.
 *
 * `role="status"` with an accessible label, so the wait is announced once
 * rather than being thirty nameless grey rectangles.
 */
export function Loading({
  label = "Loading…",
  children,
}: {
  label?: string;
  children: ReactNode;
}) {
  return (
    <div role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">{label}</span>
      {children}
    </div>
  );
}

export function SkeletonText({ lines = 3 }: { lines?: number }) {
  return (
    <div className="flex flex-col gap-2">
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton
          key={index}
          className={index === lines - 1 ? "h-3.5 w-2/3" : "h-3.5 w-full"}
        />
      ))}
    </div>
  );
}

export function SkeletonTable({
  rows = 6,
  columns = 4,
  label = "Loading…",
}: {
  rows?: number;
  columns?: number;
  label?: string;
}) {
  return (
    <Loading label={label}>
      <div className="flex flex-col gap-3">
        <div className="flex gap-4 border-b border-[var(--border)] pb-2">
          {Array.from({ length: columns }, (_, index) => (
            <Skeleton key={index} className="h-3 flex-1" />
          ))}
        </div>
        {Array.from({ length: rows }, (_, row) => (
          <div key={row} className="flex items-center gap-4">
            {Array.from({ length: columns }, (_, column) => (
              <Skeleton
                key={column}
                className={column === 0 ? "h-4 flex-[1.6]" : "h-4 flex-1"}
              />
            ))}
          </div>
        ))}
      </div>
    </Loading>
  );
}

export function SkeletonCards({
  count = 3,
  label = "Loading…",
}: {
  count?: number;
  label?: string;
}) {
  return (
    <Loading label={label}>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: count }, (_, index) => (
          <div
            key={index}
            className="flex flex-col gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4"
          >
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-3 w-3/4" />
            <Skeleton className="h-6 w-20 rounded-full" />
          </div>
        ))}
      </div>
    </Loading>
  );
}

/** A titled card whose contents have not arrived. */
export function SkeletonPanel({
  rows = 4,
  label = "Loading…",
}: {
  rows?: number;
  label?: string;
}) {
  return (
    <Loading label={label}>
      <Card>
        <div className="flex flex-col gap-2 border-b border-[var(--border)] px-5 py-4">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-3 w-64" />
        </div>
        <div className="flex flex-col gap-3 px-5 py-4">
          {Array.from({ length: rows }, (_, index) => (
            <Skeleton key={index} className="h-4 w-full" />
          ))}
        </div>
      </Card>
    </Loading>
  );
}

/** A whole page: a header, then a panel. The shape of most of this app. */
export function SkeletonPage({ label = "Loading…" }: { label?: string }) {
  return (
    <Loading label={label}>
      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-2">
          <Skeleton className="h-3 w-32" />
          <Skeleton className="h-6 w-56" />
          <Skeleton className="h-3.5 w-72" />
        </div>
        <Card>
          <div className="flex flex-col gap-2 border-b border-[var(--border)] px-5 py-4">
            <Skeleton className="h-4 w-40" />
          </div>
          <div className="flex flex-col gap-3 px-5 py-4">
            {Array.from({ length: 5 }, (_, index) => (
              <Skeleton key={index} className="h-4 w-full" />
            ))}
          </div>
        </Card>
      </div>
    </Loading>
  );
}

/**
 * The old spinner, kept because a few places genuinely do not know the shape
 * of what is coming — a blob being fetched, a session being checked.
 */
export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <p
      role="status"
      aria-live="polite"
      className="flex items-center gap-2 text-sm text-[var(--muted)]"
    >
      <Loader2 aria-hidden className="spin size-4" />
      {label}
    </p>
  );
}

/* ---------------------------------------------------------------------------
   Nothing here
   --------------------------------------------------------------------------- */

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon?: LucideIcon;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-[var(--border)] px-6 py-10 text-center">
      {Icon ? (
        <span
          aria-hidden
          className="flex size-10 items-center justify-center rounded-full bg-[var(--surface-raised)] text-[var(--muted)]"
        >
          <Icon className="size-5" />
        </span>
      ) : null}
      <p className="text-sm font-medium">{title}</p>
      {description ? (
        <p className="max-w-sm text-sm text-[var(--muted)]">{description}</p>
      ) : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

/* ---------------------------------------------------------------------------
   People
   --------------------------------------------------------------------------- */

/**
 * Initials in a circle.
 *
 * Initials rather than a photograph: §4 stores no pupil or staff image, and
 * §5 would make one a new category of personal data to look after for no
 * gain. The tint is derived from the name so the same person is the same
 * colour on every screen.
 */
export function Avatar({
  name,
  size = "md",
}: {
  name: string;
  size?: "sm" | "md" | "lg";
}) {
  const dimensions = { sm: "size-7 text-[0.65rem]", md: "size-9 text-xs", lg: "size-12 text-sm" }[
    size
  ];
  const hue = hueOf(name);

  return (
    <span
      aria-hidden
      className={`flex shrink-0 items-center justify-center rounded-full font-semibold ${dimensions}`}
      // `hsl`, not `oklch`: §8.5 assumes a low-end Android device, and an
      // older WebView drops a colour function it does not know — which here
      // would mean initials with no disc behind them.
      style={{
        backgroundColor: `hsl(${hue} 52% 88%)`,
        color: `hsl(${hue} 55% 28%)`,
      }}
    >
      {initialsOf(name)}
    </span>
  );
}

/**
 * The school's mark.
 *
 * Its initials, set in the brand navy. The school supplied no logo file, and
 * inventing a crest for a real school would be worse than a monogram — when
 * one arrives this is the single place it replaces.
 */
export function Crest({ size = "md" }: { size?: "md" | "lg" }) {
  const dimensions = size === "lg" ? "size-12 text-lg rounded-xl" : "size-9 text-sm rounded-lg";
  return (
    <span
      aria-hidden
      className={`flex shrink-0 items-center justify-center bg-[var(--brand)] font-bold text-[var(--brand-contrast)] ${dimensions}`}
    >
      SH
    </span>
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
    <div className="rounded-xl border border-[var(--warning)] bg-[var(--warning-soft)] px-4 py-3 text-sm">
      <p className="font-medium">{children}</p>
      <p className="mt-2 break-all rounded-lg bg-[var(--surface)] px-3 py-2 font-mono text-base">
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
