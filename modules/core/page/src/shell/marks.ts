// Marks: the verbs the operator marks on the document's blocks, each waiting in the one draft until it's sent
// (`lup.shell.draft`, `Marked`; `README.md` there, *The draft*).
//
// Space and a verb's key marks the innermost block at the cursor that offers that verb, or every fold chosen that
// offers it; the same key again takes the mark off. A block holds one mark at most: marking it with another verb puts
// that one in the first's place. A mark shows at the end of its block's first line, saying what the send will do.
// Nothing happens until the draft is sent; the review in the window lists each mark first. vim's `u` takes a change
// to the marks back, as any change to the draft, and Ctrl+R makes it again (`remarked`).

import { invertedEffects, isolateHistory } from "@codemirror/commands";
import { StateEffect, Transaction, type Extension, type Text } from "@codemirror/state";
import { EditorView } from "@codemirror/view";

import type { Delivered, Draft, Marked, Offer } from "../generated/read";
import { nodeAt, type Node } from "../document/tree";
import { fromCore, redrawn } from "./annotations";
import { quotedIn, sectionOf, within } from "./comments";
import type { Shell } from "./shell";

/** What a mark reads as at the end of its block's first line, before what its offer says: the core's verbs' own, a dot for another. */
const glyphs: Readonly<Record<string, string>> = { done: "✓", decline: "✗" };

/** Return the glyph a mark of `verb` reads as. */
export function glyphOf(verb: string): string {
    return glyphs[verb] ?? "•";
}

/** One mark's change, by its id: the mark as it was, and as it is after; none where there was none, or is none after. */
interface Change {
    readonly id: string;
    readonly was: Marked | null;
    readonly now: Marked | null;
}

/** A change to the draft's marks, which the editor's history keeps, so vim's `u` and Ctrl+R take it back and make it again. */
export const remarked = StateEffect.define<readonly Change[]>();

/** Undoing a change to the marks is the change the other way. */
const undoable = invertedEffects.of((transaction) =>
    transaction.effects.flatMap((effect) => (effect.is(remarked) ? [remarked.of(effect.value.map((each) => ({ id: each.id, was: each.now, now: each.was })))] : [])),
);

/** Return what `node`'s block offers under `verb`; none where it offers nothing under it. */
function offering(node: Node, verb: string): Offer | null {
    return node.block?.offers.find((offer) => offer.verb === verb) ?? null;
}

/** The marks of a shell's document, as the draft holds them. */
export class Marks {
    readonly #shell: Shell;
    /** Every mark the draft holds, by its id: as the core last told it, with those this page made or took off since. */
    #marks = new Map<string, Marked>();
    /** Each mark by the key of the block it's on, for the document's text it was found in; none once the marks change. */
    #placed: { readonly text: Text; readonly marks: ReadonlyMap<string, Marked> } | null = null;
    #stop: (() => void) | null = null;

    constructor(shell: Shell) {
        this.#shell = shell;
    }

    /** Return what the shell's editor takes to undo and redo the marks: a change undone or redone is made again in the draft. */
    extension(): Extension {
        return [
            undoable,
            EditorView.updateListener.of((update) => {
                for (const transaction of update.transactions) {
                    if (!transaction.isUserEvent("undo") && !transaction.isUserEvent("redo")) {
                        continue;
                    }
                    const undoing = transaction.isUserEvent("undo");
                    for (const effect of transaction.effects) {
                        if (effect.is(remarked)) {
                            // The editor takes no transaction while it's telling this one's listeners.
                            queueMicrotask(() => {
                                const made = this.#applied(effect.value);
                                this.#shell.say(made === 0 ? "nothing of the marks to take back: the draft moved on" : `${made} ${made === 1 ? "mark" : "marks"} ${undoing ? "taken back" : "made again"}`);
                            });
                        }
                    }
                }
            }),
        ];
    }

    /** Follow the draft's marks as the core tells them. */
    start(): void {
        this.#stop = this.#shell.source.drafts(
            (draft) => {
                this.drafted(draft);
            },
            (_delivered: Delivered) => {},
        );
    }

    /** Stop following the draft. */
    destroy(): void {
        this.#stop?.();
    }

    /** Lay out the draft's marks as the core tells them. */
    drafted(draft: Draft): void {
        this.#marks = new Map(draft.marks.map((each) => [each.id, each]));
        this.#placed = null;
        this.#shell.view.dispatch({ effects: redrawn.of(null), annotations: fromCore.of(true) });
    }

    /** Return every mark the draft holds, in the order they were made. */
    held(): Marked[] {
        return [...this.#marks.values()];
    }

    /** Return the mark of id `id`; none where the draft holds none of it. */
    byId(id: string): Marked | null {
        return this.#marks.get(id) ?? null;
    }

    /**
     * Return the mark on `node`'s block; none where it holds none. A mark is on the block the core finds at the send by
     * its view and id: the first of that id in the view's answer.
     */
    on(node: Node): Marked | null {
        const text = this.#shell.view.state.doc;
        if (this.#placed?.text !== text) {
            const marks = new Map<string, Marked>();
            for (const mark of this.#marks.values()) {
                const found = quotedIn(this.#shell.document.root, mark.on);
                if (found !== null) {
                    marks.set(found.key, mark);
                }
            }
            this.#placed = { text, marks };
        }
        return this.#placed.marks.get(node.key) ?? null;
    }

    /** Return the innermost block at the cursor that offers `verb`, the block it's on first, then each holding it; none where none does. */
    offeringHere(verb: string): Node | null {
        let node: Node | null = nodeAt(this.#shell.document.root, this.#shell.view.state.selection.main.head);
        while (node !== null) {
            if (offering(node, verb) !== null) {
                return node;
            }
            node = node.parent;
        }
        return null;
    }

    /**
     * Mark `verb` on every block vim's visual mode selects that offers it, else every fold chosen that does, else the
     * innermost block at the cursor that does; where each of those is marked with it already, take the marks off. Say
     * what was done, or why nothing was. A selection reaches what shows alone, never what a closed fold hides.
     */
    toggle(verb: string): void {
        const chosen = this.#shell.chosen();
        const selected = this.#shell.visual();
        this.#shell.unselect();
        const among =
            selected !== null
                ? this.#shell.blocksIn(selected)
                : chosen.flatMap((key) => {
                      const node = this.#shell.document.node(key);
                      return node === null ? [] : [node];
                  });
        const nodes =
            selected !== null || chosen.length > 0
                ? among.filter((node) => offering(node, verb) !== null)
                : [this.offeringHere(verb)].filter((node): node is Node => node !== null);
        if (nodes.length === 0) {
            this.#shell.say(selected !== null ? `nothing selected offers ${verb}` : chosen.length > 0 ? `nothing chosen offers ${verb}` : `nothing here offers ${verb}`);
            return;
        }
        const unmarkable = nodes.filter((node) => node.block === null || !this.#own(node));
        if (unmarkable.length > 0) {
            this.#shell.say("a block here shares its id with another in its view, so a mark on it would reach the other");
            return;
        }
        const marking = !nodes.every((node) => this.on(node)?.offer.verb === verb);
        const changes: Change[] = [];
        for (const node of nodes) {
            const was = this.on(node);
            if (!marking) {
                if (was !== null) {
                    changes.push({ id: was.id, was, now: null });
                }
                continue;
            }
            if (was?.offer.verb === verb) {
                continue;
            }
            const now = this.#made(node, verb, was?.id ?? crypto.randomUUID());
            if (now !== null) {
                changes.push({ id: now.id, was, now });
            }
        }
        if (chosen.length > 0) {
            this.#shell.choose([]);
        }
        const changed = this.#changed(changes);
        const first = nodes[0];
        const says = first === undefined ? verb : (offering(first, verb)?.says ?? verb);
        if (!marking) {
            this.#shell.say(nodes.length === 1 ? `unmarked: ${says}` : `${changed} unmarked`);
            return;
        }
        this.#shell.say(nodes.length === 1 ? `marked: ${says}; Ctrl+Enter reviews the draft` : `${changed} marked: ${verb}; Ctrl+Enter reviews the draft`);
    }

    /** Hold the mark of id `id` back from sends, or let it go, or toggle it where `held` is none. */
    hold(id: string, held: boolean | null): Marked | null {
        const mark = this.#marks.get(id);
        if (mark === undefined) {
            return null;
        }
        const now = { ...mark, held: held ?? !mark.held };
        this.#changed([{ id, was: mark, now }]);
        return now;
    }

    /** Make `changes` to the draft's marks, as one step the editor's history keeps; return how many there were. */
    #changed(changes: readonly Change[]): number {
        const made = this.#applied(changes);
        this.#shell.view.dispatch({
            effects: [remarked.of(changes), redrawn.of(null)],
            annotations: [isolateHistory.of("full"), Transaction.userEvent.of("select.mark")],
        });
        return made;
    }

    /**
     * Make each of `changes` in the draft where the mark stands as the change found it, so taking back a change the
     * draft has since moved on from (a mark sent, or changed in another page) changes nothing; return how many it made.
     */
    #applied(changes: readonly Change[]): number {
        let made = 0;
        for (const change of changes) {
            const current = this.#marks.get(change.id) ?? null;
            if (JSON.stringify(current) !== JSON.stringify(change.was)) {
                continue;
            }
            if (change.now === null) {
                this.#marks.delete(change.id);
                this.#shell.source.erase(change.id);
            } else {
                this.#marks.set(change.id, change.now);
                this.#shell.source.mark(change.now);
            }
            made += 1;
        }
        this.#placed = null;
        this.#shell.view.dispatch({ effects: redrawn.of(null), annotations: fromCore.of(true) });
        return made;
    }

    /** Return a mark of `verb` on `node`'s block under the id `id`; none where it offers nothing under the verb. */
    #made(node: Node, verb: string, id: string): Marked | null {
        const offer = offering(node, verb);
        const section = sectionOf(node);
        if (offer === null || node.block === null || section?.viewing === undefined || section.viewing === null) {
            return null;
        }
        const mark: Marked = {
            id,
            on: {
                viewing: section.viewing,
                block: node.block.id,
                version: node.block.version,
                // Its block's first line, which the review names it by: a mark is on its block whole.
                lines: node.head.length > 0 ? [node.head[0] ?? ""] : [],
                line: 0,
                start: 0,
                end: null,
                within: within(section),
            },
            offer,
            reason: null,
            held: false,
        };
        return mark;
    }

    /** Say whether `node`'s block is the one its view and id name: the first of its id in its view's answer. */
    #own(node: Node): boolean {
        const section = sectionOf(node);
        if (section?.viewing === undefined || section.viewing === null || node.block === null) {
            return false;
        }
        const quote = { viewing: section.viewing, block: node.block.id, version: null, lines: [], line: 0, start: 0, end: null, within: [] };
        return quotedIn(this.#shell.document.root, quote) === node;
    }

}
