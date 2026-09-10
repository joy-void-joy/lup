import { describe, expect, test } from "bun:test";
import type { JournalEntry } from "../generated/views";
import {
  actorDisplay,
  actorOf,
  carriesError,
  concernIds,
  inScope,
  isRunEvent,
  matchesKind,
  scopedActors,
  tone,
  visible,
} from "./filters";

function entry(seq: number, kind: string, id: string, round: number, event: JournalEntry["event"]): JournalEntry {
  return { seq, at: "2026-09-09T10:00:00+00:00", actor: { kind, id, round }, event };
}

const identifiers = { session: { value: "s" }, turn: { value: "t" } };
const record: JournalEntry[] = [
  entry(0, "run", "run-1", 0, { type: "phase_changed", phase: "workers" }),
  entry(1, "worker", "alpha", 1, { type: "turn_started", identifiers }),
  entry(2, "worker", "alpha", 1, {
    type: "message_completed",
    identifiers,
    message: {
      blocks: [{ type: "tool_result", content: "boom", is_error: true, tool_call_id: "c" }],
      message_id: null,
      model: null,
      parent_tool_call_id: null,
      role: "assistant",
    },
  }),
  entry(3, "reviewer", "alpha", 2, { type: "turn_completed", identifiers }),
  entry(4, "worker", "beta", 1, { type: "block_started", identifiers, block: { type: "text", text: "x" } }),
  entry(5, "run", "run-1", 0, { type: "run_failed", reason: "gave up" }),
];

describe("scope", () => {
  test("a concern scope takes every actor sharing its id, an actor scope one", () => {
    expect(record.filter((each) => inScope(each, { kind: "concern", id: "alpha" })).map((e) => e.seq)).toEqual([1, 2, 3]);
    expect(record.filter((each) => inScope(each, { kind: "actor", id: "alpha", label: "reviewer:alpha#2" })).map((e) => e.seq)).toEqual([3]);
    expect(record.filter((each) => inScope(each, { kind: "merged" }))).toHaveLength(6);
  });

  test("the chips list concerns in first-seen order and actors under the open one", () => {
    expect(concernIds(record)).toEqual(["run-1", "alpha", "beta"]);
    expect(scopedActors(record, { kind: "concern", id: "alpha" })).toEqual(["worker:alpha#1", "reviewer:alpha#2"]);
    expect(scopedActors(record, { kind: "merged" })).toHaveLength(4);
    expect(actorOf("reviewer:alpha#2")).toBe("alpha");
    expect(actorDisplay({ kind: "run", id: "run-1", round: 0 })).toBe("run");
  });
});

describe("kinds", () => {
  test("turn content is the actor speaking and everything else the run", () => {
    expect(record.map(isRunEvent)).toEqual([true, false, false, false, false, true]);
  });

  test("errors are a failed run, a failed concern, or a failed tool result", () => {
    expect(record.map(carriesError)).toEqual([false, false, true, false, false, true]);
    expect(record.filter((each) => matchesKind(each, "errors")).map((e) => e.seq)).toEqual([2, 5]);
  });

  test("the streaming events draw nothing, and search reads the whole entry", () => {
    expect(visible(record[4]!, { kind: "merged" }, "all", "")).toBe(false);
    expect(visible(record[5]!, { kind: "merged" }, "all", "gave up")).toBe(true);
    expect(visible(record[5]!, { kind: "merged" }, "all", "nowhere")).toBe(false);
  });

  test("an unknown status draws neutral", () => {
    expect(tone("verified")).toBe("ok");
    expect(tone("brand-new")).toBe("idle");
  });
});
