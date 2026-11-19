"use client";

/** The early-years form's header lines: dominance and years in school (D128). */

import { EarlyYearsDetailsGrid } from "@/components/class-records";

import { useClassContext } from "../context";

export default function EarlyYearsDetailsPage() {
  const { api, classId, termId } = useClassContext();
  return <EarlyYearsDetailsGrid api={api} classId={classId} termId={termId} />;
}
