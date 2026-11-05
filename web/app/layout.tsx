import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Self-Starters House Montessori School — Results Portal",
  description: "Results portal for Self-Starters House Montessori School.",
};

/**
 * The root layout, and deliberately **not** a client component.
 *
 * `AuthProvider` used to live here, which meant every page — including the
 * parent's — carried the client session machinery and the bundle that comes
 * with it. §8.5 puts the parent view under 150 KB of first load on a 3G
 * connection, so the provider moved down into the route groups that actually
 * need it: `(auth)` and `(staff)`. The parent's pages
 * (`app/page.tsx`, `(parent)/`) are server components with a server-side
 * session and no provider at all (docs/DECISIONS.md D89).
 */
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
