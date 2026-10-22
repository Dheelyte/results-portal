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
  type CurrentUser,
} from "@/lib/api/client";

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

  useEffect(() => {
    // Once per mount, even under React's development double-render.
    if (restored.current) return;
    restored.current = true;

    let cancelled = false;
    apiRefresh()
      .then((tokens) => {
        if (!cancelled) {
          setState({ user: tokens.user, token: tokens.access_token, loading: false });
        }
      })
      .catch(() => {
        // A 401 here is the ordinary "not signed in" case, not an error.
        if (!cancelled) setState({ user: null, token: null, loading: false });
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(async (identifier: string, password: string) => {
    const tokens = await apiLogin(identifier, password);
    setState({ user: tokens.user, token: tokens.access_token, loading: false });
    return tokens.user;
  }, []);

  const signOut = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      // Whether or not the server had anything to revoke, this browser is
      // signed out — a failed logout must not leave a usable token in memory.
      setState({ user: null, token: null, loading: false });
    }
  }, []);

  const replacePassword = useCallback(
    async (currentPassword: string, newPassword: string) => {
      if (!state.token) throw new ApiError(401, "Please sign in again.");
      await apiChangePassword(state.token, currentPassword, newPassword);
      // The API revokes every session on a password change (§5.1), so the
      // token in hand is already dead.
      setState({ user: null, token: null, loading: false });
    },
    [state.token],
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
