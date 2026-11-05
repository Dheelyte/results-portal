"use client";

/**
 * Publication (§6 R12, §7).
 *
 * Publishing acts on a class; withholding and releasing act on individuals.
 * The screen is built around that asymmetry — one button for the class, and a
 * per-pupil control for the exceptions — because the exception is what the
 * admin is actually here to manage.
 *
 * What a withheld parent sees is R12's one sentence and nothing else. The
 * reason typed here is the school's own record, shown on this screen and in
 * the audit log, and never sent to a parent.
 */

import { useMemo, useState } from "react";

import { Badge, Button, Notice, Panel, Select, Spinner, TextArea } from "@/components/ui";
import { ApiError } from "@/lib/api/client";
import type { AdminApi, CorrectableRow, ReportState } from "@/lib/api/admin";
import { useAdminApi } from "@/lib/api/use-admin";
import { formatDateTime } from "@/lib/format";
import { useResource } from "@/lib/use-async";

const STATE_LABELS: Record<string, string> = {
  draft: "Not published",
  published: "Published",
  withheld: "Held back",
};

const STATE_TONES: Record<string, "neutral" | "good" | "warn" | "bad"> = {
  draft: "neutral",
  published: "good",
  withheld: "bad",
};

export default function PublishPage() {
  const api = useAdminApi();

  const [classId, setClassId] = useState("");
  const [termId, setTermId] = useState("");
  const [withhold, setWithhold] = useState<Set<string>>(new Set());
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const classes = useResource(() => api!.classes(), [api], { enabled: Boolean(api) });
  const terms = useResource(() => api!.terms(), [api], { enabled: Boolean(api) });

  const publication = useResource(
    () => api!.publication(classId, termId),
    [api, classId, termId],
    { enabled: Boolean(api) && Boolean(classId) && Boolean(termId) },
  );

  const reports = useMemo(() => publication.data?.reports ?? [], [publication.data]);
  const held = reports.filter((report) => report.state === "withheld");

  async function act(run: () => Promise<unknown>, message: string) {
    setBusy(true);
    setFailure(null);
    setDone(null);
    try {
      await run();
      setDone(message);
      publication.reload();
    } catch (caught) {
      setFailure(caught instanceof ApiError ? caught.message : "Could not do that.");
    } finally {
      setBusy(false);
    }
  }

  const ready = publication.data?.workflow_state === "approved";

  return (
    <>
      <div>
        <h1 className="text-lg font-semibold">Publish results</h1>
        <p className="text-sm text-[var(--muted)]">
          A class is published once the head teacher has approved it. Individual pupils can be
          held back and released later.
        </p>
      </div>

      <Panel title="Which class">
        <div className="flex flex-wrap gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">Class</span>
            <Select value={classId} onChange={(event) => setClassId(event.target.value)}>
              <option value="">Choose a class…</option>
              {(classes.data ?? []).map((klass) => (
                <option key={klass.id} value={klass.id}>
                  {klass.name}
                </option>
              ))}
            </Select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">Term</span>
            <Select value={termId} onChange={(event) => setTermId(event.target.value)}>
              <option value="">Choose a term…</option>
              {(terms.data ?? []).map((term) => (
                <option key={term.id} value={term.id}>
                  {term.number} term{term.is_current ? " (current)" : ""}
                </option>
              ))}
            </Select>
          </label>
        </div>
      </Panel>

      {failure ? <Notice tone="error">{failure}</Notice> : null}
      {done ? <Notice tone="success">{done}</Notice> : null}

      {publication.loading ? <Spinner label="Loading the class…" /> : null}
      {publication.error ? <Notice>{publication.error}</Notice> : null}

      {publication.data ? (
        <>
          {!ready ? (
            <Notice tone="warning">
              This class is {publication.data.workflow_state.replace("_", " ")}. The head
              teacher approves a class before it can be published (§1.6).
            </Notice>
          ) : null}

          <Panel
            title={publication.data.class_name}
            description={`${reports.length} report${reports.length === 1 ? "" : "s"}${
              held.length > 0 ? ` · ${held.length} held back` : ""
            }`}
          >
            <ul className="flex flex-col divide-y divide-[var(--border)]">
              {reports.map((report) => (
                <ReportRow
                  key={report.report_id}
                  report={report}
                  busy={busy}
                  selected={withhold.has(report.pupil_id)}
                  onToggle={(on) =>
                    setWithhold((current) => {
                      const next = new Set(current);
                      if (on) next.add(report.pupil_id);
                      else next.delete(report.pupil_id);
                      return next;
                    })
                  }
                  onRelease={() =>
                    act(
                      () => api!.releaseReport(report.report_id),
                      `${report.name}'s result has been released.`,
                    )
                  }
                  onWithhold={(why) =>
                    act(
                      () => api!.withholdReport(report.report_id, why),
                      `${report.name}'s result has been held back.`,
                    )
                  }
                  api={api!}
                  termId={termId}
                  onCorrected={(message) => {
                    setDone(message);
                    publication.reload();
                  }}
                />
              ))}
            </ul>
          </Panel>

          {ready ? (
            <Panel
              title="Publish the class"
              description="Ticked pupils are held back. They can be released individually later."
            >
              <div className="flex flex-col gap-3">
                {withhold.size > 0 ? (
                  <label className="flex flex-col gap-1 text-sm">
                    <span className="font-medium">
                      Why are {withhold.size} {withhold.size === 1 ? "result" : "results"} being
                      held back?
                    </span>
                    <TextArea
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                      rows={2}
                      placeholder="The parent is not shown this. The school needs it when they ask."
                    />
                  </label>
                ) : null}

                <Button
                  disabled={busy || (withhold.size > 0 && reason.trim() === "")}
                  onClick={() =>
                    act(async () => {
                      const outcome = await api!.publishClass(classId, termId, {
                        withhold_pupil_ids: [...withhold],
                        reason: reason.trim() === "" ? null : reason,
                      });
                      setWithhold(new Set());
                      setReason("");
                      return outcome;
                    }, "Published.")
                  }
                  className="self-start"
                >
                  {busy ? "Publishing…" : "Publish this class"}
                </Button>
              </div>
            </Panel>
          ) : null}
        </>
      ) : null}
    </>
  );
}

function ReportRow({
  report,
  busy,
  selected,
  onToggle,
  onRelease,
  onWithhold,
  api,
  termId,
  onCorrected,
}: {
  report: ReportState;
  busy: boolean;
  selected: boolean;
  onToggle: (on: boolean) => void;
  onRelease: () => void;
  onWithhold: (reason: string) => void;
  api: AdminApi;
  termId: string;
  onCorrected: (message: string) => void;
}) {
  const [why, setWhy] = useState("");
  const [asking, setAsking] = useState(false);
  const [correcting, setCorrecting] = useState(false);

  return (
    <li className="flex flex-col gap-2 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <span className="block truncate text-sm font-medium">{report.name}</span>
          <span className="block text-xs text-[var(--muted)]">
            {report.admission_number}
            {report.published_at ? ` · published ${formatDateTime(report.published_at)}` : ""}
            {report.acknowledged_at
              ? ` · seen by the parent ${formatDateTime(report.acknowledged_at)}`
              : ""}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={STATE_TONES[report.state] ?? "neutral"}>
            {STATE_LABELS[report.state] ?? report.state}
          </Badge>

          {report.state === "withheld" ? (
            <Button variant="secondary" disabled={busy} onClick={onRelease}>
              Release
            </Button>
          ) : null}

          {report.state === "published" ? (
            <Button variant="secondary" disabled={busy} onClick={() => setAsking(!asking)}>
              {asking ? "Cancel" : "Hold back"}
            </Button>
          ) : null}

          {report.state === "draft" ? (
            <label className="flex items-center gap-2 text-xs text-[var(--muted)]">
              <input
                type="checkbox"
                checked={selected}
                onChange={(event) => onToggle(event.target.checked)}
              />
              hold back
            </label>
          ) : null}

          <Button variant="secondary" disabled={busy} onClick={() => setCorrecting(!correcting)}>
            {correcting ? "Close" : "Correct a score"}
          </Button>

          <CardLink api={api} pupilId={report.pupil_id} termId={termId} />
        </div>
      </div>

      {report.withheld_reason ? (
        <p className="text-xs text-[var(--muted)]">
          Held back: {report.withheld_reason} — the parent is not shown this.
        </p>
      ) : null}

      {correcting ? (
        <Corrections
          api={api}
          pupilId={report.pupil_id}
          termId={termId}
          onCorrected={onCorrected}
        />
      ) : null}

      {asking ? (
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-1 flex-col gap-1 text-sm">
            <span className="font-medium">Why?</span>
            <TextArea
              value={why}
              onChange={(event) => setWhy(event.target.value)}
              rows={2}
              placeholder="Not shown to the parent."
            />
          </label>
          <Button
            disabled={busy || why.trim() === ""}
            onClick={() => {
              onWithhold(why);
              setWhy("");
              setAsking(false);
            }}
          >
            Hold it back
          </Button>
        </div>
      ) : null}
    </li>
  );
}


/**
 * R13's correction form.
 *
 * "Admin only, reason required, audited." The reason is mandatory in the form
 * because it is mandatory in §4.9, and the response says whether the grade
 * moved — which is the question the admin is actually asking, because it
 * decides whether the card has to be reprinted.
 */
function Corrections({
  api,
  pupilId,
  termId,
  onCorrected,
}: {
  api: AdminApi;
  pupilId: string;
  termId: string;
  onCorrected: (message: string) => void;
}) {
  const rows = useResource(() => api.pupilEntries(pupilId, termId), [api, pupilId, termId]);
  const [open, setOpen] = useState<string | null>(null);

  if (rows.loading) return <p className="text-xs text-[var(--muted)]">Loading scores…</p>;
  if (rows.error) return <Notice tone="error">{rows.error}</Notice>;
  if (!rows.data) return null;

  const entries = rows.data.rows ?? [];
  if (entries.length === 0) {
    return <p className="text-xs text-[var(--muted)]">No scores recorded for this term.</p>;
  }

  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-2">
      <ul className="flex flex-col divide-y divide-[var(--border)]">
        {entries.map((row) => (
          <li key={row.entry_id} className="flex flex-col gap-1 py-1.5">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
              <span>
                {row.subject_name} · {row.half === "first_half" ? "first half" : "second half"}
              </span>
              <span className="flex items-center gap-2">
                <span className="tabular-nums text-[var(--muted)]">
                  avg {row.period_average ?? "—"}
                </span>
                {row.grade_letter ? (
                  <Badge tone={row.is_snapshot ? "good" : "neutral"}>{row.grade_letter}</Badge>
                ) : null}
                <button
                  type="button"
                  onClick={() => setOpen(open === row.entry_id ? null : row.entry_id)}
                  className="rounded border border-[var(--border)] px-1.5 py-0.5"
                >
                  {open === row.entry_id ? "Cancel" : "Correct"}
                </button>
              </span>
            </div>

            {open === row.entry_id ? (
              <CorrectionForm
                api={api}
                row={row}
                onDone={(message) => {
                  setOpen(null);
                  rows.reload();
                  onCorrected(message);
                }}
              />
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function CorrectionForm({
  api,
  row,
  onDone,
}: {
  api: AdminApi;
  row: CorrectableRow;
  onDone: (message: string) => void;
}) {
  const [column, setColumn] = useState(row.columns?.[0] ?? "");
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  return (
    <div className="flex flex-col gap-2 pt-1">
      {failure ? <Notice tone="error">{failure}</Notice> : null}
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs">
          <span>Column</span>
          <Select value={column} onChange={(event) => setColumn(event.target.value)}>
            {(row.columns ?? []).map((name) => (
              <option key={name} value={name}>
                {name.replace(/_/g, " ")}
              </option>
            ))}
          </Select>
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span>New value</span>
          <input
            value={value}
            onChange={(event) => setValue(event.target.value)}
            inputMode="decimal"
            className="w-20 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1.5 text-right text-sm tabular-nums"
          />
        </label>
      </div>

      <label className="flex flex-col gap-1 text-xs">
        <span>Reason (required, and recorded)</span>
        <TextArea value={reason} onChange={(event) => setReason(event.target.value)} rows={2} />
      </label>

      <Button
        disabled={busy || reason.trim() === "" || value.trim() === ""}
        className="self-start"
        onClick={async () => {
          setBusy(true);
          setFailure(null);
          try {
            const result = await api.editEntry(row.entry_id, {
              reason,
              [column]: value,
            } as Parameters<AdminApi["editEntry"]>[1]);
            onDone(
              result.grade_changed
                ? `${result.pupil_name} — ${result.subject_name}: the grade changed to ` +
                  `${result.after.grade_letter ?? "—"}. The card will need reprinting.`
                : `${result.pupil_name} — ${result.subject_name}: corrected, and the grade ` +
                  "did not change.",
            );
          } catch (caught) {
            setFailure(caught instanceof ApiError ? caught.message : "Could not correct it.");
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Saving…" : "Correct it"}
      </Button>
    </div>
  );
}


/**
 * Opens the printable card (§9).
 *
 * The PDF arrives as a blob rather than through a link, because the
 * endpoint needs an Authorization header and a browser following an anchor
 * sends none. §9 says the school will compare this output to the paper line
 * by line, so it is one click from the publish screen.
 */
function CardLink({
  api,
  pupilId,
  termId,
}: {
  api: AdminApi;
  pupilId: string;
  termId: string;
}) {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  async function open(half: "first_half" | "second_half") {
    setBusy(true);
    setFailure(null);
    let objectUrl: string | null = null;
    try {
      objectUrl = await api.cardBlobUrl(pupilId, termId, half);
      window.open(objectUrl, "_blank", "noopener");
    } catch (caught) {
      setFailure(caught instanceof ApiError ? caught.message : "Could not open the card.");
    } finally {
      setBusy(false);
      // Released later, not immediately: revoking at once can beat the new
      // tab to the data.
      const toRelease = objectUrl;
      if (toRelease) window.setTimeout(() => URL.revokeObjectURL(toRelease), 60_000);
    }
  }

  return (
    <span className="flex items-center gap-1">
      <Button variant="secondary" disabled={busy} onClick={() => void open("first_half")}>
        Card: 1st half
      </Button>
      <Button variant="secondary" disabled={busy} onClick={() => void open("second_half")}>
        2nd half
      </Button>
      {failure ? <span className="text-xs text-[var(--danger)]">{failure}</span> : null}
    </span>
  );
}
