/**
  * Where a redirect after a session renewal is allowed to land
 * (docs/DECISIONS.md D91).
 *
 * `/api/session?next=…` exists so a parent lands back on the page they
 * asked for. That parameter arrives in a URL, so it arrives from anywhere —
 * and a redirect the attacker controls, on a path the parent reached by
 * signing in, is exactly what makes a phishing link look legitimate.
 *
 * So this is an allowlist by shape: a path on this origin, and nothing else.
 * Pure, with no Next.js import, so it can be tested on its own.
 */

/** Where a parent goes when `next` says nothing usable. */
export const DEFAULT_DESTINATION = "/children";

/**
 * `next` reduced to a same-origin path, or `DEFAULT_DESTINATION`.
 *
 * Refused:
 *
 * - anything not starting with `/` — `https://evil.example`, `javascript:…`,
 *   a bare `evil.example/x` that a browser would resolve as a host;
 * - `//host` and `/\host`, which are **protocol-relative**: the browser
 *   reads the authority that follows, so they leave the site while looking
 *   like a path. Both slash shapes, because browsers normalise `\` to `/`
 *   in authority position;
 * - a control character, which could split the `Location` header.
 */
export function safeNext(next: string | null | undefined): string {
  if (!next) return DEFAULT_DESTINATION;
  if (!next.startsWith("/")) return DEFAULT_DESTINATION;
  if (/[\u0000-\u001f\u007f]/.test(next)) return DEFAULT_DESTINATION;

  const second = next[1];
  if (second === "/" || second === "\\") return DEFAULT_DESTINATION;

  return next;
}
