/**
 * The browser's door to the API (ARCHITECTURE.md §7, §5.1).
 *
 * Every type below comes from `schema.d.ts`, which is generated from the
 * OpenAPI schema. Nothing here is hand-written (CLAUDE.md, Conventions), so a
 * field renamed in a Pydantic model breaks `npm run typecheck` rather than
 * breaking a screen in front of an admin.
 *
 * Two things shape this file:
 *
 * - The API is on its own hostname (D13), so requests are cross-origin and
 *   carry `credentials: "include"` for the refresh cookie.
 * - The access token lives in memory only. It is never written to
 *   `localStorage`, where any successful XSS would read it; the refresh token
 *   is httpOnly and not reachable from JavaScript at all.
 */

import type { components } from "./schema";

export type Schemas = components["schemas"];

/** Baked in at build time, so it must be the public hostname. */
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://api.localhost:8080";

export const API_PREFIX = "/api/v1";

export class ApiError extends Error {
  readonly status: number;

  /**
   * Per-row refusals from a bulk write, keyed by pupil id and then by column
   * (§7, `services/errors.py` RowErrors). The score grid paints exactly those
   * cells red; a single message would say that *something* was out of range
   * without saying which.
   */
  readonly rows?: Record<string, Record<string, string>>;

  /**
   * What is still outstanding, from R10's submission gate
   * (`services/errors.py` Blocked). The same shape `GET /progress` returns,
   * so the screen renders one list whichever way it arrived.
   */
  readonly outstanding?: unknown[];

  constructor(
    status: number,
    message: string,
    rows?: ApiError["rows"],
    outstanding?: unknown[],
  ) {
    super(message);
    this.status = status;
    this.rows = rows;
    this.outstanding = outstanding;
    this.name = "ApiError";
  }

  /** The caller must change their password before anything else (§5.1). */
  get isPasswordChangeRequired(): boolean {
    return this.status === 409 && /change your password/i.test(this.message);
  }
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface RequestOptions {
  method?: Method;
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
  /** Omitted for the auth endpoints, which have no token yet. */
  token?: string | null;
  signal?: AbortSignal;
}

function url(path: string, query?: RequestOptions["query"]): string {
  const target = new URL(`${API_URL}${API_PREFIX}${path}`);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== null && value !== undefined && value !== "") {
      target.searchParams.set(key, String(value));
    }
  }
  return target.toString();
}

/**
 * The API's error shape, which FastAPI renders two ways: our own
 * `{detail: "a sentence"}`, and its own validation errors as
 * `{detail: [{loc, msg, ...}]}`. Both reach a person, so both are flattened
 * into something readable rather than printed as JSON.
 */
interface Failure {
  message: string;
  rows?: Record<string, Record<string, string>>;
  outstanding?: unknown[];
}

async function failureFrom(response: Response): Promise<Failure> {
  let detail: unknown;
  let rows: Failure["rows"];
  let outstanding: unknown[] | undefined;
  try {
    const body = await response.json();
    detail = body?.detail;
    // Present only on a bulk write that rejected individual rows.
    if (body?.errors && typeof body.errors === "object") {
      rows = body.errors as Failure["rows"];
    }
    // Present only on R10's refusal.
    if (Array.isArray(body?.outstanding)) outstanding = body.outstanding;
  } catch {
    detail = undefined;
  }

  if (typeof detail === "string") return { message: detail, rows, outstanding };

  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        const field = Array.isArray(item?.loc) ? item.loc.at(-1) : undefined;
        const message = typeof item?.msg === "string" ? item.msg : "is invalid";
        return field ? `${String(field)}: ${message}` : message;
      })
      .filter(Boolean);
    if (parts.length) return { message: parts.join("; "), rows, outstanding };
  }

  if (response.status === 401) {
    return { message: "Your session has ended. Please sign in again.", rows, outstanding };
  }
  if (response.status >= 500) {
    return { message: "Something went wrong at our end. Please try again.", rows, outstanding };
  }
  return { message: `Request failed (${response.status}).`, rows, outstanding };
}

/**
 * What to do when a signed-in request is refused with 401: renew the access
 * token and hand back the new one, or null if the session really has ended.
 * Installed by `AuthProvider` (lib/auth.tsx); absent, a 401 is final.
 *
 * Every screen binds its token into an API object when it renders, so a
 * token that expired while a teacher was typing would otherwise fail the
 * save in their hand. This lets that one request renew and go again.
 */
type Renewer = () => Promise<string | null>;
let renewer: Renewer | null = null;

export function setTokenRenewer(next: Renewer | null): void {
  renewer = next;
}

/** Send once; on a 401 for a request that carried a token, renew and resend once. */
async function send(
  token: string | null | undefined,
  attempt: (token: string | null | undefined) => Promise<Response>,
): Promise<Response> {
  const response = await attempt(token);
  if (response.status !== 401 || !token || !renewer) return response;

  const renewed = await renewer();
  if (!renewed || renewed === token) return response;
  return attempt(renewed);
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, token, signal } = options;

  const response = await send(token, (bearer) =>
    fetch(url(path, query), {
      method,
      signal,
      // The refresh cookie is host-only on the API's own hostname, so it only
      // travels when the request asks for credentials.
      credentials: "include",
      headers: {
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...(bearer ? { Authorization: `Bearer ${bearer}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  );

  if (!response.ok) {
    const failure = await failureFrom(response);
    throw new ApiError(response.status, failure.message, failure.rows, failure.outstanding);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/**
 * A binary response as an object URL — the report card PDF (§9).
 *
 * The card's endpoint answers with a 302 to a short-lived signed URL, and
 * `fetch` follows it: the first hop needs the Authorization header this adds,
 * the second needs only the token in the path. The result is a blob the
 * browser can open, print or save.
 *
 * The caller must `URL.revokeObjectURL` when done, or the page holds the
 * whole PDF in memory until it is unloaded.
 */
export async function requestBlob(path: string, options: RequestOptions = {}): Promise<string> {
  const { query, token, signal } = options;

  const response = await send(token, (bearer) =>
    fetch(url(path, query), {
      signal,
      credentials: "include",
      headers: bearer ? { Authorization: `Bearer ${bearer}` } : {},
    }),
  );

  if (!response.ok) {
    const failure = await failureFrom(response);
    throw new ApiError(response.status, failure.message, failure.rows, failure.outstanding);
  }

  return URL.createObjectURL(await response.blob());
}

/* -------------------------------------------------------------------------
 * Authentication (§5.1)
 * ---------------------------------------------------------------------- */

export type TokenResponse = Schemas["TokenResponse"];
export type CurrentUser = Schemas["UserRead"];
export type Role = CurrentUser["role"];

export const login = (identifier: string, password: string) =>
  request<TokenResponse>("/auth/login", {
    method: "POST",
    body: { identifier, password },
  });

/** Exchanges the httpOnly cookie for a new pair. 401 simply means no session. */
export const refresh = () => request<TokenResponse>("/auth/refresh", { method: "POST" });

export const logout = () => request<{ detail: string }>("/auth/logout", { method: "POST" });

/** A parent asks for an account; it waits for an admin (D126). */
export const register = (body: Schemas["RegisterRequest"]) =>
  request<Schemas["RegisterResponse"]>("/auth/register", { method: "POST", body });

export const changePassword = (
  token: string,
  currentPassword: string,
  newPassword: string,
) =>
  request<{ detail: string }>("/auth/change-password", {
    method: "POST",
    token,
    body: { current_password: currentPassword, new_password: newPassword },
  });
