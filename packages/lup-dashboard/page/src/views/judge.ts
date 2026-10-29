// The judge's views, which the page lays out until the judge is a module (#113, step 4; `views.ts`): its reading of
// each file a change touches, as the `Diff` the review shows it in (`judged`): why it's open, from what it asks and
// what lup found on its lines, held first, each said in its header's last words; which of its lines matter, each
// saying what it triggered; a file asking nothing, held or flagged, automatic, folding whole under its header, as a
// test and a data file do, by the reading's role, and each file of a first approval, which trusts the repository as it
// is, each header saying why (`Folded`). Then the views of its own items, a held change and a write that landed
// flagged, each a summary saying what it is and how its files read, and a body, its text and its files; "since you
// approved", what an agent's branch changed since the operator last saw it, each file whole, what's settled folded at
// its end; and its part of an agent's banner, whether their flagged writes are held. Pure.
import type { ChangedFile, Diff, Mark } from "../code";
import type { components } from "../generated/api";
import { reviewedLine } from "../since";
import { conversationOf, whose, type Answer, type Blocks, type Line, type OfAgent, type Offer, type Shown, type View } from "../views";

type Item = components["schemas"]["Item"];
type Reading = components["schemas"]["Reading"];
type Asked = components["schemas"]["Asked"];
type ApiChanged = components["schemas"]["ApiChanged"];
type Since = components["schemas"]["Since"];
type SinceFile = components["schemas"]["SinceFile"];
type Taken = Mark["taken"];

/** The most changes to the public API a header names: the rest are on their lines. */
const NAMED = 4;

/** One reason a file is open, or that it's automatic: its words in the header, and how a tally of an item's files counts it. */
export interface Reason {
    said: string;
    one: string;
    many: string;
}

/**
 * Why a file folds whole under its header, which says it where `automatic` would stand: a test, or a data file, by the
 * role the judge's reading gives it, whose lines the operator has little use for; or any file of a first approval,
 * which trusts the repository as it is rather than asking it read.
 */
export type Folded = "test" | "data" | "first approval";

/** What a file folded whole says in its header, and in a tally of an item's files. */
export const FOLDED: Record<Folded, Reason> = {
    test: { said: "test", one: "test", many: "tests" },
    data: { said: "data", one: "data file", many: "data files" },
    "first approval": { said: "first approval", one: "of a first approval", many: "of a first approval" },
};

/** Return why `file` folds whole under its header (`Folded`), where it's one of a first approval's (`first`) or by its role; none where it opens. */
export function foldedOf(file: ChangedFile, first: boolean): Folded | null {
    if (first) {
        return "first approval";
    }
    const role = file.reading?.role;
    return role === "test" || role === "data" ? role : null;
}

/** Say how many, in a few words. */
function counted(count: number, what: string): string {
    return `${count} ${what}${count === 1 ? "" : "s"}`;
}

/** Say what a change to the public API does, as a line that matters says it, in the judge's words (`ApiChange.describe`). */
function api(change: ApiChanged): string {
    const what = change.name.includes(".") ? "method" : "function";
    switch (change.kind) {
        case "export-added":
            return `adds \`${change.name}\` to the package's root`;
        case "export-removed":
            return `removes \`${change.name}\` from the package's root`;
        case "class-added":
            return `adds the class \`${change.name}\``;
        case "class-removed":
            return `removes the class \`${change.name}\``;
        case "function-added":
            return `adds the ${what} \`${change.name}\``;
        case "function-removed":
            return `removes the ${what} \`${change.name}\``;
        case "signature-changed":
            return `changes the signature of \`${change.name}\``;
    }
}

/** Mark a change to the public API in a header's few words: `+` a name added, `−` one removed, `~` a signature changed, which copies before found. */
function signed(change: ApiChanged): string {
    const sign = change.kind.endsWith("-removed") ? "−" : change.kind === "signature-changed" ? "~" : "+";
    return `${sign}${change.name}`;
}

/** Say what one ask on a line triggered. */
function triggered(asked: Asked): string {
    if (asked.api != null) {
        return `public API: ${api(asked.api)}`;
    }
    return asked.name === "ignore" ? "adds an ignore" : asked.name;
}

/**
 * Return what the reading found, as marks on the file's lines: each ask on its line, on the side it's in, what it
 * triggered said there, one about the file whole, or naming no line, marking its header; each finding over every line
 * it spans, what it triggered said on its first.
 */
function marksOf(reading: Reading | null): Mark[] {
    if (reading === null) {
        return [];
    }
    return [
        ...(reading.asks ?? []).map((asked): Mark => ({ taken: asked.taken, said: triggered(asked), side: asked.side ?? "after", first: asked.line ?? null, last: null })),
        ...(reading.findings ?? []).map((found): Mark => ({
            taken: found.taken,
            said: `${found.rule}: ${found.message.replaceAll("\n", " ")}`,
            side: "after",
            first: found.start,
            last: found.end,
        })),
    ];
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

/** What the judge reads of a file: why it's open, or folds whole, in its header's order; whether it asks nothing; and why it folds whole, where it does. */
interface Read {
    reasons: Reason[];
    automatic: boolean;
    folded: Folded | null;
}

/** Return what the judge reads of `file`, `first` where it's a first approval's: a file folded whole says why where `automatic` stands, or after what it asks. */
function readOf(file: ChangedFile, first: boolean): Read {
    const read = file.reading == null ? [] : reasoned(file.reading);
    const automatic = read[0]?.said === "automatic";
    const folded = foldedOf(file, first);
    const why = folded === null ? null : FOLDED[folded];
    const reasons = why === null ? read : automatic ? [why, ...read.slice(1)] : [...read, why];
    return { reasons, automatic, folded };
}

/** Each file as the judge reads it, by whether it's a first approval's, whether its bodies fold as a design's, and the version it's at: read once, as the review is laid out again at each key typed in a comment. */
const read = new WeakMap<ChangedFile, Map<string, Diff>>();

/**
 * Return `file` as the review shows it, a `Diff` (`id`, `file <path>`): `first` where it's a first approval's;
 * `design` where its bodies fold to show its design, as a new module's in "since you approved"; `version` the one it's
 * at, which a comment on it records. Made once for each and kept, so its layout is too.
 */
export function judged(file: ChangedFile, first: boolean, design: boolean = false, version: string | null = null): Diff {
    const kept = read.get(file) ?? new Map<string, Diff>();
    const key = JSON.stringify([first, design, version]);
    const found = kept.get(key);
    if (found !== undefined) {
        return found;
    }
    const { reasons, automatic, folded } = readOf(file, first);
    const made: Diff = {
        block: "diff",
        id: `file ${file.path}`,
        version,
        offers: [],
        path: file.path,
        before: file.before ?? null,
        after: file.after ?? null,
        says: reasons.map((each) => each.said),
        marks: marksOf(file.reading ?? null),
        open: folded === null && !automatic,
        automatic,
        design,
    };
    read.set(file, kept.set(key, made));
    return made;
}

/**
 * Count an item's files by the first reason each is open, or folds whole, `first` where it's a first approval, the
 * most first: `3 automatic · 2 tests · 1 new file · 1 public API`; files the judge didn't read are `unread`; nothing
 * where it read none.
 */
export function tally(files: ChangedFile[], first: boolean = false): string {
    if (files.every((each) => each.reading == null)) {
        return "";
    }
    const counts = new Map<string, { reason: Reason; count: number }>();
    for (const file of files) {
        const reason = (file.reading == null ? undefined : readOf(file, first).reasons[0]) ?? plainly("unread");
        const kept = counts.get(reason.one);
        counts.set(reason.one, { reason, count: (kept?.count ?? 0) + 1 });
    }
    return [...counts.values()]
        .sort((a, b) => b.count - a.count)
        .map(({ reason, count }) => `${count} ${count === 1 ? reason.one : reason.many}`)
        .join(" · ");
}

/** What an item's view is given: the item, by its number. */
export interface OfItem {
    number: number;
}

/**
 * Return the view of an item that changes files, an approval, a held change or a flagged write: its summary, what it
 * is (`what`) and how its files read, as the host has answered them (`tally`), and whether the judge is still reading
 * an approval's types; its body, its text, then each file it changes, whole (`judged`, `first` where it's a first
 * approval's), or a line saying why the host showed none; and what it offers.
 */
export function changed(item: Item, what: string, text: string, shown: Shown, first: boolean, offers: Offer[]): Answer {
    const files = shown.beyond.files.get(item.number);
    const counted = files !== undefined && "shown" in files ? tally(files.shown, first) : "";
    const typing = item.reason.reason === "approval" && item.reason.typing;
    const summary = [what, ...(counted === "" ? [] : [counted]), ...(typing ? ["reading types"] : [])];
    const refused: Line[] = files !== undefined && "refused" in files ? [{ block: "line", id: "refused", version: null, offers: [], spans: [{ text: `no files: ${files.refused}`, tone: "refused" }] }] : [];
    const blocks: Blocks = {
        summary: summary.map((each, at) => ({ text: at === 0 ? each : ` · ${each}`, tone: "plain" })),
        waiting: false,
        count: 0,
        offers,
        blocks: [
            { block: "markdown", id: "text", version: null, offers: [], text, tone: "plain" },
            ...(files !== undefined && "shown" in files ? files.shown.map((each) => judged(each, first)) : []),
            ...refused,
        ],
    };
    return { blocks };
}

/** Return what approving and declining an item offers, Space d and Space x, as the reply is sent, a comment on it implying approval where `commented`. */
export function answering(item: Item, commented: boolean): Offer[] {
    const answer = (approved: boolean): Offer => ({
        action: "inbox-answer-approval",
        argument: { number: item.number, approved },
        verb: approved ? "done" : "decline",
        chord: null,
        runs: "send",
        commented: approved && commented,
        says: approved ? "approve" : "decline",
    });
    return [answer(true), answer(false)];
}

/** A held change: what it holds, a landing or a change, its text and summary, its files; approving or declining it, a comment on it approving it with the comment. */
export const HELD: View<OfItem> = {
    module: "judge",
    view: "held",
    answer: ({ number }, shown) => {
        const item = shown.items.get(number);
        if (item?.reason.reason !== "held") {
            return null;
        }
        const reason = item.reason;
        return changed(item, reason.landing == null ? "held change" : "holds a landing", `${reason.text}\n${reason.summary}`, shown, false, answering(item, true));
    },
};

/** A write that landed flagged: its text and summary, and its files; answered in "since you approved", not here. */
export const FLAGGED: View<OfItem> = {
    module: "judge",
    view: "flagged",
    answer: ({ number }, shown) => {
        const item = shown.items.get(number);
        if (item?.reason.reason !== "flagged") {
            return null;
        }
        return changed(item, "landed, flagged", `${item.reason.text}\n${item.reason.summary}`, shown, false, []);
    },
};

/**
 * Say a "since you approved" drawer's summary line: on which branch, how many files changed since the operator last saw
 * them are to review, how many have flagged writes waiting on them, which the branch's landing waits on, how many are
 * tests or data files, folded whole and left out of what's to review (`foldedOf`), and how many stand as they saw them,
 * reviewed: the agent's flags in one line, as the inbox lists them.
 */
export function sinceSummary(shown: Since | null): string {
    if (shown === null) {
        return "since you approved · not read yet";
    }
    const { parts } = sinceCounts(shown);
    const branch = shown.branch == null ? "" : ` on ${shown.branch}`;
    return `since you approved${branch} · ${parts.length === 0 ? "nothing" : parts.join(" · ")}`;
}

/** What a "since you approved" drawer counts, each in a few words, how many files it has to review, and whether any waits on the operator. */
function sinceCounts(shown: Since): { parts: string[]; open: number; waiting: boolean } {
    const files = shown.files ?? [];
    const changedFiles = files.flatMap((each) => (each.file == null ? [] : [each.file]));
    const folded = new Map<Folded, number>();
    for (const each of changedFiles) {
        const why = foldedOf(each, false);
        if (why !== null) {
            folded.set(why, (folded.get(why) ?? 0) + 1);
        }
    }
    const open = changedFiles.length - [...folded.values()].reduce((sum, each) => sum + each, 0);
    // Reviewed, settled: those standing as the operator saw them with no flagged write waiting, which fold at the end.
    const kept = files.filter((each) => each.file == null && (each.flags ?? []).length === 0).length;
    const flagged = files.filter((each) => (each.flags ?? []).length > 0).length;
    const said = [
        ...(open === 0 ? [] : [`${open} to review`]),
        ...(flagged === 0 ? [] : [`${flagged} flagged`]),
        ...[...folded].map(([why, count]) => `${count} ${count === 1 ? FOLDED[why].one : FOLDED[why].many}`),
        ...(kept === 0 ? [] : [`${kept} reviewed`]),
    ];
    return { parts: said, open, waiting: open > 0 || flagged > 0 };
}

/** Return what marking `files` of the agent `conversation` names reviewed at the versions shown offers, Space d on a file or on the drawer, as the reply is sent. */
function reviewing(conversation: components["schemas"]["Conversation"], files: SinceFile[], says: string): Offer {
    return {
        action: "policy-review-since",
        argument: { conversation, files: files.map((each) => ({ path: each.path, version: each.version ?? null })) },
        verb: "done",
        chord: null,
        runs: "send",
        commented: true,
        says,
    };
}

/**
 * "Since you approved", the agent's drawer: its summary line (`sinceSummary`), bold where it has files to review or
 * flagged writes, the files to review counted for the overview; in the files' order, each changed since the operator
 * saw it, whole, a new module's bodies folded to show its design, each offering to be marked reviewed; each standing as
 * they saw it with flagged writes still waiting on it, a line of its own in its place; then those settled, folded
 * under one line saying how many, out of the way of what's left. None where its branch changed nothing, or isn't read.
 */
export const SINCE: View<OfAgent> = {
    module: "judge",
    view: "since",
    answer: (of, shown, repository) => {
        const conversation = conversationOf(repository, of);
        const since = shown.drawers.get(whose(conversation))?.since ?? null;
        const files = since?.files ?? [];
        if (since === null || files.length === 0) {
            return null;
        }
        const { parts, open, waiting } = sinceCounts(since);
        // The drawer's line leaves out the branch its summary names: the banner over it says where the agent works.
        const label = ["since you approved", ...(parts.length === 0 ? ["nothing"] : parts)].join(" · ");
        const each = new Map<string, SinceFile>();
        // A file standing as the operator last saw it offers marking it reviewed only while flagged writes wait on it,
        // which marking it approves: one settled is reviewed already.
        const line = (file: SinceFile): Line => {
            const id = `reviewed ${file.path}`;
            each.set(id, file);
            const offers = (file.flags ?? []).length > 0 ? [reviewing(conversation, [file], "mark it reviewed")] : [];
            return { block: "line", id, version: file.version ?? null, offers, spans: [{ text: reviewedLine(file), tone: "reviewed" }] };
        };
        const left = files.flatMap((file): Blocks["blocks"] => {
            if (file.file == null) {
                return (file.flags ?? []).length > 0 ? [line(file)] : [];
            }
            const diff = judged(file.file, false, file.file.before == null, file.version ?? null);
            const offered: Diff = withOffers(diff, [reviewing(conversation, [file], "mark it reviewed")]);
            each.set(offered.id, file);
            return [offered];
        });
        const settled = files.filter((file) => file.file == null && (file.flags ?? []).length === 0);
        const done: Blocks["blocks"] =
            settled.length === 0
                ? []
                : [
                      {
                          block: "fold",
                          id: "reviewed",
                          version: null,
                          offers: [],
                          kind: "lines",
                          summary: [{ text: `${settled.length} reviewed`, tone: "summary" }],
                          open: false,
                          barred: false,
                          content: settled.map(line),
                      },
                  ];
        // On the drawer as a whole, every file to review or with flagged writes waiting, those settled left out.
        const reviewable = files.filter((file) => file.file != null || (file.flags ?? []).length > 0);
        return {
            blocks: {
                summary: [{ text: label, tone: "plain" }],
                waiting,
                count: open,
                offers: reviewable.length === 0 ? [] : [reviewing(conversation, reviewable, "mark every file reviewed")],
                blocks: [...left, ...done],
            },
            files: each,
            since,
        };
    },
};

/** Each file's `Diff` with its offers, made once for each list offered, so the file's layout is kept with it. */
const offered = new WeakMap<Diff, Map<string, Diff>>();

/** Return `diff` offering `offers`, made once and kept. */
function withOffers(diff: Diff, offers: Offer[]): Diff {
    const kept = offered.get(diff) ?? new Map<string, Diff>();
    const key = JSON.stringify(offers);
    const found = kept.get(key);
    if (found !== undefined) {
        return found;
    }
    const made = { ...diff, offers };
    offered.set(diff, kept.set(key, made));
    return made;
}

/** The judge's part of an agent's banner: `holding` where the operator holds each of the agent's flagged writes, and holding or letting them land again, Space h, as the reply is sent. */
export const BANNER: View<OfAgent> = {
    module: "judge",
    view: "banner",
    answer: (of, shown, repository) => {
        const running = shown.running.get(whose(conversationOf(repository, of)));
        if (running === undefined) {
            return null;
        }
        const hold: Offer = {
            action: "set-holding",
            argument: { launch: running.launch, session: of.session, agent: of.agent ?? null, on: !running.holding },
            verb: "hold",
            chord: null,
            runs: "send",
            commented: false,
            says: running.holding ? "let their flagged writes land" : "hold their flagged writes",
        };
        return { blocks: { summary: running.holding ? [{ text: "holding", tone: "plain" }] : [], waiting: false, count: 0, offers: [hold], blocks: [] } };
    },
};
