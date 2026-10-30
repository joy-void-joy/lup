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
            { keys: "◇", does: "a file to review; beside an agent in the overview, how many their \"since you approved\" has (◇3)", short: "to review" },
            { keys: "⚑", does: "a file with a line that matters, held or flagged; lup's approvals in the overview", short: "flagged" },
            { keys: "·", does: "a file folded whole: automatic, a test, data, a first approval's", short: "folded" },
            { keys: "•", does: "news, to read rather than answer: a note, a turn's last words, a friction, how it felt, a stop", short: "news" },
            { keys: "‖", does: "an item left for later", short: "parked" },
            { keys: "new", does: "an item that came after you last marked its agent seen, Space d on their banner, and that you haven't commented on", short: "new" },
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
    done: "mark it done: an item read; an approval or a held change approved, the comments under it going with it; a file of \"since you approved\" reviewed at the version shown, approving its flagged writes where it still stands so; on the drawer's line, every file it shows; a conversation read up to its last step; on a banner, the agent seen, their own items and drawers, their subagents' left as they are",
    decline: "decline an approval or a held change, the comments under it going with it; a comment never declines",
    send: "leave the item for later, folded at the review's end, where what's drafted on it stays drafted as the rest is sent; on one left for later, bring it back; sending to an agent or a named pile comes with piles (#312)",
    comment: "comment on it whole: an item; on a banner, a message to its agent, which their drawers' remarks go with; in a drawer, a remark on the line",
    hold: "from anywhere in an agent's group, hold each flagged write of the agent and their subagents for your answer, or let them land again",
    pause: "pause the agent at their next call until they're resumed: not built yet, its host side designed beside #157",
};

/**
 * Return the review's keys, with the kinds of fold known now, outermost first (`kinds`, `looks.ts`): each kind's letter,
 * after `zf` toggling the one the cursor is in, and after Space `f` or `F` selecting every one, fold-wise; each
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
            { keys: "o", does: "comment on the line: an item's, a file's, or the agent's words in their conversation, a remark; on a banner, a message to its agent, which their drawers' remarks go with", short: "comment" },
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
                does: "half a page or a page down or up, as vim's, but never showing two files or two items at once: one that would bring a file's end into view stops with it at the bottom, the next puts the next file's header at the top; back the same",
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
                does: "on a citation, go to the passage of your words it cites, above the answer; on that passage, back to the citation; on a banner naming another agent's drawer, as a landing waiting on files there, to that drawer",
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
            { keys: "zO zC", does: "open every fold the cursor is in and every one within the innermost, but calls' input and output; or close every fold the cursor is in, within the item or the drawer, as vim's do recursively", short: "recursively" },
            {
                keys: "zr zm",
                does: "open or close one more level of the item or the drawer the cursor is in: its files, then their bodies and unchanged lines, then its context; in a conversation, the exchange before those open, one further back each time, then its runs of calls",
                short: "a level",
            },
            { keys: "zR zM", does: "open or close every fold in the item or the drawer the cursor is in, but for calls' input and output, which za opens, and those of a kind your layer keeps them from", short: "all of it" },
            {
                keys: "zf",
                does: "and a letter: open or close the fold of its kind the cursor is in, the file, the run of unchanged lines, the item, a drawer, or in a conversation an earlier exchange, a run of calls or a call's input and output, the cursor going to its summary line",
                short: "toggle one",
            },
            ...lettered.map((each) => ({ keys: `zf${each.letter}`, does: `open or close ${each.one} the cursor is in`, short: each.one })),
            {
                keys: "␣f",
                does: "and a letter: select every fold of its kind in the item, the drawer or the agent's group the cursor is in, fold-wise, each drawn as selected; in visual mode, those within the selection; motions reshape it, Esc ends it",
                short: "select by kind",
            },
            {
                keys: "␣F",
                does: "and a letter: select every fold of its kind in the whole review, fold-wise",
                short: "select every one",
            },
            ...lettered.filter((each) => each.chord).map((each) => ({
                keys: `␣f${each.letter} ␣F${each.letter}`,
                does: `select ${each.called}, here or in the whole review`,
                short: each.called,
            })),
            {
                keys: "v… za zo zc",
                does: "in a selection, toggle, open or close every fold it holds, a fold-wise one's of its kind, those opened seen, the folds around them opening",
                short: "fold them",
            },
            {
                keys: "v… ␣d d",
                does: "in a selection, Space and a verb's key on each thing it holds whole, as one mark: a fold-wise one's folds, else each item, drawer, file and agent's group whose line it holds; in a fold-wise one, the key alone too where it's no motion, d x s p",
                short: "act on them",
            },
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

/** The parts of the palette whose keys it runs as chosen, from normal mode: answering, moving, the overview and the folds. */
const RUNNABLE = new Set(["Answering", "Moving", "The overview", "Folds"]);

/**
 * Return `keys`, one way of pressing a key as the list writes it (`␣d`, `]]`, `^d`, `zR`), as vim's keymap names each
 * key pressed (`<Space>`, `d`; `<C-d>`): none for one that's no plain sequence of keys, a motion left to type (`…`),
 * Enter, Tab or a mark of the margin's.
 */
export function vimKeys(keys: string): string[] | null {
    const pressed: string[] = [];
    const chars = [...keys];
    for (let at = 0; at < chars.length; at += 1) {
        const char = chars[at] ?? "";
        if (char === "␣") {
            pressed.push("<Space>");
        } else if (char === "^" && at + 1 < chars.length && /^[a-z]$/.test(chars[at + 1] ?? "")) {
            pressed.push(`<C-${chars[at + 1]}>`);
            at += 1;
        } else if (/^[\x21-\x7e]$/.test(char)) {
            pressed.push(char);
        } else {
            return null;
        }
    }
    return pressed.length === 0 ? null : pressed;
}

/**
 * Return what the palette runs as `key` of the part titled `title` is chosen, as vim's keymap names each key: its
 * first way of being pressed that's a whole key, as `]]` of `]] [[`, never one leading a chord (`zf`, `␣f`), which
 * would wait for the next key; none for a key of a part it doesn't run, writing a comment or the clipboard's, or one
 * none of whose ways is a plain sequence of keys.
 */
export function runOf(parts: readonly Part[], title: string, key: Key): string[] | null {
    if (!RUNNABLE.has(title)) {
        return null;
    }
    for (const way of key.keys.split(" ")) {
        const pressed = vimKeys(way);
        if (pressed !== null && chords(parts, way).length === 0) {
            return pressed;
        }
    }
    return null;
}

/**
 * Return how well the search `search` matches an entry of the palette, as cmdk scores one, 0 where it doesn't: each of
 * its words in the entry's name, its keys and what it's called short (`named`), or in what it does whole (`keywords`),
 * those found in its name counting most, so `next item` finds `]]` before an entry whose long words hold both.
 */
export function searched(named: string, search: string, keywords: readonly string[] = []): number {
    const words = search.toLowerCase().split(/\s+/).filter((each) => each !== "");
    if (words.length === 0) {
        return 1;
    }
    const name = named.toLowerCase();
    const whole = `${name} ${keywords.join(" ").toLowerCase()}`;
    if (!words.every((each) => whole.includes(each))) {
        return 0;
    }
    return 0.5 + (0.5 * words.filter((each) => name.includes(each)).length) / words.length;
}

/**
 * A kind of key, as the page's timings group them (`timings.ts`; `docs/dashboard.md`, *Its timings*): typing in a
 * comment, a motion, a fold's key, a verb's, the palette's, and any other.
 */
export type KeyKind = "typing" | "motion" | "fold" | "verb" | "palette" | "other";

/** The kind of the keys of each part of the table: the rest are `other`. */
function partKind(title: string): KeyKind {
    switch (title) {
        case "Writing a comment":
            return "typing";
        case "Answering":
            return "verb";
        case "Moving":
            return "motion";
        case "Folds":
            return "fold";
        case "This palette":
            return "palette";
        default:
            return "other";
    }
}

/** vim's own motions, which the table leaves to vim, as it writes keys: the arrows, a page's keys and a scroll's among them. */
const VIM_MOTIONS: readonly string[] = [
    "h", "j", "k", "l", "w", "W", "b", "B", "e", "E", "ge", "gE", "0", "^", "$", "gg", "G", "{", "}", "(", ")", "H", "M",
    "L", "%", ";", ",", "+", "-", "_", "|", "zt", "zz", "zb", "^e", "^y", "←", "→", "↑", "↓", "PageUp", "PageDown", "Home",
    "End",
];

/** vim's motions to a character on the line, done by the character after them. */
const TO_CHARACTER: readonly string[] = ["f", "F", "t", "T"];

/**
 * Return the kind of the key that ends `pressed`, the keys of a command typed so far outside a comment, as the list
 * writes them (`␣`, `^d`, `z`): the part of the table holding those keys whole, else vim's own motion they make, else
 * the part holding a key they begin, as Space begins a verb, else vim's motion they begin; any other key is `other`.
 */
export function keyKind(parts: readonly Part[], pressed: readonly string[]): KeyKind {
    const keys = pressed.join("");
    const ways = parts
        .filter((part) => !WRITING.some((writing) => writing.title === part.title))
        .flatMap((part) => part.keys.flatMap((key) => key.keys.split(" ").map((way) => ({ way, title: part.title }))));
    const whole = ways.find((each) => each.way === keys);
    if (whole !== undefined) {
        return partKind(whole.title);
    }
    if (VIM_MOTIONS.includes(keys) || (pressed.length === 2 && TO_CHARACTER.includes(pressed[0] ?? ""))) {
        return "motion";
    }
    const begun = ways.find((each) => each.way.startsWith(keys));
    if (begun !== undefined) {
        return partKind(begun.title);
    }
    return VIM_MOTIONS.some((each) => each.startsWith(keys)) || TO_CHARACTER.includes(keys) ? "motion" : "other";
}

/** Return a key going down as the list writes keys: `␣` for Space, `^` and the letter for Ctrl and one, `⏎`, `Esc`, the arrows. */
export function writtenKey(event: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey">): string {
    const named: Readonly<Record<string, string>> = { " ": "␣", Enter: "⏎", Escape: "Esc", ArrowLeft: "←", ArrowRight: "→", ArrowUp: "↑", ArrowDown: "↓" };
    const key = named[event.key] ?? event.key;
    return event.ctrlKey || event.metaKey ? `^${[...key].length === 1 ? key.toLowerCase() : key}` : key;
}

/** Return a key vim holds of a command begun, as its keymap names it (`<Space>`, `<C-d>`), as the list writes keys. */
export function writtenVim(key: string): string {
    const named: Readonly<Record<string, string>> = { "<Space>": "␣", "<CR>": "⏎", "<Esc>": "Esc" };
    const control = /^<C-(.)>$/.exec(key);
    return named[key] ?? (control === null ? key : `^${control[1]}`);
}

/** What the palette says of the page's timings in this browser, and what choosing it does: switch them off, or on again. */
export function measuringSaid(on: boolean): Key {
    return on
        ? {
              keys: "⏎",
              does: "measuring how long each key takes to reach the screen in this browser, sent to the host every 5 minutes and as the tab is hidden, for agents to read with lup-dev dashboard timings: timings and sizes only, never what's typed or shown; ⏎ switches it off in this browser",
              short: "measuring",
          }
        : {
              keys: "⏎",
              does: "not measuring how long keys take to reach the screen: switched off in this browser; ⏎ switches it on again",
              short: "not measuring",
          };
}
