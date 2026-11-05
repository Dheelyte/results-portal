import assert from "node:assert/strict";
import { test } from "node:test";

import { GENERIC_SIGN_IN_FAILURE, signInMessage } from "./sign-in-message.ts";

test("each code has its own wording", () => {
  const credentials = signInMessage("credentials");
  const locked = signInMessage("locked");
  assert.ok(credentials && locked);
  assert.notEqual(credentials, locked);
  assert.match(locked, /locked/i);
});

test("no message at all when nothing failed", () => {
  assert.equal(signInMessage(null), null);
  assert.equal(signInMessage(undefined), null);
  assert.equal(signInMessage(""), null);
});

test("a sentence from the URL never reaches the page", () => {
  // The whole reason this module exists: a convincing sentence on the
  // school's own sign-in page is the whole of a phishing page.
  for (const hostile of [
    "Your account is suspended. Call 0800 555 0199 to restore it.",
    "<script>alert(1)</script>",
    "constructor",
    "__proto__",
    "toString",
    ["credentials", "locked"] as string[],
  ]) {
    assert.equal(signInMessage(hostile), GENERIC_SIGN_IN_FAILURE, JSON.stringify(hostile));
  }
});
