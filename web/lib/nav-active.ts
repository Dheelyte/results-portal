/**
 * Which sidebar link is the page you are on (§8.0).
 *
 * Two things make this more than a string comparison, and both have bitten:
 *
 * - A link may carry a **query string** — the review queue's links do,
 *   because a class is reviewed for a particular term — and
 *   `usePathname()` never does. Comparing the two whole would mean no queue
 *   item ever highlighted.
 * - A section root must match **exactly** or it is active on every page
 *   beneath it: `/admin` would be highlighted while the admin is on
 *   `/admin/pupils`, and two links would claim to be the current page.
 */

export function isActive(pathname: string, href: string, exact?: boolean): boolean {
  const path = href.split("?")[0] ?? href;
  if (exact) return pathname === path;
  return pathname === path || pathname.startsWith(`${path}/`);
}
