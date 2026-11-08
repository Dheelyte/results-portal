"use client";

/**
 * Publication, step one: which class and which term (§6 R12, §7).
 *
 * The class's own publication state, its pupils and the publish button are
 * `/admin/publish/[classId]` (docs/DECISIONS.md D104). They used to appear
 * beneath these two selects, which meant publishing — the one irreversible
 * thing on the admin's screens — happened at a URL that said nothing about
 * what was about to be published.
 *
 * This page deliberately does **not** label each class with its state. That
 * would be one `GET /classes/{id}/publication` per class on every load, a
 * request each for a word, and the state is the first thing the next page
 * says.
 */

import { ChevronRight, Send } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  Badge,
  EmptyState,
  Field,
  Notice,
  PageHeader,
  Panel,
  Select,
  SkeletonCards,
} from "@/components/ui";
import { useAdminApi } from "@/lib/api/use-admin";
import { TERM_LABELS } from "@/lib/format";
import { useResource } from "@/lib/use-async";

export default function PublishPage() {
  const api = useAdminApi();
  const classes = useResource(() => api!.classes(), [api], { enabled: Boolean(api) });
  const terms = useResource(() => api!.terms(), [api], { enabled: Boolean(api) });

  const [termId, setTermId] = useState("");

  // The current term, once the list arrives, unless the admin has chosen.
  useEffect(() => {
    if (termId) return;
    const current = terms.data?.find((term) => term.is_current) ?? terms.data?.[0];
    if (current) setTermId(current.id);
  }, [terms.data, termId]);

  const loading = !api || classes.loading || terms.loading;

  return (
    <>
      <PageHeader
        title="Publish results"
        description="A class is published once the head teacher has approved it. Individual pupils can be held back and released later."
      />

      <Panel
        title="Which term"
        icon={Send}
        actions={
          <div className="w-56">
            <Field label="Term">
              <Select
                value={termId}
                disabled={loading}
                onChange={(event) => setTermId(event.target.value)}
              >
                {(terms.data ?? []).map((term) => (
                  <option key={term.id} value={term.id}>
                    {TERM_LABELS[term.number] ?? term.number}
                    {term.is_current ? " (current)" : ""}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
        }
      >
        {loading ? (
          <SkeletonCards count={6} label="Loading the classes…" />
        ) : (
          <>
            {classes.error ? <Notice>{classes.error}</Notice> : null}
            {terms.error ? <Notice>{terms.error}</Notice> : null}

            {(classes.data ?? []).length === 0 ? (
              <EmptyState
                title="No classes yet"
                description="There is nothing to publish until the school has classes with pupils in them."
              />
            ) : (
              <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {(classes.data ?? []).map((klass) => (
                  <li key={klass.id}>
                    <Link
                      href={`/admin/publish/${klass.id}?term=${termId}`}
                      className="flex h-full items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3.5 transition hover:border-[var(--brand)] hover:bg-[var(--brand-soft)]"
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold">
                          {klass.name}
                        </span>
                        <span className="block text-xs text-[var(--muted)]">
                          Open to publish or hold back
                        </span>
                      </span>
                      <ChevronRight
                        aria-hidden
                        className="size-4 shrink-0 text-[var(--muted)]"
                      />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </Panel>

      <p className="text-sm text-[var(--muted)]">
        <Badge tone="warn">Note</Badge> Publishing takes a database dump first (§11), so it
        is slower than it looks. A class that has not been approved cannot be published at
        all.
      </p>
    </>
  );
}
