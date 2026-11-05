"use client";

/**
 * The audit log (§4.9, §7).
 *
 * §4.9 lists what is written; this is how it is read. Newest first, because
 * the question is almost always "what just happened" — and filterable by
 * entity, which is §4.9's own index and the shape of the other question:
 * "what has happened to this report".
 *
 * The log carries before/after values on a post-publication edit (R13), so
 * this screen shows scores. §5.2 restricts it to the admin and the head
 * teacher, who already see every card.
 */

import { useState } from "react";

import { Badge, Button, Notice, Panel, Select, Spinner } from "@/components/ui";
import type { AuditEntry } from "@/lib/api/admin";
import { useAdminApi } from "@/lib/api/use-admin";
import { formatDateTime } from "@/lib/format";
import { useResource } from "@/lib/use-async";

const PAGE = 50;

/** The entity kinds §4.9's index is built for, as a filter rather than a box
 *  the reader has to guess the vocabulary for. */
const ENTITY_TYPES = [
  "",
  "term_report",
  "result_entry",
  "result_entries",
  "class",
  "class_subject",
  "class_term_status",
  "pupil",
  "user",
  "grading_scale",
  "marks_obtainable",
  "term",
] as const;

export default function AuditPage() {
  const api = useAdminApi();
  const [entityType, setEntityType] = useState("");
  const [offset, setOffset] = useState(0);

  const page = useResource(
    () =>
      api!.audit({
        entity_type: entityType === "" ? undefined : entityType,
        limit: PAGE,
        offset,
      }),
    [api, entityType, offset],
    { enabled: Boolean(api) },
  );

  return (
    <>
      <div>
        <h1 className="text-lg font-semibold">Audit log</h1>
        <p className="text-sm text-[var(--muted)]">
          Every publication, every change after approval, every account created and every
          failed sign-in. Newest first.
        </p>
      </div>

      <Panel title="Filter">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Kind of record</span>
          <Select
            value={entityType}
            onChange={(event) => {
              setEntityType(event.target.value);
              setOffset(0);
            }}
          >
            {ENTITY_TYPES.map((kind) => (
              <option key={kind} value={kind}>
                {kind === "" ? "Everything" : kind.replace(/_/g, " ")}
              </option>
            ))}
          </Select>
        </label>
      </Panel>

      {page.loading ? <Spinner label="Loading the log…" /> : null}
      {page.error ? <Notice>{page.error}</Notice> : null}

      {page.data ? (
        <Panel
          title={`${page.data.total} record${page.data.total === 1 ? "" : "s"}`}
          description={
            page.data.total > PAGE
              ? `Showing ${offset + 1}–${Math.min(offset + PAGE, page.data.total)}`
              : undefined
          }
        >
          <ul className="flex flex-col divide-y divide-[var(--border)]">
            {(page.data.entries ?? []).map((entry) => (
              <Row key={entry.id} entry={entry} />
            ))}
          </ul>

          {page.data.total > PAGE ? (
            <div className="flex gap-2 pt-3">
              <Button
                variant="secondary"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE))}
              >
                Newer
              </Button>
              <Button
                variant="secondary"
                disabled={offset + PAGE >= page.data.total}
                onClick={() => setOffset(offset + PAGE)}
              >
                Older
              </Button>
            </div>
          ) : null}
        </Panel>
      ) : null}
    </>
  );
}

function Row({ entry }: { entry: AuditEntry }) {
  const [open, setOpen] = useState(false);
  const hasPayload = Boolean(entry.before || entry.after);

  return (
    <li className="flex flex-col gap-1 py-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-medium">{entry.action.replace(/[._]/g, " ")}</span>
        <span className="text-xs text-[var(--muted)]">{formatDateTime(entry.created_at)}</span>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
        <Badge tone="neutral">{entry.entity_type.replace(/_/g, " ")}</Badge>
        <span>{entry.actor_name ?? "the system"}</span>
        {entry.ip_address ? <span>· {entry.ip_address}</span> : null}
        {hasPayload ? (
          <button
            type="button"
            onClick={() => setOpen(!open)}
            className="rounded border border-[var(--border)] px-1.5 py-0.5"
          >
            {open ? "Hide values" : "Values"}
          </button>
        ) : null}
      </div>

      {entry.reason ? (
        <p className="text-sm">
          <span className="text-xs uppercase tracking-wide text-[var(--muted)]">Reason</span>{" "}
          {entry.reason}
        </p>
      ) : null}

      {open ? (
        <pre className="overflow-x-auto rounded-md bg-[var(--surface)] p-2 text-xs">
          {JSON.stringify({ before: entry.before, after: entry.after }, null, 2)}
        </pre>
      ) : null}
    </li>
  );
}
