"use client";

/**
 * The sign-in and change-password screens.
 *
 * Carries `AuthProvider`, which used to sit in the root layout — it moved
 * down so the parent's server-rendered pages do not ship it (§8.5's 150 KB,
 * docs/DECISIONS.md D89). These two screens need it: both call `useAuth`.
 */

import type { ReactNode } from "react";

import { AuthProvider } from "@/lib/auth";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <main className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center gap-6 px-6 py-12">
        <header className="flex flex-col gap-1">
          <p className="text-xs uppercase tracking-widest text-[var(--muted)]">
            Self-Starters House Montessori School
          </p>
          <h1 className="text-2xl font-semibold tracking-tight">Results Portal</h1>
        </header>
        {children}
      </main>
    </AuthProvider>
  );
}
