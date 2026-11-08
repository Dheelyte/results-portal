"use client";

/** R9's attendance, for the whole class at once (§8.3). */

import { ClassAttendance } from "@/components/class-records";

import { useClassContext } from "../context";

export default function ClassAttendancePage() {
  const { api, classId, termId } = useClassContext();
  return <ClassAttendance api={api} classId={classId} termId={termId} />;
}
