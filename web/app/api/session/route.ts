/**
 * The one place the parent's session is renewed (ARCHITECTURE.md §8.5,
 * docs/DECISIONS.md D89).
 *
 * A route handler, because Next.js forbids a server component from writing
 * a cookie — and the API rotates its refresh token on every use (§5.1), so
 * a renewal that could not store the rotated value would sign the parent out
 * on their next click and trip reuse detection as it went.
 *
 * Pages read a cached access token; when it has expired they redirect here
 * once, and this sends them back where they were.
 */

import { safeNext } from "@/lib/server/next-path";
import { clearSession, refreshSession } from "@/lib/server/session";

/**
 * A **relative** redirect, which RFC 9110 §10.2.2 allows and every browser
 * resolves against the address bar.
 *
 * `NextResponse.redirect` needs an absolute URL, and behind the reverse
 * proxy the only absolute URL available here is the container's own
 * `http://0.0.0.0:3000/…` — a dead host from the parent's phone. Staying
 * relative sidesteps the whole question of which hostname the request
 * arrived under, and cannot be talked into pointing off-site.
 */
function redirectTo(path: string): Response {
  return new Response(null, {
    status: 303,
    headers: { Location: path, "Cache-Control": "no-store" },
  });
}

export async function GET(request: Request) {
  // Only ever back into this app (`safeNext`'s own doc comment says why).
  const destination = safeNext(new URL(request.url).searchParams.get("next"));

  const session = await refreshSession();
  if (!session) {
    await clearSession();
    return redirectTo("/");
  }

  return redirectTo(destination);
}
