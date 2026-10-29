import "./fixtures/looks";
import { describe, expect, it } from "vitest";

import {
    doing,
    everyone,
    launches,
    repositories,
    repositoryName,
    ring,
    running,
    since,
    tokens,
    type Register,
    type Talker,
} from "./agents";

const AT = "2026-10-01T12:00:00Z";

function registered(launch: string, name: string): Register {
    return {
        kind: "register",
        launch,
        runtime: "claude",
        worktree: `/w/${name}`,
        repository: "/w/.git",
        judge: "/judge",
        container: `lup-${launch}`,
        limits: { actions: [], protected: [], gated: [] },
        github: null,
        name,
        exact: false,
    };
}

function talker(path: string, parent: string | null, depth: number): Talker {
    const own = path.split("/").at(-1) ?? path;
    const agent = parent === null ? null : own;
    return { path, own, session: "s1", agent, kind: null, parent, depth, activity: null, holding: false };
}

describe("launches", () => {
    it("puts each subagent under the conversation that spawned them", () => {
        const listed = {
            kind: "listed" as const,
            launches: [registered("one", "w"), registered("two", "x")],
            sessions: {},
            looks: {},
            standing: { folds: [], tones: [], drawers: [], banners: [], verbs: [] },
            talkers: {
                one: [
                    talker("w", null, 0),
                    talker("w/explore", "w", 1),
                    talker("w/explore/grep", "w/explore", 2),
                    talker("w/plan", "w", 1),
                ],
            },
        };
        const [one, two] = launches(listed);
        expect(one?.session?.talker.path).toBe("w");
        expect(one?.session?.children.map((each) => each.talker.path)).toEqual(["w/explore", "w/plan"]);
        expect(one?.session?.children[0]?.children.map((each) => each.talker.path)).toEqual([
            "w/explore/grep",
        ]);
        expect(two?.session).toBeNull();
        expect(everyone(launches(listed)).map((each) => each.talker.path)).toEqual([
            "w",
            "w/explore",
            "w/explore/grep",
            "w/plan",
        ]);
    });
});

describe("running", () => {
    it("lists each session and their subagents who aren't over, in the tree's order, with the launch each runs in", () => {
        const idle = { state: "idle" as const, since: AT, lups: false };
        const ended = { state: "ended" as const, since: AT, lups: false };
        const listed = {
            kind: "listed" as const,
            launches: [registered("one", "w"), registered("two", "x"), registered("three", "y")],
            sessions: {},
            looks: {},
            standing: { folds: [], tones: [], drawers: [], banners: [], verbs: [] },
            talkers: {
                one: [
                    { ...talker("w", null, 0), activity: null },
                    { ...talker("w/done", "w", 1), activity: ended },
                    { ...talker("w/done/late", "w/done", 2), activity: idle },
                    { ...talker("w/old", "w", 1), activity: null },
                    { ...talker("w/plan", "w", 1), activity: idle },
                ],
                two: [{ ...talker("x", null, 0), session: "s2", activity: idle }],
            },
        };
        expect(running(launches(listed)).map((each) => [each.launch.launch, each.talker.path])).toEqual([
            ["one", "w"],
            ["one", "w/plan"],
            ["one", "w/done/late"],
            ["two", "x"],
        ]);
    });
});

describe("doing", () => {
    const now = new Date("2026-10-01T12:05:00Z");

    it("says a call, lup's own, a wait between calls and an end, with how long", () => {
        expect(doing({ state: "calling", since: AT, tool: "Bash", lups: false }, now)).toBe("calling Bash · 5m");
        expect(doing({ state: "calling", since: AT, tool: "mcp__lup__ask", lups: true }, now)).toBe(
            "asking lup mcp__lup__ask · 5m",
        );
        expect(doing({ state: "idle", since: AT, lups: false }, now)).toBe("between calls · 5m");
        expect(doing({ state: "ended", since: AT, lups: false }, now)).toBe("ended · 5m ago");
        expect(doing(null, now)).toBe("not heard yet");
    });
});

describe("since", () => {
    it("rounds to the largest unit that fits", () => {
        const at = new Date(AT);
        const after = (seconds: number) => new Date(at.getTime() + seconds * 1000);
        expect([42, 125, 3 * 3600, 72 * 3600].map((each) => since(at, after(each)))).toEqual([
            "42s",
            "2m",
            "3h",
            "3d",
        ]);
    });
});

describe("repositories", () => {
    it("names a bare repository and a clone by what the operator calls them", () => {
        expect(repositoryName("/home/op/lup.git")).toBe("lup");
        expect(repositoryName("/home/op/zoetrope/.git")).toBe("zoetrope");
        expect(repositoryName("/home/op/plain")).toBe("plain");
    });

    it("groups launches by their repository, in the order met", () => {
        const one = { launch: { ...registered("one", "w"), repository: "/r/lup.git" }, session: null };
        const two = { launch: { ...registered("two", "x"), repository: "/r/zoetrope/.git" }, session: null };
        const three = { launch: { ...registered("three", "y"), repository: "/r/lup.git" }, session: null };
        const grouped = repositories([one, two, three]);
        expect(grouped.map((each) => [each.name, each.launches.length])).toEqual([
            ["lup", 2],
            ["zoetrope", 1],
        ]);
    });
});

describe("ring", () => {
    it("says the tokens in use against the window, the ring filled to the nearest quarter, the count alone with no window", () => {
        expect(ring(112_000, 1_000_000)).toBe("○ 112k/1M");
        expect(ring(300_000, 1_000_000)).toBe("◔ 300k/1M");
        expect(ring(100_000, 200_000)).toBe("◑ 100k/200k");
        expect(ring(150_000, 200_000)).toBe("◕ 150k/200k");
        expect(ring(190_000, 200_000)).toBe("● 190k/200k");
        expect(ring(840, null)).toBe("840");
        expect(tokens(1_500_000)).toBe("1.5M");
        expect(tokens(12_000_000)).toBe("12M");
    });
});
