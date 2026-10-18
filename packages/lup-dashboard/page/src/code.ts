// The code under an approval or a held change: each file it changes shown whole,
// what it was and what it becomes, its lines marked added, removed (in place,
// where they were) or the same, each run of unchanged lines away from the
// changes folded under a summary, a few lines of context kept around each; and
// its text highlighted by CodeMirror's own language packages, chosen by its
// name. Pure: the review lays these rows into its text (`review.ts`), and its
// editor paints the lines in view with them (`Review.tsx`).
import { javascriptLanguage, jsxLanguage, tsxLanguage, typescriptLanguage } from "@codemirror/lang-javascript";
import { jsonLanguage } from "@codemirror/lang-json";
import { markdownLanguage } from "@codemirror/lang-markdown";
import { pythonLanguage } from "@codemirror/lang-python";
import { StreamLanguage, type Language } from "@codemirror/language";
import { toml } from "@codemirror/legacy-modes/mode/toml";
import { classHighlighter, highlightTree } from "@lezer/highlight";

import { hunks } from "./comments";
import type { components } from "./generated/api";

export type ChangedFile = components["schemas"]["ChangedFile"];
type Content = components["schemas"]["Content"];

/** How many unchanged lines are kept in view on each side of a change. */
export const CONTEXT = 3;

/** The fewest unchanged lines a fold hides: one would take as much room as its summary. */
const FEWEST = 2;

/** What a line of a file shows: one the change adds, one it removes, or one it leaves. */
export type Change = "added" | "removed" | "same";

/** One line of a changed file as the review shows it. */
export interface Row {
    change: Change;
    /** Which text it's a line of: what the file was, for a removed line, else what it becomes. */
    side: "before" | "after";
    /** Its number in that text, from 1. */
    number: number;
    /** Where it starts in that text. */
    offset: number;
    text: string;
}

/** A run of unchanged rows folded under a summary line, from row `from` up to row `to`. */
export interface Run {
    from: number;
    to: number;
    summary: string;
}

/** A changed file as the review shows it: its header line, its rows in order, and the runs of them that fold. */
export interface Shown {
    header: string;
    rows: Row[];
    runs: Run[];
}

/** One line of a text, and where it starts in it. */
interface Split {
    text: string;
    offset: number;
}

/** Return the lines of `text`, each where it starts: broken at `\n`, `\r\n` and `\r`, as the editor breaks them; none for an empty text, and none after a last line break. */
export function lines(text: string): Split[] {
    const found: Split[] = [];
    let start = 0;
    let at = 0;
    while (at < text.length) {
        const char = text[at];
        if (char === "\n" || char === "\r") {
            found.push({ text: text.slice(start, at), offset: start });
            at += char === "\r" && text[at + 1] === "\n" ? 2 : 1;
            start = at;
        } else {
            at += 1;
        }
    }
    if (start < text.length) {
        found.push({ text: text.slice(start), offset: start });
    }
    return found;
}

/** Return the text of a side shown as text; none where the file isn't there, or isn't text. */
function textOf(content: Content | null | undefined): string | null {
    return content?.kind === "text" ? content.text : null;
}

/** Say how many lines, in a few words. */
function counted(count: number, what: string): string {
    return `${count} ${what}${count === 1 ? "" : "s"}`;
}

/** Say a binary side's size. */
function sized(content: Content | null | undefined): string {
    return content?.kind === "binary" ? `${content.size.toLocaleString("en")} bytes` : "none";
}

/** Say what happened to a file: created, deleted or changed, by how many lines, or that it's binary and isn't shown. */
function told(file: ChangedFile, rows: Row[]): string {
    const before = file.before ?? null;
    const after = file.after ?? null;
    const what = before === null ? "created" : after === null ? "deleted" : "changed";
    if (before?.kind === "binary" || after?.kind === "binary") {
        const sizes = what === "changed" ? `${sized(before)} → ${sized(after)}` : sized(before ?? after);
        return `${what} · binary, not shown · ${sizes}`;
    }
    if (what === "created") {
        return `created · ${counted(rows.length, "line")}`;
    }
    if (what === "deleted") {
        return `deleted · ${counted(rows.length, "line")}`;
    }
    const added = rows.filter((each) => each.change === "added").length;
    const removed = rows.filter((each) => each.change === "removed").length;
    return added + removed === 0 ? "changed · no line differs" : `changed · +${added} −${removed}`;
}

/**
 * Lay a changed file out as the review shows it: what it becomes, whole, each line it removes in place where it was,
 * before the lines that replace it; then each run of unchanged lines folded where it's `context` lines or more away
 * from every change, and hides two lines or more. A binary file shows its header alone.
 */
export function shown(file: ChangedFile, context: number = CONTEXT): Shown {
    const before = lines(textOf(file.before) ?? "");
    const after = lines(textOf(file.after) ?? "");
    const rows: Row[] = [];
    const same = (i: number, j: number) => {
        const line = after[j];
        if (line !== undefined) {
            rows.push({ change: "same", side: "after", number: j + 1, ...line });
        }
        return before[i] === undefined ? i : i + 1;
    };
    let i = 0;
    let j = 0;
    for (const hunk of hunks(
        before.map((each) => each.text),
        after.map((each) => each.text),
    )) {
        while (j < hunk.into) {
            i = same(i, j);
            j += 1;
        }
        for (; i < hunk.to; i += 1) {
            const line = before[i];
            if (line !== undefined) {
                rows.push({ change: "removed", side: "before", number: i + 1, ...line });
            }
        }
        for (; j < hunk.until; j += 1) {
            const line = after[j];
            if (line !== undefined) {
                rows.push({ change: "added", side: "after", number: j + 1, ...line });
            }
        }
    }
    while (j < after.length) {
        i = same(i, j);
        j += 1;
    }
    return { header: `${file.path} · ${told(file, rows)}`, rows, runs: runs(rows, context) };
}

/** Each file as shown, once laid out: the review is laid out again at each key typed in a comment, and a file's lines don't change. */
const laidOut = new WeakMap<ChangedFile, Shown>();

/** Return `file` as shown (`shown`), laid out once and kept. */
export function shownOnce(file: ChangedFile): Shown {
    const kept = laidOut.get(file);
    if (kept !== undefined) {
        return kept;
    }
    const made = shown(file);
    laidOut.set(file, made);
    return made;
}

/** Return the runs of unchanged rows to fold: each run's part `context` rows or more from every change, where it hides `FEWEST` rows or more. */
function runs(rows: Row[], context: number): Run[] {
    const found: Run[] = [];
    let start = 0;
    while (start < rows.length) {
        if (rows[start]?.change !== "same") {
            start += 1;
            continue;
        }
        let end = start;
        while (end < rows.length && rows[end]?.change === "same") {
            end += 1;
        }
        const from = start === 0 ? start : start + context;
        const to = end === rows.length ? end : end - context;
        if (to - from >= FEWEST) {
            const first = rows[from]?.number ?? 0;
            const last = rows[to - 1]?.number ?? 0;
            found.push({ from, to, summary: `${counted(to - from, "unchanged line")}, ${first}–${last}` });
        }
        start = end;
    }
    return found;
}

/** The languages known, by what a file's name ends with. */
const LANGUAGES: { ending: string; language: Language }[] = [
    { ending: ".py", language: pythonLanguage },
    { ending: ".pyi", language: pythonLanguage },
    { ending: ".ts", language: typescriptLanguage },
    { ending: ".mts", language: typescriptLanguage },
    { ending: ".cts", language: typescriptLanguage },
    { ending: ".tsx", language: tsxLanguage },
    { ending: ".js", language: javascriptLanguage },
    { ending: ".mjs", language: javascriptLanguage },
    { ending: ".cjs", language: javascriptLanguage },
    { ending: ".jsx", language: jsxLanguage },
    { ending: ".json", language: jsonLanguage },
    { ending: ".md", language: markdownLanguage },
    { ending: ".toml", language: StreamLanguage.define(toml) },
    { ending: "/uv.lock", language: StreamLanguage.define(toml) },
];

/** Return the language a file's text is highlighted in, by its name; none where none is known. */
export function languageOf(path: string): Language | null {
    const named = `/${path}`;
    return LANGUAGES.find((each) => named.endsWith(each.ending))?.language ?? null;
}

/** A stretch of a text, highlighted: its classes, as `classHighlighter` names them (`tok-keyword`…). */
export interface Token {
    from: number;
    to: number;
    classes: string;
}

/** Return the tokens of `text` highlighted in `language`, in order, parsed whole. */
export function highlighted(text: string, language: Language): Token[] {
    const tokens: Token[] = [];
    highlightTree(language.parser.parse(text), classHighlighter, (from, to, classes) => {
        tokens.push({ from, to, classes });
    });
    return tokens;
}

/** Each file's tokens, by side, once highlighted: a file's text is parsed once, the first time a line of it is in view. */
const highlights = new WeakMap<ChangedFile, { before?: Token[]; after?: Token[] }>();

/** Return the tokens of one side of `file`, highlighted once and kept; none where its language isn't known or it isn't text. */
export function tokensOf(file: ChangedFile, side: Row["side"]): Token[] {
    const kept = highlights.get(file) ?? {};
    const found = kept[side];
    if (found !== undefined) {
        return found;
    }
    const text = textOf(file[side]);
    const language = languageOf(file.path);
    const made = text === null || language === null ? [] : highlighted(text, language);
    highlights.set(file, { ...kept, [side]: made });
    return made;
}

/** Return the tokens of `tokens` within `row`, counted from the row's start. */
export function within(tokens: Token[], row: Row): Token[] {
    const end = row.offset + row.text.length;
    // The first token ending after the row's start, found by halving.
    let low = 0;
    let high = tokens.length;
    while (low < high) {
        const middle = (low + high) >> 1;
        if ((tokens[middle]?.to ?? 0) <= row.offset) {
            low = middle + 1;
        } else {
            high = middle;
        }
    }
    const found: Token[] = [];
    for (let at = low; at < tokens.length; at += 1) {
        const token = tokens[at];
        if (token === undefined || token.from >= end) {
            break;
        }
        found.push({
            from: Math.max(token.from, row.offset) - row.offset,
            to: Math.min(token.to, end) - row.offset,
            classes: token.classes,
        });
    }
    return found;
}
