"use client";

import { useMemo } from "react";

import { headApi, type HeadApi } from "@/lib/api/head";
import { useAuth } from "@/lib/auth";

/** The review API bound to the current access token. */
export function useHeadApi(): HeadApi | null {
  const { token } = useAuth();
  return useMemo(() => (token ? headApi(token) : null), [token]);
}
