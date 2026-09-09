// Every concern joined across progress, eligibility and outcome. A row opens
// the whole concern in the trace — worker, reviewer and merger, every round —
// because what a reader wants from a concern is what happened to it.
import type { ConcernView } from "../generated/views";
import { tone } from "./filters";

export function Concerns({ concerns, onOpen }: { concerns: ConcernView[]; onOpen(id: string): void }) {
  return (
    <section>
      <h2>Concerns</h2>
      {concerns.length === 0 ? (
        <p className="muted">No concerns planned yet.</p>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Concern</th>
                <th>Status</th>
                <th>Reason</th>
                <th>Depends on</th>
                <th>Branch</th>
                <th>Rounds</th>
              </tr>
            </thead>
            <tbody>
              {concerns.map((concern) => (
                <tr key={concern.id} className="openable" onClick={() => onOpen(concern.id)}>
                  <td>
                    <strong>{concern.id}</strong>
                    {!concern.integration_approved && <span className="badge">deferred</span>}
                    <div className="muted">{concern.title}</div>
                  </td>
                  <td>
                    <span className={`dot tone-${tone(concern.status)}`} /> {concern.status}
                  </td>
                  <td className="reason">
                    {concern.reason !== "" ? concern.reason : concern.eligibility_reason}
                    {concern.failure !== null && <div className="error">{concern.failure}</div>}
                  </td>
                  <td className="muted">{concern.dependencies.length > 0 ? concern.dependencies.join(", ") : "—"}</td>
                  <td className="muted mono">{concern.branch ?? "—"}</td>
                  <td>{concern.rounds}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
