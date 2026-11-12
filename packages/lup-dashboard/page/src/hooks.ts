// React's side of the API: a request watched for as long as a component shows it.
import { useEffect, useMemo, useRef, useState } from "react";

import { watch, type Asked, type Connection, type Replied, type ReplyOf } from "./api";
import { instanceOf, type Blocks, type Instance } from "./views";

/** The host's reply to `request`, kept up to date while the component is mounted, and where the watch stands; `null` asks nothing. */
export function useWatched(request: Asked | null): { reply: Replied | null; connection: Connection } {
    const [reply, setReply] = useState<Replied | null>(null);
    const [connection, setConnection] = useState<Connection>("connecting");
    const key = JSON.stringify(request);
    useEffect(() => {
        const asked = JSON.parse(key) as Asked | null;
        return asked === null ? undefined : watch(asked, setReply, setConnection);
    }, [key]);
    return { reply, connection };
}

/**
 * `value`, or the one kept before it where `key` says the same of both: so what's computed from it, as the review's
 * layout from the tree's conversations, isn't computed again for a reply that changed nothing it reads, as the
 * watch's answer at each hook with what each conversation is doing (`docs/host.md`, *Watching*).
 */
export function useSame<T>(value: T, key: (value: T) => string): T {
    const kept = useRef<{ key: string; value: T } | null>(null);
    const now = key(value);
    if (kept.current === null || kept.current.key !== now) {
        kept.current = { key: now, value };
    }
    return kept.current.value;
}

/** What's shown of a value given again and again, and when it was last taken. */
export interface Paced<T> {
    shown: T;
    at: number;
}

/**
 * Return what's shown of `value`, given at `now`, `paced` having shown what it shows since its `at`: `value` itself
 * where `every` has passed since and the render it's given in was `asked` for, taken at `now`; else what was shown, and
 * how long until `value` is due.
 */
export function paced<T>(was: Paced<T>, value: T, now: number, every: number, asked: boolean = true): { paced: Paced<T>; due: number | null } {
    if (value === was.shown) {
        return { paced: was, due: null };
    }
    const due = was.at + every - now;
    return due <= 0 && asked ? { paced: { shown: value, at: now }, due: null } : { paced: was, due: Math.max(due, 0) };
}

/**
 * `value`, taken no sooner than `every()` milliseconds after it was last taken: at once where it's been that long, else
 * once it has, as it stands then. What's laid out from it is laid out no more often, however often it's given anew,
 * as what the host answers at each hook of agents at work.
 *
 * Taken only in a render asked for by what it depends on, `value` given anew or its own timer, never as time alone has
 * passed: a render a state set to what it held asks for, as the cursor's at a key that doesn't move it, may be one React
 * drops, keeping its hooks' state and not its effects, so what was laid out from a value taken there would never reach
 * the effect putting it in the editor, whose dependencies say it has (`bailoutHooks`, `react-dom`).
 */
export function usePaced<T>(value: T, every: () => number): T {
    const kept = useRef<Paced<T>>({ shown: value, at: 0 });
    const waiting = useRef<ReturnType<typeof setTimeout> | null>(null);
    const [woken, wake] = useState(0);
    const last = useRef({ value, woken });
    const asked = last.current.value !== value || last.current.woken !== woken;
    last.current = { value, woken };
    const next = paced(kept.current, value, Date.now(), every(), asked);
    kept.current = next.paced;
    if (next.due !== null && waiting.current === null) {
        waiting.current = setTimeout(() => {
            waiting.current = null;
            wake((times) => times + 1);
        }, next.due);
    }
    useEffect(
        () => () => {
            if (waiting.current !== null) {
                clearTimeout(waiting.current);
            }
        },
        [],
    );
    return kept.current.shown;
}

/** The time, again every `every` milliseconds, so how long something has lasted stays true. */
export function useNow(every = 1000): Date {
    const [now, setNow] = useState(() => new Date());
    useEffect(() => {
        const ticking = setInterval(() => setNow(new Date()), every);
        return () => clearInterval(ticking);
    }, [every]);
    return now;
}

/** Return which views to start watching, of those `asked`, and which to stop, of those `watching`, by their ids: those newly asked, and those no longer, every other left as it is. */
export function rewatching(watching: ReadonlySet<string>, asked: ReadonlySet<string>): { start: string[]; stop: string[] } {
    return { start: [...asked].filter((id) => !watching.has(id)), stop: [...watching].filter((id) => !asked.has(id)) };
}

/**
 * What the host answers of each view in `asked`, each watched while it's asked, answered again at its own triggers
 * (`docs/host.md`, *The views the dashboard shows*), by its instance's id (`views.ts`); a refusal, or a view not yet
 * answered, none. A view no longer asked stops being watched, and what it answered goes; one newly asked is watched
 * alone, every other left watched as it was, so a fold's view read as it opens, or let go as it closes, asks the host
 * nothing more of the rest.
 */
export function useViews(asked: readonly Instance[]): ReadonlyMap<string, Blocks> {
    const [answers, setAnswers] = useState<ReadonlyMap<string, Blocks>>(new Map());
    // How to stop watching each view watched, by its id.
    const watching = useRef(new Map<string, () => void>());
    const key = JSON.stringify(asked.map((each) => instanceOf(each.repository, each.module, each.view, each.argument)).sort());
    useEffect(() => {
        const byId = new Map(asked.map((each) => [instanceOf(each.repository, each.module, each.view, each.argument), each]));
        const ids = new Set(byId.keys());
        const { start, stop } = rewatching(new Set(watching.current.keys()), ids);
        for (const id of stop) {
            watching.current.get(id)?.();
            watching.current.delete(id);
        }
        for (const id of start) {
            const each = byId.get(id);
            if (each === undefined) {
                continue;
            }
            const request = { kind: "module-view" as const, repository: each.repository, module: each.module, view: each.view, argument: each.argument as never };
            watching.current.set(
                id,
                watch(
                    request,
                    (reply) => {
                        if (reply.kind === "module-viewed") {
                            setAnswers((before) => new Map(before).set(id, reply.blocks));
                        }
                    },
                    () => undefined,
                ),
            );
        }
        setAnswers((before) => ([...before.keys()].every((id) => ids.has(id)) ? before : new Map([...before].filter(([id]) => ids.has(id)))));
        // Watched again only where what's asked changes, by the views' ids.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [key]);
    // Every watch stops as the page lets the views go.
    useEffect(() => {
        const watched = watching.current;
        return () => {
            for (const stop of watched.values()) {
                stop();
            }
            watched.clear();
        };
    }, []);
    return answers;
}

