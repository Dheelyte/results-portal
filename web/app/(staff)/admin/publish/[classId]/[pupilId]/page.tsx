"use client";

/**
 * One pupil's scores after publication, and R13's correction (§7, §4.9).
 *
 * "Admin only, reason required, audited." The reason is mandatory in the form
 * because it is mandatory in §4.9, and the response says whether the grade
 * moved — which is the question the admin is actually asking, because it
 * decides whether the card has to be reprinted.
 *
 * Also the one place the printable card can be opened outside the parent's
 * portal: §9 says the school will compare this output to the paper line by
 * line, and this is where someone doing that is already standing.
 *
 * Its own route since the redesign (D104). Correcting a frozen score is the
 * most consequential thing on these screens and it used to happen in a strip
 * that unfolded inside a list row.
 */

import { FileDown, Pencil } from "lucide-react";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";

import {
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  Notice,
  PageHeader,
  Panel,
  Select,
  SkeletonPanel,
  SkeletonTable,
  TextArea,
} from "@/components/ui";
import type { AdminApi, CorrectableRow } from "@/lib/api/admin";
import { ApiError } from "@/lib/api/client";
import { useAdminApi } from "@/lib/api/use-admin";
import { HALF_LABELS, joinParts, TERM_LABELS } from "@/lib/format";
import { useResource } from "@/lib/use-async";

export default function PupilCorrectionsPage() {
  const api = useAdminApi();
  const { classId, pupilId } = useParams<{ classId: string; pupilId: string }>();
  const search = useSearchParams();

  const terms = useResource(() => api!.terms(), [api], { enabled: Boolean(api) });
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
  const rows = useResource(() => api!.pupilEntries(pupilId, termId), [api, pupilId, termId], {
    enabled: Boolean(api) && Boolean(termId),
  });

  const [open, setOpen] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const report = (publication.data?.reports ?? []).find(
    (candidate) => candidate.pupil_id === pupilId,
  );
  const term = terms.data?.find((item) => item.id === termId);
  const termLabel = term ? (TERM_LABELS[term.number] ?? term.number) : "";

  const classHref = `/admin/publish/${classId}?term=${termId}`;
  const crumbs = [
    { label: "Publish", href: "/admin/publish" },
    { label: publication.data?.class_name ?? "Class", href: classHref },
    { label: report?.name ?? "Pupil" },
  ];
  const back = { href: classHref, label: publication.data?.class_name ?? "Class" };

  if (!api || terms.loading || publication.loading) {
    return (
      <>
        <PageHeader breadcrumbs={crumbs} back={back} title="Pupil" />
        <SkeletonPanel rows={8} label="Loading the pupil…" />
      </>
    );
  }

  if (publication.error) {
    return (
      <>
        <PageHeader breadcrumbs={crumbs} back={back} title="Pupil" />
        <Notice>{publication.error}</Notice>
      </>
    );
  }

  if (!report) {
    return (
      <>
        <PageHeader breadcrumbs={crumbs} back={back} title="Pupil" />
        <Notice tone="info">
          That pupil is not on this class&rsquo;s roll for this term.
        </Notice>
      </>
    );
  }

  const entries = rows.data?.rows ?? [];

  return (
    <>
      <PageHeader
        breadcrumbs={crumbs}
        back={back}
        title={report.name}
        description={joinParts(report.admission_number, termLabel)}
        badge={
          <Badge
            tone={
              report.state === "published"
                ? "good"
                : report.state === "withheld"
                  ? "bad"
                  : "neutral"
            }
          >
            {report.state === "draft" ? "not published" : report.state}
          </Badge>
        }
      />

      {done ? <Notice tone="success">{done}</Notice> : null}

      <CardDownloads api={api} pupilId={pupilId} termId={termId} />

      <Panel
        title="Scores"
        icon={Pencil}
        description="A grade frozen at approval is re-resolved against the scale it was frozen against, never today's (§4.5, R13)."
        bare
      >
        {rows.loading ? (
          <div className="px-5 py-4">
            <SkeletonTable rows={6} columns={3} label="Loading the scores…" />
          </div>
        ) : rows.error ? (
          <div className="px-5 py-4">
            <Notice>{rows.error}</Notice>
          </div>
        ) : entries.length === 0 ? (
          <div className="px-5 py-4">
            <EmptyState
              title="No scores recorded for this term"
              description="Nothing has been entered against this pupil yet, so there is nothing to correct."
            />
          </div>
        ) : (
          <ul className="flex flex-col divide-y divide-[var(--border)]">
            {entries.map((row) => (
              <li key={row.entry_id} className="flex flex-col gap-2 px-5 py-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <span className="block truncate text-sm font-medium">
                      {row.subject_name}
                    </span>
                    <span className="block text-xs text-[var(--muted)]">
                      {HALF_LABELS[row.half] ?? row.half} · average{" "}
                      <span className="tabular-nums">{row.period_average ?? "—"}</span>
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    {row.grade_letter ? (
                      <Badge tone={row.is_snapshot ? "good" : "neutral"}>
                        {row.grade_letter}
                        {row.is_snapshot ? " · frozen" : ""}
                      </Badge>
                    ) : null}
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setOpen(open === row.entry_id ? null : row.entry_id)}
                    >
                      {open === row.entry_id ? "Cancel" : "Correct"}
                    </Button>
                  </div>
                </div>

                {open === row.entry_id ? (
                  <CorrectionForm
                    api={api}
                    row={row}
                    onDone={(message) => {
                      setOpen(null);
                      rows.reload();
                      publication.reload();
                      setDone(message);
                    }}
                  />
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </>
  );
}

/* ------------------------------------------------------------------------- */

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
    <Card className="flex flex-col gap-3 p-3">
      {failure ? <Notice tone="error">{failure}</Notice> : null}

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Column">
          <Select value={column} onChange={(event) => setColumn(event.target.value)}>
            {(row.columns ?? []).map((name) => (
              <option key={name} value={name}>
                {name.replace(/_/g, " ")}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="New value">
          <Input
            value={value}
            onChange={(event) => setValue(event.target.value)}
            inputMode="decimal"
            className="text-right tabular-nums"
          />
        </Field>
      </div>

      <Field label="Reason" hint="Required, and recorded in the audit log (§4.9).">
        <TextArea value={reason} onChange={(event) => setReason(event.target.value)} rows={2} />
      </Field>

      <Button
        loading={busy}
        disabled={reason.trim() === "" || value.trim() === ""}
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
        Correct it
      </Button>
    </Card>
  );
}

/* ------------------------------------------------------------------------- */

/**
 * Opens the printable card (§9).
 *
 * The PDF arrives as a blob rather than through a link, because the
 * endpoint needs an Authorization header and a browser following an anchor
 * sends none.
 */
function CardDownloads({
  api,
  pupilId,
  termId,
}: {
  api: AdminApi;
  pupilId: string;
  termId: string;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  async function open(half: "first_half" | "second_half") {
    setBusy(half);
    setFailure(null);
    let objectUrl: string | null = null;
    try {
      objectUrl = await api.cardBlobUrl(pupilId, termId, half);
      window.open(objectUrl, "_blank", "noopener");
    } catch (caught) {
      setFailure(caught instanceof ApiError ? caught.message : "Could not open the card.");
    } finally {
      setBusy(null);
      // Released later, not immediately: revoking at once can beat the new
      // tab to the data.
      const toRelease = objectUrl;
      if (toRelease) window.setTimeout(() => URL.revokeObjectURL(toRelease), 60_000);
    }
  }

  return (
    <Panel
      title="The printable card"
      icon={FileDown}
      description="§9's card, exactly as a parent would download it. Opens in a new tab."
    >
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="secondary"
          icon={FileDown}
          loading={busy === "first_half"}
          disabled={busy !== null}
          onClick={() => void open("first_half")}
        >
          First half term
        </Button>
        <Button
          variant="secondary"
          icon={FileDown}
          loading={busy === "second_half"}
          disabled={busy !== null}
          onClick={() => void open("second_half")}
        >
          Second half term
        </Button>
      </div>
      {failure ? (
        <div className="mt-3">
          <Notice tone="error">{failure}</Notice>
        </div>
      ) : null}
    </Panel>
  );
}
