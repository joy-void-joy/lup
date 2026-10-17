// React's side of the API: a request watched for as long as a component shows it.
import { useEffect, useState } from "react";

import { watch, type Asked, type Connection, type Replied } from "./api";

/** The host's reply to `request`, kept up to date while the component is mounted, and where the watch stands. */
export function useWatched(request: Asked): { reply: Replied | null; connection: Connection } {
    const [reply, setReply] = useState<Replied | null>(null);
    const [connection, setConnection] = useState<Connection>("connecting");
    const key = JSON.stringify(request);
    useEffect(() => watch(JSON.parse(key) as Asked, setReply, setConnection), [key]);
    return { reply, connection };
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
