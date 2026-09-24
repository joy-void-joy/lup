import type { ReviewAnswer, ReviewDecision, ReviewDetail, ReviewInbox } from "../generated/views";

const TOKEN_KEY = "lup-review-token";

/** Keep the browser capability in this tab, removing it from the address bar. */
export function takeToken(): string {
  const url = new URL(window.location.href);
  const supplied = new URLSearchParams(url.hash.slice(1)).get("token");
  if (supplied !== null) {
    sessionStorage.setItem(TOKEN_KEY, supplied);
    url.hash = "";
    window.history.replaceState(null, "", url);
  }
  return sessionStorage.getItem(TOKEN_KEY) ?? "";
}

export class ReviewError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

async function accepted(response: Response): Promise<Response> {
  if (response.ok) return response;
  const payload: unknown = await response.json().catch(() => null);
  const detail = (payload as { detail?: unknown } | null)?.detail;
  throw new ReviewError(response.status, typeof detail === "string" ? detail : `HTTP ${response.status}`);
}

function authorization(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

export async function readInbox(token: string, signal?: AbortSignal): Promise<ReviewInbox> {
  return (await accepted(await fetch("api/reviews", { headers: authorization(token), signal }))).json();
}

export async function readReview(key: string, token: string, signal?: AbortSignal): Promise<ReviewDetail> {
  return (await accepted(await fetch(`api/reviews/${encodeURIComponent(key)}`, {
    headers: authorization(token), signal,
  }))).json();
}

export async function answerReview(key: string, answer: ReviewAnswer, token: string): Promise<ReviewDecision> {
  return (await accepted(await fetch(`api/reviews/${encodeURIComponent(key)}/answer`, {
    method: "POST",
    headers: { ...authorization(token), "Content-Type": "application/json" },
    body: JSON.stringify(answer),
  }))).json();
}

/** Decode complete NDJSON records even when UTF-8 or a record spans chunks. */
export async function* followInbox(token: string, signal: AbortSignal): AsyncGenerator<ReviewInbox> {
  const response = await accepted(await fetch("api/events", {
    headers: authorization(token), signal,
  }));
  if (response.body === null) throw new Error("The review stream has no response body.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffered = "";
  try {
    for (;;) {
      const chunk = await reader.read();
      buffered += decoder.decode(chunk.value, { stream: !chunk.done });
      let newline = buffered.indexOf("\n");
      for (; newline !== -1; newline = buffered.indexOf("\n")) {
        const record = buffered.slice(0, newline);
        buffered = buffered.slice(newline + 1);
        if (record.trim() !== "") yield JSON.parse(record) as ReviewInbox;
      }
      if (chunk.done) {
        if (buffered.trim() !== "") yield JSON.parse(buffered) as ReviewInbox;
        return;
      }
    }
  } finally {
    try {
      await reader.cancel();
    } finally {
      reader.releaseLock();
    }
  }
}
