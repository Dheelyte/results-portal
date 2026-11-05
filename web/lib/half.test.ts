import assert from "node:assert/strict";
import { test } from "node:test";

import { DEFAULT_HALF, HALVES, halfFrom, halfLabel } from "./half.ts";

test("either half is kept", () => {
  assert.equal(halfFrom("first_half"), "first_half");
  assert.equal(halfFrom("second_half"), "second_half");
});

test("anything else falls back to the sheet the parent holds", () => {
  for (const other of [
    null,
    undefined,
    "",
    "third_half",
    "FIRST_HALF",
    // Repeated query parameters arrive as an array.
    ["first_half", "second_half"] as string[],
    // It is interpolated into the API's URL, so this is the one that matters.
    "second_half&state=published",
  ]) {
    assert.equal(halfFrom(other), DEFAULT_HALF, JSON.stringify(other));
  }
});

test("the default is itself a half", () => {
  assert.ok(HALVES.includes(DEFAULT_HALF));
});

test("both halves have a label", () => {
  assert.deepEqual(HALVES.map(halfLabel), ["First half", "Second half"]);
});
