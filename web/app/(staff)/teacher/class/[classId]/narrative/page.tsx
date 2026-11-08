"use client";

/**
 * The class's written assessment, pupil by pupil (§8.2, §8.3).
 *
 * A list, not a form: the sixteen sections are written one pupil at a time at
 * `/teacher/narrative/[pupilId]`, and this says who is finished.
 */

import Link from "next/link";
import { ChevronRight } from "lucide-react";

import { Badge, EmptyState, Panel } from "@/components/ui";
import { pupilName } from "@/lib/format";

import { useClassContext } from "../context";

export default function ClassNarrativePage() {
  const { narrative } = useClassContext();
  const pupils = narrative.pupils ?? [];

  return (
    <Panel
      title="Written assessment"
      description={`${narrative.complete_pupils} of ${narrative.roll_size} pupils complete — every section written`}
      bare
    >
      {pupils.length === 0 ? (
        <div className="px-5 py-4">
          <EmptyState
            title="No pupils are enrolled in this class"
            description="Nobody is on this class's roll for the current session, so there is nothing to write."
          />
        </div>
      ) : (
        <ul className="flex flex-col divide-y divide-[var(--border)]">
          {pupils.map((pupil) => (
            <li key={pupil.pupil_id}>
              <Link
                href={`/teacher/narrative/${pupil.pupil_id}`}
                className="flex items-center gap-3 px-5 py-3 transition hover:bg-[var(--surface-raised)]"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">
                    {pupilName(pupil)}
                  </span>
                  <span className="block text-xs text-[var(--muted)]">
                    {pupil.admission_number}
                  </span>
                </span>
                <Badge tone={pupil.is_complete ? "good" : "neutral"}>
                  {pupil.written} of {pupil.total}
                </Badge>
                <ChevronRight aria-hidden className="size-4 shrink-0 text-[var(--muted)]" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
