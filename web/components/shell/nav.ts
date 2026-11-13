/**
 * What goes in the sidebar, for each role.
 *
 * The admin's order is the order the work has to be done in — a class cannot
 * have a teacher before the class exists, and nothing can be configured
 * before there is a session to configure it in. That was true of the old
 * horizontal tab strip and it is the reason the sidebar is not alphabetical.
 *
 * Data, not components, so the shell stays one implementation and a role is
 * a list rather than a branch.
 */

import {
  BookOpen,
  BookOpenCheck,
  CalendarDays,
  ClipboardCheck,
  ClipboardList,
  GraduationCap,
  LayoutDashboard,
  Layers,
  ScrollText,
  Send,
  Users,
  UsersRound,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Match the pathname exactly rather than by prefix — for a section root. */
  exact?: boolean;
}

export interface NavSection {
  heading?: string;
  items: NavItem[];
}

/** For a head teacher or admin who has been assigned a class (D123). */
export const MY_TEACHING: NavItem = {
  href: "/teacher",
  label: "My teaching",
  icon: BookOpenCheck,
};

export const ADMIN_NAV: NavSection[] = [
  {
    items: [{ href: "/admin", label: "Setup", icon: LayoutDashboard, exact: true }],
  },
  {
    heading: "The school year",
    items: [
      { href: "/admin/calendar", label: "Session & terms", icon: CalendarDays },
      { href: "/admin/assessment", label: "Grading & narrative", icon: ClipboardList },
    ],
  },
  {
    heading: "The school",
    items: [
      { href: "/admin/subjects", label: "Subjects", icon: BookOpen },
      { href: "/admin/classes", label: "Classes", icon: Layers },
      { href: "/admin/pupils", label: "Pupils", icon: GraduationCap },
      { href: "/admin/accounts", label: "Accounts", icon: Users },
    ],
  },
  {
    heading: "Results",
    items: [
      { href: "/admin/publish", label: "Publish", icon: Send },
      // Only the classes a head teacher teaches in reach an admin (D123).
      { href: "/review", label: "Reviews", icon: ClipboardCheck },
      { href: "/admin/audit", label: "Audit log", icon: ScrollText },
    ],
  },
  { heading: "Your teaching", items: [MY_TEACHING] },
];

export const TEACHER_ROOT: NavItem = {
  href: "/teacher",
  label: "My sheets",
  icon: LayoutDashboard,
  exact: true,
};

export const REVIEW_ROOT: NavItem = {
  href: "/review",
  label: "Review queue",
  icon: ClipboardList,
  exact: true,
};

/** A class, for the sidebar of a teacher or a head teacher. */
export function classItem(className: string, href: string): NavItem {
  return { href, label: className, icon: UsersRound };
}
