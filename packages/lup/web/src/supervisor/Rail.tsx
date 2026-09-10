// Every run recorded under the state root, most recently active first — an
// unreadable one as its own row rather than hidden, and the one open marked.
import type { RunSummary } from "../generated/views";

export function Rail({
  runs,
  current,
  onSelect,
}: {
  runs: RunSummary[];
  current: string | null;
  onSelect(runId: string): void;
}) {
  return (
    <aside className="rail">
      <div className="rail-head">Runs</div>
      <nav id="run-list">
        {runs.map((run) => (
          <button
            key={run.run_id}
            type="button"
            className={run.run_id === current ? "run-item current" : "run-item"}
            onClick={() => onSelect(run.run_id)}
          >
            <span className="run-name">{run.run_id}</span>
            {run.live && <span className="dot pulse" title="moving" />}
            {run.unreadable && <span className="dot tone-danger" title={run.detail} />}
            {run.pending_questions > 0 && (
              <span className="count" title="unanswered questions">
                {run.pending_questions}
              </span>
            )}
            <span className="run-meta">
              {run.unreadable
                ? "unreadable"
                : `${run.phase ?? "—"} · ${run.concerns} concern${run.concerns === 1 ? "" : "s"}`}
            </span>
          </button>
        ))}
      </nav>
      {runs.length === 0 && <p className="muted">No runs recorded under .lup/resolve.</p>}
    </aside>
  );
}
