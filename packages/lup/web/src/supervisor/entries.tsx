// One journal entry drawn. A run event and a block are rendered by the same
// component on purpose: the merged view is the record unfiltered, so a phase
// move has to sit in the same column as the turn that caused it or the
// ordering buys nothing.
//
// Every member of both unions gets an arm, including the two that render
// nothing. `block_started` and `block_completed` are the streaming granularity
// of content `message_completed` already carries whole, so drawing them would
// show every block twice; saying that here is what separates a deliberate
// silence from an event that fell through. An event this page has never heard
// of is drawn raw rather than dropped — a trace that quietly omits what it
// cannot name is not a record — and a test reads the arms back out of this
// file, so a new event fails there rather than in a trace somebody reads.
import type { ReactNode } from "react";
import type { AnyTurnBlock, JournalEntry } from "../generated/views";
import { actorDisplay } from "./filters";

// A body is shown whole once someone asks for it. Until then it is cut at a
// length that still says what the block was, because a single file read is
// longer than every other entry in the run put together and renders the
// trace unreadable exactly where it gets interesting.
const BODY_LIMIT = 1200;

export type Expand = { expanded: ReadonlySet<string>; onExpand(name: string): void };

const short = (sha: string): string => sha.slice(0, 12);

function Body({
  text,
  name,
  className,
  expand,
}: {
  text: string;
  name: string;
  className: string;
  expand: Expand;
}) {
  if (text.length <= BODY_LIMIT || expand.expanded.has(name)) {
    return <div className={className}>{text}</div>;
  }
  return (
    <>
      <div className={className}>{text.slice(0, BODY_LIMIT)}…</div>
      <button type="button" className="expand" onClick={() => expand.onExpand(name)}>
        show {text.length - BODY_LIMIT} more characters
      </button>
    </>
  );
}

function Block({ block, name, expand }: { block: AnyTurnBlock; name: string; expand: Expand }) {
  switch (block.type) {
    case "text":
      return <Body text={block.text} name={name} className="say" expand={expand} />;
    case "thinking":
      return block.redacted ? (
        <div className="think">[redacted reasoning]</div>
      ) : (
        <Body text={block.thinking} name={name} className="think" expand={expand} />
      );
    case "tool_call":
      return (
        <div className="call">
          <strong>{block.name}</strong>
          <Body
            text={JSON.stringify(block.arguments, null, 2)}
            name={name}
            className="pre-body"
            expand={expand}
          />
        </div>
      );
    case "tool_result":
      return (
        <div className={block.is_error ? "result bad" : "result"}>
          <Body text={block.content} name={name} className="pre-body" expand={expand} />
        </div>
      );
    default:
      return <div className="say muted">[{String((block as { type: string }).type)}]</div>;
  }
}

function Note({ stamp, who, children, className = "entry note" }: { stamp: string; who: string; children: ReactNode; className?: string }) {
  return (
    <div className={className}>
      <div className="entry-head">
        <span className="muted">{stamp}</span> <span className="pill">{who}</span>
      </div>
      {children}
    </div>
  );
}

function Boundary({ stamp, who, text }: { stamp: string; who: string; text: string }) {
  return (
    <div className="boundary">
      <span>{stamp}</span>
      <span>{who}</span>
      <span>{text}</span>
    </div>
  );
}

function Posted({ stamp, label, text }: { stamp: string; label: string; text: string }) {
  return (
    <div className="entry note">
      <div className="entry-head">
        <span className="muted">{stamp}</span> <span className="pill strong">{label}</span>
      </div>
      <div className="say">{text}</div>
    </div>
  );
}

export function Entry({ entry, expand }: { entry: JournalEntry; expand: Expand }) {
  const event = entry.event;
  const stamp = new Date(entry.at).toLocaleTimeString();
  const who = actorDisplay(entry.actor);
  switch (event.type) {
    case "message_completed":
      return (
        <Note stamp={stamp} who={who} className="entry">
          {event.message.blocks.map((block, index) => (
            <Block key={index} block={block} name={`${entry.seq}:${index}`} expand={expand} />
          ))}
        </Note>
      );
    case "turn_started":
      return <Boundary stamp={stamp} who={who} text="turn started" />;
    case "turn_completed":
      return <Boundary stamp={stamp} who={who} text="turn completed" />;
    case "block_started":
    case "block_completed":
      return null;
    case "phase_changed":
      return (
        <Note stamp={stamp} who={who}>
          <div>
            phase → <strong>{event.phase}</strong>
          </div>
        </Note>
      );
    case "concern_progressed":
      return (
        <Note stamp={stamp} who={who}>
          <div>
            <strong>{event.progress.concern_id}</strong> → {event.progress.status} {event.progress.reason}
          </div>
        </Note>
      );
    case "question_asked":
      return (
        <Note stamp={stamp} who={who}>
          <div>asked: {event.question.prompt}</div>
        </Note>
      );
    case "answer_settled":
      return (
        <Note stamp={stamp} who={who}>
          <div>
            answered {event.answer.question_id} = {event.answer.value}{" "}
            <span className="muted">({event.door})</span>
          </div>
        </Note>
      );
    case "message_posted":
      return <Posted stamp={stamp} label={`${event.door} ${event.redirect ? "redirected" : "→"} ${who}`} text={event.text} />;
    case "message_outstanding":
      return (
        <Posted
          stamp={stamp}
          label={`${event.door} ${event.redirect ? "redirect" : "message"} unread by ${who}`}
          text={event.text}
        />
      );
    case "join_planned":
      return (
        <Note stamp={stamp} who={who}>
          <div>
            merging {event.tips.length} parent(s)
            {event.carried.length > 0 &&
              `; ${event.carried.length} already inside one: ${event.carried
                .map((item) => `${short(item.commit)} in ${short(item.inside)}`)
                .join(", ")}`}
          </div>
        </Note>
      );
    case "join_rendered":
      return (
        <Note stamp={stamp} who={who}>
          <div>
            generated artifacts settled <span className="mono">{short(event.parent)}</span> — no merger turn
          </div>
        </Note>
      );
    case "join_completed":
      return (
        <Note stamp={stamp} who={who}>
          <div>
            joined <span className="mono">{short(event.parent)}</span>
            {event.conflicted && " (conflicted)"}
            {event.broke.length > 0 && ` — broke: ${event.broke.join(", ")}`}
          </div>
        </Note>
      );
    case "join_audit":
      return (
        <Note stamp={stamp} who={who}>
          <div>
            audited {event.parents.length} parent(s), {event.outstanding} outstanding
          </div>
        </Note>
      );
    case "review_residual":
      return (
        <Note stamp={stamp} who={who}>
          <div>
            residual beside round {event.round}&apos;s acceptance: {event.residual.join("; ")}
          </div>
        </Note>
      );
    case "criteria_carried":
      return (
        <Note stamp={stamp} who={who}>
          <div>
            <strong>{event.concern_id}</strong> round {event.round} was accepted with{" "}
            {event.criteria.join(", ")} left unmet, carried on the human&apos;s word
          </div>
        </Note>
      );
    case "foreign_criteria":
      return (
        <Note stamp={stamp} who={who}>
          <div>
            <strong>{event.concern_id}</strong> round {event.round} credited ids this concern never
            declared: {event.labels.join(", ")} — recorded, verdict unaffected
          </div>
        </Note>
      );
    case "verification_failed":
      return (
        <Note stamp={stamp} who={who}>
          <div className="error">
            <strong>{event.concern_id}</strong> round {event.round}: {event.name} exited {event.exit_code}
          </div>
          {event.output !== "" && (
            <Body text={event.output} name={`${entry.seq}:verification`} className="pre-body" expand={expand} />
          )}
        </Note>
      );
    case "recheck_repeated":
      return (
        <Note stamp={stamp} who={who}>
          <div>
            <strong>{event.concern_id}</strong> reproduced a settled finding ({event.criteria.join(", ")}) at{" "}
            {event.occasion}
          </div>
        </Note>
      );
    case "recheck_reused":
      return (
        <Note stamp={stamp} who={who}>
          <div>
            took {event.concerns.length} re-check{event.concerns.length === 1 ? "" : "s"} already run against{" "}
            <span className="mono">{short(event.commit)}</span>: {event.concerns.join(", ")}
          </div>
        </Note>
      );
    case "base_refreshed":
      return (
        <Note stamp={stamp} who={who}>
          <div>
            {event.commit === event.was ? (
              <>
                base unchanged on <strong>{event.branch}</strong>
                {event.reason !== "" && ` — ${event.reason}`}
                {event.conflicts.length > 0 && ` (${event.conflicts.join(", ")})`}
              </>
            ) : (
              <>
                base refreshed onto <strong>{event.branch}</strong>:{" "}
                <span className="mono">{short(event.was)}</span> → <span className="mono">{short(event.commit)}</span>
              </>
            )}
          </div>
        </Note>
      );
    case "lease_refreshed":
      return (
        <Note stamp={stamp} who={who}>
          <div>
            {event.applied ? (
              <>
                <strong>{event.concern_id}</strong> took the refreshed base{" "}
                <span className="mono">{short(event.commit)}</span>
              </>
            ) : (
              <>
                <strong>{event.concern_id}</strong> stayed where it was
                {event.reason !== "" && ` — ${event.reason}`}
                {event.conflicts.length > 0 && ` (conflicts: ${event.conflicts.join(", ")})`}
                {event.uncommitted.length > 0 && ` (uncommitted: ${event.uncommitted.join(", ")})`}
              </>
            )}
          </div>
        </Note>
      );
    case "lease_drift":
      return (
        <Note stamp={stamp} who={who}>
          <div>
            <strong>{event.concern_id}</strong> left work on its branch: recorded{" "}
            <span className="mono">{short(event.expected)}</span>, found{" "}
            <span className="mono">{short(event.found)}</span>
          </div>
        </Note>
      );
    case "run_failed":
      return (
        <Note stamp={stamp} who={who}>
          <div className="error">{event.reason}</div>
        </Note>
      );
    default:
      return (
        <Note stamp={stamp} who={who} className="entry note unknown">
          <Body
            text={JSON.stringify(event, null, 2)}
            name={`${entry.seq}:raw`}
            className="pre-body"
            expand={expand}
          />
        </Note>
      );
  }
}
