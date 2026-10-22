"use client";

/**
 * Grading scale, narrative sections and the phrase bank
 * (ARCHITECTURE.md §1.3, §4.5, §4.6).
 *
 * A grading scale is a **version**, never an edit. If the school moves a
 * boundary, last term's printed cards must still agree with the portal, so a
 * change is a new scale that becomes active from now on. Grades already
 * approved keep the scale snapshotted onto them.
 *
 * The phrase bank is treated as core rather than a nicety: a class of thirty
 * needs 480 written passages a term from one class teacher, and without
 * phrases to start from that is the feature that gets abandoned first.
 */

import { useState } from "react";

import {
  Badge,
  Button,
  Cell,
  Field,
  Input,
  Notice,
  Panel,
  Row,
  Select,
  Spinner,
  Table,
  TextArea,
} from "@/components/ui";
import type { NarrativeSection } from "@/lib/api/admin";
import { useAdminApi } from "@/lib/api/use-admin";
import { formatDate } from "@/lib/format";
import { useAction, useResource } from "@/lib/use-async";

/** The seven bands as printed on the card (§1.3), offered as a starting point. */
const CARD_BANDS = [
  { letter: "A+", remark: "Excellence", min_score: "90", max_score: "100" },
  { letter: "A", remark: "Very Good", min_score: "80", max_score: "89" },
  { letter: "B+", remark: "Good", min_score: "70", max_score: "79" },
  { letter: "B", remark: "Fairly Good", min_score: "60", max_score: "69" },
  { letter: "C", remark: "Average", min_score: "50", max_score: "59" },
  { letter: "D", remark: "Below Average", min_score: "40", max_score: "49" },
  { letter: "E", remark: "Weak", min_score: "0", max_score: "39" },
];

export default function AssessmentPage() {
  const api = useAdminApi();
  if (!api) return <Spinner />;

  return (
    <>
      <GradingScales />
      <NarrativeSections />
      <PhraseBank />
    </>
  );
}

/* ------------------------------------------------------------------------- */

function GradingScales() {
  const api = useAdminApi()!;
  const scales = useResource(() => api.gradingScales(), [api]);
  const action = useAction(scales.reload);
  const [name, setName] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [bands, setBands] = useState(CARD_BANDS);

  return (
    <Panel
      title="Grading scale"
      description="One scale is active. Changing a boundary means a new version, so printed cards keep saying what they said."
    >
      <div className="flex flex-col gap-5">
        {scales.loading ? <Spinner /> : null}
        {scales.error ? <Notice>{scales.error}</Notice> : null}

        {(scales.data ?? []).map((scale) => (
          <section key={scale.id} className="rounded-md border border-[var(--border)] p-4">
            <header className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-sm font-medium">
                  {scale.name} {scale.is_active ? <Badge tone="good">Active</Badge> : null}
                </p>
                <p className="text-xs text-[var(--muted)]">
                  In force from {formatDate(scale.effective_from)}
                </p>
              </div>
              {scale.is_active ? null : (
                <Button
                  variant="secondary"
                  disabled={action.busy}
                  onClick={() =>
                    void action.run(
                      () => api.activateGradingScale(scale.id),
                      `${scale.name} is now the active scale.`,
                    )
                  }
                >
                  Make active
                </Button>
              )}
            </header>

            <Table head={["Grade", "Meaning", "Range"]}>
              {(scale.bands ?? []).map((band) => (
                <Row key={band.id}>
                  <Cell>{band.letter}</Cell>
                  <Cell>{band.remark}</Cell>
                  <Cell>
                    {band.min_score}–{band.max_score}
                  </Cell>
                </Row>
              ))}
            </Table>
          </section>
        ))}

        <details className="rounded-md border border-[var(--border)] p-4">
          <summary className="cursor-pointer text-sm font-medium">
            Add a new version of the scale
          </summary>

          <form
            className="mt-4 flex flex-col gap-4"
            onSubmit={async (event) => {
              event.preventDefault();
              await action.run(
                () =>
                  api.createGradingScale({
                    name,
                    effective_from: effectiveFrom,
                    bands: bands.map((band) => ({
                      letter: band.letter,
                      remark: band.remark,
                      min_score: band.min_score,
                      max_score: band.max_score,
                    })),
                    activate: true,
                  }),
                `${name} created and made active.`,
              );
            }}
          >
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Name" hint="Identifies which cards used it." required>
                <Input
                  required
                  placeholder="Card scale (seven bands)"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
              </Field>
              <Field label="In force from" required>
                <Input
                  type="date"
                  required
                  value={effectiveFrom}
                  onChange={(event) => setEffectiveFrom(event.target.value)}
                />
              </Field>
            </div>

            <p className="text-sm text-[var(--muted)]">
              Bands must not overlap, and every mark from 0 to 100 must fall in one — otherwise
              some pupil&apos;s average would resolve to no grade and the cell would print
              empty.
            </p>

            <Table head={["Grade", "Meaning", "From", "To", ""]}>
              {bands.map((band, index) => (
                <Row key={index}>
                  <Cell>
                    <Input
                      aria-label={`Grade letter ${index + 1}`}
                      value={band.letter}
                      onChange={(event) => {
                        const next = [...bands];
                        next[index] = { ...band, letter: event.target.value };
                        setBands(next);
                      }}
                    />
                  </Cell>
                  <Cell>
                    <Input
                      aria-label={`Meaning ${index + 1}`}
                      value={band.remark}
                      onChange={(event) => {
                        const next = [...bands];
                        next[index] = { ...band, remark: event.target.value };
                        setBands(next);
                      }}
                    />
                  </Cell>
                  <Cell>
                    <Input
                      type="number"
                      className="w-20"
                      aria-label={`From ${index + 1}`}
                      value={band.min_score}
                      onChange={(event) => {
                        const next = [...bands];
                        next[index] = { ...band, min_score: event.target.value };
                        setBands(next);
                      }}
                    />
                  </Cell>
                  <Cell>
                    <Input
                      type="number"
                      className="w-20"
                      aria-label={`To ${index + 1}`}
                      value={band.max_score}
                      onChange={(event) => {
                        const next = [...bands];
                        next[index] = { ...band, max_score: event.target.value };
                        setBands(next);
                      }}
                    />
                  </Cell>
                  <Cell>
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => setBands(bands.filter((_, at) => at !== index))}
                    >
                      Remove
                    </Button>
                  </Cell>
                </Row>
              ))}
            </Table>

            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="secondary"
                onClick={() =>
                  setBands([
                    ...bands,
                    { letter: "", remark: "", min_score: "", max_score: "" },
                  ])
                }
              >
                Add a band
              </Button>
              <Button type="button" variant="secondary" onClick={() => setBands(CARD_BANDS)}>
                Reset to the card&apos;s scale
              </Button>
              <Button type="submit" disabled={action.busy}>
                Create and activate
              </Button>
            </div>
          </form>
        </details>

        <Notice>{action.error}</Notice>
        <Notice tone="success">{action.success}</Notice>
      </div>
    </Panel>
  );
}

/* ------------------------------------------------------------------------- */

function NarrativeSections() {
  const api = useAdminApi()!;
  const sections = useResource(() => api.narrativeSections(), [api]);
  const action = useAction(sections.reload);
  const [draft, setDraft] = useState<Record<string, Partial<NarrativeSection>>>({});

  const edited = (section: NarrativeSection) => ({ ...section, ...draft[section.id] });
  const dirty = Object.keys(draft).length > 0;

  return (
    <Panel
      title="Narrative sections"
      description="The written passages on the card's assessment pages, in card order. Retire a section rather than deleting it — past cards still cite it."
      actions={
        <Button
          disabled={action.busy || !dirty}
          onClick={async () => {
            const payload = (sections.data ?? []).map((section) => {
              const value = edited(section);
              return {
                code: value.code,
                label: value.label,
                group_label: value.group_label ?? null,
                display_order: value.display_order,
                is_active: value.is_active,
              };
            });
            const saved = await action.run(
              () => api.saveNarrativeSections({ sections: payload }),
              "Sections saved.",
            );
            if (saved) setDraft({});
          }}
        >
          Save changes
        </Button>
      }
    >
      {sections.loading ? <Spinner /> : null}
      {sections.error ? <Notice>{sections.error}</Notice> : null}

      <Table
        head={["Order", "Group", "Label", "Code", "Active"]}
        empty="No sections yet. Run the reference seed, or add them here."
      >
        {(sections.data ?? []).map((section) => {
          const value = edited(section);
          const change = (patch: Partial<NarrativeSection>) =>
            setDraft({ ...draft, [section.id]: { ...draft[section.id], ...patch } });

          return (
            <Row key={section.id}>
              <Cell>
                <Input
                  type="number"
                  min={0}
                  className="w-20"
                  aria-label={`Order of ${section.label}`}
                  value={value.display_order}
                  onChange={(event) =>
                    change({ display_order: Number(event.target.value) })
                  }
                />
              </Cell>
              <Cell className="text-[var(--muted)]">{value.group_label ?? "—"}</Cell>
              <Cell>
                <Input
                  aria-label={`Label of ${section.code}`}
                  value={value.label}
                  onChange={(event) => change({ label: event.target.value })}
                />
              </Cell>
              <Cell className="font-mono text-xs text-[var(--muted)]">{section.code}</Cell>
              <Cell>
                <input
                  type="checkbox"
                  aria-label={`${section.label} is active`}
                  checked={value.is_active}
                  onChange={(event) => change({ is_active: event.target.checked })}
                />
              </Cell>
            </Row>
          );
        })}
      </Table>

      <p className="mt-3 text-sm text-[var(--muted)]">
        {(sections.data ?? []).filter((section) => section.is_active).length} active sections.
        Each one is a passage a teacher writes for every pupil, every term.
      </p>

      <div className="mt-3 flex flex-col gap-2">
        <Notice>{action.error}</Notice>
        <Notice tone="success">{action.success}</Notice>
      </div>
    </Panel>
  );
}

/* ------------------------------------------------------------------------- */

function PhraseBank() {
  const api = useAdminApi()!;
  const sections = useResource(() => api.narrativeSections(), [api]);
  const [scope, setScope] = useState("class_teacher");
  const phrases = useResource(() => api.comments(scope), [api, scope]);
  const action = useAction(phrases.reload);
  const [text, setText] = useState("");

  return (
    <Panel
      title="Phrase bank"
      description="Starting points a teacher can pick from, scoped to one section so the suggestions are relevant."
      actions={
        <Field label="Section">
          <Select value={scope} onChange={(event) => setScope(event.target.value)}>
            <option value="class_teacher">Class teacher&apos;s comment</option>
            <option value="head_teacher">Head teacher&apos;s comment</option>
            {(sections.data ?? [])
              .filter((section) => section.is_active)
              .map((section) => (
                <option key={section.id} value={section.code}>
                  {section.group_label ? `${section.group_label}: ` : ""}
                  {section.label}
                </option>
              ))}
          </Select>
        </Field>
      }
    >
      {phrases.loading ? <Spinner /> : null}
      {phrases.error ? <Notice>{phrases.error}</Notice> : null}

      <ul className="flex flex-col gap-2">
        {(phrases.data ?? []).map((phrase) => (
          <li key={phrase.id} className="rounded border border-[var(--border)] px-3 py-2 text-sm">
            {phrase.text}
          </li>
        ))}
        {phrases.data?.length ? null : (
          <p className="text-sm text-[var(--muted)]">
            No phrases for this section yet.
          </p>
        )}
      </ul>

      <form
        className="mt-4 flex flex-col gap-3"
        onSubmit={async (event) => {
          event.preventDefault();
          const created = await action.run(
            () => api.createComment({ scope, text }),
            "Phrase added.",
          );
          if (created) setText("");
        }}
      >
        <Field label="New phrase" required>
          <TextArea
            required
            rows={2}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
        </Field>
        <Button type="submit" className="w-fit" disabled={action.busy}>
          Add phrase
        </Button>
      </form>

      <div className="mt-3 flex flex-col gap-2">
        <Notice>{action.error}</Notice>
        <Notice tone="success">{action.success}</Notice>
      </div>
    </Panel>
  );
}
