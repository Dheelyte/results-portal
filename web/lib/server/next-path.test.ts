import assert from "node:assert/strict";
import { test } from "node:test";

import { DEFAULT_DESTINATION, safeNext } from "./next-path.ts";

test("a path on this origin is kept", () => {
  assert.equal(safeNext("/children"), "/children");
  assert.equal(safeNext("/children/abc/def"), "/children/abc/def");
  assert.equal(safeNext("/children?half=first_half"), "/children?half=first_half");
});

test("an absolute URL elsewhere is refused", () => {
  for (const hostile of [
    "https://evil.example/x",
    "http://evil.example",
    "//evil.example/x",
    "/\\evil.example/x",
    "javascript:alert(1)",
    "evil.example/x",
  ]) {
    assert.equal(safeNext(hostile), DEFAULT_DESTINATION, hostile);
  }
});

test("a header-splitting attempt is refused", () => {
  assert.equal(safeNext("/children\r\nSet-Cookie: a=b"), DEFAULT_DESTINATION);
  assert.equal(safeNext("/children\nX: y"), DEFAULT_DESTINATION);
});

test("a missing parameter falls back", () => {
  assert.equal(safeNext(null), DEFAULT_DESTINATION);
  assert.equal(safeNext(undefined), DEFAULT_DESTINATION);
  assert.equal(safeNext(""), DEFAULT_DESTINATION);
});

test("the fallback is itself a path on this origin", () => {
  // Otherwise every refusal above would be the open redirect.
  assert.equal(safeNext(DEFAULT_DESTINATION), DEFAULT_DESTINATION);
});
