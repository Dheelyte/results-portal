"use client";

/**
 * The admin shell (ARCHITECTURE.md §3, §8).
 *
 * A client component, and not by preference: the session lives in an
 * httpOnly cookie on `api.<domain>` (D13), which the Next.js server cannot
 * read, so a signed-in page cannot be server-rendered as things stand. §8.5's
 * parent view solved that a different way, for itself only — see
 * docs/DECISIONS.md D41 and D89.
 *
 * The frame, the nav and the session check are all `StaffShell`; what is left
 * here is which links and which role.
 */

import { Settings } from "lucide-react";
import type { ReactNode } from "react";

import { ADMIN_NAV } from "@/components/shell/nav";
import { StaffShell } from "@/components/shell/staff-shell";

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <StaffShell
      role="admin"
      roleLabel="Administrator"
      area="Setup"
      areaHref="/admin"
      areaIcon={Settings}
      // Kept word for word: it is the nav's accessible name and the handle
      // the E2E journey navigates by.
      navLabel="Setup sections"
      sections={ADMIN_NAV}
      refusal="These pages are for the school administrator. Your account does not have access to them."
    >
      {children}
    </StaffShell>
  );
}
