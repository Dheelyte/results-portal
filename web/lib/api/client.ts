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

  constructor(status: number, message: string, rows?: ApiError["rows"]) {
    super(message);
    this.status = status;
    this.rows = rows;
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
}

async function failureFrom(response: Response): Promise<Failure> {
  let detail: unknown;
  let rows: Failure["rows"];
  try {
    const body = await response.json();
    detail = body?.detail;
    // Present only on a bulk write that rejected individual rows.
    if (body?.errors && typeof body.errors === "object") {
      rows = body.errors as Failure["rows"];
    }
  } catch {
    detail = undefined;
  }

  if (typeof detail === "string") return { message: detail, rows };

  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        const field = Array.isArray(item?.loc) ? item.loc.at(-1) : undefined;
        const message = typeof item?.msg === "string" ? item.msg : "is invalid";
        return field ? `${String(field)}: ${message}` : message;
      })
      .filter(Boolean);
    if (parts.length) return { message: parts.join("; "), rows };
  }

  if (response.status === 401) {
    return { message: "Your session has ended. Please sign in again.", rows };
  }
  if (response.status >= 500) {
    return { message: "Something went wrong at our end. Please try again.", rows };
  }
  return { message: `Request failed (${response.status}).`, rows };
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, token, signal } = options;

  const response = await fetch(url(path, query), {
    method,
    signal,
    // The refresh cookie is host-only on the API's own hostname, so it only
    // travels when the request asks for credentials.
    credentials: "include",
    headers: {
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) {
    const failure = await failureFrom(response);
    throw new ApiError(response.status, failure.message, failure.rows);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
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
