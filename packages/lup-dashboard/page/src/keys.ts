// What each view's keys do, said three ways: in the one line of keys under it,
// those that apply where the cursor is (`barOf`); whole in the list `?` opens,
// in parts; and, once a key leading a chord is pressed, as Space is, in a panel
// listing the keys that may follow (`chords`; `Keys.tsx`). One table a view, so
// the three never disagree; the kinds of fold and their letters are one table
// too, read by the keys, the review's marks and its header. Pure
// (`docs/dashboard.md`, *The review*).

/** One key, or a few doing alike: how it's pressed, what it does, and where the line of keys shows it. */
export interface Key<P extends string> {
    /** As it's pressed: `␣` for Space, `^` for Ctrl, `…` for a motion. */
    keys: string;
    /** What it does, whole, as the list says it. */
    does: string;
    /** What it does, short, as the line of keys says it. */
    short: string;
    /** Where the cursor is when the line of keys shows it. */
    at: readonly P[];
}

/** One part of the list: its title, and its keys. */
export interface Part<P extends string> {
    title: string;
    keys: Key<P>[];
}

/**
 * Where the cursor is in the review, for the line of keys: writing a comment; on one written; on an agent's banner, or
 * on lup's approvals'; on an item's own lines, an approval's or a held change's as a change; on a changed file's
 * lines, a flagged write's apart, since it's read rather than approved; on a line under an item that isn't its own, as
 * a fold's summary; or on nothing, the review empty.
 */
export type ReviewPlace = "insert" | "written" | "banner" | "approvals" | "item" | "change" | "file" | "flagged" | "aside" | "nothing";

/** A kind of fold in the review: an item whole, a file, a function's or a class's body, a run of unchanged lines, an item's context. */
export type FoldKind = "item" | "file" | "body" | "lines" | "context";

/**
 * One kind of fold: the letter naming it, what its folds are called together, whether Space `z` and its letter open
 * them, and the level `zr` and `zm` open and close them at, the item's own first.
 */
export interface FoldKindKeys {
    kind: FoldKind;
    letter: string;
    called: string;
    chord: boolean;
    level: number;
}

/**
 * Each kind of fold, outermost first, by the letter naming it: the mark beside its summary line, and, but for an
 * item's own, which its header's `za` folds, the key after Space `z`, as vim's fold keys begin with `z`, that opens
 * every fold of that kind in the item, as Shift and the letter closes them.
 */
export const FOLD_KINDS: FoldKindKeys[] = [
    { kind: "item", letter: "i", called: "the item", chord: false, level: 0 },
    { kind: "file", letter: "f", called: "files", chord: true, level: 1 },
    { kind: "body", letter: "b", called: "bodies", chord: true, level: 2 },
    { kind: "lines", letter: "u", called: "unchanged lines", chord: true, level: 2 },
    { kind: "context", letter: "c", called: "context", chord: true, level: 3 },
];

/** Where the cursor is in a conversation, for the line of keys: writing a comment, or not. */
export type ConversationPlace = "insert" | "normal";

/** What the line of keys says where the cursor is, before its keys. */
export const REVIEW_PLACES: Record<ReviewPlace, string> = {
    insert: "-- INSERT --",
    written: "your comment",
    banner: "banner",
    approvals: "lup's approvals",
    item: "item",
    change: "change",
    file: "file",
    flagged: "flagged file",
    aside: "fold",
    nothing: "nothing waiting",
};

/** What the line of keys says where the cursor is in a conversation, before its keys. */
export const CONVERSATION_PLACES: Record<ConversationPlace, string> = {
    insert: "-- INSERT --",
    normal: "conversation",
};

/** Ending a comment being written, the same in each view. */
const WRITING: Part<"insert">[] = [
    {
        title: "Writing a comment",
        keys: [
            { keys: "^⏎", does: "end it, back on what it's about", short: "end it", at: ["insert"] },
            { keys: "⏎", does: "in a list, the next item at the same indentation, with its bullet or the next number; on an empty item, the list's end", short: "next item", at: [] },
            { keys: "Esc", does: "end it where it is", short: "end it here", at: ["insert"] },
            { keys: "Esc u", does: "end it and drop it", short: "drop it", at: ["insert"] },
        ],
    },
];

/** Copying to the system clipboard and putting from it, the same in each view (`clipboard.ts`). */
const COPYING: Part<never>[] = [
    {
        title: "The clipboard",
        keys: [
            {
                keys: '"+y "*y',
                does: 'yank into the system clipboard: "+yy a line, v, a motion and "+y a selection; where " is a dead key, " then Space; a page on plain http keeps it to itself, and says so',
                short: "copy",
                at: [],
            },
            { keys: '"+p "*p', does: "put the system clipboard after the cursor, in a comment, once the browser lets the page read it", short: "put", at: [] },
            { keys: "v… ^c", does: "copy the selection, wherever the page is served", short: "copy it", at: [] },
        ],
    },
];

/** The keys of this list, which the line of keys says at its end, wherever the cursor is. */
const LIST: Part<never>[] = [{ title: "This list", keys: [{ keys: "?", does: "open it; Esc, q or ? closes it", short: "all keys", at: [] }] }];

/** The review's keys. */
export const REVIEW_KEYS: Part<ReviewPlace>[] = [
    ...WRITING,
    {
        title: "Answering",
        keys: [
            {
                keys: "␣a",
                does: "approve the approval or held change, the comments under it going with it; a flagged write, mark it read, approving it, as ␣d does",
                short: "approve",
                at: ["change", "file"],
            },
            {
                keys: "␣x",
                does: "decline it, the comments under it going with it; a flagged write is read or commented on, never declined",
                short: "decline",
                at: ["change", "file"],
            },
            { keys: "␣d", does: "mark the item read, folding it, or unmark it", short: "read", at: ["item", "change", "flagged"] },
            { keys: "␣p", does: "park the item, leaving it for later, folded; on one parked, bring it back", short: "park", at: ["item"] },
            { keys: "^⏎", does: "send the reply: every comment, message and item marked read", short: "send", at: [] },
        ],
    },
    {
        title: "Commenting",
        keys: [
            { keys: "o", does: "comment on the line", short: "comment", at: ["item", "change", "file", "flagged"] },
            {
                keys: "c…",
                does: "comment on the passage a motion covers: ct. ciw cip, cc the line",
                short: "on a passage",
                at: ["item", "change", "file", "flagged"],
            },
            { keys: "C", does: "comment from the cursor to the line's end", short: "to its end", at: ["item"] },
            { keys: "v… c", does: "comment on a selection: v or V and a motion, then c or s", short: "on a selection", at: [] },
            { keys: "␣c", does: "comment on the item whole", short: "on the item", at: ["item", "change"] },
            { keys: "o ␣c", does: "on a banner, write a message to its agent", short: "message", at: ["banner"] },
            { keys: "i a A", does: "in a comment, write in it, with vim's keys of insert mode", short: "write in it", at: ["written"] },
            { keys: "u ^r", does: "undo and redo a change to the draft, a comment written one step", short: "undo redo", at: ["written"] },
            { keys: "g- g+", does: "the draft as it was a step earlier or later, what was undone then changed after among them", short: "earlier later", at: [] },
        ],
    },
    {
        title: "Moving",
        keys: [
            { keys: "]] [[", does: "next and previous item, on its first line that matters", short: "items", at: ["banner", "approvals", "item", "aside", "written"] },
            {
                keys: "]a [a",
                does: "next and previous item to answer, in the order they came: a question, a held change, an approval, a hold at landing; news, flags and what's marked read or left for later are passed over",
                short: "to answer",
                at: ["banner", "approvals", "item", "change", "aside", "written"],
            },
            {
                keys: "]c [c",
                does: "next and previous line that matters, in what an approval, a held change or a flagged write changes",
                short: "what matters",
                at: ["change", "file", "flagged"],
            },
            {
                keys: "]n [n",
                does: "next and previous comment or message written, where you last were in it",
                short: "comments",
                at: ["written", "banner", "approvals", "item", "change", "file", "flagged"],
            },
            { keys: "␣h", does: "to the agents' tree; Space l there comes back", short: "agents", at: ["banner", "approvals", "nothing"] },
            { keys: "^k", does: "go to an agent's conversation, or the review", short: "go to", at: [] },
        ],
    },
    {
        title: "Folds",
        keys: [
            {
                keys: "za",
                does: "open or close the innermost fold the cursor is in: on an item's header or its own text, the item whole",
                short: "fold",
                at: ["item", "change", "file", "flagged", "aside"],
            },
            { keys: "zo zc", does: "open or close it", short: "open close", at: [] },
            {
                keys: "zr zm",
                does: "open or close one more level of the item the cursor is in: its files, then their bodies and unchanged lines, then its context",
                short: "a level",
                at: ["file", "flagged", "aside"],
            },
            { keys: "zR zM", does: "open or close every fold in the item the cursor is in", short: "all of it", at: ["aside"] },
            {
                keys: "␣z",
                does: "and a letter: open every fold of its kind in the item the cursor is in; Shift and the letter closes them",
                short: "by kind",
                at: ["file", "flagged", "aside"],
            },
            ...FOLD_KINDS.filter((each) => each.chord).map((each) => ({
                keys: `␣z${each.letter} ␣z${each.letter.toUpperCase()}`,
                does: `open or close the item's ${each.called}`,
                short: each.called,
                at: [],
            })),
            {
                keys: "zj zk",
                does: "to the start of the next fold, or the end of the one before, a folded one counting as its summary line",
                short: "next fold",
                at: ["aside"],
            },
            {
                keys: "[z ]z",
                does: "to the start or the end of the open fold the cursor is in; again, of the one around it",
                short: "its ends",
                at: [],
            },
        ],
    },
    ...COPYING,
    ...LIST,
];

/** A conversation's keys. */
export const CONVERSATION_KEYS: Part<ConversationPlace>[] = [
    ...WRITING,
    {
        title: "Commenting",
        keys: [
            { keys: "o", does: "comment on the agent's line", short: "comment", at: ["normal"] },
            { keys: "c…", does: "comment on the passage a motion covers", short: "on a passage", at: ["normal"] },
            { keys: "C", does: "comment from the cursor to the line's end", short: "to its end", at: [] },
            { keys: "v… c", does: "comment on a selection", short: "on a selection", at: [] },
            { keys: "␣c", does: "write your message on the whole, at the end", short: "message", at: ["normal"] },
            { keys: "u ^r", does: "undo and redo a change to what you wrote", short: "undo redo", at: [] },
            { keys: "g- g+", does: "what you wrote as it was a step earlier or later, what was undone then changed after among them", short: "earlier later", at: [] },
            { keys: "^⏎", does: "send the comments and the message, as one message", short: "send", at: [] },
        ],
    },
    {
        title: "Moving",
        keys: [
            { keys: "]] [[", does: "next and previous turn", short: "turns", at: ["normal"] },
            { keys: "]n [n", does: "next and previous comment written, where you last were in it", short: "comments", at: ["normal"] },
            { keys: "␣r", does: "back to the review", short: "review", at: ["normal"] },
            { keys: "␣h", does: "to the agents' tree", short: "agents", at: [] },
        ],
    },
    {
        title: "Folds",
        keys: [
            { keys: "za", does: "open or close the fold the cursor is on", short: "fold", at: ["normal"] },
            { keys: "zR zM", does: "open or close them all", short: "all", at: [] },
        ],
    },
    ...COPYING,
    ...LIST,
];

/** Return the keys the line of keys shows with the cursor at `place`, in the list's order: those that apply there. */
export function barOf<P extends string>(parts: Part<P>[], place: P): Key<P>[] {
    return parts.flatMap((part) => part.keys.filter((key) => key.at.includes(place)));
}

/** A key that may follow those of a chord pressed so far: the keys, each the next one alone, and what it does, short and whole. */
export interface Following {
    keys: string[];
    short: string;
    does: string;
}

/**
 * Return the keys that may follow `pressed`, the keys of a chord pressed so far as the list writes them (`␣`, `␣z`),
 * with the cursor at `place`, in the list's order: each key of `parts` that `pressed` begins and one more key ends,
 * once by that key; of two that share it, as `␣c` on an item and on a banner, the one the line of keys shows at `place`,
 * else the first. A key leading further, as `␣z`, shows by its own line of the list. None before a chord is begun.
 */
export function chords<P extends string>(parts: Part<P>[], pressed: string, place: P): Following[] {
    if (pressed === "") {
        return [];
    }
    const found = new Map<string, { following: Following; here: boolean }>();
    for (const key of parts.flatMap((part) => part.keys)) {
        const next = key.keys
            .split(" ")
            .filter((each) => each.startsWith(pressed) && [...each].length === [...pressed].length + 1)
            .map((each) => each.slice(pressed.length));
        const first = next[0];
        if (first === undefined) {
            continue;
        }
        const here = key.at.includes(place);
        const kept = found.get(first);
        if (kept === undefined || (here && !kept.here)) {
            found.set(first, { following: { keys: next, short: key.short, does: key.does }, here });
        }
    }
    return [...found.values()].map((each) => each.following);
}
