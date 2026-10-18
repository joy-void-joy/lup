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

/** The launches of one repository. */
export interface Repository {
    path: string;
    name: string;
    launches: Launch[];
}

/** Group launches by their repository, in the order each is first met. */
export function repositories(served: Launch[]): Repository[] {
    const paths = [...new Set(served.map((each) => each.launch.repository))];
    return paths.map((path) => ({
        path,
        name: repositoryName(path),
        launches: served.filter((each) => each.launch.repository === path),
    }));
}

/** Name a repository by its git directory: a bare one's own name (`lup.git` is `lup`), a clone's by the directory holding its `.git`. */
export function repositoryName(path: string): string {
    const parts = path.split("/").filter((part) => part !== "");
    const last = parts.at(-1) ?? path;
    if (last === ".git") {
        return parts.at(-2) ?? path;
    }
    return last.endsWith(".git") ? last.slice(0, -".git".length) : last;
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

/**
 * Whether a subagent's conversation is over: it ended, or no hook has been heard from it since the host began
 * keeping what each conversation does, at every hook, so one with nothing kept is from before and long over.
 */
export function over(agent: Agent): boolean {
    const activity = agent.talker.activity;
    return activity == null || activity.state === "ended";
}

/** A conversation running, with the launch it runs in. */
export interface Running {
    launch: Register;
    talker: Talker;
}

/**
 * Every conversation running, in the tree's order: each repository's launches, each session's own conversation,
 * then its subagents that aren't over, each under its parent, those running before those under one that's over.
 */
export function running(served: Launch[]): Running[] {
    function within(agent: Agent): Talker[] {
        const live = agent.children.filter((child) => !over(child));
        const gone = agent.children.filter(over);
        const own = agent.talker.agent == null || !over(agent) ? [agent.talker] : [];
        return [...own, ...live.flatMap(within), ...gone.flatMap(within)];
    }
    return repositories(served).flatMap((repository) =>
        repository.launches.flatMap((each) =>
            each.session === null ? [] : within(each.session).map((talker) => ({ launch: each.launch, talker })),
        ),
    );
}

/** The keys of a chord typed so far in the agents' tree: none, Space, or Space then `w`. */
export type Leading = "" | "space" | "space-w";

/** What a key does in the agents' tree: the chord it leaves begun, what it does, and whether the tree takes it from React Aria's own keys. */
export interface TreeKey {
    leading: Leading;
    act: "right" | "hold" | null;
    taken: boolean;
}

/**
 * What `key` does in the agents' tree, after the keys `leading` of a chord. `h` turns the operator's switch for the
 * conversation it's on; Space leads a chord, as in the views beside it: `l`, or `w` then `l`, gives the keyboard to the
 * view, and any other key ends the chord, taken. Every other key is React Aria's: arrows move, Enter selects.
 */
export function treeKey(leading: Leading, key: string): TreeKey {
    if (leading === "space" && key === "w") {
        return { leading: "space-w", act: null, taken: true };
    }
    if (leading !== "") {
        return { leading: "", act: key === "l" ? "right" : null, taken: true };
    }
    if (key === " ") {
        return { leading: "space", act: null, taken: true };
    }
    if (key === "h") {
        return { leading: "", act: "hold", taken: true };
    }
    return { leading: "", act: null, taken: false };
}

/** Say what a conversation is doing, and for how long. */
export function doing(activity: Activity | null | undefined, now: Date): string {
    if (activity == null) {
        return "not heard yet";
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
