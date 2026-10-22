"use client";

/**
 * The admin shell (ARCHITECTURE.md §3, §8).
 *
 * A client component, and not by preference: the session lives in an
 * httpOnly cookie on `api.<domain>` (D13), which the Next.js server cannot
 * read, so a signed-in page cannot be server-rendered as things stand. §8.5's
 * parent view needs that to be solved before milestone 12 — see
 * docs/DECISIONS.md D41.
 *
 * The nav order is the order the work has to be done in: a class cannot have
 * a teacher before the class exists, and nothing can be configured before
 * there is a session to configure it in.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { Button, Notice, Spinner } from "@/components/ui";
import { useAuth, useRequireRole } from "@/lib/auth";

const NAV = [
  { href: "/admin", label: "Setup" },
  { href: "/admin/calendar", label: "Session & terms" },
  { href: "/admin/subjects", label: "Subjects" },
  { href: "/admin/classes", label: "Classes" },
  { href: "/admin/pupils", label: "Pupils" },
  { href: "/admin/accounts", label: "Accounts" },
  { href: "/admin/assessment", label: "Grading & narrative" },
] as const;

export default function AdminLayout({ children }: { children: ReactNode }) {
  const { user, loading } = useRequireRole("admin");
  const { signOut } = useAuth();
  const pathname = usePathname();

  if (loading) {
    return (
      <main className="mx-auto max-w-5xl px-6 py-16">
        <Spinner label="Checking your session…" />
      </main>
    );
  }

  if (!user) return null; // the redirect in useRequireRole is in flight

  if (user.role !== "admin") {
    return (
      <main className="mx-auto max-w-xl px-6 py-16">
        <Notice tone="info">
          These pages are for the school administrator. Your account does not have access to
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
            <p className="truncate text-sm font-semibold">Setup</p>
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

        <nav aria-label="Setup sections" className="mx-auto max-w-6xl overflow-x-auto px-5">
          <ul className="flex gap-1 pb-2 text-sm">
            {NAV.map((item) => {
              const active =
                item.href === "/admin" ? pathname === "/admin" : pathname.startsWith(item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`inline-block whitespace-nowrap rounded-md px-3 py-1.5 ${
                      active
                        ? "bg-[var(--surface-raised)] font-medium"
                        : "text-[var(--muted)] hover:text-[var(--foreground)]"
                    }`}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </header>

      <main className="mx-auto flex max-w-6xl flex-col gap-6 px-5 py-6">{children}</main>
    </div>
  );
}
