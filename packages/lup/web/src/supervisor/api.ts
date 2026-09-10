// The routes the supervisor answers, each typed against the projection the
// server declares. Spelled out in full rather than composed from a helper,
// because a test reads them back out of this file: the types across the seam
// are compiled, but a route is a path and not a model.
import type {
  AnswerSubmission,
  JournalEntry,
  MessageSubmission,
  ParkSubmission,
  RunIndex,
  SupervisorState,
} from "../generated/views";

type Refusal = { detail?: unknown };

async function checked<T>(response: Response): Promise<T> {
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = (payload as Refusal | null)?.detail;
    throw new Error(typeof detail === "string" ? detail : `HTTP ${response.status}`);
  }
  return payload as T;
}

async function post<T>(
  path: string,
  body: AnswerSubmission | MessageSubmission | ParkSubmission | Record<string, never>,
): Promise<T> {
  return checked<T>(
    await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

const named = (runId: string): string => encodeURIComponent(runId);

export async function readRuns(): Promise<RunIndex> {
  return checked<RunIndex>(await fetch("api/runs"));
}

/** The run the server was opened on, or null where it was opened on none. */
export async function readSelected(): Promise<SupervisorState | null> {
  const response = await fetch("api/state");
  return response.ok ? ((await response.json()) as SupervisorState) : null;
}

export async function readRun(runId: string): Promise<SupervisorState> {
  return checked<SupervisorState>(await fetch(`api/runs/${named(runId)}`));
}

export async function readEarlier(
  runId: string,
  before: number,
  count: number,
): Promise<JournalEntry[]> {
  return checked<JournalEntry[]>(
    await fetch(`api/runs/${named(runId)}/journal?before=${before}&count=${count}`),
  );
}

export function eventsUrl(runId: string): string {
  return `api/runs/${named(runId)}/events`;
}

export function submitAnswers(runId: string, submission: AnswerSubmission): Promise<SupervisorState> {
  return post<SupervisorState>(`api/runs/${named(runId)}/answers`, submission);
}

export function parkRun(runId: string, submission: ParkSubmission): Promise<SupervisorState> {
  return post<SupervisorState>(`api/runs/${named(runId)}/park`, submission);
}

export function resumeRun(runId: string): Promise<SupervisorState> {
  return post<SupervisorState>(`api/runs/${named(runId)}/resume`, {});
}

export function sendMessage(runId: string, submission: MessageSubmission): Promise<SupervisorState> {
  return post<SupervisorState>(`api/runs/${named(runId)}/messages`, submission);
}
