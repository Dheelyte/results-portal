"use client";

/**
 * One term: its calendar, and what each column of each half is out of
 * (ARCHITECTURE.md §1.1, §4.2, §4.4).
 *
 * Its own route since the redesign (D104). The Marks Obtainable row is what
 * every score on the term is validated against and what prints across the
 * top of the card, and it used to be reached by opening a panel inside a
 * panel inside a table.
 */

import { CalendarCheck, Ruler } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";

import {
  Badge,
  Button,
  Field,
  Input,
  Notice,
  PageHeader,
  Panel,
  Select,
  SkeletonPanel,
  SkeletonTable,
} from "@/components/ui";
import type { AssessmentPeriod, Term } from "@/lib/api/admin";
import { useAdminApi } from "@/lib/api/use-admin";
import { formatDate, HALF_LABELS, TERM_LABELS } from "@/lib/format";
import { useAction, useResource } from "@/lib/use-async";

export default function TermPage() {
  const api = useAdminApi();
  const { termId } = useParams<{ termId: string }>();

  const terms = useResource(() => api!.terms(), [api], { enabled: Boolean(api) });
  const periods = useResource(() => api!.assessmentPeriods(termId), [api, termId], {
    enabled: Boolean(api),
  });

  const term = (terms.data ?? []).find((item) => item.id === termId) ?? null;
  const label = term ? (TERM_LABELS[term.number] ?? term.number) : "Term";

  const crumbs = [{ label: "Session & terms", href: "/admin/calendar" }, { label }];
  const back = { href: "/admin/calendar", label: "Session & terms" };

  if (!api || terms.loading) {
    return (
      <>
        <PageHeader breadcrumbs={crumbs} back={back} title="Term" />
        <SkeletonPanel rows={2} label="Loading the term…" />
        <SkeletonPanel rows={6} />
      </>
    );
  }

  if (terms.error) {
    return (
      <>
        <PageHeader breadcrumbs={crumbs} back={back} title="Term" />
        <Notice>{terms.error}</Notice>
      </>
    );
  }

  if (!term) {
    return (
      <>
        <PageHeader breadcrumbs={crumbs} back={back} title="Term" />
        <Notice tone="info">
          That term no longer exists. Pick one from the list of terms.
        </Notice>
      </>
    );
  }

  return (
    <>
      <PageHeader
        breadcrumbs={crumbs}
        back={back}
        title={label}
        description={`${formatDate(term.starts_on)} – ${formatDate(term.ends_on)}`}
        badge={term.is_current ? <Badge tone="good">Current</Badge> : null}
      />

      <OpenedPanel term={term} onChanged={terms.reload} />

      {periods.loading ? (
        <SkeletonPanel rows={6} label="Loading the half terms…" />
      ) : periods.error ? (
        <Notice>{periods.error}</Notice>
      ) : (
        (periods.data ?? []).map((period) => (
          <PeriodPanel
            key={period.id}
            term={term}
            period={period}
            onChanged={() => {
              periods.reload();
              terms.reload();
            }}
          />
        ))
      )}
    </>
  );
}

/* ------------------------------------------------------------------------- */

function OpenedPanel({ term, onChanged }: { term: Term; onChanged: () => void }) {
  const api = useAdminApi()!;
  const action = useAction(onChanged);
  const [opened, setOpened] = useState(String(term.times_school_opened ?? ""));

  return (
    <Panel
      title="Term calendar"
      icon={CalendarCheck}
      description="R9: times present plus times absent must equal the days the school opened, for every pupil."
    >
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={async (event) => {
          event.preventDefault();
          await action.run(
            () =>
              api.updateTerm(term.id, {
                times_school_opened: opened === "" ? null : Number(opened),
              }),
            "Saved.",
          );
        }}
      >
        <Field label="Times school opened">
          <Input
            type="number"
            min={0}
            value={opened}
            onChange={(event) => setOpened(event.target.value)}
          />
        </Field>
        <Button type="submit" variant="secondary" loading={action.busy}>
          Save
        </Button>
      </form>

      <div className="mt-3 flex flex-col gap-2">
        <Notice>{action.error}</Notice>
        <Notice tone="success">{action.success}</Notice>
      </div>
    </Panel>
  );
}

// Four since D127. On the second half they are the first half's, carried
// over, so the second-half form shows them locked.
const CA_COLUMNS = ["ca_test_1", "ca_test_2", "ca_test_3", "ca_test_4"] as const;

function PeriodPanel({
  term,
  period,
  onChanged,
}: {
  term: Term;
  period: AssessmentPeriod;
  onChanged: () => void;
}) {
  const api = useAdminApi()!;
  const maxima = useResource(() => api.marksObtainable(period.id), [api, period.id]);
  const classes = useResource(() => api.classes(), [api]);
  const action = useAction(() => {
    maxima.reload();
    onChanged();
  });

  const [window, setWindow] = useState({
    opens_on: period.opens_on ?? "",
    closes_on: period.closes_on ?? "",
  });
  const [classId, setClassId] = useState("");
  const terminal = period.half === "first_half" ? "mid_term_test" : "exam";
  const terminalLabel = period.half === "first_half" ? "Mid Term Test" : "Exam";
  const halfLabel = HALF_LABELS[period.half] ?? period.half;

  const editing =
    (maxima.data ?? []).find((row) => (row.class_id ?? "") === classId) ?? null;
  const [values, setValues] = useState<Record<string, string>>({});
  const value = (column: string) =>
    values[column] ??
    (editing ? String((editing as Record<string, unknown>)[column] ?? "") : "");

  return (
    // The handle the E2E journey finds this panel by. A heading alone was not
    // enough once the panel gained an icon and a description: the test used
    // to walk up two DOM parents from the `<h2>` to find the form.
    <div data-testid={`period-${period.half}`}>
      <Panel
        title={halfLabel}
        icon={Ruler}
        description="When the sheet is open, and what each of its columns is out of."
      >
        <div className="flex flex-col gap-6">
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={async (event) => {
              event.preventDefault();
              await action.run(
                () =>
                  api.saveAssessmentPeriod(term.id, {
                    half: period.half,
                    opens_on: window.opens_on || null,
                    closes_on: window.closes_on || null,
                  }),
                "Dates saved.",
              );
            }}
          >
            <Field label="Opens">
              <Input
                type="date"
                value={window.opens_on}
                onChange={(event) => setWindow({ ...window, opens_on: event.target.value })}
              />
            </Field>
            <Field label="Closes">
              <Input
                type="date"
                value={window.closes_on}
                onChange={(event) => setWindow({ ...window, closes_on: event.target.value })}
              />
            </Field>
            <Button type="submit" variant="secondary" loading={action.busy}>
              Save dates
            </Button>
          </form>

          <div className="border-t border-[var(--border)] pt-5">
            <p className="text-sm font-semibold">Marks Obtainable</p>
            <p className="mt-1 text-sm text-[var(--muted)]">
              What each column is out of. Scores are checked against these and the row prints
              on the card. The school has not yet confirmed the figures — the row is blank on
              the printed card, so these are whatever the school tells you.
            </p>

            {maxima.loading || classes.loading ? (
              <div className="mt-3">
                <SkeletonTable rows={2} columns={3} label="Loading the maxima…" />
              </div>
            ) : (
              <>
                {maxima.error ? (
                  <div className="mt-3">
                    <Notice>{maxima.error}</Notice>
                  </div>
                ) : null}

                <div className="mt-3 max-w-sm">
                  <Field
                    label="Applies to"
                    hint="A class's own row overrides the school-wide one."
                  >
                    <Select
                      value={classId}
                      onChange={(event) => {
                        setClassId(event.target.value);
                        setValues({});
                      }}
                    >
                      <option value="">Every class</option>
                      {(classes.data ?? []).map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name}
                        </option>
                      ))}
                    </Select>
                  </Field>
                </div>

                <form
                  className="mt-4 grid gap-3 sm:grid-cols-3"
                  onSubmit={async (event) => {
                    event.preventDefault();
                    const body: Record<string, unknown> = { class_id: classId || null };
                    const owned = period.half === "first_half" ? [...CA_COLUMNS, terminal] : [terminal];
                    for (const column of owned) {
                      const raw = value(column);
                      body[column] = raw === "" ? null : raw;
                    }
                    await action.run(
                      () => api.saveMarksObtainable(period.id, body as never),
                      "Marks obtainable saved.",
                    );
                  }}
                >
                  {period.half === "second_half" ? (
                    <p className="text-sm text-[var(--muted)] sm:col-span-3">
                      The CA tests are carried over from the first half, maximum marks included.
                      Change them on the first-half sheet.
                    </p>
                  ) : null}
                  {CA_COLUMNS.map((column, index) => (
                    <Field key={column} label={`CA Test ${index + 1}`}>
                      <Input
                        type="number"
                        min="0.01"
                        step="0.01"
                        disabled={period.half === "second_half"}
                        value={value(column)}
                        onChange={(event) =>
                          setValues({ ...values, [column]: event.target.value })
                        }
                      />
                    </Field>
                  ))}
                  <Field label={terminalLabel}>
                    <Input
                      type="number"
                      min="0.01"
                      step="0.01"
                      value={value(terminal)}
                      onChange={(event) =>
                        setValues({ ...values, [terminal]: event.target.value })
                      }
                    />
                  </Field>
                  <div className="flex items-end sm:col-span-3">
                    <Button type="submit" loading={action.busy}>
                      Save marks obtainable
                    </Button>
                  </div>
                </form>
              </>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <Notice>{action.error}</Notice>
            <Notice tone="success">{action.success}</Notice>
          </div>
        </div>
      </Panel>
    </div>
  );
}
