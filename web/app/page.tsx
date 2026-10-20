// Milestone 1 landing page.  It exists to prove the caddy -> web -> api path
// end to end; milestone 2 replaces it with the login screen of
// ARCHITECTURE.md §8.

const API_URL = process.env.INTERNAL_API_URL ?? "http://api:8000";

type ApiStatus =
  | { reachable: true; database: string }
  | { reachable: false; database: null };

async function readApiStatus(): Promise<ApiStatus> {
  try {
    // No caching: this is a health read, and a cached "ready" is a lie.
    const response = await fetch(`${API_URL}/readyz`, { cache: "no-store" });
    const body = (await response.json()) as { database?: string };
    return { reachable: true, database: body.database ?? "unknown" };
  } catch {
    return { reachable: false, database: null };
  }
}

export default async function Home() {
  const status = await readApiStatus();
  const ok = status.reachable && status.database === "ok";

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-8 px-6 py-16">
      <header className="flex flex-col gap-2">
        <p className="text-sm uppercase tracking-widest text-[var(--muted)]">
          Self-Starters House Montessori School
        </p>
        <h1 className="text-3xl font-semibold tracking-tight">Results Portal</h1>
      </header>

      <section
        aria-labelledby="status-heading"
        className="rounded-lg border border-[var(--border)] p-5"
      >
        <h2 id="status-heading" className="text-sm font-medium">
          System status
        </h2>
        <dl className="mt-4 flex flex-col gap-2 text-sm">
          <div className="flex items-center justify-between gap-4">
            <dt className="text-[var(--muted)]">Web</dt>
            <dd>Running</dd>
          </div>
          <div className="flex items-center justify-between gap-4">
            <dt className="text-[var(--muted)]">API</dt>
            <dd>{status.reachable ? "Reachable" : "Unreachable"}</dd>
          </div>
          <div className="flex items-center justify-between gap-4">
            <dt className="text-[var(--muted)]">Database</dt>
            <dd>{ok ? "Reachable" : "Unreachable"}</dd>
          </div>
        </dl>
      </section>

      <footer className="text-sm text-[var(--muted)]">
        Milestone 1 — skeleton. Built by HSD Technologies.
      </footer>
    </main>
  );
}
