/**
 * One child, and the terms the school has released for them (§8.5, R12).
 *
 * The middle step of §8.5's journey — "children as cards → published terms →
 * the report card" — which until the redesign was stacked under the list
 * rather than being a place you could be. It is a route now, so a parent can
 * be sent a link to one child, the back button means something, and the list
 * page costs one request.
 *
 * A term the school has not released says R12's sentence and nothing else:
 * nothing on this page distinguishes "not published yet" from "held back for
 * this child".
 */

import { CalendarX, FileText } from "lucide-react";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { Avatar, Badge, Card, EmptyState, PageHeader } from "@/components/ui";
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

export default async function ChildPage({
  params,
}: {
  params: Promise<{ pupilId: string }>;
}) {
  const { pupilId } = await params;
  const state = await sessionState();
  if (state.kind === "stale") {
    redirect(`/api/session?next=${encodeURIComponent(`/children/${pupilId}`)}`);
  }
  if (state.kind === "signed-out") redirect("/");
  const session = state.session;

  // `/my/children` is filtered to this guardian's own children by §5.2's
  // scope, so finding the child in that list *is* the authorization check —
  // an id belonging to someone else's child is simply not in it.
  const children = (await apiGet<Child[]>(session, "/my/children")) ?? [];
  const child = children.find((candidate) => candidate.pupil_id === pupilId);
  if (!child) notFound();

  const reports = await apiGet<{ terms: Availability[] }>(
    session,
    `/my/children/${pupilId}/reports`,
  );
  const terms = reports?.terms ?? [];
  const name = `${child.first_name} ${child.last_name}`;

  return (
    <>
      <PageHeader
        breadcrumbs={[
          { label: "Your children", href: "/children" },
          { label: name },
        ]}
        back={{ href: "/children", label: "Your children" }}
        title={
          <span className="flex items-center gap-2.5">
            <Avatar name={name} />
            {name}
          </span>
        }
        description={`${child.admission_number}${
          child.class_name ? ` · ${child.class_name}` : ""
        }`}
      />

      {terms.length === 0 ? (
        <EmptyState
          icon={CalendarX}
          title="No results have been released yet"
          description="The school releases a term's results once the head teacher has approved them. You will see them here."
        />
      ) : (
        <ul className="flex flex-col gap-3">
          {terms.map((term) =>
            term.available ? (
              <li key={term.term_id}>
                <Link
                  href={`/children/${pupilId}/${term.term_id}`}
                  className="flex items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3.5 shadow-sm transition hover:border-[var(--brand)] hover:bg-[var(--brand-soft)]"
                >
                  <span
                    aria-hidden
                    className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-[var(--brand-soft)] text-[var(--brand)]"
                  >
                    <FileText className="size-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">
                      {term.term_label}
                    </span>
                    <span className="block text-xs text-[var(--muted)]">
                      Report card and PDF
                    </span>
                  </span>
                  {term.acknowledged_at ? (
                    <Badge tone="good">Seen</Badge>
                  ) : (
                    <Badge tone="brand">View result</Badge>
                  )}
                </Link>
              </li>
            ) : (
              <li key={term.term_id}>
                <Card className="px-4 py-3.5">
                  <p className="text-sm font-semibold">{term.term_label}</p>
                  {/* R12, verbatim and alone. */}
                  <p className="mt-0.5 text-sm text-[var(--muted)]">{term.message}</p>
                </Card>
              </li>
            ),
          )}
        </ul>
      )}
    </>
  );
}
