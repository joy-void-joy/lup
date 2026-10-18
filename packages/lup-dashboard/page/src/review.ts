// The review: everything waiting for the operator laid out as one text to read
// and move through, their comments in it, each under the line it's on. Under an
// approval or a held change, each file it changes, whole (`code.ts`), its lines
// commented on as the item's own are, the lines that matter in it, by the judge's
// reading, kept in order for the keys to walk; under each item its context.
// What's folded by default: the context, each run of a file's unchanged lines
// away from its changes and the lines that matter, and an automatic file whole
// under its header. Pure: the editor (`Review.tsx`) draws it, folds it and lets
// the comments be edited, and the host keeps the draft (`docs/dashboard.md`,
// *The review*). What it shares with a conversation's text is in `comments.ts`.
import { since } from "./agents";
import { shownOnce, type ChangedFile, type Matter, type Row } from "./code";
import {
    calls,
    passage,
    saying,
    shownIn,
    spoken,
    starts as startsOf,
    under,
    type Block,
    type Line,
    type Span,
} from "./comments";
import type { components } from "./generated/api";

export { calls, type Block, type ChangedFile, type Line, type Span };

export type Item = components["schemas"]["Item"];
export type Draft = components["schemas"]["Draft"];
export type Comment = components["schemas"]["Comment"];
export type { Quote } from "./comments";
export type Context = components["schemas"]["Context"];

/** What the host answered, asked for more of an item than its own text: what it showed, or why it refused. */
export type Answered<T> = { shown: T } | { refused: string };

/** What the review shows of each item beyond its own text, by the item's number, once the host has answered: its context, and each file an approval or a held change changes. */
export interface Around {
    contexts: Map<number, Answered<Context>>;
    files: Map<number, Answered<ChangedFile[]>>;
}

/**
 * What a line under an item that isn't its own text shows: a fold's summary; a step of its context, the operator's
 * words, the agent's, a run of calls, or the call that made the item; or why the host showed none.
 */
export type Kind = "summary" | "you" | "agent" | "calls" | "anchor" | "refused";

/** A line under an item that isn't its own text, so no comment is on it. */
export interface Aside extends Span {
    kind: Kind;
}

/** A line of a changed file under an item, which comments may be on: the file's header, where `row` is none, or one of its rows, and what it triggered where it's a line that matters. */
export interface Coded extends Span {
    file: ChangedFile;
    row: Row | null;
    matter: Matter | null;
}

/**
 * What folds under an item, folded by default: its context, a run of a file's unchanged lines, an automatic file under
 * its header, or, where it's marked read, all of it under its header. It hides `from` to `to`, from the end of its
 * summary line to the end of its last; an automatic file's from the end of the comments on its header, which stay in
 * view.
 */
export interface Fold extends Span {
    item: number;
    kind: "context" | "code" | "file" | "read";
    /** What names it among its item's folds of its kind: a run of code by its file and its first row, a file by its path. */
    name: string;
    summary: Span;
}

/**
 * One item, where it's shown: the banner of the group it opens, if it's the first of one; its header line, the lines
 * comments may be on (its own, then its files' headers and rows) with its comments among them; then the lines under
 * it, and what folds.
 */
export interface Region {
    item: Item;
    banner: Span | null;
    header: Span;
    lines: Line[];
    blocks: Block[];
    /** Its lines that are its files', each with its file and row. */
    code: Coded[];
    asides: Aside[];
    folds: Fold[];
    /** Where its lines that matter start, in order: a file's header where what it asks is about the file whole, then the first row of each thing a line triggered. */
    stops: number[];
}

/** The review's text, and where each item is in it. */
export interface Laid {
    text: string;
    regions: Region[];
}

export const EMPTY: Draft = { comments: [], done: [], parked: [] };

/** Return an item's own text as the review shows it: a message's or a question's words with its decisions, an approval's question and summary. */
export function body(item: Item): string {
    const reason = item.reason;
    switch (reason.reason) {
        case "message":
            return reason.text;
        case "question": {
            const decisions = reason.decisions.map(
                (each, at) => `${at + 1}. ${each.text}\n   lean: ${each.lean}`,
            );
            return [reason.text, ...decisions].join("\n");
        }
        case "approval":
            return `${reason.text}\n${plain(reason.summary)}`;
        case "held":
            return `${reason.text}\n${reason.summary}`;
        case "answer":
            return reason.comment;
        case "review":
            return reason.comments.map((each) => each.text).join("\n");
    }
}

/** Return `text` without the terminal's colour codes git colours a diff with. */
export function plain(text: string): string {
    return text.replace(/\u001b\[[0-9;]*m/g, "");
}

/** One line under an item that isn't its own text, and what it shows. */
export interface Said {
    kind: Kind;
    text: string;
}

/** What shows under an item's files: its context, its summary line with the lines that fold under it; or, where the host refused it, a line saying why. */
interface Under {
    summary: Said;
    lines: Said[];
}

/** Return an item's context as the lines it's shown in: each thing said after who said it, its own lines kept; each run of calls in one line; and the call that made the item, marked. */
export function steps(context: Context): Said[] {
    const shown: Said[] = [];
    let run: string[] = [];
    const ran = () => {
        if (run.length > 0) {
            shown.push({ kind: "calls", text: calls(run) });
            run = [];
        }
    };
    context.entries.forEach((entry, at) => {
        if (entry.kind === "called" && at !== context.anchor) {
            run.push(entry.tool);
            return;
        }
        ran();
        if (entry.kind === "called") {
            shown.push({ kind: "anchor", text: `→ called ${entry.tool} · this item` });
            return;
        }
        const who: Kind = entry.by === "operator" ? "you" : "agent";
        shown.push(...spoken(who, entry.text, false).map((row) => ({ kind: who, text: row.text })));
    });
    ran();
    return shown;
}

/** Say what an item's context holds: how many steps, and from whose words and how long before the item. */
function told(item: Item, context: Context): string {
    const count = `context · ${context.entries.length} ${context.entries.length === 1 ? "step" : "steps"}`;
    const first = context.entries[0];
    const yours = first?.kind === "said" && first.by === "operator";
    const before = first?.at == null ? "" : ` ${since(new Date(first.at), new Date(item.made))} before this item`;
    if (!yours && before === "") {
        return count;
    }
    return `${count}, from${yours ? " your words" : ""}${before}`;
}

/** Return the item's context as it shows under the item, of what the host has answered; none before it has. */
function beneath(item: Item, around: Around): Under | null {
    const context = around.contexts.get(item.number);
    if (context === undefined) {
        return null;
    }
    return {
        summary:
            "shown" in context
                ? { kind: "summary", text: told(item, context.shown) }
                : { kind: "refused", text: `no context: ${context.refused}` },
        lines: "shown" in context ? steps(context.shown) : [],
    };
}

/**
 * One line under an item's own text that comments may be on, of a changed file: its header, or one of its rows, the
 * run of unchanged rows it opens, if any, before it, and whether it ends one; what it triggered, where it's a line that
 * matters, and whether it's a stop, the first line of what triggered; and, for an automatic file, the fold its header
 * opens and its last row ends.
 */
interface Filed {
    file: ChangedFile;
    row: Row | null;
    text: string;
    opens: { summary: string; name: string } | null;
    closes: boolean;
    matter: Matter | null;
    stop: boolean;
    folds: string | null;
    ends: boolean;
}

/**
 * Return the lines of each file an approval or a held change changes, as the host answered them: each file's header,
 * then its rows, its runs of unchanged ones folding, and the whole of an automatic one folding under its header; none
 * for any other item, or before the host has answered.
 */
function filed(item: Item, around: Around): Filed[] {
    const files = around.files.get(item.number);
    if ((item.reason.reason !== "approval" && item.reason.reason !== "held") || files === undefined || !("shown" in files)) {
        return [];
    }
    return files.shown.flatMap((file) => {
        const laidOut = shownOnce(file);
        const folding = laidOut.automatic && laidOut.rows.length > 0;
        const header: Filed = {
            file,
            row: null,
            text: laidOut.header,
            opens: null,
            closes: false,
            matter: null,
            stop: laidOut.whole,
            folds: folding ? file.path : null,
            ends: false,
        };
        const matters = new Map(laidOut.matters.map((each) => [each.row, each]));
        const rows = laidOut.rows.map((row, at): Filed => {
            const run = laidOut.runs.find((each) => each.from === at);
            const matter = matters.get(at) ?? null;
            return {
                file,
                row,
                text: row.text,
                opens: run === undefined ? null : { summary: run.summary, name: `${file.path}:${at}` },
                closes: laidOut.runs.some((each) => each.to === at + 1),
                matter,
                stop: (matter?.notes.length ?? 0) > 0,
                folds: null,
                ends: folding && at === laidOut.rows.length - 1,
            };
        });
        return [header, ...rows];
    });
}

/** Return `items` in groups, each under its banner: the group with the newest item first, and the items in each in their own order. */
function grouped(items: Item[], banner: (item: Item) => string): Item[][] {
    const groups = new Map<string, Item[]>();
    for (const item of items) {
        const key = banner(item);
        groups.set(key, [...(groups.get(key) ?? []), item]);
    }
    const made = (group: Item[]) => Math.max(...group.map((each) => new Date(each.made).getTime()));
    const numbered = (group: Item[]) => Math.max(...group.map((each) => each.number));
    return [...groups.values()].sort((a, b) => made(b) - made(a) || numbered(b) - numbered(a));
}

/** Say how long an item has waited, to the minute: what came in under a minute ago is just in. */
export function waited(made: string, now: Date): string {
    const at = new Date(made);
    return now.getTime() - at.getTime() < 60_000 ? "just in" : `waiting ${since(at, now)}`;
}

/** Say whether an item is new to the operator: made after they last settled one of theirs, `reviewed`; none before their first. */
export function fresh(item: Item, reviewed: string | null | undefined): boolean {
    return reviewed != null && new Date(item.made) > new Date(reviewed);
}

/**
 * Lay `items` out as one text: those to answer now first, then the parked ones, each in the group its banner names
 * (the agent that sent it), each under a header naming it, each comment of the draft on it under the line it's on:
 * a comment on a passage under the passage's last line, one on the item whole under its header. Under each item's
 * own text, what the host has answered of it: each file an approval or a held change changes, its header then its
 * lines, each run of unchanged ones folding under a summary line; then the item's context, a summary line with the
 * lines that fold under it. Where the host showed none, a line says why.
 */
export function laid(
    items: Item[],
    banner: (item: Item, parked: boolean) => string,
    header: (item: Item, parked: boolean) => string,
    draft: Draft,
    around: Around,
): Laid {
    const parked = draft.parked ?? [];
    const done = draft.done ?? [];
    const comments = draft.comments ?? [];
    const now = grouped(items.filter((each) => !parked.includes(each.number)), (item) => banner(item, false));
    const later = grouped(items.filter((each) => parked.includes(each.number)), (item) => banner(item, true));
    let text = "";
    const regions: Region[] = [];
    for (const group of [...now, ...later]) {
        group.forEach((item, at) => {
            const isParked = parked.includes(item.number);
            let opening: Span | null = null;
            if (at === 0) {
                const said = banner(item, isParked);
                opening = { from: text.length, to: text.length + said.length };
                text += `${said}\n`;
            }
            layItem(item, opening, isParked);
        });
    }
    return { text, regions };

    function layItem(item: Item, opening: Span | null, isParked: boolean): void {
        const files = filed(item, around);
        // Its own lines, then its files': the text comments are placed in, by where each quote ends.
        const own = [...body(item).split("\n"), ...files.map((each) => each.text)];
        const starts = startsOf(own);
        const ownCount = own.length - files.length;
        // Each comment on the item, by the line it's under, once.
        const placed = new Map<number | null, { comment: Comment; at: number }[]>();
        comments.forEach((comment, at) => {
            if (comment.item === item.number) {
                const line = under(starts, comment.quote);
                placed.set(line, [...(placed.get(line) ?? []), { comment, at }]);
            }
        });
        const blocks: Block[] = [];
        const lines: Line[] = [];
        const code: Coded[] = [];
        const asides: Aside[] = [];
        const folds: Fold[] = [];
        const writeBlocks = (line: number | null) => {
            for (const { comment, at } of placed.get(line) ?? []) {
                const from = text.length;
                text += `${comment.text}\n`;
                blocks.push({ comment: at, from, to: from + comment.text.length });
            }
        };
        const writeLine = (line: string, at: number): Line => {
            const from = text.length;
            text += `${line}\n`;
            const written = { from, to: from + line.length, own: starts[at] ?? 0 };
            lines.push(written);
            return written;
        };
        const writeAside = (said: Said): Aside => {
            const from = text.length;
            text += `${said.text}\n`;
            const aside = { kind: said.kind, from, to: from + said.text.length };
            asides.push(aside);
            return aside;
        };
        const head = header(item, isParked);
        const headFrom = text.length;
        text += `${head}\n`;
        writeBlocks(null);
        own.slice(0, ownCount).forEach((line, at) => {
            writeLine(line, at);
            writeBlocks(at);
        });
        const stops: number[] = [];
        let opened: { summary: Aside; name: string } | null = null;
        let whole: { summary: Span; name: string; from: number } | null = null;
        files.forEach((each, index) => {
            if (each.opens !== null) {
                opened = { summary: writeAside({ kind: "summary", text: each.opens.summary }), name: each.opens.name };
            }
            const at = ownCount + index;
            const written = writeLine(each.text, at);
            code.push({ from: written.from, to: written.to, file: each.file, row: each.row, matter: each.matter });
            if (each.stop) {
                stops.push(written.from);
            }
            const run: { summary: Aside; name: string } | null = opened;
            if (each.closes && run !== null) {
                const summary = { from: run.summary.from, to: run.summary.to };
                folds.push({ item: item.number, kind: "code", name: run.name, summary, from: summary.to, to: written.to });
                opened = null;
            }
            const automatic: { summary: Span; name: string; from: number } | null = whole;
            if (each.ends && automatic !== null) {
                const { summary, name, from } = automatic;
                folds.push({ item: item.number, kind: "file", name, summary, from, to: written.to });
                whole = null;
            }
            writeBlocks(at);
            if (each.folds !== null) {
                // The file folds under its header and the comments on it, which stay in view.
                whole = { summary: { from: written.from, to: written.to }, name: each.folds, from: text.length - 1 };
            }
        });
        const refused = around.files.get(item.number);
        if (refused !== undefined && "refused" in refused) {
            writeAside({ kind: "refused", text: `no files: ${refused.refused}` });
        }
        const context = beneath(item, around);
        if (context !== null) {
            const summary = writeAside(context.summary);
            const last = context.lines.map(writeAside).at(-1);
            if (last !== undefined) {
                const shown = { from: summary.from, to: summary.to };
                folds.push({ item: item.number, kind: "context", name: "", summary: shown, from: summary.to, to: last.to });
            }
        }
        if (done.includes(item.number)) {
            // Marked read, it folds whole under its header, what folds within it inside.
            const header = { from: headFrom, to: headFrom + head.length };
            folds.push({ item: item.number, kind: "read", name: "", summary: header, from: header.to, to: text.length - 1 });
        }
        text += "\n";
        regions.push({
            item,
            banner: opening,
            header: { from: headFrom, to: headFrom + head.length },
            lines,
            blocks,
            code,
            asides,
            folds,
            stops,
        });
    }
}

/** Where a region starts: at the banner of the group it opens, else at its header. */
function start(region: Region): number {
    return region.banner?.from ?? region.header.from;
}

/** Return where going to an item lands: on its first line that matters, as the judge read its files, unless it's marked read; else on its header. */
export function arrival(region: Region): number {
    const read = region.folds.some((each) => each.kind === "read");
    return (read ? undefined : region.stops[0]) ?? region.header.from;
}

/** Return the stop after the line starting at `line`, or before it, of `stops`, in the text's order; none past the last, or before the first. */
export function stepped(stops: number[], line: number, forward: boolean): number | undefined {
    return forward ? stops.find((each) => each > line) : [...stops].reverse().find((each) => each < line);
}

/** Return the region `position` is in: the banner of the group it opens, its header, its lines, its comments, or the blank line after it. */
export function regionAt(regions: Region[], position: number): Region | undefined {
    return regions.find((each, at) => {
        const next = regions[at + 1];
        return position >= start(each) && (next === undefined || position < start(next));
    });
}

/** Return whether `position` is on a group's banner, which no comment is on. */
export function onBanner(region: Region, position: number): boolean {
    return region.banner !== null && position >= region.banner.from && position <= region.banner.to;
}

/** Return the comment shown at `position`, where it's in one; a comment's end counts, so an empty one can be typed in. */
export function blockAt(laidOut: Laid, position: number): Block | undefined {
    return laidOut.regions.flatMap((each) => each.blocks).find((each) => position >= each.from && position <= each.to);
}

/** Return the item's own line shown at `position`, where it's on one. */
export function lineAt(region: Region, position: number): Line | undefined {
    return region.lines.find((each) => position >= each.from && position <= each.to);
}

/** Return the line under an item that isn't its own text shown at `position`, where it's on one. */
export function asideAt(region: Region, position: number): Aside | undefined {
    return region.asides.find((each) => position >= each.from && position <= each.to);
}

/** Return the fold `position` is on: on its summary line or the lines it hides. */
export function foldAt(laidOut: Laid, position: number): Fold | undefined {
    return laidOut.regions
        .flatMap((each) => each.folds)
        .find((each) => position >= each.summary.from && position <= each.to);
}

/** Return what names a fold across layouts: its item's number, what it holds, and which of those it is. */
export function foldKey(fold: Fold): string {
    return `${fold.item} ${fold.kind} ${fold.name}`;
}

/** Return where the first of `code` ending at or after `position` is among them, found by halving: they're in the text's order. */
export function codeFrom(code: Coded[], position: number): number {
    let low = 0;
    let high = code.length;
    while (low < high) {
        const middle = (low + high) >> 1;
        if ((code[middle]?.to ?? 0) < position) {
            low = middle + 1;
        } else {
            high = middle;
        }
    }
    return low;
}

/** Return the line of a changed file shown at `position`, where it's on one. */
export function codeAt(region: Region, position: number): Coded | undefined {
    const found = region.code[codeFrom(region.code, position)];
    return found !== undefined && position >= found.from && position <= found.to ? found : undefined;
}

/** How a line of a changed file is marked where a comment quotes it, as a diff marks it. */
const SIGNS: Record<Row["change"], string> = { added: "+", removed: "-", same: " " };

/**
 * Say the passage `from` to `to` selects on `lines` as a comment quotes it, so the agent can find it: the item's own
 * words as they are; a changed file's lines under the file's path and where they are in it (`path:12-14`, the
 * numbers what the file becomes, or what it was where they're all removed), each marked as a diff marks it; a file's
 * header alone, its path.
 */
function said(text: string, region: Region, lines: Line[], from: number, to: number): string {
    const parts = lines.map((line) => ({
        line,
        coded: codeAt(region, line.from),
        text: text.slice(Math.max(line.from, from), Math.min(line.to, Math.max(to, line.from))),
    }));
    const groups: (typeof parts)[] = [];
    for (const part of parts) {
        const last = groups.at(-1);
        const same = last?.[0]?.coded?.file === part.coded?.file;
        if (last !== undefined && same) {
            last.push(part);
        } else {
            groups.push([part]);
        }
    }
    return groups
        .map((group) => {
            const file = group[0]?.coded?.file;
            if (file === undefined) {
                return group.map((each) => each.text).join("\n");
            }
            const rows = group.flatMap((each) => (each.coded?.row == null ? [] : [{ row: each.coded.row, text: each.text }]));
            const kept = rows.filter((each) => each.row.side === "after");
            const numbered = (kept.length > 0 ? kept : rows).map((each) => each.row.number);
            const span = numbered.length === 0 ? "" : `:${spanOf(numbered)}`;
            const before = kept.length === 0 && rows.length > 0 ? ", as it was before the change" : "";
            return [`${file.path}${span}${before}`, ...rows.map((each) => `${SIGNS[each.row.change]}${each.text}`)].join(
                "\n",
            );
        })
        .join("\n");
}

/** Say a run of line numbers as a span: `12`, or `12-14`. */
function spanOf(numbers: number[]): string {
    const first = Math.min(...numbers);
    const last = Math.max(...numbers);
    return first === last ? `${first}` : `${first}-${last}`;
}

/**
 * Return where a comment opened on the line at `position` goes: on that line of its item, or on the item whole from
 * its header or an empty line of its own; on a line of a changed file, or its header, empty or not; none outside
 * every item, or on a line no comment is on.
 */
export function opened(laidOut: Laid, position: number): Comment | undefined {
    const region = regionAt(laidOut.regions, position);
    if (region === undefined || onBanner(region, position) || asideAt(region, position) !== undefined) {
        return undefined;
    }
    const line = lineAt(region, position);
    const shown = line === undefined ? "" : laidOut.text.slice(line.from, line.to);
    if (line === undefined || (shown === "" && codeAt(region, line.from) === undefined)) {
        return { item: region.item.number, quote: null, text: "" };
    }
    return {
        item: region.item.number,
        quote: { text: said(laidOut.text, region, [line], line.from, line.to), start: line.own, end: line.own + shown.length },
        text: "",
    };
}

/** Return a comment on the passage `from` to `to` selects, counted in its item's text, its own and its files'; none where it isn't all inside one item's lines. */
export function quoted(laidOut: Laid, from: number, to: number): Comment | undefined {
    const region = regionAt(laidOut.regions, from);
    const first = region === undefined ? undefined : lineAt(region, from);
    const last = region === undefined ? undefined : lineAt(region, Math.max(to - 1, from));
    if (region === undefined || first === undefined || last === undefined || to <= from) {
        return undefined;
    }
    const own = region.lines.map((each) => laidOut.text.slice(each.from, each.to)).join("\n");
    const quote = passage(own, first, last, from, to);
    const lines = region.lines.slice(region.lines.indexOf(first), region.lines.indexOf(last) + 1);
    if (lines.every((each) => codeAt(region, each.from) === undefined)) {
        return { item: region.item.number, quote, text: "" };
    }
    return { item: region.item.number, quote: { ...quote, text: said(laidOut.text, region, lines, from, to) }, text: "" };
}

/** Say an item's comments as one answer, as its agent reads them: each under the passage it quotes, set off as a mail quotes, in the order they were written; those on the whole after. */
export function answer(comments: Comment[]): string {
    const saying = comments.filter((each) => each.text.trim() !== "");
    const quoted = saying.filter((each) => each.quote != null).sort((a, b) => (a.quote?.start ?? 0) - (b.quote?.start ?? 0));
    const whole = saying.filter((each) => each.quote == null);
    const parts = quoted.map((each) => {
        const lines = (each.quote?.text ?? "").split("\n").map((line) => (line === "" ? ">" : `> ${line}`));
        return `${lines.join("\n")}\n\n${each.text.trim()}`;
    });
    return [...parts, ...whole.map((each) => each.text.trim())].join("\n\n");
}

/** Return where in the text an offset of an item's own text is shown. */
export function shownAt(region: Region, offset: number): number {
    return shownIn(region.lines, offset, region.header.to);
}

/** Return `draft` with `number` in `list` if it wasn't, and out of it if it was. */
export function toggled(draft: Draft, list: "done" | "parked", number: number): Draft {
    const present = draft[list] ?? [];
    const next = present.includes(number) ? present.filter((each) => each !== number) : [...present, number];
    return { ...draft, [list]: next };
}

/** Return the items a draft answers: each with a comment that says something, or marked done, but the parked ones. */
export function covered(draft: Draft): number[] {
    const parked = draft.parked ?? [];
    const mentioned = [
        ...(draft.comments ?? []).filter((each) => each.text.trim() !== "").map((each) => each.item),
        ...(draft.done ?? []),
    ];
    return [...new Set(mentioned)].filter((each) => !parked.includes(each)).sort((a, b) => a - b);
}

/** Return `draft` without the comments that say nothing. */
export function pruned(draft: Draft): Draft {
    return { ...draft, comments: saying(draft.comments ?? []) };
}
