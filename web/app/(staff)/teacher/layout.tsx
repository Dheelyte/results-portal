"use client";

/**
 * The teacher shell (ARCHITECTURE.md §3, §8).
 *
 * A client component for the same reason the admin shell is: the session
 * lives in an httpOnly cookie on `api.<domain>` (D13), which the Next.js
 * server cannot read. See docs/DECISIONS.md D41.
 *
 * The sidebar lists the classes this teacher leads, which costs one
 * `GET /my/assignments` the shell would not otherwise make. It is worth it:
 * §8.3's class page is where attendance, growth and the comment live, and
 * reaching it used to mean going back to the landing page first. A teacher
 * with no class of their own gets a sidebar of one item, which is honest —
 * they only have sheets.
 */

import { BookOpenCheck } from "lucide-react";
import type { ReactNode } from "react";

import { classItem, TEACHER_ROOT, type NavSection } from "@/components/shell/nav";
import { StaffShell } from "@/components/shell/staff-shell";
import { useTeacherApi } from "@/lib/api/use-teacher";
import { useResource } from "@/lib/use-async";

export default function TeacherLayout({ children }: { children: ReactNode }) {
  const api = useTeacherApi();
  const workload = useResource((signal) => api!.workload(undefined, signal), [api], {
    enabled: Boolean(api),
  });

  const myClasses = workload.data?.class_teacher_of ?? [];

  const sections: NavSection[] = [
    { items: [TEACHER_ROOT] },
    ...(myClasses.length > 0
      ? [
          {
            heading: myClasses.length === 1 ? "My class" : "My classes",
            items: myClasses.map((klass) =>
              classItem(klass.class_name, `/teacher/class/${klass.class_id}`),
            ),
          },
        ]
      : []),
  ];

  return (
    <StaffShell
      role="teacher"
      roleLabel="Teacher"
      area="My sheets"
      areaHref="/teacher"
      areaIcon={BookOpenCheck}
      navLabel="Teaching sections"
      sections={sections}
      refusal="These pages are for class and subject teachers. Your account does not have access to them."
    >
      {children}
    </StaffShell>
  );
}
