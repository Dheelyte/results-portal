/**
 * Getting in, and getting around. Shared by every spec.
 *
 * Extracted from `full-term.spec.ts` when `navigation.spec.ts` needed the
 * same helpers. None of them is trivial — each encodes something learned the
 * hard way — and two copies would have drifted.
 */

import { expect, type Locator, type Page } from "@playwright/test";

/**
 * Sign in on the staff screens.
 *
 * The submit is retried, and the reason is specific rather than
 * superstitious: on a loaded machine a click sometimes lands with nothing
 * sent — the API's `audit_log` shows no attempt at all, successful or
 * failed, so the request was never made. This is the development Next
 * server, which compiles a route on first request, and a button that is
 * visible and enabled before React has finished wiring it. A second submit
 * always works.
 *
 * It is deliberately **not** a Playwright `retries` setting: a retry would
 * re-run a whole step of a serial journey, and this is one click.
 */
export async function signInAsStaff(
  page: Page,
  identifier: string,
  password: string,
): Promise<void> {
  await page.goto("/login");
  await page.getByLabel(/email address or phone/i).fill(identifier);
  await page.getByLabel(/^password/i).fill(password);

  const submit = page.getByRole("button", { name: /^sign in$/i });

  for (let attempt = 1; attempt <= 3; attempt += 1) {
    await expect(submit).toBeEnabled({ timeout: 30_000 });
    await submit.click();

    try {
      await expect(page).not.toHaveURL(/\/login$/, { timeout: 15_000 });
      return;
    } catch {
      // Still on the sign-in screen. If the API refused us, say so rather
      // than hammering it — only a silent no-op is worth retrying.
      const alert = page.getByRole("alert");
      if ((await alert.count()) > 0) {
        const message = (await alert.first().textContent())?.trim();
        if (message) {
          throw new Error(`signing in as ${identifier} was refused: ${message}`);
        }
      }
    }
  }

  throw new Error(`signing in as ${identifier} never left /login after three submits`);
}

/** The parent's door is a different screen entirely (§8.5, D89). */
export async function signInAsParent(
  page: Page,
  identifier: string,
  password: string,
): Promise<void> {
  await page.goto("/");
  await page.getByLabel(/email address or phone/i).fill(identifier);
  await page.getByLabel(/^password/i).fill(password);

  // No retry needed here: this is a `<form>` posting to a server action, so
  // it works before any JavaScript has loaded at all (D90). That is the
  // whole point of §8.5's "3G on a low-end Android device", and it is also
  // why this screen is the steadiest thing in the journey.
  await page.getByRole("button", { name: /^sign in$/i }).click();
  await expect(page).toHaveURL(/\/children$/, { timeout: 30_000 });
}

/**
 * Follow a link in §8.0's sidebar.
 *
 * The redesign put the staff navigation in a sidebar that is a permanent rail
 * from `lg` up and a drawer below it — and these specs run at a phone
 * viewport, because §8.1 and §8.5 both specify one. So reaching a nav link
 * is two taps, which is what it is for a teacher.
 *
 * Which of the two it is, is decided by looking rather than assumed, so the
 * specs still pass if the viewport in `playwright.config.ts` ever changes.
 * The menu button is **not** hidden while the drawer is open — it is merely
 * covered by it — so "is the drawer open" is the question asked, not "is the
 * button gone".
 */
export async function navigate(page: Page, name: RegExp, url?: RegExp): Promise<void> {
  const open = async () => {
    const menu = page.getByRole("button", { name: /open the menu/i });

    if (await menu.isVisible().catch(() => false)) {
      await menu.click();
      const drawer = page.getByRole("dialog", { name: /^menu$/i });
      await expect(drawer).toBeVisible({ timeout: 20_000 });
      return drawer.getByRole("link", { name });
    }

    // A wide viewport: the rail is always there.
    return page.getByRole("navigation").getByRole("link", { name }).first();
  };

  if (!url) {
    await (await open()).click();
    return;
  }

  await clickThrough(page, open, url, `the sidebar's ${String(name)} link`);
}

/**
 * Click something, and make sure the click actually went somewhere.
 *
 * Same bounded retry as `signInAsStaff`, for the same documented reason
 * (docs/DECISIONS.md D101): on a loaded machine a click sometimes lands with
 * nothing happening, because the development Next server compiles a route on
 * first request and a link is clickable before React has finished wiring it.
 * A second click always works.
 *
 * It takes a **factory** rather than a locator so a retry re-opens the drawer
 * it may have closed, and it is bounded at three so a genuinely broken link
 * still fails the test rather than hanging it.
 */
export async function clickThrough(
  page: Page,
  target: () => Promise<Locator> | Locator,
  url: RegExp,
  what: string,
): Promise<void> {
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    await (await target()).click();
    try {
      await expect(page).toHaveURL(url, { timeout: attempt === 3 ? 30_000 : 15_000 });
      return;
    } catch (caught) {
      if (attempt === 3) throw caught;
    }
  }

  throw new Error(`${what} never reached ${String(url)} after three clicks`);
}

/**
 * Open a term the school has released, whichever child it belongs to.
 *
 * §10's fixture gives the test parent **two children in different classes**,
 * and a run typically has only one of those classes published — so "the
 * first child" is a coin flip, and a spec that assumed it passed or failed
 * depending on the seed's ordering. This walks the children until it finds
 * one with something to open.
 *
 * Starts on `/children` and ends on a report card.
 */
export async function openAReleasedTerm(page: Page): Promise<void> {
  const children = page.getByRole("link", { name: /view results/i });
  const count = await children.count();

  for (let index = 0; index < count; index += 1) {
    await children.nth(index).click();
    await expect(page).toHaveURL(/\/children\/[0-9a-f-]+$/, { timeout: 30_000 });

    // The page is server-rendered, so once the URL is the child's its heading
    // is already there — and then either there is a term to open or there is
    // not. Waiting for the heading is what makes the next check meaningful
    // rather than a race.
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30_000 });

    // Matched on the subtitle every released term's link carries, not on its
    // badge: the badge reads "View result" or "Seen", so the accessible name
    // is "Third Term Report card and PDF Seen" — which no anchored pattern
    // for either badge can match. A term the school has **not** released is a
    // card with R12's sentence and no link at all.
    const term = page.getByRole("link", { name: /report card and pdf/i }).first();
    if ((await term.count()) > 0) {
      await term.click();
      return;
    }

    // `goto`, not `goBack`: the parent's session renews by bouncing through
    // `/api/session` (D89), so how many entries back `/children` is depends
    // on whether the access cookie happened to be stale. A hard navigation is
    // safe here — these pages are server-rendered against this origin's own
    // cookie, which is why the specs are allowed to navigate the parent
    // directly and not the staff screens.
    await page.goto("/children");
    await expect(page).toHaveURL(/\/children$/, { timeout: 30_000 });
  }

  throw new Error(`none of this parent's ${count} children has a released term`);
}
