import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { act } from "react";
import { App } from "./App";
import { click, labelled, mount, one, until, type Mounted } from "../testing";

const originalFetch = globalThis.fetch;
const root = { id: "tree", path: "/project/tree/feature" };
const summary = {
  key: "tree-q1", root_id: root.id, id: "q1", state: "pending", requester: "codex-session",
  reason: "Review the complete replacement", operation: "apply_patch in /project", rule: "whole-file",
  created: "2026-09-24T12:00:00Z", answerable: true,
};

function review() {
  return {
    summary: { ...summary },
    question: {
      fingerprint: "bound-payload", resumption: "native_retry", answer: null as null | { approved: boolean; principal: string; note: string },
      operation: { tool: "apply_patch", payload: { patch: "Complete requested patch" } },
    },
    files: [{ path: "/project/file.py", operation: "modify", before: "before\n", after: "after\n", unified: "--- before\n+++ after\n-before\n+after\n", unchanged: false }],
    stale_reason: "",
  };
}

describe("review inbox page", () => {
  let shown: Mounted | null = null;
  let detail = review();
  let rows = [{ ...summary }];
  let answerStatus = 200;
  let stream: ReadableStreamDefaultController<Uint8Array> | null = null;
  let streamingAborted = false;
  let requests: { path: string; method: string; body: unknown; authorization: string | null }[] = [];

  const inbox = () => ({ roots: [root], reviews: rows, errors: [] });

  beforeEach(() => {
    detail = review();
    rows = [{ ...summary }];
    answerStatus = 200;
    stream = null;
    streamingAborted = false;
    requests = [];
    sessionStorage.clear();
    window.history.replaceState(null, "", "/#token=browser-secret");
    globalThis.fetch = Object.assign(async (input: string | URL | Request, options?: RequestInit) => {
      const path = String(input);
      requests.push({ path, method: options?.method ?? "GET", body: typeof options?.body === "string" ? JSON.parse(options.body) : null,
        authorization: new Headers(options?.headers).get("Authorization") });
      if (path === "api/events") return new Response(new ReadableStream<Uint8Array>({
        start(controller) {
          stream = controller;
          controller.enqueue(new TextEncoder().encode(`${JSON.stringify(inbox())}\n`));
          options?.signal?.addEventListener("abort", () => {
            streamingAborted = true;
            controller.error(new DOMException("Stopped", "AbortError"));
          }, { once: true });
        },
      }));
      if (path === "api/reviews") return Response.json(inbox());
      if (path === "api/reviews/tree-q1") return Response.json(detail);
      if (path === "api/reviews/tree-q1/answer") {
        if (answerStatus !== 200) return Response.json({ detail: "The file changed; refresh the request." }, { status: answerStatus });
        const body = JSON.parse(String(options?.body)) as { approved: boolean; note: string };
        detail = { ...detail, summary: { ...detail.summary, state: body.approved ? "approved" : "rejected", answerable: false },
          question: { ...detail.question, answer: { ...body, principal: "operator" } } };
        rows = [{ ...detail.summary }];
        return Response.json({ review: detail, notification: { queued: true, woken: false, detail: "Decision queued for the requesting session." } });
      }
      return Response.json({ detail: `Unknown fixture route ${path}` }, { status: 404 });
    }, { preconnect() {} });
  });

  afterEach(() => {
    shown?.unmount();
    shown = null;
    globalThis.fetch = originalFetch;
    sessionStorage.clear();
    window.history.replaceState(null, "", "/");
  });

  async function open() {
    shown = mount(<App />);
    await until(() => shown?.root.querySelector(".decision") !== null && shown?.root.querySelector(".decision") !== undefined, "the decision form");
    return shown;
  }

  async function comment(value: string) {
    if (shown === null) throw new Error("page is not open");
    const textarea = one<HTMLTextAreaElement>(shown.root, "textarea");
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
    if (setter === undefined) throw new Error("textarea has no value setter");
    await act(async () => {
      setter.call(textarea, value);
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }

  test("shows complete evidence and submits an exact approval with the comment", async () => {
    const page = await open();
    const change = detail.files[0];
    if (change === undefined) throw new Error("fixture carries no change");
    expect(one(page.root, ".diff").textContent).toBe(change.unified);
    expect(one(page.root, ".record pre").textContent).toContain("Complete requested patch");
    expect(page.root.textContent).toContain("before\n");
    await comment("Keep the public signature.");
    await click(labelled(page.root, "button", "Approve"));
    await until(() => page.root.textContent?.includes("Approval recorded.") ?? false, "the approval receipt");
    expect(requests.find((request) => request.method === "POST")?.body).toEqual({ approved: true, note: "Keep the public signature.", fingerprint: "bound-payload" });
    expect(requests.every((request) => request.authorization === "Bearer browser-secret")).toBe(true);
    expect(window.location.hash).toBe("");
    expect(page.root.textContent).toContain("Decision queued for the requesting session.");
    expect(page.root.querySelector(".decision")).toBeNull();
    await click(labelled(page.root, "button", "History (1)"));
    expect(page.root.querySelectorAll(".queue-row")).toHaveLength(1);
  });

  test("a refused submission keeps the comment and permits an explicit rejection", async () => {
    const page = await open();
    answerStatus = 409;
    await comment("Use a scoped patch.");
    await click(labelled(page.root, "button", "Approve"));
    await until(() => page.root.textContent?.includes("The file changed") ?? false, "the refusal");
    expect(one<HTMLTextAreaElement>(page.root, "textarea").value).toBe("Use a scoped patch.");
    answerStatus = 200;
    await click(labelled(page.root, "button", "Reject"));
    await until(() => page.root.textContent?.includes("Rejected by operator") ?? false, "the rejected record");
    expect(requests.filter((request) => request.method === "POST")[1]?.body).toEqual({ approved: false, note: "Use a scoped patch.", fingerprint: "bound-payload" });
  });

  test("live snapshots add requests and stale evidence prevents approval", async () => {
    detail.stale_reason = "The proposed file has changed.";
    const page = await open();
    expect(labelled<HTMLButtonElement>(page.root, "button", "Approve").disabled).toBe(true);
    expect(labelled<HTMLButtonElement>(page.root, "button", "Reject").disabled).toBe(false);
    rows = [{ ...summary }, { ...summary, key: "tree-q2", id: "q2", reason: "A second request" }];
    await act(async () => stream?.enqueue(new TextEncoder().encode(`${JSON.stringify(inbox())}\n`)));
    await until(() => page.root.querySelectorAll(".queue-row").length === 2, "the new queued request");
    page.unmount();
    shown = null;
    expect(streamingAborted).toBe(true);
  });

  test("missing capability makes no requests", async () => {
    window.history.replaceState(null, "", "/");
    shown = mount(<App />);
    expect(shown.root.textContent).toContain("This tab has no access token");
    expect(requests).toHaveLength(0);
  });

  test("a newer request never replaces the request or comment being reviewed", async () => {
    const page = await open();
    await comment("This comment belongs to the first request.");
    rows = [{ ...summary, key: "tree-q2", id: "q2", reason: "A newer request" }, { ...summary }];
    await act(async () => stream?.enqueue(new TextEncoder().encode(`${JSON.stringify(inbox())}\n`)));
    await until(() => page.root.querySelectorAll(".queue-row").length === 2, "the newer request");
    expect(one(page.root, ".queue-row.selected").textContent).toContain(summary.reason);
    expect(one(page.root, ".request .reason").textContent).toBe(summary.reason);
    expect(one<HTMLTextAreaElement>(page.root, "textarea").value).toBe("This comment belongs to the first request.");
    await click(labelled(page.root, "button", "Approve"));
    await until(() => requests.some((request) => request.method === "POST"), "the original request approval");
    expect(requests.find((request) => request.method === "POST")?.path).toBe("api/reviews/tree-q1/answer");
  });

  test("a disconnected stream reports failure and reconnects without losing the comment", async () => {
    const page = await open();
    await comment("Preserve this draft.");
    await act(async () => stream?.error(new Error("Connection lost")));
    await until(() => page.root.textContent?.includes("Reconnecting") ?? false, "the reconnect status");
    await click(labelled(page.root, "button", "Reconnect"));
    await until(() => requests.filter((request) => request.path === "api/events").length === 2, "a fresh stream");
    expect(one<HTMLTextAreaElement>(page.root, "textarea").value).toBe("Preserve this draft.");
    expect(page.root.textContent).toContain("Live");
  });
});
