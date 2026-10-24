/**
 * Draft persistence and reconciliation (§8.1).
 *
 * "Draft persistence to localStorage, keyed by class-subject and period, so a
 * dropped connection loses nothing. Reconcile on reload and say what was
 * recovered."
 *
 * `localStorage` is stubbed rather than mocked through a library: the surface
 * is three methods, and the failure modes worth testing — storage that throws
 * and storage holding rubbish — are easier to stage directly.
 */

import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import { clearDraft, countCells, readDraft, unreconciled, writeDraft } from "./drafts.ts";

// The score grid's pair. The narrative screen passes a pupil and a term
// instead; the store does not care which, and that is the point.
const CS = "class-subject-1";
const P1 = "period-1";
const P2 = "period-2";

function stubStorage(overrides: Partial<Storage> = {}) {
  const store = new Map<string, string>();
  const storage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
    removeItem: (key: string) => void store.delete(key),
    clear: () => store.clear(),
    key: (index: number) => [...store.keys()][index] ?? null,
    get length() {
      return store.size;
    },
    ...overrides,
  } as Storage;
  (globalThis as { window?: { localStorage: Storage } }).window = { localStorage: storage };
  return store;
}

beforeEach(() => {
  stubStorage();
});

describe("writeDraft and readDraft", () => {
  it("keeps a draft and reads it back", () => {
    writeDraft(CS, P1, { ada: { ca_test_1: "7" } });

    assert.deepEqual(readDraft(CS, P1)?.values, { ada: { ca_test_1: "7" } });
  });

  it("stamps the draft with when it was written", () => {
    writeDraft(CS, P1, { ada: { ca_test_1: "7" } });

    // §8.1: "say what was recovered" — which needs a time to say it from.
    assert.ok(Date.parse(readDraft(CS, P1)!.at) > 0);
  });

  it("keys drafts by class-subject and period", () => {
    // The same pupil has a different row on each half's sheet. One key for
    // both would recover first-half marks into the second-half grid.
    writeDraft(CS, P1, { ada: { ca_test_1: "7" } });
    writeDraft(CS, P2, { ada: { ca_test_1: "3" } });

    assert.deepEqual(readDraft(CS, P1)?.values, { ada: { ca_test_1: "7" } });
    assert.deepEqual(readDraft(CS, P2)?.values, { ada: { ca_test_1: "3" } });
  });

  it("returns null when there is nothing stored", () => {
    assert.equal(readDraft(CS, P1), null);
  });

  it("clears the key rather than storing an empty draft", () => {
    const store = stubStorage();
    writeDraft(CS, P1, { ada: { ca_test_1: "7" } });
    writeDraft(CS, P1, {});

    assert.equal(store.size, 0);
    assert.equal(readDraft(CS, P1), null);
  });

  it("forgets a draft once asked to", () => {
    writeDraft(CS, P1, { ada: { ca_test_1: "7" } });
    clearDraft(CS, P1);

    // Scores on a device are kept only while they are unsaved.
    assert.equal(readDraft(CS, P1), null);
  });
});

describe("when storage is unavailable", () => {
  it("survives a read that throws", () => {
    // Private browsing and locked-down Android WebViews both throw rather
    // than returning null. Losing the grid would be worse than losing the
    // draft.
    stubStorage({
      getItem: () => {
        throw new Error("SecurityError");
      },
    });

    assert.equal(readDraft(CS, P1), null);
  });

  it("survives a write that throws", () => {
    stubStorage({
      setItem: () => {
        throw new Error("QuotaExceededError");
      },
    });

    assert.doesNotThrow(() => writeDraft(CS, P1, { ada: { ca_test_1: "7" } }));
  });

  it("survives rubbish in the key", () => {
    const store = stubStorage();
    store.set(`sshms.draft.v1.${CS}.${P1}`, "not json");

    assert.equal(readDraft(CS, P1), null);
  });

  it("survives a stored value of the wrong shape", () => {
    const store = stubStorage();
    store.set(`sshms.draft.v1.${CS}.${P1}`, JSON.stringify({ values: "nope" }));

    assert.equal(readDraft(CS, P1), null);
  });
});

describe("unreconciled", () => {
  it("keeps only the cells the server does not already agree with", () => {
    const pending = unreconciled(
      { ada: { ca_test_1: "7", ca_test_2: "6" } },
      { ada: { ca_test_1: "7", ca_test_2: "" } },
    );

    assert.deepEqual(pending, { ada: { ca_test_2: "6" } });
  });

  it("recovers nothing when the save did land after all", () => {
    // The browser closed between writing the draft and the save returning.
    // Announcing a recovery here teaches a teacher to ignore the notice.
    const pending = unreconciled({ ada: { ca_test_1: "7" } }, { ada: { ca_test_1: "7" } });

    assert.deepEqual(pending, {});
  });

  it("recovers a cell the teacher cleared", () => {
    // An emptied cell is real work: the draft says blank, the server still
    // holds a score.
    const pending = unreconciled({ ada: { ca_test_1: "" } }, { ada: { ca_test_1: "7" } });

    assert.deepEqual(pending, { ada: { ca_test_1: "" } });
  });

  it("recovers a pupil the server has no row for yet", () => {
    const pending = unreconciled({ ada: { ca_test_1: "7" } }, {});

    assert.deepEqual(pending, { ada: { ca_test_1: "7" } });
  });

  it("counts what it recovered", () => {
    const pending = unreconciled(
      { ada: { ca_test_1: "7", ca_test_2: "6" }, emeka: { ca_test_1: "4" } },
      {},
    );

    assert.equal(countCells(pending), 3);
  });
});
