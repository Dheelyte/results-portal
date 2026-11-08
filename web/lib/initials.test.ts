import assert from "node:assert/strict";
import { test } from "node:test";

import { hueOf, initialsOf } from "./initials.ts";

test("two names give the first letter of each", () => {
  assert.equal(initialsOf("Ada Lovelace"), "AL");
});

test("a middle name is skipped — the first and the last, not the first two", () => {
  assert.equal(initialsOf("Ada Byron Lovelace"), "AL");
});

test("one name gives one letter", () => {
  assert.equal(initialsOf("Ada"), "A");
});

test("surrounding and doubled whitespace is not a word", () => {
  assert.equal(initialsOf("  Ada   Lovelace  "), "AL");
});

test("a name that is only whitespace does not produce an empty circle", () => {
  assert.equal(initialsOf("   "), "?");
  assert.equal(initialsOf(""), "?");
});

test("initials are upper-cased, whatever was typed", () => {
  assert.equal(initialsOf("ada lovelace"), "AL");
});

test("a non-Latin name still yields two characters", () => {
  assert.equal(initialsOf("Chidinma Ọlá"), "CỌ");
});

test("the hue is stable for a name and in range", () => {
  const hue = hueOf("Ada Lovelace");
  assert.equal(hue, hueOf("Ada Lovelace"));
  assert.ok(hue >= 0 && hue < 360, `${hue} is not a hue`);
});

test("two different names usually differ, which is the whole point", () => {
  assert.notEqual(hueOf("Ada Lovelace"), hueOf("Grace Hopper"));
});
