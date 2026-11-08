"use client";

/**
 * The class the five views of §8.3 are all about.
 *
 * In its own module rather than exported from `layout.tsx`: a layout's job is
 * to be a layout, and Next.js treats extra exports from a route file as
 * something to inspect rather than something to import.
 */

import { createContext, useContext } from "react";

import type { ClassNarrative, TeacherApi } from "@/lib/api/teacher";

export interface ClassContextValue {
  api: TeacherApi;
  classId: string;
  termId: string;
  narrative: ClassNarrative;
  reload: () => void;
}

export const ClassContext = createContext<ClassContextValue | null>(null);

export function useClassContext(): ClassContextValue {
  const value = useContext(ClassContext);
  if (!value) {
    throw new Error("useClassContext must be used inside the class layout");
  }
  return value;
}
