"use client";

/**
 * Loading a resource, and running an action that reloads it.
 *
 * Two hooks rather than a data-fetching library: §2 lists the stack and does
 * not include one, and rule 8 is clear about new dependencies. These screens
 * need a spinner, an error line and a reload, which is this file.
 */

import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api/client";

export function messageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return "Something went wrong. Please try again.";
}

export interface Resource<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/**
 * `deps` is what re-fetches, exactly as in `useEffect`. The loader is called
 * with an AbortSignal so a reload that overtakes its predecessor does not
 * paint the older answer.
 */
export function useResource<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
  options: { enabled?: boolean } = {},
): Resource<T> {
  const enabled = options.enabled ?? true;
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    load(controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        setData(value);
        setError(null);
      })
      .catch((caught) => {
        if (controller.signal.aborted) return;
        setError(messageOf(caught));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, enabled]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  return { data, error, loading, reload };
}

export interface Action {
  run: (task: () => Promise<unknown>, successMessage?: string) => Promise<boolean>;
  busy: boolean;
  error: string | null;
  success: string | null;
  clear: () => void;
}

/** Runs one write at a time and keeps its outcome for display. */
export function useAction(onDone?: () => void): Action {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const run = useCallback(
    async (task: () => Promise<unknown>, successMessage?: string) => {
      setBusy(true);
      setError(null);
      setSuccess(null);
      try {
        await task();
        if (successMessage) setSuccess(successMessage);
        onDone?.();
        return true;
      } catch (caught) {
        setError(messageOf(caught));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [onDone],
  );

  const clear = useCallback(() => {
    setError(null);
    setSuccess(null);
  }, []);

  return { run, busy, error, success, clear };
}
