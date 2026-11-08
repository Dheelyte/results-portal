"use client";

/**
 * The review queue (§8.4).
 *
 * "Queue of submitted classes." Longest-waiting first, because the queue is
 * worked through rather than browsed — the class that has been waiting
 * longest is the one holding up the release.
 */

import { ClipboardCheck, Inbox } from "lucide-react";

import {
  Badge,
  ButtonLink,
  EmptyState,
  Notice,
  PageHeader,
  Panel,
  SkeletonPanel,
} from "@/components/ui";
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

  if (!api || queue.loading) {
    return (
      <>
        <PageHeader title="Classes for review" />
        <SkeletonPanel rows={3} label="Loading the queue…" />
        <SkeletonPanel rows={3} />
      </>
    );
  }
  if (queue.error) return <Notice>{queue.error}</Notice>;
  if (!queue.data) return null;

  const waiting = queue.data.filter((entry) => entry.state === "submitted");

  return (
    <>
      <PageHeader
        title="Classes for review"
        description={`${queue.data[0]?.term_label ?? "This term"} · ${
          waiting.length === 0
            ? "nothing is waiting for you"
            : `${waiting.length} waiting for you`
        }`}
      />

      {queue.data.length === 0 ? (
        <EmptyState
          icon={Inbox}
          title="No class has been submitted for review yet"
          description="A class teacher sends one when everything on it is complete — every score, every narrative section, attendance, height and weight, and their own comment."
        />
      ) : null}

      {queue.data.map((entry) => (
        <Panel
          key={entry.class_id}
          title={entry.class_name}
          icon={ClipboardCheck}
          description={`${entry.roll} pupil${entry.roll === 1 ? "" : "s"}${
            entry.submitted_by ? ` · submitted by ${entry.submitted_by}` : ""
          }${entry.submitted_at ? ` · ${formatDateTime(entry.submitted_at)}` : ""}`}
          actions={
            <ButtonLink
              href={`/review/${entry.class_id}?term=${entry.term_id}`}
              variant={entry.state === "submitted" ? "primary" : "secondary"}
            >
              {entry.state === "submitted" ? "Review" : "Open"}
            </ButtonLink>
          }
        >
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={STATE_TONES[entry.state] ?? "neutral"}>
              {STATE_LABELS[entry.state] ?? entry.state}
            </Badge>
            <Badge tone={entry.remarks_written >= entry.roll ? "good" : "neutral"}>
              {entry.remarks_written} of {entry.roll} remarks written
            </Badge>
          </div>
        </Panel>
      ))}
    </>
  );
}
