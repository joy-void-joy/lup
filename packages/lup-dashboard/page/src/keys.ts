// What the review's keys do, said four ways: in the one line of keys under it,
// what the cursor is on and what each verb would do to it (`Here`, from
// `grammar.ts`'s walk); whole in the palette `?` opens, searchable, those that
// apply where the cursor is first (`Palette.tsx`'s `KeyPalette`); and, once a key leading a chord
// is pressed, as Space is, in a panel listing the keys that may follow
// (`chords`; `Keys.tsx`). One table, so they never disagree, made from the kinds
// of fold and the verbs the looks declare (`looks.ts`), an agent's drawers among
// them, whose letters the fold keys take; it says nothing about one keyboard
// layout. Pure (`docs/dashboard.md`, *The review*, *The keys*).
import type { Kind, Verb } from "./looks";

/** One key, or a few doing alike: how it's pressed, what it does, whole and short. */
export interface Key {
    /** As it's pressed: `␣` for Space, `^` for Ctrl, `…` for a motion; several, between spaces, doing alike. */
    keys: string;
    /** What it does, whole, as the palette says it. */
    does: string;
    /** What it does, short, as the chord panel says it. */
    short: string;
}

/** One part of the palette: its title, and its keys. */
export interface Part {
    title: string;
    keys: Key[];
}

/** What a verb would do where the cursor is: its keys, what it does there, and what it's on where that isn't what the cursor is on. */
export interface Reached {
    keys: string;
    says: string;
    on: string | null;
}

/** What the line of keys says where the cursor is: what it's on, and what each verb would do to it; or, writing, the keys that end the comment. */
export interface Here {
    on: string;
    reached: Reached[];
}

/** A kind of drawer under an agent's banner, by the name of the view it shows, which its fold's kind is named for: `tasks`, `since`, `conversation`. */
export type DrawerKind = string;

/** A kind of fold in the review, by its name, as the looks declare it (`Kind`): `item`, `file`, `earlier`, a drawer's. */
export type FoldKind = string;

/** What the line of keys says while a comment is written, before the keys that end it, which it lists (`WRITING`). */
export const WRITING_HERE = "-- INSERT --";

/** The keys of `WRITING` the line of keys lists while a comment is written: those ending it. */
export const ENDING = ["^⏎", "Esc", "Esc u"];

/** Ending a comment being written. */
export const WRITING: Part[] = [
    {
        title: "Writing a comment",
        keys: [
            { keys: "^⏎", does: "end it, back on what it's about", short: "end it" },
            { keys: "⏎", does: "a new line at the indentation of the one it's on, with no bullet or number: type - or 1. where you want an item", short: "new line" },
            { keys: "Tab ⇧Tab", does: "move the line in or out by the list's indentation, as >> and << do", short: "in out" },
            {
                keys: "^t ^d",
                does: "the same, as vim's own keys, where ^t reaches the page: a browser tab keeps it to open a tab",
                short: "in out",
            },
            { keys: "Esc", does: "end it where it is", short: "end it here" },
            { keys: "Esc u", does: "end it and drop it", short: "drop it" },
        ],
    },
];

/** Copying to the system clipboard and putting from it (`clipboard.ts`). */
const COPYING: Part[] = [
    {
        title: "The clipboard",
        keys: [
            {
                keys: '"+y "*y',
                does: 'yank into the system clipboard: "+yy a line, v, a motion and "+y a selection; where " is a dead key, " then Space; a page on plain http keeps it to itself, and says so',
                short: "copy",
            },
            { keys: '"+p "*p', does: "put the system clipboard after the cursor, in a comment, once the browser lets the page read it", short: "put" },
            { keys: "v… ^c", does: "copy the selection, wherever the page is served", short: "copy it" },
        ],
    },
];

/**
 * What the margin's labels, the stack's and the overview's marks say: how a thing stands, each in the state's own
 * colour; and apart, in the colour of what's written, what the next Ctrl+Enter does with it. Not keys: looked up here.
 */
const MARKS: Part[] = [
    {
        title: "Marks in the margin and the overview",
        keys: [
            { keys: "◆", does: "an item waiting on you: a question, a held change, an approval, a hold at landing", short: "waiting" },
            { keys: "◇", does: "a file to review; beside an agent in the overview, how many its \"since you approved\" has (◇3)", short: "to review" },
            { keys: "⚑", does: "a file with a line that matters, held or flagged; lup's approvals in the overview", short: "flagged" },
            { keys: "·", does: "a file folded whole: automatic, a test, data, a first approval's", short: "folded" },
            { keys: "•", does: "news, to read rather than answer: a note, a turn's last words, a friction, how it went, a stop", short: "news" },
            { keys: "‖", does: "an item left for later", short: "parked" },
            { keys: "new", does: "an item that came after you last sent", short: "new" },
            { keys: "▶ ○ ✕", does: "an agent calling a tool, between calls, ended", short: "agents" },
            { keys: "» ✓ ✔ ✗", does: "in yellow, what your next Ctrl+Enter does with it: your comment on it goes, it's marked read, it's approved, it's declined", short: "your reply" },
        ],
    },
];

/** The keys of this list, which the line of keys says at its end, wherever the cursor is. */
const LIST: Part[] = [{ title: "This palette", keys: [{ keys: "?", does: "open it, every key searchable, what applies where the cursor is first; ⏎ does the one chosen, Esc closes it", short: "all keys" }] }];

/**
 * What each verb lup's own modules declare does, whole, as the palette says it (`lup.SHELL_VERBS`, `Core.verbs`): on the
 * innermost thing at the cursor it applies to, from the cursor outward, a mark in the draft, shown on what it marks,
 * undone with u and sent with Ctrl+Enter, the key pressed again taking it off. A module's own verb says what it's called.
 */
const VERBS: Readonly<Record<string, string>> = {
    done: "mark it done: an item read; an approval or a held change approved, the comments under it going with it; a file of \"since you approved\" reviewed at the version shown, approving its flagged writes where it still stands so; on the drawer's line, every file it shows; on a banner, the agent's own items and drawers, its subagents' left as they are",
    decline: "decline an approval or a held change, the comments under it going with it; a comment never declines",
    send: "leave the item for later, folded at the review's end, where what's drafted on it stays drafted as the rest is sent; on one left for later, bring it back; sending to an agent or a named pile comes with piles (#312)",
    comment: "comment on it whole: an item; on a banner, a message to its agent, which its drawers' remarks go with; in a drawer, a remark on the line",
    hold: "from anywhere in an agent's group, hold each flagged write of the agent and its subagents for your answer, or let them land again",
    pause: "pause the agent at its next call until it's resumed: not built yet, its host side designed beside #157",
};

/**
 * Return the review's keys, with the kinds of fold known now, outermost first (`kinds`, `looks.ts`): each kind's letter,
 * after `zf` closing the one the cursor is in, and after Space `z` `f` or `F` opening or closing every one; each
 * drawer's after `]` and `[`. A kind with no letter, another kind having taken it, is reached by the generic keys
 * alone. And the verbs known now (`verbs`), each Space and its key, in the order declared, the core's first.
 */
export function reviewKeys(kinds: readonly Kind[], verbs: readonly Verb[] = []): Part[] {
    const lettered = kinds.flatMap((each) => (each.letter === null ? [] : [{ ...each, letter: each.letter }]));
    const drawers = lettered.filter((each) => each.drawer);
    return [
    ...WRITING,
    {
        title: "Answering",
        keys: [
            ...verbs.map((verb) => ({
                keys: `␣${verb.key}`,
                does: VERBS[verb.name] ?? `${verb.called}, on the innermost thing at the cursor that offers it`,
                short: verb.called,
            })),
            { keys: "u", does: "take back the last mark or comment, as any change to the draft", short: "undo" },
            { keys: "^⏎", does: "send the reply: every comment, message and remark, and every mark, each item marked done, declined or read, each file marked reviewed, each agent's writes held", short: "send" },
        ],
    },
    {
        title: "Commenting",
        keys: [
            { keys: "o", does: "comment on the line: an item's, a file's, or the agent's words in its conversation, a remark; on a banner, a message to its agent, which its drawers' remarks go with", short: "comment" },
            {
                keys: "c…",
                does: "comment on the passage a motion covers: ct. ciw cip, cc the line",
                short: "on a passage",
            },
            { keys: "C", does: "comment from the cursor to the line's end", short: "to its end" },
            { keys: "v… c", does: "comment on a selection: v or V and a motion, then c or s", short: "on a selection" },
            { keys: "i a A", does: "in a comment, write in it, with vim's keys of insert mode", short: "write in it" },
            { keys: "o O", does: "in a comment, a line below or above to write on, at the line's indentation, with no bullet or number", short: "line below above" },
            {
                keys: ">> <<",
                does: "in a comment, move the line in, nested under the item above it where its words begin, or out, to the item it's in; > and < with a motion or a selection move each line by as much as the first",
                short: "in out",
            },
            { keys: "u ^r", does: "undo and redo a change to the draft, a comment written one step", short: "undo redo" },
            { keys: "g- g+", does: "the draft as it was a step earlier or later, what was undone then changed after among them", short: "earlier later" },
        ],
    },
    {
        title: "Moving",
        keys: [
            {
                keys: "]] [[",
                does: "next and previous item, on its first line that matters, or on the summary line of the closed fold hiding it, which, as every motion of vim's, it doesn't open; the view stays where it's in view, else it comes in a third of the view from the edge",
                short: "items",
            },
            {
                keys: "]a [a",
                does: "next and previous item to answer, in the order they came: a question, a held change, an approval, a hold at landing; news and what's marked read or left for later are passed over; the folds hiding where it lands open, said under the review; the view stays where it's in view, else it comes in a third of the view from the edge",
                short: "to answer",
            },
            {
                keys: "]c [c",
                does: "next and previous line that matters, in what an approval, a held change or a \"since you approved\" drawer changes, the folds hiding it opening, said under the review; the view stays where it's in view, else it comes in a third of the view from the edge",
                short: "what matters",
            },
            {
                keys: "]f [f",
                does: "next and previous file's header, in what an approval, a held change or a \"since you approved\" drawer changes: one folded whole on its header, which it doesn't open; one in a closed fold, or standing as you last saw it, a line with nothing under it, passed over; the view stays where it's in view, else it comes in a third of the view from the edge",
                short: "files",
            },
            {
                keys: "^d ^u ^f ^b",
                does: "half a page or a page down or up, as vim's, stopping on the next file's header it reaches, as a motion repeated by a key held down does, j among them; held there until a key is pressed afresh, which goes on",
                short: "page",
            },
            {
                keys: "]n [n",
                does: "next and previous comment, message or remark written, where you last were in it, the folds hiding it opening, said under the review",
                short: "comments",
            },
            {
                keys: "]q [q",
                does: "next and previous citation of your words in an agent's answer, the passage it cites opening under its line, the folds hiding it opening, said under the review",
                short: "citations",
            },
            {
                keys: "gd",
                does: "on a citation, go to the passage of your words it cites, above the answer; on that passage, back to the citation",
                short: "follow",
            },
            {
                keys: "/ n N",
                does: "search, then the next and previous match, the folds hiding it opening, said under the review; / then N searches back, ? being this list",
                short: "search",
            },
            {
                keys: "]g [g",
                does: "next and previous agent's group, on its banner, its fold's letter a in the margin; the view stays where it's in view, else it comes in a third of the view from the edge",
                short: "agents",
            },
            {
                keys: "]i [i",
                does: "next and previous item, on its header, its fold's letter i in the margin; the view stays where it's in view, else it comes in a third of the view from the edge",
                short: "item headers",
            },
            ...(drawers.length === 0
                ? []
                : [
                      {
                          keys: drawers.map((each) => `]${each.letter} [${each.letter}`).join(" "),
                          does: `next and previous drawer of a kind, by its letter: ${drawers.map((each) => each.called).join(", ")}; the view stays where it's in view, else it comes in a third of the view from the edge`,
                          short: "drawers",
                      },
                  ]),
            { keys: "^k", does: "go to an agent's group", short: "go to" },
        ],
    },
    {
        title: "The overview",
        keys: [
            { keys: "\\", does: "hide the overview of every agent and item beside the review, or show it again", short: "overview" },
            { keys: "gO", does: "take the keyboard to the overview, opening it, on a phone over the review: j k move, ⏎ goes there, Esc or q back", short: "into it" },
        ],
    },
    {
        title: "Folds",
        keys: [
            {
                keys: "za",
                does: "open or close the innermost fold the cursor is in: on an item's header or its own text, the item whole; on a drawer's summary line, the drawer; on a call's line, its input and output, read as it opens",
                short: "fold",
            },
            { keys: "zo zc", does: "open or close it", short: "open close" },
            {
                keys: "zr zm",
                does: "open or close one more level of the item or the drawer the cursor is in: its files, then their bodies and unchanged lines, then its context; in a conversation, the exchange before those open, one further back each time, then its runs of calls",
                short: "a level",
            },
            { keys: "zR zM", does: "open or close every fold in the item or the drawer the cursor is in, but for calls' input and output, which za and ␣zfd open", short: "all of it" },
            {
                keys: "zf",
                does: "and a letter: close the fold of its kind the cursor is in, the file, the run of unchanged lines, the item, a drawer, or in a conversation an earlier exchange, a run of calls or a call's input and output, the cursor going to its summary line",
                short: "close one",
            },
            ...lettered.map((each) => ({ keys: `zf${each.letter}`, does: `close ${each.one} the cursor is in`, short: each.one })),
            {
                keys: "␣z",
                does: "f or F, then a letter: open or close every fold of its kind in the item or the drawer the cursor is in",
                short: "by kind",
            },
            {
                keys: "␣zf",
                does: "and a letter: open every fold of its kind in the item or the drawer the cursor is in, or, on a banner, that drawer of the agent's",
                short: "open by kind",
            },
            {
                keys: "␣zF",
                does: "and a letter: close every fold of its kind in the item or the drawer the cursor is in, or, on a banner, that drawer of the agent's",
                short: "close by kind",
            },
            ...lettered.filter((each) => each.chord).map((each) => ({
                keys: `␣zf${each.letter} ␣zF${each.letter}`,
                does: `open or close ${each.called}`,
                short: each.called,
            })),
            {
                keys: "zj zk",
                does: "to the start of the next fold, or the end of the one before, a folded one counting as its summary line",
                short: "next fold",
            },
            {
                keys: "[z ]z",
                does: "to the start or the end of the open fold the cursor is in; again, of the one around it",
                short: "its ends",
            },
        ],
    },
    ...MARKS,
    ...COPYING,
    ...LIST,
    ];
}

/** A key that may follow those of a chord pressed so far: the keys, each the next one alone, and what it does, short and whole. */
export interface Following {
    keys: string[];
    short: string;
    does: string;
}

/**
 * Return the keys that may follow `pressed`, the keys of a chord pressed so far as the list writes them (`␣`, `␣z`, `zf`),
 * in the list's order: each key of `parts` that `pressed` begins and one more key ends, once by that key, the first
 * saying it. A key leading further, as `␣z`, shows by its own line of the list. None before a chord is begun.
 */
export function chords(parts: readonly Part[], pressed: string): Following[] {
    if (pressed === "") {
        return [];
    }
    const found = new Map<string, Following>();
    for (const key of parts.flatMap((part) => part.keys)) {
        const next = key.keys
            .split(" ")
            .filter((each) => each.startsWith(pressed) && [...each].length === [...pressed].length + 1)
            .map((each) => each.slice(pressed.length));
        const first = next[0];
        if (first !== undefined && !found.has(first)) {
            found.set(first, { keys: next, short: key.short, does: key.does });
        }
    }
    return [...found.values()];
}
