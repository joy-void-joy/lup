// React's side of the API: a request watched for as long as a component shows it.
import { useEffect, useRef, useState } from "react";

import { watch, type Asked, type Connection, type Replied } from "./api";

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

/** The time, again every `every` milliseconds, so how long something has lasted stays true. */
export function useNow(every = 1000): Date {
    const [now, setNow] = useState(() => new Date());
    useEffect(() => {
        const ticking = setInterval(() => setNow(new Date()), every);
        return () => clearInterval(ticking);
    }, [every]);
    return now;
}
