"use client";

/**
 * Edit and delete, the same way on every admin screen (docs/DECISIONS.md D121).
 *
 * A delete always asks first and says what will happen. The server decides
 * whether it is safe. Anything with history is refused with a sentence such
 * as "it has 312 scores. Deactivate it instead.", and the dialog shows that
 * sentence where the button was, so the admin learns the safe alternative at
 * the moment they need it.
 */

import { Pencil, Trash2 } from "lucide-react";
import type { ReactNode } from "react";

import { Modal } from "@/components/modal";
import { Button, Notice } from "@/components/ui";
import { useAction } from "@/lib/use-async";

export interface DeleteTarget {
  /** What is being deleted, as the dialog's title names it: "Primary 4". */
  name: string;
  /** What else goes with it, if anything; shown above the buttons. */
  consequence?: ReactNode;
  run: () => Promise<unknown>;
}

export function ConfirmDelete({
  target,
  onClose,
  onDeleted,
}: {
  target: DeleteTarget | null;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const action = useAction(onDeleted);

  const close = () => {
    action.clear();
    onClose();
  };

  return (
    <Modal open={target !== null} onClose={close} title={`Delete ${target?.name ?? ""}?`}>
      <div className="flex flex-col gap-3 text-sm">
        <p>
          This can&apos;t be undone. Anything already in use is kept: the portal refuses and
          says why.
        </p>
        {target?.consequence ? (
          <p className="text-[var(--muted)]">{target.consequence}</p>
        ) : null}
        <Notice>{action.error}</Notice>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={close}>
            {action.error ? "Close" : "Cancel"}
          </Button>
          {action.error ? null : (
            <Button
              type="button"
              variant="danger"
              icon={Trash2}
              loading={action.busy}
              onClick={async () => {
                if (target && (await action.run(target.run))) onClose();
              }}
            >
              Delete
            </Button>
          )}
        </div>
      </div>
    </Modal>
  );
}

/** The two buttons at the end of a row. */
export function RowActions({
  label,
  onEdit,
  onDelete,
  disabled,
  children,
}: {
  /** The row's name, for screen readers: "Edit Primary 4". */
  label: string;
  onEdit?: () => void;
  onDelete?: () => void;
  disabled?: boolean;
  /** Any other row buttons, placed before Edit. */
  children?: ReactNode;
}) {
  return (
    <span className="inline-flex flex-wrap items-center justify-end gap-1">
      {children}
      {onEdit ? (
        <Button
          variant="ghost"
          size="sm"
          icon={Pencil}
          disabled={disabled}
          aria-label={`Edit ${label}`}
          onClick={onEdit}
        >
          Edit
        </Button>
      ) : null}
      {onDelete ? (
        <Button
          variant="ghost-danger"
          size="sm"
          icon={Trash2}
          disabled={disabled}
          aria-label={`Delete ${label}`}
          onClick={onDelete}
        >
          Delete
        </Button>
      ) : null}
    </span>
  );
}
