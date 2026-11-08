"use client";

/**
 * The setup checklist (ARCHITECTURE.md §7, §12).
 *
 * The admin's answer to "can teachers start?". Every item names what is
 * outstanding and in which class, because "setup incomplete" with no list
 * generates a support call every term — the same lesson R10 draws about the
 * submission gate.
 */

import { Check, ListChecks, RefreshCw, Sparkles } from "lucide-react";
import Link from "next/link";

import {
  Badge,
  Button,
  ButtonLink,
  Field,
  Notice,
  PageHeader,
  Panel,
  Select,
  SkeletonPanel,
  SkeletonTable,
} from "@/components/ui";
import type { ChecklistItem } from "@/lib/api/admin";
import { useAdminApi } from "@/lib/api/use-admin";
import { TERM_LABELS } from "@/lib/format";
import { useResource } from "@/lib/use-async";
import { useState } from "react";

/** Where an admin goes to fix each item. */
const FIX_LINKS: Record<string, { href: string; label: string }> = {
  current_session: { href: "/admin/calendar", label: "Session & terms" },
  current_term: { href: "/admin/calendar", label: "Session & terms" },
  times_school_opened: { href: "/admin/calendar", label: "Session & terms" },
  assessment_periods: { href: "/admin/calendar", label: "Session & terms" },
  marks_obtainable: { href: "/admin/calendar", label: "Marks obtainable" },
  grading_scale: { href: "/admin/assessment", label: "Grading & narrative" },
  classes: { href: "/admin/classes", label: "Classes" },
  houses: { href: "/admin/classes", label: "Houses" },
  pupils_enrolled: { href: "/admin/pupils", label: "Pupils" },
  every_pupil_placed: { href: "/admin/pupils", label: "Pupils" },
  no_empty_classes: { href: "/admin/pupils", label: "Pupils" },
  class_subjects: { href: "/admin/classes", label: "Classes" },
  teaching_assignments: { href: "/admin/classes", label: "Classes" },
  class_teachers: { href: "/admin/classes", label: "Classes" },
  narrative_sections: { href: "/admin/assessment", label: "Grading & narrative" },
  comment_bank: { href: "/admin/assessment", label: "Phrase bank" },
  teacher_accounts: { href: "/admin/accounts", label: "Accounts" },
  parent_accounts: { href: "/admin/accounts", label: "Accounts" },
};

export default function SetupPage() {
  const api = useAdminApi();
  const [termId, setTermId] = useState<string>("");

  const terms = useResource(() => api!.terms(), [api], { enabled: Boolean(api) });
  const chosen =
    termId || terms.data?.find((term) => term.is_current)?.id || terms.data?.[0]?.id || "";

  const checklist = useResource(() => api!.checklist(chosen), [api, chosen], {
    enabled: Boolean(api && chosen),
  });

  if (!api || terms.loading) {
    return (
      <>
        <PageHeader title="Setup" />
        <SkeletonPanel rows={6} label="Loading the checklist…" />
      </>
    );
  }
  if (terms.error) return <Notice>{terms.error}</Notice>;

  if (!terms.data?.length) {
    return (
      <>
        <PageHeader title="Setup" />
        <Panel
          title="Nothing is set up yet"
          icon={Sparkles}
          description="Start by creating this academic session and its first term."
        >
          <ButtonLink href="/admin/calendar" variant="primary">
            Create the session
          </ButtonLink>
        </Panel>
      </>
    );
  }

  const blocking = checklist.data?.items.filter((item) => item.blocking) ?? [];
  const advisory = checklist.data?.items.filter((item) => !item.blocking) ?? [];
  const outstanding = blocking.filter((item) => !item.done).length;

  return (
    <>
      <PageHeader
        title="Setup"
        description="What teachers need before they can start entering scores for a term."
      />

      <Panel
        icon={ListChecks}
        title={
          checklist.data
            ? `${checklist.data.term_label}, ${checklist.data.academic_session_name}`
            : "Setup"
        }
        description={
          checklist.data?.ready
            ? "Everything teachers need is in place. They can enter scores for this term."
            : `${outstanding} ${outstanding === 1 ? "item" : "items"} still to do before teachers can start.`
        }
        actions={
          <div className="flex flex-wrap items-end gap-2">
            {checklist.data ? (
              <Badge
                tone={checklist.data.ready ? "good" : "warn"}
                icon={checklist.data.ready ? Check : undefined}
              >
                {checklist.data.ready ? "Ready" : "Not ready"}
              </Badge>
            ) : null}
            <div className="w-44">
              <Field label="Term">
                <Select
                  aria-label="Term"
                  value={chosen}
                  onChange={(event) => setTermId(event.target.value)}
                >
                  {terms.data.map((term) => (
                    <option key={term.id} value={term.id}>
                      {TERM_LABELS[term.number] ?? term.number}
                      {term.is_current ? " (current)" : ""}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <Button
              variant="secondary"
              icon={RefreshCw}
              loading={checklist.loading}
              onClick={checklist.reload}
            >
              Refresh
            </Button>
          </div>
        }
      >
        {checklist.loading ? (
          <SkeletonTable rows={6} columns={2} label="Loading the checklist…" />
        ) : (
          <>
            {checklist.error ? <Notice>{checklist.error}</Notice> : null}
            <ul className="flex flex-col gap-3">
              {blocking.map((item) => (
                <ChecklistRow key={item.key} item={item} />
              ))}
            </ul>
          </>
        )}
      </Panel>

      {advisory.length ? (
        <Panel
          icon={Sparkles}
          title="Worth doing"
          description="Real gaps, but teachers can start without them."
        >
          <ul className="flex flex-col gap-3">
            {advisory.map((item) => (
              <ChecklistRow key={item.key} item={item} />
            ))}
          </ul>
        </Panel>
      ) : null}
    </>
  );
}

function ChecklistRow({ item }: { item: ChecklistItem }) {
  const link = FIX_LINKS[item.key];
  // `outstanding` has a default on the API side, so the generated type makes
  // it optional even though a response always carries it.
  const outstanding = item.outstanding ?? [];

  return (
    <li className="flex gap-3">
      <span
        aria-hidden
        className={`mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border ${
          item.done
            ? "border-[var(--success)] bg-[var(--success-soft)] text-[var(--success)]"
            : "border-[var(--border)] text-[var(--muted)]"
        }`}
      >
        {item.done ? <Check className="size-3" /> : null}
      </span>
      <div className="min-w-0">
        <p className="text-sm font-medium">
          {item.label}
          <span className="sr-only">{item.done ? " — done" : " — outstanding"}</span>
        </p>
        <p className="text-sm text-[var(--muted)]">{item.detail}</p>
        {outstanding.length ? (
          <ul className="mt-1 flex flex-wrap gap-1.5">
            {outstanding.map((entry) => (
              <li key={entry}>
                <Badge tone="warn">{entry}</Badge>
              </li>
            ))}
          </ul>
        ) : null}
        {!item.done && link ? (
          <Link
            href={link.href}
            className="mt-1 inline-block text-sm font-medium text-[var(--brand)] hover:underline"
          >
            Go to {link.label} &rarr;
          </Link>
        ) : null}
      </div>
    </li>
  );
}
