"use client";

/**
 * Publishing one class (§6 R12, §7).
 *
 * Publishing acts on a class; withholding and releasing act on individuals.
 * The screen is built around that asymmetry — one button for the class, and a
 * per-pupil control for the exceptions — because the exception is what the
 * admin is actually here to manage.
 *
 * What a withheld parent sees is R12's one sentence and nothing else. The
 * reason typed here is the school's own record, shown on this screen and in
 * the audit log, and never sent to a parent.
 *
 * R13's correction form is one level further down,
 * `/admin/publish/[classId]/[pupilId]` — it is a different job from
 * publishing, needs a reason on every change, and used to expand inside a
 * row of forty (docs/DECISIONS.md D104).
 */

import { Eye, Send, Undo2 } from "lucide-react";
import { useParams, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import {
  Badge,
  Button,
  ButtonLink,
  Card,
  Notice,
  PageHeader,
  Panel,
  SkeletonPanel,
  TextArea,
} from "@/components/ui";
import { ApiError } from "@/lib/api/client";
import type { ReportState } from "@/lib/api/admin";
import { useAdminApi } from "@/lib/api/use-admin";
import { formatDateTime, TERM_LABELS } from "@/lib/format";
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

export default function PublishClassPage() {
  const api = useAdminApi();
  const { classId } = useParams<{ classId: string }>();
  const search = useSearchParams();

  const terms = useResource(() => api!.terms(), [api], { enabled: Boolean(api) });
  // The term comes from the URL, so this page is a thing you can link to.
  // Falling back to the current term keeps a hand-typed URL working.
  const termId =
    search.get("term") ||
    terms.data?.find((term) => term.is_current)?.id ||
    terms.data?.[0]?.id ||
    "";

  const publication = useResource(
    () => api!.publication(classId, termId),
    [api, classId, termId],
    { enabled: Boolean(api) && Boolean(termId) },
  );

  const [withhold, setWithhold] = useState<Set<string>>(new Set());
  const [reason, setReason] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [rowBusy, setRowBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const reports = useMemo(() => publication.data?.reports ?? [], [publication.data]);
  const held = reports.filter((report) => report.state === "withheld");
  const ready = publication.data?.workflow_state === "approved";
  const term = terms.data?.find((item) => item.id === termId);
  const termLabel = term ? (TERM_LABELS[term.number] ?? term.number) : "";

  async function act(run: () => Promise<unknown>, message: string) {
    setFailure(null);
    setDone(null);
    try {
      await run();
      setDone(message);
      publication.reload();
      return true;
    } catch (caught) {
      setFailure(caught instanceof ApiError ? caught.message : "Could not do that.");
      return false;
    }
  }

  const crumbs = [
    { label: "Publish", href: "/admin/publish" },
    { label: publication.data?.class_name ?? "Class" },
  ];
  const back = { href: "/admin/publish", label: "Publish" };

  if (!api || terms.loading || publication.loading) {
    return (
      <>
        <PageHeader breadcrumbs={crumbs} back={back} title="Class" />
        <SkeletonPanel rows={10} label="Loading the class…" />
      </>
    );
  }

  if (publication.error) {
    return (
      <>
        <PageHeader breadcrumbs={crumbs} back={back} title="Class" />
        <Notice>{publication.error}</Notice>
      </>
    );
  }

  if (!publication.data) {
    return (
      <>
        <PageHeader breadcrumbs={crumbs} back={back} title="Class" />
        <Notice tone="info">Pick a class and a term from the publish screen.</Notice>
      </>
    );
  }

  return (
    <>
      <PageHeader
        breadcrumbs={crumbs}
        back={back}
        title={publication.data.class_name}
        description={`${termLabel} · ${reports.length} report${
          reports.length === 1 ? "" : "s"
        }${held.length > 0 ? ` · ${held.length} held back` : ""}`}
        badge={
          <Badge tone={ready ? "good" : "warn"}>
            {publication.data.workflow_state.replace(/_/g, " ")}
          </Badge>
        }
      />

      {failure ? <Notice tone="error">{failure}</Notice> : null}
      {done ? <Notice tone="success">{done}</Notice> : null}

      {!ready ? (
        <Notice tone="warning">
          This class is {publication.data.workflow_state.replace(/_/g, " ")}. The head
          teacher approves a class before it can be published (§1.6).
        </Notice>
      ) : null}

      {ready ? (
        <Panel
          title="Publish the class"
          icon={Send}
          description="Ticked pupils are held back. They can be released individually later."
        >
          <div className="flex flex-col gap-3">
            {withhold.size > 0 ? (
              <label className="flex flex-col gap-1.5 text-sm">
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
              icon={Send}
              loading={publishing}
              disabled={withhold.size > 0 && reason.trim() === ""}
              className="self-start"
              onClick={async () => {
                setPublishing(true);
                const published = await act(async () => {
                  const outcome = await api.publishClass(classId, termId, {
                    withhold_pupil_ids: [...withhold],
                    reason: reason.trim() === "" ? null : reason,
                  });
                  return outcome;
                }, "Published.");
                if (published) {
                  setWithhold(new Set());
                  setReason("");
                }
                setPublishing(false);
              }}
            >
              Publish this class
            </Button>

            <p className="text-xs text-[var(--muted)]">
              §11 takes a database dump before the first row moves, so this takes a moment.
            </p>
          </div>
        </Panel>
      ) : null}

      <Panel
        title="Pupils"
        description="Open a pupil to correct a score (R13) or to see the printable card."
        bare
      >
        <ul className="flex flex-col divide-y divide-[var(--border)]">
          {reports.map((report) => (
            <ReportRow
              key={report.report_id}
              report={report}
              classId={classId}
              termId={termId}
              busy={rowBusy === report.report_id}
              anyBusy={rowBusy !== null || publishing}
              selected={withhold.has(report.pupil_id)}
              onToggle={(on) =>
                setWithhold((current) => {
                  const next = new Set(current);
                  if (on) next.add(report.pupil_id);
                  else next.delete(report.pupil_id);
                  return next;
                })
              }
              onRelease={async () => {
                setRowBusy(report.report_id);
                await act(
                  () => api.releaseReport(report.report_id),
                  `${report.name}'s result has been released.`,
                );
                setRowBusy(null);
              }}
              onWithhold={async (why) => {
                setRowBusy(report.report_id);
                await act(
                  () => api.withholdReport(report.report_id, why),
                  `${report.name}'s result has been held back.`,
                );
                setRowBusy(null);
              }}
            />
          ))}
        </ul>
      </Panel>
    </>
  );
}

function ReportRow({
  report,
  classId,
  termId,
  busy,
  anyBusy,
  selected,
  onToggle,
  onRelease,
  onWithhold,
}: {
  report: ReportState;
  classId: string;
  termId: string;
  busy: boolean;
  anyBusy: boolean;
  selected: boolean;
  onToggle: (on: boolean) => void;
  onRelease: () => void;
  onWithhold: (reason: string) => void;
}) {
  const [why, setWhy] = useState("");
  const [asking, setAsking] = useState(false);

  return (
    <li className="flex flex-col gap-2 px-5 py-3">
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
            <Button
              variant="secondary"
              size="sm"
              icon={Undo2}
              loading={busy}
              disabled={anyBusy}
              onClick={onRelease}
            >
              Release
            </Button>
          ) : null}

          {report.state === "published" ? (
            <Button
              variant="secondary"
              size="sm"
              disabled={anyBusy}
              onClick={() => setAsking(!asking)}
            >
              {asking ? "Cancel" : "Hold back"}
            </Button>
          ) : null}

          {report.state === "draft" ? (
            <label className="flex items-center gap-1.5 text-xs text-[var(--muted)]">
              <input
                type="checkbox"
                checked={selected}
                onChange={(event) => onToggle(event.target.checked)}
              />
              hold back
            </label>
          ) : null}

          <ButtonLink
            href={`/admin/publish/${classId}/${report.pupil_id}?term=${termId}`}
            size="sm"
            icon={Eye}
          >
            Open
          </ButtonLink>
        </div>
      </div>

      {report.withheld_reason ? (
        <p className="text-xs text-[var(--muted)]">
          Held back: {report.withheld_reason} — the parent is not shown this.
        </p>
      ) : null}

      {asking ? (
        <Card className="flex flex-wrap items-end gap-2 p-3">
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
            size="sm"
            loading={busy}
            disabled={anyBusy || why.trim() === ""}
            onClick={() => {
              onWithhold(why);
              setWhy("");
              setAsking(false);
            }}
          >
            Hold it back
          </Button>
        </Card>
      ) : null}
    </li>
  );
}
