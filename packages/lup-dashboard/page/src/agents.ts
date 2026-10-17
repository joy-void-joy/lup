// The agents the host serves, as the page shows them: each launch with its
// session's conversation, and each subagent under the conversation that spawned it.
import type { ReplyOf } from "./api";

type Listed = ReplyOf<"listed">;
export type Register = Listed["launches"][number];
export type Talker = NonNullable<Listed["talkers"]>[string][number];
export type Activity = NonNullable<Talker["activity"]>;

/** A conversation, with the subagents it spawned. */
export interface Agent {
    talker: Talker;
    children: Agent[];
}

/** A launch the host serves: its session's conversation and every subagent under it, none before its session is heard. */
export interface Launch {
    launch: Register;
    session: Agent | null;
}

/** Arrange what the host listed into its launches, each conversation under its parent. */
export function launches(listed: Listed): Launch[] {
    return listed.launches.map((launch) => {
        const talkers = listed.talkers?.[launch.launch] ?? [];
        const [own] = talkers.filter((talker) => talker.parent == null);
        return { launch, session: own === undefined ? null : under(own, talkers) };
    });
}

function under(talker: Talker, talkers: Talker[]): Agent {
    const children = talkers
        .filter((each) => each.parent === talker.path)
        .map((each) => under(each, talkers));
    return { talker, children };
}

/** Every conversation of every launch, a session's before its subagents: what the palette goes to. */
export function everyone(served: Launch[]): Agent[] {
    function within(agent: Agent): Agent[] {
        return [agent, ...agent.children.flatMap(within)];
    }
    return served.flatMap((each) => (each.session === null ? [] : within(each.session)));
}

/** Say what a conversation is doing, and for how long. */
export function doing(activity: Activity | null | undefined, now: Date): string {
    if (activity == null) {
        return "not heard since the host started";
    }
    const lasted = since(new Date(activity.since), now);
    switch (activity.state) {
        case "calling":
            return `${activity.lups ? "asking lup" : "calling"} ${activity.tool ?? "a tool"} · ${lasted}`;
        case "idle":
            return `between calls · ${lasted}`;
        case "ended":
            return `ended · ${lasted} ago`;
    }
}

/** Say how long ago `at` was, roughly: seconds, minutes, hours, then days. */
export function since(at: Date, now: Date): string {
    const seconds = Math.max(0, Math.round((now.getTime() - at.getTime()) / 1000));
    if (seconds < 60) {
        return `${seconds}s`;
    }
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) {
        return `${minutes}m`;
    }
    const hours = Math.floor(minutes / 60);
    if (hours < 48) {
        return `${hours}h`;
    }
    return `${Math.floor(hours / 24)}d`;
}
