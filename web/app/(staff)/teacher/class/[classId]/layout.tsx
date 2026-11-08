"use client";

/**
 * One class, and the class teacher's own work on it (§8.3).
 *
 * §8.3 describes one page per class: every subject with its state and owner,
 * then the class teacher's own work — narrative, attendance, growth,
 * comments — with **Send to head teacher** disabled until R10 passes and the
 * outstanding items listed beneath it.
 *
 * Those five views used to be tabs driven by `?tab=`, switched by
 * `router.replace`. They are **routes** now (docs/DECISIONS.md D104), which
 * costs nothing and buys three things: each one can be linked to, each one
 * code-splits and streams its own skeleton, and the back button walks back
 * through them in the order a teacher visited rather than leaving the class
 * entirely.
 *
 * The term and the class's own summary are fetched once, here, and handed
 * down through context — otherwise every one of the five would re-fetch
 * them on every switch.
 */

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { Notice, PageHeader, Skeleton, SkeletonPanel } from "@/components/ui";
import { ClassContext } from "./context";
import { useTeacherApi } from "@/lib/api/use-teacher";
import { TERM_LABELS } from "@/lib/format";
import { useResource } from "@/lib/use-async";

const TABS = [
  { segment: "", label: "Progress" },
  { segment: "narrative", label: "Narrative" },
  { segment: "attendance", label: "Attendance" },
  { segment: "growth", label: "Height & weight" },
  { segment: "comments", label: "Class teacher's comment" },
] as const;

export default function ClassLayout({ children }: { children: ReactNode }) {
  const api = useTeacherApi();
  const { classId } = useParams<{ classId: string }>();
  const pathname = usePathname();

  const workload = useResource((signal) => api!.workload(undefined, signal), [api], {
    enabled: Boolean(api),
  });
  const termId = workload.data?.term.id ?? null;

  const narrative = useResource(
    (signal) => api!.classNarrative(classId, termId!, signal),
    [api, classId, termId],
    { enabled: Boolean(api) && Boolean(termId) },
  );

  const base = `/teacher/class/${classId}`;
  const back = { href: "/teacher", label: "My sheets" };

  if (workload.loading || (termId && narrative.loading)) {
    return (
      <>
        <PageHeader breadcrumbs={[{ label: "My sheets", href: "/teacher" }]} back={back} title="Class" />
        <div className="flex flex-wrap gap-2" aria-hidden>
          {TABS.map((tab) => (
            <Skeleton key={tab.segment} className="h-8 w-28 rounded-lg" />
          ))}
        </div>
        <SkeletonPanel rows={8} label="Loading the class…" />
      </>
    );
  }
  if (workload.error) return <Notice>{workload.error}</Notice>;
  if (narrative.error) return <Notice>{narrative.error}</Notice>;
  if (!narrative.data || !api || !termId) return null;

  const term = workload.data?.term;
  const data = narrative.data;

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "My sheets", href: "/teacher" }, { label: data.class_name }]}
        back={back}
        title={data.class_name}
        description={
          `${
            term ? `${TERM_LABELS[term.number] ?? term.number}, ${term.academic_session_name} · ` : ""
          }${data.roll_size} pupil${data.roll_size === 1 ? "" : "s"}`
        }
      />

      <nav aria-label="Class records" className="-mb-2 flex flex-wrap gap-1 text-sm">
        {TABS.map((tab) => {
          const href = tab.segment ? `${base}/${tab.segment}` : base;
          const active = pathname === href;
          return (
            <Link
              key={tab.segment}
              href={href}
              aria-current={active ? "page" : undefined}
              className={`rounded-lg px-3 py-1.5 transition ${
                active
                  ? "bg-[var(--brand-soft)] font-semibold text-[var(--brand)]"
                  : "text-[var(--muted)] hover:bg-[var(--surface-raised)] hover:text-[var(--foreground)]"
              }`}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>

      <ClassContext.Provider
        value={{ api, classId, termId, narrative: data, reload: narrative.reload }}
      >
        {children}
      </ClassContext.Provider>
    </>
  );
}
