"use client";

/**
 * The setup checklist (ARCHITECTURE.md §7, §12).
 *
 * The admin's answer to "can teachers start?". Every item names what is
 * outstanding and in which class, because "setup incomplete" with no list
 * generates a support call every term — the same lesson R10 draws about the
 * submission gate.
 */

import {
  Check,
  CircleAlert,
  GraduationCap,
  Inbox,
  Layers,
  ListChecks,
  RefreshCw,
  Sparkles,
  Users,
  X,
} from "lucide-react";
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
  Skeleton,
  SkeletonPanel,
  SkeletonTable,
  StatCard,
  StatRow,
} from "@/components/ui";
import type { ChecklistItem } from "@/lib/api/admin";
import { useAdminApi } from "@/lib/api/use-admin";
import { pupilName, TERM_LABELS } from "@/lib/format";
import { useAction, useResource } from "@/lib/use-async";
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

  // The headline numbers. `limit: 1` because only `total` is wanted — the
  // roll itself is `/admin/pupils`, and asking for five hundred rows to
  // print one number would be the wrong trade on the screen an admin opens
  // first.
  const roll = useResource(() => api!.pupils({ limit: 1 }), [api], {
    enabled: Boolean(api),
  });
  const classes = useResource(() => api!.classes(), [api], { enabled: Boolean(api) });
  const accounts = useResource(() => api!.users(), [api], { enabled: Boolean(api) });

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

  const pupilCount = roll.data?.total ?? null;
  const classCount = classes.data?.length ?? null;
  const staff = (accounts.data ?? []).filter(
    (account) => account.role !== "parent" && account.is_active,
  );
  const parents = (accounts.data ?? []).filter(
    (account) => account.role === "parent" && account.is_active,
  );
  const statsLoading = roll.loading || classes.loading || accounts.loading;

  return (
    <>
      <PageHeader
        title="Setup"
        description="What teachers need before they can start entering scores for a term."
      />

      {statsLoading ? (
        <StatRow>
          {Array.from({ length: 4 }, (_, index) => (
            <Skeleton key={index} className="h-[8.5rem] rounded-xl" />
          ))}
        </StatRow>
      ) : (
        <StatRow>
          {/* Readiness is the only one of the four that is a *state*, so it
              is the only one allowed a status colour — green when teachers
              can start, amber with the count when they cannot. The other
              three are plain counts and wear the brand hue, which is what
              keeps a green tile on this screen meaning one thing. */}
          <StatCard
            tone={outstanding === 0 ? "good" : "warn"}
            icon={outstanding === 0 ? Check : CircleAlert}
            value={outstanding === 0 ? "Ready" : outstanding}
            label={outstanding === 0 ? "Teachers can start" : "Still to do"}
            hint={
              outstanding === 0
                ? checklist.data?.term_label ?? undefined
                : `${outstanding === 1 ? "item" : "items"} blocking this term`
            }
          />
          <StatCard
            icon={GraduationCap}
            value={pupilCount ?? "—"}
            label="Pupils on the roll"
            hint="Active enrolments"
            href="/admin/pupils"
          />
          <StatCard
            icon={Layers}
            value={classCount ?? "—"}
            label={classCount === 1 ? "Class" : "Classes"}
            hint="Taking results this session"
            href="/admin/classes"
          />
          <StatCard
            icon={Users}
            value={staff.length}
            label="Staff accounts"
            hint={`${parents.length} parent ${parents.length === 1 ? "account" : "accounts"}`}
            href="/admin/accounts"
          />
        </StatRow>
      )}

      <Approvals />

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


/**
 * What is waiting for the admin (D125, D126): parents who signed themselves
 * up, and pupils a class teacher added. Hidden when there is nothing, so the
 * dashboard isn't one panel longer every day for no reason.
 */
function Approvals() {
  const api = useAdminApi()!;
  const parents = useResource(() => api.pendingUsers(), [api]);
  const pupils = useResource(() => api.pupils({ pending: true, limit: 50 }), [api]);
  const action = useAction(() => {
    parents.reload();
    pupils.reload();
  });
  const [working, setWorking] = useState<string | null>(null);

  const waitingParents = parents.data ?? [];
  const waitingPupils = pupils.data?.items ?? [];
  if (!waitingParents.length && !waitingPupils.length && !action.success) return null;

  const act = async (key: string, task: () => Promise<unknown>, message: string) => {
    setWorking(key);
    await action.run(task, message);
    setWorking(null);
  };

  return (
    <Panel
      icon={Inbox}
      title="Waiting for your approval"
      description="Nobody here can sign in, or appears on a class list, until you approve them."
    >
      <div className="flex flex-col gap-4">
        <Notice>{action.error}</Notice>
        <Notice tone="success">{action.success}</Notice>

        {waitingParents.length ? (
          <section className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold">Parents who asked for an account</h3>
            {waitingParents.map((account) => (
              <div
                key={account.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
              >
                <span>
                  <span className="font-medium">{account.full_name}</span>
                  <span className="block text-[var(--muted)]">
                    {[account.phone, account.email].filter(Boolean).join(" · ")}
                  </span>
                </span>
                <span className="flex gap-1.5">
                  <Button
                    size="sm"
                    icon={Check}
                    loading={working === `approve-${account.id}`}
                    disabled={working !== null}
                    onClick={() =>
                      void act(
                        `approve-${account.id}`,
                        () => api.approveUser(account.id),
                        `${account.full_name} approved. Link their children from Accounts → Children.`,
                      )
                    }
                  >
                    Approve
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost-danger"
                    icon={X}
                    loading={working === `reject-${account.id}`}
                    disabled={working !== null}
                    onClick={() =>
                      void act(
                        `reject-${account.id}`,
                        () => api.rejectUser(account.id),
                        `${account.full_name}'s request was turned away.`,
                      )
                    }
                  >
                    Turn away
                  </Button>
                </span>
              </div>
            ))}
          </section>
        ) : null}

        {waitingPupils.length ? (
          <section className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold">Pupils added by class teachers</h3>
            {waitingPupils.map((pupil) => (
              <div
                key={pupil.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
              >
                <span className="font-medium">{pupilName(pupil)}</span>
                <span className="flex gap-1.5">
                  <Button
                    size="sm"
                    icon={Check}
                    loading={working === `pupil-${pupil.id}`}
                    disabled={working !== null}
                    onClick={() =>
                      void act(
                        `pupil-${pupil.id}`,
                        () => api.approvePupil(pupil.id),
                        `${pupilName(pupil)} approved and added to the class.`,
                      )
                    }
                  >
                    Approve
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost-danger"
                    icon={X}
                    loading={working === `reject-pupil-${pupil.id}`}
                    disabled={working !== null}
                    onClick={() =>
                      void act(
                        `reject-pupil-${pupil.id}`,
                        () => api.deletePupil(pupil.id),
                        `${pupilName(pupil)} was turned away.`,
                      )
                    }
                  >
                    Turn away
                  </Button>
                </span>
              </div>
            ))}
            <Link href="/admin/pupils?pending=1" className="text-sm text-[var(--brand)] hover:underline">
              Review or correct their details on the Pupils page
            </Link>
          </section>
        ) : null}
      </div>
    </Panel>
  );
}
