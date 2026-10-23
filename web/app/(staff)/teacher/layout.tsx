"use client";

/**
 * The teacher shell (ARCHITECTURE.md §3, §8).
 *
 * A client component for the same reason the admin shell is: the session
 * lives in an httpOnly cookie on `api.<domain>` (D13), which the Next.js
 * server cannot read. See docs/DECISIONS.md D41.
 */

import Link from "next/link";
import type { ReactNode } from "react";

import { Button, Notice, Spinner } from "@/components/ui";
import { useAuth, useRequireRole } from "@/lib/auth";

export default function TeacherLayout({ children }: { children: ReactNode }) {
  const { user, loading } = useRequireRole("teacher");
  const { signOut } = useAuth();

  if (loading) {
    return (
      <main className="mx-auto max-w-5xl px-6 py-16">
        <Spinner label="Checking your session…" />
      </main>
    );
  }

  if (!user) return null; // the redirect in useRequireRole is in flight

  if (user.role !== "teacher") {
    return (
      <main className="mx-auto max-w-xl px-6 py-16">
        <Notice tone="info">
          These pages are for class and subject teachers. Your account does not have access to
          them.
        </Notice>
      </main>
    );
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-[var(--border)]">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-5 py-3">
          <div className="min-w-0">
            <p className="text-xs uppercase tracking-widest text-[var(--muted)]">
              Self-Starters House Montessori School
            </p>
            <Link href="/teacher" className="truncate text-sm font-semibold">
              My classes
            </Link>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="hidden truncate text-[var(--muted)] sm:inline">
              {user.full_name}
            </span>
            <Button variant="secondary" onClick={() => void signOut()}>
              Sign out
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto flex max-w-6xl flex-col gap-6 px-5 py-6">{children}</main>
    </div>
  );
}
