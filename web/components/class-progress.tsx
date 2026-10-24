"use client";

/**
 * §8.3's progress view and R10's gate.
 *
 * "One page per class: every subject with its state and owner, for both
 * assessment periods; then the class teacher's own tasks — narrative,
 * attendance, growth, comments. **Send to head teacher** is disabled until
 * R10 passes, with the outstanding items listed beneath it."
 *
 * The outstanding list is the server's, not this component's. It arrives on
 * `GET /progress` and again in R10's 422, identically, so the reason the
 * button is disabled and the reason a submission was refused can never be two
 * different stories. Nothing here re-derives completeness.
 */

import Link from "next/link";
import { useState } from "react";

import { Badge, Notice, Panel } from "@/components/ui";
import { ApiError } from "@/lib/api/client";
import type { OutstandingItem, Progress, TeacherApi } from "@/lib/api/teacher";
import { HALF_LABELS } from "@/lib/format";
import { useResource } from "@/lib/use-async";

const STATE_LABELS: Record<string, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  submitted: "Submitted for review",
  returned: "Returned for correction",
  approved: "Approved",
};

const STATE_TONES: Record<string, "neutral" | "good" | "warn" | "bad"> = {
  not_started: "neutral",
  in_progress: "neutral",
  submitted: "warn",
  returned: "bad",
  approved: "good",
};

/** Who can clear each kind of item, so nobody waits on the wrong person. */
const OWNER: Record<string, string> = {
  term: "Administrator",
  class: "Administrator",
  sheet: "Administrator",
  scores: "Subject teacher",
  pupil: "You",
};

export function ClassProgress({
  api,
  classId,
  termId,
}: {
  api: TeacherApi;
  classId: string;
  termId: string;
}) {
  const [submitting, setSubmitting] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [refused, setRefused] = useState<OutstandingItem[] | null>(null);

  const progress = useResource(
    (signal) => api.progress(classId, termId, signal),
    [api, classId, termId],
  );

  if (progress.loading) return <p className="text-sm text-[var(--muted)]">Loading progress…</p>;
  if (progress.error) return <Notice>{progress.error}</Notice>;
  if (!progress.data) return null;

  const data: Progress = progress.data;
  const sheets = data.sheets ?? [];
  const pupils = data.pupils ?? [];
  // The server's list, except just after a refusal, when it is the server's
  // list from the refusal — same shape, and fresher by a moment.
  const outstanding = refused ?? data.outstanding ?? [];
  const sent = data.state === "submitted" || data.state === "approved";

  async function send() {
    setSubmitting(true);
    setFailure(null);
    setRefused(null);
    try {
      await api.submitClass(classId, termId);
      progress.reload();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 422) {
        setRefused((caught.outstanding ?? []) as OutstandingItem[]);
        setFailure(caught.message);
      } else {
        setFailure(caught instanceof ApiError ? caught.message : "Could not submit.");
      }
      progress.reload();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Badge tone={STATE_TONES[data.state] ?? "neutral"}>
          {STATE_LABELS[data.state] ?? data.state}
        </Badge>
        {data.ready && !sent ? (
          <Badge tone="good">Everything is complete</Badge>
        ) : sent ? null : (
          <Badge tone="warn">
            {outstanding.length} {outstanding.length === 1 ? "item" : "items"} outstanding
          </Badge>
        )}
      </div>

      {data.return_note ? (
        <Notice tone="warning">
          <strong>Returned by the head teacher:</strong> {data.return_note}
        </Notice>
      ) : null}

      {failure ? <Notice tone="error">{failure}</Notice> : null}

      {sent ? (
        <Notice tone="info">
          {data.state === "approved"
            ? "This class has been approved. Only an administrator may change it now."
            : "This class is with the head teacher. Its scores and narrative are read-only until it is approved or returned."}
        </Notice>
      ) : null}

      <Panel
        title="Subjects"
        description="Every subject offered to this class, on both of the term's sheets"
      >
        <ul className="flex flex-col divide-y divide-[var(--border)]">
          {sheets.length === 0 ? (
            <li className="py-2 text-sm text-[var(--muted)]">
              No scored subjects are offered to this class yet.
            </li>
          ) : null}
          {sheets.map((sheet) => (
            <li
              key={`${sheet.class_subject_id}:${sheet.half}`}
              className="flex flex-wrap items-center justify-between gap-3 py-2"
            >
              <div className="min-w-0">
                <span className="block truncate text-sm font-medium">
                  {sheet.subject_name}
                </span>
                <span className="block text-xs text-[var(--muted)]">
                  {HALF_LABELS[sheet.half]} ·{" "}
                  {sheet.teacher_name ?? "no teacher assigned"}
                </span>
              </div>
              <div className="flex items-center gap-2">
                {sheet.not_configured ? (
                  <Badge tone="bad">No Marks Obtainable row</Badge>
                ) : (
                  <Badge tone={sheet.is_complete ? "good" : "neutral"}>
                    {sheet.complete} of {sheet.roll} entered
                  </Badge>
                )}
              </div>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel title="Pupils" description="Narrative, comment, attendance, height and weight">
        <ul className="flex flex-col divide-y divide-[var(--border)]">
          {pupils.map((pupil) => (
            <li
              key={pupil.pupil_id}
              className="flex flex-wrap items-center justify-between gap-3 py-2"
            >
              <Link
                href={`/teacher/narrative/${pupil.pupil_id}`}
                className="min-w-0 hover:underline"
              >
                <span className="block truncate text-sm font-medium">{pupil.name}</span>
                <span className="block text-xs text-[var(--muted)]">
                  {pupil.admission_number}
                </span>
              </Link>
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge tone={pupil.sections_written >= pupil.sections_total ? "good" : "neutral"}>
                  narrative {pupil.sections_written}/{pupil.sections_total}
                </Badge>
                <Badge tone={pupil.has_comment ? "good" : "warn"}>comment</Badge>
                <Badge tone={pupil.has_attendance ? "good" : "warn"}>attendance</Badge>
                <Badge tone={pupil.has_growth ? "good" : "warn"}>height &amp; weight</Badge>
              </div>
            </li>
          ))}
        </ul>
      </Panel>

      {!sent ? (
        <Panel title="Send to the head teacher">
          <div className="flex flex-col gap-3">
            <button
              type="button"
              onClick={() => void send()}
              disabled={!data.ready || !data.may_submit || submitting}
              className="self-start rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {submitting ? "Sending…" : "Send to head teacher"}
            </button>

            {!data.may_submit ? (
              <p className="text-sm text-[var(--muted)]">
                Only the class teacher submits a class. You can see what is outstanding, and
                anything of yours below is worth clearing either way.
              </p>
            ) : null}

            {outstanding.length > 0 ? (
              <div className="flex flex-col gap-1">
                <p className="text-sm font-medium">Still to do</p>
                <ul className="flex flex-col gap-1.5">
                  {outstanding.map((item, index) => (
                    <li
                      key={`${item.kind}-${index}`}
                      className="flex flex-wrap items-baseline gap-2 text-sm"
                    >
                      <Badge tone={item.kind === "pupil" ? "warn" : "neutral"}>
                        {OWNER[item.kind] ?? item.kind}
                      </Badge>
                      <span>{item.what}</span>
                      {item.detail ? (
                        <span className="text-xs text-[var(--muted)]">{item.detail}</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </Panel>
      ) : null}
    </div>
  );
}
