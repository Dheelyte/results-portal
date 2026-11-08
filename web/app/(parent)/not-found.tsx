/**
 * A child, or a term, that is not there (§8.5, R12).
 *
 * **Why this exists when `app/not-found.tsx` already does.** The root one
 * handles URLs that match no route, and it does that under either bundler.
 * A `notFound()` thrown *inside* a route group is a different thing: Next
 * looks for the nearest `not-found.tsx` boundary, and whether it walks up to
 * the root one turned out to depend on the bundler — webpack used it,
 * Turbopack rendered Next's own built-in 404 instead
 * (docs/DECISIONS.md D112). Rather than rely on that, the group has its own.
 *
 * It is also the better page. A parent who follows a stale link keeps their
 * header and is one tap from their children, instead of being dropped onto a
 * bare page.
 *
 * Deliberately incurious, like `parents.py`'s R12 message: a pupil id
 * belonging to somebody else's child reads exactly like one belonging to
 * nobody. Nothing here distinguishes "no such child", "not your child",
 * "not published yet" or "held back".
 */

import { SearchX } from "lucide-react";

import { ButtonLink, Card, PageHeader } from "@/components/ui";

export default function ParentNotFound() {
  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Your children", href: "/children" }, { label: "Not available" }]}
        title="Not available"
      />

      <Card className="flex flex-col items-center gap-3 px-6 py-10 text-center">
        <span
          aria-hidden
          className="flex size-10 items-center justify-center rounded-full bg-[var(--surface-raised)] text-[var(--muted)]"
        >
          <SearchX className="size-5" />
        </span>
        <p className="text-sm font-medium">This page is not available.</p>
        <p className="max-w-sm text-sm text-[var(--muted)]">
          The link may be out of date. If you were expecting a result, please contact the
          school office.
        </p>
        <ButtonLink href="/children" variant="primary" className="mt-1">
          Your children
        </ButtonLink>
      </Card>
    </>
  );
}
