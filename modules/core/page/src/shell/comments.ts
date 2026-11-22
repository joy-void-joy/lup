// Comments: what the operator writes into the document, under the line or passage it's about, kept in the one draft
// the core holds (`lup.shell.draft`, `README.md` there, *The draft*).
//
// Nothing is bound to a key. The document's text is the core's: an edit vim makes there is refused, and entering
// insert mode there opens a comment, on the passage the refused edit covered (`c` with a motion, `s`, `S`, `v…s`), or
// under the cursor's line (`i`, `a`, `o`, `O`). In a comment, vim edits as anywhere: an edit inside it is let through,
// one deleting its lines whole takes them out of it, and leaving insert mode with it saying nothing drops it.
//
// Each comment is a node of the document's tree under the line it's on (`Document.remark`), its text the editor's,
// which the tree follows as it's typed. It's written to the draft as it changes, at a pause in typing, as insert mode
// ends and at `:w`; the draft as another page changes it, or as a send leaves it, is laid out as it comes. A comment
// whose block isn't laid out (its fold closed and unread, its view gone) is held until its block is, under the lines it
// quotes, found again by what they say where they moved.

import { EditorSelection, type Text, type Transaction } from "@codemirror/state";
import type { ViewUpdate } from "@codemirror/view";
import { getCM, Vim } from "@replit/codemirror-vim";

import type { Comment, Delivered, Draft, JsonValue, Party, Quote, Within } from "../generated/read";
import { comment as remark, every, nodeAt, offsetOf, ownLines, viewKey, type Node } from "../document/tree";
import { fromCore, redrawn } from "./annotations";
import type { Shell } from "./shell";
import type { Choice } from "./window";

/** A party a comment can reach, as the block naming it says it, its fields as they came. */
type Reached = { [key: string]: JsonValue };

/** A comment as the page holds it: what it says and is on, where it's laid out, and whether the draft holds it as it stands. */
interface Held {
    comment: Comment;
    /** The key of its node in the document; none while its block isn't laid out. */
    key: string | null;
    /** Whether the draft holds it as it stands: nothing written since the last write. */
    written: boolean;
}

/** An edit the document refused, outside every comment: what it would have changed. */
interface Refused {
    readonly from: number;
    readonly to: number;
}

/** What a comment says of itself on its first line: whom it reaches, and why it stayed in the draft or is outdated. */
export interface Said {
    readonly to: string;
    readonly outdated: boolean;
    readonly reason: string | null;
    /** Whether the operator keeps it back from sends. */
    readonly held: boolean;
}

/** Say `party` as a comment's line says whom it reaches: what identifies it, as its fields give it, but which of the core's parties it is. */
function named(party: Party): string {
    return Object.entries(party)
        .filter(([key]) => key !== "party")
        .map(([, value]) => String(value))
        .join(" ");
}

/** The comments of a shell's document, and the draft they're kept in. */
export class Comments {
    readonly #shell: Shell;
    /** Every comment the page holds, by its id. */
    readonly #held = new Map<string, Held>();
    /** The comment being written, in insert mode, by its id. */
    #writing: string | null = null;
    /** Where the cursor was as the comment being written was opened, to go back to where it's dropped. */
    #opened: number | null = null;
    /** The last edit refused outside the comments, until the key that made it is done with. */
    #refused: Refused | null = null;
    #pause: ReturnType<typeof setTimeout> | null = null;
    #stop: (() => void) | null = null;
    /** How many comments are laid out under each node, by its key, for each text of the document. */
    readonly #counts = new WeakMap<Text, Map<string, number>>();
    /** Hold `shell`'s comments, written to the draft its source keeps after a pause of `pause` milliseconds in typing. */
    constructor(
        shell: Shell,
        readonly pause = 300,
    ) {
        this.#shell = shell;
    }

    /** Follow the draft its source keeps, once the shell's editor is there to lay it out in. */
    start(): void {
        this.#stop = this.#shell.source.drafts(
            (draft) => {
                this.drafted(draft);
            },
            (delivered) => {
                this.delivered(delivered);
            },
        );
    }

    /** Stop following the draft, writing what's not written yet. */
    destroy(): void {
        this.flush();
        this.#stop?.();
    }

    /** Return the id of the comment being written; none outside insert mode, or outside a comment. */
    writing(): string | null {
        return this.#writing;
    }

    /** Return every comment the page holds, as it stands. */
    held(): Comment[] {
        return [...this.#held.values()].map((held) => held.comment);
    }

    /** Return the comment whose node is keyed `key`; none where it's no comment's. */
    byKey(key: string): Comment | null {
        for (const held of this.#held.values()) {
            if (held.key === key) {
                return held.comment;
            }
        }
        return null;
    }

    /**
     * Say whether `transaction`, made by the operator's keys, may change the text: where every change it makes is
     * inside one comment. One that isn't is refused, and kept for the key that made it, which may go on into insert
     * mode and comment on what it would have changed.
     */
    allows(transaction: Transaction): boolean {
        if (transaction.changes.empty) {
            return true;
        }
        const touched = new Set<Node | null>();
        let from = Number.POSITIVE_INFINITY;
        let to = 0;
        transaction.changes.iterChangedRanges((changedFrom, changedTo) => {
            touched.add(this.#around(changedFrom, changedTo));
            from = Math.min(from, changedFrom);
            to = Math.max(to, changedTo);
        });
        if (touched.size === 1 && !touched.has(null)) {
            return true;
        }
        this.#refused = { from, to };
        queueMicrotask(() => {
            this.#settleRefused();
        });
        return false;
    }

    /** Follow, in the tree and the draft, what the operator's keys changed in a comment, as `update` made it. */
    changed(update: ViewUpdate): void {
        for (const transaction of update.transactions) {
            if (transaction.changes.empty || transaction.annotation(fromCore) === true) {
                continue;
            }
            let from = -1;
            let to = -1;
            let delta = 0;
            transaction.changes.iterChanges((fromA, toA, _fromB, _toB, inserted) => {
                if (from === -1) {
                    from = fromA;
                    to = toA;
                }
                delta += inserted.length - (toA - fromA);
            });
            const node = from === -1 ? null : this.#around(from, to);
            const held = node === null ? undefined : this.#heldBy(node.key);
            if (node === null || held === undefined) {
                continue;
            }
            const start = offsetOf(node);
            const text = transaction.newDoc.sliceString(start, start + node.size + delta);
            this.#shell.document.rewrite(node.key, text);
            held.comment = { ...held.comment, words: text, warned: false, reason: null };
            held.written = false;
            if (held.comment.id === this.#writing) {
                this.#later();
                continue;
            }
            // Edited out of insert mode, as `x` does: written at once, or dropped once it says nothing, the update
            // done with first.
            queueMicrotask(() => {
                this.#ended(held.comment.id, null);
            });
        }
    }

    /** Follow vim into `mode`: into insert mode, write the comment the cursor's in, or open one; out of it, end the one written. */
    moded(mode: string): void {
        if (mode === "insert") {
            const head = this.#shell.view.state.selection.main.head;
            const around = this.#around(head, head);
            const refused = this.#refused;
            this.#refused = null;
            if (around !== null) {
                this.#writing = this.#heldBy(around.key)?.comment.id ?? null;
                return;
            }
            if (this.#writing !== null && this.#held.has(this.#writing)) {
                return;
            }
            if (this.#shell.owner !== null) {
                this.#shell.say("the window takes no comment");
                queueMicrotask(() => {
                    const cm = getCM(this.#shell.view);
                    if (cm !== null) {
                        Vim.handleKey(cm, "<Esc>", "mapping");
                    }
                });
                return;
            }
            this.#open(refused, head);
            return;
        }
        const writing = this.#writing;
        const opened = this.#opened;
        this.#writing = null;
        this.#opened = null;
        if (writing !== null) {
            this.#ended(writing, opened);
        }
    }

    /**
     * Return the part of the draft of id `id`, as its line in the review in the window names it, else the comment the
     * cursor is in; none where there's neither.
     */
    partAt(id: string | null = null): Comment | null {
        if (id !== null) {
            return this.#held.get(id)?.comment ?? null;
        }
        const head = this.#shell.view.state.selection.main.head;
        const around = this.#around(head, head);
        return around === null ? null : (this.#heldBy(around.key)?.comment ?? null);
    }

    /**
     * Keep back from sends the comment of id `id`, as its line in the review names it, else the comment at the cursor,
     * or let it go, or toggle which where `held` is none, as Space x, Space d and Space t do on its line in the review.
     */
    hold(held: boolean | null, id: string | null = null): void {
        const part = this.partAt(id);
        if (part === null) {
            this.#shell.say("no part of the draft here: a comment, or a line of the review");
            return;
        }
        const now = held ?? !part.held;
        this.#rewritten(part.id, { ...part, held: now });
        this.#shell.say(now ? "kept back: it stays in the draft" : "it goes at the next send");
    }

    /**
     * Choose whom the comment at the cursor reaches, from the parties the document shows, as Space s does; outside a
     * comment, choose first, then write a new one under the cursor's line, reaching whom was chosen.
     */
    address(id: string | null = null): void {
        const part = this.partAt(id);
        const choices = parties(this.#shell);
        const window = this.#shell.window;
        if (choices.length === 0 || window === null) {
            this.#shell.say("the document shows no party to send a comment to");
            return;
        }
        const reviewing = window.role() === "review";
        window.pick(part === null ? "Write a comment to…" : "Send this comment to…", choices, (party) => {
            if (part !== null) {
                this.#rewritten(part.id, { ...part, to: party });
                this.#shell.say(`to ${named(party)}`);
                if (reviewing) {
                    window.review(this.#shell.review());
                }
                return;
            }
            const head = this.#shell.view.state.selection.main.head;
            const block = this.#blockAt(head);
            if (block === null) {
                this.#shell.say("nothing here takes a comment");
                return;
            }
            const index = Math.max(
                ownLines(block).findIndex((line) => head >= line.from && head <= line.to),
                0,
            );
            const written = this.#write(block, { first: index, last: index, start: 0, end: null, whole: false }, head);
            const held = written === null ? undefined : this.#heldBy(written.key);
            if (written === null || held === undefined) {
                return;
            }
            held.comment = { ...held.comment, to: party };
            this.#shell.view.dispatch({ selection: EditorSelection.cursor(offsetOf(written)), annotations: fromCore.of(true) });
            const cm = getCM(this.#shell.view);
            if (cm !== null) {
                Vim.handleKey(cm, "i", "mapping");
            }
        });
    }

    /** Write `comment` in place of the part of id `id`, at once, and lay out what its first line says again. */
    #rewritten(id: string, comment: Comment): void {
        const held = this.#held.get(id);
        if (held === undefined) {
            return;
        }
        held.comment = comment;
        held.written = false;
        this.flush();
        this.#shell.view.dispatch({ effects: redrawn.of(null), annotations: fromCore.of(true) });
    }

    /** Comment on the innermost block at the cursor whole, and write it, as Space `c` does. */
    commentWhole(): void {
        const head = this.#shell.view.state.selection.main.head;
        const block = this.#blockAt(head);
        if (block === null) {
            this.#shell.say("nothing here takes a comment");
            return;
        }
        const written = this.#write(block, { first: 0, last: 0, start: 0, end: null, whole: true }, head);
        if (written !== null) {
            this.#shell.view.dispatch({ selection: EditorSelection.cursor(offsetOf(written)), annotations: fromCore.of(true) });
        }
        const cm = getCM(this.#shell.view);
        if (cm !== null) {
            Vim.handleKey(cm, "i", "mapping");
        }
    }

    /** Write every comment changed since it was last written to the draft, as `:w` does. */
    flush(): void {
        if (this.#pause !== null) {
            clearTimeout(this.#pause);
            this.#pause = null;
        }
        for (const held of this.#held.values()) {
            if (!held.written && held.comment.words.trim() !== "") {
                this.#shell.source.write(held.comment);
                held.written = true;
            }
        }
    }

    /** Send the draft, every comment written first, as Ctrl+Enter does outside a comment. */
    send(): void {
        this.flush();
        this.#shell.say("sending…");
        this.#shell.source.send();
    }

    /** Lay out the draft as the core tells it, but the comment being written, which the page holds newer. */
    drafted(draft: Draft): void {
        const told = new Map(draft.comments.map((each) => [each.id, each]));
        for (const [id, held] of [...this.#held]) {
            if (id === this.#writing || told.has(id) || !held.written) {
                continue;
            }
            this.#unlay(held);
            this.#held.delete(id);
        }
        for (const comment of draft.comments) {
            if (comment.id === this.#writing) {
                continue;
            }
            const held = this.#held.get(comment.id);
            if (held === undefined) {
                this.#held.set(comment.id, { comment, key: null, written: true });
                continue;
            }
            if (!held.written) {
                continue;
            }
            const before = held.comment.words;
            held.comment = comment;
            const node = held.key === null ? null : this.#shell.document.node(held.key);
            if (node !== null && before !== comment.words) {
                const start = offsetOf(node);
                const size = node.size;
                this.#shell.document.rewrite(node.key, comment.words);
                this.#shell.view.dispatch({ changes: { from: start, to: start + size, insert: comment.words }, annotations: fromCore.of(true) });
            }
        }
        this.laid();
        this.#shell.view.dispatch({ effects: redrawn.of(null), annotations: fromCore.of(true) });
    }

    /** Say what a send did on the status line. */
    delivered(delivered: Delivered): void {
        const kept = delivered.stayed.length > 0 ? `; ${delivered.stayed.length} kept in the draft, each saying why` : "";
        this.#shell.say(`sent ${delivered.went.length}${kept}`);
    }

    /** Lay out each comment held whose block is laid out and which isn't yet: after every change to the document. */
    laid(): void {
        for (const held of this.#held.values()) {
            if (held.key !== null && this.#shell.document.node(held.key) !== null) {
                continue;
            }
            held.key = null;
            const block = this.#blockOf(held.comment.on);
            if (block === null) {
                continue;
            }
            const node = remark(`comment:${held.comment.id}`, held.comment.words, seat(block.head, held.comment.on));
            const changes = this.#shell.document.remark(block.key, node);
            held.key = node.key;
            this.#shell.view.dispatch({ changes, annotations: fromCore.of(true) });
        }
    }

    /**
     * Return where the passages the comments laid out quote are in the document: each line quoted whole, or the part of
     * it the passage covers.
     */
    quoted(): { from: number; to: number }[] {
        const ranges: { from: number; to: number }[] = [];
        for (const held of this.#held.values()) {
            const node = held.key === null ? null : this.#shell.document.node(held.key);
            const block = node?.parent ?? null;
            const quote = held.comment.on;
            if (block === null || quote.lines.length === 0) {
                continue;
            }
            const lines = ownLines(block).slice(quote.line, quote.line + quote.lines.length);
            let joined = 0;
            for (const line of lines) {
                const length = line.to - line.from;
                const from = Math.max(quote.start - joined, 0);
                const to = quote.end === null ? length : Math.min(quote.end - joined, length);
                if (to > from) {
                    ranges.push({ from: line.from + from, to: line.from + to });
                }
                joined += length + 1;
            }
        }
        return ranges;
    }

    /**
     * Return how many comments are laid out under `node`, its own among them: counted once for each text the document
     * has, since a comment laid out or taken out always changes it.
     */
    within(node: Node): number {
        const text = this.#shell.view.state.doc;
        let counts = this.#counts.get(text);
        if (counts === undefined) {
            counts = new Map();
            for (const held of this.#held.values()) {
                let at = held.key === null ? null : this.#shell.document.node(held.key);
                while (at !== null) {
                    counts.set(at.key, (counts.get(at.key) ?? 0) + 1);
                    at = at.parent;
                }
            }
            this.#counts.set(text, counts);
        }
        return counts.get(node.key) ?? 0;
    }

    /** Say what the comment keyed `key` says of itself on its first line; none where it's no comment's. */
    said(key: string): Said | null {
        const held = this.#heldBy(key);
        const node = this.#shell.document.node(key);
        const block = node?.parent ?? null;
        if (held === undefined || block === null) {
            return null;
        }
        const quote = held.comment.on;
        const shown = block.block?.version ?? null;
        const lines = quote.lines.length === 0 || quote.lines.every((line, at) => block.head[quote.line + at] === line);
        return {
            to: held.comment.to !== null ? named(held.comment.to) : reachesOf(block),
            outdated: (quote.version !== null && shown !== null && shown !== quote.version) || !lines,
            reason: held.comment.reason,
            held: held.comment.held,
        };
    }

    /** Return the comment node holding `from` to `to`, its text whole; none where they aren't inside one comment. */
    #around(from: number, to: number): Node | null {
        let node: Node | null = nodeAt(this.#shell.document.root, from);
        while (node !== null && node.kind !== "comment") {
            node = node.parent;
        }
        if (node === null) {
            return null;
        }
        const start = offsetOf(node);
        return from >= start && to <= start + node.size ? node : null;
    }

    #heldBy(key: string): Held | undefined {
        for (const held of this.#held.values()) {
            if (held.key === key) {
                return held;
            }
        }
        return undefined;
    }

    /** Return the innermost block holding `position` that a comment can be written under: one with lines of its own. */
    #blockAt(position: number): Node | null {
        let node: Node | null = nodeAt(this.#shell.document.root, position);
        while (node !== null && (node.block === null || node.head.length === 0)) {
            if (node.kind === "comment") {
                return null;
            }
            node = node.parent;
        }
        return node;
    }

    /** Return the block `quote` is on, as the document lays it out now; none where it isn't. */
    #blockOf(quote: Quote): Node | null {
        return quotedIn(this.#shell.document.root, quote);
    }

    /** Open a comment where vim went into insert mode at `head`: on the passage `refused` covered, else under the cursor's line. */
    #open(refused: Refused | null, head: number): void {
        const passage = refused !== null && refused.to > refused.from ? refused : null;
        const at = passage?.from ?? head;
        const block = this.#blockAt(at);
        if (block === null) {
            this.#shell.say("nothing here takes a comment");
            queueMicrotask(() => {
                const cm = getCM(this.#shell.view);
                if (cm !== null) {
                    Vim.handleKey(cm, "<Esc>", "mapping");
                }
            });
            return;
        }
        const lines = ownLines(block);
        const index = (position: number): number => {
            const found = lines.findIndex((line) => position >= line.from && position <= line.to);
            return found === -1 ? -1 : found;
        };
        const cursor = Math.max(index(at), 0);
        const quoted = passage === null ? null : { first: index(passage.from), last: index(Math.max(passage.from, passage.to - 1)) };
        if (passage === null || quoted === null || quoted.first === -1 || quoted.last === -1) {
            this.#write(block, { first: cursor, last: cursor, start: 0, end: null, whole: false }, head);
            return;
        }
        const first = lines[quoted.first];
        const last = lines[quoted.last];
        const whole = first !== undefined && last !== undefined && passage.from === first.from && passage.to >= last.to;
        this.#write(
            block,
            {
                first: quoted.first,
                last: quoted.last,
                start: whole ? 0 : joinedAt(lines, quoted.first, quoted.first, passage.from),
                end: whole ? null : joinedAt(lines, quoted.first, quoted.last, Math.min(passage.to, last?.to ?? passage.to)),
                whole: false,
            },
            head,
        );
    }

    /**
     * Write a new comment under `block`, on the lines `on` says, the cursor put in it once the key is done with, and come
     * back to `head` where it's dropped; return its node.
     */
    #write(block: Node, on: { first: number; last: number; start: number; end: number | null; whole: boolean }, head: number): Node | null {
        const section = sectionOf(block);
        if (section?.viewing === undefined || section.viewing === null || block.block === null) {
            return null;
        }
        const id = crypto.randomUUID();
        const quote: Quote = {
            viewing: section.viewing,
            block: block.block.id,
            version: block.block.version,
            lines: on.whole ? [] : block.head.slice(on.first, on.last + 1),
            line: on.whole ? 0 : on.first,
            start: on.start,
            end: on.end,
            within: within(section),
        };
        const comment: Comment = { id, on: quote, words: "", to: null, reason: null, warned: false, held: false };
        const node = remark(`comment:${id}`, "", on.whole ? 0 : on.last);
        const changes = this.#shell.document.remark(block.key, node);
        this.#held.set(id, { comment, key: node.key, written: false });
        this.#writing = id;
        this.#opened = head;
        this.#shell.view.dispatch({ changes, annotations: fromCore.of(true) });
        // Once the key is done with, vim having put the cursor where it would have written: into the comment.
        queueMicrotask(() => {
            if (this.#shell.document.node(node.key) !== null) {
                this.#shell.view.dispatch({ selection: EditorSelection.cursor(offsetOf(node)), annotations: fromCore.of(true) });
            }
        });
        return node;
    }

    /**
     * End the comment `id`, as insert mode ends or an edit out of it is made: one that says nothing is dropped, the cursor
     * put back at `back` where one is given; another is written.
     */
    #ended(id: string, back: number | null): void {
        const held = this.#held.get(id);
        if (held === undefined) {
            return;
        }
        if (held.comment.words.trim() !== "") {
            this.flush();
            return;
        }
        this.#unlay(held);
        this.#held.delete(id);
        if (held.written) {
            this.#shell.source.erase(id);
        }
        if (back !== null) {
            this.#shell.view.dispatch({ selection: EditorSelection.cursor(Math.min(back, this.#shell.view.state.doc.length)), annotations: fromCore.of(true) });
        }
    }

    /** Take `held`'s node out of the document, where it's laid out. */
    #unlay(held: Held): void {
        if (held.key === null) {
            return;
        }
        const changes = this.#shell.document.unremark(held.key);
        held.key = null;
        if (changes.length > 0) {
            this.#shell.view.dispatch({ changes, annotations: fromCore.of(true) });
        }
    }

    /**
     * Once the key that made a refused edit is done with: where it deleted lines of one comment whole, as `dd` on one
     * does, take them out of it, the comment with them where it was all of it; where it didn't go on into insert mode,
     * say the document's text isn't written in.
     */
    #settleRefused(): void {
        const refused = this.#refused;
        this.#refused = null;
        const vim = getCM(this.#shell.view)?.state.vim as { insertMode?: boolean } | undefined;
        if (refused === null || vim?.insertMode === true) {
            return;
        }
        const node = this.#overlapped(refused);
        const held = node === null ? undefined : this.#heldBy(node.key);
        if (node === null || held === undefined) {
            this.#shell.say("the document is the views'; write a comment with i, a, o or c");
            return;
        }
        const start = offsetOf(node);
        const end = start + node.size;
        const kept = [...node.head.keys()].flatMap((at) => {
            const lineStart = start + node.head.slice(0, at).reduce((sum, line) => sum + line.length + 1, 0);
            const lineEnd = lineStart + (node.head[at]?.length ?? 0);
            return refused.from <= lineStart && refused.to >= lineEnd ? [] : [node.head[at] ?? ""];
        });
        if (kept.length === 0 || (refused.from <= start && refused.to >= end)) {
            this.#unlay(held);
            this.#held.delete(held.comment.id);
            if (held.written) {
                this.#shell.source.erase(held.comment.id);
            }
            return;
        }
        const text = kept.join("\n");
        this.#shell.document.rewrite(node.key, text);
        this.#shell.view.dispatch({ changes: { from: start, to: end, insert: text }, annotations: fromCore.of(true) });
        held.comment = { ...held.comment, words: text, warned: false, reason: null };
        held.written = false;
        this.flush();
    }

    /** Return the comment a refused edit took whole lines of, reaching at most one newline past it either side; none where it didn't. */
    #overlapped(refused: Refused): Node | null {
        const node = this.#around(Math.min(refused.from + 1, refused.to), Math.min(refused.from + 1, refused.to));
        if (node === null) {
            return null;
        }
        const start = offsetOf(node);
        const end = start + node.size;
        return refused.from >= start - 1 && refused.to <= end + 1 ? node : null;
    }

    /** Write what's changed to the draft after a pause in typing. */
    #later(): void {
        if (this.#pause !== null) {
            clearTimeout(this.#pause);
        }
        this.#pause = setTimeout(() => {
            this.#pause = null;
            this.flush();
        }, this.pause);
    }
}

/** Return the parties `shell`'s document shows, each once, in the order it shows them, called by their summary. */
function parties(shell: Shell): Choice<Reached>[] {
    const seen = new Set<string>();
    return every(shell.document.root).flatMap((node) => {
        const reaches = node.block?.reaches ?? null;
        if (node.block?.block !== "fold" || node.block.kind !== "party" || reaches === null) {
            return [];
        }
        const key = JSON.stringify(reaches);
        if (seen.has(key)) {
            return [];
        }
        seen.add(key);
        return [{ name: node.block.summary[0]?.text.trim() ?? key, value: reaches as Reached }];
    });
}

/** Return which of a block's own lines a comment on `quote` goes under: the last it quotes, found again by what the quoted lines say where they moved. */
function seat(head: readonly string[], quote: Quote): number {
    const count = quote.lines.length;
    if (count === 0) {
        return 0;
    }
    const at = (line: number): boolean => quote.lines.every((text, offset) => head[line + offset] === text);
    if (at(quote.line)) {
        return quote.line + count - 1;
    }
    for (let distance = 1; distance < head.length; distance++) {
        for (const line of [quote.line - distance, quote.line + distance]) {
            if (line >= 0 && line + count <= head.length && at(line)) {
                return line + count - 1;
            }
        }
    }
    return Math.max(0, Math.min(quote.line + count - 1, head.length - 1));
}

/**
 * Return where `position`, in the line `line` of a block's own lines, falls in those lines from `first` on, joined by
 * newlines, as a quote counts a passage: the comments laid out between them skipped.
 */
function joinedAt(lines: readonly { from: number; to: number }[], first: number, line: number, position: number): number {
    const before = lines.slice(first, line).reduce((sum, each) => sum + (each.to - each.from) + 1, 0);
    return before + position - (lines[line]?.from ?? position);
}

/** Return the section `node` is in: the answer of the view that laid it out. */
export function sectionOf(node: Node): Node | null {
    let at = node.parent;
    while (at !== null && at.kind !== "section") {
        at = at.parent;
    }
    return at;
}

/**
 * Return the folds `section`'s view was read under, innermost first, each as the view whose block it is and its id, so
 * the core finds whom a comment in the section reaches where its own blocks name none.
 */
export function within(section: Node): Within[] {
    const folds: Within[] = [];
    let at = section.parent;
    while (at !== null) {
        const outer = sectionOf(at);
        if (at.block !== null && outer?.viewing !== undefined && outer.viewing !== null) {
            folds.push({ viewing: outer.viewing, block: at.block.id });
        }
        at = outer?.parent ?? null;
    }
    return folds;
}

/**
 * Return the block `quote` is on in the document under `root`, as the core finds it at a send: the first block of its
 * id in its view's answer, in the order they're shown; none where the document doesn't lay it out.
 */
export function quotedIn(root: Node, quote: Quote): Node | null {
    const wanted = viewKey(quote.viewing);
    for (const node of every(root)) {
        if (node.kind === "section" && node.viewing !== null && viewKey(node.viewing) === wanted) {
            const found = inSection(node, quote.block);
            if (found !== null) {
                return found;
            }
        }
    }
    return null;
}

/** Return the block of id `id` in `section`, its folds' given content among it, but not what a fold under it reads as it opens. */
function inSection(section: Node, id: string): Node | null {
    for (const child of section.children) {
        if (child.kind === "section" || child.kind === "comment") {
            continue;
        }
        if (child.block?.id === id) {
            return child;
        }
        const found = inSection(child, id);
        if (found !== null) {
            return found;
        }
    }
    return null;
}

/** Say whom a comment on `block` reaches: its block's party, else the nearest block holding it that names one. */
function reachesOf(block: Node): string {
    let at: Node | null = block;
    while (at !== null) {
        const reaches = at.block?.reaches ?? null;
        if (reaches !== null) {
            return named(reaches);
        }
        at = at.parent;
    }
    return "no one yet";
}
