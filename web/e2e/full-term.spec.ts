/**
 * §10's one E2E journey, end to end through the browser.
 *
 *   set up → enter both periods → narrative → submit → approve → publish
 *   → parent downloads and acknowledges
 *
 * **Precondition:** a freshly seeded database — `docs/RUNBOOK.md` has the two
 * commands. The seed is §10's own fixture, and this spec leans on two of its
 * details: the class teacher of Primary 4 is `teacher1`, and `parent1` is
 * guardian to a child in that class.
 *
 * **What is clicked and what is not.** Every screen and every state
 * transition of the journey happens in the browser. The bulk — the remaining
 * ~1,600 score cells and ~150 narrative passages — is filled through the
 * real API as the real role, with the same validation and the same
 * authorization the screens go through. Nothing is faked; it is simply not
 * typed. `e2e/api.ts` and docs/DECISIONS.md D98 say why.
 *
 * Driven at a phone viewport, because §8.1 and §8.5 both specify one.
 *
 * **The staff screens are navigated by clicking**, never by `page.goto`.
 * That is closer to what an admin does, and in development it is the only
 * thing that works: the staff session holds its access token in memory (D41)
 * and restores it from the refresh cookie on reload — but Chrome treats
 * `localhost` as a public suffix, so `localhost` ↔ `api.localhost` is
 * cross-**site** in development while `portal.x.ng` ↔ `api.x.ng` is
 * same-site in production. `SameSite=Lax` therefore withholds the cookie
 * here and sends it there, and a hard navigation lands back on the sign-in
 * screen. It errs safe — development is stricter than production — and
 * `docs/RUNBOOK.md` §5 has the `.test` recipe for mirroring production
 * exactly. The parent's pages are server-rendered against this origin's own
 * cookie (D89), so those are navigated directly.
 */

import { expect, test, type Page } from "@playwright/test";

import {
  ACCOUNTS,
  Api,
  DEMO_PASSWORD,
  currentTerm,
  fillNarrative,
  fillSheet,
  must,
  setMarksObtainable,
  type Assignment,
  type Period,
  type Term,
  type Workload,
} from "./api";

// One story told in order: a class cannot be approved before it is
// submitted. These are steps, not independent tests.
test.describe.configure({ mode: "serial" });

interface Journey {
  term: Term;
  periods: Period[];
  classId: string;
  className: string;
  /** The class teacher's own assignments in that class. */
  mine: Assignment[];
  pupils: { pupil_id: string; first_name: string; last_name: string }[];
}

const journey = {} as Journey;

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
async function signInAsStaff(page: Page, identifier: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel(/email address or phone/i).fill(identifier);
  await page.getByLabel(/^password/i).fill(DEMO_PASSWORD);

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

/**
 * Wait for §8.1's autosave to settle.
 *
 * Asserting on "Saved" is wrong: the indicator is a live status, and once a
 * save lands and the sheet refetches it returns to "No changes" — a
 * terminal label this test would race. What matters is that nothing is still
 * outstanding, and then that the value is there when the screen is opened
 * again, which is the next assertion either caller makes.
 */
async function autosaveSettles(page: Page): Promise<void> {
  const status = page.getByTestId("autosave-status");
  await expect(status).toBeVisible({ timeout: 20_000 });
  await expect(status).not.toHaveText(/unsaved|saving|not saved/i, { timeout: 20_000 });
}

/** The parent's door is a different screen entirely (§8.5, D89). */
async function signInAsParent(page: Page, identifier: string): Promise<void> {
  await page.goto("/");
  await page.getByLabel(/email address or phone/i).fill(identifier);
  await page.getByLabel(/^password/i).fill(DEMO_PASSWORD);

  // No retry needed here: this is a `<form>` posting to a server action, so
  // it works before any JavaScript has loaded at all (D90). That is the
  // whole point of §8.5's "3G on a low-end Android device", and it is also
  // why this screen is the steadiest thing in the journey.
  await page.getByRole("button", { name: /^sign in$/i }).click();
  await expect(page).toHaveURL(/\/children$/, { timeout: 30_000 });
}

test.describe("a full term, from an empty sheet to a parent's acknowledgement", () => {
  // -------------------------------------------------------------------------
  // Set up
  // -------------------------------------------------------------------------

  test("the admin says what every column is out of", async ({ page, request }) => {
    const admin = await Api.signIn(request, ACCOUNTS.admin);
    const { term, periods } = await currentTerm(admin);
    journey.term = term;
    journey.periods = periods;

    const first = must(
      periods.find((period) => period.half === "first_half"),
      "a first-half assessment period",
    );

    // The first half through the rule, the second through the screen, so both
    // the service and the form that feeds it are exercised.
    await setMarksObtainable(admin, first);

    await signInAsStaff(page, ACCOUNTS.admin);
    await page
      .getByRole("navigation", { name: /setup sections/i })
      .getByRole("link", { name: /session & terms/i })
      .click();

    // The two half-term cards are behind the term's own "Open". Found by the
    // row that says "Current" rather than by the term's name, so the test
    // does not care which term the school is in.
    const currentTermRow = page.getByRole("row").filter({ hasText: "Current" }).last();
    await expect(currentTermRow).toBeVisible({ timeout: 20_000 });
    await currentTermRow.getByRole("button", { name: /^open$/i }).click();

    const secondHalf = page
      .getByRole("heading", { name: "Second Half Term" })
      .locator("xpath=..");
    await expect(secondHalf).toBeVisible({ timeout: 20_000 });

    for (let index = 1; index <= 5; index += 1) {
      await secondHalf.getByLabel(`CA Test ${index}`, { exact: true }).fill("8");
    }
    await secondHalf.getByLabel("Exam", { exact: true }).fill("60");
    await secondHalf.getByRole("button", { name: /save marks obtainable/i }).click();

    await expect(page.getByText(/marks obtainable saved/i)).toBeVisible({ timeout: 20_000 });
  });

  // -------------------------------------------------------------------------
  // Enter both periods
  // -------------------------------------------------------------------------

  test("a teacher types a score into the grid and it survives a reload", async ({
    page,
    request,
  }) => {
    const teacher = await Api.signIn(request, ACCOUNTS.teacher1);
    const workload = await teacher.get<Workload>(`/my/assignments?term_id=${journey.term.id}`);

    // The class this teacher is class teacher of — the one they may submit.
    const own = must(workload.class_teacher_of[0], "a class this teacher leads");
    journey.classId = own.class_id;
    journey.className = own.class_name;
    journey.mine = workload.assignments.filter(
      (assignment) => assignment.class_id === own.class_id,
    );
    expect(journey.mine.length, "subjects this teacher teaches in their own class")
      .toBeGreaterThan(0);

    await signInAsStaff(page, ACCOUNTS.teacher1);

    // The landing page lists every sheet this teacher owns, with a link per
    // half term. Take the first one offered rather than deciding in advance
    // which subject to open — that is what a teacher does, and it leaves the
    // test with nothing to assume about the seed's subject order.
    const firstSheetLink = page.getByRole("link", { name: /first half term/i }).first();
    await expect(firstSheetLink).toBeVisible({ timeout: 20_000 });
    await firstSheetLink.click();

    // Which sheet that was, from where the browser ended up.
    await expect(page).toHaveURL(/\/teacher\/[0-9a-f-]+\?period=/, { timeout: 20_000 });
    const opened = must(
      /\/teacher\/([0-9a-f-]+)\?period=([0-9a-f-]+)/.exec(page.url()),
      "a class-subject and period in the URL",
    );
    const classSubjectId = must(opened[1], "the class-subject id");
    const periodId = must(opened[2], "the period id");

    const rows = await teacher.get<{ rows: Journey["pupils"] }>(
      `/class-subjects/${classSubjectId}/entries?assessment_period_id=${periodId}`,
    );
    journey.pupils = rows.rows;
    expect(journey.pupils.length, "the seed enrolls ten pupils a class").toBe(10);

    const pupil = must(journey.pupils[0], "a pupil");
    const cell = page.getByLabel(`CA Test 1 for ${pupil.last_name}, ${pupil.first_name}`);
    await expect(cell).toBeVisible({ timeout: 20_000 });

    await cell.fill("7");
    // §8.1: autosave on blur. Nothing is clicked.
    await cell.blur();
    await autosaveSettles(page);

    // Away and back, within the app, which re-fetches the sheet from the API
    // — so a value that comes back was persisted and not merely held in
    // React state. Not `page.reload()`: a hard navigation drops the staff
    // token, which in development the refresh cookie cannot restore (see the
    // note at the top of this file).
    await page.getByRole("link", { name: /my classes/i }).first().click();
    await expect(
      page.getByRole("link", { name: /first half term/i }).first(),
      "the landing page should no longer say nothing is entered",
    ).not.toHaveText(/0 of \d+ entered/, { timeout: 20_000 });

    await page.getByRole("link", { name: /first half term/i }).first().click();
    await expect(
      page.getByLabel(`CA Test 1 for ${pupil.last_name}, ${pupil.first_name}`),
    ).toHaveValue("7", { timeout: 20_000 });
  });

  test("every sheet of both halves is filled", async ({ request }) => {
    // Two teachers, because the seed gives the specialist subjects to a third
    // party (B1/D15) and only the assigned teacher may write a sheet.
    for (const account of [ACCOUNTS.teacher1, ACCOUNTS.teacher3]) {
      const teacher = await Api.signIn(request, account);
      const workload = await teacher.get<Workload>(`/my/assignments?term_id=${journey.term.id}`);
      const here = workload.assignments.filter(
        (assignment) => assignment.class_id === journey.classId,
      );

      for (const period of journey.periods) {
        for (const assignment of here) {
          await fillSheet(teacher, assignment.class_subject_id, period);
        }
      }
    }
  });

  // -------------------------------------------------------------------------
  // Narrative
  // -------------------------------------------------------------------------

  test("the class teacher writes a passage in the browser", async ({ page }) => {
    const pupil = must(journey.pupils[0], "a pupil");

    await signInAsStaff(page, ACCOUNTS.teacher1);
    await page.getByRole("link", { name: journey.className, exact: true }).first().click();
    await page
      .getByRole("link", { name: new RegExp(pupil.last_name, "i") })
      .first()
      .click();

    const passage = page.locator("textarea:not([disabled])").first();
    await expect(passage).toBeVisible({ timeout: 20_000 });
    await passage.fill("A purposeful and settled term, written in the browser.");
    await passage.blur();
    await autosaveSettles(page);

    // And it is on the server, not only in the textarea: away and back.
    await page.getByRole("link", { name: new RegExp(journey.className, "i") }).first().click();
    await page
      .getByRole("link", { name: new RegExp(pupil.last_name, "i") })
      .first()
      .click();
    await expect(page.locator("textarea:not([disabled])").first()).toHaveValue(
      /written in the browser/,
      { timeout: 20_000 },
    );
  });

  test("the rest of the sixteen sections, for every pupil", async ({ request }) => {
    for (const account of [ACCOUNTS.teacher1, ACCOUNTS.teacher3]) {
      const teacher = await Api.signIn(request, account);
      for (const pupil of journey.pupils) {
        await fillNarrative(teacher, pupil.pupil_id, journey.term.id);
      }
    }

    // R10 counts attendance and the class teacher's comment too.
    const classTeacher = await Api.signIn(request, ACCOUNTS.teacher1);
    const workload = await classTeacher.get<Workload>(
      `/my/assignments?term_id=${journey.term.id}`,
    );
    const opened = workload.term.times_school_opened;

    await classTeacher.send(
      "put",
      `/classes/${journey.classId}/attendance?term_id=${journey.term.id}`,
      {
        rows: journey.pupils.map((pupil) => ({
          pupil_id: pupil.pupil_id,
          times_present: opened - 2,
          times_absent: 2,
          times_late: 0,
        })),
      },
    );
    await classTeacher.send(
      "put",
      `/classes/${journey.classId}/comments?term_id=${journey.term.id}`,
      {
        rows: journey.pupils.map((pupil) => ({
          pupil_id: pupil.pupil_id,
          comment: "A purposeful and settled term.",
        })),
      },
    );

    // And height and weight — §9's section 2, which R10 counts as well. The
    // gate's own words for a pupil without them are "height and weight".
    await classTeacher.send(
      "put",
      `/classes/${journey.classId}/growth?term_id=${journey.term.id}`,
      {
        rows: journey.pupils.map((pupil) => ({
          pupil_id: pupil.pupil_id,
          height_start_m: "1.32",
          height_end_m: "1.35",
          weight_start_kg: "29.5",
          weight_end_kg: "30.2",
        })),
      },
    );
  });

  // -------------------------------------------------------------------------
  // Submit
  // -------------------------------------------------------------------------

  test("the class teacher sends the class to the head teacher", async ({ page }) => {
    await signInAsStaff(page, ACCOUNTS.teacher1);
    await page.getByRole("link", { name: journey.className, exact: true }).first().click();

    const send = page.getByRole("button", { name: /send to head teacher/i });
    await expect(send).toBeVisible({ timeout: 20_000 });
    await expect(send, "R10's gate should be satisfied by now").toBeEnabled();
    await send.click();

    await expect(page.getByText(/submitted for review/i).first()).toBeVisible({
      timeout: 30_000,
    });
  });

  // -------------------------------------------------------------------------
  // Approve
  // -------------------------------------------------------------------------

  test("the head teacher approves, which freezes the grades", async ({ page }) => {
    await signInAsStaff(page, ACCOUNTS.head);
    await expect(page.getByText(/classes for review/i)).toBeVisible({ timeout: 20_000 });

    // The queue lists the class by name and offers a "Review" link; the
    // banner has one of its own, so this is scoped to the page body.
    await expect(page.getByRole("heading", { name: journey.className })).toBeVisible();
    await page
      .getByRole("main")
      .getByRole("link", { name: /^review$/i })
      .first()
      .click();

    await page.getByRole("button", { name: /^approve this class$/i }).click();

    // §4.5's warning is read and confirmed, not clicked past.
    await expect(page.getByText(/approving freezes every grade/i)).toBeVisible();
    await page.getByRole("button", { name: /yes, approve and freeze the grades/i }).click();

    await expect(page.getByText(/approved/i).first()).toBeVisible({ timeout: 30_000 });
  });

  // -------------------------------------------------------------------------
  // Publish
  // -------------------------------------------------------------------------

  test("the admin publishes the class", async ({ page, request }) => {
    await signInAsStaff(page, ACCOUNTS.admin);
    await page
      .getByRole("navigation", { name: /setup sections/i })
      .getByRole("link", { name: /^publish$/i })
      .click();
    await expect(page.getByText(/publish results/i).first()).toBeVisible({ timeout: 20_000 });

    // By **role**, not `getByLabel`: each `<select>` sits inside its own
    // `<label>`, so the label's text content is "Class" followed by every
    // option — the accessible name is still just "Class", and that is what
    // the role locator matches.
    //
    // Selected by id rather than by option text: the term's reads "third
    // term (current)", which is a sentence about today rather than a name.
    await page
      .getByRole("combobox", { name: "Class", exact: true })
      .selectOption(journey.classId);
    await page
      .getByRole("combobox", { name: "Term", exact: true })
      .selectOption(journey.term.id);

    await page
      .getByRole("button", { name: /^publish/i })
      .first()
      .click();

    // Wait for something only a publication produces. Not the word
    // "published": the page's own prose says "A class is published once the
    // head teacher has approved it", so matching that raced the publish and
    // the API check below failed on a class half-way through.
    //
    // §11 takes a pg_dump before the first row moves, so this is slower than
    // a click usually is.
    await expect(page.getByRole("button", { name: /hold back/i })).toHaveCount(10, {
      timeout: 90_000,
    });

    // And from the API, so this is the rows moving rather than the screen.
    const admin = await Api.signIn(request, ACCOUNTS.admin);
    const state = await admin.get<{ reports: { state: string }[] }>(
      `/classes/${journey.classId}/publication?term_id=${journey.term.id}`,
    );
    expect(state.reports.length).toBe(10);
    expect(state.reports.every((report) => report.state === "published")).toBeTruthy();
  });

  // -------------------------------------------------------------------------
  // The parent
  // -------------------------------------------------------------------------

  test("a parent opens the card, downloads the PDF and acknowledges it", async ({ page }) => {
    await signInAsParent(page, ACCOUNTS.parent);

    // §10's fixture: this parent has two children, in different classes.
    await expect(page.getByRole("heading", { name: /your children/i })).toBeVisible();

    const open = page.getByRole("link", { name: /view result/i }).first();
    await expect(open, "a published term to open").toBeVisible({ timeout: 20_000 });
    await open.click();

    // §9's card, in the order the paper prints it.
    await expect(page.getByText(/continuous assessment for/i)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("3. Cognitive Ability")).toBeVisible();
    await expect(page.getByText(/grand total/i)).toBeVisible();

    // The PDF: a plain link, so a download rather than a fetch (D90).
    const downloading = page.waitForEvent("download", { timeout: 60_000 });
    await page.getByRole("link", { name: /download pdf/i }).click();
    const file = await downloading;
    expect(file.suggestedFilename()).toMatch(/\.pdf$/);

    // A8: this replaces the signature and the physical return of the card.
    await page.getByRole("button", { name: /i have seen this result/i }).click();
    await expect(page.getByText(/you confirmed you have seen this result/i)).toBeVisible({
      timeout: 30_000,
    });
  });
});
