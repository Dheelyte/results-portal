import { LogIn } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";

import { SubmitButton } from "@/components/submit-button";
import { Card, Crest, Field, Input, Notice } from "@/components/ui";
import { signInMessage } from "@/lib/sign-in-message";
import { currentSession, signIn, signOut } from "@/lib/server/session";

/**
 * The front door, and the parent's sign-in (ARCHITECTURE.md §8.5).
 *
 * §8.5: "The lightest page in the system… Login → children as cards →
 * published terms → the report card. Assume a 3G connection on a low-end
 * Android device."
 *
 * So this is a server component with a form that posts to a server action.
 * It works with JavaScript switched off, and the only client code on it is
 * the submit button's pending state. A parent already signed in is sent
 * straight to their children.
 *
 * Staff sign in at `/login`, which is a client component for the reason D41
 * records: those screens are interactive and their session lives in memory.
 */
export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ error?: string | string[] }>;
}) {
  const session = await currentSession();
  if (session?.user.role === "parent") redirect("/children");

  // A code, mapped here — never a message carried in the URL (D94).
  const error = signInMessage((await searchParams).error);

  async function submit(form: FormData) {
    "use server";
    const identifier = String(form.get("identifier") ?? "").trim();
    const password = String(form.get("password") ?? "");

    const result = await signIn(identifier, password);
    if (!result.ok) {
      redirect(`/?error=${result.reason}`);
    }
    if (result.user.role !== "parent") {
      // Staff have their own screens and their own session. Keeping the
      // refresh token this page just stored would leave a second live token
      // family in a cookie those screens know nothing about and never
      // revoke, so it goes — along with the family, through the API.
      await signOut();
      redirect("/login");
    }
    redirect("/children");
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center gap-5 px-5 py-12">
      <header className="flex flex-col items-center gap-3 text-center">
        <Crest size="lg" />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Results Portal</h1>
          <p className="text-sm text-[var(--muted)]">
            Self-Starters House Montessori School
          </p>
        </div>
      </header>

      <Card className="flex flex-col gap-4 px-5 py-6">
        <p className="text-sm text-[var(--muted)]">
          Sign in to see your child&rsquo;s result.
        </p>

        {error ? <Notice tone="error">{error}</Notice> : null}

        <form action={submit} className="flex flex-col gap-4">
          <Field label="Email address or phone number" required>
            <Input
              name="identifier"
              required
              autoComplete="username"
              autoCapitalize="none"
              className="py-2.5 text-base"
            />
          </Field>

          <Field label="Password" required>
            <Input
              name="password"
              type="password"
              required
              autoComplete="current-password"
              className="py-2.5 text-base"
            />
          </Field>

          <SubmitButton
            icon={<LogIn aria-hidden className="size-4 shrink-0" />}
            className="justify-center py-2.5"
          >
            Sign in
          </SubmitButton>
        </form>
      </Card>

      <footer className="flex flex-col items-center gap-1 text-sm text-[var(--muted)]">
        <Link href="/login" className="text-[var(--brand)] hover:underline">
          Staff sign in
        </Link>
        <span className="text-xs">Built by HSD Technologies.</span>
      </footer>
    </main>
  );
}
