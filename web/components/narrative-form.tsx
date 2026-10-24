"use client";

/**
 * The narrative writing screen (ARCHITECTURE.md §8.2).
 *
 * "This is the heaviest task in the system — sixteen passages per pupil, 480
 * for a class of 30 — and it belongs to one person, the class teacher."
 *
 * Every control here is in the specification, and each one is there because
 * of how much writing this is:
 *
 * - **One pupil, every section on a page**, with previous/next navigation, so
 *   the teacher holds one child in mind rather than one section.
 * - **A phrase bank button beside each section**, scoped to that section.
 *   §4.6 calls the bank core, not optional, for exactly this reason.
 * - **Copy this section from the previous pupil.** §8.2: "They will otherwise
 *   do it through the clipboard anyway, and an explicit control is honest
 *   about it."
 * - **A character count**, because the card has finite room.
 * - **Autosave and localStorage drafts, exactly as the grid** — the same two
 *   modules, so there is one implementation of "save every twenty seconds and
 *   recover on reload" in the project.
 *
 * Sections this teacher does not own are shown read-only rather than hidden
 * (D15): a specialist writing one curriculum area needs to see what the class
 * teacher said about the same child, and the class teacher needs to see that
 * the specialist's section is being handled by somebody.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Badge, Notice } from "@/components/ui";
import { ApiError } from "@/lib/api/client";
import type { PassageSave, Phrase, PupilNarrative, TeacherApi } from "@/lib/api/teacher";
import { clearDraft, readDraft, unreconciled, writeDraft, type Draft } from "@/lib/drafts";
import { countCells, isEmpty, merge, type Cells } from "@/lib/scores";
import { autosaveLabel, useAutosave } from "@/lib/use-autosave";

/** One row of the draft store per pupil, keyed by section id. */
const ROW = "sections";

function savedCells(page: PupilNarrative): Cells {
  const row: Record<string, string> = {};
  for (const passage of page.passages ?? []) {
    row[passage.section_id] = passage.body ?? "";
  }
  return { [ROW]: row };
}

export function NarrativeForm({
  page,
  api,
  termId,
  onMoved,
}: {
  page: PupilNarrative;
  api: TeacherApi;
  termId: string;
  onMoved: (pupilId: string) => void;
}) {
  const saved = useMemo(() => savedCells(page), [page]);

  const [values, setValues] = useState<Cells>(saved);
  const [dirty, setDirty] = useState<Cells>({});
  const [rejections, setRejections] = useState<Record<string, string>>({});
  const [recovered, setRecovered] = useState<Draft | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [openBank, setOpenBank] = useState<string | null>(null);

  const locked = !page.editable;
  const pupilId = page.pupil_id;

  /* --- Draft recovery, the same contract as the grid ------------------ */
  useEffect(() => {
    const draft = readDraft(pupilId, termId);
    if (!draft) return;

    const pending = unreconciled(draft.values, saved);
    if (isEmpty(pending)) {
      clearDraft(pupilId, termId);
      return;
    }
    setValues((current) => merge(current, pending));
    setDirty((current) => merge(current, pending));
    setRecovered({ values: pending, at: draft.at });
  }, [pupilId, termId, saved]);

  useEffect(() => {
    writeDraft(pupilId, termId, dirty);
  }, [pupilId, termId, dirty]);

  const dirtyCount = countCells(dirty);

  const save = useCallback(async () => {
    const row = dirty[ROW] ?? {};
    const passages: PassageSave[] = Object.entries(row).map(([sectionId, body]) => ({
      section_id: sectionId,
      // An emptied textarea clears the passage; the API distinguishes that
      // from a section not sent at all.
      body: body.trim() === "" ? null : body,
    }));
    if (passages.length === 0) return;

    const sent = passages.map((passage) => passage.section_id);
    try {
      await api.savePupilNarrative(pupilId, termId, passages);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 422) {
        const flat: Record<string, string> = {};
        for (const [sectionId, fields] of Object.entries(caught.rows ?? {})) {
          flat[sectionId] = Object.values(fields)[0] ?? "This section was refused.";
        }
        setRejections(flat);
      }
      setFailure(caught instanceof ApiError ? caught.message : "Could not save.");
      throw caught;
    }

    setRejections({});
    setFailure(null);
    setDirty((current) => {
      const remaining = { ...(current[ROW] ?? {}) };
      for (const sectionId of sent) delete remaining[sectionId];
      const next: Cells = {};
      if (Object.keys(remaining).length) next[ROW] = remaining;
      return next;
    });
    clearDraft(pupilId, termId);
  }, [api, dirty, pupilId, termId]);

  const autosave = useAutosave({
    hasPending: dirtyCount > 0,
    save,
    isRetryable: (error) => !(error instanceof ApiError && error.status === 422),
    enabled: !locked,
  });

  const change = useCallback(
    (sectionId: string, text: string) => {
      setValues((current) => ({ [ROW]: { ...(current[ROW] ?? {}), [sectionId]: text } }));
      setDirty((current) => {
        const row = { ...(current[ROW] ?? {}) };
        if (text === (saved[ROW]?.[sectionId] ?? "")) delete row[sectionId];
        else row[sectionId] = text;
        const next: Cells = {};
        if (Object.keys(row).length) next[ROW] = row;
        return next;
      });
      setRejections((current) => {
        const next = { ...current };
        delete next[sectionId];
        return next;
      });
    },
    [saved],
  );

  /**
   * Move to another pupil, saving first.
   *
   * The draft would survive the move either way, but a teacher who presses
   * "next pupil" has finished this one — leaving the work unsaved for up to
   * twenty seconds while the page changes under it invites exactly the
   * confusion the draft exists to prevent.
   */
  const moveTo = useCallback(
    async (target: string | null) => {
      if (!target) return;
      if (dirtyCount > 0) {
        try {
          await save();
        } catch {
          return; // the notice is already on screen; do not lose the text
        }
      }
      onMoved(target);
    },
    [dirtyCount, onMoved, save],
  );

  // Grouped as the card groups them: the seven curriculum areas under "Area
  // of Curriculum", then B through J with no heading of their own (§1.4).
  const groups = useMemo(() => {
    const passages = page.passages ?? [];
    const seen: Array<{ label: string | null; items: typeof passages }> = [];
    for (const passage of passages) {
      const label = passage.group_label ?? null;
      const last = seen.at(-1);
      if (last && last.label === label) last.items.push(passage);
      else seen.push({ label, items: [passage] });
    }
    return seen;
  }, [page.passages]);

  return (
    <div className="flex flex-col gap-5">
      {recovered ? (
        <Notice tone="warning">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span>
              Recovered {countCells(recovered.values)} unsaved{" "}
              {countCells(recovered.values) === 1 ? "section" : "sections"} from this device, last
              changed{" "}
              {new Date(recovered.at).toLocaleString("en-NG", { timeZone: "Africa/Lagos" })}.
            </span>
            <span className="flex gap-2">
              <button
                type="button"
                className="rounded-md border border-[var(--border)] px-3 py-1 text-sm"
                onClick={() => {
                  setValues(saved);
                  setDirty({});
                  clearDraft(pupilId, termId);
                  setRecovered(null);
                }}
              >
                Discard them
              </button>
              <button
                type="button"
                className="rounded-md border border-[var(--border)] px-3 py-1 text-sm"
                onClick={() => {
                  setRecovered(null);
                  autosave.saveNow();
                }}
              >
                Save them now
              </button>
            </span>
          </div>
        </Notice>
      ) : null}

      {locked ? (
        <Notice tone="info">
          {page.state === "submitted"
            ? "This class has been submitted for review, so the narrative is read-only. Ask the head teacher to return it if a correction is needed."
            : "This class has been approved, so the narrative is final."}
        </Notice>
      ) : null}

      {failure ? <Notice tone="error">{failure}</Notice> : null}

      <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] bg-[var(--background)] py-2">
        <p aria-live="polite" className="text-sm text-[var(--muted)]" data-testid="autosave-status">
          {autosaveLabel(autosave.state, autosave.savedAt)}
          {dirtyCount > 0 ? ` · ${dirtyCount} unsaved` : ""}
        </p>
        <div className="flex items-center gap-2">
          <Badge tone={page.complete_count === page.section_count ? "good" : "neutral"}>
            {page.complete_count} of {page.section_count} written
          </Badge>
          <button
            type="button"
            onClick={autosave.saveNow}
            disabled={locked || dirtyCount === 0 || autosave.state === "saving"}
            className="rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Save now
          </button>
        </div>
      </div>

      {groups.map((group) => (
        <section key={group.label ?? "ungrouped"} className="flex flex-col gap-4">
          {group.label ? (
            <h2 className="text-xs font-semibold uppercase tracking-widest text-[var(--muted)]">
              {group.label}
            </h2>
          ) : null}

          {group.items.map((passage) => {
            const text = values[ROW]?.[passage.section_id] ?? "";
            const error = rejections[passage.section_id];
            return (
              <div key={passage.section_id} className="flex flex-col gap-1.5">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <label
                    htmlFor={`section-${passage.section_id}`}
                    className="text-sm font-medium"
                  >
                    {passage.label}
                    {!passage.writable ? (
                      <span className="ml-2 text-xs font-normal text-[var(--muted)]">
                        written by another teacher
                      </span>
                    ) : null}
                  </label>
                  <span className="text-xs text-[var(--muted)]">{text.length} characters</span>
                </div>

                <textarea
                  id={`section-${passage.section_id}`}
                  value={text}
                  onChange={(event) => change(passage.section_id, event.target.value)}
                  onBlur={autosave.saveNow}
                  disabled={locked || !passage.writable}
                  rows={4}
                  maxLength={2000}
                  aria-invalid={error ? true : undefined}
                  className={`w-full rounded-md border bg-[var(--background)] px-3 py-2 text-sm ${
                    error ? "border-[var(--danger)]" : "border-[var(--border)]"
                  } disabled:bg-[var(--surface)] disabled:text-[var(--muted)]`}
                />

                {error ? (
                  <span role="alert" className="text-xs text-[var(--danger)]">
                    {error}
                  </span>
                ) : null}

                {passage.writable && !locked ? (
                  <div className="flex flex-wrap gap-2 text-xs">
                    <button
                      type="button"
                      onClick={() =>
                        setOpenBank(openBank === passage.section_id ? null : passage.section_id)
                      }
                      className="rounded-md border border-[var(--border)] px-2 py-1"
                    >
                      {openBank === passage.section_id ? "Hide phrases" : "Phrases"}
                    </button>

                    {page.previous_pupil_id ? (
                      <CopyFromPrevious
                        api={api}
                        termId={termId}
                        previousPupilId={page.previous_pupil_id}
                        sectionId={passage.section_id}
                        onCopied={(body) => change(passage.section_id, body)}
                      />
                    ) : null}
                  </div>
                ) : null}

                {openBank === passage.section_id ? (
                  <PhraseBank
                    api={api}
                    scope={passage.code}
                    onPick={(phrase) =>
                      change(
                        passage.section_id,
                        text.trim() === "" ? phrase : `${text.trimEnd()} ${phrase}`,
                      )
                    }
                  />
                ) : null}
              </div>
            );
          })}
        </section>
      ))}

      <nav className="flex items-center justify-between gap-3 border-t border-[var(--border)] pt-4">
        <button
          type="button"
          disabled={!page.previous_pupil_id}
          onClick={() => void moveTo(page.previous_pupil_id ?? null)}
          className="rounded-md border border-[var(--border)] px-4 py-2 text-sm disabled:opacity-40"
        >
          ← Previous pupil
        </button>
        <span className="text-sm text-[var(--muted)]">
          Pupil {page.position} of {page.roll_size}
        </span>
        <button
          type="button"
          disabled={!page.next_pupil_id}
          onClick={() => void moveTo(page.next_pupil_id ?? null)}
          className="rounded-md border border-[var(--border)] px-4 py-2 text-sm disabled:opacity-40"
        >
          Next pupil →
        </button>
      </nav>
    </div>
  );
}

/**
 * The phrase bank for one section (§4.6, §8.2).
 *
 * Fetched when opened rather than with the page: sixteen sections' worth of
 * phrases on a 3G connection would be paid for whether or not the teacher
 * uses them.
 */
function PhraseBank({
  api,
  scope,
  onPick,
}: {
  api: TeacherApi;
  scope: string;
  onPick: (phrase: string) => void;
}) {
  const [phrases, setPhrases] = useState<Phrase[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api
      .phrases(scope, controller.signal)
      .then((found) => !controller.signal.aborted && setPhrases(found))
      .catch((caught) => {
        if (!controller.signal.aborted) {
          setError(caught instanceof ApiError ? caught.message : "Could not load phrases.");
        }
      });
    return () => controller.abort();
  }, [api, scope]);

  if (error) {
    return <p className="text-xs text-[var(--danger)]">{error}</p>;
  }
  if (phrases === null) {
    return <p className="text-xs text-[var(--muted)]">Loading phrases…</p>;
  }
  if (phrases.length === 0) {
    return (
      <p className="text-xs text-[var(--muted)]">
        No phrases for this section yet. An administrator adds them under Grading &amp;
        narrative.
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-1 rounded-md border border-[var(--border)] bg-[var(--surface)] p-2">
      {phrases.map((phrase) => (
        <li key={phrase.id}>
          <button
            type="button"
            onClick={() => onPick(phrase.text)}
            className="w-full rounded px-2 py-1 text-left text-xs hover:bg-[var(--surface-raised)]"
          >
            {phrase.text}
          </button>
        </li>
      ))}
    </ul>
  );
}

/**
 * §8.2's copy control.
 *
 * Fetches the previous pupil's page on demand. The teacher may already read
 * it — it is the page they were on a moment ago — so this grants nothing new;
 * it saves a round trip through the clipboard and two page loads.
 */
function CopyFromPrevious({
  api,
  termId,
  previousPupilId,
  sectionId,
  onCopied,
}: {
  api: TeacherApi;
  termId: string;
  previousPupilId: string;
  sectionId: string;
  onCopied: (body: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const cache = useRef<PupilNarrative | null>(null);

  return (
    <>
      <button
        type="button"
        disabled={busy}
        className="rounded-md border border-[var(--border)] px-2 py-1 disabled:opacity-50"
        onClick={async () => {
          setBusy(true);
          setMessage(null);
          try {
            cache.current ??= await api.pupilNarrative(previousPupilId, termId);
            const found = (cache.current.passages ?? []).find(
              (passage) => passage.section_id === sectionId,
            );
            if (!found?.body) setMessage("The previous pupil has nothing written here yet.");
            else onCopied(found.body);
          } catch (caught) {
            setMessage(caught instanceof ApiError ? caught.message : "Could not copy.");
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Copying…" : "Copy from previous pupil"}
      </button>
      {message ? <span className="text-[var(--muted)]">{message}</span> : null}
    </>
  );
}
