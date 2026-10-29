// The dashboard's API as the page calls it: the host's requests, asked or watched.
// Their types are generated from the server's own description (`pnpm run types`),
// itself made from the host's models, so the page and the host can't disagree.
import type { components, paths } from "./generated/api";

type Asking = paths["/api/ask"]["post"];
/** A request the page may send: one of the host's own. */
export type Asked = Asking["requestBody"]["content"]["application/json"];
/** The host's reply to one, a refusal among them. */
export type Replied = Asking["responses"][200]["content"]["application/json"];
/** A reply of one kind. */
export type ReplyOf<K extends Replied["kind"]> = Extract<Replied, { kind: K }>;

/** What a demo serving a copy of the operator's dashboard state says of it (`GET /api/about`). */
export type OfCopy = components["schemas"]["OfCopy"];

/** Where a watch stands: its reply arriving, the dashboard out of reach and tried again, or the page's token refused, which trying again can't mend. */
export type Connection = "connecting" | "live" | "retrying" | "refused";

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

/** What the page sends on its socket, as the server's `Watch` and `Unwatch` read it. */
type Sent = { kind: "watch"; number: number; request: Asked } | { kind: "unwatch"; number: number };

/** What the server sends on it, as its `Watched` and `Ended` write it. */
type Received = { kind: "watched"; number: number; reply: Replied } | { kind: "ended"; number: number; why: string };

/** The codes the server closes the socket with for a page whose token, or origin, it refuses. */
const REFUSED = [4401, 4403];

/** The longest the page waits before trying again, in milliseconds. */
const LONGEST = 60_000;

/** One watch the page holds: what it asks, whom it tells, and how long it waits before asking again once the host ends it. */
interface Held {
    request: Asked;
    received: (reply: Replied) => void;
    connection: (state: Connection) => void;
    wait: number;
}

/**
 * The page's one socket to the dashboard, carrying every watch it holds: a browser keeps six connections to a host,
 * which a stream per watch would use up in three tabs. Opened at the first watch; where it drops, every watch is
 * told the dashboard is out of reach and it's opened again after `retry` milliseconds, doubling up to a minute, each
 * watch started again on it; where the server refuses the page's token, every watch is told so and it stays shut.
 */
class Socket {
    private socket: WebSocket | null = null;
    private readonly held = new Map<number, Held>();
    private numbered = 0;
    private wait: number;
    private refused = false;

    constructor(private readonly retry: number) {
        this.wait = retry;
    }

    /** Watch `request` on the socket, until the function returned is called. */
    watch(request: Asked, received: (reply: Replied) => void, connection: (state: Connection) => void): () => void {
        this.numbered += 1;
        const number = this.numbered;
        this.held.set(number, { request, received, connection, wait: this.retry });
        connection(this.refused ? "refused" : "connecting");
        this.opened();
        this.send({ kind: "watch", number, request });
        return () => {
            this.held.delete(number);
            this.send({ kind: "unwatch", number });
        };
    }

    /** Open the socket, where it isn't and the token wasn't refused; once open, it starts every watch held. */
    private opened(): void {
        if (this.socket !== null || this.refused) {
            return;
        }
        const scheme = location.protocol === "https:" ? "wss" : "ws";
        const socket = new WebSocket(`${scheme}://${location.host}/api/socket`);
        this.socket = socket;
        socket.addEventListener("open", () => {
            this.wait = this.retry;
            for (const [number, each] of this.held) {
                this.send({ kind: "watch", number, request: each.request });
            }
        });
        socket.addEventListener("message", (event: MessageEvent<string>) => {
            this.arrived(JSON.parse(event.data) as Received);
        });
        socket.addEventListener("close", (event) => {
            this.socket = null;
            this.refused = REFUSED.includes(event.code);
            for (const each of this.held.values()) {
                each.connection(this.refused ? "refused" : "retrying");
            }
            if (!this.refused) {
                setTimeout(() => this.opened(), this.wait);
                this.wait = Math.min(this.wait * 2, LONGEST);
            }
        });
    }

    /** Send a frame where the socket is open; where it isn't, opening it starts every watch held. */
    private send(frame: Sent): void {
        if (this.socket?.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify(frame));
        }
    }

    /** Tell a watch its reply; or, where the host ended it, start it again after its wait. */
    private arrived(frame: Received): void {
        const each = this.held.get(frame.number);
        if (each === undefined) {
            return;
        }
        if (frame.kind === "watched") {
            each.wait = this.retry;
            each.connection("live");
            each.received(frame.reply);
            return;
        }
        console.warn("lup's dashboard: a watch ended", frame.why);
        each.connection("retrying");
        setTimeout(() => {
            if (this.held.get(frame.number) === each) {
                this.send({ kind: "watch", number: frame.number, request: each.request });
            }
        }, each.wait);
        each.wait = Math.min(each.wait * 2, LONGEST);
    }
}

const socket = new Socket(500);

/** Watch one of the host's requests on the page's socket: `received` gets its reply at once, then again each time it changes, until the function returned is called. */
export function watch(
    request: Asked,
    received: (reply: Replied) => void,
    connection: (state: Connection) => void,
): () => void {
    return socket.watch(request, received, connection);
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
