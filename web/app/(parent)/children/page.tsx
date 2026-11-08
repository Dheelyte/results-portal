/**
 * A parent's children (§8.5: "Login → children as cards → published terms →
 * the report card").
 *
 * Server-rendered. §10's seed calls out the multi-child parent as the
 * fixture that catches most bugs here, and §12's criterion says the same:
 * "multi-child parent sees both children".
 *
 * **Cards only.** This page used to list every child *and*, beneath each one,
 * that child's terms — one request per child on top of its own, all of it
 * waited for before anything painted. The terms moved to
 * `/children/[pupilId]`, which is both the route structure the rest of the
 * portal now follows and one request instead of `1 + n` on the page §8.5 is
 * strictest about.
 */

import { ChevronRight, GraduationCap } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Avatar, EmptyState, PageHeader } from "@/components/ui";
import { apiGet, sessionState } from "@/lib/server/session";

interface Child {
  pupil_id: string;
  admission_number: string;
  first_name: string;
  middle_name?: string | null;
  last_name: string;
  class_name?: string | null;
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
      <PageHeader
        title={children.length === 1 ? "Your child" : "Your children"}
        description={
          children.length > 0
            ? "Open a child to see the terms the school has released."
            : undefined
        }
      />

      {children.length === 0 ? (
        <EmptyState
          icon={GraduationCap}
          title="No children are linked to this account"
          description="Please contact the school office and they will attach your child to it."
        />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {children.map((child) => (
            <li key={child.pupil_id}>
              <Link
                href={`/children/${child.pupil_id}`}
                className="flex h-full items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-sm transition hover:border-[var(--brand)] hover:bg-[var(--brand-soft)]"
              >
                <Avatar name={`${child.first_name} ${child.last_name}`} size="lg" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-base font-semibold">
                    {child.first_name} {child.last_name}
                  </span>
                  <span className="block truncate text-sm text-[var(--muted)]">
                    {child.admission_number}
                    {child.class_name ? ` · ${child.class_name}` : ""}
                  </span>
                  <span className="mt-1 block text-sm font-medium text-[var(--brand)]">
                    View results
                  </span>
                </span>
                <ChevronRight aria-hidden className="size-5 shrink-0 text-[var(--muted)]" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
