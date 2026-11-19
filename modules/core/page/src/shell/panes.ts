// Pane mode: moving between the page's panes, the outline, the document and the window under it, as vim's `Ctrl+W`
// moves between windows. Entered by Space w, or by Esc twice in Normal mode: an Esc pressed out of insert or visual
// mode doesn't count, so from insert mode it takes three, and pressing Esc to be sure never lands there. In pane mode,
// h, j, k and l choose the pane to their side, and Enter or Esc goes into it; no key reaches a pane until then.

import { getCM } from "@replit/codemirror-vim";

import type { Shell } from "./shell";

/** A pane of the page. */
export type Pane = "outline" | "document" | "window";

/** The pane each of h, j, k and l chooses from each pane: the outline to the left, the window under the document. */
const beside: Readonly<Record<Pane, Readonly<Record<string, Pane>>>> = {
    outline: { l: "document" },
    document: { h: "outline", j: "window" },
    window: { h: "outline", k: "document" },
};

/** Say whether `shell`'s vim is in Normal mode, neither inserting nor in visual mode. */
function normal(shell: Shell): boolean {
    const vim = getCM(shell.view)?.state.vim as { insertMode?: boolean; visualMode?: boolean } | null | undefined;
    return vim?.insertMode !== true && vim?.visualMode !== true;
}

/** The page's panes, around the document's shell `owner`, keys heard on `page`, which holds them all. */
export class Panes {
    readonly #owner: Shell;
    readonly #page: HTMLElement;
    /** The pane chosen, while in pane mode; none outside it. */
    #chosen: Pane | null = null;
    /** Whether the last key was Esc pressed in Normal mode, which a second makes pane mode. */
    #escaped = false;

    constructor(owner: Shell, page: HTMLElement) {
        this.#owner = owner;
        this.#page = page;
        page.addEventListener(
            "keydown",
            (event) => {
                this.#heard(event);
            },
            { capture: true },
        );
    }

    /** Return the pane chosen in pane mode; none outside it. */
    chosen(): Pane | null {
        return this.#chosen;
    }

    /** Enter pane mode, the pane the keys are in chosen. */
    enter(): void {
        this.#chosen = this.#focused() ?? "document";
        this.#escaped = false;
        this.#drawn();
        this.#owner.say("panes: h, j, k and l choose one, Enter or Esc goes into it");
    }

    /** Leave pane mode into the pane chosen. */
    leave(): void {
        const chosen = this.#chosen;
        this.#chosen = null;
        this.#drawn();
        this.#owner.say(null);
        this.#shellOf(chosen ?? "document")?.view.focus();
    }

    /** Hear a key before any pane does: in pane mode, take it; outside, count Esc pressed twice in Normal mode. */
    #heard(event: KeyboardEvent): void {
        if (this.#chosen !== null) {
            event.preventDefault();
            event.stopPropagation();
            if (event.key === "Enter" || event.key === "Escape") {
                this.leave();
                return;
            }
            const next = beside[this.#chosen][event.key];
            if (next !== undefined && this.#shellOf(next) !== null) {
                this.#chosen = next;
                this.#drawn();
            }
            return;
        }
        if (event.key !== "Escape" || event.ctrlKey || event.altKey || event.metaKey) {
            this.#escaped = false;
            return;
        }
        const pane = this.#from(event.target);
        const shell = pane === null ? null : this.#shellOf(pane);
        const counted = shell !== null && normal(shell);
        if (counted && this.#escaped) {
            event.preventDefault();
            event.stopPropagation();
            this.enter();
            return;
        }
        this.#escaped = counted;
    }

    /** Return the shell drawing `pane`; none where it isn't there, as the window while it's closed. */
    #shellOf(pane: Pane): Shell | null {
        switch (pane) {
            case "outline":
                return this.#owner.outline?.shell ?? null;
            case "document":
                return this.#owner;
            case "window":
                return this.#owner.window?.shell() ?? null;
        }
    }

    /** Return the pane the keys are in; none where they're in none. */
    #focused(): Pane | null {
        return this.#from(document.activeElement);
    }

    /** Return the pane `target`, where a key went, is in: the innermost, as the window is inside the document's editor. */
    #from(target: EventTarget | null): Pane | null {
        if (!(target instanceof Node)) {
            return null;
        }
        const panes: Pane[] = ["window", "outline", "document"];
        return panes.find((pane) => this.#shellOf(pane)?.view.dom.contains(target) === true) ?? null;
    }

    /** Mark the page as in pane mode or not, and each pane's frame as chosen or not. */
    #drawn(): void {
        this.#page.classList.toggle("lup-paning", this.#chosen !== null);
        for (const pane of ["outline", "document", "window"] as const) {
            this.#shellOf(pane)?.view.dom.classList.toggle("lup-pane-chosen", this.#chosen === pane);
        }
    }
}
