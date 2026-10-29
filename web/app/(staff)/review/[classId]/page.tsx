"use client";

/**
 * One class under review (§8.4).
 *
 * "Opening one shows each pupil's card as the parent will see it, with fields
 * for the remark, the optional position text, and, in third term, the
 * promotion decision. Approve, or return with a note."
 *
 * Two things this screen is careful about:
 *
 * - **Approval is irreversible.** §4.5 freezes every grade at that moment and
 *   nothing recomputes one afterwards, so the button asks first and says what
 *   it is about to do — including which grading scale the grades will be
 *   frozen against.
 * - **A grade shown here may be live or frozen.** `is_snapshot` says which,
 *   and the screen says so too: before approval the letter follows the active
 *   scale, after it the letter is what the card says for ever.
 */

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Badge, Button, Notice, Panel, Spinner, TextArea } from "@/components/ui";
import { ApiError } from "@/lib/api/client";
import type { Approval, Card, CardSubjectRow } from "@/lib/api/head";
import { useHeadApi } from "@/lib/api/use-head";
import { pupilName } from "@/lib/format";
import { useResource } from "@/lib/use-async";

function plain(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const asNumber = Number(value);
  return Number.isFinite(asNumber) ? String(asNumber) : String(value);
}

const HALVES = [
  ["first_half", "First Half Term"],
  ["second_half", "Second Half Term"],
] as const;

export default function ClassReviewPage() {
  const api = useHeadApi();
  const { classId } = useParams<{ classId: string }>();
  const termId = useSearchParams().get("term") ?? undefined;

  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"approve" | "return" | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [approved, setApproved] = useState<Approval["snapshot"] | null>(null);
  const [confirming, setConfirming] = useState(false);

  const review = useResource(
    (signal) => api!.review(classId, termId ?? "", signal),
    [api, classId, termId],
    { enabled: Boolean(api) },
  );

  if (review.loading) return <Spinner label="Loading the class…" />;
  if (review.error) return <Notice>{review.error}</Notice>;
  if (!review.data || !api) return null;

  const data = review.data;
  const cards = data.cards ?? [];
  const term = termId ?? data.term_id;

  async function run(what: "approve" | "return") {
    setBusy(what);
    setFailure(null);
    try {
      if (what === "approve") {
        const result = await api!.approve(classId, term);
        setApproved(result.snapshot);
        setConfirming(false);
      } else {
        await api!.returnClass(classId, term, note);
        setNote("");
      }
      review.reload();
    } catch (caught) {
      setFailure(caught instanceof ApiError ? caught.message : "Could not do that.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <div>
        <Link href="/review" className="text-sm text-[var(--muted)] hover:underline">
          ← Review queue
        </Link>
        <h1 className="text-lg font-semibold">{data.class_name}</h1>
        <p className="text-sm text-[var(--muted)]">
          {data.term_label} · {cards.length} pupil{cards.length === 1 ? "" : "s"}
        </p>
      </div>

      {failure ? <Notice tone="error">{failure}</Notice> : null}

      {approved ? (
        <Notice tone="success">
          Approved. {approved.graded} of {approved.rows} score rows were graded against{" "}
          <strong>{approved.grading_scale_name}</strong>
          {approved.ungraded > 0
            ? `, and ${approved.ungraded} had no average to grade`
            : ""}
          . Those grades are now fixed and will not change if the scale does.
        </Notice>
      ) : null}

      {data.state === "approved" ? (
        <Notice tone="info">
          This class is approved. Its grades are frozen against the scale that was active at
          the time, and an administrator publishes it from here.
        </Notice>
      ) : null}

      {data.state === "returned" ? (
        <Notice tone="warning">
          Returned to the class teacher: {data.return_note}
        </Notice>
      ) : null}

      {cards.map((card) => (
        <PupilCard
          key={card.pupil_id}
          card={card}
          promotionApplies={data.promotion_applies}
          editable={data.state === "submitted" || data.state === "approved"}
          onSave={async (row) => {
            await api.saveRemarks(classId, term, [row]);
            review.reload();
          }}
        />
      ))}

      {data.state === "submitted" ? (
        <Panel title="Approve or return">
          <div className="flex flex-col gap-4">
            {confirming ? (
              <Notice tone="warning">
                <div className="flex flex-col gap-2">
                  <span>
                    Approving freezes every grade in this class against the grading scale
                    that is active now. If the school later changes a band, these cards will
                    keep saying what they say today — that is deliberate, and it cannot be
                    undone here.
                  </span>
                  <span className="flex gap-2">
                    <Button onClick={() => void run("approve")} disabled={busy !== null}>
                      {busy === "approve" ? "Approving…" : "Yes, approve and freeze the grades"}
                    </Button>
                    <Button variant="secondary" onClick={() => setConfirming(false)}>
                      Cancel
                    </Button>
                  </span>
                </div>
              </Notice>
            ) : (
              <Button onClick={() => setConfirming(true)} disabled={busy !== null}>
                Approve this class
              </Button>
            )}

            <div className="flex flex-col gap-2 border-t border-[var(--border)] pt-4">
              <label htmlFor="return-note" className="text-sm font-medium">
                Or return it with a note
              </label>
              <TextArea
                id="return-note"
                value={note}
                onChange={(event) => setNote(event.target.value)}
                rows={3}
                placeholder="Say what needs changing — the teacher has the whole class to look through otherwise."
              />
              <Button
                variant="secondary"
                onClick={() => void run("return")}
                disabled={busy !== null || note.trim() === ""}
                className="self-start"
              >
                {busy === "return" ? "Returning…" : "Return to the class teacher"}
              </Button>
            </div>
          </div>
        </Panel>
      ) : null}
    </>
  );
}

function PupilCard({
  card,
  promotionApplies,
  editable,
  onSave,
}: {
  card: Card;
  promotionApplies: boolean;
  editable: boolean;
  onSave: (row: {
    pupil_id: string;
    head_teacher_remark?: string | null;
    position_text?: string | null;
    promotion_decision?: string | null;
  }) => Promise<void>;
}) {
  const [remark, setRemark] = useState(card.head_teacher_remark ?? "");
  const [position, setPosition] = useState(card.position_text ?? "");
  const [promotion, setPromotion] = useState(card.promotion_decision ?? "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const subjects = card.subjects ?? [];

  return (
    <Panel
      title={pupilName(card)}
      description={`${card.admission_number}${card.house_name ? ` · ${card.house_name} House` : ""}${
        card.no_in_class ? ` · ${card.no_in_class} in class` : ""
      }`}
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap gap-2 text-xs">
          <Badge tone="neutral">
            Overall {plain(card.overall_percentage)}
            {card.overall_percentage ? "%" : ""}
          </Badge>
          {card.attendance ? (
            <Badge tone="neutral">
              Present {card.attendance.times_present}/{card.attendance.times_school_opened}
            </Badge>
          ) : null}
          {card.growth ? (
            <Badge tone="neutral">
              {plain(card.growth.height_end_m)}m · {plain(card.growth.weight_end_kg)}kg
            </Badge>
          ) : null}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[34rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] text-left">
                <th className="py-2 pr-4 font-medium text-[var(--muted)]">Subject</th>
                {HALVES.map(([key, label]) => (
                  <th key={key} className="py-2 pr-4 font-medium text-[var(--muted)]">
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {subjects.map((row) => (
                <SubjectLine key={row.class_subject_id} row={row} />
              ))}
            </tbody>
          </table>
        </div>

        {(card.narrative ?? []).length > 0 ? (
          <details className="rounded-md border border-[var(--border)] px-3 py-2">
            <summary className="cursor-pointer text-sm font-medium">
              Written assessment
            </summary>
            <dl className="mt-2 flex flex-col gap-2">
              {(card.narrative ?? []).map((passage) => (
                <div key={passage.section_id}>
                  <dt className="text-xs font-medium text-[var(--muted)]">{passage.label}</dt>
                  <dd className="text-sm">{passage.body ?? "—"}</dd>
                </div>
              ))}
            </dl>
          </details>
        ) : null}

        {card.class_teacher_comment ? (
          <p className="text-sm">
            <span className="text-xs uppercase tracking-wide text-[var(--muted)]">
              Class teacher
            </span>
            <br />
            {card.class_teacher_comment}
          </p>
        ) : null}

        <div className="flex flex-col gap-2 border-t border-[var(--border)] pt-3">
          <label htmlFor={`remark-${card.pupil_id}`} className="text-sm font-medium">
            Head teacher&rsquo;s remark
          </label>
          <TextArea
            id={`remark-${card.pupil_id}`}
            value={remark}
            onChange={(event) => {
              setRemark(event.target.value);
              setSaved(false);
            }}
            rows={2}
            disabled={!editable}
          />

          <div className="flex flex-wrap gap-3">
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">Position (in grades)</span>
              <input
                value={position}
                onChange={(event) => {
                  setPosition(event.target.value);
                  setSaved(false);
                }}
                disabled={!editable}
                placeholder="Optional"
                className="rounded-md border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-sm"
              />
            </label>

            {promotionApplies ? (
              <label className="flex flex-col gap-1 text-sm">
                <span className="font-medium">Promotion</span>
                <input
                  value={promotion}
                  onChange={(event) => {
                    setPromotion(event.target.value);
                    setSaved(false);
                  }}
                  disabled={!editable}
                  placeholder="Third term only"
                  className="rounded-md border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-sm"
                />
              </label>
            ) : null}
          </div>

          <div className="flex items-center gap-3">
            <Button
              variant="secondary"
              disabled={!editable || saving}
              onClick={async () => {
                setSaving(true);
                try {
                  await onSave({
                    pupil_id: card.pupil_id,
                    head_teacher_remark: remark.trim() === "" ? null : remark,
                    position_text: position.trim() === "" ? null : position,
                    ...(promotionApplies
                      ? { promotion_decision: promotion.trim() === "" ? null : promotion }
                      : {}),
                  });
                  setSaved(true);
                } finally {
                  setSaving(false);
                }
              }}
            >
              {saving ? "Saving…" : "Save"}
            </Button>
            {saved ? <span className="text-xs text-[var(--success)]">Saved</span> : null}
          </div>
        </div>
      </div>
    </Panel>
  );
}

function SubjectLine({ row }: { row: CardSubjectRow }) {
  if (row.is_group) {
    // R7: a heading spans its sub-rows and carries no figures of its own.
    return (
      <tr className="border-b border-[var(--border)]">
        <td colSpan={3} className="py-2 pr-4 text-sm font-semibold">
          {row.subject_name}
        </td>
      </tr>
    );
  }

  return (
    <tr className="border-b border-[var(--border)] last:border-0">
      <td className="py-2 pr-4">{row.subject_name}</td>
      {HALVES.map(([key]) => {
        const half = row.halves?.[key];
        if (!half) {
          return (
            <td key={key} className="py-2 pr-4 text-[var(--muted)]">
              —
            </td>
          );
        }
        return (
          <td key={key} className="py-2 pr-4 tabular-nums">
            {plain(half.period_average)}
            {half.grade_letter ? (
              <span className="ml-2">
                <Badge tone={half.is_snapshot ? "good" : "neutral"}>{half.grade_letter}</Badge>
              </span>
            ) : null}
          </td>
        );
      })}
    </tr>
  );
}
