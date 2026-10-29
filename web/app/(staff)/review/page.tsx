"use client";

/**
 * The review queue (§8.4).
 *
 * "Queue of submitted classes." Longest-waiting first, because the queue is
 * worked through rather than browsed — the class that has been waiting
 * longest is the one holding up the release.
 */

import Link from "next/link";

import { Badge, Notice, Panel, Spinner } from "@/components/ui";
import { useHeadApi } from "@/lib/api/use-head";
import { formatDateTime } from "@/lib/format";
import { useResource } from "@/lib/use-async";

const STATE_LABELS: Record<string, string> = {
  submitted: "Waiting for you",
  returned: "Returned to the teacher",
  approved: "Approved",
};

const STATE_TONES: Record<string, "neutral" | "good" | "warn" | "bad"> = {
  submitted: "warn",
  returned: "bad",
  approved: "good",
};

export default function ReviewQueuePage() {
  const api = useHeadApi();

  // No term id: the server resolves the current term, because §5.2 gives
  // `/terms` to the admin alone (D51).
  const queue = useResource((signal) => api!.queue(undefined, signal), [api], {
    enabled: Boolean(api),
  });

  if (queue.loading) return <Spinner label="Loading the queue…" />;
  if (queue.error) return <Notice>{queue.error}</Notice>;
  if (!queue.data) return null;

  const waiting = queue.data.filter((entry) => entry.state === "submitted");

  return (
    <>
      <div>
        <h1 className="text-lg font-semibold">Classes for review</h1>
        <p className="text-sm text-[var(--muted)]">
          {queue.data[0]?.term_label ?? "This term"} ·{" "}
          {waiting.length === 0
            ? "nothing is waiting for you"
            : `${waiting.length} waiting for you`}
        </p>
      </div>

      {queue.data.length === 0 ? (
        <Notice tone="info">
          No class has been submitted for review yet. A class teacher sends one when
          everything on it is complete.
        </Notice>
      ) : null}

      {queue.data.map((entry) => (
        <Panel
          key={entry.class_id}
          title={entry.class_name}
          description={`${entry.roll} pupil${entry.roll === 1 ? "" : "s"}${
            entry.submitted_by ? ` · submitted by ${entry.submitted_by}` : ""
          }${entry.submitted_at ? ` · ${formatDateTime(entry.submitted_at)}` : ""}`}
        >
          <div className="flex flex-wrap items-center gap-3">
            <Badge tone={STATE_TONES[entry.state] ?? "neutral"}>
              {STATE_LABELS[entry.state] ?? entry.state}
            </Badge>
            <Badge tone={entry.remarks_written >= entry.roll ? "good" : "neutral"}>
              {entry.remarks_written} of {entry.roll} remarks written
            </Badge>
            <Link
              href={`/review/${entry.class_id}?term=${entry.term_id}`}
              className="rounded-md border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-raised)]"
            >
              {entry.state === "submitted" ? "Review" : "Open"}
            </Link>
          </div>
        </Panel>
      ))}
    </>
  );
}
