import type { ReactNode } from "react";

export default function AuthLayout({ children }: { children: ReactNode }) {
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
