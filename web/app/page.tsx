import Link from "next/link";

/**
 * The front door.
 *
 * Server-rendered and static: the session lives in an httpOnly cookie on the
 * API's own hostname (D13), which this server cannot read, so there is
 * nothing for it to personalise. Signing in happens on `/login`.
 */
export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-8 px-6 py-16">
      <header className="flex flex-col gap-2">
        <p className="text-sm uppercase tracking-widest text-[var(--muted)]">
          Self-Starters House Montessori School
        </p>
        <h1 className="text-3xl font-semibold tracking-tight">Results Portal</h1>
        <p className="text-sm text-[var(--muted)]">
          Termly results for parents, and the staff tools behind them.
        </p>
      </header>

      <Link
        href="/login"
        className="inline-flex w-fit items-center rounded-md bg-[var(--accent)] px-4 py-2.5 text-sm font-medium text-white"
      >
        Sign in
      </Link>

      <footer className="text-sm text-[var(--muted)]">Built by HSD Technologies.</footer>
    </main>
  );
}
