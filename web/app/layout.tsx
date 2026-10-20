import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Self-Starters House Montessori School — Results Portal",
  description: "Results portal for Self-Starters House Montessori School.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
