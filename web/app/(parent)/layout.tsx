/**
 * The parent shell (ARCHITECTURE.md §8.5).
 *
 * A **server component**, unlike every other shell in this app. §8.5: "The
 * lightest page in the system. Server-rendered, target under 150 KB first
 * load, no client-side fetching for the report itself. Assume a 3G
 * connection on a low-end Android device."
 *
 * **Why there is no sidebar here.** The staff screens got one in the
 * redesign; this did not, and that is a decision rather than an omission
 * (docs/DECISIONS.md D103). A collapsible sidebar is client state, and §8.5's
 * budget is the one hard number in §8 — it would buy a drawer for a journey
 * three screens long (children → child → card) that breadcrumbs and a back
 * button cover without a byte of JavaScript. The palette, the cards, the
 * badges and the header are the same as the staff shell's, so it is the same
 * portal; it is only the navigation that is sized to the journey.
 *
 * The one client component on these pages is `SubmitButton`, and its own file
 * says why.
 */

import Link from "next/link";
import { LogOut } from "lucide-react";
import type { ReactNode } from "react";

import { SubmitButton } from "@/components/submit-button";
import { Avatar, Crest } from "@/components/ui";
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
      <header className="sticky top-0 z-30 border-b border-[var(--border)] bg-[var(--surface)]">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-3 px-4 py-2.5">
          <Link href="/children" className="flex min-w-0 items-center gap-2.5">
            <Crest />
            <span className="min-w-0">
              <span className="block truncate text-sm font-semibold leading-tight">
                Results Portal
              </span>
              <span className="block truncate text-[0.7rem] text-[var(--muted)]">
                Self-Starters House Montessori School
              </span>
            </span>
          </Link>

          {session ? (
            <div className="flex items-center gap-2">
              <span className="hidden min-w-0 text-right sm:block">
                <span className="block truncate text-sm font-medium leading-tight">
                  {session.user.full_name}
                </span>
                <span className="block text-xs text-[var(--muted)]">Parent</span>
              </span>
              <Avatar name={session.user.full_name} />
              <form action={endSession}>
                <SubmitButton
                  variant="secondary"
                  size="sm"
                  icon={<LogOut aria-hidden className="size-4 shrink-0" />}
                >
                  <span className="hidden sm:inline">Sign out</span>
                  <span className="sr-only sm:hidden">Sign out</span>
                </SubmitButton>
              </form>
            </div>
          ) : null}
        </div>
      </header>

      <main className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6">{children}</main>
    </div>
  );
}
