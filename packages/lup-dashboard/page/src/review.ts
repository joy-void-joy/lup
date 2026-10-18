// The review: everything waiting for the operator laid out as one text to read
// and move through, their comments in it, each under the line it's on. Pure: the
// editor (`Review.tsx`) draws it and lets the comments be edited, and the host
// keeps the draft (`docs/dashboard.md`, *The review*).
import type { components } from "./generated/api";

export type Item = components["schemas"]["Item"];
export type Draft = components["schemas"]["Draft"];
export type Comment = components["schemas"]["Comment"];
export type Quote = components["schemas"]["Quote"];

/** A stretch of the text, from its start to its end. */
export interface Span {
    from: number;
    to: number;
}

/** One line of an item's own text, where it's shown, and where it starts in that text. */
export interface Line extends Span {
    own: number;
}

/** One comment, where its lines are shown: `comment` is its place in the draft. */
export interface Block extends Span {
    comment: number;
}

/** One item, where it's shown: its header line, its own lines, and its comments among them. */
export interface Region {
    item: Item;
    header: Span;
    lines: Line[];
    blocks: Block[];
}

/** The review's text, and where each item is in it. */
export interface Laid {
    text: string;
    regions: Region[];
}

export const EMPTY: Draft = { comments: [], done: [], parked: [] };

/** Return an item's own text as the review shows it: a message's or a question's words with its decisions, an approval's question and summary, and its whole diff where it's opened. */
export function body(item: Item, diff: string | undefined): string {
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
        case "approval": {
            const summary = plain(reason.summary);
            const whole = diff === undefined ? "Space e shows the whole diff." : plain(diff);
            return `${reason.text}\n${summary}\n${whole}`;
        }
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

/** Return the line of `text` an offset is on, counting from 0. */
function lineOf(starts: number[], offset: number): number {
    const found = starts.findLastIndex((each) => each <= offset);
    return Math.max(found, 0);
}

/**
 * Lay `items` out as one text: those to answer now first, then the parked ones, each under a header naming it,
 * each comment of the draft on it under the line it's on: a comment on a passage under the passage's last line,
 * one on the item whole under its header.
 */
export function laid(
    items: Item[],
    header: (item: Item, parked: boolean) => string,
    draft: Draft,
    diffs: Map<number, string>,
): Laid {
    const parked = draft.parked ?? [];
    const comments = draft.comments ?? [];
    const ordered = [
        ...items.filter((each) => !parked.includes(each.number)),
        ...items.filter((each) => parked.includes(each.number)),
    ];
    let text = "";
    const regions: Region[] = [];
    for (const item of ordered) {
        const own = body(item, diffs.get(item.number)).split("\n");
        const starts = own.map((_, at) => own.slice(0, at).reduce((sum, line) => sum + line.length + 1, 0));
        const mine = comments.flatMap((comment, at) => (comment.item === item.number ? [{ comment, at }] : []));
        const under = (line: number | null) =>
            mine.filter(({ comment }) =>
                comment.quote == null ? line === null : line !== null && lineOf(starts, Math.max(comment.quote.end - 1, comment.quote.start)) === line,
            );
        const blocks: Block[] = [];
        const lines: Line[] = [];
        const writeBlocks = (line: number | null) => {
            for (const { comment, at } of under(line)) {
                const from = text.length;
                text += `${comment.text}\n`;
                blocks.push({ comment: at, from, to: from + comment.text.length });
            }
        };
        const head = header(item, parked.includes(item.number));
        const headFrom = text.length;
        text += `${head}\n`;
        writeBlocks(null);
        own.forEach((line, at) => {
            const from = text.length;
            text += `${line}\n`;
            lines.push({ from, to: from + line.length, own: starts[at] ?? 0 });
            writeBlocks(at);
        });
        text += "\n";
        regions.push({ item, header: { from: headFrom, to: headFrom + head.length }, lines, blocks });
    }
    return { text, regions };
}

/** Return the region `position` is in: its header, its lines, its comments, or the blank line after it. */
export function regionAt(regions: Region[], position: number): Region | undefined {
    return regions.find((each, at) => {
        const next = regions[at + 1];
        return position >= each.header.from && (next === undefined || position < next.header.from);
    });
}

/** Return the comment shown at `position`, where it's in one; a comment's end counts, so an empty one can be typed in. */
export function blockAt(laidOut: Laid, position: number): Block | undefined {
    return laidOut.regions.flatMap((each) => each.blocks).find((each) => position >= each.from && position <= each.to);
}

/** Return the item's own line shown at `position`, where it's on one. */
export function lineAt(region: Region, position: number): Line | undefined {
    return region.lines.find((each) => position >= each.from && position <= each.to);
}

/** Return where a comment opened on the line at `position` goes: on that line of its item, or on the item whole from its header or an empty line; none outside every item. */
export function opened(laidOut: Laid, position: number): Comment | undefined {
    const region = regionAt(laidOut.regions, position);
    if (region === undefined) {
        return undefined;
    }
    const line = lineAt(region, position);
    const shown = line === undefined ? "" : laidOut.text.slice(line.from, line.to);
    if (line === undefined || shown === "") {
        return { item: region.item.number, quote: null, text: "" };
    }
    return {
        item: region.item.number,
        quote: { text: shown, start: line.own, end: line.own + shown.length },
        text: "",
    };
}

/** Return a comment on the passage `from` to `to` selects, counted in its item's own text; none where it isn't all inside one item's own lines. */
export function quoted(laidOut: Laid, from: number, to: number): Comment | undefined {
    const region = regionAt(laidOut.regions, from);
    const first = region === undefined ? undefined : lineAt(region, from);
    const last = region === undefined ? undefined : lineAt(region, Math.max(to - 1, from));
    if (region === undefined || first === undefined || last === undefined || to <= from) {
        return undefined;
    }
    const start = first.own + (from - first.from);
    const end = last.own + (Math.min(to, last.to) - last.from);
    const own = region.lines.map((each) => laidOut.text.slice(each.from, each.to)).join("\n");
    return { item: region.item.number, quote: { text: own.slice(start, end), start, end }, text: "" };
}

/** Return where in the text an offset of an item's own text is shown. */
export function shownAt(region: Region, offset: number): number {
    const line = [...region.lines].reverse().find((each) => each.own <= offset) ?? region.lines[0];
    return line === undefined ? region.header.to : Math.min(line.from + (offset - line.own), line.to);
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
    return { ...draft, comments: (draft.comments ?? []).filter((each) => each.text.trim() !== "") };
}
