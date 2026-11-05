/**
 * The parent shell (ARCHITECTURE.md §8.5).
 *
 * A **server component**, unlike every other shell in this app. §8.5: "The
 * lightest page in the system. Server-rendered, target under 150 KB first
 * load, no client-side fetching for the report itself. Assume a 3G
 * connection on a low-end Android device."
 *
 * Nothing here is a client component, so nothing here contributes to the
 * JavaScript bundle. The only interactive controls on the parent's pages are
 * form submissions, which work without JavaScript at all.
 */

import type { ReactNode } from "react";

import { currentSession, signOut } from "@/lib/server/session";

export default async function ParentLayout({ children }: { children: ReactNode }) {
  const session = await currentSession();

  async function endSession() {
    "use server";
    const { redirect } = await import("next/navigation");
    await signOut();
    redirect("/");
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-[var(--border)]">
        <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-3 px-5 py-3">
          <div className="min-w-0">
            <p className="text-xs uppercase tracking-widest text-[var(--muted)]">
              Self-Starters House Montessori School
            </p>
            <p className="truncate text-sm font-semibold">Results</p>
          </div>
          {session ? (
            <form action={endSession}>
              <span className="mr-3 hidden text-sm text-[var(--muted)] sm:inline">
                {session.user.full_name}
              </span>
              <button
                type="submit"
                className="rounded-md border border-[var(--border)] px-3 py-1.5 text-sm"
              >
                Sign out
              </button>
            </form>
          ) : null}
        </div>
      </header>

      <main className="mx-auto flex max-w-3xl flex-col gap-6 px-5 py-6">{children}</main>
    </div>
  );
}
