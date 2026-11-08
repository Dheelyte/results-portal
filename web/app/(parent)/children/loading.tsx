/**
 * The children list, while it is being fetched (§8.5).
 *
 * A `loading.tsx` is how the App Router streams a page: the shell and this
 * file are sent immediately and the page replaces them when its data lands.
 * On §8.5's 3G connection that is the difference between a blank white
 * screen and a screen that is visibly working.
 */

import { Loading, Skeleton } from "@/components/ui";

export default function LoadingChildren() {
  return (
    <Loading label="Loading your children…">
      <div className="flex flex-col gap-6">
        <Skeleton className="h-7 w-44" />
        <div className="grid gap-3 sm:grid-cols-2">
          {Array.from({ length: 2 }, (_, index) => (
            <div
              key={index}
              className="flex items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4"
            >
              <Skeleton className="size-12 rounded-full" />
              <div className="flex flex-1 flex-col gap-2">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-3 w-40" />
                <Skeleton className="h-3 w-20" />
              </div>
            </div>
          ))}
        </div>
      </div>
    </Loading>
  );
}
