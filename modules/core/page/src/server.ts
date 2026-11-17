// The page's side of the server's socket: one socket carrying every view the page watches, each under a number the
// page picks, answered and answered again, and the draft, written a comment at a time and told as it changes; the
// token said first, read from the page's address's fragment, which no request carries.

import type { Blocks, Comment, Delivered, Draft, Opened, Sent, Told, Unanswered, Viewing } from "./generated/read";
import type { Source } from "./shell/shell";

/** The server's socket, as a source of views. */
export class Server implements Source {
    readonly #socket: WebSocket;
    readonly #watches = new Map<number, (blocks: Blocks) => void>();
    readonly #waiting: Sent[] = [];
    readonly #drafted = new Set<(draft: Draft) => void>();
    readonly #delivered = new Set<(delivered: Delivered) => void>();
    /** The draft as the server last told it, handed to whoever follows the draft from then on. */
    #draft: Draft | null = null;
    #next = 1;
    #open = false;

    /** Open the socket at `url`, say `token`, and hand what it's told to `opened` and `refused`. */
    constructor(url: string, token: string, opened: (told: Opened) => void, refused: (told: Unanswered) => void) {
        this.#socket = new WebSocket(url);
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

    #send(frame: Sent): void {
        if (this.#open) {
            this.#socket.send(JSON.stringify(frame));
        } else {
            this.#waiting.push(frame);
        }
    }
}
