// The wizard as a page: a scope selector, a card per step, and a status line.
// It knows no step by name — it draws whatever the server declares — so a
// project adding a step writes a declaration and nothing here changes.
import { useCallback, useEffect, useState } from "react";
import type { StepReply, WizardView } from "../generated/views";
import {
  actOnRow,
  makeScope,
  readView,
  resetStep,
  runStep,
  scopeQuery,
  testStep,
} from "./api";
import { Scopes } from "./Scopes";
import { Screen } from "./Screen";
import { Step } from "./Step";

export type Status = { text: string; ok: boolean | null };

function initialScope(): string {
  return new URLSearchParams(window.location.search).get("scope") ?? "";
}

export function App() {
  const [scope, setScope] = useState(initialScope);
  const [view, setView] = useState<WizardView | null>(null);
  const [status, setStatus] = useState<Status>({ text: "", ok: null });
  const [stream, setStream] = useState<string | null>(null);

  const refresh = useCallback(async (which: string) => {
    try {
      setView(await readView(which));
    } catch (error) {
      setStatus({ text: String(error), ok: false });
    }
  }, []);

  useEffect(() => {
    void refresh(scope);
  }, [refresh, scope]);

  useEffect(() => {
    // The scope rides in the URL, so a reloaded tab and a shared link open on
    // the same one.
    const query = scopeQuery(scope);
    window.history.replaceState(null, "", query === "" ? window.location.pathname : query);
  }, [scope]);

  useEffect(() => {
    if (view !== null) document.title = view.title;
  }, [view]);

  // Every reply carries the page as it stands afterwards, so nothing here
  // renders from what it assumed happened.
  function applied(reply: StepReply) {
    setStatus({ text: reply.outcome.message, ok: reply.outcome.ok });
    if (reply.view.chosen !== "") setScope(reply.view.chosen);
    setView(reply.view);
  }

  async function perform(saying: string, request: () => Promise<StepReply>) {
    setStatus({ text: saying, ok: null });
    try {
      applied(await request());
    } catch (error) {
      setStatus({ text: String(error), ok: false });
    }
  }

  const say = useCallback((text: string, ok: boolean | null) => setStatus({ text, ok }), []);
  const streamed = useCallback(() => {
    setStream(null);
    void refresh(scope);
  }, [refresh, scope]);

  return (
    <>
      <h1>{view?.title ?? "Setup"}</h1>
      <p className="lede">{view?.lede ?? ""}</p>
      {view !== null && (
        <Scopes
          view={view}
          onChoose={(name) => setScope(name)}
          onMake={(name) => void perform("Making…", () => makeScope({ name }))}
        />
      )}
      {view !== null && view.notice !== "" && <div className="notice">{view.notice}</div>}
      {view?.steps.map((step) => (
        <Step
          key={step.slug}
          step={step}
          onRun={(answers) => void perform("Working…", () => runStep(scope, step.slug, answers))}
          onTest={() => void perform("Checking…", () => testStep(scope, step.slug))}
          onReset={() => void perform("Clearing…", () => resetStep(scope, step.slug))}
          onAct={(request) => void perform("Working…", () => actOnRow(scope, step.slug, request))}
          onStream={(path) => setStream(path)}
        />
      ))}
      {stream !== null && <Screen path={stream} say={say} onDone={streamed} />}
      <div id="status" className={status.ok === null ? "" : status.ok ? "ok" : "bad"}>
        {status.text}
      </div>
    </>
  );
}
