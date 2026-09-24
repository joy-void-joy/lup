import { afterEach, describe, expect, test } from "bun:test";
import { answerReview, followInbox, readInbox, takeToken } from "./api";

const originalFetch = globalThis.fetch;
const snapshot = { roots: [], reviews: [], errors: [] };

afterEach(() => {
  globalThis.fetch = originalFetch;
  sessionStorage.clear();
  window.history.replaceState(null, "", "/");
});

describe("review capability", () => {
  test("takes the capability from the fragment, scrubs it, and keeps it only in this tab", () => {
    window.history.replaceState(null, "", "/#token=operator-secret");
    expect(takeToken()).toBe("operator-secret");
    expect(window.location.hash).toBe("");
    expect(takeToken()).toBe("operator-secret");
    expect(sessionStorage.getItem("lup-review-token")).toBe("operator-secret");
  });

  test("authenticates reads and answers without putting the capability in the URL or body", async () => {
    const calls: { url: string; options?: RequestInit }[] = [];
    globalThis.fetch = Object.assign(async (input: string | URL | Request, options?: RequestInit) => {
      calls.push({ url: String(input), options });
      return Response.json(snapshot);
    }, { preconnect() {} });
    await readInbox("operator-secret");
    await answerReview("tree/request", { approved: false, note: "Use a scoped change", fingerprint: "exact" }, "operator-secret");
    expect(calls.map((call) => call.url)).toEqual(["api/reviews", "api/reviews/tree%2Frequest/answer"]);
    for (const call of calls) expect(new Headers(call.options?.headers).get("Authorization")).toBe("Bearer operator-secret");
    expect(JSON.parse(String(calls[1]?.options?.body))).toEqual({ approved: false, note: "Use a scoped change", fingerprint: "exact" });
  });
});

describe("review stream", () => {
  test("decodes records and UTF-8 across arbitrary byte boundaries", async () => {
    const wanted = { ...snapshot, errors: [{ root: "é/check", message: "Readable" }] };
    const encoded = new TextEncoder().encode(`${JSON.stringify(wanted)}\n\n${JSON.stringify(snapshot)}`);
    globalThis.fetch = Object.assign(async () => new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        for (const byte of encoded) controller.enqueue(Uint8Array.of(byte));
        controller.close();
      },
    })), { preconnect() {} });
    const received = [];
    for await (const entry of followInbox("secret", new AbortController().signal)) received.push(entry);
    expect(received).toEqual([wanted, snapshot]);
  });

  test("surfaces refused credentials instead of decoding an error as a snapshot", async () => {
    globalThis.fetch = Object.assign(async () => Response.json({ detail: "Access denied" }, { status: 403 }), { preconnect() {} });
    await expect(followInbox("bad", new AbortController().signal).next()).rejects.toThrow("Access denied");
  });

  test("closing a reader cancels the underlying stream", async () => {
    let cancelled = false;
    globalThis.fetch = Object.assign(async () => new Response(new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(new TextEncoder().encode(`${JSON.stringify(snapshot)}\n`)); },
      cancel() { cancelled = true; },
    })), { preconnect() {} });
    const reader = followInbox("secret", new AbortController().signal);
    await reader.next();
    await reader.return(undefined);
    expect(cancelled).toBe(true);
  });
});
