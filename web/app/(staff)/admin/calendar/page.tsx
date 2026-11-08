"use client";

/**
 * The academic session and its terms (ARCHITECTURE.md §1.1, §4.2).
 *
 * The first screen an admin uses, because nothing else can be configured
 * before there is a current session to configure it in.
 *
 * A term's own calendar and its two Marks Obtainable sheets are
 * `/admin/calendar/[termId]` (docs/DECISIONS.md D104). They used to unfold
 * beneath this table, three levels of nesting deep, on a page with one
 * address.
 */

import { CalendarDays, CalendarRange, Plus } from "lucide-react";
import { useState } from "react";

import {
  Badge,
  Button,
  ButtonLink,
  Cell,
  Field,
  Input,
  Notice,
  PageHeader,
  Panel,
  Row,
  Select,
  SkeletonTable,
  Table,
} from "@/components/ui";
import type { AcademicSession, Term } from "@/lib/api/admin";
import { useAdminApi } from "@/lib/api/use-admin";
import { formatDate, TERM_LABELS } from "@/lib/format";
import { useAction, useResource, type Resource } from "@/lib/use-async";

export default function CalendarPage() {
  const api = useAdminApi();
  const sessions = useResource(() => api!.sessions(), [api], { enabled: Boolean(api) });
  const terms = useResource(() => api!.terms(), [api, sessions.data], {
    enabled: Boolean(api),
  });

  const currentSession = sessions.data?.find((item) => item.is_current) ?? null;

  const reloadAll = () => {
    sessions.reload();
    terms.reload();
  };

  return (
    <>
      <PageHeader
        title="Session & terms"
        description="The school year, its three terms, and the two assessment sheets each term carries."
      />

      <SessionsPanel sessions={sessions} ready={Boolean(api)} onChanged={reloadAll} />

      {!api || sessions.loading ? null : currentSession ? (
        <TermsPanel
          terms={terms}
          sessionId={currentSession.id}
          sessionName={currentSession.name}
          onChanged={reloadAll}
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
  ready,
  onChanged,
}: {
  sessions: Resource<AcademicSession[]>;
  ready: boolean;
  onChanged: () => void;
}) {
  const api = useAdminApi();
  const [form, setForm] = useState({ name: "", starts_on: "", ends_on: "" });
  const action = useAction(onChanged);

  return (
    <Panel
      title="Academic session"
      icon={CalendarRange}
      description="The school year, as the school writes it — 2026/2027. Exactly one is current."
    >
      <div className="flex flex-col gap-5">
        {!ready || sessions.loading ? (
          <SkeletonTable rows={3} columns={4} label="Loading the sessions…" />
        ) : (
          <>
            {sessions.error ? <Notice>{sessions.error}</Notice> : null}

            <Table head={["Session", "Runs", "", ""]} empty="No sessions yet.">
              {(sessions.data ?? []).map((item) => (
                <Row key={item.id}>
                  <Cell className="font-medium">{item.name}</Cell>
                  <Cell className="text-[var(--muted)]">
                    {formatDate(item.starts_on)} – {formatDate(item.ends_on)}
                  </Cell>
                  <Cell>{item.is_current ? <Badge tone="good">Current</Badge> : null}</Cell>
                  <Cell className="text-right">
                    {item.is_current ? null : (
                      <Button
                        variant="ghost"
                        size="sm"
                        loading={action.busy}
                        onClick={() =>
                          void action.run(
                            () => api!.makeSessionCurrent(item.id),
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
          </>
        )}

        <form
          className="grid gap-3 border-t border-[var(--border)] pt-4 sm:grid-cols-4"
          onSubmit={async (event) => {
            event.preventDefault();
            const created = await action.run(
              () => api!.createSession({ ...form, is_current: true }),
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
            <Button type="submit" icon={Plus} loading={action.busy} disabled={!ready}>
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
}: {
  terms: Resource<Term[]>;
  sessionId: string;
  sessionName: string;
  onChanged: () => void;
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
      icon={CalendarDays}
      description="Each term produces two sheets, created with it. One term is current at a time."
    >
      <div className="flex flex-col gap-5">
        {terms.loading ? (
          <SkeletonTable rows={3} columns={5} label="Loading the terms…" />
        ) : (
          <>
            {terms.error ? <Notice>{terms.error}</Notice> : null}

            <Table
              head={["Term", "Runs", "School opened", "", ""]}
              empty="No terms in this session yet."
            >
              {inSession.map((term) => (
                <Row key={term.id}>
                  <Cell className="font-medium">
                    {TERM_LABELS[term.number] ?? term.number}
                  </Cell>
                  <Cell className="text-[var(--muted)]">
                    {formatDate(term.starts_on)} – {formatDate(term.ends_on)}
                  </Cell>
                  <Cell>
                    {term.times_school_opened ?? <Badge tone="warn">Not set</Badge>}
                  </Cell>
                  <Cell>{term.is_current ? <Badge tone="good">Current</Badge> : null}</Cell>
                  <Cell className="whitespace-nowrap text-right">
                    {term.is_current ? null : (
                      <Button
                        variant="ghost"
                        size="sm"
                        loading={action.busy}
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
                    <ButtonLink
                      href={`/admin/calendar/${term.id}`}
                      size="sm"
                      className="ml-1.5"
                    >
                      Open
                    </ButtonLink>
                  </Cell>
                </Row>
              ))}
            </Table>
          </>
        )}

        {taken.size < 3 ? (
          <form
            className="grid gap-3 border-t border-[var(--border)] pt-4 sm:grid-cols-3"
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
              <Button type="submit" icon={Plus} loading={action.busy}>
                Add term
              </Button>
            </div>
          </form>
        ) : (
          <p className="border-t border-[var(--border)] pt-4 text-sm text-[var(--muted)]">
            All three terms exist for this session.
          </p>
        )}

        <Notice>{action.error}</Notice>
        <Notice tone="success">{action.success}</Notice>
      </div>
    </Panel>
  );
}
