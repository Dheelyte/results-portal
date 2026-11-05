"use client";

/**
 * The client session, for the staff route group only.
 *
 * Moved here from the root layout so the parent's server-rendered pages do
 * not carry it (§8.5's 150 KB, docs/DECISIONS.md D89). Every screen beneath
 * this one is interactive and signed in, and holds its access token in
 * memory as D41 describes.
 */

import type { ReactNode } from "react";

import { AuthProvider } from "@/lib/auth";

export default function StaffLayout({ children }: { children: ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}
