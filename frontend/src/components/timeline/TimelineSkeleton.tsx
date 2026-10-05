"use client";

import { Skeleton } from "@/components/ui/skeleton";

export function TimelineSkeleton() {
  return (
    <div className="relative">
      {/* Vertical line */}
      <div className="absolute left-3 sm:left-5 top-0 bottom-0 w-px bg-line-strong" aria-hidden />

      <div className="space-y-6">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="relative flex gap-4 sm:gap-6">
            {/* Date marker skeleton */}
            <div className="relative z-10 flex flex-col items-center shrink-0 w-6 sm:w-10">
              <Skeleton className="h-[9px] w-[9px] rounded-full mt-5" />
              <div className="hidden sm:flex flex-col items-center gap-0.5 mt-2">
                <Skeleton className="h-3 w-4" />
                <Skeleton className="h-2.5 w-6" />
                <Skeleton className="h-2.5 w-7" />
              </div>
            </div>

            {/* Card skeleton */}
            <div className="flex-1 min-w-0 pb-2">
              <div className="border-b border-line py-4 space-y-2">
                <div className="flex items-center gap-3">
                  <Skeleton className="h-4 w-1/4" />
                  <Skeleton className="h-4 w-12" />
                </div>
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-5/6" />
                <Skeleton className="h-3 w-1/3 mt-3" />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
