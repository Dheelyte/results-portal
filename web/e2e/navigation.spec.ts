/**
 * §8.0's shell and every route behind it, in a browser.
 *
 * `full-term.spec.ts` proves the *work* can be done; this proves you can get
 * to it. The two are separate because they need different things:
 *
 * - The journey needs a **freshly seeded** database, because a class can
 *   only be published once.
 * - This needs only a *seeded* one, so it can be run again and again against
 *   a stack that has already been through the journey — which is exactly
 *   when you want to check that a change to the interface broke nothing.
 *
 * It is driven at a phone viewport, because that is where the sidebar is a
 * drawer and §8.1 and §8.5 both specify one. Every assertion here is about
 * reaching a page and the page saying which page it is; what the page then
 * does is the journey's business and the API suite's.
 *
 * These are **independent** tests, not a story, so one failure names one
 * broken route instead of stopping the rest.
 */

import { expect, test, type Page } from "@playwright/test";

import { ACCOUNTS, DEMO_PASSWORD } from "./api";
import {
  clickThrough,
  navigate,
  openAReleasedTerm,
  signInAsParent,
  signInAsStaff,
} from "./sign-in";

/** The signed-in name and the avatar beside it are the header's whole job. */
async function headerShowsWhoIsSignedIn(page: Page): Promise<void> {
  await expect(page.getByRole("button", { name: /sign out/i })).toBeVisible({
    timeout: 20_000,
  });
}

/**
 * The drawer must close when a link inside it is followed.
 *
 * A drawer that survived the navigation it was opened to make would cover
 * the page that arrived — and because it is `position: fixed` over the whole
 * viewport, it would cover it completely.
 */
async function drawerClosed(page: Page): Promise<void> {
  await expect(page.getByRole("dialog", { name: /^menu$/i })).toHaveCount(0, {
    timeout: 20_000,
  });
}

// ---------------------------------------------------------------------------
// The administrator
// ---------------------------------------------------------------------------

test.describe("the admin's sidebar reaches every setup screen", () => {
  // Every link in `ADMIN_NAV`, with the heading the page it leads to shows.
  const DESTINATIONS = [
    { link: /^setup$/i, url: /\/admin$/, heading: /^setup$/i },
    { link: /session & terms/i, url: /\/admin\/calendar$/, heading: /session & terms/i },
    { link: /grading & narrative/i, url: /\/admin\/assessment$/, heading: /grading & narrative/i },
    { link: /^subjects$/i, url: /\/admin\/subjects$/, heading: /^subjects$/i },
    { link: /^classes$/i, url: /\/admin\/classes$/, heading: /^classes$/i },
    { link: /^pupils$/i, url: /\/admin\/pupils$/, heading: /^pupils$/i },
    { link: /^accounts$/i, url: /\/admin\/accounts$/, heading: /^accounts$/i },
    { link: /^publish$/i, url: /\/admin\/publish$/, heading: /publish results/i },
    { link: /audit log/i, url: /\/admin\/audit$/, heading: /audit log/i },
  ] as const;

  for (const { link, url, heading } of DESTINATIONS) {
    test(`${String(link)} opens its own route`, async ({ page }) => {
      await signInAsStaff(page, ACCOUNTS.admin, DEMO_PASSWORD);
      await headerShowsWhoIsSignedIn(page);

      await navigate(page, link, url);
      await drawerClosed(page);
      await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible({
        timeout: 30_000,
      });
    });
  }
});

test("the admin dashboard leads with its headline numbers", async ({ page }) => {
  await signInAsStaff(page, ACCOUNTS.admin, DEMO_PASSWORD);

  const main = page.getByRole("main");
  // Every tile carries a label in words, which is also what makes the
  // colour non-load-bearing: a status tone must never be the only thing
  // saying what a tile means (docs/DECISIONS.md D113).
  for (const label of [
    /pupils on the roll/i,
    /^classes$|^class$/i,
    /staff accounts/i,
  ]) {
    await expect(main.getByText(label).first()).toBeVisible({ timeout: 30_000 });
  }

  // The readiness tile says one of two things, and both are words.
  await expect(
    main.getByText(/teachers can start/i).or(main.getByText(/still to do/i)).first(),
  ).toBeVisible({ timeout: 30_000 });

  // The counting tiles are links to where that number is managed.
  await clickThrough(
    page,
    () => main.getByRole("link", { name: /pupils on the roll/i }).first(),
    /\/admin\/pupils$/,
    "the pupils tile",
  );
});

test("the head teacher's dashboard leads with the state of the queue", async ({ page }) => {
  await signInAsStaff(page, ACCOUNTS.head, DEMO_PASSWORD);

  const main = page.getByRole("main");
  for (const label of [
    /nothing waiting|waiting for you/i,
    /remarks written/i,
    /class(es)? approved/i,
    /returned to teachers/i,
  ]) {
    await expect(main.getByText(label).first()).toBeVisible({ timeout: 30_000 });
  }
});

test.describe("the admin's list → detail routes", () => {
  test("a class opens at its own URL, with a way back", async ({ page }) => {
    await signInAsStaff(page, ACCOUNTS.admin, DEMO_PASSWORD);
    await navigate(page, /^classes$/i, /\/admin\/classes$/);

    const main = page.getByRole("main");
    // D104: the detail is a route, not a panel under the table.
    await clickThrough(
      page,
      () => main.getByRole("link", { name: /subjects & teachers/i }).first(),
      /\/admin\/classes\/[0-9a-f-]+$/,
      "a class",
    );
    await expect(main.getByRole("heading", { name: /class teacher/i })).toBeVisible({
      timeout: 30_000,
    });
    await expect(main.getByRole("heading", { name: /who enters the scores/i })).toBeVisible();

    // Breadcrumbs, and the back button beside them.
    await expect(page.getByRole("navigation", { name: /breadcrumb/i })).toBeVisible();
    await clickThrough(
      page,
      () => main.getByRole("link", { name: /^classes$/i }).first(),
      /\/admin\/classes$/,
      "the way back to the class list",
    );
  });

  test("a term opens at its own URL, with both half-term sheets", async ({ page }) => {
    await signInAsStaff(page, ACCOUNTS.admin, DEMO_PASSWORD);
    await navigate(page, /session & terms/i, /\/admin\/calendar$/);

    const current = page.getByRole("row").filter({ hasText: "Current" }).last();
    await expect(current).toBeVisible({ timeout: 30_000 });
    await clickThrough(
      page,
      () => current.getByRole("link", { name: /^open$/i }),
      /\/admin\/calendar\/[0-9a-f-]+$/,
      "the current term",
    );
    await expect(page.getByTestId("period-first_half")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("period-second_half")).toBeVisible();
    await expect(page.getByRole("navigation", { name: /breadcrumb/i })).toBeVisible();
  });

  test("a parent account's children open at their own URL", async ({ page }) => {
    await signInAsStaff(page, ACCOUNTS.admin, DEMO_PASSWORD);
    await navigate(page, /^accounts$/i, /\/admin\/accounts$/);

    const main = page.getByRole("main");
    await clickThrough(
      page,
      () => main.getByRole("link", { name: /^children$/i }).first(),
      /\/admin\/accounts\/[0-9a-f-]+$/,
      "a parent account",
    );
    await expect(main.getByRole("heading", { name: /attached children/i })).toBeVisible({
      timeout: 30_000,
    });
    await expect(main.getByRole("heading", { name: /attach a child/i })).toBeVisible();
  });

  test("publishing happens at a URL that names the class", async ({ page }) => {
    await signInAsStaff(page, ACCOUNTS.admin, DEMO_PASSWORD);
    await navigate(page, /^publish$/i, /\/admin\/publish$/);

    const main = page.getByRole("main");
    const firstClass = main.getByRole("link", { name: /open to publish or hold back/i }).first();
    await expect(firstClass).toBeVisible({ timeout: 30_000 });

    // D104: the one irreversible action on these screens no longer happens
    // at a URL that says nothing about what it would act on.
    await clickThrough(
      page,
      () => firstClass,
      /\/admin\/publish\/[0-9a-f-]+\?term=[0-9a-f-]+$/,
      "a class to publish",
    );
    await expect(main.getByRole("heading", { name: /^pupils$/i })).toBeVisible({
      timeout: 30_000,
    });

    // And one level further: R13's correction form has a page of its own.
    await clickThrough(
      page,
      () => main.getByRole("link", { name: /^open$/i }).first(),
      /\/admin\/publish\/[0-9a-f-]+\/[0-9a-f-]+\?term=[0-9a-f-]+$/,
      "a pupil's scores",
    );
    await expect(main.getByRole("heading", { name: /^scores$/i })).toBeVisible({
      timeout: 30_000,
    });
    await expect(main.getByRole("heading", { name: /the printable card/i })).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// The teacher
// ---------------------------------------------------------------------------

test.describe("the teacher's shell", () => {
  test("the sidebar lists the classes this teacher leads", async ({ page }) => {
    await signInAsStaff(page, ACCOUNTS.teacher1, DEMO_PASSWORD);
    await headerShowsWhoIsSignedIn(page);

    await navigate(page, /^my sheets$/i, /\/teacher$/);
    await drawerClosed(page);

    // The seed makes teacher1 class teacher of a class, so the drawer has a
    // section for it — which is the one extra request the shell spends
    // (docs/DECISIONS.md D103).
    await page.getByRole("button", { name: /open the menu/i }).click();
    const drawer = page.getByRole("dialog", { name: /^menu$/i });
    await expect(drawer).toBeVisible({ timeout: 20_000 });
    await expect(drawer.getByText(/^my class(es)?$/i)).toBeVisible({ timeout: 20_000 });
  });

  test("the five class views are five routes", async ({ page }) => {
    await signInAsStaff(page, ACCOUNTS.teacher1, DEMO_PASSWORD);

    const main = page.getByRole("main");
    // "My classes" on the landing page, not the sidebar's copy of the name.
    await clickThrough(
      page,
      () => main.getByRole("link", { name: /primary/i }).first(),
      /\/teacher\/class\/[0-9a-f-]+$/,
      "this teacher's own class",
    );

    const tabs = page.getByRole("navigation", { name: /class records/i });
    await expect(tabs).toBeVisible({ timeout: 30_000 });

    // D104: each was a `?tab=` switched by `router.replace`; each is a route.
    for (const [label, suffix] of [
      [/^narrative$/i, "/narrative"],
      [/^attendance$/i, "/attendance"],
      [/height & weight/i, "/growth"],
      [/class teacher's comment/i, "/comments"],
    ] as const) {
      await clickThrough(
        page,
        () => tabs.getByRole("link", { name: label }),
        new RegExp(`/teacher/class/[0-9a-f-]+${suffix}$`),
        `the ${String(label)} view`,
      );
      // The header above the tabs is the layout's, fetched once and kept.
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    }
  });

  test("a sheet opens from the landing page", async ({ page }) => {
    await signInAsStaff(page, ACCOUNTS.teacher1, DEMO_PASSWORD);

    const sheet = page
      .getByRole("main")
      .getByRole("link", { name: /first half term/i })
      .first();
    await expect(sheet).toBeVisible({ timeout: 30_000 });
    await clickThrough(
      page,
      () => sheet,
      /\/teacher\/[0-9a-f-]+\?period=[0-9a-f-]+$/,
      "a sheet",
    );
    await expect(page.getByTestId("autosave-status")).toBeVisible({ timeout: 30_000 });
  });
});

// ---------------------------------------------------------------------------
// The head teacher
// ---------------------------------------------------------------------------

test("the head teacher lands on the review queue", async ({ page }) => {
  await signInAsStaff(page, ACCOUNTS.head, DEMO_PASSWORD);
  await headerShowsWhoIsSignedIn(page);

  await expect(page.getByRole("heading", { level: 1, name: /classes for review/i })).toBeVisible(
    { timeout: 30_000 },
  );

  await navigate(page, /review queue/i, /\/review$/);
  await drawerClosed(page);
});

// ---------------------------------------------------------------------------
// The parent (§8.5)
// ---------------------------------------------------------------------------

test.describe("the parent's three routes", () => {
  test("children → one child → the card, each with a way back", async ({ page }) => {
    await signInAsParent(page, ACCOUNTS.parent, DEMO_PASSWORD);

    // §10's fixture: this parent has two children, in different classes.
    await expect(page.getByRole("heading", { level: 1, name: /your children/i })).toBeVisible({
      timeout: 30_000,
    });

    await expect(page.getByRole("link", { name: /view results/i }).first()).toBeVisible({
      timeout: 30_000,
    });

    // D104: the terms used to be stacked under the list. They are a route,
    // and `openAReleasedTerm` goes through it — child first, then the card.
    await openAReleasedTerm(page);

    await expect(page).toHaveURL(/\/children\/[0-9a-f-]+\/[0-9a-f-]+/, { timeout: 30_000 });
    await expect(page.getByText(/continuous assessment for/i)).toBeVisible({ timeout: 30_000 });

    // Back up through the breadcrumb, to the child rather than to the list.
    await clickThrough(
      page,
      () => page.getByRole("navigation", { name: /breadcrumb/i }).getByRole("link").last(),
      /\/children\/[0-9a-f-]+$/,
      "the card's breadcrumb",
    );
  });

  test("a child that is not this parent's is not found", async ({ page }) => {
    await signInAsParent(page, ACCOUNTS.parent, DEMO_PASSWORD);

    // R12's posture, applied to a route: a well-formed id that belongs to
    // someone else's child reads exactly like one that belongs to nobody.
    await page.goto("/children/00000000-0000-7000-8000-000000000000");
    await expect(page.getByText(/this page is not available/i)).toBeVisible({
      timeout: 30_000,
    });
  });
});
