"use client";

/**
 * A parent asks for an account (docs/DECISIONS.md D126).
 *
 * Nothing is granted here. The account can't sign in until an admin
 * approves it, and the admin then links it to the parent's children. The
 * page always ends on the same message, whether or not an account was
 * created, so it can't be used to find out which phone numbers belong to
 * parents at the school.
 */

import { CheckCircle2, UserPlus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button, Field, Input, Notice } from "@/components/ui";
import { register } from "@/lib/api/client";
import { useAction } from "@/lib/use-async";

export default function RegisterPage() {
  const [form, setForm] = useState({ full_name: "", email: "", phone: "", password: "" });
  const [confirm, setConfirm] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const action = useAction();

  if (done) {
    return (
      <div className="flex flex-col gap-4 text-sm">
        <p className="flex items-start gap-2">
          <CheckCircle2 aria-hidden className="mt-0.5 size-5 shrink-0 text-[var(--success)]" />
          <span>{done}</span>
        </p>
        <p className="text-[var(--muted)]">
          If you already have an account, sign in with it instead. For anything else, contact
          the school office.
        </p>
        <Link href="/login" className="font-medium text-[var(--brand)] hover:underline">
          Back to sign in
        </Link>
      </div>
    );
  }

  const mismatch = confirm !== "" && confirm !== form.password;

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={async (event) => {
        event.preventDefault();
        if (mismatch) return;
        await action.run(async () => {
          const response = await register({
            full_name: form.full_name,
            email: form.email.trim() || null,
            phone: form.phone.trim() || null,
            password: form.password,
          });
          setDone(response.detail);
        });
      }}
    >
      <div>
        <h2 className="text-base font-semibold">Ask for a parent account</h2>
        <p className="text-sm text-[var(--muted)]">
          The school checks every request. Once yours is approved, you can sign in and see your
          children&apos;s results.
        </p>
      </div>

      <Field label="Your full name" required>
        <Input
          required
          autoComplete="name"
          value={form.full_name}
          onChange={(event) => setForm({ ...form, full_name: event.target.value })}
        />
      </Field>
      <Field label="Phone number" hint="Give a phone number, an email address, or both.">
        <Input
          inputMode="tel"
          autoComplete="tel"
          value={form.phone}
          onChange={(event) => setForm({ ...form, phone: event.target.value })}
        />
      </Field>
      <Field label="Email address">
        <Input
          type="email"
          autoCapitalize="none"
          autoComplete="email"
          value={form.email}
          onChange={(event) => setForm({ ...form, email: event.target.value })}
        />
      </Field>
      <Field label="Password" hint="At least 10 characters." required>
        <Input
          type="password"
          required
          minLength={10}
          autoComplete="new-password"
          value={form.password}
          onChange={(event) => setForm({ ...form, password: event.target.value })}
        />
      </Field>
      <Field label="Type the password again" required>
        <Input
          type="password"
          required
          autoComplete="new-password"
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
        />
      </Field>
      {mismatch ? <Notice>The two passwords don&apos;t match.</Notice> : null}
      <Notice>{action.error}</Notice>

      <Button
        type="submit"
        icon={UserPlus}
        loading={action.busy}
        disabled={mismatch || (!form.phone.trim() && !form.email.trim())}
        className="justify-center py-2.5"
      >
        Send request
      </Button>

      <p className="text-sm">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-[var(--brand)] hover:underline">
          Sign in
        </Link>
      </p>
    </form>
  );
}
