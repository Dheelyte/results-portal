"use client";

import { useMemo } from "react";

import { adminApi, type AdminApi } from "@/lib/api/admin";
import { useAuth } from "@/lib/auth";

/**
 * The admin API bound to the current access token.
 *
 * `null` while the session is still being restored, which every screen
 * treats as "not ready yet" rather than as an error.
 */
export function useAdminApi(): AdminApi | null {
  const { token } = useAuth();
  return useMemo(() => (token ? adminApi(token) : null), [token]);
}
