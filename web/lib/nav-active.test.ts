import assert from "node:assert/strict";
import { test } from "node:test";

import { isActive } from "./nav-active.ts";

test("the page you are on is active", () => {
  assert.equal(isActive("/admin/pupils", "/admin/pupils"), true);
});

test("a section is active on the pages beneath it", () => {
  assert.equal(isActive("/admin/classes/abc", "/admin/classes"), true);
});

test("a sibling whose path is a prefix of ours is not active", () => {
  // `/admin/class` must not light up for `/admin/classes`.
  assert.equal(isActive("/admin/classes", "/admin/class"), false);
});

test("a section root marked exact is not active beneath itself", () => {
  // Otherwise "Setup" and "Pupils" would both claim to be the current page.
  assert.equal(isActive("/admin/pupils", "/admin", true), false);
  assert.equal(isActive("/admin", "/admin", true), true);
});

test("a link with a query string matches on its path", () => {
  // The review queue links to a class *for a term*; the pathname has no query.
  assert.equal(isActive("/review/abc", "/review/abc?term=xyz"), true);
});

test("an unrelated page is not active", () => {
  assert.equal(isActive("/teacher", "/admin"), false);
});
