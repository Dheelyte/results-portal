/**
 * The stack is up and reachable, both hostnames (ARCHITECTURE.md §11).
 *
 * Kept separate from the journey because when `full-term.spec.ts` fails, the
 * first question is whether anything was running at all, and this answers it
 * in a second.
 */

import { expect, test } from "@playwright/test";

const API = process.env.E2E_API_URL ?? "http://api.localhost:8080";

test("the web app serves the parent's front door", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Results Portal" })).toBeVisible();
  await expect(page.getByLabel(/email address or phone/i)).toBeVisible();
});

test("the API answers its health checks, and the web host does not", async ({ request }) => {
  await expect((await request.get(`${API}/healthz`)).status()).toBe(200);
  await expect((await request.get(`${API}/readyz`)).status()).toBe(200);

  // §11 puts both on the API host only. A 200 here would mean Caddy is
  // routing the web hostname to the API.
  await expect((await request.get("/healthz")).status()).toBe(404);
});
