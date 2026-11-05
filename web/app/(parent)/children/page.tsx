/**
 * A parent's children (§8.5: "Login → children as cards → published terms →
 * the report card").
 *
 * Server-rendered. §10's seed calls out the multi-child parent as the
 * fixture that catches most bugs here, and §12's criterion says the same:
 * "multi-child parent sees both children".
 */

import Link from "next/link";
import { redirect } from "next/navigation";

import { apiGet, sessionState } from "@/lib/server/session";

interface Child {
  pupil_id: string;
  admission_number: string;
  first_name: string;
  middle_name?: string | null;
  last_name: string;
  class_name?: string | null;
}

interface Availability {
  term_id: string;
  term_label: string;
  available: boolean;
  acknowledged_at?: string | null;
  message?: string | null;
}

export default async function ChildrenPage() {
  const state = await sessionState();
  // Rendering may not write a cookie, so a stale access token bounces once
  // through the route handler that may (D89).
  if (state.kind === "stale") redirect("/api/session?next=/children");
  if (state.kind === "signed-out") redirect("/");
  const session = state.session;

  const children = (await apiGet<Child[]>(session, "/my/children")) ?? [];

  return (
    <>
      <h1 className="text-lg font-semibold">
        {children.length === 1 ? "Your child" : "Your children"}
      </h1>

      {children.length === 0 ? (
        <p className="rounded-md border border-[var(--border)] px-3 py-2 text-sm text-[var(--muted)]">
          No children are linked to this account. Please contact the school.
        </p>
      ) : null}

      {await Promise.all(
        children.map(async (child) => {
          const reports = await apiGet<{ terms: Availability[] }>(
            session,
            `/my/children/${child.pupil_id}/reports`,
          );
          const terms = reports?.terms ?? [];

          return (
            <section
              key={child.pupil_id}
              className="rounded-lg border border-[var(--border)] p-4"
            >
              <h2 className="text-base font-semibold">
                {child.first_name} {child.last_name}
              </h2>
              <p className="text-sm text-[var(--muted)]">
                {child.admission_number}
                {child.class_name ? ` · ${child.class_name}` : ""}
              </p>

              {terms.length === 0 ? (
                <p className="mt-3 text-sm text-[var(--muted)]">
                  No results have been released for this child yet.
                </p>
              ) : null}

              <ul className="mt-3 flex flex-col gap-2">
                {terms.map((term) => (
                  <li key={term.term_id}>
                    {term.available ? (
                      <Link
                        href={`/children/${child.pupil_id}/${term.term_id}`}
                        className="flex items-center justify-between rounded-md border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-raised)]"
                      >
                        <span className="font-medium">{term.term_label}</span>
                        <span className="text-xs text-[var(--muted)]">
                          {term.acknowledged_at ? "Seen" : "View result"}
                        </span>
                      </Link>
                    ) : (
                      <div className="rounded-md border border-[var(--border)] px-3 py-2 text-sm">
                        <span className="font-medium">{term.term_label}</span>
                        <br />
                        {/* R12, verbatim and alone. */}
                        <span className="text-[var(--muted)]">{term.message}</span>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          );
        }),
      )}
    </>
  );
}
