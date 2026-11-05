"use client";

/**
 * Replace a temporary password (ARCHITECTURE.md §5.1).
 *
 * The gate that makes `must_change_password` mean something: until this is
 * done the API refuses every other endpoint with a 409, so this screen is the
 * only place a new account can go.
 */

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button, Field, Input, Notice, Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { useAction } from "@/lib/use-async";

/** Mirrors `services/auth.MIN_PASSWORD_LENGTH`, which is what enforces it. */
const MIN_LENGTH = 10;

export default function ChangePasswordPage() {
  const router = useRouter();
  const { user, loading, replacePassword } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [mismatch, setMismatch] = useState<string | null>(null);
  const action = useAction();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading) return <Spinner />;

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={async (event) => {
        event.preventDefault();
        setMismatch(null);
        if (next !== confirmation) {
          setMismatch("The two new passwords do not match.");
          return;
        }
        const changed = await action.run(() => replacePassword(current, next));
        if (changed) {
          // Every session is revoked on a password change (§5.1), so signing
          // in again is the expected next step rather than a failure.
          router.replace("/login");
        }
      }}
    >
      <p className="text-sm text-[var(--muted)]">
        {user?.must_change_password
          ? "Choose your own password before you continue. The one you were given works only once."
          : "Choose a new password. You will be signed out of every device."}
      </p>

      <Field label="Current password" required>
        <Input
          type="password"
          autoComplete="current-password"
          required
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
        />
      </Field>

      <Field label="New password" hint={`At least ${MIN_LENGTH} characters.`} required>
        <Input
          type="password"
          autoComplete="new-password"
          minLength={MIN_LENGTH}
          required
          value={next}
          onChange={(event) => setNext(event.target.value)}
        />
      </Field>

      <Field label="New password again" required>
        <Input
          type="password"
          autoComplete="new-password"
          minLength={MIN_LENGTH}
          required
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
        />
      </Field>

      <Notice>{mismatch ?? action.error}</Notice>

      <Button type="submit" disabled={action.busy}>
        {action.busy ? "Saving…" : "Change password"}
      </Button>
    </form>
  );
}
