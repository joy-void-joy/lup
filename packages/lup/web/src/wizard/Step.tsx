// One step as a card: its guide, its external link, its form or its rows,
// and whatever live check and undo it declares. A step the server withholds
// is drawn with its reason and no form, so the page never offers what a
// request would then be refused for.
import { useState } from "react";
import type { Row, RowAct, RowRequest, StepAnswers, StepView } from "../generated/views";

// lup: defer: the form is controlled inputs; TanStack Form, the default
// answer for form-heavy UI, waits on `bun add @tanstack/react-form`, which
// the policy asks about — take it when the wizard's forms outgrow two fields
function Fields({ step, onRun }: { step: StepView; onRun(answers: StepAnswers): void }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const answers = (): StepAnswers => ({
    answers: step.fields.map((field) => ({ key: field.key, value: values[field.key] ?? "" })),
  });
  return (
    <div>
      {step.fields.map((field) => (
        <div key={field.key}>
          <label>
            {field.label}
            <input
              type={field.secret ? "password" : "text"}
              placeholder={field.placeholder}
              value={values[field.key] ?? ""}
              onChange={(event) => setValues({ ...values, [field.key]: event.target.value })}
            />
          </label>
        </div>
      ))}
      <div className="actions">
        <button type="button" className="go" onClick={() => onRun(answers())}>
          {step.submit !== "" ? step.submit : "Save"}
        </button>
      </div>
    </div>
  );
}

// An act that asks for a value grows its input in place, so what is being
// confirmed stays visible beside the prompt. Signing in is the one act
// performed differently: the terminal opens a browser where it runs, and the
// page streams the same window over a socket to whoever is reading — so the
// button comes from the row like every other, and only where it goes differs.
function RowLine({
  row,
  onAct,
  onStream,
}: {
  row: Row;
  onAct(request: RowRequest): void;
  onStream(path: string): void;
}) {
  const [asking, setAsking] = useState<RowAct | null>(null);
  const [answer, setAnswer] = useState("");

  function chosen(act: RowAct) {
    if (act.slug === "sign-in" && row.stream !== "") {
      onStream(row.stream);
      return;
    }
    if (act.asks === "") {
      onAct({ row: row.name, act: act.slug, answer: "" });
      return;
    }
    setAsking(act);
    setAnswer("");
  }

  return (
    <div className="row">
      <span className="name">{row.name}</span>
      <span className="state">{row.detail}</span>
      {row.acts.map((act) => (
        <button key={act.slug} type="button" title={act.consequence} onClick={() => chosen(act)}>
          {act.label}
        </button>
      ))}
      {asking !== null && (
        <span>
          <input
            autoFocus
            placeholder={asking.asks}
            value={answer}
            style={{ maxWidth: asking.destructive ? "12rem" : "24rem" }}
            onChange={(event) => setAnswer(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") onAct({ row: row.name, act: asking.slug, answer });
            }}
          />
          <button type="button" onClick={() => onAct({ row: row.name, act: asking.slug, answer })}>
            {asking.destructive ? "Confirm" : "Save"}
          </button>
        </span>
      )}
    </div>
  );
}

export function Step({
  step,
  onRun,
  onTest,
  onReset,
  onAct,
  onStream,
}: {
  step: StepView;
  onRun(answers: StepAnswers): void;
  onTest(): void;
  onReset(): void;
  onAct(request: RowRequest): void;
  onStream(path: string): void;
}) {
  return (
    <section className="step">
      <h2>
        <span className={step.standing.done ? "mark done" : "mark"}>
          {step.standing.done ? "✓" : "○"}
        </span>
        <span>{step.title}</span>
        <span className="detail">{step.standing.detail}</span>
      </h2>
      {step.blurb !== "" && <p className="blurb">{step.blurb}</p>}
      {/* Prose written for a terminal usually numbers itself, so a step says
          whether its guide wants numbering rather than getting it regardless. */}
      {step.guide.length > 0 &&
        (step.numbered ? (
          <ol className="guide">
            {step.guide.map((line, index) => (
              <li key={index}>{line}</li>
            ))}
          </ol>
        ) : (
          <div className="guide-lines">
            {step.guide.map((line, index) => (
              <p key={index}>{line}</p>
            ))}
          </div>
        ))}
      {step.opens !== "" && (
        <a className="ext" href={step.opens} target="_blank" rel="noreferrer">
          Open that page →
        </a>
      )}
      {step.kind === "rows" &&
        step.rows.map((row) => (
          <RowLine key={row.name} row={row} onAct={onAct} onStream={onStream} />
        ))}
      {!step.standing.offered
        ? step.standing.blocked !== "" && <p className="blocked">{step.standing.blocked}</p>
        : step.fields.length > 0 && <Fields step={step} onRun={onRun} />}
      {(step.tests !== "" || step.undoes !== "") && (
        <div className="actions">
          {step.tests !== "" && (
            <button type="button" onClick={onTest}>
              {step.tests}
            </button>
          )}
          {step.undoes !== "" && (
            <button type="button" onClick={onReset}>
              {step.undoes}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
