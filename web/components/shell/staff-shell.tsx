"use client";

/**
 * The three staff shells, minus the three copies.
 *
 * Admin, teacher and head teacher each used to carry their own layout with
 * the same session check, the same "these pages are not for you" notice and
 * the same header rebuilt by hand. They are one component now; what differs
 * is a role, a name and a list of links.
 *
 * The role check here is **convenience, not security** — same as
 * `useRequireRole`. Every endpoint behind these screens is gated server-side
 * against §5.2's matrix; this exists so a teacher who follows an admin link
 * sees a sentence rather than a page of failed requests.
 */

import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { AppShell } from "@/components/shell/app-shell";
import type { NavSection } from "@/components/shell/nav";
import { Card, Notice, Skeleton } from "@/components/ui";
import { useAuth, useRequireRole } from "@/lib/auth";
import type { CurrentUser } from "@/lib/api/client";
import { ROLE_LABELS } from "@/lib/format";

export function StaffShell({
  role,
  alsoFor = [],
  roleLabel,
  area,
  areaHref,
  areaIcon,
  navLabel,
  sections,
  refusal,
  children,
}: {
  role: CurrentUser["role"];
  /** Other roles these pages also serve: the teaching pages serve a head
   *  teacher or an admin who has been assigned a class (D123). */
  alsoFor?: CurrentUser["role"][];
  roleLabel: string;
  area: string;
  areaHref: string;
  areaIcon: LucideIcon;
  navLabel: string;
  sections: NavSection[];
  /** What to tell someone whose account is the wrong kind for these pages. */
  refusal: string;
  children: ReactNode;
}) {
  const { user, loading } = useRequireRole(role);
  const { signOut } = useAuth();

  // The frame, drawn before the session has settled. A spinner in the middle
  // of an empty page used to be the first thing a teacher saw on every cold
  // load; this is the shape of the screen that is coming.
  if (loading) return <ShellSkeleton />;

  if (!user) return null; // the redirect in useRequireRole is in flight

  if (user.role !== role && !alsoFor.includes(user.role)) {
    return (
      <main className="mx-auto max-w-xl px-6 py-16">
        <Notice tone="info">{refusal}</Notice>
      </main>
    );
  }

  return (
    <AppShell
      navLabel={navLabel}
      sections={sections}
      area={area}
      areaHref={areaHref}
      areaIcon={areaIcon}
      user={user}
      roleLabel={user.role === role ? roleLabel : (ROLE_LABELS[user.role] ?? roleLabel)}
      onSignOut={() => void signOut()}
    >
      {children}
    </AppShell>
  );
}

function ShellSkeleton() {
  return (
    <div role="status" aria-live="polite" aria-busy="true" className="min-h-screen lg:flex">
      <span className="sr-only">Checking your session…</span>

      <div className="hidden w-64 shrink-0 border-r border-[var(--border)] bg-[var(--surface)] lg:block">
        <div className="flex items-center gap-2.5 border-b border-[var(--border)] px-3 py-4">
          <Skeleton className="size-9 rounded-lg" />
          <div className="flex flex-1 flex-col gap-1.5">
            <Skeleton className="h-3.5 w-28" />
            <Skeleton className="h-2.5 w-36" />
          </div>
        </div>
        <div className="flex flex-col gap-2 px-3 py-4">
          {Array.from({ length: 7 }, (_, index) => (
            <Skeleton key={index} className="h-8 w-full rounded-lg" />
          ))}
        </div>
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-3 border-b border-[var(--border)] bg-[var(--surface)] px-4 py-3">
          <Skeleton className="size-9 rounded-lg lg:hidden" />
          <Skeleton className="h-4 w-32" />
          <span className="flex-1" />
          <Skeleton className="size-9 rounded-full" />
        </div>
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6">
          <div className="flex flex-col gap-2">
            <Skeleton className="h-6 w-56" />
            <Skeleton className="h-3.5 w-80" />
          </div>
          <Card>
            <div className="border-b border-[var(--border)] px-5 py-4">
              <Skeleton className="h-4 w-40" />
            </div>
            <div className="flex flex-col gap-3 px-5 py-4">
              {Array.from({ length: 5 }, (_, index) => (
                <Skeleton key={index} className="h-4 w-full" />
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
