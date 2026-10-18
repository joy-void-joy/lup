// The dashboard's API as the page calls it: the host's requests, asked or watched.
// Their types are generated from the server's own description (`npm run types`),
// itself made from the host's models, so the page and the host can't disagree.
import { EventSourceParserStream } from "eventsource-parser/stream";

import type { paths } from "./generated/api";

type Asking = paths["/api/ask"]["post"];
/** A request the page may send: one of the host's own. */
export type Asked = Asking["requestBody"]["content"]["application/json"];
/** The host's reply to one, a refusal among them. */
export type Replied = Asking["responses"][200]["content"]["application/json"];
/** A reply of one kind. */
export type ReplyOf<K extends Replied["kind"]> = Extract<Replied, { kind: K }>;

/** Where a watch stands: its reply arriving, or the dashboard out of reach and tried again. */
export type Connection = "connecting" | "live" | "retrying";

/** Why a call to the API failed: its status and what the server said. */
export class ApiError extends Error {
    constructor(
        readonly status: number,
        detail: string,
    ) {
        super(detail);
    }
}

/** Trade the token the page was handed in its address's fragment for the cookie it calls with, and take it out of the address. */
export async function session(location: Location, history: History): Promise<void> {
    const handed = new URLSearchParams(location.hash.slice(1)).get("token");
    if (handed === null) {
        return;
    }
    const response = await fetch("/api/session", {
        method: "POST",
        headers: { Authorization: `Bearer ${handed}` },
    });
    history.replaceState(null, "", location.pathname + location.search);
    if (!response.ok) {
        throw await failure(response);
    }
}

/** Send one of the host's requests and return its reply. */
export async function ask(request: Asked): Promise<Replied> {
    const response = await fetch("/api/ask", posting(request));
    if (!response.ok) {
        throw await failure(response);
    }
    return (await response.json()) as Replied;
}

/**
 * Watch one of the host's requests: `received` gets its reply at once, then again each time it changes.
 *
 * Where the dashboard is out of reach, or the watch ends, it's tried again after
 * `retry` milliseconds, doubling up to a minute, until `stop` is called.
 */
export function watch(
    request: Asked,
    received: (reply: Replied) => void,
    connection: (state: Connection) => void,
    retry = 500,
): () => void {
    const stopping = new AbortController();
    async function watching(): Promise<void> {
        let wait = retry;
        while (!stopping.signal.aborted) {
            connection("connecting");
            try {
                const response = await fetch("/api/watch", {
                    ...posting(request),
                    signal: stopping.signal,
                });
                if (!response.ok || response.body === null) {
                    throw await failure(response);
                }
                connection("live");
                wait = retry;
                const events = response.body
                    .pipeThrough(new TextDecoderStream())
                    .pipeThrough(new EventSourceParserStream());
                for await (const event of events) {
                    received(JSON.parse(event.data) as Replied);
                }
            } catch (error) {
                if (stopping.signal.aborted) {
                    return;
                }
                console.warn("lup's dashboard: the watch broke", error);
            }
            connection("retrying");
            await new Promise((resume) => setTimeout(resume, wait));
            wait = Math.min(wait * 2, 60_000);
        }
    }
    void watching();
    return () => stopping.abort();
}

function posting(request: Asked): RequestInit {
    return {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
    };
}

async function failure(response: Response): Promise<ApiError> {
    const text = await response.text();
    return new ApiError(response.status, text || response.statusText);
}
