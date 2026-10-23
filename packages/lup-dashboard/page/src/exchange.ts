// What the review shows around an agent's words where they answer the operator (`docs/dashboard.md`, *The review*):
// the operator's words they answer, above them, each part as the host numbers it (`spoken`, `inbox/threads.py`), so
// a citation's passage is found among them; each citation of the operator's words in them, which unfolds under its
// line to the passage it cites; what an edit changed; and, for an item kept with replies from before agents answered
// in their turn's last words, the operator's comments on it and the agent's replies, each after who wrote it. Pure:
// `review.ts` lays these lines out, and `Review.tsx` draws the citations and the passages they answer.
import { cited, starts, type Quote } from "./comments";
import type { components } from "./generated/api";

type Item = components["schemas"]["Item"];
type Conversation = components["schemas"]["Conversation"];
type PartId = components["schemas"]["PartId"];
export type Citation = components["schemas"]["Citation"];

/** One part of the operator's words, as the host numbers it (`spoken`): its id, their words, and what they're on. */
export interface Said {
    id: PartId;
    text: string;
    /** The agent's item it's on, for a comment on one, a reply to one, or a ruling. */
    on: number | null;
    /** The passage of that item it's on, or of the conversation for a message sent from reading it. */
    quote: Quote | null;
    /** Whom a review's message or remark was written to. */
    to: Conversation | null;
    /** The decision a ruling rules on, from 1, and its verdict. */
    decision: number | null;
    verdict: string | null;
    /** Whether it's a remark, written in one of the agent's drawers. */
    remark: boolean;
}

/** What a line around an agent's words shows: who wrote what follows, what the operator's words are on, their words, the agent's, a passage a citation cites, or a line an edit took away or put in. */
export type RowKind = "by" | "quoted" | "you" | "agent" | "cited" | "was" | "now";

/** One line around an agent's words: what it shows, and, for the operator's words, the part it's of and where it starts in that part's text. */
export interface Row {
    kind: RowKind;
    text: string;
    part: PartId | null;
    own: number;
}

/** How far a passage's lines under its citation, and the operator's words above an agent's, are set in after their first. */
export const SET_IN = "  ";


/** Return whether two conversations are the same one. */
export function same(a: Conversation | null | undefined, b: Conversation | null | undefined): boolean {
    return (
        a != null &&
        b != null &&
        a.repository === b.repository &&
        a.runtime === b.runtime &&
        a.session === b.session &&
        (a.agent ?? null) === (b.agent ?? null)
    );
}

/** Return whether two ids name the same part. */
export function samePart(a: PartId | null | undefined, b: PartId | null | undefined): boolean {
    return a != null && b != null && a.item === b.item && a.part === b.part;
}

/**
 * Return every part of `item` that's the operator's own words, in the item's order, numbered as the host numbers them
 * (`spoken`, `inbox/threads.py`): first what they said on an agent's words (a review's comments; the comment a reply to
 * a message carries; each passage's reply in a message sent from reading a conversation; an answer's rulings, then its
 * comment), then, after those and after any replies kept on the item from before, a review's messages and remarks, or
 * a message's words on the whole. None for an item that isn't the operator's.
 */
export function spokenOf(item: Item): Said[] {
    if (item.sender.party !== "operator") {
        return [];
    }
    const reason = item.reason;
    const id = (part: number): PartId => ({ item: item.number, part });
    const plain = { on: null, quote: null, to: null, decision: null, verdict: null, remark: false };
    const on: Said[] = [];
    const rest: Omit<Said, "id">[] = [];
    switch (reason.reason) {
        case "review":
            reason.comments.forEach((each, at) => {
                on.push({ ...plain, id: id(at + 1), text: each.text, on: each.item, quote: each.quote ?? null });
            });
            for (const each of reason.letters ?? []) {
                rest.push({ ...plain, text: each.text, to: each.to });
            }
            for (const each of reason.remarks ?? []) {
                rest.push({ ...plain, text: each.text, to: each.to, quote: each.quote, remark: true });
            }
            break;
        case "message":
            if (reason.of != null) {
                on.push({ ...plain, id: id(1), text: reason.text, on: reason.of });
                break;
            }
            reason.passages.forEach((each, at) => {
                on.push({ ...plain, id: id(at + 1), text: each.text, quote: { text: each.quote, start: 0, end: each.quote.length } });
            });
            if (reason.text.trim() !== "") {
                rest.push({ ...plain, text: reason.text });
            }
            break;
        case "answer": {
            const rulings = reason.rulings ?? [];
            rulings.forEach((each, at) => {
                on.push({ ...plain, id: id(at + 1), text: each.comment ?? "", on: reason.question, decision: each.decision, verdict: each.verdict ?? null });
            });
            if ((reason.comment ?? "") !== "") {
                on.push({ ...plain, id: id(rulings.length + 1), text: reason.comment ?? "", on: reason.question });
            }
            break;
        }
        default:
            return [];
    }
    const after = on.length + (item.replies ?? []).length;
    return [...on, ...rest.map((each, at) => ({ ...each, id: id(after + at + 1) }))];
}

/** Return the words of a part as lines of the operator's, each with where it starts in them; their trailing blank lines left out. */
function worded(said: Said, first: string, then: string = SET_IN): Row[] {
    const lines = said.text.trimEnd().split("\n");
    const at = starts(lines);
    return lines.map((line, index) => ({
        kind: "you",
        text: `${index === 0 ? first : then}${line}`,
        part: said.id,
        own: (at[index] ?? 0) - (index === 0 ? first.length : then.length),
    }));
}

/** Say a passage the operator's words were on, cut to its first line, as a quote's cue is. */
function cue(text: string): string {
    const line = text.split("\n")[0] ?? "";
    return line.length > 80 ? `${line.slice(0, 79).trimEnd()}…` : line;
}

/** A line saying what follows, of the operator's words or an agent's. */
function by(text: string): Row {
    return { kind: "by", text, part: null, own: 0 };
}

/** A line saying what the operator's words after it are on. */
function quoted(text: string): Row {
    return { kind: "quoted", text: `${SET_IN}${text}`, part: null, own: 0 };
}

/** Say what an item of the operator's is, to the agent it was sent to, after `you ·`. */
function theirs(item: Item): string {
    const reason = item.reason;
    switch (reason.reason) {
        case "review":
            return "your review";
        case "answer":
            return `your answer to ${cited(reason.question)}`;
        case "message":
            return reason.of == null ? "your message" : `your reply to ${cited(reason.of)}`;
        default:
            return `your ${reason.reason}`;
    }
}

/** Return the text an agent's item holds of its own words, which an edit changes: a message's, a question's, a friction's, how it went's, a stop's; none of any other. */
export function ownText(item: Item): string | null {
    const reason = item.reason;
    switch (reason.reason) {
        case "message":
        case "question":
        case "friction":
        case "how it went":
            return reason.text;
        case "stop":
            return reason.why;
        default:
            return null;
    }
}

/** Return an agent's item's words as the review shows them, which a comment's quote counts in: a question's with each decision numbered, its lean under it (`body`, `review.ts`); its own text for any other an edit changes. */
function shownText(item: Item): string | null {
    const reason = item.reason;
    if (reason.reason === "question") {
        return [reason.text, ...reason.decisions.map((each, at) => `${at + 1}. ${each.text}\n   lean: ${each.lean}`)].join("\n");
    }
    return ownText(item);
}

/**
 * Return whether a comment on `item`'s text, quoting `quote`, is outdated: the item was edited since, and its text no
 * longer holds the passage where the comment quoted it.
 */
export function outdated(item: Item | undefined, quote: Quote | null | undefined): boolean {
    if (item === undefined || quote == null || (item.edits ?? []).length === 0) {
        return false;
    }
    const text = shownText(item);
    return text !== null && text.slice(quote.start, quote.end) !== quote.text;
}

/**
 * Return the lines of the operator's words that `item`, an agent's, answers (`Message.answers`), above its own: for
 * each of their items it answers, who wrote it and what it is, then what of it was the agent's: a review's message and
 * remarks to it and its comments on the agent's own items, each after what it's on, a comment on a passage an edit
 * changed said to be outdated; a message's words; an answer's rulings, each after its decision, then its comment. The
 * operator's items are read from `answers`, the agent's they're on from `commented`; none where the item answers
 * nothing.
 */
export function above(item: Item, answers: Item[], commented: Item[]): Row[] {
    const reason = item.reason;
    const agent = item.sender.party === "conversation" ? item.sender : null;
    if (reason.reason !== "message" || agent === null) {
        return [];
    }
    const numbers = reason.answers ?? [];
    const onItems = new Map(commented.map((each) => [each.number, each]));
    return numbers.flatMap((number) => {
        const theirsItem = answers.find((each) => each.number === number);
        if (theirsItem === undefined) {
            return [];
        }
        const rows: Row[] = [by(`you · ${cited(number)}, ${theirs(theirsItem)}`)];
        const said = spokenOf(theirsItem);
        const whose = (on: number | null) => (on === null ? undefined : onItems.get(on));
        for (const each of said.filter((part) => part.to !== null && !part.remark && same(part.to, agent))) {
            rows.push(...worded(each, SET_IN));
        }
        for (const each of said.filter((part) => part.remark && same(part.to, agent))) {
            rows.push(quoted(`on your words: “${cue(each.quote?.text ?? "")}”`), ...worded(each, SET_IN));
        }
        for (const each of said.filter((part) => part.to === null)) {
            const on = whose(each.on);
            if (each.on !== null && on !== undefined && !same(on.sender.party === "conversation" ? on.sender : null, agent)) {
                continue;
            }
            const where = each.on === null ? "" : `on ${cited(each.on)}`;
            const decided = each.decision === null ? "" : `${where === "" ? "" : ", "}decision ${each.decision}${each.verdict === null ? "" : ` · ${each.verdict}`}`;
            const passage = each.quote === null ? "" : `${where === "" && decided === "" ? "" : ": "}“${cue(each.quote.text)}”`;
            const stale = outdated(on, each.quote) ? " · outdated: the passage changed" : "";
            if (where !== "" || decided !== "" || passage !== "") {
                rows.push(quoted(`${where}${decided}${passage}${stale}`));
            }
            if (each.text.trim() !== "") {
                rows.push(...worded(each, SET_IN));
            }
        }
        return rows;
    });
}

/** One citation in an agent's words, by the line of its own text it's on. */
export interface OnLine {
    line: number;
    citation: Citation;
}

/** Return each citation of `item`'s that found its passage, by the line of `lines`, its own text's, it starts on: where it unfolds. */
export function citedOn(item: Item, lines: string[]): OnLine[] {
    const at = starts(lines);
    return (item.citations ?? []).flatMap((citation) => {
        if (citation.found == null) {
            return [];
        }
        const line = at.findLastIndex((start) => start <= citation.start);
        return line < 0 ? [] : [{ line, citation }];
    });
}

/** Return the lines a citation unfolds to under its line: the passage it cites, whole, after who wrote it and the part it's of. */
export function passageOf(citation: Citation): Row[] {
    const found = citation.found;
    if (found == null) {
        return [];
    }
    const lines = found.text.split("\n");
    const head = `you, ${cited(found.part.item)}.${found.part.part}: `;
    return lines.map((line, index) => ({
        kind: "cited",
        text: `${index === 0 ? head : " ".repeat(head.length)}${line}`,
        part: found.part,
        own: 0,
    }));
}

/** Say why a citation that found no passage is marked as not found: nothing its words read, or the several places they read. */
export function unfound(citation: Citation): string {
    const places = citation.candidates ?? [];
    if (places.length === 0) {
        return "not found: no words of yours to this agent read it";
    }
    const parts = [...new Set(places.map((each) => `${cited(each.part.item)}.${each.part.part}`))];
    return `not found: it reads ${places.length} ${places.length === 1 ? "place" : "places"}, in ${parts.join(", ")}`;
}

/** Where a citation's id ends in its text, `@820.9`, before its words: the marker a resolved one shows. */
export function markerEnd(citation: Citation): number {
    const bracket = citation.said.indexOf("[");
    return citation.start + (bracket < 0 ? citation.said.length : bracket);
}

/** What an edit changed of an agent's words: a summary line, the lines it took away and put in, and which of the lines as they stand it put in. */
export interface Edited {
    summary: string;
    rows: Row[];
    /** The lines of its own text, as it stands, the edits put in or changed. */
    changed: number[];
}

/**
 * Return what the edits of `item` changed of its own words since it was sent, line by line: each line taken away and
 * each put in, in order, by the longest run of lines the two share; none where it wasn't edited. `when` says a moment.
 */
export function editedOf(item: Item, when: (at: string) => string): Edited | null {
    const edits = item.edits ?? [];
    const first = edits[0];
    const last = edits.at(-1);
    const now = ownText(item);
    if (first === undefined || last === undefined || now === null) {
        return null;
    }
    const before = first.before.split("\n");
    const after = now.split("\n");
    // The longest run of lines the two share, from each line on, read from the end.
    const shared: number[][] = Array.from({ length: before.length + 1 }, () => new Array<number>(after.length + 1).fill(0));
    for (let i = before.length - 1; i >= 0; i -= 1) {
        for (let j = after.length - 1; j >= 0; j -= 1) {
            const row = shared[i] ?? [];
            row[j] = before[i] === after[j] ? (shared[i + 1]?.[j + 1] ?? 0) + 1 : Math.max(shared[i + 1]?.[j] ?? 0, row[j + 1] ?? 0);
        }
    }
    const rows: Row[] = [];
    const changed: number[] = [];
    let i = 0;
    let j = 0;
    while (i < before.length || j < after.length) {
        if (i < before.length && j < after.length && before[i] === after[j]) {
            i += 1;
            j += 1;
        } else if (i < before.length && (j >= after.length || (shared[i + 1]?.[j] ?? 0) >= (shared[i]?.[j + 1] ?? 0))) {
            rows.push({ kind: "was", text: `− ${before[i] ?? ""}`, part: null, own: 0 });
            i += 1;
        } else {
            rows.push({ kind: "now", text: `+ ${after[j] ?? ""}`, part: null, own: 0 });
            changed.push(j);
            j += 1;
        }
    }
    const times = edits.length === 1 ? "" : `, ${edits.length} times`;
    const lines = changed.length === 1 ? "1 line" : `${changed.length} lines`;
    return { summary: `edited ${when(last.at)} after it was sent${times} · ${lines} changed`, rows, changed };
}
