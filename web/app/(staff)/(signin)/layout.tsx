/**
 * The staff sign-in and change-password screens (ARCHITECTURE.md §3, §5.1).
 *
 * **Inside `(staff)`, deliberately.** These used to live in their own
 * `(auth)` group with an `AuthProvider` of their own, and that was a bug:
 * signing in at `/login` and arriving at `/admin` crossed a route-group
 * boundary, so React unmounted one provider and mounted another — and the
 * access token lives in memory (D41), so it was dropped on the very first
 * hop. In production the refresh cookie covered it up; in development, where
 * `localhost` and `api.localhost` are cross-*site*, nothing did. The E2E
 * journey found it (docs/DECISIONS.md D100).
 *
 * Now one provider spans the sign-in and everything it leads to, and the
 * parent's server-rendered pages still carry none of it.
 *
 * Not a client component: it has no state of its own. The provider is in
 * `(staff)/layout.tsx`, one level up.
 */

import type { ReactNode } from "react";

export default function SignInLayout({ children }: { children: ReactNode }) {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center gap-6 px-6 py-12">
      <header className="flex flex-col gap-1">
        <p className="text-xs uppercase tracking-widest text-[var(--muted)]">
          Self-Starters House Montessori School
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">Results Portal</h1>
      </header>
      {children}
    </main>
  );
}
