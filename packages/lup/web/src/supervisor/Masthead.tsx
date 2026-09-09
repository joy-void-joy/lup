// The run's name and where it stands: the phase, the operator-facing status,
// the stream's connection, the last event, a tally of concerns by status, and
// the phase strip with the current one marked.
import type { SupervisorState } from "../generated/views";
import { tone } from "./filters";

export type Connection = { label: string; tone: "" | "ok" | "danger" };

function statusTone(status: SupervisorState["status"]): string {
  switch (status) {
    case "failed":
      return "danger";
    case "complete":
      return "ok";
    case "awaiting_answers":
    case "aborted":
      return "warn";
    default:
      return "";
  }
}

export function Masthead({
  state,
  connection,
  lastEvent,
}: {
  state: SupervisorState | null;
  connection: Connection;
  lastEvent: string;
}) {
  const counts = new Map<string, number>();
  for (const concern of state?.concerns ?? []) {
    counts.set(concern.status, (counts.get(concern.status) ?? 0) + 1);
  }
  // The two terminal failure phases sit in the enum after `complete`; showing
  // them as forever-unreached steps would read as work left.
  const strip = (state?.phases ?? []).filter(
    (phase) => !["aborted", "failed"].includes(phase) || phase === state?.phase,
  );
  const current = state === null ? -1 : strip.indexOf(state.phase);
  return (
    <header className="masthead">
      <p className="eyebrow">Resolver supervision</p>
      <h1>{state?.run_id ?? "—"}</h1>
      <div className="pills">
        <span className="pill strong">{state?.phase ?? "—"}</span>
        <span className={`pill ${state === null ? "" : statusTone(state.status)}`}>
          {state === null ? "—" : state.status.replaceAll("_", " ")}
        </span>
        <span className={`pill ${connection.tone}`}>{connection.label}</span>
        <span className="pill">{lastEvent}</span>
      </div>
      <div className="tally-bar">
        {[...counts.entries()].map(([status, count]) => (
          <span
            key={status}
            className={`seg tone-${tone(status)}`}
            style={{ flex: count }}
            title={`${status}: ${count}`}
          />
        ))}
      </div>
      <p className="progress-line">{state?.progress_line ?? ""}</p>
      <div className="chips phase-chips">
        {strip.map((phase, index) => (
          <span
            key={phase}
            className={`chip ${phase === state?.phase ? "current" : index < current ? "done" : ""}`}
          >
            {phase}
          </span>
        ))}
      </div>
      {state !== null && !state.live && (
        <p className="banner">This run is not moving. Answers you submit are held for its next run.</p>
      )}
    </header>
  );
}
