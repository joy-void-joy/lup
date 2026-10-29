import { describe, expect, it } from "vitest";

import { demo } from "./demo.ts";

describe("the demo", () => {
    it("is served on a port of its own, two started at once, until it's closed", async () => {
        const [first, second] = await Promise.all([demo({ size: 0 }), demo({ size: 0 })]);
        try {
            expect(new URL(first.url).port).not.toBe(new URL(second.url).port);
            expect(new URL(first.url).hash).toMatch(/^#token=./);
            expect((await fetch(first.url)).ok).toBe(true);
            expect((await fetch(second.url)).ok).toBe(true);
        } finally {
            await first.close();
            await second.close();
        }
        await expect(fetch(first.url)).rejects.toThrow();
    });
});
