// What the review's keys do, said three ways: in the one line of keys under it,
// those that apply where the cursor is (`barOf`); whole in the list `?` opens,
// in parts; and, once a key leading a chord is pressed, as Space is, in a panel
// listing the keys that may follow (`chords`; `Keys.tsx`). One table, so the
// three never disagree; the kinds of fold and their letters are one table too,
// read by the keys, the review's marks and its header, an agent's drawers among
// them. Pure (`docs/dashboard.md`, *The review*, *The drawers*).

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
 * lines; on a drawer's summary line or a line of its tasks; on the agent's words in its conversation; on a file's lines
 * in its "since you approved" drawer, or on the line of one standing as the operator last saw it, reviewed, which takes
 * no comment; on a line under an item or in a drawer that isn't the agent's or a file's, as a fold's summary or a call;
 * or on nothing, the review empty.
 */
export type ReviewPlace =
    | "insert"
    | "written"
    | "banner"
    | "approvals"
    | "item"
    | "change"
    | "file"
    | "drawer"
    | "words"
    | "since"
    | "reviewed"
    | "aside"
    | "nothing";

/** The kinds of drawer under an agent's banner, in the order they come: its task list, what its branch changed since the operator approved it, and its whole conversation. */
export type DrawerKind = "tasks" | "since" | "conversation";

/**
 * A kind of fold in the review: an item whole, a file, a function's or a class's body, a run of unchanged lines, an
 * item's context or an item's text in a conversation, one of an agent's drawers; and in a conversation, each exchange
 * before the operator's last words, a run of calls, and a call's input and output.
 */
export type FoldKind = "group" | "item" | "file" | "body" | "lines" | "context" | "earlier" | "calls" | "call" | DrawerKind;

/**
 * One kind of fold: the letter naming it, what its folds are called together, and what the one the cursor is in is
 * called, which `zf` and the letter closes; whether Space `z` `f` and its letter open them, the level `zr` and `zm` open
 * and close them at, the item's own first, and whether it's the fold holding the rest, as the item's own and a
 * drawer's are, which `zm` never closes. `back` folds open one at a time, the latest first, so each `zr` reaches one
 * step further back, and close the earliest first; `deep` ones only by their own keys, `za` or Space `z` `f` and the
 * letter, never by `zr` or `zR`, since what they hold is read as they open.
 */
export interface FoldKindKeys {
    kind: FoldKind;
    letter: string;
    called: string;
    one: string;
    chord: boolean;
    level: number;
    own: boolean;
    back?: boolean;
    deep?: boolean;
}

/**
 * Each kind of fold, outermost first, by the letter naming it: the mark beside its summary line; the key after `zf`
 * that closes the fold of that kind the cursor is in, as vim's fold keys begin with `z`; and, but for an item's own,
 * which its header's `za` folds, the key after Space `z` `f` that opens every fold of that kind in the item or the
 * drawer, as after Space `z` `F` it closes them.
 */
export const FOLD_KINDS: FoldKindKeys[] = [
    // An agent's group whole under its banner, where the layout trials give it a fold (`trials.ts`, `frame` or `nest`).
    { kind: "group", letter: "a", called: "agents' groups", one: "the agent's group", chord: true, level: 0, own: true },
    { kind: "item", letter: "i", called: "the item", one: "the item", chord: false, level: 0, own: true },
    { kind: "tasks", letter: "t", called: "the tasks", one: "the tasks", chord: true, level: 0, own: true },
    { kind: "since", letter: "s", called: "since you approved", one: "since you approved", chord: true, level: 0, own: true },
    { kind: "conversation", letter: "v", called: "the conversation", one: "the conversation", chord: true, level: 0, own: true },
    { kind: "file", letter: "f", called: "files", one: "the file", chord: true, level: 1, own: false },
    { kind: "earlier", letter: "e", called: "earlier exchanges", one: "the earlier exchange", chord: true, level: 1, own: false, back: true },
    { kind: "body", letter: "b", called: "bodies", one: "the body", chord: true, level: 2, own: false },
    { kind: "lines", letter: "u", called: "unchanged lines", one: "the unchanged lines", chord: true, level: 2, own: false },
    { kind: "calls", letter: "k", called: "runs of calls", one: "the run of calls", chord: true, level: 2, own: false },
    { kind: "context", letter: "c", called: "context", one: "the context", chord: true, level: 3, own: false },
    { kind: "call", letter: "d", called: "calls' input and output", one: "the call's input and output", chord: true, level: 4, own: false, deep: true },
];

/** The drawers, in the order they come under a banner. */
export const DRAWERS: DrawerKind[] = ["tasks", "since", "conversation"];

/** What the line of keys says where the cursor is, before its keys. */
export const REVIEW_PLACES: Record<ReviewPlace, string> = {
    insert: "-- INSERT --",
    written: "your comment",
    banner: "banner",
    approvals: "lup's approvals",
    item: "item",
    change: "change",
    file: "file",
    drawer: "drawer",
    words: "the agent's words",
    since: "since you approved",
    reviewed: "reviewed file",
    aside: "fold",
    nothing: "nothing waiting",
};

/** Ending a comment being written. */
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

/** Copying to the system clipboard and putting from it (`clipboard.ts`). */
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

/**
 * What the margin's labels, the stack's and the overview's marks say: how a thing stands, each in the state's own
 * colour; and apart, in the colour of what's written, what the next Ctrl+Enter does with it. Not keys: looked up here.
 */
const MARKS: Part<never>[] = [
    {
        title: "Marks in the margin and the overview",
        keys: [
            { keys: "◆", does: "an item waiting on you: a question, a held change, an approval, a hold at landing", short: "waiting", at: [] },
            { keys: "◇", does: "a file to review; beside an agent in the overview, how many its \"since you approved\" has (◇3)", short: "to review", at: [] },
            { keys: "⚑", does: "a file with a line that matters, held or flagged; lup's approvals in the overview", short: "flagged", at: [] },
            { keys: "·", does: "a file folded whole: automatic, a test, data, a first approval's", short: "folded", at: [] },
            { keys: "•", does: "news, to read rather than answer: a note, a turn's last words, a friction, how it went, a stop", short: "news", at: [] },
            { keys: "‖", does: "an item left for later", short: "parked", at: [] },
            { keys: "new", does: "an item that came after you last sent", short: "new", at: [] },
            { keys: "▶ ○ ✕", does: "an agent calling a tool, between calls, ended", short: "agents", at: [] },
            { keys: "» ✓ ✔", does: "in yellow, what your next Ctrl+Enter does with it: your comment on it goes, it's marked read, it's approved", short: "your reply", at: [] },
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
                does: "approve the approval or held change, the comments under it going with it; in \"since you approved\", mark the file reviewed at the version shown, approving its flagged writes where it still stands so: it's a line until the agent writes it again, then shows what changed since",
                short: "approve",
                at: ["change", "file", "since", "reviewed"],
            },
            {
                keys: "␣x",
                does: "decline it, the comments under it going with it",
                short: "decline",
                at: ["change", "file"],
            },
            { keys: "␣d", does: "mark the item read, folding it, or unmark it", short: "read", at: ["item", "change"] },
            { keys: "␣p", does: "park the item, leaving it for later, folded; on one parked, bring it back", short: "park", at: ["item"] },
            {
                keys: "␣A",
                does: "in \"since you approved\", mark every file it shows reviewed, as Space a does each",
                short: "all reviewed",
                at: ["since", "reviewed"],
            },
            { keys: "h", does: "on a banner, hold each flagged write of the agent and its subagents for your answer, or let them land again; elsewhere, vim's h", short: "hold", at: ["banner"] },
            { keys: "^⏎", does: "send the reply: every comment, message, remark and item marked read", short: "send", at: [] },
        ],
    },
    {
        title: "Commenting",
        keys: [
            { keys: "o", does: "comment on the line: an item's, a file's, or the agent's words in its conversation", short: "comment", at: ["item", "change", "file", "words", "since"] },
            {
                keys: "c…",
                does: "comment on the passage a motion covers: ct. ciw cip, cc the line",
                short: "on a passage",
                at: ["item", "change", "file", "words", "since"],
            },
            { keys: "C", does: "comment from the cursor to the line's end", short: "to its end", at: ["item", "words"] },
            { keys: "v… c", does: "comment on a selection: v or V and a motion, then c or s", short: "on a selection", at: [] },
            { keys: "␣c", does: "comment on the item whole", short: "on the item", at: ["item", "change"] },
            { keys: "o ␣c", does: "on a banner, write a message to its agent, which its drawers' remarks go with", short: "message", at: ["banner"] },
            { keys: "i a A", does: "in a comment, write in it, with vim's keys of insert mode", short: "write in it", at: ["written"] },
            {
                keys: "o O",
                does: "in a comment, a line below or above to write on; on a list's item, the next item or the one before it, at its indentation, with its bullet or its number, as ⏎ starts one",
                short: "line below above",
                at: [],
            },
            { keys: "u ^r", does: "undo and redo a change to the draft, a comment written one step", short: "undo redo", at: ["written"] },
            { keys: "g- g+", does: "the draft as it was a step earlier or later, what was undone then changed after among them", short: "earlier later", at: [] },
        ],
    },
    {
        title: "Moving",
        keys: [
            {
                keys: "]] [[",
                does: "next and previous item, on its first line that matters, or on the summary line of the closed fold hiding it, which, as every motion of vim's, it doesn't open; the view stays where it's in view, else it comes in a third of the view from the edge",
                short: "items",
                at: ["banner", "approvals", "item", "aside", "written", "drawer"],
            },
            {
                keys: "]a [a",
                does: "next and previous item to answer, in the order they came: a question, a held change, an approval, a hold at landing; news and what's marked read or left for later are passed over; the folds hiding where it lands open, said under the review; the view stays where it's in view, else it comes in a third of the view from the edge",
                short: "to answer",
                at: ["banner", "approvals", "item", "change", "aside", "written", "drawer"],
            },
            {
                keys: "]c [c",
                does: "next and previous line that matters, in what an approval, a held change or a \"since you approved\" drawer changes, the folds hiding it opening, said under the review; the view stays where it's in view, else it comes in a third of the view from the edge",
                short: "what matters",
                at: ["change", "file", "since", "reviewed"],
            },
            {
                keys: "]f [f",
                does: "next and previous file's header, in what an approval, a held change or a \"since you approved\" drawer changes: one folded whole on its header, which it doesn't open; one in a closed fold, or standing as you last saw it, a line with nothing under it, passed over; the view stays where it's in view, else it comes in a third of the view from the edge",
                short: "files",
                at: ["change", "file", "since", "reviewed"],
            },
            {
                keys: "^d ^u ^f ^b",
                does: "half a page or a page down or up, as vim's, stopping on the next file's header it reaches, as a motion repeated by a key held down does, j among them; held there until a key is pressed afresh, which goes on",
                short: "page",
                at: [],
            },
            {
                keys: "]n [n",
                does: "next and previous comment, message or remark written, where you last were in it, the folds hiding it opening, said under the review",
                short: "comments",
                at: ["written", "banner", "approvals", "item", "change", "file", "words", "since", "reviewed"],
            },
            {
                keys: "]q [q",
                does: "next and previous citation of your words in an agent's answer, the passage it cites opening under its line, the folds hiding it opening, said under the review",
                short: "citations",
                at: [],
            },
            {
                keys: "gd",
                does: "on a citation, go to the passage of your words it cites, above the answer; on that passage, back to the citation",
                short: "follow",
                at: [],
            },
            {
                keys: "/ n N",
                does: "search, then the next and previous match, the folds hiding it opening, said under the review; / then N searches back, ? being this list",
                short: "search",
                at: [],
            },
            {
                keys: "]g [g",
                does: "next and previous agent's group, on its banner, its fold's letter a in the margin; the view stays where it's in view, else it comes in a third of the view from the edge",
                short: "agents",
                at: ["banner", "approvals"],
            },
            {
                keys: "]i [i",
                does: "next and previous item, on its header, its fold's letter i in the margin; the view stays where it's in view, else it comes in a third of the view from the edge",
                short: "item headers",
                at: [],
            },
            {
                keys: "]t [t ]s [s ]v [v",
                does: "next and previous drawer of a kind, by its letter: tasks, since you approved, the conversation; the view stays where it's in view, else it comes in a third of the view from the edge",
                short: "drawers",
                at: ["banner", "drawer"],
            },
            { keys: "^k", does: "go to an agent's group", short: "go to", at: [] },
        ],
    },
    {
        title: "The overview",
        keys: [
            { keys: "\\", does: "hide the overview of every agent and item beside the review, or show it again; where it's the review zoomed out, zoom out to every header, or back", short: "overview", at: ["banner", "approvals"] },
            { keys: "gO", does: "take the keyboard to the overview, opening it, on a phone over the review: j k move, ⏎ goes there, Esc or q back", short: "into it", at: [] },
        ],
    },
    {
        title: "Folds",
        keys: [
            {
                keys: "za",
                does: "open or close the innermost fold the cursor is in: on an item's header or its own text, the item whole; on a drawer's summary line, the drawer; on a call's line, its input and output, read as it opens",
                short: "fold",
                at: ["item", "change", "file", "drawer", "words", "since", "reviewed", "aside"],
            },
            { keys: "zo zc", does: "open or close it", short: "open close", at: [] },
            {
                keys: "zr zm",
                does: "open or close one more level of the item or the drawer the cursor is in: its files, then their bodies and unchanged lines, then its context; in a conversation, the exchange before those open, one further back each time, then its runs of calls",
                short: "a level",
                at: ["file", "since", "reviewed", "drawer", "aside"],
            },
            { keys: "zR zM", does: "open or close every fold in the item or the drawer the cursor is in, but for calls' input and output, which za and ␣zfd open", short: "all of it", at: ["aside", "drawer"] },
            {
                keys: "zf",
                does: "and a letter: close the fold of its kind the cursor is in, the file, the run of unchanged lines, the item, a drawer, or in a conversation an earlier exchange, a run of calls or a call's input and output, the cursor going to its summary line",
                short: "close one",
                at: ["file", "since", "reviewed", "aside"],
            },
            ...FOLD_KINDS.map((each) => ({ keys: `zf${each.letter}`, does: `close ${each.one} the cursor is in`, short: each.one, at: [] })),
            {
                keys: "␣z",
                does: "f or F, then a letter: open or close every fold of its kind in the item or the drawer the cursor is in",
                short: "by kind",
                at: ["file", "since", "reviewed", "drawer", "aside", "banner"],
            },
            {
                keys: "␣zf",
                does: "and a letter: open every fold of its kind in the item or the drawer the cursor is in, or, on a banner, that drawer of the agent's",
                short: "open by kind",
                at: [],
            },
            {
                keys: "␣zF",
                does: "and a letter: close every fold of its kind in the item or the drawer the cursor is in, or, on a banner, that drawer of the agent's",
                short: "close by kind",
                at: [],
            },
            ...FOLD_KINDS.filter((each) => each.chord).map((each) => ({
                keys: `␣zf${each.letter} ␣zF${each.letter}`,
                does: `open or close ${each.called}`,
                short: each.called,
                at: [],
            })),
            {
                keys: "zj zk",
                does: "to the start of the next fold, or the end of the one before, a folded one counting as its summary line",
                short: "next fold",
                at: ["aside", "drawer"],
            },
            {
                keys: "[z ]z",
                does: "to the start or the end of the open fold the cursor is in; again, of the one around it",
                short: "its ends",
                at: [],
            },
        ],
    },
    ...MARKS,
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
 * Return the keys that may follow `pressed`, the keys of a chord pressed so far as the list writes them (`␣`, `␣z`, `zf`),
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
