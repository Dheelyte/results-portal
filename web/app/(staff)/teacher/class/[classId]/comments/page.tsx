"use client";

/** The class teacher's own comment on each pupil (§8.3, §9). */

import { ClassComments } from "@/components/class-records";

import { useClassContext } from "../context";

export default function ClassCommentsPage() {
  const { api, classId, termId } = useClassContext();
  return <ClassComments api={api} classId={classId} termId={termId} />;
}
