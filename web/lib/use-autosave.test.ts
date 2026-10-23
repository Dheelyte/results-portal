/**
 * The autosave indicator (§8.1).
 *
 * "...with a visible 'Saved 14:32' / 'Saving…' / 'Not saved — retrying'
 * indicator." The hook's timing needs a renderer to test and §12 puts that at
 * milestone 13; the label is pure, and it is the part a teacher actually
 * reads.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { autosaveLabel } from "./use-autosave.ts";

// 14:32 in Lagos. The school is in Nigeria and the clock on screen must be
// the clock on the wall (CLAUDE.md: rendered Africa/Lagos).
const AT = new Date("2026-10-23T13:32:00Z");

describe("autosaveLabel", () => {
  it("says when the sheet was last saved", () => {
    assert.equal(autosaveLabel("saved", AT), "Saved 14:32");
  });

  it("renders the time in Lagos, not the browser's zone", () => {
    assert.ok(autosaveLabel("saved", AT).includes("14:32"));
  });

  it("says a save is in flight", () => {
    assert.equal(autosaveLabel("saving", AT), "Saving…");
  });

  it("says a failed save will be tried again", () => {
    // The teacher keeps typing; the twenty-second tick retries.
    assert.equal(autosaveLabel("retrying", AT), "Not saved — retrying");
  });

  it("points a rejection at the cells rather than promising a retry", () => {
    // A score over its maximum fails identically every time, so saying
    // "retrying" would be a lie told every twenty seconds.
    assert.match(autosaveLabel("rejected", AT), /fix the cells/);
  });

  it("distinguishes unsaved changes from a clean sheet", () => {
    assert.match(autosaveLabel("pending", AT), /Unsaved changes/);
    assert.equal(autosaveLabel("clean", null), "No changes");
  });

  it("does not claim a save time it does not have", () => {
    assert.equal(autosaveLabel("saved", null), "Saved");
    assert.equal(autosaveLabel("pending", null), "Unsaved changes");
  });
});
