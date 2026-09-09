// What the trace shows and how it reads an entry: the scope a reader narrowed
// to, the kind filter, the search, and the tone a status draws in. Pure
// functions over the journal's own types, so `bun test` holds them still.
import type { ActorRef, JournalEntry } from "../generated/views";

// A concern is not one actor: its worker, the reviewer that read it and the
// merger that joined it share an id and run in different rounds, so opening
// a concern has to mean all of them or it silently shows whichever came
// first.
export type Scope =
  | { kind: "merged" }
  | { kind: "concern"; id: string }
  | { kind: "actor"; id: string; label: string };

export type KindFilter = "all" | "notes" | "errors";

export type Tone = "ok" | "run" | "wait" | "danger" | "idle";

// Presentation only: an unknown status draws neutral rather than failing, so
// the page never has to be told about a new status to keep drawing every
// concern that carries one.
const STATUS_TONES: Record<string, Tone> = {
  verified: "ok",
  integrated: "ok",
  cleaned: "ok",
  failed: "danger",
  ineligible: "danger",
  leased: "run",
  running: "run",
  validating: "run",
  reviewing: "run",
  revising: "run",
  integrating: "run",
  waiting_for_answers: "wait",
  retained: "wait",
};

export function tone(status: string): Tone {
  return STATUS_TONES[status] ?? "idle";
}

export function actorLabel(actor: ActorRef): string {
  return `${actor.kind}:${actor.id}#${actor.round}`;
}

/** The run's own entries would otherwise wear the run id twice over. */
export function actorDisplay(actor: ActorRef): string {
  return actor.kind === "run" ? "run" : actorLabel(actor);
}

export function inScope(entry: JournalEntry, scope: Scope): boolean {
  switch (scope.kind) {
    case "concern":
      return entry.actor.id === scope.id;
    case "actor":
      return actorLabel(entry.actor) === scope.label;
    default:
      return true;
  }
}

// Turn content is what an actor's session said and did; everything else is
// the run speaking. Listing the turn kinds rather than the run kinds means an
// event added later lands on the run side — shown under the narrower filter
// rather than hidden by it.
const TURN_CONTENT = [
  "message_completed",
  "turn_started",
  "turn_completed",
  "block_started",
  "block_completed",
];

export function isRunEvent(entry: JournalEntry): boolean {
  return !TURN_CONTENT.includes(entry.event.type);
}

export function carriesError(entry: JournalEntry): boolean {
  const event = entry.event;
  switch (event.type) {
    case "run_failed":
      return true;
    case "concern_progressed":
      return event.progress.status === "failed";
    case "message_completed":
      return event.message.blocks.some((block) => block.type === "tool_result" && block.is_error);
    default:
      return false;
  }
}

export function matchesKind(entry: JournalEntry, filter: KindFilter): boolean {
  switch (filter) {
    case "notes":
      return isRunEvent(entry);
    case "errors":
      return carriesError(entry);
    default:
      return true;
  }
}

export function matchesQuery(entry: JournalEntry, query: string): boolean {
  return query === "" || JSON.stringify(entry).toLowerCase().includes(query);
}

/** The two streaming events carry what `message_completed` already carries whole. */
export function drawsNothing(entry: JournalEntry): boolean {
  return entry.event.type === "block_started" || entry.event.type === "block_completed";
}

export function visible(
  entry: JournalEntry,
  scope: Scope,
  filter: KindFilter,
  query: string,
): boolean {
  return (
    !drawsNothing(entry) && inScope(entry, scope) && matchesKind(entry, filter) && matchesQuery(entry, query)
  );
}

/** Every actor id the record names, in first-seen order: the concern chips. */
export function concernIds(entries: JournalEntry[]): string[] {
  return [...new Set(entries.map((entry) => entry.actor.id))];
}

// Which actors the actor row offers: every one under the open concern, or
// every one in the run when nothing is narrowed. Selecting an actor keeps the
// concern it belongs to, so the two rows read as one path in.
export function scopedActors(entries: JournalEntry[], scope: Scope): string[] {
  const concern = scope.kind === "merged" ? null : scope.id;
  return [
    ...new Set(
      entries
        .filter((entry) => concern === null || entry.actor.id === concern)
        .map((entry) => actorLabel(entry.actor)),
    ),
  ];
}

/** The actor an actor label names, which is what a scope narrowed to it keeps. */
export function actorOf(label: string): string {
  const afterKind = label.slice(label.indexOf(":") + 1);
  return afterKind.slice(0, afterKind.lastIndexOf("#"));
}
