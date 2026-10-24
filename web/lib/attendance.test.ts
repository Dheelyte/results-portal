/**
 * R9's browser mirror (§6 R9).
 *
 * The same cases as `api/tests/unit/test_attendance_bounds.py`, because the
 * two are the same rule and a disagreement between them shows as a cell that
 * turns red when the server would have accepted it.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { attendanceErrors, attendanceRowErrors } from "./attendance.ts";

const OPENED = 60;

function row(present: string, absent: string, late = ""): Record<string, string> {
  return { times_present: present, times_absent: absent, times_late: late };
}

describe("attendanceRowErrors", () => {
  it("accepts a row that adds up", () => {
    assert.deepEqual(attendanceRowErrors(row("58", "2"), OPENED), {});
    assert.deepEqual(attendanceRowErrors(row("60", "0"), OPENED), {});
    assert.deepEqual(attendanceRowErrors(row("0", "60"), OPENED), {});
  });

  it("treats a wholly empty row as not yet entered", () => {
    // Most of the class, most of the term.
    assert.deepEqual(attendanceRowErrors(row("", ""), OPENED), {});
    assert.deepEqual(attendanceRowErrors({}, OPENED), {});
  });

  it("refuses a total that does not add up, and says what it adds to", () => {
    const errors = attendanceRowErrors(row("50", "5"), OPENED);

    assert.ok(errors.times_absent);
    assert.match(errors.times_absent, /55/);
    assert.match(errors.times_absent, /60/);
  });

  it("refuses more days present than the school opened", () => {
    const errors = attendanceRowErrors(row("61", "0"), OPENED);

    assert.deepEqual(Object.keys(errors), ["times_present"]);
  });

  it("asks for the other half of the pair", () => {
    // Present without absent cannot be checked, and silently treating the
    // blank as zero would show "adds up to 58, not 60" — an error about the
    // wrong field.
    assert.deepEqual(attendanceRowErrors(row("58", ""), OPENED), {
      times_absent: "Enter a number.",
    });
  });

  it("does not demand a late count", () => {
    // "Times Collected Late" defaults to zero (§4.7), and N6 has not even
    // confirmed it appears on the digital card.
    assert.deepEqual(attendanceRowErrors(row("58", "2", ""), OPENED), {});
  });

  it("refuses anything that is not a whole number of days", () => {
    for (const typed of ["5.5", "abc", "-1", "5a", "1e2"]) {
      const errors = attendanceRowErrors(row(typed, "2"), OPENED);
      assert.equal(errors.times_present, "Whole days only.", `for ${typed}`);
    }
  });

  it("reports a bad number before the arithmetic", () => {
    // Otherwise the teacher is told the total is wrong, which is a
    // consequence of the typo rather than the typo.
    const errors = attendanceRowErrors(row("abc", "2"), OPENED);

    assert.deepEqual(Object.keys(errors), ["times_present"]);
  });

  it("refuses more late collections than days the school opened", () => {
    assert.ok(attendanceRowErrors(row("58", "2", "61"), OPENED).times_late);
  });

  it("allows late on every day the pupil attended", () => {
    assert.deepEqual(attendanceRowErrors(row("60", "0", "60"), OPENED), {});
  });

  it("checks nothing when the term has no figure to add up to", () => {
    // The admin has not set times_school_opened. The page says so; it does
    // not invent a target.
    assert.deepEqual(attendanceRowErrors(row("58", "2"), null), {});
  });

  it("still rejects a typo when there is no figure", () => {
    assert.ok(attendanceRowErrors(row("abc", "2"), null).times_present);
  });
});

describe("attendanceErrors", () => {
  it("keys refusals by pupil, as the server does", () => {
    const found = attendanceErrors(
      { ada: row("58", "2"), emeka: row("50", "5") },
      OPENED,
    );

    assert.deepEqual(Object.keys(found), ["emeka"]);
  });

  it("is empty when the whole class adds up", () => {
    assert.deepEqual(attendanceErrors({ ada: row("58", "2") }, OPENED), {});
  });
});
