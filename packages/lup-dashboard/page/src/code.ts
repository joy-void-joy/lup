// The code under an approval, a held change or a write that landed flagged: each
// file it changes shown whole, what it was and what it becomes, its lines marked
// added, removed (in place, where they were) or the same, each run of unchanged
// lines away from the changes folded under a summary, a few lines of context
// kept around each; and its text highlighted by CodeMirror's own language
// packages, chosen by its name. The judge's reading of the file says why it's
// open, in its header's last words, and which of its lines matter, each saying
// what it triggered; a file that asks nothing, held or flagged, is automatic,
// its header alone in view. A held change's and a flagged write's files show
// every change; an approval's, which may change tens of thousands of lines, show
// only the lines that ask in a file whose asks are each on a line, with their
// context, every other change folded (`Showing`). Each function's and class's
// body, read from the file's syntax, can fold under the line declaring it; a run
// of lines never crosses a body's edge, so every fold sits whole inside another.
// Pure: the review lays these rows into its text (`review.ts`), and its editor
// paints the lines in view with them (`Review.tsx`).
import { javascriptLanguage, jsxLanguage, tsxLanguage, typescriptLanguage } from "@codemirror/lang-javascript";
import { jsonLanguage } from "@codemirror/lang-json";
import { markdownLanguage } from "@codemirror/lang-markdown";
import { pythonLanguage } from "@codemirror/lang-python";
import { StreamLanguage, type Language } from "@codemirror/language";
import { toml } from "@codemirror/legacy-modes/mode/toml";
import { classHighlighter, highlightTree } from "@lezer/highlight";

import { hunks, lineOf } from "./comments";
import type { components } from "./generated/api";

export type ChangedFile = components["schemas"]["ChangedFile"];
type Content = components["schemas"]["Content"];
export type Reading = components["schemas"]["Reading"];
type Asked = components["schemas"]["Asked"];
type ApiChanged = components["schemas"]["ApiChanged"];
/** How the declaration takes what a line triggered: held for the operator's answer, flagged for their review, or told to the agent alone. */
export type Taken = components["schemas"]["Found"]["taken"];

/** How many unchanged lines are kept in view on each side of a change. */
export const CONTEXT = 3;

/** The fewest lines a fold hides: one would take as much room as its summary. */
const FEWEST = 2;

/** The most changes to the public API a header names: the rest are on their lines. */
const NAMED = 4;

/**
 * What a file whose asks are each on a line keeps open, by the item it's under: every change, unchanged lines alone
 * folding, as in any other file, for a held change and a flagged write, which the operator reads whole; or the lines
 * that ask alone, with their context, every other change folding too, for an approval, which may change tens of
 * thousands of lines.
 */
export type Showing = "changes" | "asks";

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
    /** How many of its rows are changed: none for a run of unchanged lines. */
    changed: number;
    /**
     * What names it across layouts, by what it hides, so it's found again as lines are added or taken away elsewhere in
     * the file: the body it's in, none at the file's top level; the bodies it holds whole, or where it holds none its
     * first line with words; and, where two are named alike, which of them it is.
     */
    name: string;
}

/**
 * A function's or a class's body, by its rows: the row declaring it, which stays in view while it folds, and its last;
 * the bodies it's in and its own name, an unnamed function's by its first line; and what names it across layouts.
 */
export interface Body {
    from: number;
    to: number;
    names: string[];
    name: string;
}

/** What a line that matters triggered, said at its end, and how the declaration takes it. */
export interface Note {
    taken: Taken;
    said: string;
}

/** A row that matters, by its index among the file's rows, and what's said at its end: on the first row of what it triggered, none on the rest. */
export interface Matter {
    row: number;
    notes: Note[];
}

/** One reason a file is open, or that it's automatic: its words in the header, and how a tally of an item's files counts it. */
export interface Reason {
    said: string;
    one: string;
    many: string;
}

/**
 * A changed file as the review shows it: its header line, its rows in order, the runs of them that fold and the bodies
 * of its functions and classes; why it's open, from the judge's reading of it, none where it wasn't read; whether it's
 * automatic; whether what it asks is about it whole, its header then a line that matters; and the rows that matter.
 */
export interface Shown {
    header: string;
    rows: Row[];
    runs: Run[];
    bodies: Body[];
    reasons: Reason[];
    automatic: boolean;
    whole: boolean;
    matters: Matter[];
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
 * from every change and every line that matters, and hides two lines or more; where `showing` is `asks` and the file's
 * asks are each on a line, every run of lines away from those, changed ones among them. A binary file shows its
 * header alone.
 */
export function shown(file: ChangedFile, showing: Showing = "changes", context: number = CONTEXT): Shown {
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
    const reading = file.reading ?? null;
    const placed = mattering(reading, rows);
    const reasons = reading === null ? [] : reasoned(reading);
    const automatic = reasons[0]?.said === "automatic";
    const header = [`${file.path} · ${told(file, rows)}`, ...reasons.map((each) => each.said)].join(" · ");
    const kept = new Set(placed.matters.map((each) => each.row));
    // An approval's file whose asks are each on a line shows those lines alone, with their context, its other changes folded.
    const onLines = showing === "asks" && !automatic && !placed.whole && placed.matters.length > 0;
    const found = bodiesOf(file, rows);
    return {
        header,
        rows,
        runs: runs(rows, context, kept, onLines, found),
        bodies: found,
        reasons,
        automatic,
        whole: placed.whole,
        matters: placed.matters,
    };
}

/** Say what a change to the public API does, as a line that matters says it. */
function api(change: ApiChanged): string {
    switch (change.kind) {
        case "export-added":
            return `adds \`${change.name}\` to the package's root`;
        case "export-removed":
            return `takes \`${change.name}\` out of the package's root`;
        case "class-added":
            return `adds the class \`${change.name}\``;
        case "signature-changed":
            return `changes the signature of \`${change.name}\``;
    }
}

/** Mark a change to the public API in a header's few words: `+` a name added, `−` one taken out, `~` a signature changed. */
function signed(change: ApiChanged): string {
    const sign = change.kind === "export-removed" ? "−" : change.kind === "signature-changed" ? "~" : "+";
    return `${sign}${change.name}`;
}

/** Say what one ask on a line triggered. */
function triggered(asked: Asked): string {
    if (asked.api != null) {
        return `public API: ${api(asked.api)}`;
    }
    return asked.name === "ignore" ? "adds an ignore" : asked.name;
}

/** The rows that matter, and whether anything the file asks is about it whole, or on no row shown, so its header matters too. */
interface Placed {
    matters: Matter[];
    whole: boolean;
}

/**
 * Place what the reading found on the rows it's on: each ask on its line, on the side it's in, and each finding on
 * every line it spans, what it triggered said on its first. An ask about the file whole, or on a line no row shows,
 * is the header's.
 */
function mattering(reading: Reading | null, rows: Row[]): Placed {
    if (reading === null) {
        return { matters: [], whole: false };
    }
    const at = (side: Row["side"], number: number) =>
        rows.findIndex((row) => row.side === side && row.number === number && (side === "after" || row.change === "removed"));
    const notes = new Map<number, Note[]>();
    const mark = (row: number, note: Note | null) => {
        notes.set(row, [...(notes.get(row) ?? []), ...(note === null ? [] : [note])]);
    };
    let whole = false;
    for (const asked of reading.asks ?? []) {
        const row = asked.line == null ? -1 : at(asked.side ?? "after", asked.line);
        if (row < 0) {
            whole = true;
        } else {
            mark(row, { taken: asked.taken, said: triggered(asked) });
        }
    }
    for (const found of reading.findings ?? []) {
        const said = `${found.rule}: ${found.message.replaceAll("\n", " ")}`;
        for (let line = found.start; line <= found.end; line += 1) {
            const row = at("after", line);
            if (row >= 0) {
                mark(row, line === found.start ? { taken: found.taken, said } : null);
            }
        }
    }
    const matters = [...notes.entries()].map(([row, said]) => ({ row, notes: said })).sort((a, b) => a.row - b.row);
    return { matters, whole };
}

/** One reason, said the same in a header and in a tally of an item's files. */
function plainly(said: string, many: string = said): Reason {
    return { said, one: said, many };
}

/**
 * Say why a file is open, from the judge's reading of it: what it asks, held first, each kind once, the changes to
 * its public API together (counted, for a new file; named, up to `NAMED`, for any other); the rules of the findings
 * held or flagged; else `automatic`, for one asking nothing held or flagged, production code among them. The
 * findings only told come last, which open nothing.
 */
function reasoned(reading: Reading): Reason[] {
    const asks = reading.asks ?? [];
    const findings = reading.findings ?? [];
    const ignores = asks.filter((each) => each.name === "ignore").length;
    const changes = asks.flatMap((each) => (each.api == null ? [] : [signed(each.api)]));
    const reason = (name: string): Reason => {
        switch (name) {
            case "protected":
                return plainly("protected");
            case "operator":
                return plainly("operator's document", "operator's documents");
            case "new-file":
                return { said: "new file", one: "new file", many: "new files" };
            case "whole-file":
                return plainly("written whole");
            case "ignore":
                return {
                    said: ignores === 1 ? "adds an ignore" : `adds ${ignores} ignores`,
                    one: "with an ignore",
                    many: "with ignores",
                };
            case "public-api": {
                const named =
                    changes.length <= NAMED
                        ? changes.join(" ")
                        : `${changes.slice(0, NAMED).join(" ")} and ${changes.length - NAMED} more`;
                const created = asks.some((each) => each.name === "new-file");
                const said = created ? counted(changes.length, "public name") : `public API: ${named}`;
                return { said, one: "public API", many: "public API" };
            }
            default: {
                const found = findings.filter((each) => each.rule === name).length;
                return { said: found > 1 ? `${name} ×${found}` : name, one: name, many: name };
            }
        }
    };
    const ordered = (taken: Taken) => [
        ...asks.filter((each) => each.taken === taken).map((each) => each.name),
        ...findings.filter((each) => each.taken === taken).map((each) => each.rule),
    ];
    const asked = [...new Set([...ordered("held"), ...ordered("flagged")])].map(reason);
    const told = [...new Set(ordered("told"))];
    const informed =
        told.length === 0
            ? []
            : [{ said: `told: ${told.join(", ")}`, one: "with findings told", many: "with findings told" }];
    return [...(asked.length > 0 ? asked : [plainly("automatic")]), ...informed];
}

/** Count an item's files by the first reason each is open, the most first: `3 automatic · 1 new file · 1 public API`; files the judge didn't read are `unread`; nothing where it read none. */
export function tally(files: ChangedFile[]): string {
    if (files.every((each) => each.reading == null)) {
        return "";
    }
    const counts = new Map<string, { reason: Reason; count: number }>();
    for (const file of files) {
        const reason = (file.reading == null ? undefined : reasoned(file.reading)[0]) ?? plainly("unread");
        const kept = counts.get(reason.one);
        counts.set(reason.one, { reason, count: (kept?.count ?? 0) + 1 });
    }
    return [...counts.values()]
        .sort((a, b) => b.count - a.count)
        .map(({ reason, count }) => `${count} ${count === 1 ? reason.one : reason.many}`)
        .join(" · ");
}

/** Each file as shown, by what it shows, once laid out: the review is laid out again at each key typed in a comment, and a file's lines don't change. */
const laidOut = new WeakMap<ChangedFile, Map<Showing, Shown>>();

/** Return `file` as shown (`shown`), showing what `showing` says, laid out once and kept. */
export function shownOnce(file: ChangedFile, showing: Showing): Shown {
    const kept = laidOut.get(file) ?? new Map<Showing, Shown>();
    const found = kept.get(showing);
    if (found !== undefined) {
        return found;
    }
    const made = shown(file, showing);
    laidOut.set(file, kept.set(showing, made));
    return made;
}

/** Rows `from` up to `to` of a file. */
interface Stretch {
    from: number;
    to: number;
}

/**
 * Return the runs of rows to fold: each run's part `context` rows or more from every change and every row that
 * matters (`kept`), where it hides `FEWEST` rows or more. Unchanged rows alone fold, but `onLines`, where the rows
 * that matter are the only ones kept open, changed rows among the rest folding, each run saying how many it holds. A run
 * never crosses the edge of one of `bodies` (`cut`), so each sits whole inside the body or around it, and is named by
 * what it hides (`Run.name`).
 */
function runs(rows: Row[], context: number, kept: Set<number> = new Set(), onLines: boolean = false, bodies: Body[] = []): Run[] {
    const stretches: Stretch[] = [];
    const folding = (at: number) => (onLines || rows[at]?.change === "same") && !kept.has(at);
    let start = 0;
    while (start < rows.length) {
        if (!folding(start)) {
            start += 1;
            continue;
        }
        let end = start;
        while (end < rows.length && folding(end)) {
            end += 1;
        }
        stretches.push({ from: start === 0 ? start : start + context, to: end === rows.length ? end : end - context });
        start = end;
    }
    const pieces = bodies
        .reduce((each, body) => each.flatMap((stretch) => cut(stretch, body)), stretches)
        .filter((stretch) => stretch.to - stretch.from >= FEWEST);
    const named = new Map<string, number>();
    return pieces.map(({ from, to }) => {
        const first = rows[from]?.number ?? 0;
        const last = rows[to - 1]?.number ?? 0;
        const changed = rows.slice(from, to).filter((row) => row.change !== "same").length;
        const said =
            changed === 0 ? counted(to - from, "unchanged line") : `${counted(to - from, "line")}, ${changed} changed`;
        // The innermost body it's in: the one starting last of those holding it whole.
        const within = bodies.filter((body) => body.from < from && to - 1 <= body.to).at(-1)?.name ?? "";
        // What it hides: the outermost bodies it holds whole, else its first line with words.
        const held = bodies.filter((body) => body.from >= from && body.to <= to - 1);
        const outermost = held.filter((body) => !held.some((other) => other.from < body.from && body.to <= other.to));
        const words = rows.slice(from, to).find((row) => row.text.trim() !== "")?.text.trim() ?? "";
        const hides = JSON.stringify([within, outermost.length > 0 ? outermost.map((body) => body.name) : words]);
        const times = named.get(hides) ?? 0;
        named.set(hides, times + 1);
        return { from, to, summary: `${said}, ${first}–${last}`, changed, name: times === 0 ? hides : `${hides} ${times}` };
    });
}

/**
 * Return `stretch` cut where it crosses an edge of `body`, so each part is inside the body or outside it: where it holds
 * the row declaring the body but not its last, that row stays in view between its two parts, as the line a folded body
 * is under; where it starts inside the body and goes on past it, it's cut after the body's last row.
 */
function cut(stretch: Stretch, body: Body): Stretch[] {
    const last = stretch.to - 1;
    if (stretch.from <= body.from && body.from <= last && body.to > last) {
        return [
            { from: stretch.from, to: body.from },
            { from: body.from + 1, to: stretch.to },
        ];
    }
    if (stretch.from > body.from && stretch.from <= body.to && last > body.to) {
        return [
            { from: stretch.from, to: body.to + 1 },
            { from: body.to + 1, to: stretch.to },
        ];
    }
    return [stretch];
}

/** The syntax nodes that declare a function or a class, by their names in Python's grammar and in JavaScript's and TypeScript's. */
const DECLARING = new Set([
    "FunctionDefinition",
    "ClassDefinition",
    "FunctionDeclaration",
    "ClassDeclaration",
    "MethodDeclaration",
    "FunctionExpression",
    "ArrowFunction",
    "ClassExpression",
]);

/** The child of a declaration that names it, in each grammar. */
const NAMING = ["VariableName", "VariableDefinition", "PropertyDefinition", "PrivatePropertyDefinition"];

/** A node of a file's syntax tree. */
type Node = Tree["topNode"];

/**
 * Return the bodies of the functions and classes `file` declares, in the order they start, read from the syntax of
 * what it becomes, or of what it was where it's deleted, in a language with such bodies: each from the row declaring
 * it to its last, where that hides `FEWEST` rows or more; named by its declaration, an unnamed one by where it's
 * assigned or else by its first line, after the bodies it's in, a name given twice counted, so each names one body.
 */
function bodiesOf(file: ChangedFile, rows: Row[]): Body[] {
    const side: Row["side"] = file.after?.kind === "text" ? "after" : "before";
    const text = textOf(file[side]);
    const language = languageOf(file.path);
    if (text === null || language === null || !BODIED.has(language)) {
        return [];
    }
    const starts = lines(text).map((each) => each.offset);
    const index = new Map(rows.flatMap((row, at) => (row.side === side ? [[row.number, at] as const] : [])));
    const rowAt = (offset: number) => index.get(lineOf(starts, offset) + 1);
    const found: Body[] = [];
    const seen = new Map<string, number>();
    const walk = (node: Node, names: string[]) => {
        let inner = names;
        if (declaring(node)) {
            const from = rowAt(node.from);
            const end = node.from + text.slice(node.from, node.to).trimEnd().length;
            const to = rowAt(Math.max(end - 1, node.from));
            if (from !== undefined && to !== undefined) {
                inner = [...names, nameOf(node, text) ?? (rows[from]?.text.trim() ?? "")];
                const key = JSON.stringify(inner);
                const times = seen.get(key) ?? 0;
                seen.set(key, times + 1);
                if (to - from >= FEWEST) {
                    found.push({ from, to, names: inner, name: times === 0 ? key : `${key} ${times}` });
                }
            }
        }
        for (let child = node.firstChild; child !== null; child = child.nextSibling) {
            walk(child, inner);
        }
    };
    walk(treeOf(file, side, text, language).topNode, []);
    return found;
}

/** Return whether `node` declares a function or a class: one of `DECLARING`, or a method written in an object's braces. */
function declaring(node: Node): boolean {
    return DECLARING.has(node.name) || (node.name === "Property" && node.getChild("ParamList") !== null);
}

/** Return the name `node` declares: its own, or, where it has none, that of what it's assigned to, a variable or a property; none for one passed as it is. */
function nameOf(node: Node, text: string): string | null {
    const said = (named: Node | null) => (named === null ? null : text.slice(named.from, named.to));
    const own = NAMING.map((name) => node.getChild(name)).find((each) => each !== null) ?? null;
    if (own !== null) {
        return said(own);
    }
    const parent = node.parent;
    if (parent?.name === "Property") {
        return said(parent.getChild("PropertyDefinition"));
    }
    if (parent?.name !== "VariableDeclaration") {
        return null;
    }
    let before = node.prevSibling;
    while (before !== null && before.name !== "VariableDefinition") {
        before = before.prevSibling;
    }
    return said(before);
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

/** A text's syntax, as its language's parser reads it. */
type Tree = ReturnType<Language["parser"]["parse"]>;

/** The languages whose syntax declares functions and classes, whose bodies fold. */
const BODIED = new Set<Language>([pythonLanguage, typescriptLanguage, tsxLanguage, javascriptLanguage, jsxLanguage]);

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
    return tokensIn(language.parser.parse(text));
}

/** Return the tokens of a parsed text, in order. */
function tokensIn(tree: Tree): Token[] {
    const tokens: Token[] = [];
    highlightTree(tree, classHighlighter, (from, to, classes) => {
        tokens.push({ from, to, classes });
    });
    return tokens;
}

/** Each file's syntax trees, by side, once parsed: for its bodies as it's laid out, and its highlighting as its lines come into view. */
const trees = new WeakMap<ChangedFile, { before?: Tree; after?: Tree }>();

/** Return the syntax tree of one side of `file`, its `text` in `language`, parsed once and kept. */
function treeOf(file: ChangedFile, side: Row["side"], text: string, language: Language): Tree {
    const kept = trees.get(file) ?? {};
    const found = kept[side];
    if (found !== undefined) {
        return found;
    }
    const made = language.parser.parse(text);
    trees.set(file, { ...kept, [side]: made });
    return made;
}

/** Each file's tokens, by side, once highlighted: a file's text is highlighted once, the first time a line of it is in view. */
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
    const made = text === null || language === null ? [] : tokensIn(treeOf(file, side, text, language));
    highlights.set(file, { ...kept, [side]: made });
    return made;
}

/**
 * Return the tokens of `tokens` within `row`, counted from the row's start, each with some text: a grammar's tokens
 * of no width (Python's indentation, say) are left out, since CodeMirror refuses an empty mark, and a view plugin
 * that throws is dropped, its highlighting gone until the page loads again.
 */
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
        const from = Math.max(token.from, row.offset) - row.offset;
        const to = Math.min(token.to, end) - row.offset;
        if (to > from) {
            found.push({ from, to, classes: token.classes });
        }
    }
    return found;
}
