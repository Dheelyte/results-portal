"use client";

/**
 * Attendance, height and weight, and the class teacher's comment (§4.7, §8.3).
 *
 * Three tables of the same roll, all written the same way: edit, autosave,
 * all-or-none, per-pupil errors. They share `useRecords` below rather than
 * each growing its own copy of that — the differences between them are the
 * columns and the validation, and nothing else.
 *
 * R9's arithmetic is mirrored in `lib/attendance.ts` so a row that does not
 * add up says so as it is typed, rather than twenty seconds later. The
 * server is still the authority.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { Notice, Panel } from "@/components/ui";
import { ApiError } from "@/lib/api/client";
import type { TeacherApi } from "@/lib/api/teacher";
import { attendanceErrors } from "@/lib/attendance";
import { countCells, merge, plain, type Cells } from "@/lib/scores";
import { autosaveLabel, useAutosave } from "@/lib/use-autosave";
import { pupilName } from "@/lib/format";

/**
 * The shared editing machinery.
 *
 * Generic over the response shape and its row type, so neither table needs a
 * cast: `rowsOf` pulls the rows out, `read` turns one into the strings its
 * inputs hold, and `validate` is the local mirror of the service's rule.
 */
interface RecordsOptions<TData, TRow> {
  load: (signal: AbortSignal) => Promise<TData>;
  save: (dirty: Cells) => Promise<TData>;
  rowsOf: (data: TData) => TRow[];
  keyOf: (row: TRow) => string;
  read: (row: TRow) => Record<string, string>;
  editable: (data: TData) => boolean;
  validate?: (values: Cells, data: TData) => Record<string, Record<string, string>>;
  deps: readonly unknown[];
}

function useRecords<TData, TRow>(options: RecordsOptions<TData, TRow>) {
  const { load, save, rowsOf, keyOf, read, editable, validate, deps } = options;

  const [data, setData] = useState<TData | null>(null);
  const [values, setValues] = useState<Cells>({});
  const [dirty, setDirty] = useState<Cells>({});
  const [rejections, setRejections] = useState<Record<string, Record<string, string>>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const absorb = useCallback(
    (found: TData) => {
      const cells: Cells = {};
      for (const row of rowsOf(found)) cells[keyOf(row)] = read(row);
      setData(found);
      setValues(cells);
    },
    [keyOf, read, rowsOf],
  );

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    load(controller.signal)
      .then((found) => !controller.signal.aborted && absorb(found))
      .catch((caught) => {
        if (!controller.signal.aborted) {
          setError(caught instanceof ApiError ? caught.message : "Could not load.");
        }
      })
      .finally(() => !controller.signal.aborted && setLoading(false));
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const localErrors = useMemo(
    () => (validate && data ? validate(values, data) : {}),
    [validate, values, data],
  );

  const run = useCallback(async () => {
    // A row the teacher is still fixing is held back rather than sent: the
    // save applies all or none, so one bad row would reject the whole class.
    const clean: Cells = Object.fromEntries(
      Object.entries(dirty).filter(([pupilId]) => !localErrors[pupilId]),
    );
    if (Object.keys(clean).length === 0) return;

    const sent = Object.keys(clean);
    try {
      absorb(await save(clean));
      setRejections({});
      setError(null);
      setDirty((current) => {
        const remaining: Cells = {};
        for (const [pupilId, row] of Object.entries(current)) {
          if (!sent.includes(pupilId)) remaining[pupilId] = row;
        }
        return remaining;
      });
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 422) setRejections(caught.rows ?? {});
      setError(caught instanceof ApiError ? caught.message : "Could not save.");
      throw caught;
    }
  }, [absorb, dirty, localErrors, save]);

  const autosave = useAutosave({
    hasPending: countCells(dirty) > 0 && Object.keys(localErrors).length === 0,
    save: run,
    isRetryable: (caught) => !(caught instanceof ApiError && caught.status === 422),
    enabled: Boolean(data && editable(data)),
  });

  const change = useCallback((pupilId: string, field: string, text: string) => {
    setValues((current) => merge(current, { [pupilId]: { [field]: text } }));
    setDirty((current) => ({
      ...current,
      // Every field of a touched row is sent, not only the one that changed:
      // attendance is checked as a whole — present and absent must add up —
      // so half a pair would be checked against a stale other half.
      [pupilId]: { ...(current[pupilId] ?? {}), [field]: text },
    }));
    setRejections((current) => {
      const next = { ...current };
      delete next[pupilId];
      return next;
    });
  }, []);

  return {
    data,
    loading,
    error,
    autosave,
    change,
    valueOf: (pupilId: string, field: string) => values[pupilId]?.[field] ?? "",
    errorOf: (pupilId: string, field: string) =>
      localErrors[pupilId]?.[field] ?? rejections[pupilId]?.[field],
    pending: countCells(dirty),
    blocked: Object.keys(localErrors).length > 0,
  };
}


function SaveBar({
  autosave,
  pending,
  blocked,
  editable,
}: {
  autosave: ReturnType<typeof useAutosave>;
  pending: number;
  blocked: boolean;
  editable: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p aria-live="polite" className="text-sm text-[var(--muted)]" data-testid="autosave-status">
        {autosaveLabel(autosave.state, autosave.savedAt)}
        {pending > 0 ? ` · ${pending} unsaved` : ""}
      </p>
      <button
        type="button"
        onClick={autosave.saveNow}
        disabled={!editable || pending === 0 || blocked || autosave.state === "saving"}
        className="rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        Save now
      </button>
    </div>
  );
}

function Cell({
  value,
  error,
  onChange,
  onBlur,
  disabled,
  label,
  width = "w-20",
}: {
  value: string;
  error?: string;
  onChange: (text: string) => void;
  onBlur: () => void;
  disabled: boolean;
  label: string;
  width?: string;
}) {
  return (
    <div className="flex flex-col items-end gap-0.5">
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onBlur}
        disabled={disabled}
        inputMode="decimal"
        aria-label={label}
        aria-invalid={error ? true : undefined}
        className={`${width} rounded-md border bg-[var(--background)] px-2 py-1.5 text-right text-sm tabular-nums ${
          error ? "border-[var(--danger)]" : "border-[var(--border)]"
        } disabled:bg-[var(--surface)] disabled:text-[var(--muted)]`}
      />
      {error ? (
        <span role="alert" className="max-w-[16rem] text-right text-xs text-[var(--danger)]">
          {error}
        </span>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------------- */

export function ClassAttendance({
  api,
  classId,
  termId,
}: {
  api: TeacherApi;
  classId: string;
  termId: string;
}) {
  const records = useRecords({
    load: (signal) => api.attendance(classId, termId, signal),
    save: (dirty) =>
      api.saveAttendance(
        classId,
        termId,
        Object.entries(dirty).map(([pupilId, row]) => ({
          pupil_id: pupilId,
          times_present: Number(row.times_present ?? 0),
          times_absent: Number(row.times_absent ?? 0),
          times_late: Number(row.times_late ?? 0),
        })),
      ),
    rowsOf: (data) => data.rows ?? [],
    keyOf: (row) => row.pupil_id,
    editable: (data) => data.editable,
    read: (row) => ({
      times_present: row.times_present === null ? "" : String(row.times_present),
      times_absent: row.times_absent === null ? "" : String(row.times_absent),
      times_late: row.times_late === null ? "" : String(row.times_late),
    }),
    validate: (values, data) => attendanceErrors(values, data.times_school_opened ?? null),
    deps: [api, classId, termId],
  });

  if (records.loading) return <p className="text-sm text-[var(--muted)]">Loading attendance…</p>;
  if (!records.data) return <Notice>{records.error ?? "Could not load attendance."}</Notice>;

  // Bound once, because TypeScript loses the narrowing above inside the map
  // callbacks below — and `records.data!` seven times reads worse than this.
  const data = records.data;
  const opened = data.times_school_opened;

  return (
    <Panel
      title="Attendance"
      description={
        opened === null
          ? "The number of times the school opened has not been set for this term."
          : `Present and absent must add up to ${opened}, the number of times the school opened.`
      }
    >
      {opened === null ? (
        <Notice tone="warning">
          Ask the administrator to set &ldquo;times school opened&rdquo; on the term before
          entering attendance — there is nothing to check these numbers against until then.
        </Notice>
      ) : null}

      {records.error && !records.blocked ? <Notice tone="error">{records.error}</Notice> : null}

      <SaveBar
        autosave={records.autosave}
        pending={records.pending}
        blocked={records.blocked}
        editable={data.editable && opened !== null}
      />

      <ul className="flex flex-col divide-y divide-[var(--border)]">
        {(data.rows ?? []).map((row) => (
          <li key={row.pupil_id} className="flex flex-wrap items-start justify-between gap-3 py-3">
            <div className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">{pupilName(row)}</span>
              <span className="block text-xs text-[var(--muted)]">{row.admission_number}</span>
            </div>
            {(
              [
                ["times_present", "Present"],
                ["times_absent", "Absent"],
                ["times_late", "Collected late"],
              ] as const
            ).map(([field, label]) => (
              <label key={field} className="flex items-center gap-2 text-xs text-[var(--muted)]">
                <span className="w-24 text-right sm:w-auto">{label}</span>
                <Cell
                  value={records.valueOf(row.pupil_id, field)}
                  error={records.errorOf(row.pupil_id, field)}
                  onChange={(text) => records.change(row.pupil_id, field, text)}
                  onBlur={records.autosave.saveNow}
                  disabled={!data.editable || opened === null}
                  label={`${label} for ${pupilName(row)}`}
                  width="w-16"
                />
              </label>
            ))}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

/* ------------------------------------------------------------------------- */

const GROWTH_FIELDS = [
  ["height_start_m", "Height, start (m)"],
  ["height_end_m", "Height, end (m)"],
  ["weight_start_kg", "Weight, start (kg)"],
  ["weight_end_kg", "Weight, end (kg)"],
] as const;

export function ClassGrowth({
  api,
  classId,
  termId,
}: {
  api: TeacherApi;
  classId: string;
  termId: string;
}) {
  const records = useRecords({
    load: (signal) => api.growth(classId, termId, signal),
    save: (dirty) =>
      api.saveGrowth(
        classId,
        termId,
        Object.entries(dirty).map(([pupilId, row]) => ({
          pupil_id: pupilId,
          height_start_m: row.height_start_m?.trim() || null,
          height_end_m: row.height_end_m?.trim() || null,
          weight_start_kg: row.weight_start_kg?.trim() || null,
          weight_end_kg: row.weight_end_kg?.trim() || null,
        })),
      ),
    rowsOf: (data) => data.rows ?? [],
    keyOf: (row) => row.pupil_id,
    editable: (data) => data.editable,
    read: (row) =>
      Object.fromEntries(
        GROWTH_FIELDS.map(([field]) => [field, row[field] === null ? "" : plain(row[field])]),
      ),
    deps: [api, classId, termId],
  });

  if (records.loading) return <p className="text-sm text-[var(--muted)]">Loading measurements…</p>;
  if (!records.data) return <Notice>{records.error ?? "Could not load measurements."}</Notice>;

  const data = records.data;

  return (
    <Panel
      title="Height and weight"
      description="Recorded at the beginning and the end of term. The end-of-term figures can be added later."
    >
      {records.error ? <Notice tone="error">{records.error}</Notice> : null}

      <SaveBar
        autosave={records.autosave}
        pending={records.pending}
        blocked={records.blocked}
        editable={data.editable}
      />

      <ul className="flex flex-col divide-y divide-[var(--border)]">
        {(data.rows ?? []).map((row) => (
          <li key={row.pupil_id} className="flex flex-col gap-2 py-3">
            <div className="min-w-0">
              <span className="block truncate text-sm font-medium">{pupilName(row)}</span>
              <span className="block text-xs text-[var(--muted)]">{row.admission_number}</span>
            </div>
            <div className="flex flex-wrap gap-3">
              {GROWTH_FIELDS.map(([field, label]) => (
                <label key={field} className="flex items-center gap-2 text-xs text-[var(--muted)]">
                  <span>{label}</span>
                  <Cell
                    value={records.valueOf(row.pupil_id, field)}
                    error={records.errorOf(row.pupil_id, field)}
                    onChange={(text) => records.change(row.pupil_id, field, text)}
                    onBlur={records.autosave.saveNow}
                    disabled={!data.editable}
                    label={`${label} for ${pupilName(row)}`}
                  />
                </label>
              ))}
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

/* ------------------------------------------------------------------------- */

export function ClassComments({
  api,
  classId,
  termId,
}: {
  api: TeacherApi;
  classId: string;
  termId: string;
}) {
  const [bank, setBank] = useState<string | null>(null);

  const records = useRecords({
    load: (signal) => api.comments(classId, termId, signal),
    save: (dirty) =>
      api.saveComments(
        classId,
        termId,
        Object.entries(dirty).map(([pupilId, row]) => ({
          pupil_id: pupilId,
          comment: row.comment?.trim() ? row.comment : null,
        })),
      ),
    rowsOf: (data) => data.rows ?? [],
    keyOf: (row) => row.pupil_id,
    editable: (data) => data.editable,
    read: (row) => ({ comment: row.comment ?? "" }),
    deps: [api, classId, termId],
  });

  if (records.loading) return <p className="text-sm text-[var(--muted)]">Loading comments…</p>;
  if (!records.data) return <Notice>{records.error ?? "Could not load comments."}</Notice>;

  const data = records.data;

  return (
    <Panel
      title="Class teacher's comment"
      description="One comment per pupil, printed in the card's footer."
    >
      {records.error ? <Notice tone="error">{records.error}</Notice> : null}

      <SaveBar
        autosave={records.autosave}
        pending={records.pending}
        blocked={records.blocked}
        editable={data.editable}
      />

      <ul className="flex flex-col divide-y divide-[var(--border)]">
        {(data.rows ?? []).map((row) => {
          const text = records.valueOf(row.pupil_id, "comment");
          const error = records.errorOf(row.pupil_id, "comment");
          return (
            <li key={row.pupil_id} className="flex flex-col gap-1.5 py-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-sm font-medium">{pupilName(row)}</span>
                <span className="text-xs text-[var(--muted)]">{text.length} characters</span>
              </div>
              <textarea
                value={text}
                onChange={(event) => records.change(row.pupil_id, "comment", event.target.value)}
                onBlur={records.autosave.saveNow}
                disabled={!data.editable}
                rows={2}
                maxLength={1000}
                aria-label={`Comment for ${pupilName(row)}`}
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
              {data.editable ? (
                <div className="flex flex-wrap gap-2 text-xs">
                  <button
                    type="button"
                    onClick={() => setBank(bank === row.pupil_id ? null : row.pupil_id)}
                    className="rounded-md border border-[var(--border)] px-2 py-1"
                  >
                    {bank === row.pupil_id ? "Hide phrases" : "Phrases"}
                  </button>
                </div>
              ) : null}
              {bank === row.pupil_id ? (
                <CommentPhrases
                  api={api}
                  onPick={(phrase) =>
                    records.change(
                      row.pupil_id,
                      "comment",
                      text.trim() === "" ? phrase : `${text.trimEnd()} ${phrase}`,
                    )
                  }
                />
              ) : null}
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}

function CommentPhrases({
  api,
  onPick,
}: {
  api: TeacherApi;
  onPick: (phrase: string) => void;
}) {
  const [phrases, setPhrases] = useState<{ id: string; text: string }[] | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api
      .phrases("class_teacher", controller.signal)
      .then((found) => !controller.signal.aborted && setPhrases(found))
      .catch(() => !controller.signal.aborted && setPhrases([]));
    return () => controller.abort();
  }, [api]);

  if (phrases === null) return <p className="text-xs text-[var(--muted)]">Loading phrases…</p>;
  if (phrases.length === 0) {
    return (
      <p className="text-xs text-[var(--muted)]">
        No class teacher phrases yet. An administrator adds them under Grading &amp; narrative.
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
