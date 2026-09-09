// The run's open questions, grouped by concern, groups still waiting sorted
// ahead of settled ones and settled ones folded to one-line records. A draft
// survives a reload in this browser, so a half-answered form is not lost to
// a stream reconnecting under it.
import { useEffect, useMemo, useState } from "react";
import type { PendingQuestionView, SupervisorState } from "../generated/views";

function draftKey(runId: string): string {
  return `lup-supervisor:${runId}`;
}

function readDraft(runId: string): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(draftKey(runId)) ?? "{}") as Record<string, string>;
  } catch {
    return {};
  }
}

function cut(text: string, limit: number): string {
  return text.length <= limit ? text : `${text.slice(0, limit)}…`;
}

/** What the form would submit for one question: the draft, else the offer, else the recommendation. */
function chosen(view: PendingQuestionView, draft: Record<string, string>): string {
  return draft[view.question.id] ?? view.offer ?? view.question.recommendation ?? "";
}

function Meta({ view }: { view: PendingQuestionView }) {
  const question = view.question;
  return (
    <div className="q-meta">
      <span className="qid">{question.id}</span>
      {question.allowances.length > 0 && (
        <span className="chip tone-warn" title="Edit gates an answer here grants to this concern's sessions">
          grants: {question.allowances.join(", ")}
        </span>
      )}
      {question.criteria.length > 0 && (
        <span className="chip" title="The lost criteria this re-check is about">
          criteria: {question.criteria.join(", ")}
        </span>
      )}
    </div>
  );
}

function Question({
  view,
  draft,
  onChange,
}: {
  view: PendingQuestionView;
  draft: Record<string, string>;
  onChange(id: string, value: string): void;
}) {
  const question = view.question;
  if (view.answered !== null) {
    // A settled question is record, not work. One line keeps a long run's
    // decisions scannable; opening it shows the exchange whole.
    return (
      <details className="answered">
        <summary>
          {cut(question.prompt, 140)} <span className="muted">— answered</span>{" "}
          <strong>{cut(view.answered, 60)}</strong> <span className="qid">{question.id}</span>
        </summary>
        <div className="prompt">{question.prompt}</div>
        <p className="muted">
          Answered <strong>{view.answered}</strong>
        </p>
      </details>
    );
  }
  const value = chosen(view, draft);
  return (
    <>
      <div className="prompt">
        {question.prompt}
        {view.offer !== null && <span className="badge">offered</span>}
      </div>
      <Meta view={view} />
      {question.choices.length > 0 ? (
        question.choices.map((choice) => (
          <label key={choice} className="choice">
            <input
              type="radio"
              name={question.id}
              value={choice}
              checked={value === choice}
              onChange={() => onChange(question.id, choice)}
            />
            <span>
              {choice}
              {question.recommendation === choice && <span className="badge">recommended</span>}
            </span>
          </label>
        ))
      ) : (
        <input
          type="text"
          value={value}
          autoComplete="off"
          onChange={(event) => onChange(question.id, event.target.value)}
        />
      )}
    </>
  );
}

export function Questions({
  state,
  onSubmit,
  onPark,
  onResume,
  error,
}: {
  state: SupervisorState;
  onSubmit(answers: { question_id: string; value: string }[]): Promise<boolean>;
  onPark(): void;
  onResume(): void;
  error: string;
}) {
  const [draft, setDraft] = useState<Record<string, string>>(() => readDraft(state.run_id));
  const [copied, setCopied] = useState(false);
  // The draft is re-read only when the question set itself moved: retyping is
  // not a set change, and a reset under a keystroke would lose the word.
  const shape = JSON.stringify(state.pending.map((view) => [view.question.id, view.answered, view.offer]));
  useEffect(() => {
    setDraft(readDraft(state.run_id));
  }, [state.run_id, shape]);

  const outstanding = state.pending.filter((view) => view.answered === null);
  const grouped = useMemo(() => {
    const groups = new Map<string, PendingQuestionView[]>();
    for (const view of state.pending) {
      const concern = view.question.concern_id;
      groups.set(concern, [...(groups.get(concern) ?? []), view]);
    }
    // Groups still waiting on a decision come first: the section exists to be
    // answered, and the answered record should not bury the ask.
    const waiting = (views: PendingQuestionView[]) => views.some((view) => view.answered === null);
    return [...groups.entries()].sort((a, b) => Number(waiting(b[1])) - Number(waiting(a[1])));
  }, [state.pending]);

  if (state.pending.length === 0) return null;

  function changed(id: string, value: string) {
    const next = { ...draft, [id]: value };
    setDraft(next);
    localStorage.setItem(draftKey(state.run_id), JSON.stringify(next));
  }

  async function submitted() {
    const answers = outstanding
      .map((view) => ({ question_id: view.question.id, value: chosen(view, draft) }))
      .filter((answer) => answer.value !== "");
    if (await onSubmit(answers)) localStorage.removeItem(draftKey(state.run_id));
  }

  async function copyRecipe() {
    await navigator.clipboard.writeText(state.rerun_recipe);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  return (
    <section className={outstanding.length > 0 ? "questions attention" : "questions"}>
      <div className="section-head">
        <h2>Pending questions</h2>
        <span className="muted">
          {outstanding.length > 0 ? `${outstanding.length} waiting on you` : "all answered"}
        </span>
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submitted();
        }}
      >
        {grouped.map(([concern, views]) => (
          <fieldset key={concern}>
            <legend>{concern}</legend>
            {views.map((view) => (
              <Question key={view.question.id} view={view} draft={draft} onChange={changed} />
            ))}
          </fieldset>
        ))}
        {outstanding.length > 0 && (
          <div className="actions">
            <button className="primary" type="submit">
              Submit answers
            </button>
            <button type="button" onClick={onPark}>
              Park run
            </button>
            {!state.live && (
              <button type="button" onClick={onResume}>
                Resume run
              </button>
            )}
          </div>
        )}
      </form>
      {error !== "" && <p className="error">{error}</p>}
      {outstanding.length > 0 && (
        <div className="recipe-row">
          <code>{state.rerun_recipe}</code>
          <button type="button" className="small" onClick={() => void copyRecipe()}>
            {copied ? "copied" : "copy"}
          </button>
        </div>
      )}
    </section>
  );
}
