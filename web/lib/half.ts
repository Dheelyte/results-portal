/**
 * Which of a term's two sheets to show (ARCHITECTURE.md §9, D92).
 *
 * §9 prints a card **per half term**, so every parent-facing path that names
 * a report also names a half: the page, the PDF download, and the API call
 * behind each. The value arrives in a query string, so it arrives from
 * anywhere, and both callers interpolate it into a URL — one into the API's
 * own. So it is narrowed to the enum here, once, rather than trusted twice.
 *
 * The second half is the default because it is the sheet the parent holds:
 * it carries the cumulative columns and the term's comments.
 */

export const HALVES = ["first_half", "second_half"] as const;

export type Half = (typeof HALVES)[number];

export const DEFAULT_HALF: Half = "second_half";

/** `value` if it names a half, otherwise the second half. */
export function halfFrom(value: string | string[] | null | undefined): Half {
  return HALVES.includes(value as Half) ? (value as Half) : DEFAULT_HALF;
}

/** The half as the toggle labels it. */
export function halfLabel(half: Half): string {
  return half === "first_half" ? "First half" : "Second half";
}
