/**
 * The API, for the parts of the journey that are not what the E2E is testing
 * (ARCHITECTURE.md §10, docs/DECISIONS.md D98).
 *
 * §10's journey is "set up → enter both periods → narrative → submit →
 * approve → publish → parent downloads and acknowledges". Driven entirely
 * through the browser, "enter both periods" alone is 10 pupils × 12 subjects
 * × 7 columns × 2 halves — some 1,700 cells — and the narrative is 16
 * passages per pupil. That test would take an hour and fail for reasons
 * nobody could read.
 *
 * So the bulk is filled here, through the **real API as the real role**, with
 * the same validation and the same authorization the screens go through.
 * Nothing is faked and nothing bypasses a rule; it is simply not clicked.
 * What the browser drives is every screen and every transition of the
 * journey, with representative work typed into each.
 */

import { expect, type APIRequestContext } from "@playwright/test";

export const API_BASE = process.env.E2E_API_URL ?? "http://api.localhost:8080";
const V1 = `${API_BASE}/api/v1`;

/** `python -m app.seed` gives every demo account the same password. */
export const DEMO_PASSWORD = "demo-password-change-me";

export const ACCOUNTS = {
  admin: "admin@sshms.test",
  head: "head@sshms.test",
  // The seed's class teachers, in class order.
  teacher1: "teacher1@sshms.test",
  teacher2: "teacher2@sshms.test",
  teacher3: "teacher3@sshms.test",
  // The seed's first parent has two children in different classes (§10).
  parent: "+2348000000001",
} as const;

/**
 * One token per account for the length of the run; see `signIn`.
 *
 * The **token**, not the `Api` wrapping it: each test gets a fresh
 * `APIRequestContext` and the old one is disposed, so a cached client fails
 * the next test with "target page, context or browser has been closed".
 */
const tokens = new Map<string, { token: string; user: Api["user"] }>();

export class Api {
  private constructor(
    private readonly request: APIRequestContext,
    readonly token: string,
    readonly user: { id: string; full_name: string; role: string },
  ) {}

  /**
   * Sign in, reusing a token already held for this account.
   *
   * Not an optimisation. §5.1 now limits sign-ins to 20 per 15 minutes per
   * address (A34), and this journey signs in at every step: without the
   * cache it spends most of one allowance on itself, and a second run inside
   * the window spends the rest. The access token lasts 30 minutes, which is
   * longer than the whole journey.
   *
   * The stack the E2E runs against also raises the limit — see
   * `docs/RUNBOOK.md` §4 — because the browser sign-ins cannot be cached:
   * the staff screens keep their token in memory (D41), so each test's fresh
   * context signs in again, which is the thing being tested.
   */
  static async signIn(request: APIRequestContext, identifier: string): Promise<Api> {
    const held = tokens.get(identifier);
    if (held) return new Api(request, held.token, held.user);

    const response = await request.post(`${V1}/auth/login`, {
      data: { identifier, password: DEMO_PASSWORD },
    });
    expect(response.status(), `signing in as ${identifier}`).toBe(200);
    const body = await response.json();

    tokens.set(identifier, { token: body.access_token, user: body.user });
    return new Api(request, body.access_token, body.user);
  }

  private get headers() {
    return { Authorization: `Bearer ${this.token}` };
  }

  async get<T>(path: string): Promise<T> {
    const response = await this.request.get(`${V1}${path}`, { headers: this.headers });
    expect(response.status(), `GET ${path}`).toBe(200);
    return response.json() as Promise<T>;
  }

  async send<T>(method: "post" | "put" | "patch", path: string, data?: unknown): Promise<T> {
    const response = await this.request[method](`${V1}${path}`, {
      headers: this.headers,
      ...(data === undefined ? {} : { data }),
    });
    expect(
      response.ok(),
      `${method.toUpperCase()} ${path} → ${response.status()} ${await response.text()}`,
    ).toBeTruthy();
    const text = await response.text();
    return (text ? JSON.parse(text) : null) as T;
  }
}

// ---------------------------------------------------------------------------
// The shapes this spec reads. Hand-written rather than generated, because
// `lib/api/schema.d.ts` is for the app and these are a test's own view.
// ---------------------------------------------------------------------------

export interface Term {
  id: string;
  number: string;
  is_current: boolean;
  academic_session_id: string;
}

export interface Period {
  id: string;
  half: "first_half" | "second_half";
}

export interface Klass {
  id: string;
  name: string;
  level_order: number;
}

export interface ClassSubject {
  id: string;
  subject_id: string;
  subject_name: string;
}

export interface SheetRow {
  pupil_id: string;
  first_name: string;
  last_name: string;
}

/** The current term, and both of its halves. */
export async function currentTerm(api: Api): Promise<{ term: Term; periods: Period[] }> {
  const terms = await api.get<Term[]>("/terms");
  const term = terms.find((candidate) => candidate.is_current);
  expect(term, "the seed marks one term current").toBeTruthy();
  const periods = await api.get<Period[]>(`/terms/${term!.id}/assessment-periods`);
  expect(periods).toHaveLength(2);
  return { term: term!, periods };
}

/**
 * §10's "set up": what every column is out of.
 *
 * The seed does not write these — nothing in this system defaults a maximum,
 * because A13 makes a sheet's readiness depend on them. The figures are A2's
 * placeholders from the card: five CA tests of 8, a terminal column of 60.
 */
export async function setMarksObtainable(api: Api, period: Period): Promise<void> {
  const terminal = period.half === "first_half" ? "mid_term_test" : "exam";
  await api.send("put", `/assessment-periods/${period.id}/marks-obtainable`, {
    class_id: null,
    ca_test_1: "8",
    ca_test_2: "8",
    ca_test_3: "8",
    ca_test_4: "8",
    ca_test_5: "8",
    [terminal]: "60",
  });
}

/**
 * `value`, or a failed expectation naming what was missing.
 *
 * `noUncheckedIndexedAccess` is on, and in a test the honest response to a
 * missing element is a readable failure rather than a `!`.
 */
export function must<T>(value: T | undefined | null, what: string): T {
  expect(value, `expected ${what}`).toBeTruthy();
  return value as T;
}

export interface Assignment {
  class_subject_id: string;
  class_id: string;
  class_name: string;
  subject_id: string;
  subject_name: string;
}

export interface Workload {
  assignments: Assignment[];
  class_teacher_of: { class_id: string; class_name: string }[];
  periods: { id: string; half: "first_half" | "second_half" }[];
  term: { id: string; number: string; times_school_opened: number };
}

export interface Passage {
  section_id: string;
  label: string;
  body: string | null;
  writable: boolean;
}

/** Fill every column of every pupil on one sheet (R10's gate needs all of
 *  them, and only the assigned teacher may write them). */
export async function fillSheet(
  api: Api,
  classSubjectId: string,
  period: { id: string; half: "first_half" | "second_half" },
): Promise<void> {
  const terminal = period.half === "first_half" ? "mid_term_test" : "exam";
  const sheet = await api.get<{ rows: { pupil_id: string }[] }>(
    `/class-subjects/${classSubjectId}/entries?assessment_period_id=${period.id}`,
  );
  await api.send("put", `/class-subjects/${classSubjectId}/entries`, {
    assessment_period_id: period.id,
    rows: sheet.rows.map((row) => ({
      pupil_id: row.pupil_id,
      ca_test_1: "7",
      ca_test_2: "7",
      ca_test_3: "7",
      ca_test_4: "7",
      ca_test_5: "7",
      [terminal]: "48",
    })),
  });
}

/** Write every passage this teacher is allowed to write for one pupil. */
export async function fillNarrative(api: Api, pupilId: string, termId: string): Promise<number> {
  const page = await api.get<{ passages: Passage[] }>(
    `/pupils/${pupilId}/narrative?term_id=${termId}`,
  );
  const mine = page.passages.filter((passage) => passage.writable);
  if (mine.length === 0) return 0;

  await api.send("put", `/pupils/${pupilId}/narrative?term_id=${termId}`, {
    passages: mine.map((passage) => ({
      section_id: passage.section_id,
      body: passage.body?.trim()
        ? passage.body
        : `Steady, careful work in ${passage.label.toLowerCase()} through the term.`,
    })),
  });
  return mine.length;
}
