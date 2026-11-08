/**
 * The report card, while it is being fetched (§8.5, §9).
 *
 * Laid out as the card is — header, the two record blocks, the subject table
 * — because this is the page a parent opens on a slow connection and the
 * shape arriving before the figures is what tells them it is the right one.
 */

import { Loading, Skeleton } from "@/components/ui";

export default function LoadingReport() {
  return (
    <Loading label="Loading the report card…">
      <div className="flex flex-col gap-6">
        <div className="flex items-center justify-between gap-3">
          <Skeleton className="h-8 w-28 rounded-md" />
          <Skeleton className="h-8 w-44 rounded-md" />
        </div>

        <div className="flex flex-col items-center gap-2">
          <Skeleton className="h-3 w-56" />
          <Skeleton className="h-5 w-64" />
          <Skeleton className="h-3.5 w-40" />
        </div>

        <div className="grid grid-cols-2 gap-x-6 gap-y-3">
          {Array.from({ length: 8 }, (_, index) => (
            <div key={index} className="flex flex-col gap-1.5">
              <Skeleton className="h-2.5 w-24" />
              <Skeleton className="h-4 w-full" />
            </div>
          ))}
        </div>

        <div className="flex flex-col gap-2">
          <Skeleton className="h-3.5 w-40" />
          {Array.from({ length: 8 }, (_, index) => (
            <Skeleton key={index} className="h-6 w-full" />
          ))}
        </div>
      </div>
    </Loading>
  );
}
