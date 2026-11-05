import Link from "next/link";
import { redirect } from "next/navigation";

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
 * It works with JavaScript switched off, and it contributes nothing to the
 * client bundle. A parent already signed in is sent straight to their
 * children.
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
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 px-6 py-16">
      <header className="flex flex-col gap-2">
        <p className="text-sm uppercase tracking-widest text-[var(--muted)]">
          Self-Starters House Montessori School
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">Results Portal</h1>
        <p className="text-sm text-[var(--muted)]">
          Sign in to see your child&rsquo;s result.
        </p>
      </header>

      {error ? (
        <p role="alert" className="rounded-md border border-[var(--danger)] px-3 py-2 text-sm text-[var(--danger)]">
          {error}
        </p>
      ) : null}

      <form action={submit} className="flex flex-col gap-4">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Email address or phone number</span>
          <input
            name="identifier"
            required
            autoComplete="username"
            autoCapitalize="none"
            className="rounded-md border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-base"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Password</span>
          <input
            name="password"
            type="password"
            required
            autoComplete="current-password"
            className="rounded-md border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-base"
          />
        </label>

        <button
          type="submit"
          className="rounded-md bg-[var(--accent)] px-4 py-2.5 text-sm font-medium text-white"
        >
          Sign in
        </button>
      </form>

      <footer className="flex flex-col gap-1 text-sm text-[var(--muted)]">
        <Link href="/login" className="hover:underline">
          Staff sign in
        </Link>
        <span>Built by HSD Technologies.</span>
      </footer>
    </main>
  );
}
