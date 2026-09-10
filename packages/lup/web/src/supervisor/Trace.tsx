// The record, followed as it grows: every entry the filters admit, drawn in
// order, virtualised so a long run costs what is on screen. Following means
// the newest entry is what the reader wants to see; scrolling up is how they
// say otherwise, so arrivals stop moving the view and are counted into a chip
// instead of yanking them back down.
import { useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { JournalEntry } from "../generated/views";
import { readEarlier, sendMessage } from "./api";
import { Entry, type Expand } from "./entries";
import { actorOf, concernIds, scopedActors, visible, type KindFilter, type Scope } from "./filters";

const EARLIER_PAGE = 200;

function Chip({ text, active, onClick }: { text: string; active: boolean; onClick(): void }) {
  return (
    <button type="button" className={active ? "chip current" : "chip"} onClick={onClick}>
      {text}
    </button>
  );
}

export function Trace({
  runId,
  entries,
  scope,
  onScope,
  onEarlier,
}: {
  runId: string;
  entries: JournalEntry[];
  scope: Scope;
  onScope(scope: Scope): void;
  onEarlier(page: JournalEntry[]): void;
}) {
  const [typed, setTyped] = useState("");
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<KindFilter>("all");
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set());
  const [follow, setFollow] = useState(true);
  const [unseen, setUnseen] = useState(0);
  const [exhausted, setExhausted] = useState(false);
  const [message, setMessage] = useState("");
  const [messageError, setMessageError] = useState("");
  const body = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(typed.trim().toLowerCase()), 150);
    return () => window.clearTimeout(timer);
  }, [typed]);

  const shown = useMemo(
    () => entries.filter((entry) => visible(entry, scope, kind, query)),
    [entries, scope, kind, query],
  );
  const virtualizer = useVirtualizer({
    count: shown.length,
    getScrollElement: () => body.current,
    estimateSize: () => 72,
    overscan: 8,
    getItemKey: (index) => shown[index]?.seq ?? index,
  });

  // Arrivals while following scroll the view; while not, they are counted.
  const lastCount = useRef(0);
  useEffect(() => {
    const grew = shown.length - lastCount.current;
    lastCount.current = shown.length;
    if (shown.length === 0) return;
    if (follow) {
      virtualizer.scrollToIndex(shown.length - 1, { align: "end" });
    } else if (grew > 0) {
      setUnseen((held) => held + grew);
    }
  }, [shown.length, follow, virtualizer]);

  useEffect(() => {
    if (entries.length > 0 && entries[0]?.seq === 0) setExhausted(true);
  }, [entries]);

  const expand: Expand = {
    expanded,
    onExpand: (name) => setExpanded((held) => new Set([...held, name])),
  };

  function scrolled() {
    const element = body.current;
    if (element === null) return;
    const atBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 48;
    if (atBottom && !follow) {
      setFollow(true);
      setUnseen(0);
    } else if (!atBottom && follow) {
      setFollow(false);
    }
  }

  function resumeFollowing() {
    setFollow(true);
    setUnseen(0);
    if (shown.length > 0) virtualizer.scrollToIndex(shown.length - 1, { align: "end" });
  }

  async function loadEarlier() {
    const first = entries[0];
    if (exhausted || first === undefined) return;
    const page = await readEarlier(runId, first.seq, EARLIER_PAGE);
    if (page.length < EARLIER_PAGE) setExhausted(true);
    if (page.length === 0) return;
    setFollow(false);
    onEarlier(page);
    // The entry that was first stays in view: the page lands above it.
    const kept = page.filter((entry) => visible(entry, scope, kind, query)).length;
    window.requestAnimationFrame(() => virtualizer.scrollToIndex(kept, { align: "start" }));
  }

  // A message reaches one actor or all of them; the mailbox addresses an
  // exact label or broadcasts, and has nothing in between. A concern scope
  // therefore says so rather than silently picking one of its actors.
  const target = scope.kind === "actor" ? scope.label : "";

  async function say(redirect: boolean) {
    if (message.trim() === "") return;
    setMessageError("");
    try {
      await sendMessage(runId, { text: message, to_actor: target, in_reply_to: "", redirect });
      setMessage("");
    } catch (error) {
      setMessageError(String(error));
    }
  }

  const concerns = concernIds(entries);
  const actors = scopedActors(entries, scope);

  return (
    <section>
      <h2>Trace</h2>
      <div className="trace-controls">
        <input
          type="search"
          placeholder="Search the record…"
          autoComplete="off"
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
        />
        <select
          title="Which entries to show"
          value={kind}
          onChange={(event) => setKind(event.target.value as KindFilter)}
        >
          <option value="all">everything</option>
          <option value="notes">run events only</option>
          <option value="errors">errors only</option>
        </select>
        <button
          type="button"
          className="small"
          disabled={exhausted || entries.length === 0}
          onClick={() => void loadEarlier()}
        >
          {exhausted ? "at the start of the record" : "load earlier record"}
        </button>
      </div>
      <div className="chip-row">
        <span className="muted">Scope</span>
        <div className="chips">
          <Chip text="merged" active={scope.kind === "merged"} onClick={() => onScope({ kind: "merged" })} />
          {concerns.map((id) => (
            <Chip
              key={id}
              text={id}
              active={scope.kind !== "merged" && scope.id === id}
              onClick={() => onScope({ kind: "concern", id })}
            />
          ))}
        </div>
      </div>
      <div className="chip-row">
        <span className="muted">Actor</span>
        <div className="chips">
          {scope.kind !== "merged" && (
            <Chip
              text="whole concern"
              active={scope.kind === "concern"}
              onClick={() => onScope({ kind: "concern", id: scope.id })}
            />
          )}
          {actors.map((label) => (
            <Chip
              key={label}
              text={label}
              active={scope.kind === "actor" && scope.label === label}
              onClick={() => onScope({ kind: "actor", id: actorOf(label), label })}
            />
          ))}
        </div>
      </div>
      <div className="trace-wrap">
        <div ref={body} className="trace-body" onScroll={scrolled}>
          <div className="trace-rows" style={{ height: virtualizer.getTotalSize() }}>
            {virtualizer.getVirtualItems().map((item) => {
              const entry = shown[item.index];
              if (entry === undefined) return null;
              return (
                <div
                  key={entry.seq}
                  className="trace-row"
                  data-index={item.index}
                  ref={virtualizer.measureElement}
                  style={{ transform: `translateY(${item.start}px)` }}
                >
                  <Entry entry={entry} expand={expand} />
                </div>
              );
            })}
          </div>
        </div>
        {unseen > 0 && (
          <button type="button" className="follow-chip" onClick={resumeFollowing}>
            {unseen} new ↓
          </button>
        )}
      </div>
      {shown.length === 0 && <p className="muted">Nothing recorded yet.</p>}
      <div className="actions">
        <input
          type="text"
          placeholder="Say something — it decides nothing and never parks the run"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
        />
        <button className="primary" type="button" onClick={() => void say(false)}>
          Send
        </button>
        <button
          type="button"
          title="Refuse this actor's next tool call and hand it this text as the reason"
          onClick={() => void say(true)}
        >
          Redirect
        </button>
      </div>
      <p className="target">
        {target !== "" ? `Goes to ${target}.` : "Goes to every actor in this run. Pick an actor above to address one."}
      </p>
      {messageError !== "" && <p className="error">{messageError}</p>}
    </section>
  );
}
