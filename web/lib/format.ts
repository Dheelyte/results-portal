/**
 * Small formatting helpers.
 *
 * Dates render in `Africa/Lagos` (CLAUDE.md, Conventions). The API stores and
 * sends UTC; a date that drifts by a day on the way to a screen is a date
 * that will drift on the way to a card.
 */

export const TIME_ZONE = "Africa/Lagos";

const DATE = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: TIME_ZONE,
});

/** A plain `date` from the API — no time, so no zone conversion to apply. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return value;
  return DATE.format(new Date(Date.UTC(year, month - 1, day)));
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: TIME_ZONE,
  }).format(new Date(value));
}

export const TERM_LABELS: Record<string, string> = {
  first: "First Term",
  second: "Second Term",
  third: "Third Term",
};

export const HALF_LABELS: Record<string, string> = {
  first_half: "First Half Term",
  second_half: "Second Half Term",
};

export const ROLE_LABELS: Record<string, string> = {
  admin: "Administrator",
  head_teacher: "Head teacher",
  teacher: "Teacher",
  parent: "Parent",
};

export function pupilName(pupil: {
  first_name: string;
  middle_name?: string | null;
  last_name: string;
}): string {
  return [pupil.first_name, pupil.middle_name, pupil.last_name].filter(Boolean).join(" ");
}


/**
 * "SSHMS/26/004 · Primary 4", leaving out whatever is missing. An admission
 * number is optional (D124), and a template string would print "null".
 */
export function joinParts(...parts: (string | null | undefined | false)[]): string {
  return parts.filter((part): part is string => Boolean(part)).join(" · ");
}
