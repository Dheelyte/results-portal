/**
 * Any admin screen, while it arrives (§7).
 *
 * A `loading.tsx` is the App Router's own code-splitting boundary: the route
 * below it is fetched lazily and this is shown while its chunk and its data
 * are on the way. On a teacher's phone on patchy data (§8.1) that is the
 * difference between a dead tap and a screen that is visibly working.
 */

import { SkeletonPage } from "@/components/ui";

export default function Loading() {
  return <SkeletonPage label="Loading…" />;
}
