"use client";

/**
 * The head teacher's shell (§8.4).
 *
 * A client component for the same reason the others are: the session lives in
 * an httpOnly cookie on `api.<domain>` (D13), which the Next.js server cannot
 * read. See docs/DECISIONS.md D41.
 *
 * The sidebar is the queue itself, longest-waiting first, because §8.4's
 * screen is worked through rather than browsed — the head teacher's next
 * action is nearly always the next class down.
 */

import { ArrowLeft, ClipboardCheck } from "lucide-react";
import type { ReactNode } from "react";

import { classItem, MY_TEACHING, REVIEW_ROOT, type NavSection } from "@/components/shell/nav";
import { StaffShell } from "@/components/shell/staff-shell";
import { useHeadApi } from "@/lib/api/use-head";
import { useAuth } from "@/lib/auth";
import { useResource } from "@/lib/use-async";

export default function ReviewLayout({ children }: { children: ReactNode }) {
  const api = useHeadApi();
  const { user } = useAuth();
  const queue = useResource((signal) => api!.queue(undefined, signal), [api], {
    enabled: Boolean(api),
  });

  const waiting = (queue.data ?? []).filter((entry) => entry.state === "submitted");

  const sections: NavSection[] = [
    { items: [REVIEW_ROOT] },
    user?.role === "admin"
      ? { items: [{ href: "/admin", label: "Back to setup", icon: ArrowLeft }] }
      : { heading: "Your teaching", items: [MY_TEACHING] },
    ...(waiting.length > 0
      ? [
          {
            heading: "Waiting for you",
            items: waiting.map((entry) =>
              classItem(entry.class_name, `/review/${entry.class_id}?term=${entry.term_id}`),
            ),
          },
        ]
      : []),
  ];

  return (
    <StaffShell
      role="head_teacher"
      alsoFor={["admin"]}
      roleLabel="Head teacher"
      area="Review"
      areaHref="/review"
      areaIcon={ClipboardCheck}
      navLabel="Review sections"
      sections={sections}
      refusal="These pages are for the head teacher. Your account does not have access to them."
    >
      {children}
    </StaffShell>
  );
}
