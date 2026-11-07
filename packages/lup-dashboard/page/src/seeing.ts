// What's new stops being new once it's been seen (`docs/dashboard.md`, *Review marks*), and stays where it is. The page
// says only what's been on screen: which things are read so, and how far each moves a mark, are the host's, a view's (`Sights`), a thread's what it
// says is new (`ThreadRead.new`) and a group's its review mark, and the mark stays the host's, which only goes forward, so
// two pages and a phone can't take back what another moved it past. What's here is the eye: for how long each thing has
// been in view, while the operator was there to see it, and which marks that lets move. Pure, with the time given, so a
// test moves its own clock; `useSeeing.ts` gives it the view.
import { CORE_MODULE, findNode, type Moved } from "./grammar";
import { fresh, type Conversation, type Draft, type Laid, type Placed, type Seeing, type ThreadRead } from "./review";
import { blockId, instanceOf, type Instance, type Remote } from "./views";

/** How long a thing has to be in view at least. */
export const DWELL = 2000;
/** How long each of its lines asks for, where that's longer: a long thing takes longer to read. */
export const PER_LINE = 150;
/** How long its first line and its last each have to be in view: going through a thing longer than the screen, it's reached both ends, and neither was passed by in a moment. */
export const EDGE = 1000;
/** How long after they last touched the page they're taken to be there: what comes while they're away stays new. */
export const AWAY = 60_000;
/** How often the time in view is added up. */
export const TICK = 500;
/** The longest one tick counts: a page asleep for an hour saw nothing of it. */
export const MOST_TICK = 1000;
/** How often the marks that may move are told the host at most, each move answered by a layout of what read it. */
export const EVERY = 3000;

/** What moving a mark is given: `Moved`, how far as its view says, only forward, by being seen. */
export type Moving = Moved & { through?: string | null; forward: true; seen: true };

/** One thing read by being on screen, as it's laid out. */
export interface Sighted {
    /** What names it across layouts. */
    id: string;
    /** What names the mark it moves, once all before it are seen. */
    mark: string;
    /** How that mark moves once it's read. */
    moves: Moving;
    from: number;
    to: number;
    lines: number;
    /** Whether it's not one thing but stands for what a fold holds: closed, the mark stops there, since what's new in it wasn't seen; open, what it holds is here itself. */
    standing: boolean;
    /** Whether the mark can't pass it yet: laid out nowhere, or holding what the operator wrote, which keeps it where they're writing. */
    held: boolean;
    /** Whether it asks the operator something: it waits on them wherever the mark is, so it never holds the mark back from what comes after it, which only takes off its word that it's new. */
    asks?: boolean;
}

/** What's in view as a thing's edges are asked about, in the layout's places. */
export interface Viewing {
    from: number;
    to: number;
    /** Where the closed fold hiding `at` starts, the end of its summary line; none where `at` isn't hidden. */
    closedAt: (at: number) => number | null;
}

/** How much of a thing has been in view, and how long. */
interface Dwelt {
    total: number;
    first: number;
    last: number;
}

/** Return how many lines of `text` the span from `from` to `to` is. */
function linesIn(text: string, from: number, to: number): number {
    let count = 1;
    for (let at = text.indexOf("\n", from); at >= 0 && at < to; at = text.indexOf("\n", at + 1)) {
        count += 1;
    }
    return count;
}

/** Return where `of` is: its first position and last, with what's shown of it on screen right now in `view`; none where a closed fold hides it. */
export function shownOf(of: { from: number; to: number }, view: Viewing): { first: boolean; last: boolean; any: boolean } | null {
    if (view.closedAt(of.from) !== null) {
        return null;
    }
    const end = view.closedAt(of.to) ?? of.to;
    const within = (at: number) => at >= view.from && at <= view.to;
    return { first: within(of.from), last: within(end), any: of.from <= view.to && end >= view.from };
}

/** Return how long a thing of `lines` has to be in view to be seen. */
export function dwellFor(lines: number): number {
    return Math.max(DWELL, lines * PER_LINE);
}

/** How long each thing has been in view while the operator was there, and which marks that moves. */
export class Dwelling {
    private readonly dwelt = new Map<string, Dwelt>();
    private readonly told = new Set<string>();
    private at: number | null = null;

    /** Add up the time to `now`, what's in `view` of `sights`, in the order they're laid out, gaining it where `there` says the operator was there to see it. */
    advance(now: number, sights: readonly Sighted[], view: Viewing | null, there: boolean): void {
        const since = this.at === null ? 0 : Math.min(now - this.at, MOST_TICK);
        this.at = now;
        if (!there || view === null || since <= 0) {
            return;
        }
        for (const each of sights) {
            if (each.from > view.to) {
                break;
            }
            const shown = shownOf(each, view);
            if (shown === null || !shown.any || each.standing) {
                continue;
            }
            const was = this.dwelt.get(each.id) ?? { total: 0, first: 0, last: 0 };
            this.dwelt.set(each.id, {
                total: was.total + since,
                first: was.first + (shown.first ? since : 0),
                last: was.last + (shown.last ? since : 0),
            });
        }
    }

    /** Say whether `sight` has been on screen long enough to be seen. */
    seen(sight: Sighted): boolean {
        const dwelt = this.dwelt.get(sight.id);
        return dwelt !== undefined && dwelt.total >= dwellFor(sight.lines) && dwelt.first >= EDGE && dwelt.last >= EDGE;
    }

    /**
     * Return each mark that may move, as far as the first of its `sights` not yet seen, or held, and not past one still in
     * `view` unless `leaving`, as the tab goes: so nothing folds while they're reading it. A mark is
     * one position, so what's seen past what wasn't waits for it. Each is said once: `failed` says it again.
     */
    due(sights: readonly Sighted[], view: Viewing | null, leaving: boolean): Due[] {
        const marks = new Map<string, Sighted[]>();
        for (const each of sights) {
            const kept = marks.get(each.mark);
            if (kept === undefined) {
                marks.set(each.mark, [each]);
            } else {
                kept.push(each);
            }
        }
        const found: Due[] = [];
        for (const [, ordered] of marks) {
            const passed: Sighted[] = [];
            for (const each of ordered) {
                if (each.standing) {
                    if (each.held || view === null || view.closedAt(each.from) !== null) {
                        break;
                    }
                    continue;
                }
                const onScreen = !leaving && view !== null && shownOf(each, view)?.any === true;
                if (each.held || !this.seen(each) || onScreen) {
                    if (each.asks ?? false) {
                        continue;
                    }
                    break;
                }
                passed.push(each);
            }
            const untold = passed.filter((each) => !this.told.has(each.id));
            const last = untold.at(-1);
            if (last !== undefined) {
                found.push({ ids: untold.map((each) => each.id), moves: last.moves });
            }
        }
        for (const each of found) {
            each.ids.forEach((id) => this.told.add(id));
        }
        return found;
    }

    /** Say `due` wasn't kept: it's due again. */
    failed(due: Due): void {
        due.ids.forEach((id) => this.told.delete(id));
    }

    /** Forget what's no longer among `sights`, read since, so what's kept stays small. */
    settled(sights: readonly Sighted[]): void {
        const known = new Set(sights.map((each) => each.id));
        for (const id of this.dwelt.keys()) {
            if (!known.has(id)) {
                this.dwelt.delete(id);
            }
        }
        for (const id of this.told) {
            if (!known.has(id)) {
                this.told.delete(id);
            }
        }
    }
}

/** A mark that may move, and how. */
export interface Due {
    ids: string[];
    moves: Moving;
}

/** Return what names a mark among the others: its repository, its module and what it's on. */
function markId(moves: { repository: string; module: string; key: Record<string, unknown> }): string {
    return JSON.stringify([moves.repository, moves.module, moves.key]);
}

/** Return `conversation`'s group's mark moved as far as item `number`. */
function groupMoves(conversation: Conversation, number: number): Moving {
    return {
        repository: conversation.repository,
        module: CORE_MODULE,
        key: { runtime: conversation.runtime, session: conversation.session, agent: conversation.agent ?? null },
        up_to: String(number),
        forward: true,
        seen: true,
    };
}

/** Nowhere: where something laid out nowhere goes among what's laid out, so it holds back only what comes after it. */
const NOWHERE = Number.MAX_SAFE_INTEGER;

/**
 * Return each thing `laidOut` lays out read by being on screen, in the order it's laid out: what each drawer's view says;
 * each item new to the operator, by the mark of what it's in, a thread's where the review reads threads (`threads`) and
 * else its agent's group's. What holds what they wrote holds its mark back, a fold never closing over their words.
 */
export function sightsOf(laidOut: Laid, seeing: Seeing, draft: Draft, remote: Remote, threads: readonly ThreadRead[] | null): Sighted[] {
    const written = new Set((draft.comments ?? []).filter((each) => each.text.trim() !== "").map((each) => each.item));
    const remarked = new Set((draft.remarks ?? []).filter((each) => each.text.trim() !== "").map((each) => each.quote.block ?? ""));
    const holdsRemark = (part: Placed): boolean => remarked.has(part.id) || part.children.some(holdsRemark);
    const marked = new Set([...(draft.done ?? []), ...(draft.declined ?? []), ...(draft.parked ?? [])]);
    const regions = new Map(laidOut.regions.map((each) => [each.item.number, each]));

    /** Each part of `parts`, those within among them, by its id. */
    const walked = (parts: readonly Placed[], into: Map<string, Placed>): Map<string, Placed> => {
        for (const each of parts) {
            into.set(each.id, each);
            walked(each.children, into);
        }
        return into;
    };

    const ofDrawers = laidOut.drawers.flatMap((drawer) => {
        const asked = drawer.view.answer?.blocks.sights ?? null;
        const opened = [...drawer.loads.values()].flatMap((each: Instance) => remote.get(instanceOf(each.repository, each.module, each.view, each.argument))?.sights ?? []);
        const all = [...(asked === null ? [] : [asked]), ...opened];
        if (all.length === 0) {
            return [];
        }
        const placed = walked(findNode(laidOut.nodes, drawer.view.id)?.children ?? [], new Map());
        return all.flatMap((sights) =>
            (sights.sights ?? []).map((sight) => {
                const id = blockId(drawer.view.id, sight.block);
                const node = placed.get(id);
                const argument = sights.offer.argument as unknown as Moved;
                const moves: Moving = { repository: argument.repository, module: argument.module, key: argument.key, up_to: sight.up_to, through: sight.through ?? null, forward: true, seen: true };
                const standing = sight.folded ?? false;
                // What a fold holds starts after its summary line; read as it opens, it isn't here until the host has answered.
                const from = node === undefined ? NOWHERE : standing ? Math.min(node.header.to + 1, node.to) : node.from;
                const unread = standing && drawer.folds.some((each) => each.name === sight.block && (each.unread ?? false));
                return {
                    id,
                    mark: markId(moves),
                    moves,
                    from,
                    to: node?.to ?? NOWHERE,
                    lines: node === undefined ? 1 : linesIn(laidOut.text, node.from, node.to),
                    standing,
                    held: node === undefined || unread || holdsRemark(node),
                } satisfies Sighted;
            }),
        );
    });

    /** Return item `number` as a thing read by being on screen, what's under its header, moving `moves` once it's passed; none where the draft has marked it, which says what becomes of it. */
    const ofItem = (number: number, moves: Moving): Sighted[] => {
        if (marked.has(number)) {
            return [];
        }
        const region = regions.get(number);
        if (region === undefined) {
            return [{ id: `item ${number}`, mark: markId(moves), moves, from: NOWHERE, to: NOWHERE, lines: 1, standing: false, held: true }];
        }
        const from = Math.min(region.header.to + 1, region.end);
        return [
            {
                id: `item ${number}`,
                mark: markId(moves),
                moves,
                from,
                to: region.end,
                lines: linesIn(laidOut.text, from, region.end),
                standing: false,
                held: written.has(number),
                asks: region.item.asks,
            },
        ];
    };

    const ofThreads = (threads ?? []).flatMap((read) => {
        const asked = (read.asks ?? []).map((each) => each.node).filter((each) => regions.has(each));
        const numbers = [...new Set([...(read.new ?? []), ...asked])].toSorted((a, b) => a - b);
        return numbers.flatMap((number) =>
            ofItem(number, { repository: read.thread.repository, module: CORE_MODULE, key: { node: read.thread.number }, up_to: String(number), forward: true, seen: true }),
        );
    });
    const ofAgents =
        threads !== null
            ? []
            : laidOut.regions.flatMap((region) => {
                  const sender = region.item.sender;
                  return sender.party === "conversation" && fresh(region.item, seeing) ? ofItem(region.item.number, groupMoves(sender, region.item.number)) : [];
              });

    return [...ofDrawers, ...ofThreads, ...ofAgents].toSorted((a, b) => a.from - b.from);
}
