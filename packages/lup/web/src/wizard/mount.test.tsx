// The wizard mounted as a page over a two-scope, two-step declaration: what
// it draws, what choosing a scope asks for, what a filled form posts, what an
// undo and a row act post, and the sign-in screen streamed over a socket.
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { act, StrictMode } from "react";
import type { StepReply, WizardView } from "../generated/views";
import {
  FakeWebSocket,
  click,
  labelled,
  mount,
  one,
  serve,
  stubCanvas,
  stubLayout,
  texts,
  type,
  until,
  type Call,
  type Mounted,
} from "../testing";
import { App } from "./App";

const view: WizardView = {
  title: "Setup wizard",
  lede: "Two steps to a working deployment.",
  notice: "",
  chosen: "alpha",
  scope_label: "Deployment",
  scopes: [
    { name: "alpha", label: "Alpha", detail: "the alpha deployment", chosen: true },
    { name: "beta", label: "Beta", detail: "the beta deployment", chosen: false },
  ],
  creates: "",
  create_asks: "",
  steps: [
    {
      slug: "credentials",
      title: "Credentials",
      kind: "form",
      blurb: "The client the deployment signs in as.",
      guide: ["Open the console", "Copy the client id"],
      numbered: true,
      opens: "https://console.example/credentials",
      fields: [
        { key: "client_id", label: "Client id", placeholder: "1234.apps", secret: false },
        { key: "client_secret", label: "Client secret", placeholder: "", secret: true },
      ],
      rows: [],
      standing: { done: false, offered: true, blocked: "", detail: "not configured" },
      submit: "Save credentials",
      tests: "Check",
      undoes: "Forget",
    },
    {
      slug: "accounts",
      title: "Accounts",
      kind: "rows",
      blurb: "",
      guide: [],
      numbered: false,
      opens: "",
      fields: [],
      rows: [
        {
          name: "ops@example.com",
          detail: "enrolled",
          stream: "",
          acts: [
            { slug: "remove", label: "Remove", asks: "", consequence: "Drops the account", destructive: true },
          ],
        },
        {
          name: "dev@example.com",
          detail: "not signed in",
          stream: "/api/wizard/accounts/stream/dev",
          acts: [
            { slug: "sign-in", label: "Sign in", asks: "", consequence: "Opens a browser", destructive: false },
          ],
        },
      ],
      standing: { done: false, offered: true, blocked: "", detail: "1 of 2 enrolled" },
      submit: "",
      tests: "",
      undoes: "",
    },
  ],
};

const saved: WizardView = {
  ...view,
  steps: view.steps.map((step) =>
    step.slug === "credentials"
      ? { ...step, standing: { ...step.standing, done: true, detail: "configured" } }
      : step,
  ),
};

function reply(message: string, after: WizardView): StepReply {
  return { outcome: { message, ok: true }, view: after };
}

const routes = {
  "api/wizard": view,
  "api/wizard/credentials/run": reply("Saved.", saved),
  "api/wizard/credentials/reset": reply("Forgotten.", view),
  "api/wizard/accounts/act": reply("Removed ops@example.com.", view),
};

describe("the wizard", () => {
  let calls: Call[];
  let shown: Mounted;

  beforeEach(async () => {
    stubLayout();
    stubCanvas();
    FakeWebSocket.install();
    window.history.replaceState(null, "", "/");
    calls = serve(routes);
    shown = mount(
      <StrictMode>
        <App />
      </StrictMode>,
    );
    await until(() => shown.root.querySelectorAll(".step").length === 2, "the two steps");
  });

  afterEach(() => shown.unmount());

  async function chooseScope(label: string): Promise<void> {
    await click(labelled(shown.root, ".scopes .tab", label));
    await until(
      () => calls.some((call) => call.path === "api/wizard" && call.search === `?scope=${label.toLowerCase()}`),
      `the view read for ${label}`,
    );
  }

  test("draws the declaration: title, scopes, the first step's guide and fields, the rows", () => {
    expect(document.title).toBe("Setup wizard");
    expect(one(shown.root, "h1").textContent).toBe("Setup wizard");
    expect(one(shown.root, ".lede").textContent).toBe("Two steps to a working deployment.");
    expect(one(shown.root, ".scopes span").textContent).toBe("Deployment:");
    expect(texts(shown.root, ".scopes .tab")).toEqual(["Alpha", "Beta"]);
    expect(one(shown.root, ".scopes .tab.on").textContent).toBe("Alpha");
    expect(texts(shown.root, ".step h2")).toEqual(["○Credentialsnot configured", "○Accounts1 of 2 enrolled"]);
    expect(texts(shown.root, "ol.guide li")).toEqual(["Open the console", "Copy the client id"]);
    expect(one(shown.root, "a.ext").getAttribute("href")).toBe("https://console.example/credentials");
    expect(one(shown.root, 'input[placeholder="1234.apps"]').getAttribute("type")).toBe("text");
    expect(shown.root.querySelectorAll('.step form input[type="password"]')).toHaveLength(1);
    expect(one(shown.root, 'button[type="submit"]').textContent).toBe("Save credentials");
    expect(texts(shown.root, ".row .name")).toEqual(["ops@example.com", "dev@example.com"]);
    expect(texts(shown.root, ".row button")).toEqual(["Remove", "Sign in"]);
    expect([...new Set(calls.map((call) => `${call.path}${call.search}`))]).toEqual(["api/wizard"]);
  });

  test("choosing a scope re-reads the view for it and puts it in the address", async () => {
    await chooseScope("Beta");
    expect(window.location.search).toBe("?scope=beta");
  });

  test("filling the form posts every field as the step's answers, and the reply redraws the step", async () => {
    await chooseScope("Alpha");
    await type(one(shown.root, 'input[placeholder="1234.apps"]'), "1234.apps");
    await type(one(shown.root, 'input[type="password"]'), "s3cret");
    await click(labelled(shown.root, "button", "Save credentials"));
    await until(() => calls.some((call) => call.path === "api/wizard/credentials/run"), "the run post");
    expect(calls.find((call) => call.path === "api/wizard/credentials/run")).toEqual({
      method: "POST",
      path: "api/wizard/credentials/run",
      search: "?scope=alpha",
      body: {
        answers: [
          { key: "client_id", value: "1234.apps" },
          { key: "client_secret", value: "s3cret" },
        ],
      },
    });
    await until(() => one(shown.root, "#status").textContent === "Saved.", "the outcome");
    expect(one(shown.root, "#status").className).toBe("ok");
    expect(texts(shown.root, ".step h2")[0]).toBe("✓Credentialsconfigured");
  });

  test("the undo posts the step's reset, and a row's act posts which row and verb", async () => {
    await chooseScope("Alpha");
    await click(labelled(shown.root, "button", "Forget"));
    await until(() => one(shown.root, "#status").textContent === "Forgotten.", "the undo's outcome");
    expect(calls.find((call) => call.path === "api/wizard/credentials/reset")).toEqual({
      method: "POST",
      path: "api/wizard/credentials/reset",
      search: "?scope=alpha",
      body: {},
    });

    await click(labelled(shown.root, ".row button", "Remove"));
    await until(() => one(shown.root, "#status").textContent === "Removed ops@example.com.", "the act's outcome");
    expect(calls.find((call) => call.path === "api/wizard/accounts/act")).toEqual({
      method: "POST",
      path: "api/wizard/accounts/act",
      search: "?scope=alpha",
      body: { row: "ops@example.com", act: "remove", answer: "" },
    });
  });

  test("signing in streams the server's browser over a socket until it says signed in", async () => {
    await chooseScope("Alpha");
    const before = calls.length;
    await click(labelled(shown.root, ".row button", "Sign in"));
    await until(() => shown.root.querySelector("canvas#screen") !== null, "the screen");
    const socket = FakeWebSocket.current();
    expect(socket.url).toBe("ws://localhost/api/wizard/accounts/stream/dev");
    expect(one(shown.root, "#status").textContent).toBe("Starting a browser…");

    await act(async () => {
      one(shown.root, "canvas#screen").dispatchEvent(
        new MouseEvent("mousedown", { clientX: 120, clientY: 40, bubbles: true }),
      );
    });
    const pressed: { mouse: { action: string; x: number; y: number } } = JSON.parse(socket.sent[0] ?? "null");
    expect(pressed.mouse.action).toBe("mousePressed");

    await act(async () => socket.deliver({ signed_in: true }));
    await until(() => shown.root.querySelector("canvas#screen") === null, "the screen closing");
    expect(one(shown.root, "#status").textContent).toBe("Signed in. You can enrol them now.");
    expect(socket.readyState).toBe(FakeWebSocket.CLOSED);
    await until(() => calls.length > before && calls[calls.length - 1]?.path === "api/wizard", "the re-read");
    expect(calls[calls.length - 1]?.search).toBe("?scope=alpha");
  });
});
