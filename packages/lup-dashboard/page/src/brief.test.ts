import { describe, expect, it } from "vitest";

import { calledBy, notSent } from "./App";
import { brief, countedRuns, partsSaid, shortened } from "./brief";
import type { Conversation } from "./review";

describe("what the page says on one row", () => {
    it("counts each run of two or more items' numbers, one alone named", () => {
        expect(countedRuns("read @51, @58 and @69 · approving @54")).toBe("read 3 items · approving @54");
        expect(countedRuns("@51 @58 @69.2 left")).toBe("3 items left");
        expect(countedRuns("@dashboard-review read")).toBe("@dashboard-review read");
    });

    it("says the first sentence alone, its whole left to g<", () => {
        expect(brief("reviewed a.py. b.py changed since you read it: shown with what came.")).toBe("reviewed a.py.");
        expect(shortened("reviewed a.py. b.py changed since you read it.")).toBe(true);
        expect(brief("Sent: read @66.")).toBe("Sent: read @66.");
        expect(shortened("Sent: read @66.")).toBe(false);
        expect(brief("Sent: read @1, @2, @3.")).toBe("Sent: read 3 items.");
    });

    it("says a reply's parts on one line, threads marked alike counted where the first was", () => {
        expect(partsSaid(["to s1: a message", "@reader read", "read @1, @2", "@auth read", "@voice settled"])).toBe("to s1: a message · 2 threads read · read 2 items · @voice settled");
        expect(partsSaid(["@reader read"])).toBe("@reader read");
    });

    it("says a reply not sent in one sentence, the draft kept", () => {
        expect(notSent("the dashboard can't be reached: the host is restarting, or out of reach.")).toBe(
            "Not sent, your draft kept: the dashboard can't be reached: the host is restarting, or out of reach.",
        );
        expect(shortened(notSent("the host is restarting"))).toBe(false);
    });

    it("names a conversation by their name, never by an id whole: the start of their id where another shares the name", () => {
        const session: Conversation = { party: "conversation", repository: "/r/lup.git", runtime: "claude", session: "c0fa70bc-c700-4294-b9b5-6296b7d5553b", agent: null };
        const subagent: Conversation = { ...session, agent: "a286754c2226941b0" };
        expect(calledBy(session, "dashboard-review", false)).toBe("dashboard-review");
        expect(calledBy(session, "dashboard-review", true)).toBe("dashboard-review c0fa70bc");
        expect(calledBy(subagent, "dashboard-review/explore", true)).toBe("dashboard-review/explore a286754c");
        expect(calledBy(subagent, null, false)).toBe("claude c0fa70bc / a286754c");
    });
});
