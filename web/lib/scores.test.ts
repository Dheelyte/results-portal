/**
 * R1 as the browser sees it (§6 R1, §8.1).
 *
 * Run with Node's own test runner and its TypeScript support, so the grid's
 * logic is tested without adding a test framework to the project (CLAUDE.md
 * rule 7, and rule 10 — tests are part of the work):
 *
 *     docker compose exec web npm test
 *
 * The server is still the authority on R1. What these tests pin is that the
 * browser's mirror agrees with it, because a cell that turns red when the
 * server would have accepted it is as bad as one that does not.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { cellError, countCells, errorsIn, isEmpty, labelOf, merge, payloadFrom, plain } from "./scores.ts";

const COLUMNS = ["ca_test_1", "ca_test_2", "mid_term_test"] as const;
const MAXIMA = { ca_test_1: "8.00", ca_test_2: "8.00", mid_term_test: "60.00", exam: null };

describe("cellError", () => {
  it("accepts an empty cell", () => {
    // A blank is not an error: most of the grid is blank most of the term.
    assert.equal(cellError("", "8"), null);
    assert.equal(cellError("   ", "8"), null);
  });

  it("accepts a whole mark and one decimal place", () => {
    assert.equal(cellError("8", "8"), null);
    assert.equal(cellError("7.5", "8"), null);
    assert.equal(cellError("0", "8"), null);
  });

  it("names the maximum when the score is over it (R1)", () => {
    // R1: "The error names the applicable maximum." A teacher needs to know
    // the ceiling, not merely that they went past it.
    assert.equal(cellError("9", "8.00"), "Out of 8.");
    assert.equal(cellError("60.5", "60.00"), "Out of 60.");
  });

  it("refuses two significant decimal places (R1)", () => {
    assert.equal(cellError("7.25", "8"), "One decimal place.");
    assert.equal(cellError("7.99", "8"), "One decimal place.");
  });

  it("accepts trailing zeros, because the value is what R1 bounds", () => {
    // "8.00" is how the API returns a column maximum. A teacher who types
    // the maximum, or a client that echoes it back, must not be refused for
    // the way the number is written.
    assert.equal(cellError("8.00", "8.00"), null);
    assert.equal(cellError("7.50", "8"), null);
    assert.equal(cellError("0.00", "8"), null);
  });

  it("refuses anything that is not a number", () => {
    for (const typed of ["abc", "8abc", "8,5", "-1", "1e3", "8..5", "--"]) {
      assert.equal(cellError(typed, "8"), "Enter a number.", `for ${typed}`);
    }
  });

  it("does not quietly read a number out of a typo", () => {
    // parseFloat("8abc") is 8. A cell that drops what was typed is worse
    // than one that complains about it.
    assert.equal(cellError("8abc", "8"), "Enter a number.");
  });

  it("says so when the column has no maximum", () => {
    // N2 is open, so this is a state the school can really be in.
    assert.equal(cellError("5", null), "No maximum is set for this column.");
    assert.equal(cellError("5", undefined), "No maximum is set for this column.");
  });

  it("allows a leading decimal point", () => {
    assert.equal(cellError(".5", "8"), null);
  });
});

describe("errorsIn", () => {
  it("keys refusals by pupil and column, as the server does", () => {
    const found = errorsIn(
      { ada: { ca_test_1: "9", ca_test_2: "7" }, emeka: { ca_test_1: "4" } },
      COLUMNS,
      MAXIMA,
    );

    assert.deepEqual(Object.keys(found), ["ada"]);
    assert.ok(found.ada);
    assert.deepEqual(Object.keys(found.ada), ["ca_test_1"]);
  });

  it("ignores a column that is not on this sheet", () => {
    // The second-half sheet has no Mid Term Test, and vice versa. A stale
    // value for the other half must not paint a cell that is not rendered.
    const found = errorsIn({ ada: { exam: "500" } }, COLUMNS, MAXIMA);

    assert.deepEqual(found, {});
  });

  it("reports every bad cell, not the first", () => {
    const found = errorsIn({ ada: { ca_test_1: "9", ca_test_2: "x" } }, COLUMNS, MAXIMA);

    assert.ok(found.ada);
    assert.deepEqual(Object.keys(found.ada).sort(), ["ca_test_1", "ca_test_2"]);
  });
});

describe("payloadFrom", () => {
  it("sends only the cells that changed", () => {
    // §8.1 autosaves "the dirty set". An omitted column means "leave it
    // alone" to the API, which is what makes a one-cell save possible.
    const payload = payloadFrom({ ada: { ca_test_2: "7" } });

    assert.deepEqual(payload, [{ pupil_id: "ada", ca_test_2: "7" }]);
  });

  it("turns an emptied cell into an explicit null", () => {
    // The only way to undo a mistyped score. "Not sent" and "sent as null"
    // mean different things to the API, and this is the difference.
    assert.deepEqual(payloadFrom({ ada: { ca_test_1: "  " } }), [
      { pupil_id: "ada", ca_test_1: null },
    ]);
  });

  it("trims what the teacher typed", () => {
    assert.deepEqual(payloadFrom({ ada: { ca_test_1: " 7 " } }), [
      { pupil_id: "ada", ca_test_1: "7" },
    ]);
  });
});

describe("plain", () => {
  it("drops the database's trailing zeros", () => {
    // The card says 40, not 40.00.
    assert.equal(plain("40.00"), "40");
    assert.equal(plain("7.50"), "7.5");
  });

  it("shows a dash rather than nothing", () => {
    assert.equal(plain(null), "—");
    assert.equal(plain(undefined), "—");
    assert.equal(plain(""), "—");
  });

  it("keeps a zero, which is a real score", () => {
    assert.equal(plain("0.00"), "0");
  });
});

describe("labelOf", () => {
  it("uses the card's own column names", () => {
    assert.equal(labelOf("ca_test_3"), "CA Test 3");
    assert.equal(labelOf("mid_term_test"), "Mid Term Test");
    assert.equal(labelOf("exam"), "Exam");
  });

  it("falls back to the column name rather than crashing", () => {
    assert.equal(labelOf("something_new"), "something_new");
  });
});

describe("merge, isEmpty and countCells", () => {
  it("overlays a draft onto the saved sheet without losing either", () => {
    const merged = merge({ ada: { ca_test_1: "5" } }, { ada: { ca_test_2: "6" } });

    assert.deepEqual(merged, { ada: { ca_test_1: "5", ca_test_2: "6" } });
  });

  it("lets the overlay win, because the draft is the newer work", () => {
    const merged = merge({ ada: { ca_test_1: "5" } }, { ada: { ca_test_1: "7" } });

    assert.deepEqual(merged, { ada: { ca_test_1: "7" } });
  });

  it("does not mutate what it was given", () => {
    const base = { ada: { ca_test_1: "5" } };
    merge(base, { ada: { ca_test_1: "7" } });

    assert.deepEqual(base, { ada: { ca_test_1: "5" } });
  });

  it("counts cells, not rows", () => {
    assert.equal(countCells({ ada: { ca_test_1: "5", ca_test_2: "6" }, emeka: {} }), 2);
    assert.equal(countCells({}), 0);
  });

  it("treats a row with no cells as empty", () => {
    assert.equal(isEmpty({ ada: {} }), true);
    assert.equal(isEmpty({ ada: { ca_test_1: "5" } }), false);
  });
});
