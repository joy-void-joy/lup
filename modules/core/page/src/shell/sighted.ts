// What's been on the operator's screen (`DESIGN.md`, *The dashboard*: news loses its mark once it's been on their
// screen). A block offering what being seen does (`Shown.sighted`), as an item new to the operator, is said seen once
// its first line has shown in the document, under no closed fold, for `dwell` milliseconds while the page is visible;
// the server then runs what it offers (`Seen`). Each block is said seen once for what it shows, so one that changes
// can be seen again.

import { foldKind, nodeAt, offsetOf, viewKey, type Node } from "../document/tree";
import type { Viewing } from "../generated/read";
import { sectionOf } from "./comments";
import type { Shell } from "./shell";

/** A block showing, as the page says it's seen: its view and id, and when it began to show. */
interface Showing {
    readonly viewing: Viewing;
    readonly block: string;
    readonly since: number;
}

/** What of a shell's document has been on the operator's screen long enough to count as seen. */
export class Sightings {
    readonly #shell: Shell;
    readonly #dwell: number;
    /** Each block showing that hasn't been said seen, by its place: its view, its id and its version. */
    readonly #showing = new Map<string, Showing>();
    /** The places of the blocks said seen. */
    readonly #said = new Set<string>();
    #timer: ReturnType<typeof setTimeout> | null = null;

    /** Say `shell`'s blocks seen once each has shown for `dwell` milliseconds. */
    constructor(shell: Shell, dwell: number) {
        this.#shell = shell;
        this.#dwell = dwell;
    }

    /** Note what shows as the document scrolls, changes or folds, and say seen what has shown long enough. */
    viewed(): void {
        const now = Date.now();
        const shown = this.#shownNow();
        for (const key of [...this.#showing.keys()]) {
            if (!shown.has(key)) {
                this.#showing.delete(key);
            }
        }
        for (const [key, showing] of shown) {
            if (!this.#showing.has(key) && !this.#said.has(key)) {
                this.#showing.set(key, { ...showing, since: now });
            }
        }
        this.#later();
    }

    /** Stop waiting to say anything seen. */
    destroy(): void {
        if (this.#timer !== null) {
            clearTimeout(this.#timer);
            this.#timer = null;
        }
    }

    /** Say seen each block that has shown for long enough and still does, after `dwell`, where any is waiting. */
    #later(): void {
        if (this.#timer !== null || this.#showing.size === 0) {
            return;
        }
        this.#timer = setTimeout(() => {
            this.#timer = null;
            this.#check();
        }, this.#dwell);
    }

    #check(): void {
        if (typeof document !== "undefined" && document.visibilityState === "hidden") {
            this.#later();
            return;
        }
        const now = Date.now();
        const shown = this.#shownNow();
        for (const [key, showing] of [...this.#showing]) {
            if (!shown.has(key)) {
                this.#showing.delete(key);
                continue;
            }
            if (now - showing.since >= this.#dwell) {
                this.#showing.delete(key);
                this.#said.add(key);
                this.#shell.source.seen(showing.viewing, showing.block);
            }
        }
        this.#later();
    }

    /** Return each block offering what being seen does whose first line shows in the document now, under no closed fold, by its place. */
    #shownNow(): Map<string, Showing> {
        const shown = new Map<string, Showing>();
        const view = this.#shell.view;
        for (const { from, to } of view.visibleRanges) {
            let position = from;
            while (position <= to) {
                const line = view.state.doc.lineAt(position);
                const node = nodeAt(this.#shell.document.root, line.from);
                const section = sectionOf(node);
                if (
                    node.block?.sighted !== null &&
                    node.block !== null &&
                    offsetOf(node) === line.from &&
                    section?.viewing !== undefined &&
                    section.viewing !== null &&
                    this.#open(node)
                ) {
                    const key = `${viewKey(section.viewing)}\n${node.block.id}\n${node.block.version ?? ""}`;
                    shown.set(key, { viewing: section.viewing, block: node.block.id, since: 0 });
                }
                position = line.to + 1;
            }
        }
        return shown;
    }

    /** Say whether no closed fold hides `node`. */
    #open(node: Node): boolean {
        for (let at = node.parent; at !== null; at = at.parent) {
            if (foldKind(at) !== null && !this.#shell.isOpen(at)) {
                return false;
            }
        }
        return true;
    }
}
