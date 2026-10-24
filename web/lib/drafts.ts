"use client";

/**
 * Unsaved work in `localStorage` (ARCHITECTURE.md §8.1, §8.2).
 *
 * "Draft persistence to localStorage, keyed by class-subject and period, so a
 * dropped connection loses nothing. Reconcile on reload and say what was
 * recovered."
 *
 * Two decisions worth stating:
 *
 * - Only cells that have **not** reached the server are kept. A draft is a
 *   record of unsaved work, not a cache of the sheet; keeping saved values
 *   too would mean deciding on reload which copy is newer, and the server's
 *   answer is always the one that matters.
 * - Every read and write is wrapped. Private browsing, a full quota and a
 *   locked-down Android WebView all throw rather than returning null, and a
 *   teacher losing the grid because storage is unavailable would be a worse
 *   failure than losing the draft.
 *
 * Scores are a pupil's data, so this is the one place they are written to a
 * device. That is the point of the requirement — the alternative is retyping
 * a class — but it is why `clear()` runs on every successful save rather than
 * leaving them there.
 */

// The extension is explicit, and both `.ts` imports in this file are
// deliberate: `npm test` runs these modules in Node directly
// (--experimental-strip-types), and Node's ESM resolver needs the extension
// at every hop. The bundler is happy either way.
import { countCells as count, type Cells } from "./scores.ts";

const VERSION = "v1";

export interface Draft {
  /** `{ [pupilId]: { [column]: value as typed } }`, unsaved cells only. */
  values: Cells;
  /** When the draft was last written, as an ISO string. */
  at: string;
}

/** `scope` and `item` are the two ids that identify one screen's work. */
function key(scope: string, item: string): string {
  return `sshms.draft.${VERSION}.${scope}.${item}`;
}

export function readDraft(scope: string, item: string): Draft | null {
  try {
    const raw = window.localStorage.getItem(key(scope, item));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Draft;
    if (!parsed || typeof parsed !== "object" || typeof parsed.values !== "object") return null;
    return parsed;
  } catch {
    return null;
  }
}

export function writeDraft(scope: string, item: string, values: Draft["values"]): void {
  try {
    if (Object.keys(values).length === 0) {
      clearDraft(scope, item);
      return;
    }
    window.localStorage.setItem(
      key(scope, item),
      JSON.stringify({ values, at: new Date().toISOString() } satisfies Draft),
    );
  } catch {
    // Storage unavailable or full. The grid keeps working from memory.
  }
}

export function clearDraft(scope: string, item: string): void {
  try {
    window.localStorage.removeItem(key(scope, item));
  } catch {
    // Nothing to do, and nothing worth telling the teacher about.
  }
}

/** How many cells a draft holds, for "recovered 4 unsaved scores". */
export const countCells = count;

/**
 * The cells in a draft that the server does not already agree with.
 *
 * Called on load. A draft written just before a successful save — the browser
 * closed between the two — would otherwise be "recovered" as unsaved work
 * that is identical to what is on screen, which teaches a teacher to ignore
 * the notice.
 */
export function unreconciled(draft: Cells, saved: Cells): Cells {
  const pending: Draft["values"] = {};
  for (const [pupilId, row] of Object.entries(draft)) {
    for (const [column, value] of Object.entries(row)) {
      if ((saved[pupilId]?.[column] ?? "") !== value) {
        pending[pupilId] = { ...(pending[pupilId] ?? {}), [column]: value };
      }
    }
  }
  return pending;
}
