"use client";

/**
 * §8.3's progress view: every subject with its state and owner, every
 * pupil's outstanding items, and R10's submission gate.
 *
 * The default view of a class, because it is the one that says what is left
 * to do — and §8.3 puts the Send button on it.
 */

import { ClassProgress } from "@/components/class-progress";

import { useClassContext } from "./context";

export default function ClassProgressPage() {
  const { api, classId, termId } = useClassContext();
  return <ClassProgress api={api} classId={classId} termId={termId} />;
}
