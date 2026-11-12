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

import {
  ClipboardList,
  ListPlus,
  MessageSquarePlus,
  MessageSquareQuote,
  Plus,
  Scale,
} from "lucide-react";
import { useState } from "react";

import { ConfirmDelete, RowActions, type DeleteTarget } from "@/components/manage";
import { Modal } from "@/components/modal";
import {
  Badge,
  Button,
  Card,
  Cell,
  Field,
  Input,
  Notice,
  PageHeader,
  Panel,
  Row,
  Select,
  SkeletonPanel,
  SkeletonTable,
  Table,
  TextArea,
} from "@/components/ui";
import type { Comment, NarrativeSection } from "@/lib/api/admin";
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

/**
 * A create dialog's wiring, handed from the page (which owns the button at
 * the top) to the panel (which owns the form and what it reloads). D117.
 */
interface CreateDialog {
  open: boolean;
  onClose: () => void;
}

/** Clear an action's messages each time its dialog opens, during render. */
function useClearOnOpen(open: boolean, ...actions: { clear: () => void }[]) {
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) for (const action of actions) action.clear();
  }
}

export default function AssessmentPage() {
  const api = useAdminApi();
  const [dialog, setDialog] = useState<"scale" | "section" | "phrase" | null>(null);
  // Bumped when a section is added, so the phrase bank can offer it at once.
  const [sectionsVersion, setSectionsVersion] = useState(0);
  const closeDialog = () => setDialog(null);

  return (
    <>
      <PageHeader
        title="Grading & narrative"
        description="The scale a grade is read from, the sections the card prints, and the phrases a teacher starts from."
        actions={
          <>
            <Button
              variant="secondary"
              icon={ListPlus}
              disabled={!api}
              onClick={() => setDialog("section")}
            >
              Add section
            </Button>
            <Button
              variant="secondary"
              icon={MessageSquarePlus}
              disabled={!api}
              onClick={() => setDialog("phrase")}
            >
              Add phrase
            </Button>
            <Button icon={Plus} disabled={!api} onClick={() => setDialog("scale")}>
              New scale version
            </Button>
          </>
        }
      />

      {api ? (
        <>
          <GradingScales create={{ open: dialog === "scale", onClose: closeDialog }} />
          <NarrativeSections
            create={{ open: dialog === "section", onClose: closeDialog }}
            onAdded={() => setSectionsVersion((version) => version + 1)}
          />
          <PhraseBank
            create={{ open: dialog === "phrase", onClose: closeDialog }}
            sectionsVersion={sectionsVersion}
          />
        </>
      ) : (
        <>
          <SkeletonPanel rows={6} label="Loading the assessment settings…" />
          <SkeletonPanel rows={6} />
        </>
      )}
    </>
  );
}

/* ------------------------------------------------------------------------- */

function GradingScales({ create: dialog }: { create: CreateDialog }) {
  const api = useAdminApi()!;
  const scales = useResource(() => api.gradingScales(), [api]);
  const action = useAction(scales.reload);
  const create = useAction(scales.reload);
  useClearOnOpen(dialog.open, action, create);
  const [name, setName] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [bands, setBands] = useState(CARD_BANDS);
  const [deleting, setDeleting] = useState<DeleteTarget | null>(null);

  return (
    <Panel
      title="Grading scale"
      icon={Scale}
      description="One scale is active. Changing a boundary means a new version, so printed cards keep saying what they said."
    >
      <div className="flex flex-col gap-5">
        {scales.loading ? <SkeletonTable rows={7} columns={3} label="Loading the scales…" /> : null}
        {scales.error ? <Notice>{scales.error}</Notice> : null}

        {(scales.data ?? []).map((scale) => (
          <Card key={scale.id} className="p-4">
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
                <RowActions
                  label={scale.name}
                  onDelete={() =>
                    setDeleting({
                      name: scale.name,
                      consequence:
                        "A scale is never edited: make a new version instead. Only a version that isn't active and that no grade was approved under can be deleted.",
                      run: () => api.deleteGradingScale(scale.id),
                    })
                  }
                >
                  <Button
                    variant="secondary"
                    size="sm"
                    loading={action.busy}
                    onClick={() =>
                      void action.run(
                        () => api.activateGradingScale(scale.id),
                        `${scale.name} is now the active scale.`,
                      )
                    }
                  >
                    Make active
                  </Button>
                </RowActions>
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
          </Card>
        ))}

        <Notice>{action.error}</Notice>
        <Notice tone="success">
          {action.success ?? (dialog.open ? null : create.success)}
        </Notice>
      </div>

      <Modal
        open={dialog.open}
        onClose={dialog.onClose}
        title="New version of the grading scale"
        description="It becomes the active scale. Grades already approved keep the scale they were read from."
        size="lg"
      >
        <form
          className="flex flex-col gap-4"
          onSubmit={async (event) => {
            event.preventDefault();
            const created = await create.run(
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
            if (created) dialog.onClose();
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

          <Notice>{create.error}</Notice>

          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() =>
                setBands([
                  ...bands,
                  { letter: "", remark: "", min_score: "", max_score: "" },
                ])
              }
            >
              Add a band
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setBands(CARD_BANDS)}
            >
              Reset to the card&apos;s scale
            </Button>
          </div>

          <div className="flex justify-end gap-2 border-t border-[var(--border)] pt-4">
            <Button type="button" variant="secondary" onClick={dialog.onClose}>
              Cancel
            </Button>
            <Button type="submit" icon={Plus} loading={create.busy}>
              Create and activate
            </Button>
          </div>
        </form>
      </Modal>
      <ConfirmDelete target={deleting} onClose={() => setDeleting(null)} onDeleted={scales.reload} />
    </Panel>
  );
}

/* ------------------------------------------------------------------------- */

/** In the "Where it goes" select: a heading of its own, or a new group. */
const OWN_HEADING = "";
const NEW_GROUP = "\u0000new-group"; // cannot collide with a real group name

function NarrativeSections({
  create: dialog,
  onAdded,
}: {
  create: CreateDialog;
  onAdded: () => void;
}) {
  const api = useAdminApi()!;
  const sections = useResource(() => api.narrativeSections(), [api]);
  const action = useAction(sections.reload);
  const create = useAction(sections.reload);
  useClearOnOpen(dialog.open, create);
  const [draft, setDraft] = useState<Record<string, Partial<NarrativeSection>>>({});
  const [newLabel, setNewLabel] = useState("");
  const [placement, setPlacement] = useState(OWN_HEADING);
  const [newGroup, setNewGroup] = useState("");
  const [deleting, setDeleting] = useState<DeleteTarget | null>(null);

  const edited = (section: NarrativeSection) => ({ ...section, ...draft[section.id] });
  const dirty = Object.keys(draft).length > 0;

  // Each group once, with the letter the card prints before it.
  const groups = new Map<string, string>();
  for (const section of sections.data ?? []) {
    if (section.group_label && !groups.has(section.group_label)) {
      groups.set(section.group_label, section.code.split(".", 1)[0] ?? section.code);
    }
  }

  return (
    <Panel
      title="Narrative sections"
      icon={ClipboardList}
      description="The written passages on the card's assessment pages, in card order. Retire a section rather than deleting it — past cards still cite it."
      actions={
        <Button
          loading={action.busy}
          disabled={!dirty}
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
      {sections.loading ? (
        <SkeletonTable rows={8} columns={3} label="Loading the sections…" />
      ) : null}
      {sections.error ? <Notice>{sections.error}</Notice> : null}

      <Table
        head={["Order", "Group", "Label", "Code", "Active", ""]}
        empty="No sections yet. Add one with “Add section” at the top of the page."
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
              <Cell className="text-right">
                <RowActions
                  label={section.label}
                  disabled={dirty}
                  onDelete={() =>
                    setDeleting({
                      name: section.label,
                      consequence:
                        "Only a section nobody has written in can be deleted. Its phrases in the phrase bank go with it. Once a passage is written, untick Active to retire it instead.",
                      run: async () => {
                        await api.deleteNarrativeSection(section.id);
                        onAdded();
                      },
                    })
                  }
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
        {!dialog.open ? <Notice tone="success">{create.success}</Notice> : null}
      </div>

      <Modal
        open={dialog.open}
        onClose={dialog.onClose}
        title="Add a narrative section"
        description="A passage teachers write for every pupil, every term. Its letter and place on the card are chosen for you."
      >
        <form
          className="flex flex-col gap-3"
          onSubmit={async (event) => {
            event.preventDefault();
            const group =
              placement === NEW_GROUP ? newGroup : placement === OWN_HEADING ? null : placement;
            const added = await create.run(
              () => api.createNarrativeSection({ label: newLabel, group_label: group }),
              `“${newLabel.trim()}” added.`,
            );
            if (added) {
              setNewLabel("");
              setNewGroup("");
              onAdded();
              dialog.onClose();
            }
          }}
        >
          <Field label="Section name" hint="Printed on the card." required>
            <Input
              required
              maxLength={200}
              value={newLabel}
              onChange={(event) => setNewLabel(event.target.value)}
            />
          </Field>
          <Field
            label="Where it goes"
            hint={
              placement === OWN_HEADING || placement === NEW_GROUP
                ? "At the end of the card, with the next unused letter."
                : "Inside that block, after its last section."
            }
          >
            <Select value={placement} onChange={(event) => setPlacement(event.target.value)}>
              <option value={OWN_HEADING}>A heading of its own</option>
              {[...groups].map(([group, letter]) => (
                <option key={group} value={group}>
                  Inside {letter}) {group}
                </option>
              ))}
              <option value={NEW_GROUP}>A new group…</option>
            </Select>
          </Field>
          {placement === NEW_GROUP ? (
            <Field label="Group name" hint="Printed above the sections inside it." required>
              <Input
                required
                maxLength={200}
                value={newGroup}
                onChange={(event) => setNewGroup(event.target.value)}
              />
            </Field>
          ) : null}
          {dirty ? (
            <Notice tone="warning">
              Save or undo your edits to the table first — adding a section renumbers the order.
            </Notice>
          ) : null}
          <Notice>{create.error}</Notice>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={dialog.onClose}>
              Cancel
            </Button>
            <Button type="submit" icon={Plus} loading={create.busy} disabled={dirty}>
              Add section
            </Button>
          </div>
        </form>
      </Modal>
      <ConfirmDelete target={deleting} onClose={() => setDeleting(null)} onDeleted={sections.reload} />
    </Panel>
  );
}

/* ------------------------------------------------------------------------- */

function PhraseBank({
  create: dialog,
  sectionsVersion,
}: {
  create: CreateDialog;
  sectionsVersion: number;
}) {
  const api = useAdminApi()!;
  const sections = useResource(() => api.narrativeSections(), [api, sectionsVersion]);
  const [scope, setScope] = useState("class_teacher");
  const phrases = useResource(() => api.comments(scope), [api, scope]);
  const action = useAction(phrases.reload);
  useClearOnOpen(dialog.open, action);
  const [text, setText] = useState("");
  const update = useAction(phrases.reload);
  const [editing, setEditing] = useState<{ phrase: Comment; text: string } | null>(null);
  const [deleting, setDeleting] = useState<DeleteTarget | null>(null);

  // One list of sections, for the filter above the list and the dialog's own
  // choice — the two are the same state, so a new phrase lands in view.
  const sectionOptions = (
    <>
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
    </>
  );

  return (
    <Panel
      title="Phrase bank"
      icon={MessageSquareQuote}
      description="Starting points a teacher can pick from, scoped to one section so the suggestions are relevant."
      actions={
        <Field label="Section">
          <Select value={scope} onChange={(event) => setScope(event.target.value)}>
            {sectionOptions}
          </Select>
        </Field>
      }
    >
      {phrases.loading ? <SkeletonTable rows={6} columns={2} label="Loading the phrases…" /> : null}
      {phrases.error ? <Notice>{phrases.error}</Notice> : null}

      <ul className="flex flex-col gap-2">
        {(phrases.data ?? []).map((phrase) => (
          <li
            key={phrase.id}
            className="flex items-start justify-between gap-3 rounded border border-[var(--border)] px-3 py-2 text-sm"
          >
            <span className="min-w-0 py-1">{phrase.text}</span>
            <RowActions
              label="phrase"
              onEdit={() => {
                update.clear();
                setEditing({ phrase, text: phrase.text });
              }}
              onDelete={() =>
                setDeleting({
                  name: "this phrase",
                  consequence: "Passages already written from it keep their own words.",
                  run: () => api.deleteComment(phrase.id),
                })
              }
            />
          </li>
        ))}
        {phrases.data?.length ? null : (
          <p className="text-sm text-[var(--muted)]">
            No phrases for this section yet.
          </p>
        )}
      </ul>

      {!dialog.open && action.success ? (
        <div className="mt-3">
          <Notice tone="success">{action.success}</Notice>
        </div>
      ) : null}

      <Modal
        open={dialog.open}
        onClose={dialog.onClose}
        title="Add a phrase"
        description="A starting point a teacher can pick from and then make their own."
      >
        <form
          className="flex flex-col gap-3"
          onSubmit={async (event) => {
            event.preventDefault();
            const created = await action.run(
              () => api.createComment({ scope, text }),
              "Phrase added.",
            );
            if (created) {
              setText("");
              dialog.onClose();
            }
          }}
        >
          <Field label="Section" required>
            <Select value={scope} onChange={(event) => setScope(event.target.value)}>
              {sectionOptions}
            </Select>
          </Field>
          <Field label="Phrase" required>
            <TextArea
              required
              rows={3}
              value={text}
              onChange={(event) => setText(event.target.value)}
            />
          </Field>
          <Notice>{action.error}</Notice>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={dialog.onClose}>
              Cancel
            </Button>
            <Button type="submit" icon={Plus} loading={action.busy}>
              Add phrase
            </Button>
          </div>
        </form>
      </Modal>
      <Modal open={editing !== null} onClose={() => setEditing(null)} title="Edit phrase">
        {editing ? (
          <form
            className="flex flex-col gap-3"
            onSubmit={async (event) => {
              event.preventDefault();
              const saved = await update.run(() =>
                api.updateComment(editing.phrase.id, { text: editing.text }),
              );
              if (saved) setEditing(null);
            }}
          >
            <Field label="Phrase" hint="Passages already written from it keep their own words." required>
              <TextArea
                required
                rows={3}
                value={editing.text}
                onChange={(event) => setEditing({ ...editing, text: event.target.value })}
              />
            </Field>
            <Notice>{update.error}</Notice>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={() => setEditing(null)}>
                Cancel
              </Button>
              <Button type="submit" loading={update.busy}>
                Save changes
              </Button>
            </div>
          </form>
        ) : null}
      </Modal>

      <ConfirmDelete target={deleting} onClose={() => setDeleting(null)} onDeleted={phrases.reload} />
    </Panel>
  );
}
