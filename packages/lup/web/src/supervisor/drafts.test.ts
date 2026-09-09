import { describe, expect, test } from "bun:test";
import type { MaterialQuestion, PendingQuestionView } from "../generated/views";
import { chosen, draftKey, parseDraft, submission } from "./drafts";

function asked(
  id: string,
  question: Partial<MaterialQuestion> = {},
  standing: Partial<Omit<PendingQuestionView, "question">> = {},
): PendingQuestionView {
  return {
    answered: null,
    asked_by: "worker:alpha#1",
    offer: null,
    ...standing,
    question: {
      allowances: [],
      choices: [],
      closed_choices: false,
      concern_id: "alpha",
      criteria: [],
      id,
      prompt: `question ${id}`,
      recommendation: null,
      ...question,
    },
  };
}

describe("the draft", () => {
  test("is filed by run, so two runs open in one browser never share a form", () => {
    expect(draftKey("run-1")).toBe("lup-supervisor:run-1");
    expect(draftKey("run-1")).not.toBe(draftKey("run-2"));
  });

  test("reads back what was stored, and nothing where the record is missing or unreadable", () => {
    expect(parseDraft(null)).toEqual({});
    expect(parseDraft('{"q1":"yes"}')).toEqual({ q1: "yes" });
    expect(parseDraft("{not json")).toEqual({});
    expect(parseDraft("null")).toEqual({});
    expect(parseDraft('["yes"]')).toEqual({});
  });
});

describe("what a question shows", () => {
  test("the draft, else the offer, else the recommendation, else nothing", () => {
    const both = asked("q", { recommendation: "b" }, { offer: "a" });
    expect(chosen(both, "typed")).toBe("typed");
    expect(chosen(both, undefined)).toBe("a");
    expect(chosen(asked("q", { recommendation: "b" }), undefined)).toBe("b");
    expect(chosen(asked("q"), undefined)).toBe("");
  });
});

describe("a submission", () => {
  test("carries one answer per open question that has a value, in the server's shape", () => {
    const pending = [
      asked("settled", {}, { answered: "done" }),
      asked("typed"),
      asked("offered", {}, { offer: "offer" }),
      asked("recommended", { recommendation: "rec" }),
      asked("blank"),
    ];
    expect(submission(pending, { typed: "yes", settled: "stale" })).toEqual([
      { question_id: "typed", value: "yes" },
      { question_id: "offered", value: "offer" },
      { question_id: "recommended", value: "rec" },
    ]);
  });
});
