/**
 * One child's report card (ARCHITECTURE.md §8.5, §9, R12).
 *
 * The page §8.5 is strictest about: server-rendered, no client-side fetching
 * for the report itself, under 150 KB of first load, on a 3G connection and
 * a low-end Android device.
 *
 * So this is a server component that fetches once, over the Docker network,
 * and sends HTML. The two actions — download and acknowledge — are a link
 * and a form; neither needs JavaScript. The card's structure is §9's, in the
 * order the paper prints it, because a parent comparing the screen with the
 * card in their hand should find them the same document.
 */

import { Download, Eye } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";

import { SubmitButton } from "@/components/submit-button";
import { Badge, Card, PageHeader } from "@/components/ui";
import { HALVES, halfFrom, halfLabel } from "@/lib/half";
import {
  apiGet,
  apiPost,
  currentSession,
  refreshSession,
  sessionState,
} from "@/lib/server/session";

interface Line {
  subject_name: string;
  group_name?: string | null;
  group_size: number;
  in_group: boolean;
  values: Record<string, string | null>;
  cumulative: Record<string, string | null>;
  grade?: string | null;
}

interface Card {
  title: string;
  subtitle: string;
  school_name: string;
  date?: string | null;
  pupil_name: string;
  admission_number: string;
  overall_percentage?: string | null;
  position_text?: string | null;
  class_name: string;
  session_name: string;
  no_in_class?: number | null;
  house_name?: string | null;
  times_school_opened?: number | null;
  times_present?: number | null;
  times_absent?: number | null;
  times_late?: number | null;
  height_start_m?: string | null;
  height_end_m?: string | null;
  weight_start_kg?: string | null;
  weight_end_kg?: string | null;
  columns: [string, string][];
  cumulative_columns: string[];
  maxima: Record<string, string | null>;
  lines: Line[];
  grand_total: Record<string, string | null>;
  key: [string, string, string][];
  narrative_groups: [string, string | null, [string, string, string | null][]][];
  class_teacher_comment?: string | null;
  head_teacher_remark?: string | null;
  promotion_decision?: string | null;
  return_date?: string | null;
}

interface Report {
  term_label: string;
  available: boolean;
  acknowledged_at?: string | null;
  message?: string | null;
  card?: Card | null;
}

/** A figure as the card prints it: 40, not 40.00; nothing for nothing. */
function show(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  const asNumber = Number(value);
  return Number.isFinite(asNumber) ? String(asNumber) : String(value);
}

export default async function ReportPage({
  params,
  searchParams,
}: {
  params: Promise<{ pupilId: string; termId: string }>;
  searchParams: Promise<{ half?: string | string[] }>;
}) {
  const { pupilId, termId } = await params;
  const half = halfFrom((await searchParams).half);
  const state = await sessionState();
  const here = `/children/${pupilId}/${termId}?half=${half}`;
  if (state.kind === "stale") redirect(`/api/session?next=${encodeURIComponent(here)}`);
  if (state.kind === "signed-out") redirect("/");
  const session = state.session;

  const report = await apiGet<Report>(
    session,
    `/my/children/${pupilId}/reports/${termId}?half=${half}`,
  );

  if (!report) {
    // Not this parent's child, or no such term. R12's wording either way:
    // nothing here confirms whether a report exists.
    return (
      <Unavailable
        pupilId={pupilId}
        message="Result not yet available. Please contact the school."
      />
    );
  }

  if (!report.available || !report.card) {
    return <Unavailable pupilId={pupilId} message={report.message ?? ""} />;
  }

  async function acknowledge() {
    "use server";
    // A server action may write cookies, so it can renew the session itself
    // rather than throwing away the tap (D89).
    const live = (await currentSession()) ?? (await refreshSession());
    if (!live) redirect("/");
    await apiPost(live, `/my/children/${pupilId}/reports/${termId}/acknowledge`);
    const { revalidatePath } = await import("next/cache");
    revalidatePath(`/children/${pupilId}/${termId}`);
  }

  const card = report.card;

  return (
    <>
      <PageHeader
        breadcrumbs={[
          { label: "Your children", href: "/children" },
          { label: card.pupil_name, href: `/children/${pupilId}` },
          { label: report.term_label },
        ]}
        back={{ href: `/children/${pupilId}`, label: card.pupil_name }}
        title={report.term_label}
        description={`${card.pupil_name} · ${card.class_name}`}
        badge={
          report.acknowledged_at ? (
            <Badge tone="good" icon={Eye}>
              Seen
            </Badge>
          ) : null
        }
        actions={
          <nav
            aria-label="Which half of the term"
            className="flex overflow-hidden rounded-lg border border-[var(--border)] text-xs"
          >
            {HALVES.map((option) => (
              <Link
                key={option}
                href={`/children/${pupilId}/${termId}?half=${option}`}
                aria-current={option === half ? "page" : undefined}
                className={
                  option === half
                    ? "bg-[var(--brand)] px-3 py-2 font-medium text-[var(--brand-contrast)]"
                    : "px-3 py-2 text-[var(--muted)] hover:bg-[var(--surface-raised)]"
                }
              >
                {halfLabel(option)}
              </Link>
            ))}
          </nav>
        }
      />

      <header className="text-center">
        <p className="text-sm">{card.school_name}</p>
        <h1 className="text-base font-bold">{card.title}</h1>
        <p className="text-sm font-semibold">{card.subtitle}</p>
      </header>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
        <Entry label="Name of Pupil" value={card.pupil_name} />
        <Entry label="Date" value={card.date} />
        <Entry label="Overall Percentage" value={show(card.overall_percentage)} />
        <Entry label="Position (In grades)" value={card.position_text} />
        <Entry label="Class" value={card.class_name} />
        <Entry label="Year/Session" value={card.session_name} />
        <Entry label="No. in Class" value={card.no_in_class} />
        <Entry label="House" value={card.house_name} />
      </dl>

      <section>
        <h2 className="text-sm font-bold">1. Attendance Record</h2>
        <dl className="grid grid-cols-2 gap-x-6 text-sm sm:grid-cols-4">
          <Entry label="Times School Opened" value={card.times_school_opened} />
          <Entry label="Times Present" value={card.times_present} />
          <Entry label="Times Absent" value={card.times_absent} />
          <Entry label="Times Collected Late" value={card.times_late} />
        </dl>
      </section>

      <section>
        <h2 className="text-sm font-bold">2. Health and Physical Growth</h2>
        <dl className="grid grid-cols-2 gap-x-6 text-sm sm:grid-cols-4">
          <Entry label="Height, start" value={suffix(card.height_start_m, "m")} />
          <Entry label="Height, end" value={suffix(card.height_end_m, "m")} />
          <Entry label="Weight, start" value={suffix(card.weight_start_kg, "kg")} />
          <Entry label="Weight, end" value={suffix(card.weight_end_kg, "kg")} />
        </dl>
      </section>

      <section className="overflow-x-auto">
        <h2 className="text-sm font-bold">3. Cognitive Ability</h2>
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr>
              <th className="border border-[var(--border)] p-1 text-left">Subject</th>
              {card.columns.map(([key, label]) => (
                <th key={key} className="border border-[var(--border)] p-1">
                  {label}
                </th>
              ))}
              {card.cumulative_columns.map((label) => (
                <th key={label} className="border border-[var(--border)] p-1">
                  {label}
                </th>
              ))}
              <th className="border border-[var(--border)] p-1">Grade</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th className="border border-[var(--border)] p-1 text-left font-semibold">
                Marks Obtainable
              </th>
              {card.columns.map(([key]) => (
                <td key={key} className="border border-[var(--border)] p-1 text-center">
                  {show(card.maxima[key])}
                </td>
              ))}
              {card.cumulative_columns.map((label) => (
                <td key={label} className="border border-[var(--border)] p-1" />
              ))}
              <td className="border border-[var(--border)] p-1" />
            </tr>

            {card.lines.map((line) => (
              <tr key={line.subject_name}>
                <th className="border border-[var(--border)] p-1 text-left font-normal">
                  {/* §9: English spans its sub-rows. On a phone a spanning
                      cell is unreadable, so the heading prefixes the row. */}
                  {line.in_group && line.group_name ? (
                    <span className="block text-[0.65rem] font-semibold uppercase text-[var(--muted)]">
                      {line.group_name}
                    </span>
                  ) : null}
                  {line.subject_name}
                </th>
                {card.columns.map(([key]) => (
                  <td key={key} className="border border-[var(--border)] p-1 text-center tabular-nums">
                    {show(line.values[key])}
                  </td>
                ))}
                {card.cumulative_columns.map((label) => (
                  <td key={label} className="border border-[var(--border)] p-1 text-center tabular-nums">
                    {show(line.cumulative[label])}
                  </td>
                ))}
                <td className="border border-[var(--border)] p-1 text-center font-semibold">
                  {line.grade ?? ""}
                </td>
              </tr>
            ))}

            <tr>
              <th className="border border-[var(--border)] p-1 text-left font-semibold">
                Grand Total
              </th>
              {card.columns.map(([key]) => (
                <td key={key} className="border border-[var(--border)] p-1 text-center tabular-nums">
                  {show(card.grand_total[key])}
                </td>
              ))}
              {card.cumulative_columns.map((label) => (
                <td key={label} className="border border-[var(--border)] p-1 text-center tabular-nums">
                  {show(card.grand_total[label])}
                </td>
              ))}
              <td className="border border-[var(--border)] p-1" />
            </tr>
          </tbody>
        </table>
      </section>

      {card.key.length > 0 ? (
        <section className="text-xs">
          <h2 className="text-sm font-bold">Key</h2>
          <ul className="flex flex-wrap gap-x-4 gap-y-1">
            {card.key.map(([letter, remark, range]) => (
              <li key={letter}>
                <span className="font-semibold">{letter}</span> = {remark} {range}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section>
        <h2 className="text-sm font-bold">Assessment</h2>
        {card.narrative_groups.map(([letter, groupLabel, sections]) => (
          <div key={`${letter}-${groupLabel ?? ""}`}>
            {groupLabel ? (
              <p className="mt-2 text-sm font-semibold">
                {letter}) {groupLabel}
              </p>
            ) : null}
            <dl className={groupLabel ? "ml-4" : ""}>
              {sections.map(([code, label, body]) => (
                <div key={code} className="mt-1.5">
                  <dt className="text-sm font-medium">{label}</dt>
                  <dd className="text-sm text-[var(--muted)]">{body ?? "—"}</dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
      </section>

      <section className="flex flex-col gap-2">
        {card.class_teacher_comment ? (
          <p className="text-sm">
            <span className="font-semibold">Class teacher: </span>
            {card.class_teacher_comment}
          </p>
        ) : null}
        {card.head_teacher_remark ? (
          <p className="text-sm">
            <span className="font-semibold">Head teacher: </span>
            {card.head_teacher_remark}
          </p>
        ) : null}
        {card.promotion_decision ? (
          <p className="text-sm">
            <span className="font-semibold">Promotion: </span>
            {card.promotion_decision}
          </p>
        ) : null}
      </section>

      <Card className="flex flex-wrap items-center gap-3 px-4 py-4">
        {/* A plain link: the endpoint redirects to a five-minute signed URL
            and the browser follows it, which is what makes the PDF open in a
            viewer rather than arriving as a blob in JavaScript (§9). It is an
            `<a>` and not `ButtonLink`, because `next/link` would prefetch a
            one-use signed download. */}
        <a
          href={`/api/reports/${pupilId}/${termId}?half=${half}`}
          className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-[var(--brand)] px-3.5 py-2 text-sm font-medium text-[var(--brand-contrast)] shadow-sm transition hover:bg-[var(--brand-strong)]"
        >
          <Download aria-hidden className="size-4" />
          Download PDF
        </a>

        {report.acknowledged_at ? (
          <span className="flex items-center gap-1.5 text-sm text-[var(--success)]">
            <Eye aria-hidden className="size-4" />
            You confirmed you have seen this result.
          </span>
        ) : (
          <form action={acknowledge}>
            <SubmitButton
              variant="secondary"
              icon={<Eye aria-hidden className="size-4 shrink-0" />}
            >
              I have seen this result
            </SubmitButton>
          </form>
        )}
      </Card>

      {card.return_date ? (
        <p className="text-xs italic text-[var(--muted)]">
          (Please return this card to the School on {card.return_date} when next term
          begins)
        </p>
      ) : null}
    </>
  );
}

function Entry({
  label,
  value,
}: {
  label: string;
  value: string | number | null | undefined;
}) {
  return (
    <div>
      <dt className="text-xs text-[var(--muted)]">{label}</dt>
      <dd className="border-b border-[var(--border)] pb-0.5">{value ?? ""}</dd>
    </div>
  );
}

function suffix(value: string | null | undefined, unit: string): string {
  return value ? `${show(value)} ${unit}` : "";
}

/** R12's sentence, and nothing else. */
function Unavailable({ message, pupilId }: { message: string; pupilId: string }) {
  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Your children", href: "/children" }, { label: "Result" }]}
        back={{ href: `/children/${pupilId}`, label: "Back" }}
        title="Result"
      />
      <Card className="px-4 py-4">
        <p className="text-sm">{message}</p>
      </Card>
    </>
  );
}
