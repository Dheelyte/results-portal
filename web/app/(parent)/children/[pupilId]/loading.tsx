/** One child's terms, while they are being fetched (§8.5). */

import { Loading, Skeleton } from "@/components/ui";

export default function LoadingChild() {
  return (
    <Loading label="Loading the terms…">
      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-2">
          <Skeleton className="h-3 w-36" />
          <Skeleton className="h-8 w-32 rounded-md" />
          <Skeleton className="h-7 w-48" />
          <Skeleton className="h-3.5 w-56" />
        </div>
        <div className="flex flex-col gap-3">
          {Array.from({ length: 3 }, (_, index) => (
            <div
              key={index}
              className="flex items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3.5"
            >
              <Skeleton className="size-9 rounded-lg" />
              <div className="flex flex-1 flex-col gap-2">
                <Skeleton className="h-3.5 w-28" />
                <Skeleton className="h-3 w-36" />
              </div>
              <Skeleton className="h-5 w-16 rounded-full" />
            </div>
          ))}
        </div>
      </div>
    </Loading>
  );
}
