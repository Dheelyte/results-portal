/**
 * The parent view's session, held by the web server (ARCHITECTURE.md §8.5,
 * docs/DECISIONS.md D41 option 1, D89).
 *
 * §8.5 asks for a **server-rendered** report card under 150 KB with "no
 * client-side fetching for the report itself". The staff screens cannot do
 * that: the API's refresh cookie is httpOnly and scoped to `api.<domain>`
 * (D13), so the Next.js server on `<domain>` cannot read it and cannot
 * render a signed-in page at all.
 *
 * So the parent view has its own cookie, set by this origin, holding the
 * refresh token the API issued. A server component reads it, exchanges it
 * for an access token **server-side** over the Docker network, and renders
 * HTML. The browser receives a page, not a bundle that then goes and fetches
 * one.
 *
 * Three properties this keeps:
 *
 * - The cookie is `httpOnly`, `sameSite: lax` and `secure` outside
 *   development, exactly as the API's own is. No JavaScript reads it.
 * - The **access** token never reaches the browser at all. On the staff
 *   screens it lives in React state; here it never leaves the server.
 * - Signing out clears both — this cookie and, through the API, the token
 *   family.
 *
 * **The API is unchanged.** Its refresh token is absent from every response
 * body by design — "returning it in the body would hand it to any successful
 * XSS" — and travels only in an httpOnly cookie. So the web server behaves
 * like a browser: it reads the `Set-Cookie` the API sends and replays it as a
 * `Cookie` header on the next call. Nothing about the API's own guarantee
 * changes, and the token still never reaches a script anywhere.
 */

import { cache } from "react";

import { cookies } from "next/headers";

/** The API as seen from the web server: the short path over the network. */
const INTERNAL_API = process.env.INTERNAL_API_URL ?? "http://api:8000";
const API_PREFIX = "/api/v1";

export const SESSION_COOKIE = "sshms_parent";

/** The access token, cached for its own lifetime so rendering can be
 *  read-only. httpOnly, so no script reads it here either. */
export const ACCESS_COOKIE = "sshms_access";

/** The API's own cookie name and path, which this code presents back to it. */
const API_REFRESH_COOKIE = "refresh_token";

/** Matches the API's own refresh lifetime (§5.1). */
const SESSION_MAX_AGE = 30 * 24 * 60 * 60;

export interface Session {
  accessToken: string;
  user: { id: string; full_name: string; role: string; must_change_password: boolean };
}

function secure(): boolean {
  return process.env.NODE_ENV === "production";
}

export async function storeRefreshToken(token: string): Promise<void> {
  (await cookies()).set(SESSION_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: secure(),
    path: "/",
    maxAge: SESSION_MAX_AGE,
  });
}

export async function storeAccessToken(token: string, maxAge: number): Promise<void> {
  (await cookies()).set(ACCESS_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: secure(),
    path: "/",
    // A minute short of the real lifetime, so a page never picks up a token
    // that expires between being read and being used.
    maxAge: Math.max(30, maxAge - 60),
  });
}

export async function clearSession(): Promise<void> {
  const jar = await cookies();
  jar.delete(SESSION_COOKIE);
  jar.delete(ACCESS_COOKIE);
}

/** The refresh token out of a response's Set-Cookie, or null. */
function refreshTokenFrom(response: Response): string | null {
  for (const header of response.headers.getSetCookie()) {
    const match = header.match(new RegExp(`^${API_REFRESH_COOKIE}=([^;]*)`));
    // An empty value is the API clearing the cookie, not issuing one.
    if (match?.[1]) return match[1];
  }
  return null;
}

/**
 * Sign in against the API and keep its refresh token here.
 *
 * The parent's browser never talks to the API directly, so the cookie the
 * API sets would never be sent back to it. This reads it out and stores the
 * value under this origin's own cookie instead.
 */
/**
 * Why a sign-in failed, as a **code** rather than a message.
 *
 * The parent's sign-in is a server action on a page with no JavaScript, so
 * it reports failure by redirecting back with a query parameter — and a
 * query parameter is attacker-supplied. A message carried that way is a
 * sentence of the attacker's choosing, rendered on the school's own sign-in
 * page under the school's own name: "Your account is suspended, call …".
 * React escapes it, so it is text and not script, but a convincing sentence
 * is the whole of a phishing page.
 *
 * So the page maps a small closed set of codes to its own wording, and an
 * unrecognised code reads as the generic failure.
 */
export type SignInFailure = "credentials" | "locked" | "unavailable";

export async function signIn(
  identifier: string,
  password: string,
): Promise<{ ok: true; user: Session["user"] } | { ok: false; reason: SignInFailure }> {
  const response = await fetch(`${INTERNAL_API}${API_PREFIX}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier, password }),
    cache: "no-store",
  });

  if (!response.ok) {
    // 423 is the API's lockout (§5.1); 401 is a wrong identifier or
    // password, and the API does not say which.
    if (response.status === 423) return { ok: false, reason: "locked" };
    if (response.status === 401) return { ok: false, reason: "credentials" };
    return { ok: false, reason: "unavailable" };
  }

  const token = refreshTokenFrom(response);
  if (!token) {
    return { ok: false, reason: "unavailable" };
  }

  const body = await response.json();
  await storeRefreshToken(token);
  await storeAccessToken(body.access_token, body.expires_in ?? 1800);

  return { ok: true, user: body.user };
}

/**
 * The session as a **read**, for server components.
 *
 * Returns null when there is no usable access token — either the parent is
 * signed out, or the cached token has expired and only `/api/session` may
 * mint a new one. A page distinguishes the two by whether a refresh token is
 * still present, and `sessionState` below says which.
 */
export const currentSession = cache(async function currentSession(): Promise<Session | null> {
  const jar = await cookies();
  const accessToken = jar.get(ACCESS_COOKIE)?.value;
  if (!accessToken) return null;

  const user = await fetchUser(accessToken);
  if (!user) return null;
  return { accessToken, user };
  // `cache` so the shell and the page inside it share one `/auth/me` call
  // rather than making the same round trip twice per render.
});

export type SessionState =
  | { kind: "signed-out" }
  | { kind: "stale" }
  | { kind: "live"; session: Session };

/**
 * What a page should do: render, bounce through `/api/session`, or send the
 * parent to sign in.
 */
export async function sessionState(): Promise<SessionState> {
  const jar = await cookies();
  const live = await currentSession();
  if (live) return { kind: "live", session: live };
  if (jar.get(SESSION_COOKIE)?.value) return { kind: "stale" };
  return { kind: "signed-out" };
}

async function fetchUser(accessToken: string): Promise<Session["user"] | null> {
  const response = await fetch(`${INTERNAL_API}${API_PREFIX}/auth/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
  if (!response.ok) return null;
  return (await response.json()) as Session["user"];
}

/**
 * Exchange the refresh token for a new pair. **Only from a route handler or
 * a server action** — it writes cookies, which a render may not.
 */
export async function refreshSession(): Promise<Session | null> {
  const jar = await cookies();
  const refreshToken = jar.get(SESSION_COOKIE)?.value;
  if (!refreshToken) return null;

  const response = await fetch(`${INTERNAL_API}${API_PREFIX}/auth/refresh`, {
    method: "POST",
    headers: { Cookie: `${API_REFRESH_COOKIE}=${refreshToken}` },
    cache: "no-store",
  });

  if (!response.ok) {
    // Expired, or reuse detection revoked the family (§5.1). Either way the
    // cookie here is worthless, and leaving it would retry on every page.
    await clearSession();
    return null;
  }

  const rotated = refreshTokenFrom(response);
  if (rotated) await storeRefreshToken(rotated);

  const body = await response.json();
  await storeAccessToken(body.access_token, body.expires_in ?? 1800);
  return { accessToken: body.access_token, user: body.user };
}

/**
 * A GET against the API, server-side, as the signed-in parent.
 *
 * `cache: "no-store"` throughout: a cached result card is somebody else's
 * child on a shared device, and Next's default fetch caching would do
 * exactly that.
 */
export async function apiGet<T>(session: Session, path: string): Promise<T | null> {
  const response = await fetch(`${INTERNAL_API}${API_PREFIX}${path}`, {
    headers: { Authorization: `Bearer ${session.accessToken}` },
    cache: "no-store",
  });
  if (!response.ok) return null;
  return (await response.json()) as T;
}

export async function apiPost<T>(session: Session, path: string): Promise<T | null> {
  const response = await fetch(`${INTERNAL_API}${API_PREFIX}${path}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${session.accessToken}` },
    cache: "no-store",
  });
  if (!response.ok) return null;
  return (await response.json()) as T;
}

/** Sign out here and at the API, so the token family is revoked too. */
export async function signOut(): Promise<void> {
  const jar = await cookies();
  const refreshToken = jar.get(SESSION_COOKIE)?.value;
  if (refreshToken) {
    await fetch(`${INTERNAL_API}${API_PREFIX}/auth/logout`, {
      method: "POST",
      headers: { Cookie: `${API_REFRESH_COOKIE}=${refreshToken}` },
      cache: "no-store",
    }).catch(() => undefined);
  }
  await clearSession();
}
