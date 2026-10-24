/**
 * R9 in the browser (ARCHITECTURE.md §6 R9).
 *
 * The rule lives in `api/src/app/services/wellbeing.py` and a trigger backs
 * it in the database; the server's answer is the authority (CLAUDE.md rule
 * 2). This is the mirror that turns a row red as it is typed — a teacher
 * entering thirty pupils should not discover on save that the first one does
 * not add up.
 *
 * Kept out of the component, and free of React and the DOM, so it can be
 * tested with `npm test` against the same cases as the Python.
 */

import type { Cells } from "./scores";

/** A single attendance row's refusals, keyed by field. */
export function attendanceRowErrors(
  row: Record<string, string>,
  timesSchoolOpened: number | null,
): Record<string, string> {
  const errors: Record<string, string> = {};

  // Every field blank means "not entered yet", which is not an error — it is
  // most of the class for most of the term.
  const entries = ["times_present", "times_absent", "times_late"] as const;
  if (entries.every((field) => (row[field] ?? "").trim() === "")) return errors;

  const numbers: Record<string, number> = {};
  for (const field of entries) {
    const text = (row[field] ?? "").trim();
    if (text === "") {
      // Present and absent are checked as a pair, so one of them missing is
      // as much an error as a wrong total.
      if (field !== "times_late") errors[field] = "Enter a number.";
      numbers[field] = 0;
      continue;
    }
    if (!/^\d+$/.test(text)) {
      errors[field] = "Whole days only.";
      continue;
    }
    numbers[field] = Number(text);
  }

  if (Object.keys(errors).length > 0) return errors;
  if (timesSchoolOpened === null) return errors;

  const present = numbers.times_present ?? 0;
  const absent = numbers.times_absent ?? 0;
  const late = numbers.times_late ?? 0;

  if (present > timesSchoolOpened) {
    errors.times_present = `The school opened ${timesSchoolOpened} times this term.`;
  } else if (present + absent !== timesSchoolOpened) {
    errors.times_absent = `These add up to ${present + absent}, not ${timesSchoolOpened}.`;
  }

  if (late > timesSchoolOpened) {
    errors.times_late = `The school opened ${timesSchoolOpened} times this term.`;
  }

  return errors;
}

/** Every row of the table that breaks R9, keyed as the server keys them. */
export function attendanceErrors(
  values: Cells,
  timesSchoolOpened: number | null,
): Record<string, Record<string, string>> {
  const found: Record<string, Record<string, string>> = {};
  for (const [pupilId, row] of Object.entries(values)) {
    const errors = attendanceRowErrors(row, timesSchoolOpened);
    if (Object.keys(errors).length > 0) found[pupilId] = errors;
  }
  return found;
}
