// The page's side of the server's socket: one socket carrying every view the page watches, each under a number the
// page picks, answered and answered again, and the draft, written a comment at a time and told as it changes; the
// token said first, read from the page's address's fragment, which no request carries, and kept for every tab of the
// dashboard's address.

import type { Blocks, Comment, Delivered, Draft, Marked, Opened, Sent, Told, Unanswered, Viewing } from "./generated/read";

const nothing: Blocks = { blocks: [], summary: [], offers: [] };
import type { Source } from "./shell/shell";

/** Where the token is kept, in the storage every tab of the dashboard's address shares. */
const kept = "lup-token";

/** The close code the server refuses a page with whose token isn't the dashboard's (`lup.environment.shell.server`). */
const untokened = 4401;

/**
 * Return the token the page says: the one handed in its address's fragment, kept in `storage` for every tab of the
 * dashboard's address, else the one kept there already; none where neither is.
 *
 * Kept per tab, a tab opened by hand on the dashboard's address, which `lup` says without the token, would say none.
 */
export function remembered(fragment: string, storage: Storage): string {
    const handed = fragment.replace(/^#/, "");
    if (handed !== "") {
        storage.setItem(kept, handed);
        return handed;
    }
    return storage.getItem(kept) ?? "";
}

/** Say why the server closed the page's socket, with the code it closed it with: what the operator does next. */
export function closed(code: number): string {
    if (code === untokened) {
        return "This tab holds no token the dashboard takes. Open the dashboard with `lup` in your terminal: it hands the page its token, which every tab on this address then shares.";
    }
    return "The dashboard's server closed this page's socket: reload once the machine serves it again.";
}

/** The server's socket, as a source of views. */
export class Server implements Source {
    readonly #socket: WebSocket;
    readonly #watches = new Map<number, (blocks: Blocks) => void>();
    readonly #waiting: Sent[] = [];
    readonly #drafted = new Set<(draft: Draft) => void>();
    readonly #delivered = new Set<(delivered: Delivered) => void>();
    readonly #reviewed = new Set<(review: Blocks) => void>();
    /** The review as the server last told it, handed to whoever follows it from then on. */
    #review: Blocks = nothing;
    /** The draft as the server last told it, handed to whoever follows the draft from then on. */
    #draft: Draft | null = null;
    #next = 1;
    #open = false;

    /** Open the socket at `url`, say `token`, hand what it's told to `opened` and `refused`, and why it's closed to `lost`. */
    constructor(
        url: string,
        token: string,
        opened: (told: Opened) => void,
        refused: (told: Unanswered) => void,
        lost: (why: string) => void,
    ) {
        this.#socket = new WebSocket(url);
        this.#socket.addEventListener("close", (event: CloseEvent) => {
            this.#open = false;
            lost(closed(event.code));
        });
        this.#socket.addEventListener("open", () => {
            this.#socket.send(JSON.stringify({ kind: "hello", token } satisfies Sent));
            this.#open = true;
            for (const frame of this.#waiting.splice(0)) {
                this.#socket.send(JSON.stringify(frame));
            }
        });
        this.#socket.addEventListener("message", (event: MessageEvent<string>) => {
            const told = JSON.parse(event.data) as Told;
            switch (told.kind) {
                case "opened":
                    opened(told);
                    break;
                case "answered":
                    this.#watches.get(told.watch)?.(told.blocks);
                    break;
                case "unanswered":
                    refused(told);
                    break;
                case "drafted":
                    this.#draft = told.draft;
                    for (const drafted of this.#drafted) {
                        drafted(told.draft);
                    }
                    break;
                case "delivered":
                    for (const delivered of this.#delivered) {
                        delivered(told);
                    }
                    break;
                case "reviewed":
                    this.#review = told.review;
                    for (const reviewed of this.#reviewed) {
                        reviewed(told.review);
                    }
                    break;
            }
        });
    }

    watch(viewing: Viewing, answered: (blocks: Blocks) => void): () => void {
        const watch = this.#next;
        this.#next += 1;
        this.#watches.set(watch, answered);
        this.#send({ kind: "watch", watch, viewing });
        return () => {
            this.#watches.delete(watch);
            this.#send({ kind: "unwatch", watch });
        };
    }

    write(comment: Comment): void {
        this.#send({ kind: "write", comment });
    }

    mark(marked: Marked): void {
        this.#send({ kind: "mark", marked });
    }

    seen(viewing: Viewing, block: string): void {
        this.#send({ kind: "seen", viewing, block });
    }

    erase(id: string): void {
        this.#send({ kind: "erase", id });
    }

    send(): void {
        this.#send({ kind: "send" });
    }

    drafts(drafted: (draft: Draft) => void, delivered: (delivered: Delivered) => void): () => void {
        this.#drafted.add(drafted);
        this.#delivered.add(delivered);
        if (this.#draft !== null) {
            drafted(this.#draft);
        }
        return () => {
            this.#drafted.delete(drafted);
            this.#delivered.delete(delivered);
        };
    }

    reviews(reviewed: (review: Blocks) => void): () => void {
        this.#reviewed.add(reviewed);
        reviewed(this.#review);
        return () => {
            this.#reviewed.delete(reviewed);
        };
    }

    #send(frame: Sent): void {
        if (this.#open) {
            this.#socket.send(JSON.stringify(frame));
        } else {
            this.#waiting.push(frame);
        }
    }
}
