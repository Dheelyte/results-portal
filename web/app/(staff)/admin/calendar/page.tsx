"use client";

/**
 * Session, terms, half terms and column maxima
 * (ARCHITECTURE.md §1.1, §4.2, §4.4).
 *
 * The first screen an admin uses, because nothing else can be configured
 * before there is a current session to configure it in.
 */

import { useState } from "react";

import {
  Badge,
  Button,
  Cell,
  Field,
  Input,
  Notice,
  Panel,
  Row,
  Select,
  Spinner,
  Table,
} from "@/components/ui";
import type { AcademicSession, AssessmentPeriod, Term } from "@/lib/api/admin";
import { useAdminApi } from "@/lib/api/use-admin";
import { formatDate, HALF_LABELS, TERM_LABELS } from "@/lib/format";
import { useAction, useResource, type Resource } from "@/lib/use-async";

export default function CalendarPage() {
  const api = useAdminApi();
  const sessions = useResource(() => api!.sessions(), [api], { enabled: Boolean(api) });
  const [openTermId, setOpenTermId] = useState<string | null>(null);

  const currentSession = sessions.data?.find((item) => item.is_current) ?? null;
  const terms = useResource(() => api!.terms(), [api, sessions.data], {
    enabled: Boolean(api),
  });

  const reloadAll = () => {
    sessions.reload();
    terms.reload();
  };

  if (!api) return <Spinner />;

  return (
    <>
      <SessionsPanel
        sessions={sessions}
        onChanged={reloadAll}
      />

      {currentSession ? (
        <TermsPanel
          terms={terms}
          sessionId={currentSession.id}
          sessionName={currentSession.name}
          onChanged={reloadAll}
          openTermId={openTermId}
          setOpenTermId={setOpenTermId}
        />
      ) : (
        <Notice tone="info">
          Make a session current before adding terms. Everything a teacher or a parent sees is
          scoped to the current session.
        </Notice>
      )}
    </>
  );
}

/* ------------------------------------------------------------------------- */

function SessionsPanel({
  sessions,
  onChanged,
}: {
  sessions: Resource<AcademicSession[]>;
  onChanged: () => void;
}) {
  const api = useAdminApi()!;
  const [form, setForm] = useState({ name: "", starts_on: "", ends_on: "" });
  const action = useAction(onChanged);

  return (
    <Panel
      title="Academic session"
      description="The school year, as the school writes it — 2026/2027. Exactly one is current."
    >
      <div className="flex flex-col gap-5">
        {sessions.loading ? <Spinner /> : null}
        {sessions.error ? <Notice>{sessions.error}</Notice> : null}

        <Table head={["Session", "Runs", "", ""]} empty="No sessions yet.">
          {(sessions.data ?? []).map((item) => (
            <Row key={item.id}>
              <Cell>{item.name}</Cell>
              <Cell>
                {formatDate(item.starts_on)} – {formatDate(item.ends_on)}
              </Cell>
              <Cell>{item.is_current ? <Badge tone="good">Current</Badge> : null}</Cell>
              <Cell>
                {item.is_current ? null : (
                  <Button
                    variant="ghost"
                    disabled={action.busy}
                    onClick={() =>
                      void action.run(
                        () => api.makeSessionCurrent(item.id),
                        `${item.name} is now the current session.`,
                      )
                    }
                  >
                    Make current
                  </Button>
                )}
              </Cell>
            </Row>
          ))}
        </Table>

        <form
          className="grid gap-3 sm:grid-cols-4"
          onSubmit={async (event) => {
            event.preventDefault();
            const created = await action.run(
              () => api.createSession({ ...form, is_current: true }),
              `${form.name} created and made current.`,
            );
            if (created) setForm({ name: "", starts_on: "", ends_on: "" });
          }}
        >
          <Field label="Name" required>
            <Input
              required
              placeholder="2026/2027"
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
            />
          </Field>
          <Field label="Starts" required>
            <Input
              type="date"
              required
              value={form.starts_on}
              onChange={(event) => setForm({ ...form, starts_on: event.target.value })}
            />
          </Field>
          <Field label="Ends" required>
            <Input
              type="date"
              required
              value={form.ends_on}
              onChange={(event) => setForm({ ...form, ends_on: event.target.value })}
            />
          </Field>
          <div className="flex items-end">
            <Button type="submit" disabled={action.busy}>
              Add session
            </Button>
          </div>
        </form>

        <Notice>{action.error}</Notice>
        <Notice tone="success">{action.success}</Notice>
      </div>
    </Panel>
  );
}

/* ------------------------------------------------------------------------- */

function TermsPanel({
  terms,
  sessionId,
  sessionName,
  onChanged,
  openTermId,
  setOpenTermId,
}: {
  terms: Resource<Term[]>;
  sessionId: string;
  sessionName: string;
  onChanged: () => void;
  openTermId: string | null;
  setOpenTermId: (id: string | null) => void;
}) {
  const api = useAdminApi()!;
  const action = useAction(onChanged);
  const [form, setForm] = useState({
    number: "first",
    starts_on: "",
    ends_on: "",
    times_school_opened: "",
    next_resumption_on: "",
    card_return_on: "",
  });

  const inSession = (terms.data ?? []).filter(
    (term) => term.academic_session_id === sessionId,
  );
  const taken = new Set(inSession.map((term) => term.number));

  return (
    <Panel
      title={`Terms in ${sessionName}`}
      description="Each term produces two sheets, created with it. One term is current at a time."
    >
      <div className="flex flex-col gap-5">
        {terms.loading ? <Spinner /> : null}
        {terms.error ? <Notice>{terms.error}</Notice> : null}

        <Table
          head={["Term", "Runs", "School opened", "", ""]}
          empty="No terms in this session yet."
        >
          {inSession.map((term) => (
            <Row key={term.id}>
              <Cell>{TERM_LABELS[term.number] ?? term.number}</Cell>
              <Cell>
                {formatDate(term.starts_on)} – {formatDate(term.ends_on)}
              </Cell>
              <Cell>
                {term.times_school_opened ?? (
                  <Badge tone="warn">Not set</Badge>
                )}
              </Cell>
              <Cell>{term.is_current ? <Badge tone="good">Current</Badge> : null}</Cell>
              <Cell className="whitespace-nowrap">
                {term.is_current ? null : (
                  <Button
                    variant="ghost"
                    disabled={action.busy}
                    onClick={() =>
                      void action.run(
                        () => api.makeTermCurrent(term.id),
                        `${TERM_LABELS[term.number]} is now current.`,
                      )
                    }
                  >
                    Make current
                  </Button>
                )}
                <Button
                  variant="ghost"
                  onClick={() => setOpenTermId(openTermId === term.id ? null : term.id)}
                >
                  {openTermId === term.id ? "Close" : "Open"}
                </Button>
              </Cell>
            </Row>
          ))}
        </Table>

        {openTermId ? (
          <TermDetail
            key={openTermId}
            term={inSession.find((term) => term.id === openTermId)!}
            onChanged={onChanged}
          />
        ) : null}

        {taken.size < 3 ? (
          <form
            className="grid gap-3 sm:grid-cols-3"
            onSubmit={async (event) => {
              event.preventDefault();
              const created = await action.run(
                () =>
                  api.createTerm({
                    academic_session_id: sessionId,
                    number: form.number as Term["number"],
                    starts_on: form.starts_on,
                    ends_on: form.ends_on,
                    times_school_opened: form.times_school_opened
                      ? Number(form.times_school_opened)
                      : null,
                    next_resumption_on: form.next_resumption_on || null,
                    card_return_on: form.card_return_on || null,
                    is_current: taken.size === 0,
                  }),
                "Term created, with both of its half terms.",
              );
              if (created) {
                setForm({ ...form, starts_on: "", ends_on: "", times_school_opened: "" });
              }
            }}
          >
            <Field label="Term" required>
              <Select
                value={form.number}
                onChange={(event) => setForm({ ...form, number: event.target.value })}
              >
                {(["first", "second", "third"] as const)
                  .filter((number) => !taken.has(number))
                  .map((number) => (
                    <option key={number} value={number}>
                      {TERM_LABELS[number]}
                    </option>
                  ))}
              </Select>
            </Field>
            <Field label="Starts" required>
              <Input
                type="date"
                required
                value={form.starts_on}
                onChange={(event) => setForm({ ...form, starts_on: event.target.value })}
              />
            </Field>
            <Field label="Ends" required>
              <Input
                type="date"
                required
                value={form.ends_on}
                onChange={(event) => setForm({ ...form, ends_on: event.target.value })}
              />
            </Field>
            <Field
              label="Times school opened"
              hint="Attendance is checked against this (R9). It can be filled in later."
            >
              <Input
                type="number"
                min={0}
                value={form.times_school_opened}
                onChange={(event) =>
                  setForm({ ...form, times_school_opened: event.target.value })
                }
              />
            </Field>
            <Field label="Next term resumes" hint="Prints on the card.">
              <Input
                type="date"
                value={form.next_resumption_on}
                onChange={(event) =>
                  setForm({ ...form, next_resumption_on: event.target.value })
                }
              />
            </Field>
            <Field label="Card returned on" hint='"Return this card to the School on …"'>
              <Input
                type="date"
                value={form.card_return_on}
                onChange={(event) => setForm({ ...form, card_return_on: event.target.value })}
              />
            </Field>
            <div className="flex items-end sm:col-span-3">
              <Button type="submit" disabled={action.busy}>
                Add term
              </Button>
            </div>
          </form>
        ) : (
          <p className="text-sm text-[var(--muted)]">
            All three terms exist for this session.
          </p>
        )}

        <Notice>{action.error}</Notice>
        <Notice tone="success">{action.success}</Notice>
      </div>
    </Panel>
  );
}

/* ------------------------------------------------------------------------- */

function TermDetail({ term, onChanged }: { term: Term; onChanged: () => void }) {
  const api = useAdminApi()!;
  const periods = useResource(() => api.assessmentPeriods(term.id), [api, term.id]);
  const action = useAction(() => {
    periods.reload();
    onChanged();
  });
  const [opened, setOpened] = useState(String(term.times_school_opened ?? ""));

  return (
    <div className="flex flex-col gap-4 rounded-md border border-[var(--border)] p-4">
      <h3 className="text-sm font-semibold">
        {TERM_LABELS[term.number] ?? term.number} — calendar and sheets
      </h3>

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
        <Field
          label="Times school opened"
          hint="R9: present + absent must equal this for every pupil."
        >
          <Input
            type="number"
            min={0}
            value={opened}
            onChange={(event) => setOpened(event.target.value)}
          />
        </Field>
        <Button type="submit" variant="secondary" disabled={action.busy}>
          Save
        </Button>
      </form>

      {periods.loading ? <Spinner /> : null}
      {periods.error ? <Notice>{periods.error}</Notice> : null}

      {(periods.data ?? []).map((period) => (
        <PeriodCard
          key={period.id}
          term={term}
          period={period}
          onChanged={() => {
            periods.reload();
            onChanged();
          }}
        />
      ))}

      <Notice>{action.error}</Notice>
      <Notice tone="success">{action.success}</Notice>
    </div>
  );
}

const CA_COLUMNS = ["ca_test_1", "ca_test_2", "ca_test_3", "ca_test_4", "ca_test_5"] as const;

function PeriodCard({
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

  const editing =
    (maxima.data ?? []).find((row) => (row.class_id ?? "") === classId) ?? null;
  const [values, setValues] = useState<Record<string, string>>({});
  const value = (column: string) =>
    values[column] ??
    (editing ? String((editing as Record<string, unknown>)[column] ?? "") : "");

  return (
    <section className="rounded-md border border-[var(--border)] p-4">
      <h4 className="text-sm font-medium">{HALF_LABELS[period.half] ?? period.half}</h4>

      <form
        className="mt-3 flex flex-wrap items-end gap-3"
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
        <Button type="submit" variant="secondary" disabled={action.busy}>
          Save dates
        </Button>
      </form>

      <div className="mt-5">
        <p className="text-sm font-medium">Marks Obtainable</p>
        <p className="mt-1 text-sm text-[var(--muted)]">
          What each column is out of. Scores are checked against these and the row prints on
          the card. The school has not yet confirmed the figures — the row is blank on the
          printed card, so these are whatever the school tells you.
        </p>

        {maxima.loading ? <Spinner /> : null}
        {maxima.error ? <Notice>{maxima.error}</Notice> : null}

        <Field label="Applies to" hint="A class's own row overrides the school-wide one.">
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

        <form
          className="mt-3 grid gap-3 sm:grid-cols-3"
          onSubmit={async (event) => {
            event.preventDefault();
            const body: Record<string, unknown> = { class_id: classId || null };
            for (const column of [...CA_COLUMNS, terminal]) {
              const raw = value(column);
              body[column] = raw === "" ? null : raw;
            }
            await action.run(
              () => api.saveMarksObtainable(period.id, body as never),
              "Marks obtainable saved.",
            );
          }}
        >
          {CA_COLUMNS.map((column, index) => (
            <Field key={column} label={`CA Test ${index + 1}`}>
              <Input
                type="number"
                min="0.01"
                step="0.01"
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
              onChange={(event) => setValues({ ...values, [terminal]: event.target.value })}
            />
          </Field>
          <div className="flex items-end sm:col-span-3">
            <Button type="submit" disabled={action.busy}>
              Save marks obtainable
            </Button>
          </div>
        </form>
      </div>

      <div className="mt-3">
        <Notice>{action.error}</Notice>
        <Notice tone="success">{action.success}</Notice>
      </div>
    </section>
  );
}
