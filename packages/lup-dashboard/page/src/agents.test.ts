import { describe, expect, it } from "vitest";

import { doing, everyone, launches, repositories, repositoryName, since, type Register, type Talker } from "./agents";

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
    return { path, own, session: "s1", agent, kind: null, parent, depth, activity: null };
}

describe("launches", () => {
    it("puts each subagent under the conversation that spawned it", () => {
        const listed = {
            kind: "listed" as const,
            launches: [registered("one", "w"), registered("two", "x")],
            sessions: {},
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
        expect(repositoryName("/home/op/adlib/.git")).toBe("adlib");
        expect(repositoryName("/home/op/plain")).toBe("plain");
    });

    it("groups launches by their repository, in the order met", () => {
        const one = { launch: { ...registered("one", "w"), repository: "/r/lup.git" }, session: null };
        const two = { launch: { ...registered("two", "x"), repository: "/r/adlib/.git" }, session: null };
        const three = { launch: { ...registered("three", "y"), repository: "/r/lup.git" }, session: null };
        const grouped = repositories([one, two, three]);
        expect(grouped.map((each) => [each.name, each.launches.length])).toEqual([
            ["lup", 2],
            ["adlib", 1],
        ]);
    });
});
