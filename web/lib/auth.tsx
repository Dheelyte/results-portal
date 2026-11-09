"use client";

/**
 * Who is signed in, for the whole client tree (ARCHITECTURE.md §5.1).
 *
 * The access token is held in React state and nowhere else. Not
 * `localStorage`, where a successful XSS would read it; not a cookie the
 * client can see. The refresh token is httpOnly on the API's own hostname, so
 * restoring a session after a reload is a `POST /auth/refresh` the browser
 * authenticates with a cookie this code cannot read.
 *
 * The access token lasts 30 minutes; this renews it two minutes early, on
 * waking, and on any 401, so a session lasts as long as the refresh cookie
 * (30 days from last use) rather than as long as one token (D116).
 *
 * That is also why the admin screens are client components. The web server
 * cannot see a cookie set on `api.<domain>`, so it cannot render a signed-in
 * page. §8.5's server-rendered parent view will need a different arrangement
 * — recorded as an open question in docs/DECISIONS.md D41.
 */

import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  ApiError,
  changePassword as apiChangePassword,
  login as apiLogin,
  logout as apiLogout,
  refresh as apiRefresh,
  setTokenRenewer,
  type CurrentUser,
  type TokenResponse,
} from "@/lib/api/client";

/**
 * Renew this long before the access token expires (§5.1: 30 minutes), so a
 * request never meets an expired one in the ordinary case. The 401 retry in
 * `lib/api/client.ts` covers the cases a timer cannot — a laptop that slept
 * through it, a clock that drifted.
 */
const RENEW_AHEAD_MS = 2 * 60 * 1000;

/** After a network failure, not a refusal: try again this soon. */
const RETRY_AFTER_MS = 30 * 1000;

interface AuthState {
  user: CurrentUser | null;
  token: string | null;
  /** True until the first refresh attempt settles, so no screen flashes. */
  loading: boolean;
}

interface AuthContextValue extends AuthState {
  signIn: (identifier: string, password: string) => Promise<CurrentUser>;
  signOut: () => Promise<void>;
  replacePassword: (currentPassword: string, newPassword: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    token: null,
    loading: true,
  });
  const restored = useRef(false);

  // When the access token in hand expires, the pending renewal timer, and
  // the one refresh in flight. Refs, because none of them should re-render.
  const expiresAt = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inFlight = useRef<Promise<string | null> | null>(null);

  const clearTimer = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  }, []);

  const signedOut = useCallback(() => {
    clearTimer();
    expiresAt.current = 0;
    setState({ user: null, token: null, loading: false });
  }, [clearTimer]);

  // Declared before `accept` uses it, assigned below; a ref breaks the cycle
  // between "accept schedules a renewal" and "a renewal calls accept".
  const renewRef = useRef<() => Promise<string | null>>(async () => null);

  const schedule = useCallback(
    (delay: number) => {
      clearTimer();
      timer.current = setTimeout(() => void renewRef.current(), Math.max(delay, 5_000));
    },
    [clearTimer],
  );

  const accept = useCallback(
    (tokens: TokenResponse) => {
      expiresAt.current = Date.now() + tokens.expires_in * 1000;
      schedule(tokens.expires_in * 1000 - RENEW_AHEAD_MS);
      setState({ user: tokens.user, token: tokens.access_token, loading: false });
    },
    [schedule],
  );

  /**
   * Exchange the refresh cookie for a new access token, once at a time.
   *
   * Concurrent callers — the timer, a waking tab, three requests that all
   * met a 401 together — share one `POST /auth/refresh`. Each would
   * otherwise present the same rotating cookie, and the API reads a replay
   * as theft (§5.1).
   *
   * A **refusal** (401/403) ends the session. A network failure or a 5xx —
   * the API restarting during a deploy — does not: the cookie is probably
   * still good, so this keeps the user and tries again shortly.
   */
  const renew = useCallback((): Promise<string | null> => {
    if (inFlight.current) return inFlight.current;

    inFlight.current = apiRefresh()
      .then((tokens) => {
        accept(tokens);
        return tokens.access_token;
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
          // The ordinary "not signed in" case, not an error.
          signedOut();
        } else {
          schedule(RETRY_AFTER_MS);
          setState((current) => ({ ...current, loading: false }));
        }
        return null;
      })
      .finally(() => {
        inFlight.current = null;
      });

    return inFlight.current;
  }, [accept, schedule, signedOut]);

  useEffect(() => {
    renewRef.current = renew;
  }, [renew]);

  useEffect(() => {
    // Once per mount, even under React's development double-render.
    if (restored.current) return;
    restored.current = true;
    void renew();
  }, [renew]);

  useEffect(() => {
    setTokenRenewer(() => renewRef.current());

    // A laptop lid closed over lunch: timers do not run while it sleeps, so
    // check on the way back rather than wait for the first request to fail.
    const onWake = () => {
      if (document.visibilityState !== "visible" || !expiresAt.current) return;
      if (expiresAt.current - Date.now() < RENEW_AHEAD_MS) void renewRef.current();
    };
    document.addEventListener("visibilitychange", onWake);
    window.addEventListener("online", onWake);

    return () => {
      setTokenRenewer(null);
      document.removeEventListener("visibilitychange", onWake);
      window.removeEventListener("online", onWake);
      clearTimer();
    };
  }, [clearTimer]);

  const signIn = useCallback(
    async (identifier: string, password: string) => {
      const tokens = await apiLogin(identifier, password);
      accept(tokens);
      return tokens.user;
    },
    [accept],
  );

  const signOut = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      // Whether or not the server had anything to revoke, this browser is
      // signed out — a failed logout must not leave a usable token in memory.
      signedOut();
    }
  }, [signedOut]);

  const replacePassword = useCallback(
    async (currentPassword: string, newPassword: string) => {
      if (!state.token) throw new ApiError(401, "Please sign in again.");
      await apiChangePassword(state.token, currentPassword, newPassword);
      // The API revokes every session on a password change (§5.1), so the
      // token in hand is already dead.
      signedOut();
    },
    [state.token, signedOut],
  );

  const value = useMemo(
    () => ({ ...state, signIn, signOut, replacePassword }),
    [state, signIn, signOut, replacePassword],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}

/**
 * Keep a page for signed-in users of a given role, or send them somewhere
 * they can do something about it.
 *
 * This is **convenience, not security**. Every one of these endpoints is
 * gated server-side by `authz/dependencies.py` against the §5.2 matrix; a
 * redirect in a browser protects nothing. It exists so a teacher who follows
 * an admin link sees an explanation rather than a page of failed requests.
 */
export function useRequireRole(role: CurrentUser["role"]): AuthContextValue {
  const auth = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (auth.loading) return;
    if (!auth.user) {
      router.replace("/login");
    } else if (auth.user.must_change_password) {
      router.replace("/change-password");
    }
  }, [auth.loading, auth.user, role, router]);

  return auth;
}
