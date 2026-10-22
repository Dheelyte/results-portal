"use client";

/**
 * Sign in (ARCHITECTURE.md §5.1, §7).
 *
 * One field for the identifier, because A7 lets a parent sign in with either
 * an email address or a phone number against the same password — many
 * parents' email addresses are inactive. Asking them which kind it is would
 * be asking them to know something about our schema.
 */

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button, Field, Input, Notice } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { useAction } from "@/lib/use-async";

export default function LoginPage() {
  const router = useRouter();
  const { signIn, user, loading } = useAuth();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const action = useAction();

  // A session restored from the refresh cookie means there is nothing to do
  // here.
  useEffect(() => {
    if (loading || !user) return;
    router.replace(user.must_change_password ? "/change-password" : destinationFor(user.role));
  }, [loading, user, router]);

  // The form renders immediately rather than waiting for the session check.
  // That check only matters for the rare already-signed-in visitor, and §8.5's
  // 3G assumption applies here too: a spinner that blocks the first paint
  // until JavaScript arrives is the wrong trade on a login screen.
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={async (event) => {
        event.preventDefault();
        const signedIn = await action.run(async () => {
          const account = await signIn(identifier.trim(), password);
          router.replace(
            account.must_change_password ? "/change-password" : destinationFor(account.role),
          );
        });
        if (!signedIn) setPassword("");
      }}
    >
      <Field label="Email address or phone number" required>
        <Input
          name="identifier"
          autoComplete="username"
          autoCapitalize="none"
          inputMode="email"
          required
          value={identifier}
          onChange={(event) => setIdentifier(event.target.value)}
        />
      </Field>

      <Field label="Password" required>
        <Input
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </Field>

      <Notice>{action.error}</Notice>

      <Button type="submit" disabled={action.busy || loading}>
        {action.busy ? "Signing in…" : "Sign in"}
      </Button>

      <p className="text-xs text-[var(--muted)]">
        Accounts are created by the school. If you cannot sign in, or you have forgotten your
        password, contact the school office.
      </p>
    </form>
  );
}

/** Where each role's work lives. Only the admin surface exists so far. */
function destinationFor(role: string): string {
  return role === "admin" ? "/admin" : "/";
}
