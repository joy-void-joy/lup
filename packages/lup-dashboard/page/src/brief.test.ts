import { describe, expect, it } from "vitest";

import { calledBy, notSent } from "./App";
import { brief, partSaid, partsCounted, partsSaid, shortened, type ReplyPart } from "./brief";
import type { Conversation } from "./review";

describe("what the page says on one row", () => {
    it("says the first sentence alone, its whole left to g<", () => {
        expect(brief("reviewed a.py. b.py changed since you read it: shown with what came.")).toBe("reviewed a.py.");
        expect(shortened("reviewed a.py. b.py changed since you read it.")).toBe(true);
        expect(brief("Sent: read @66.")).toBe("Sent: read @66.");
        expect(shortened("Sent: read @66.")).toBe(false);
    });

    it("says a reply's parts on one line by what each does, items and threads done alike counted, and each whole, every number named", () => {
        const parts: ReplyPart[] = [
            { kind: "to", who: "s1", what: ["a message", "comments on @62"] },
            { kind: "thread", name: "reader", done: "read" },
            { kind: "items", done: "read", numbers: [1, 2] },
            { kind: "thread", name: "auth", done: "read" },
            { kind: "thread", name: "voice", done: "settled" },
            { kind: "items", done: "approving", numbers: [54] },
        ];
        expect(partsSaid(parts)).toBe("to s1: a message, comments on @62 · 2 threads read · read 2 items · @voice settled · approving @54");
        expect(parts.map(partSaid)).toEqual(["to s1: a message, comments on @62", "@reader read", "read @1, @2", "@auth read", "@voice settled", "approving @54"]);
        expect(partsCounted(parts)).toBe(true);
        // One thread or item alone is named.
        const alone: ReplyPart[] = [
            { kind: "thread", name: "reader", done: "read" },
            { kind: "items", done: "read", numbers: [66] },
        ];
        expect(partsSaid(alone)).toBe("@reader read · read @66");
        expect(partsCounted(alone)).toBe(false);
    });

    it("counts by what a part does, never by its words: what's said as it is stays as it is, worded as a thread's or with numbers", () => {
        const parts: ReplyPart[] = [
            { kind: "said", text: "@notes read" },
            { kind: "thread", name: "gate", done: "read" },
            { kind: "thread", name: "lag", done: "read" },
            { kind: "said", text: "check @1, @2: refused" },
            { kind: "items", done: "comments on", numbers: [4, 5], then: " kept: no session's push asked it" },
        ];
        expect(partsSaid(parts, "; ")).toBe("@notes read; 2 threads read; check @1, @2: refused; comments on 2 items kept: no session's push asked it");
        expect(parts.map(partSaid).join("; ")).toBe("@notes read; @gate read; @lag read; check @1, @2: refused; comments on @4, @5 kept: no session's push asked it");
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
