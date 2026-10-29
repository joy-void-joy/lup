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
import { filesOf, heldSaid, isHeld, placeSaid, reviewedLine } from "../since";
import { conversationOf, whose, type Answer, type Blocks, type Fold, type Line, type OfAgent, type Offer, type PlacedFile, type Shown, type Span, type View } from "../views";

type Item = components["schemas"]["Item"];
type Reading = components["schemas"]["Reading"];
type Asked = components["schemas"]["Asked"];
type ApiChanged = components["schemas"]["ApiChanged"];
type Since = components["schemas"]["Since"];
type SinceFile = components["schemas"]["SinceFile"];
type SincePlace = components["schemas"]["SincePlace"];
type Conversation = components["schemas"]["Conversation"];
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
            case "role":
                return { said: "by its role's level", one: "by its role's level", many: "by their role's level" };
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
 * Say a "since you approved" drawer's summary line: on which branch, where it reads one, how many files a landing
 * waits on, how many changed since the operator last saw them are to review, how many have flagged writes waiting on
 * them, which their branch's landing waits on, how many are tests or data files, folded whole and left out of what's
 * to review (`foldedOf`), and how many stand as they saw them, reviewed: the agent's flags in one line, as the inbox
 * lists them.
 */
export function sinceSummary(shown: Since | null): string {
    if (shown === null) {
        return "since you approved · not read yet";
    }
    const { parts } = counts(filesOf(shown));
    const branches = (shown.places ?? []).flatMap((each) => (each.branch == null ? [] : [each.branch]));
    const branch = branches.length === 0 ? "" : ` on ${branches.join(", ")}`;
    return `since you approved${branch} · ${parts.length === 0 ? "nothing" : parts.join(" · ")}`;
}

/**
 * What files of a "since you approved" drawer count, each in a few words: how many a landing waits on, held at landing;
 * how many to review; how many with flagged writes waiting on them; the tests and data files; and how many of them all
 * are settled, reviewed, the drawer's progress (`3 of 7 reviewed`). With how many wait on the operator, those held and
 * those to review, and whether any does.
 */
function counts(files: readonly SinceFile[]): { parts: string[]; open: number; waiting: boolean } {
    const held = files.filter(isHeld).length;
    const changedFiles = files.filter((each) => each.file != null && !isHeld(each));
    // Each automatic file, folded whole and never counted as to review, said as its role's (`2 tests`), else `automatic`.
    const folded = new Map<string, { reason: Reason; count: number }>();
    for (const each of changedFiles) {
        const why = automaticOf(each);
        if (why !== null) {
            folded.set(why.one, { reason: why, count: (folded.get(why.one)?.count ?? 0) + 1 });
        }
    }
    const open = changedFiles.length - [...folded.values()].reduce((sum, each) => sum + each.count, 0);
    // Reviewed, settled: those standing as the operator saw them with no flagged write waiting, which fold at the end.
    const kept = files.filter((each) => each.file == null && (each.flags ?? []).length === 0 && each.held == null).length;
    const flagged = files.filter((each) => (each.flags ?? []).length > 0 && !isHeld(each)).length;
    const said = [
        ...(held === 0 ? [] : [`${held} held at landing`]),
        ...(open === 0 ? [] : [`${open} to review`]),
        ...(flagged === 0 ? [] : [`${flagged} flagged`]),
        ...[...folded.values()].map(({ reason, count }) => `${count} ${count === 1 ? reason.one : reason.many}`),
        ...(files.length === 0 ? [] : [`${kept} of ${files.length} reviewed`]),
    ];
    return { parts: said, open: open + held, waiting: open > 0 || flagged > 0 || held > 0 };
}

/** What `automatic` says of a file folded whole for its role's level, beside a test's or a data file's own words. */
const AUTOMATIC: Reason = { said: "automatic", one: "automatic", many: "automatic" };

/**
 * Return why a file of "since you approved" folds whole, asking nothing, never counted as to review, where it does: its
 * role's level `automatic`, said as a test or a data file (`FOLDED`) where it's one, else `automatic`; by its role alone,
 * a test's or a data file's, where no level was read; none where it's to review.
 */
function automaticOf(file: SinceFile): Reason | null {
    if (file.file == null) {
        return null;
    }
    const role = file.role ?? file.file.reading?.role ?? null;
    const named = role === "test" || role === "data" ? FOLDED[role] : AUTOMATIC;
    if (file.level != null) {
        return file.level === "automatic" ? named : null;
    }
    const why = foldedOf(file.file, false);
    return why === null ? null : FOLDED[why];
}

/** What the drawer calls each role's group, in the order it lays them out: production code its source. */
const ROLES: readonly { role: string; called: string }[] = [
    { role: "production", called: "source" },
    { role: "test", called: "tests" },
    { role: "docs", called: "docs" },
    { role: "data", called: "data" },
    { role: "operator", called: "operator's documents" },
    { role: "protected", called: "protected" },
    { role: "excluded", called: "excluded" },
    { role: "scratch", called: "scratch" },
];

/** Return a file's role, as the host read it, else as the judge's reading of it says; production where neither says. */
function roleOf(file: SinceFile): string {
    return file.role ?? file.file?.reading?.role ?? "production";
}

/**
 * Say what one role's group of a place holds, after its name: how many files are held at landing, to review, flagged,
 * automatic, and reviewed (`source · 3 to review`, `tests · 5 automatic`).
 */
function grouped(called: string, files: readonly SinceFile[]): string {
    const held = files.filter(isHeld).length;
    const automatic = files.filter((each) => !isHeld(each) && automaticOf(each) !== null).length;
    const open = files.filter((each) => each.file != null && !isHeld(each) && automaticOf(each) === null).length;
    const flagged = files.filter((each) => (each.flags ?? []).length > 0 && !isHeld(each)).length;
    const kept = files.filter((each) => each.file == null && (each.flags ?? []).length === 0 && each.held == null).length;
    const parts = [
        ...(held === 0 ? [] : [`${held} held at landing`]),
        ...(open === 0 ? [] : [`${open} to review`]),
        ...(flagged === 0 ? [] : [`${flagged} flagged`]),
        ...(automatic === 0 ? [] : [`${automatic} automatic`]),
        ...(kept === 0 ? [] : [`${kept} reviewed`]),
    ];
    return [called, ...parts].join(" · ");
}

/** Return what marking `files` of the place `place` of the agent `conversation` names reviewed at the versions shown offers, Space d on a file or on the drawer, as the reply is sent; a comment on one implying it where `commented`. */
function reviewing(conversation: Conversation, place: SincePlace, files: SinceFile[], says: string, commented: boolean = true): Offer {
    return {
        action: "policy-review-since",
        argument: {
            conversation,
            worktree: place.worktree ?? null,
            branch: place.branch ?? null,
            files: files.map((each) => ({ path: each.path, version: each.version ?? null })),
        },
        verb: "done",
        chord: null,
        runs: "send",
        commented,
        says,
    };
}

/**
 * Return what declining the landing of `files` of the place `place` offers, Space x on a file held at landing, as the
 * reply is sent: each marked reviewed at the version shown, its flags left waiting, and the landing told no, with the
 * operator's words on it; a comment on one implying it, as one on a hold at landing holds it back.
 */
function declining(conversation: Conversation, place: SincePlace, files: SinceFile[]): Offer {
    const offer = reviewing(conversation, place, files, "decline its landing");
    return { ...offer, argument: { ...offer.argument, decline: true }, verb: "decline" };
}

/** What a file held at landing offers: marking it reviewed, which lets it land, and declining its landing, a comment implying that; nothing once declined, the landing answering. */
function heldOffers(conversation: Conversation, place: SincePlace, file: SinceFile): Offer[] {
    if (file.held?.declined === true) {
        return [];
    }
    return [reviewing(conversation, place, [file], "mark it reviewed, letting it land", false), declining(conversation, place, [file])];
}

/** Return the words naming `place` in its blocks' ids: none for the drawer's first place, so its files keep the ids they had before it had others; its branch, else its worktree. */
function placeKey(place: SincePlace, first: boolean): string {
    if (first) {
        return "";
    }
    return ` on ${place.branch ?? place.worktree ?? "a detached HEAD"}`;
}

/**
 * Return the blocks of one place of a "since you approved" drawer, `first` where it's the drawer's first, each file it
 * shows put in `each` by its block's id: in the files' order, each changed since the operator saw it, whole, a new
 * module's bodies folded to show its design, each offering to be marked reviewed, one held at landing saying so in
 * its header and offering its landing declined too; each standing as they saw it with flagged writes still waiting on
 * it, or held at landing, a line of its own in its place; then those settled, folded under one line saying how many.
 */
function placed(conversation: Conversation, place: SincePlace, first: boolean, each: Map<string, PlacedFile>): Blocks["blocks"] {
    const files = place.files ?? [];
    const key = placeKey(place, first);
    // A file standing as the operator last saw it offers marking it reviewed only while flagged writes wait on it,
    // which marking it approves, or a landing waits on it: one settled is reviewed already.
    const line = (file: SinceFile): Line => {
        const id = `reviewed ${file.path}${key}`;
        each.set(id, { file, place, block: id });
        const offers =
            file.held != null
                ? heldOffers(conversation, place, file)
                : (file.flags ?? []).length > 0
                  ? [reviewing(conversation, place, [file], "mark it reviewed")]
                  : [];
        return { block: "line", id, version: file.version ?? null, offers, spans: [{ text: reviewedLine(file), tone: "reviewed" }] };
    };
    const shownOf = (file: SinceFile): Blocks["blocks"] => {
        if (file.file == null) {
            return (file.flags ?? []).length > 0 || file.held != null ? [line(file)] : [];
        }
        const diff = leveled(withKey(judged(file.file, false, file.file.before == null, file.version ?? null), key), file);
        const offers = file.held != null ? heldOffers(conversation, place, file) : [reviewing(conversation, place, [file], "mark it reviewed")];
        const offered: Diff = withOffers(file.held == null ? diff : heldDiff(diff, file), offers);
        each.set(offered.id, { file, place, block: offered.id });
        return [offered];
    };
    const settledOf = (list: readonly SinceFile[], id: string): Blocks["blocks"] => {
        const settled = list.filter((file) => file.file == null && (file.flags ?? []).length === 0 && file.held == null);
        return settled.length === 0
            ? []
            : [
                  {
                      block: "fold",
                      id,
                      version: null,
                      offers: [],
                      kind: "lines",
                      summary: [{ text: `${settled.length} reviewed`, tone: "summary" }],
                      open: false,
                      barred: false,
                      content: settled.map(line),
                  },
              ];
    };
    // Each role's files a group of its own where the place shows several roles, in the order `ROLES` lays them out.
    const roles = [...new Set(files.map(roleOf))];
    if (roles.length < 2) {
        return [...files.flatMap(shownOf), ...settledOf(files, `reviewed${key}`)];
    }
    const order = (role: string) => {
        const at = ROLES.findIndex((each) => each.role === role);
        return at < 0 ? ROLES.length : at;
    };
    return roles
        .sort((a, b) => order(a) - order(b))
        .map((role): Fold => {
            const mine = files.filter((file) => roleOf(file) === role);
            const called = ROLES.find((each) => each.role === role)?.called ?? role;
            // A group asking nothing, each file automatic or settled, starts folded.
            const quiet = mine.every((file) => !isHeld(file) && (file.flags ?? []).length === 0 && (file.file == null || automaticOf(file) !== null));
            const reviewable = mine.filter((file) => (file.file != null || (file.flags ?? []).length > 0) && file.held?.declined !== true);
            return {
                block: "fold",
                id: `role ${role}${key}`,
                version: null,
                // Space d on its line marks each of its files, each by its own offer; this says so.
                offers: reviewable.length === 0 ? [] : [reviewing(conversation, place, reviewable, "mark each of its files reviewed")],
                kind: "role",
                summary: [{ text: grouped(called, mine), tone: "summary" }],
                open: !quiet,
                barred: false,
                content: [...mine.flatMap(shownOf), ...settledOf(mine, `reviewed ${role}${key}`)],
            };
        });
}

/** Each file's `Diff` as its role's level shows it, made once for each level, so the file's layout is kept with it. */
const levelled = new WeakMap<Diff, Map<string, Diff>>();

/**
 * Return `diff` as its role's level shows it in "since you approved": folded whole, saying `automatic`, where the level
 * is `automatic`; where it's reviewed, flagged or held, not folded for its role alone, a test's or a data file's, but
 * as any file is, by what it asks (`automatic` where it asks nothing); itself where no level was read, or it's shown
 * so already.
 */
function leveled(diff: Diff, file: SinceFile): Diff {
    const level = file.level ?? null;
    if (level === null || file.file == null) {
        return diff;
    }
    const automatic = level === "automatic";
    const folded = foldedOf(file.file, false) !== null;
    if (automatic ? !(diff.open ?? true) : !folded) {
        return diff;
    }
    const kept = levelled.get(diff) ?? new Map<string, Diff>();
    const found = kept.get(level);
    if (found !== undefined) {
        return found;
    }
    const says = diff.says ?? [];
    const made: Diff = automatic
        ? { ...diff, open: false, automatic: true, says: ["automatic", ...says.filter((each) => each !== "automatic")] }
        : { ...diff, open: !(diff.automatic ?? false), says: diff.automatic === true ? ["automatic", ...says.filter((each) => each !== "automatic" && each !== FOLDED.test.said && each !== FOLDED.data.said)] : says.filter((each) => each !== FOLDED.test.said && each !== FOLDED.data.said) };
    levelled.set(diff, kept.set(level, made));
    return made;
}

/**
 * "Since you approved", the agent's drawer: its summary line (`sinceSummary`), bold where it has files to review,
 * flagged writes or files held at landing, the files held and to review counted for the overview; each place the
 * agent worked laid out (`placed`), alone as the drawer's own, or, where they worked in several, each a fold of the
 * judge's `branch` kind, open, its line saying which and what it counts. None where their branches changed nothing, or
 * aren't read yet; where the host refused to read them, its line says it's unavailable, and the line under it why.
 */
export const SINCE: View<OfAgent> = {
    module: "judge",
    view: "since",
    answer: (of, shown, repository) => {
        const conversation = conversationOf(repository, of);
        const drawers = shown.drawers.get(whose(conversation));
        const since = drawers?.since ?? null;
        const unread = drawers?.unread ?? null;
        if (since === null && unread !== null) {
            // What the host refused to read is said in the drawer's place, rather than leaving it out as if nothing changed.
            const why: Line = { block: "line", id: "unread", version: null, offers: [], spans: [{ text: unread, tone: "refused" }] };
            const summary = [{ text: "since you approved · unavailable", tone: "plain" }];
            return { blocks: { summary, waiting: false, count: 0, offers: [], blocks: [why] } };
        }
        const files = since === null ? [] : filesOf(since);
        if (since === null || files.length === 0) {
            return null;
        }
        const { parts, open, waiting } = counts(files);
        // The drawer's line leaves out the branch its summary names: the banner over it says where the agent works.
        const label = ["since you approved", ...(parts.length === 0 ? ["nothing"] : parts)].join(" · ");
        const each = new Map<string, PlacedFile>();
        const places = since.places ?? [];
        const showing = places.filter((place) => (place.files ?? []).length > 0);
        const [only] = showing;
        const blocks: Blocks["blocks"] =
            showing.length === 1 && only !== undefined && only === places[0]
                ? placed(conversation, only, true, each)
                : showing.map((place) => {
                      const first = place === places[0];
                      const said = counts(place.files ?? []).parts;
                      const reviewable = (place.files ?? []).filter((file) => (file.file != null || (file.flags ?? []).length > 0) && file.held?.declined !== true);
                      return {
                          block: "fold",
                          id: `place${placeKey(place, first)}`,
                          version: null,
                          offers: reviewable.length === 0 ? [] : [reviewing(conversation, place, reviewable, "mark each of its files reviewed")],
                          kind: "branch",
                          summary: [{ text: [placeSaid(place), ...(said.length === 0 ? ["nothing"] : said)].join(" · "), tone: "summary" }],
                          open: true,
                          barred: false,
                          content: placed(conversation, place, first, each),
                      };
                  });
        // On the drawer as a whole, every file to review, with flagged writes waiting or held at landing, of its first
        // place: those settled left out. Space d on its line reaches each file of every place, each offering it.
        const first = places[0];
        const reviewable = (first?.files ?? []).filter((file) => (file.file != null || (file.flags ?? []).length > 0) && file.held?.declined !== true);
        return {
            blocks: {
                summary: [{ text: label, tone: "plain" }],
                waiting,
                count: open,
                offers: first === undefined || reviewable.length === 0 ? [] : [reviewing(conversation, first, reviewable, "mark every file reviewed")],
                blocks,
            },
            files: each,
            since,
        };
    },
};

/** Each file's `Diff` with its id naming its place, made once for each, so the file's layout is kept with it. */
const keyed = new WeakMap<Diff, Map<string, Diff>>();

/** Return `diff` with its id naming its place, `key`, made once and kept; itself for the drawer's first place. */
function withKey(diff: Diff, key: string): Diff {
    if (key === "") {
        return diff;
    }
    const kept = keyed.get(diff) ?? new Map<string, Diff>();
    const found = kept.get(key);
    if (found !== undefined) {
        return found;
    }
    const made = { ...diff, id: `${diff.id}${key}` };
    keyed.set(diff, kept.set(key, made));
    return made;
}

/** Each held file's `Diff`, its header saying it's held at landing, open: made once for each landing. */
const holding = new WeakMap<Diff, Map<string, Diff>>();

/** Return `diff` as a file held at landing shows it: its header saying so first, open, made once and kept. */
function heldDiff(diff: Diff, file: SinceFile): Diff {
    const [said] = heldSaid(file);
    if (said === undefined) {
        return diff;
    }
    const kept = holding.get(diff) ?? new Map<string, Diff>();
    const found = kept.get(said);
    if (found !== undefined) {
        return found;
    }
    const made = { ...diff, says: [said, ...(diff.says ?? [])], open: true, automatic: false };
    holding.set(diff, kept.set(said, made));
    return made;
}

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

/**
 * The judge's part of an agent's banner: `holding` where the operator holds each of the agent's flagged writes, and
 * holding or letting them land again, Space h, as the reply is sent, for an agent running; how many files of their
 * drawer a landing waits on (`landing waits on 2 files`); and, for an agent landing, each landing of theirs waiting and
 * whose drawers hold its files (`landing `feat` on `dev` waits on 2 files in parser's drawer`), each writer's name a
 * span naming them, which `gd` goes to.
 */
export const BANNER: View<OfAgent> = {
    module: "judge",
    view: "banner",
    answer: (of, shown, repository) => {
        const conversation = conversationOf(repository, of);
        const key = whose(conversation);
        const running = shown.running.get(key);
        const since = shown.drawers.get(key)?.since ?? null;
        const held = since === null ? 0 : filesOf(since).filter(isHeld).length;
        const landing = shown.landings.filter((each) => whose(each.lander) === key);
        const parts: Span[][] = [
            ...(running?.holding === true ? [[{ text: "holding", tone: "plain" }]] : []),
            ...(held === 0 ? [] : [[{ text: `landing waits on ${held} file${held === 1 ? "" : "s"}`, tone: "strong" }]]),
            ...landing.map((wait) => landingSaid(wait, key, shown)),
        ];
        if (running === undefined && parts.length === 0) {
            return null;
        }
        const hold: Offer[] =
            running === undefined
                ? []
                : [
                      {
                          action: "set-holding",
                          argument: { launch: running.launch, session: of.session, agent: of.agent ?? null, on: !running.holding },
                          verb: "hold",
                          chord: null,
                          runs: "send",
                          commented: false,
                          says: running.holding ? "let their flagged writes land" : "hold their flagged writes",
                      },
                  ];
        const summary = parts.flatMap((each, at) => (at === 0 ? each : [{ text: " · ", tone: "plain" }, ...each]));
        return { blocks: { summary, waiting: held > 0, count: 0, offers: hold, blocks: [] } };
    },
};

/** Say a landing of the agent `lander`'s waiting, as their banner says it: what lands where, how many files it waits on still, and in whose drawers, each writer but the lander named by a span `gd` follows to their drawer. */
function landingSaid(wait: components["schemas"]["Wait"], lander: string, shown: Shown): Span[] {
    const left = (wait.files ?? []).filter((each) => each.declined == null);
    const writers = [...new Map(left.flatMap((each) => each.writers ?? []).map((each) => [whose(each), each])).values()];
    const others = writers.filter((each) => whose(each) !== lander);
    const named = wait.branches.map((each) => `\`${each}\``).join(", ");
    const onto = wait.onto.replace(/^refs\/heads\//, "");
    const head: Span = { text: `landing ${named} on \`${onto}\` waits on ${left.length} file${left.length === 1 ? "" : "s"}`, tone: "strong" };
    if (others.length === 0) {
        return [head];
    }
    const drawers = others.flatMap((each, at): Span[] => [
        ...(at === 0 ? [] : [{ text: ", ", tone: "plain" }]),
        { text: shown.called(each), tone: "strong", conversation: { runtime: each.runtime, session: each.session, agent: each.agent ?? null } },
    ]);
    return [head, { text: " in ", tone: "strong" }, ...drawers, { text: `'s drawer${others.length === 1 ? "" : "s"}`, tone: "strong" }];
}
