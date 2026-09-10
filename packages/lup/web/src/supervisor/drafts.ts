// What the answer form keeps between renders and reloads, and what it sends:
// the key a browser files a run's draft under, the tolerance for a record it
// cannot read, the value a question shows, and the payload the server takes.
// Pure over the view types, so `bun test` holds them still.
import type { PendingQuestionView, QuestionAnswer } from "../generated/views";

/** The record a browser keeps for one run: question id to the value typed for it. */
export type Draft = Record<string, string>;

export function draftKey(runId: string): string {
  return `lup-supervisor:${runId}`;
}

/** A stored draft, or an empty one where nothing was stored or what was cannot be read. */
export function parseDraft(stored: string | null): Draft {
  try {
    const parsed: unknown = JSON.parse(stored ?? "{}");
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed) ? (parsed as Draft) : {};
  } catch {
    return {};
  }
}

/** What the form shows and would submit for one question: the draft, else the offer, else the recommendation. */
export function chosen(view: PendingQuestionView, draft: string | undefined): string {
  return draft ?? view.offer ?? view.question.recommendation ?? "";
}

/** One answer per question still open that has a value; a settled question is never re-sent. */
export function submission(pending: PendingQuestionView[], draft: Draft): QuestionAnswer[] {
  return pending
    .filter((view) => view.answered === null)
    .map((view) => ({ question_id: view.question.id, value: chosen(view, draft[view.question.id]) }))
    .filter((answer) => answer.value !== "");
}
