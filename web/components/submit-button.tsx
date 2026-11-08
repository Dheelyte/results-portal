"use client";

/**
 * A submit button that knows its own form is in flight.
 *
 * The only client component on §8.5's parent pages, and it is here for a
 * reason that matters on the connection §8.5 names: on 3G, tapping "I have
 * seen this result" and getting no acknowledgement for four seconds reads as
 * a tap that missed, so the parent taps again. `useFormStatus` is React's own
 * answer and needs no state of ours.
 *
 * It degrades the way the rest of those pages do. With JavaScript switched
 * off this is an ordinary `<button type="submit">` inside an ordinary
 * `<form>` that posts to a server action — exactly what was there before —
 * and the only thing lost is the spinner.
 */

import { useFormStatus } from "react-dom";
import type { ReactNode } from "react";

import { Button } from "@/components/ui";

/**
 * `icon` is a rendered **element**, not a component — `icon={<LogIn />}`,
 * never `icon={LogIn}`.
 *
 * That is not a style preference. Every caller of this is a server component,
 * and a component reference is a function: React cannot serialise one across
 * the boundary and the page 500s with "Functions cannot be passed directly to
 * Client Components". An element is plain data and crosses fine. The kit's own
 * `Button` takes the component, because both sides of that call are already on
 * the same side of the boundary.
 *
 * While the form is in flight the icon is replaced by `Button`'s own spinner.
 */
export function SubmitButton({
  children,
  variant = "primary",
  size = "md",
  icon,
  className,
}: {
  children: ReactNode;
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  icon?: ReactNode;
  className?: string;
}) {
  const { pending } = useFormStatus();
  return (
    <Button
      type="submit"
      variant={variant}
      size={size}
      loading={pending}
      className={className}
    >
      {pending ? null : icon}
      {children}
    </Button>
  );
}
