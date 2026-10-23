"use client";

/**
 * When to save, and what to tell the teacher about it (§8.1).
 *
 * "Autosave the dirty set every 20 seconds and on blur, with a visible
 * 'Saved 14:32' / 'Saving…' / 'Not saved — retrying' indicator."
 *
 * This hook owns the *timing* and the *status*. The grid owns what to send,
 * because only it knows which cells are dirty — a hook that also owned the
 * payload would need to know the shape of a score sheet.
 *
 * The failure modes are deliberately different:
 *
 * - A network or server failure is **retried** on the next tick, and the
 *   indicator says so. The dirty set is kept, the draft is still on the
 *   device, and the teacher keeps typing.
 * - A rejection — a score over its maximum — is **not** retried. Retrying
 *   would fail identically every twenty seconds while the teacher watched a
 *   spinner, so the save stops until something changes.
 */

import { useCallback, useEffect, useRef, useState } from "react";

export type SaveState = "clean" | "pending" | "saving" | "saved" | "retrying" | "rejected";

export interface Autosave {
  state: SaveState;
  savedAt: Date | null;
  /** Save immediately, if there is anything to save. Safe to call freely. */
  saveNow: () => void;
}

export const AUTOSAVE_INTERVAL_MS = 20_000;

export function useAutosave(options: {
  /** True when there are unsaved cells. */
  hasPending: boolean;
  /** Resolves when saved; rejects on failure. */
  save: () => Promise<void>;
  /** False for a rejection, so it is not retried. */
  isRetryable: (error: unknown) => boolean;
  enabled?: boolean;
  intervalMs?: number;
}): Autosave {
  const { hasPending, save, isRetryable, enabled = true, intervalMs = AUTOSAVE_INTERVAL_MS } =
    options;

  const [state, setState] = useState<SaveState>("clean");
  const [savedAt, setSavedAt] = useState<Date | null>(null);

  // Refs, so the interval below is installed once rather than re-armed on
  // every keystroke — a timer reset by typing would never fire for a teacher
  // working steadily, which is precisely the case it exists for.
  const saveRef = useRef(save);
  const retryableRef = useRef(isRetryable);
  const pendingRef = useRef(hasPending);
  const inFlight = useRef(false);
  const again = useRef(false);
  const rejected = useRef(false);

  saveRef.current = save;
  retryableRef.current = isRetryable;
  pendingRef.current = hasPending;

  const run = useCallback(async () => {
    if (!pendingRef.current || inFlight.current) {
      // A save asked for while one is in flight is remembered, not dropped:
      // the cell the teacher just changed would otherwise sit unsaved until
      // the next tick.
      if (inFlight.current) again.current = true;
      return;
    }

    inFlight.current = true;
    setState("saving");
    try {
      await saveRef.current();
      rejected.current = false;
      setSavedAt(new Date());
      setState(pendingRef.current ? "pending" : "saved");
    } catch (error) {
      if (retryableRef.current(error)) {
        rejected.current = false;
        setState("retrying");
      } else {
        rejected.current = true;
        setState("rejected");
      }
    } finally {
      inFlight.current = false;
      if (again.current) {
        again.current = false;
        if (!rejected.current) void run();
      }
    }
  }, []);

  const saveNow = useCallback(() => {
    if (!enabled) return;
    void run();
  }, [enabled, run]);

  // The twenty-second tick. It also retries, which is why a failed save needs
  // no timer of its own.
  useEffect(() => {
    if (!enabled) return;
    const timer = window.setInterval(() => {
      if (pendingRef.current && !rejected.current) void run();
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [enabled, intervalMs, run]);

  // Keep the indicator honest as the teacher types and as saves land.
  useEffect(() => {
    setState((current) => {
      if (current === "saving") return current;
      if (hasPending) return current === "retrying" || current === "rejected" ? current : "pending";
      return savedAt ? "saved" : "clean";
    });
  }, [hasPending, savedAt]);

  return { state, savedAt, saveNow };
}

/** The sentence beside the grid. Short, because it is read at a glance. */
export function autosaveLabel(state: SaveState, savedAt: Date | null): string {
  const time = savedAt
    ? savedAt.toLocaleTimeString("en-NG", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
        timeZone: "Africa/Lagos",
      })
    : null;

  switch (state) {
    case "saving":
      return "Saving…";
    case "retrying":
      return "Not saved — retrying";
    case "rejected":
      return "Not saved — fix the cells marked below";
    case "pending":
      return time ? `Unsaved changes — last saved ${time}` : "Unsaved changes";
    case "saved":
      return time ? `Saved ${time}` : "Saved";
    default:
      return "No changes";
  }
}
