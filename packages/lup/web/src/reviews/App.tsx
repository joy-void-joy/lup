import { useEffect, useRef, useState } from "react";
import type { ReviewDecision, ReviewDetail, ReviewInbox } from "../generated/views";
import { answerReview, followInbox, readInbox, readReview, ReviewError, takeToken } from "./api";

function RequestDetails({ detail, onAnswer }: {
  detail: ReviewDetail;
  onAnswer(approved: boolean, note: string): Promise<boolean>;
}) {
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);
  const { summary, question } = detail;

  async function decide(approved: boolean) {
    setSending(true);
    try {
      if (await onAnswer(approved, note)) setNote("");
    } finally {
      setSending(false);
    }
  }

  return (
    <article className="request">
      <header className="request-heading">
        <span className={`state ${summary.state}`}>{summary.state}</span>
        <h2>{summary.operation}</h2>
        <p className="reason">{summary.reason}</p>
        <dl className="metadata">
          <dt>Requester</dt><dd>{summary.requester}</dd>
          <dt>Created</dt><dd>{new Date(summary.created).toLocaleString()}</dd>
          <dt>Rule</dt><dd>{summary.rule || "Unattributed"}</dd>
          <dt>Request</dt><dd><code>{summary.id}</code></dd>
        </dl>
      </header>
      {detail.stale_reason !== "" && <p className="notice" role="status">{detail.stale_reason}</p>}
      {detail.files.map((file) => (
        <section className="file" key={file.path}>
          <h3><span className="state">{file.operation}</span> <code>{file.path}</code></h3>
          {file.unchanged ? <p>This leaves the file unchanged.</p> : <pre className="diff">{file.unified}</pre>}
          <details>
            <summary>Complete before and after</summary>
            <h4>Before</h4>
            {file.before === null ? <p>File absent</p> : <pre>{file.before}</pre>}
            <h4>After</h4>
            {file.after === null ? <p>File absent</p> : <pre>{file.after}</pre>}
          </details>
        </section>
      ))}
      {detail.files.length === 0 && <section>
        <h3>Tool input</h3>
        <pre>{JSON.stringify(question.operation.payload, null, 2)}</pre>
      </section>}
      <details className="record">
        <summary>Complete request record</summary>
        <pre>{JSON.stringify(question, null, 2)}</pre>
      </details>
      {question.answer !== null && <section className="answer-record">
        <h3>{question.answer.approved ? "Approved" : "Rejected"} by {question.answer.principal}</h3>
        {question.answer.note !== "" && <p>{question.answer.note}</p>}
      </section>}
      {summary.state === "pending" && <section className="decision">
        <label htmlFor="review-comment">Comment for the requesting agent</label>
        <textarea id="review-comment" rows={3} value={note} disabled={sending}
          onChange={(event) => setNote(event.target.value)} placeholder="Optional instructions or reason" />
        {!summary.answerable && <p className="notice">This request cannot be answered from this inbox.</p>}
        <div className="actions">
          <button className="approve" type="button"
            disabled={sending || !summary.answerable || detail.stale_reason !== ""}
            onClick={() => void decide(true)}>Approve</button>
          <button className="reject" type="button" disabled={sending || !summary.answerable}
            onClick={() => void decide(false)}>Reject</button>
          {sending && <span role="status">Recording decision…</span>}
        </div>
      </section>}
    </article>
  );
}

export function App() {
  const [token] = useState(takeToken);
  const [inbox, setInbox] = useState<ReviewInbox | null>(null);
  const [selected, setSelected] = useState("");
  const [filter, setFilter] = useState<"pending" | "history">("pending");
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [connection, setConnection] = useState("Connecting…");
  const [error, setError] = useState("");
  const [decision, setDecision] = useState<ReviewDecision | null>(null);
  const [retry, setRetry] = useState(0);
  const rows = inbox?.reviews ?? [];
  const key = selected;
  const current = useRef(key);
  current.current = key;
  const pending = rows.filter((row) => row.state === "pending");
  const visible = rows.filter((row) => filter === "pending" ? row.state === "pending" : row.state !== "pending");

  useEffect(() => {
    if (inbox === null) return;
    setSelected((held) => held || inbox.reviews.find((row) => row.state === "pending")?.key || inbox.reviews[0]?.key || "");
  }, [inbox]);

  useEffect(() => {
    if (token === "") return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function connect() {
      setConnection("Connecting…");
      try {
        const fresh = await readInbox(token, controller.signal);
        if (controller.signal.aborted) return;
        setInbox(fresh);
        for await (const snapshot of followInbox(token, controller.signal)) {
          if (controller.signal.aborted) return;
          setInbox(snapshot);
          setConnection("Live");
        }
        if (!controller.signal.aborted) throw new Error("The connection closed.");
      } catch (failure) {
        if (controller.signal.aborted) return;
        if (failure instanceof ReviewError && [401, 403].includes(failure.status)) {
          setConnection("Access denied. Open the inbox using the operator's launch link.");
          return;
        }
        setConnection(`Reconnecting — ${String(failure)}`);
        timer = setTimeout(() => void connect(), 3000);
      }
    }
    void connect();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [token, retry]);

  useEffect(() => {
    if (key === "" || token === "") return;
    const controller = new AbortController();
    void readReview(key, token, controller.signal).then((fresh) => {
      if (!controller.signal.aborted) setDetail(fresh);
    }).catch((failure: unknown) => {
      if (!controller.signal.aborted) setError(String(failure));
    });
    return () => controller.abort();
  }, [key, token, inbox]);

  function select(wanted: string) {
    setSelected(wanted);
    setError("");
    setDecision(null);
  }

  async function answer(approved: boolean, note: string): Promise<boolean> {
    if (detail === null || detail.summary.key !== key) return false;
    setError("");
    try {
      const settled = await answerReview(key, {
        approved, note, fingerprint: detail.question.fingerprint,
      }, token);
      if (current.current === key) {
        setDetail(settled.review);
        setDecision(settled);
      }
    } catch (failure) {
      setError(String(failure));
      return false;
    }
    try {
      setInbox(await readInbox(token));
    } catch (failure) {
      setError(`The decision was recorded, but refreshing the inbox failed: ${String(failure)}`);
    }
    return true;
  }

  if (token === "") return <main className="access">
    <h1>Review inbox</h1>
    <p>Open the launch link printed by the operator's review inbox command. This tab has no access token.</p>
  </main>;

  return (
    <div className="inbox">
      <header className="masthead">
        <div><p className="eyebrow">Lup · operator review</p><h1>Review inbox</h1></div>
        <div className="connection"><span role="status" className={connection === "Live" ? "live" : "muted"}>{connection}</span>
          <button type="button" onClick={() => setRetry((value) => value + 1)}>Reconnect</button></div>
      </header>
      <div className="workspace">
        <aside className="queue" aria-label="Review requests">
          <div className="filters" aria-label="Request filter">
            <button type="button" aria-pressed={filter === "pending"} onClick={() => setFilter("pending")}>Pending ({pending.length})</button>
            <button type="button" aria-pressed={filter === "history"} onClick={() => setFilter("history")}>History ({rows.length - pending.length})</button>
          </div>
          {inbox !== null && visible.length === 0 && <p className="empty">{filter === "pending" ? "No requests waiting. This page will update when one arrives." : "No answered requests yet."}</p>}
          {visible.map((row) => <button type="button" className={`queue-row ${key === row.key ? "selected" : ""}`} key={row.key}
            aria-current={key === row.key ? "true" : undefined} onClick={() => select(row.key)}>
            <span className="row-top"><span className={`state ${row.state}`}>{row.state}</span><time>{new Date(row.created).toLocaleTimeString()}</time></span>
            <strong>{row.operation}</strong><span>{row.reason}</span><small>{row.requester}</small>
            <small className="root-path">{inbox?.roots.find((root) => root.id === row.root_id)?.path}</small>
          </button>)}
          <details className="roots"><summary>Watched checkouts ({inbox?.roots.length ?? 0})</summary>
            {inbox?.roots.map((root) => <p key={root.id}><code>{root.path}</code></p>)}</details>
        </aside>
        <main className="stage">
          {inbox?.errors.map((issue) => <p className="notice" role="alert" key={issue.root}>{issue.root}: {issue.message}</p>)}
          {error !== "" && <p className="error" role="alert">{error}</p>}
          {decision !== null && <div className="decision-receipt" role="status">
            <strong>{decision.review.summary.state === "approved" ? "Approval recorded." : "Decision recorded."}</strong>
            <p>{decision.notification.detail}</p>
          </div>}
          {key === "" ? <section className="welcome"><h2>Ready for the next request</h2><p>Keep this tab open. New requests appear automatically, with their complete changes and tool inputs.</p></section>
            : detail?.summary.key === key ? <RequestDetails key={key} detail={detail} onAnswer={answer} />
            : <p className="empty" role="status">Loading request…</p>}
        </main>
      </div>
    </div>
  );
}
