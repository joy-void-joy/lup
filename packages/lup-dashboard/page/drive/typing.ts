// Typing into a comment, the measure every session working on the review's speed takes: key to frame, and keys lost.
//
//     node packages/lup-dashboard/page/drive/typing.ts --approval-lines 30000 --slower 4
//
// starts the demo at that size, types into a comment in the room's headless Chromium, and says how long the keys took
// to reach the screen and how many were lost. `--help` says each option.
import { parseArgs } from "node:util";

import type { components } from "../src/generated/api.ts";
import { open, type Dashboard } from "./dashboard.ts";
import { demo } from "./demo.ts";
import { percentiles, timed, type Timed } from "./timing.ts";

/** Where a comment is typed, and what, how fast. */
export interface TypingOptions {
    /** The text whose line, and the one after it, the comment goes under: an item's header, its text the next line. */
    at?: string;
    /** What's typed, a key a character, each on a US keyboard. */
    text?: string;
    /** Milliseconds between keys. */
    gap?: number;
}

/** What typing a comment did. */
export interface Typing {
    /** What was typed. */
    text: string;
    /** What the comment held once typing was done. */
    landed: string;
    /** How many keys typed the comment doesn't hold. */
    lost: number;
    /** Whether the host's draft holds the comment as it landed; null where the page has no draft to ask for. */
    kept: boolean | null;
    timed: Timed;
}

/** An item of the demo's, a note of how the work felt, whose text is a line. */
export const DEMO_ITEM = "── @58 how it felt";

/** What's typed unless said: 30 keys, letters and spaces, as #341's measures typed. */
export const PANGRAM = "the quick brown fox jumps over";

/**
 * Type `options.text` into a comment under the line after `options.at`, `options.gap` milliseconds apart, through the
 * DevTools protocol, never waiting on the page, and return how long each key took to reach the screen, what landed, and
 * whether the host kept it; then take the comment back with `u`, leaving the review as it was.
 */
export async function typing(dashboard: Dashboard, options: TypingOptions = {}): Promise<Typing> {
    const text = options.text ?? PANGRAM;
    const review = await dashboard.review();
    await review.goTo(options.at ?? DEMO_ITEM);
    await dashboard.page.keyboard.press("j");
    await review.comment();
    const before = await review.line();
    const keys = await timed(dashboard.page, () => dashboard.keys.type(text, options.gap ?? 120));
    await dashboard.page.keyboard.press("Escape");
    await review.inMode("normal");
    const after = await review.line();
    const landed = after.startsWith(before) ? after.slice(before.length) : after;
    const kept = await keptOnHost(dashboard, landed);
    // Taken back once the review holds what landed once fewer: it may hold it elsewhere too.
    const held = landed === "" ? 0 : await review.evaluate((view, landed) => view.state.doc.toString().split(landed).length - 1, landed);
    await dashboard.page.keyboard.press("u");
    if (landed !== "") {
        await review.until("took the comment back", (view, [landed, held]) => view.state.doc.toString().split(landed).length - 1 < held, [landed, held] as const);
    }
    return { text, landed, lost: text.length - common(text, landed), kept, timed: keys };
}

/**
 * Return whether the host's draft holds `landed` as a comment, a message or a remark, once it does, or once it's said
 * the draft without it for five seconds: the page keeps the draft on the host a moment after it last changed, not as
 * each key is typed. Null where the dashboard has no draft to ask for.
 */
async function keptOnHost(dashboard: Dashboard, landed: string): Promise<boolean | null> {
    const asked = async (): Promise<boolean | null> =>
        dashboard.page.evaluate(async (landed) => {
            const response = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: "inbox-draft" }) });
            if (!response.ok) {
                return null;
            }
            const answer = (await response.json()) as { kind: string };
            if (answer.kind !== "inbox-drafted") {
                return null;
            }
            const { draft } = answer as components["schemas"]["Drafted"];
            return [...draft.comments, ...draft.letters, ...draft.remarks].some((each) => each.text === landed);
        }, landed);
    const since = Date.now();
    let kept = await asked();
    while (kept === false && Date.now() - since < 5000) {
        await dashboard.page.waitForTimeout(200);
        kept = await asked();
    }
    return kept;
}

/** How many characters of `typed` `landed` holds in order: their longest common subsequence's length. */
export function common(typed: string, landed: string): number {
    let above = new Array<number>(landed.length + 1).fill(0);
    for (const character of typed) {
        const row = [0];
        for (const [index, other] of [...landed].entries()) {
            row.push(character === other ? (above[index] ?? 0) + 1 : Math.max(above[index + 1] ?? 0, row[index] ?? 0));
        }
        above = row;
    }
    return above.at(-1) ?? 0;
}

/** The command: options parsed, the demo started where no `--url` is given, each round typed and said. */
async function main(): Promise<void> {
    const { values } = parseArgs({
        options: {
            url: { type: "string" },
            size: { type: "string" },
            "approval-lines": { type: "string" },
            hooks: { type: "string" },
            at: { type: "string", default: DEMO_ITEM },
            keys: { type: "string", default: String(PANGRAM.length) },
            gap: { type: "string", default: "120" },
            slower: { type: "string", default: "1" },
            rounds: { type: "string", default: "1" },
            help: { type: "boolean", default: false },
        },
    });
    if (values.help) {
        console.log(HELP);
        return;
    }
    const number = (name: string, given: string | undefined): number | undefined => {
        if (given === undefined) {
            return undefined;
        }
        const read = Number(given);
        if (!Number.isFinite(read) || read < 0) {
            throw new Error(`--${name} is a number, not ${given}`);
        }
        return read;
    };
    const count = number("keys", values.keys) ?? PANGRAM.length;
    const gap = number("gap", values.gap) ?? 120;
    const slower = number("slower", values.slower) ?? 1;
    const rounds = number("rounds", values.rounds) ?? 1;
    const text = PANGRAM.repeat(Math.ceil(count / PANGRAM.length) + 1).slice(0, count);
    const size = number("size", values.size);
    const approvalLines = number("approval-lines", values["approval-lines"]);
    const hooks = number("hooks", values.hooks);
    await using served =
        values.url === undefined
            ? await demo({ ...(size === undefined ? {} : { size }), ...(approvalLines === undefined ? {} : { approvalLines }), ...(hooks === undefined ? {} : { hooks }) })
            : null;
    await using dashboard = await open(served?.url ?? values.url ?? "");
    const review = await dashboard.review();
    await review.holds(values.at);
    await review.settled();
    const sized = await review.evaluate((view) => ({ lines: view.state.doc.lines, characters: view.state.doc.length }));
    await dashboard.slow(slower);
    console.log(
        `${count} keys ${gap} ms apart into a comment under ${JSON.stringify(values.at)}, ${slower === 1 ? "the CPU at its own speed" : `the CPU ${slower}x slower`}; ` +
            `the review ${sized.lines.toLocaleString("en")} lines, ${sized.characters.toLocaleString("en")} characters`,
    );
    const every: number[] = [];
    let lost = 0;
    for (let round = 1; round <= rounds; round += 1) {
        const typed = await typing(dashboard, { at: values.at, text, gap });
        const times = typed.timed.keys.flatMap((each) => (each.toFrame === null ? [] : [each.toFrame]));
        every.push(...times);
        lost += typed.lost;
        const kept = typed.kept === null ? "no draft to ask the host for" : typed.kept ? "the host kept it" : "the host's draft doesn't hold it";
        console.log(`round ${round}: key to frame ${said(times)}; ${text.length - typed.lost} of ${text.length} keys landed, ${typed.timed.seen} seen; ${kept}`);
    }
    if (rounds > 1) {
        console.log(`every round: key to frame ${said(every)}; ${lost} of ${rounds * text.length} keys lost`);
    }
}

/** Say `times`' percentiles, in milliseconds. */
function said(times: number[]): string {
    const read = percentiles(times);
    return read === null ? "never drawn" : `median ${read.median.toFixed(0)} ms, p90 ${read.p90.toFixed(0)} ms, most ${read.most.toFixed(0)} ms`;
}

const HELP = `node packages/lup-dashboard/page/drive/typing.ts [options]

Type into a comment in the review, in the room's headless Chromium, through the DevTools protocol, never waiting on the
page, and say how long each key took to reach the screen, from sent to the end of the frame drawing it, and how many
keys were lost. The demo is started on a free port, at the size given, unless --url names a dashboard already served.

  --size N             the demo's flagged writes of a busy day beside its own items; 0 for its own alone
  --approval-lines N   lines of the approval's change; 30000 is the operator's size on 2026-10-29
  --hooks N            stand-in hook calls a minute, each answering every watch again
  --url URL            a dashboard already served, its token in the fragment, rather than the demo
  --at TEXT            the line the comment goes under the next line of (default: ${JSON.stringify(DEMO_ITEM)})
  --keys N             how many keys to type (default: ${PANGRAM.length})
  --gap MS             milliseconds between keys (default: 120)
  --slower RATE        Chromium's CPU slowed RATE times (default: 1)
  --rounds N           how many comments to type, each taken back after (default: 1)`;

if (import.meta.main) {
    await main();
}
