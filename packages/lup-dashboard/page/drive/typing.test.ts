import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { describe, expect, it } from "vitest";

describe("the measure of typing, as a command", () => {
    it("runs in Node as it is, typing into a comment on the demo and saying what landed", async () => {
        const command = fileURLToPath(new URL("typing.ts", import.meta.url));
        const { stdout } = await promisify(execFile)("node", [command, "--size", "0", "--keys", "6", "--gap", "20"]);
        expect(stdout).toContain("6 keys 20 ms apart into a comment");
        expect(stdout).toMatch(/round 1: key to frame median \d+ ms, p90 \d+ ms, most \d+ ms; 6 of 6 keys landed, 6 seen; the host kept it/);
    });
});
