/**
 * R1 in the browser, and the small conversions the grid needs (§6 R1, §8.1).
 *
 * The rule itself lives in `api/src/app/services/results.py` and the server's
 * answer is the authority (CLAUDE.md rule 2). This is the mirror that lets a
 * mistyped cell turn red as it is typed rather than twenty seconds later —
 * §8.1 asks for validation "inline and immediate", and a round trip on a 3G
 * connection is neither.
 *
 * It is a separate module from the grid so it can be tested without a
 * browser: no JSX, no React, no DOM.
 */

/** The columns as the card prints them. */
export const COLUMN_LABELS: Record<string, string> = {
  ca_test_1: "CA Test 1",
  ca_test_2: "CA Test 2",
  ca_test_3: "CA Test 3",
  ca_test_4: "CA Test 4",
  ca_test_5: "CA Test 5",
  mid_term_test: "Mid Term Test",
  exam: "Exam",
};

export function labelOf(column: string): string {
  return COLUMN_LABELS[column] ?? column;
}

/**
 * A number as a person writes it: 40, not 40.00.
 *
 * Every score crosses the wire as a string, because the API is `numeric(5,2)`
 * and a float would be the one representation CLAUDE.md forbids. Trailing
 * zeros are the database's, not the teacher's.
 */
export function plain(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const asNumber = Number(value);
  return Number.isFinite(asNumber) ? String(asNumber) : String(value);
}

export type Cells = Record<string, Record<string, string>>;

/**
 * R1, locally.
 *
 * Returns the message for a cell, or null. The order of the checks is the
 * order a teacher makes the mistakes: a stray letter, too many decimals, then
 * over the maximum.
 */
export function cellError(raw: string, maximum: string | number | null | undefined): string | null {
  const text = raw.trim();
  if (text === "") return null;

  // Deliberately not parseFloat: it reads "8abc" as 8, and a cell that
  // silently drops what was typed is worse than one that complains.
  if (!/^\d+(\.\d*)?$|^\.\d+$/.test(text)) return "Enter a number.";

  const value = Number(text);
  if (!Number.isFinite(value)) return "Enter a number.";

  const decimals = text.split(".")[1] ?? "";
  if (decimals.length > 1) return "One decimal place.";

  if (maximum === null || maximum === undefined || maximum === "") {
    return "No maximum is set for this column.";
  }
  if (value > Number(maximum)) return `Out of ${plain(maximum)}.`;

  return null;
}

/** Every cell of the grid that breaks R1, keyed as the server keys them. */
export function errorsIn(
  values: Cells,
  columns: readonly string[],
  maxima: Record<string, string | null> | null,
): Record<string, Record<string, string>> {
  const found: Record<string, Record<string, string>> = {};
  for (const [pupilId, row] of Object.entries(values)) {
    for (const [column, raw] of Object.entries(row)) {
      if (!columns.includes(column)) continue;
      const message = cellError(raw, maxima?.[column]);
      if (message) found[pupilId] = { ...(found[pupilId] ?? {}), [column]: message };
    }
  }
  return found;
}

/**
 * The dirty set as the API's row array.
 *
 * An empty cell becomes an explicit null, which is how a teacher undoes a
 * mistyped score: the API distinguishes "not sent" from "sent as null", and
 * only the second one clears the cell.
 */
export function payloadFrom(dirty: Cells): Array<Record<string, string | null>> {
  return Object.entries(dirty).map(([pupilId, row]) => {
    const cells: Record<string, string | null> = { pupil_id: pupilId };
    for (const [column, raw] of Object.entries(row)) {
      cells[column] = raw.trim() === "" ? null : raw.trim();
    }
    return cells;
  });
}

export function merge(base: Cells, overlay: Cells): Cells {
  const merged: Cells = {};
  for (const [pupilId, row] of Object.entries(base)) merged[pupilId] = { ...row };
  for (const [pupilId, row] of Object.entries(overlay)) {
    merged[pupilId] = { ...(merged[pupilId] ?? {}), ...row };
  }
  return merged;
}

export function isEmpty(cells: Cells): boolean {
  return Object.values(cells).every((row) => Object.keys(row).length === 0);
}

export function countCells(cells: Cells): number {
  return Object.values(cells).reduce((total, row) => total + Object.keys(row).length, 0);
}
