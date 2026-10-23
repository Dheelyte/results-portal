"use client";

import { useMemo } from "react";

import { teacherApi, type TeacherApi } from "@/lib/api/teacher";
import { useAuth } from "@/lib/auth";

/**
 * The teacher API bound to the current access token.
 *
 * `null` while the session is still being restored, which every screen treats
 * as "not ready yet" rather than as an error.
 */
export function useTeacherApi(): TeacherApi | null {
  const { token } = useAuth();
  return useMemo(() => (token ? teacherApi(token) : null), [token]);
}
