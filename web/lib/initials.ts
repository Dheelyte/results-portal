/**
 * The initials an avatar shows, and the tint it shows them in.
 *
 * In `lib/` rather than beside the component because this is the kind of
 * string handling that has edge cases — one-word names, a trailing space, a
 * hyphen, a name that is entirely whitespace — and `npm test` only runs
 * `lib/**\/*.test.ts`. A component is the wrong place for a rule.
 */

/** The first letter of the first word and of the last, upper-cased. */
export function initialsOf(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  const first = words[0]?.[0] ?? "";
  const last = words.length > 1 ? (words[words.length - 1]?.[0] ?? "") : "";
  return (first + last).toUpperCase();
}

/**
 * A stable hue per name, so the same person is the same colour on every
 * screen.
 *
 * Not security-sensitive and not stored: a sum of code points is enough to
 * keep two colleagues apart, and being stable is the whole requirement.
 */
export function hueOf(name: string): number {
  let total = 0;
  for (const character of name) total += character.codePointAt(0) ?? 0;
  return total % 360;
}
