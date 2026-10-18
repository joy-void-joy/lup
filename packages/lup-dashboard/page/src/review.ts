// The review: everything waiting for the operator laid out as one text to read
// and move through, and the draft reply they build while reading it. Pure: the
// editor (`Review.tsx`) draws it, and the host keeps the draft (`docs/dashboard.md`,
// *The review*).
import type { components } from "./generated/api";

export type Item = components["schemas"]["Item"];
export type Draft = components["schemas"]["Draft"];
export type Comment = components["schemas"]["Comment"];
export type Quote = components["schemas"]["Quote"];
export type Verdict = components["schemas"]["Verdict"];

/** A stretch of the text, from its start to its end. */
export interface Span {
    from: number;
    to: number;
}

/** A numbered decision of a question, where it's shown. */
export interface Asked extends Span {
    number: number;
}

/** One item, where it's shown: its header line, its own text (which a passage's place is counted in), and each decision. */
export interface Region {
    item: Item;
    header: Span;
    body: Span;
    decisions: Asked[];
}

/** The review's text, and where each item is in it. */
export interface Laid {
    text: string;
    regions: Region[];
}

export const EMPTY: Draft = { comments: [], verdicts: [], done: [], parked: [] };

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

/** Lay `items` out as one text: those to answer now first, then the parked ones, each under a header naming it. */
export function laid(
    items: Item[],
    header: (item: Item, parked: boolean) => string,
    parked: number[],
    diffs: Map<number, string>,
): Laid {
    const ordered = [
        ...items.filter((each) => !parked.includes(each.number)),
        ...items.filter((each) => parked.includes(each.number)),
    ];
    let text = "";
    const regions: Region[] = [];
    for (const item of ordered) {
        const head = header(item, parked.includes(item.number));
        const headFrom = text.length;
        text += `${head}\n`;
        const own = body(item, diffs.get(item.number));
        const bodyFrom = text.length;
        text += `${own}\n\n`;
        regions.push({
            item,
            header: { from: headFrom, to: headFrom + head.length },
            body: { from: bodyFrom, to: bodyFrom + own.length },
            decisions: decisions(item, own, bodyFrom),
        });
    }
    return { text, regions };
}

function decisions(item: Item, own: string, from: number): Asked[] {
    if (item.reason.reason !== "question") {
        return [];
    }
    const lines = own.split("\n");
    const asked: Asked[] = [];
    let at = from;
    let number = 0;
    for (const line of lines) {
        if (/^\d+\. /.test(line) && number < item.reason.decisions.length) {
            number += 1;
            asked.push({ number, from: at, to: at + line.length });
        }
        at += line.length + 1;
    }
    return asked;
}

/** Return the region `position` is in: its header, its text, or the blank line after it. */
export function regionAt(regions: Region[], position: number): Region | undefined {
    return regions.find((each, at) => {
        const next = regions[at + 1];
        return position >= each.header.from && (next === undefined || position < next.header.from);
    });
}

/** Return the decision on the line `position` is on, or just under. */
export function decisionAt(region: Region, position: number): Asked | undefined {
    return [...region.decisions].reverse().find((each) => position >= each.from);
}

/** Return the passage `from` to `to` selects, counted in its item's text; none where it isn't all inside one item's text. */
export function quoted(laidOut: Laid, from: number, to: number): { item: number; quote: Quote } | undefined {
    const region = regionAt(laidOut.regions, from);
    if (region === undefined || from < region.body.from || to > region.body.to || to <= from) {
        return undefined;
    }
    return {
        item: region.item.number,
        quote: {
            text: laidOut.text.slice(from, to),
            start: from - region.body.from,
            end: to - region.body.from,
        },
    };
}

/** Return `draft` with `number` in `list` if it wasn't, and out of it if it was. */
export function toggled(draft: Draft, list: "done" | "parked", number: number): Draft {
    const present = draft[list] ?? [];
    const next = present.includes(number) ? present.filter((each) => each !== number) : [...present, number];
    return { ...draft, [list]: next };
}

/** Return `draft` with decision `decision` of item `item` given `verdict`, or the verdict taken back where it was already that. */
export function ruled(draft: Draft, item: number, decision: number, verdict: Verdict): Draft {
    const verdicts = draft.verdicts ?? [];
    const other = verdicts.filter((each) => !(each.item === item && each.decision === decision));
    const same = verdicts.some(
        (each) => each.item === item && each.decision === decision && each.verdict === verdict,
    );
    return { ...draft, verdicts: same ? other : [...other, { item, decision, verdict }] };
}

/** Return the items a draft answers: each with a comment, a verdict or marked done, but the parked ones. */
export function covered(draft: Draft): number[] {
    const parked = draft.parked ?? [];
    const mentioned = [
        ...(draft.comments ?? []).flatMap((each) => (each.item == null ? [] : [each.item])),
        ...(draft.verdicts ?? []).map((each) => each.item),
        ...(draft.done ?? []),
    ];
    return [...new Set(mentioned)].filter((each) => !parked.includes(each)).sort((a, b) => a - b);
}
