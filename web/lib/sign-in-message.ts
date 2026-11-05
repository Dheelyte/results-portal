/**
 * The sign-in page's own wording for a failure (D94).
 *
 * The page reports failure through a query parameter, which is
 * attacker-supplied, so it carries a code and this maps it. An unrecognised
 * code reads as the generic failure rather than as itself — that is the
 * point: nothing an attacker puts in the URL reaches the page as words.
 */

export const GENERIC_SIGN_IN_FAILURE =
  "Sorry, we could not sign you in just now. Please try again.";

const MESSAGES = new Map<string, string>([
  ["credentials", "Those details were not recognised. Please check and try again."],
  [
    "locked",
    "This account is temporarily locked after too many failed attempts. " +
      "Please try again shortly, or contact the school.",
  ],
  ["unavailable", GENERIC_SIGN_IN_FAILURE],
]);

/** The message for `code`, or the generic failure. */
export function signInMessage(code: string | string[] | null | undefined): string | null {
  if (code === undefined || code === null || code === "") return null;
  if (typeof code !== "string") return GENERIC_SIGN_IN_FAILURE;
  // A `Map`, not an object: `?error=__proto__` must not reach a prototype.
  return MESSAGES.get(code) ?? GENERIC_SIGN_IN_FAILURE;
}
