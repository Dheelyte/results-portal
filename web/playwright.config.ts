/**
 * E2E configuration (ARCHITECTURE.md §10, docs/DECISIONS.md D98).
 *
 * §10 names one E2E journey: "Full term: set up → enter both periods →
 * narrative → submit → approve → publish → parent downloads and
 * acknowledges." One spec, run in order, against the compose stack through
 * Caddy — the same two hostnames the school will use, so the cross-origin
 * and cookie behaviour under test is the real one.
 *
 * No `webServer` block: the stack is brought up by `docker compose`, because
 * this journey needs Postgres, the API, the PDF renderer and the seed, not
 * just Next.js. `docs/RUNBOOK.md` has the two commands.
 */

import { defineConfig, devices } from "@playwright/test";

/** Through Caddy, as a parent's phone reaches it. */
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:8080";

export default defineConfig({
  testDir: "./e2e",

  // The journey is one story told in order: a class cannot be approved before
  // it is submitted. Parallelism here would not be faster, only wrong.
  fullyParallel: false,
  workers: 1,

  // A failing E2E is a symptom, not a flake to paper over. A retry would hide
  // the ordering bug it is most likely to catch.
  retries: 0,

  // Generous, for two reasons that are both about first visits rather than
  // about the app being slow: the stack under test is the **development**
  // Next server, which compiles each route the first time it is asked for,
  // and the PDF step renders a card through WeasyPrint on first request.
  // A step that opens two screens it has not opened before pays both.
  timeout: 150_000,
  expect: { timeout: 20_000 },

  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],

  use: {
    baseURL: BASE_URL,
    // §8.1 and §8.5 both specify phones: "a teacher enters a full class on a
    // phone viewport", "a low-end Android device". The journey is driven at
    // that size, so a control that only exists on a desktop layout fails here.
    ...devices["Pixel 7"],
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },

  projects: [{ name: "android-chrome", use: { ...devices["Pixel 7"] } }],
});
