// The supervisor mounted as a page over one recorded run: the rail, picking
// the run, its questions and what answering posts, and the trace drawn from
// what the event stream delivers.
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { act, StrictMode } from "react";
import type {
  ConcernView,
  JournalEntry,
  PendingQuestionView,
  RunIndex,
  SupervisorState,
} from "../generated/views";
import {
  FakeEventSource,
  choose,
  click,
  json,
  labelled,
  mount,
  one,
  serve,
  stubLayout,
  texts,
  until,
  type Call,
  type Mounted,
} from "../testing";
import { App } from "./App";

const PHASES: SupervisorState["phases"] = [
  "inventory",
  "questions",
  "eligibility",
  "dag",
  "leases",
  "workers",
  "dependency_bases",
  "review",
  "integration",
  "verification",
  "cleanup",
  "complete",
  "aborted",
  "failed",
];
const STATUSES: SupervisorState["statuses"] = [
  "discovered",
  "waiting_for_answers",
  "eligible",
  "ineligible",
  "leased",
  "running",
  "validating",
  "reviewing",
  "revising",
  "verified",
  "integrating",
  "integrated",
  "cleaned",
  "retained",
  "retired",
  "failed",
];

function concern(
  id: string,
  title: string,
  status: ConcernView["status"],
  branch: string | null,
  rounds: number,
): ConcernView {
  return {
    id,
    title,
    status,
    reason: "",
    eligible: true,
    integration_approved: true,
    eligibility_reason: "no dependencies",
    dependencies: [],
    branch,
    commit: branch === null ? null : "0123456789abcdef",
    rounds,
    failure: null,
  };
}

function asked(
  id: string,
  concernId: string,
  prompt: string,
  choices: string[],
  answered: string | null,
): PendingQuestionView {
  return {
    answered,
    asked_by: `worker:${concernId}#1`,
    offer: null,
    question: {
      allowances: [],
      choices,
      closed_choices: choices.length > 0,
      concern_id: concernId,
      criteria: [],
      id,
      prompt,
      recommendation: null,
    },
  };
}

// Two questions still open and one settled, the settled one listed first so
// the page's ordering has something to move.
const state: SupervisorState = {
  run_id: "run-1",
  phase: "workers",
  status: "awaiting_answers",
  live: false,
  last_activity: 1757498400,
  phases: PHASES,
  statuses: STATUSES,
  progress_line: "2 of 3 concerns leased",
  rerun_recipe: "uv run lup-devtools harness resolve --run run-1",
  concerns: [
    concern("alpha", "Alpha adapter", "waiting_for_answers", null, 0),
    concern("beta", "Beta routes", "running", "feat-beta", 1),
    concern("gamma", "Gamma docs", "verified", "feat-gamma", 1),
  ],
  pending: [
    asked("q-gamma", "gamma", "Keep the docs page?", ["keep", "drop"], "keep"),
    asked("q-alpha", "alpha", "Keep the legacy adapter?", ["keep", "drop"], null),
    asked("q-beta", "beta", "Which prefix do the routes take?", [], null),
  ],
  review: null,
  failures: [],
};

const answered: SupervisorState = {
  ...state,
  pending: state.pending.map((view) =>
    view.question.id === "q-alpha" ? { ...view, answered: "drop" } : view,
  ),
};

const index: RunIndex = {
  runs: [
    {
      run_id: "run-1",
      phase: "workers",
      concerns: 3,
      pending_questions: 2,
      live: false,
      unreadable: false,
      detail: "",
      last_activity: 1757498400,
    },
  ],
};

const identifiers = { session: { value: "s1" }, turn: { value: "t1" } };

function entry(seq: number, kind: string, id: string, event: JournalEntry["event"]): JournalEntry {
  return { seq, at: "2026-09-10T09:00:00+00:00", actor: { kind, id, round: 1 }, event };
}

// Every arm the page draws differently: a run event, a turn boundary, a
// message with a tool call and a failed result, a concern move, a streaming
// event that draws nothing, and a verification failure.
const record: JournalEntry[] = [
  entry(0, "run", "run-1", { type: "phase_changed", phase: "workers" }),
  entry(1, "worker", "alpha", { type: "turn_started", identifiers }),
  entry(2, "worker", "alpha", {
    type: "message_completed",
    identifiers,
    message: {
      blocks: [
        { type: "text", text: "Reading the adapter." },
        { type: "tool_call", id: "call-1", name: "Read", arguments: { path: "src/adapter.py" } },
        { type: "tool_result", content: "no such file", is_error: true, tool_call_id: "call-1" },
      ],
      message_id: null,
      model: null,
      parent_tool_call_id: null,
      role: "assistant",
    },
  }),
  entry(3, "worker", "beta", {
    type: "concern_progressed",
    progress: { concern_id: "beta", status: "failed", reason: "tests red", settled_at: null },
  }),
  entry(4, "worker", "alpha", { type: "block_started", identifiers, block: { type: "text", text: "half" } }),
  entry(5, "run", "run-1", {
    type: "verification_failed",
    concern_id: "alpha",
    round: 1,
    name: "pytest",
    exit_code: 1,
    output: "1 failed",
  }),
];

// An event this page was never taught, as a newer server would record it.
const unknown = {
  seq: 6,
  at: "2026-09-10T09:00:00+00:00",
  actor: { kind: "run", id: "run-1", round: 1 },
  event: { type: "budget_warning", remaining: 3 },
};

describe("the supervisor", () => {
  let calls: Call[];
  let shown: Mounted;
  let current: SupervisorState;

  beforeEach(async () => {
    stubLayout();
    FakeEventSource.install();
    localStorage.clear();
    window.history.replaceState(null, "", "/");
    current = state;
    calls = serve({
      "api/runs": index,
      "api/state": () => json({ detail: "opened on no run" }, 404),
      "api/runs/run-1": () => current,
      "api/runs/run-1/answers": () => {
        current = answered;
        return answered;
      },
    });
    shown = mount(
      <StrictMode>
        <App />
      </StrictMode>,
    );
    await until(() => shown.root.textContent?.includes("Pick a run") ?? false, "the run picker");
  });

  afterEach(() => shown.unmount());

  async function open(): Promise<void> {
    await click(one(shown.root, ".run-item"));
    await until(() => shown.root.querySelector(".questions") !== null, "the run's questions");
  }

  test("mounts on the rail with every recorded run, waiting for one to be picked", () => {
    expect(texts(shown.root, ".run-item .run-name")).toEqual(["run-1"]);
    expect(one(shown.root, ".run-item .run-meta").textContent).toBe("workers · 3 concerns");
    expect(one(shown.root, ".run-item .count").textContent).toBe("2");
    expect(one(shown.root, ".masthead h1").textContent).toBe("—");
    expect(texts(shown.root, ".pills .pill")).toContain("select a run");
    expect([...new Set(calls.map((call) => call.path))]).toEqual(["api/runs", "api/state"]);
  });

  test("picking the run shows its questions first, groups still waiting ahead of settled ones", async () => {
    await open();
    expect(window.location.hash).toBe("#run-1");
    expect(one(shown.root, ".run-item").className).toBe("run-item current");
    expect(one(shown.root, ".masthead h1").textContent).toBe("run-1");
    expect(texts(shown.root, ".pills .pill")).toContain("awaiting answers");
    expect(one(shown.root, ".phase-chips .chip.current").textContent).toBe("workers");
    expect(shown.root.textContent).toContain("This run is not moving.");
    expect(texts(shown.root, ".stage h2")).toEqual(["Pending questions", "Concerns", "Trace"]);
    const questions = one(shown.root, ".questions");
    expect(texts(questions, "legend")).toEqual(["alpha", "beta", "gamma"]);
    expect(questions.textContent).toContain("2 waiting on you");
    expect(texts(questions, ".answered summary")).toHaveLength(1);
    expect(texts(questions, ".prompt")).toEqual([
      "Keep the legacy adapter?",
      "Which prefix do the routes take?",
      "Keep the docs page?",
    ]);
    expect(texts(shown.root, "tbody tr td:first-child strong")).toEqual(["alpha", "beta", "gamma"]);
    expect(FakeEventSource.current().url).toBe("api/runs/run-1/events");

    await act(async () => FakeEventSource.current().open());
    await until(() => texts(shown.root, ".pills .pill").includes("watching"), "the stream's pill");
  });

  test("answering a question posts only the answers given, and the reply settles it", async () => {
    await open();
    await click(one(shown.root, 'input[name="q-alpha"][value="drop"]'));
    await click(labelled(shown.root, "button", "Submit answers"));
    await until(() => calls.some((call) => call.path === "api/runs/run-1/answers"), "the answers post");
    expect(calls.find((call) => call.path === "api/runs/run-1/answers")).toEqual({
      method: "POST",
      path: "api/runs/run-1/answers",
      search: "",
      body: { answers: [{ question_id: "q-alpha", value: "drop" }] },
    });
    await until(() => shown.root.textContent?.includes("1 waiting on you") ?? false, "the settled count");
    expect(texts(one(shown.root, ".questions"), ".answered summary")).toHaveLength(2);
    expect(texts(one(shown.root, ".questions"), "legend")).toEqual(["beta", "gamma", "alpha"]);
    expect(localStorage.getItem("lup-supervisor:run-1")).toBeNull();
  });

  test("the trace draws what the stream delivers, raw where it cannot name it, and the kind filter narrows", async () => {
    await open();
    await act(async () => {
      for (const each of [...record, unknown]) FakeEventSource.current().deliver(each);
    });
    await until(() => shown.root.querySelectorAll(".trace-row").length === 6, "the drawn entries");
    const drawn = texts(shown.root, ".trace-row");
    expect(drawn[0]).toContain("phase → workers");
    expect(drawn[1]).toContain("turn started");
    expect(drawn[2]).toContain("Reading the adapter.");
    expect(drawn[2]).toContain("Read");
    expect(drawn[2]).toContain("src/adapter.py");
    expect(drawn[3]).toContain("beta → failed tests red");
    expect(drawn[4]).toContain("alpha round 1: pytest exited 1");
    expect(drawn[4]).toContain("1 failed");
    expect(one(shown.root, ".trace-row .unknown .pre-body").textContent).toContain('"type": "budget_warning"');
    expect(texts(shown.root, ".trace-row .result.bad")).toEqual(["no such file"]);
    expect(texts(shown.root, ".chip-row .chip")).toContain("worker:alpha#1");
    expect(texts(shown.root, "tbody tr")[1]).toContain("failed");
    expect(texts(shown.root, ".pills .pill").some((pill) => pill.startsWith("last event "))).toBe(true);

    const filter = one<HTMLSelectElement>(shown.root, ".trace-controls select");
    await choose(filter, "errors");
    await until(() => shown.root.querySelectorAll(".trace-row").length === 2, "only the errors");
    expect(texts(shown.root, ".trace-row").map((text) => text.includes("no such file"))).toEqual([true, false]);
    await choose(filter, "notes");
    await until(() => shown.root.querySelectorAll(".trace-row").length === 4, "run events only");
    expect(shown.root.querySelector(".trace-row .say")).toBeNull();
  });
});
