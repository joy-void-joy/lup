import type { ReviewView } from "../generated/views";

export function Review({ review }: { review: ReviewView }) {
  return (
    <section>
      <h2>Review branch</h2>
      <p>
        <code>{review.review_branch}</code>
      </p>
      <div className="table-scroll">
        <table>
          <tbody>
            {review.verification.map((check) => (
              <tr key={check.name}>
                <td>{check.name}</td>
                <td className={check.passed ? "" : "error"}>{check.passed ? "passed" : "failed"}</td>
                <td className="muted">exit {check.exit_code}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">
        This branch is yours to land. What is recorded here is mechanical — whether the merged
        concerns are jointly right is read from the trace above.
      </p>
    </section>
  );
}

export function Failures({ failures }: { failures: string[] }) {
  if (failures.length === 0) return null;
  return (
    <section>
      <h2>Failures</h2>
      {failures.map((failure, index) => (
        <p key={index} className="error">
          {failure}
        </p>
      ))}
    </section>
  );
}
