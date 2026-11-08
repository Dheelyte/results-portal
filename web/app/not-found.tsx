/**
 * A route, or a record, that is not there.
 *
 * Deliberately incurious: a parent who follows a link to a child that is not
 * theirs lands here, and so does anyone who mistypes a path. The two must
 * read identically, because the difference between them is exactly what R12
 * will not disclose.
 */

import { FileQuestion } from "lucide-react";

import { ButtonLink, Card, Crest } from "@/components/ui";

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center gap-5 px-5 py-12">
      <header className="flex flex-col items-center gap-3 text-center">
        <Crest size="lg" />
        <h1 className="text-xl font-semibold tracking-tight">Results Portal</h1>
      </header>

      <Card className="flex flex-col items-center gap-3 px-5 py-8 text-center">
        <span
          aria-hidden
          className="flex size-10 items-center justify-center rounded-full bg-[var(--surface-raised)] text-[var(--muted)]"
        >
          <FileQuestion className="size-5" />
        </span>
        <p className="text-sm font-medium">This page is not available.</p>
        <p className="text-sm text-[var(--muted)]">
          It may have moved, or you may not have access to it. If you were expecting a
          result, please contact the school office.
        </p>
        <ButtonLink href="/" variant="secondary" className="mt-1">
          Back to the portal
        </ButtonLink>
      </Card>
    </main>
  );
}
