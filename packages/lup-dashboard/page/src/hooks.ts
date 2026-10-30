// React's side of the API: a request watched for as long as a component shows it.
import { useEffect, useMemo, useRef, useState } from "react";

import { watch, type Asked, type Connection, type Replied, type ReplyOf } from "./api";
import { instanceOf, type Blocks, type Instance } from "./views";

/** The host's reply to `request`, kept up to date while the component is mounted, and where the watch stands. */
export function useWatched(request: Asked): { reply: Replied | null; connection: Connection } {
    const [reply, setReply] = useState<Replied | null>(null);
    const [connection, setConnection] = useState<Connection>("connecting");
    const key = JSON.stringify(request);
    useEffect(() => watch(JSON.parse(key) as Asked, setReply, setConnection), [key]);
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
 * where `every` has passed since, taken at `now`; else what was shown, and how long until `value` is due.
 */
export function paced<T>(was: Paced<T>, value: T, now: number, every: number): { paced: Paced<T>; due: number | null } {
    if (value === was.shown) {
        return { paced: was, due: null };
    }
    const due = was.at + every - now;
    return due <= 0 ? { paced: { shown: value, at: now }, due: null } : { paced: was, due };
}

/**
 * `value`, taken no sooner than `every()` milliseconds after it was last taken: at once where it's been that long, else
 * once it has, as it stands then. What's laid out from it is laid out no more often, however often it's given anew,
 * as what the host answers at each hook of agents at work.
 */
export function usePaced<T>(value: T, every: () => number): T {
    const kept = useRef<Paced<T>>({ shown: value, at: 0 });
    const waiting = useRef<ReturnType<typeof setTimeout> | null>(null);
    const [, wake] = useState(0);
    const next = paced(kept.current, value, Date.now(), every());
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

/**
 * What the host answers of each view in `asked`, each watched while it's asked, answered again at its own triggers
 * (`docs/host.md`, *The views the dashboard shows*), by its instance's id (`views.ts`); a refusal, or a view not yet
 * answered, none. A view no longer asked stops being watched, and what it answered goes.
 */
export function useViews(asked: readonly Instance[]): ReadonlyMap<string, Blocks> {
    const [answers, setAnswers] = useState<ReadonlyMap<string, Blocks>>(new Map());
    const key = JSON.stringify(asked.map((each) => instanceOf(each.repository, each.module, each.view, each.argument)).sort());
    useEffect(() => {
        const ids = new Set<string>();
        const stops = asked.map((each) => {
            const id = instanceOf(each.repository, each.module, each.view, each.argument);
            ids.add(id);
            const request = { kind: "module-view" as const, repository: each.repository, module: each.module, view: each.view, argument: each.argument as never };
            return watch(
                request,
                (reply) => {
                    if (reply.kind === "module-viewed") {
                        setAnswers((before) => new Map(before).set(id, reply.blocks));
                    }
                },
                () => undefined,
            );
        });
        setAnswers((before) => new Map([...before].filter(([id]) => ids.has(id))));
        return () => stops.forEach((stop) => stop());
        // Watched again only where what's asked changes, by the views' ids.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [key]);
    return answers;
}

/**
 * How many of what came before where the operator last read a thread show before what's new, the latest, each folded to
 * its header: a little they may have seen, as context, the rest under "N earlier" (`ShowThread.seen`).
 */
const SEEN = 3;

/** One thread's conversation the page asks for: from where the operator last read it, or whole. */
export interface ThreadAsked {
    number: number;
    whole: boolean;
}

/**
 * What the host answers of each thread's conversation in `asked`, each watched while it's asked, answered again as the
 * thread changes (`inbox-thread`; `docs/inbox.md`, *Threads in the review*): those from where the operator last read
 * them, and those read whole, each by the thread's number. One no longer asked stops being watched, and what it
 * answered goes; a refusal, or one not yet answered, none.
 */
export function useThreads(asked: readonly ThreadAsked[]): { shown: ReadonlyMap<number, ReplyOf<"inbox-thread-shown">>; whole: ReadonlyMap<number, ReplyOf<"inbox-thread-shown">> } {
    const [answers, setAnswers] = useState<ReadonlyMap<string, ReplyOf<"inbox-thread-shown">>>(new Map());
    // Each watch running, by its thread's key: one asked again is kept, never watched anew.
    const watching = useRef(new Map<string, () => void>());
    const keyOf = (each: ThreadAsked) => `${each.number}${each.whole ? " whole" : ""}`;
    const key = JSON.stringify(asked.map(keyOf).sort());
    useEffect(() => {
        const keys = new Set(asked.map(keyOf));
        for (const [each, stop] of watching.current) {
            if (!keys.has(each)) {
                stop();
                watching.current.delete(each);
            }
        }
        for (const each of asked) {
            const at = keyOf(each);
            if (watching.current.has(at)) {
                continue;
            }
            const stop = watch(
                { kind: "inbox-thread", number: each.number, whole: each.whole, seen: SEEN },
                (reply) => {
                    if (reply.kind === "inbox-thread-shown") {
                        setAnswers((before) => new Map(before).set(at, reply));
                    }
                },
                () => undefined,
            );
            watching.current.set(at, stop);
        }
        setAnswers((before) => (before.size === 0 || [...before.keys()].every((each) => keys.has(each)) ? before : new Map([...before].filter(([each]) => keys.has(each)))));
        // Watched again only where what's asked changes, by the threads' keys.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [key]);
    useEffect(
        () => () => {
            for (const stop of watching.current.values()) {
                stop();
            }
            watching.current.clear();
        },
        [],
    );
    return useMemo(() => {
        const shown = new Map<number, ReplyOf<"inbox-thread-shown">>();
        const whole = new Map<number, ReplyOf<"inbox-thread-shown">>();
        for (const [each, reply] of answers) {
            (each.endsWith(" whole") ? whole : shown).set(reply.read.thread.number, reply);
        }
        return { shown, whole };
    }, [answers]);
}
