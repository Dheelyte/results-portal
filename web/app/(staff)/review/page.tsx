"use client";

/**
 * The review queue (§8.4).
 *
 * "Queue of submitted classes." Longest-waiting first, because the queue is
 * worked through rather than browsed — the class that has been waiting
 * longest is the one holding up the release.
 */

import {
  CheckCheck,
  ClipboardCheck,
  CornerUpLeft,
  Hourglass,
  Inbox,
  PenLine,
} from "lucide-react";

import {
  Badge,
  ButtonLink,
  EmptyState,
  Notice,
  PageHeader,
  Panel,
  Skeleton,
  SkeletonPanel,
  StatCard,
  StatRow,
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
        <StatRow>
          {Array.from({ length: 4 }, (_, index) => (
            <Skeleton key={index} className="h-[8.5rem] rounded-xl" />
          ))}
        </StatRow>
        <SkeletonPanel rows={3} label="Loading the queue…" />
        <SkeletonPanel rows={3} />
      </>
    );
  }
  if (queue.error) return <Notice>{queue.error}</Notice>;
  if (!queue.data) return null;

  const waiting = queue.data.filter((entry) => entry.state === "submitted");
  const approved = queue.data.filter((entry) => entry.state === "approved");
  const returned = queue.data.filter((entry) => entry.state === "returned");

  // Remarks across the **whole** queue, not just what is waiting: §8.4 lets
  // the head teacher write a remark on an approved class too, right up until
  // the admin publishes it, so counting only submitted classes would show a
  // dash on a term with real work left in it. Both figures come off the queue
  // the page has already fetched, so the cards cost no extra request (D113).
  const pupilsInQueue = queue.data.reduce((total, entry) => total + entry.roll, 0);
  const remarksWritten = queue.data.reduce(
    (total, entry) => total + entry.remarks_written,
    0,
  );

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

      <StatRow>
        {/* Waiting is the head teacher's whole job, so it leads and it is the
            one card allowed to be amber — and only when there is something
            on it. Nothing waiting is a finished state, not a neutral one. */}
        <StatCard
          tone={waiting.length === 0 ? "good" : "warn"}
          icon={waiting.length === 0 ? CheckCheck : Hourglass}
          value={waiting.length === 0 ? "Clear" : waiting.length}
          label={waiting.length === 0 ? "Nothing waiting" : "Waiting for you"}
          hint={
            waiting.length === 0
              ? "Every submitted class is dealt with"
              : `${waiting.length === 1 ? "class" : "classes"} submitted for review`
          }
        />
        <StatCard
          icon={PenLine}
          value={pupilsInQueue === 0 ? "0" : `${remarksWritten}/${pupilsInQueue}`}
          label="Remarks written"
          hint={
            pupilsInQueue === 0
              ? "No class in the queue yet"
              : `across ${pupilsInQueue} ${pupilsInQueue === 1 ? "pupil" : "pupils"}`
          }
        />
        {/* Green only when there is something to be green about: a green
            tile reading 0 claims an achievement that has not happened. */}
        <StatCard
          tone={approved.length === 0 ? "neutral" : "good"}
          icon={ClipboardCheck}
          value={approved.length}
          label={approved.length === 1 ? "Class approved" : "Classes approved"}
          hint={
            approved.length === 0
              ? "None approved this term yet"
              : "Grades frozen, ready to publish"
          }
        />
        <StatCard
          tone={returned.length === 0 ? "neutral" : "bad"}
          icon={CornerUpLeft}
          value={returned.length}
          label="Returned to teachers"
          hint={
            returned.length === 0
              ? "Nothing sent back"
              : "Waiting on a class teacher"
          }
        />
      </StatRow>

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
            {entry.decision_blocked ? <Badge tone="neutral">An admin decides</Badge> : null}
            <Badge tone={entry.remarks_written >= entry.roll ? "good" : "neutral"}>
              {entry.remarks_written} of {entry.roll} remarks written
            </Badge>
          </div>
        </Panel>
      ))}
    </>
  );
}
