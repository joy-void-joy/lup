// The page's side of the server's socket: one socket carrying every view the page watches, each under a number the
// page picks, answered and answered again; the token said first, read from the page's address's fragment, which no
// request carries.

import type { Blocks, Opened, Sent, Told, Unanswered, Viewing } from "./generated/read";
import type { Source } from "./shell/shell";

/** The server's socket, as a source of views. */
export class Server implements Source {
    readonly #socket: WebSocket;
    readonly #watches = new Map<number, (blocks: Blocks) => void>();
    readonly #waiting: Sent[] = [];
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

    #send(frame: Sent): void {
        if (this.#open) {
            this.#socket.send(JSON.stringify(frame));
        } else {
            this.#waiting.push(frame);
        }
    }
}
