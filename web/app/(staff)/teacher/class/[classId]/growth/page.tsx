"use client";

/** §9's section 2 — height and weight, start and end of term (§8.3). */

import { ClassGrowth } from "@/components/class-records";

import { useClassContext } from "../context";

export default function ClassGrowthPage() {
  const { api, classId, termId } = useClassContext();
  return <ClassGrowth api={api} classId={classId} termId={termId} />;
}
