import { describe, expect, test } from "bun:test";
import type { GraphView, NodeView } from "../generated/views";
import { matches, narrowed } from "./narrow";

function node(id: string, kind: string, standing: string, moved: string): NodeView {
  return {
    id,
    kind,
    title: `node ${id}`,
    slug: "",
    text: "",
    priority: 0,
    standing,
    reason: "",
    sound: true,
    author: "session:t#1",
    moved,
  };
}

const graph: GraphView = {
  nodes: [
    node("a", "corpus:claim", "supported", "2026-09-01T10:00:00+00:00"),
    node("b", "corpus:claim", "refuted", "2026-09-05T10:00:00+00:00"),
    node("c", "coordination:task", "open", "2026-09-09T10:00:00+00:00"),
  ],
  edges: [
    { kind: "corpus:rests_on", source: "a", target: "b" },
    { kind: "coordination:blocks", source: "b", target: "c" },
  ],
  kinds: ["corpus:claim", "coordination:task"],
  standings: ["supported", "refuted", "open"],
};

describe("narrowed", () => {
  test("keeps everything for an empty query", () => {
    expect(narrowed(graph, { kind: "", standing: "", since: "", lacking: "" })).toEqual(graph);
  });

  test("drops an edge whose far end was narrowed away", () => {
    const claims = narrowed(graph, { kind: "corpus:claim", standing: "", since: "", lacking: "" });
    expect(claims.nodes.map((each) => each.id)).toEqual(["a", "b"]);
    expect(claims.edges.map((each) => each.kind)).toEqual(["corpus:rests_on"]);
    expect(claims.kinds).toEqual(graph.kinds);
  });

  test("reads since off when each node last moved", () => {
    const recent = narrowed(graph, { kind: "", standing: "", since: "2026-09-04T00:00:00Z", lacking: "" });
    expect(recent.nodes.map((each) => each.id)).toEqual(["b", "c"]);
    const unreadable = narrowed(graph, { kind: "", standing: "", since: "yesterday-ish", lacking: "" });
    expect(unreadable.nodes).toHaveLength(3);
  });

  test("narrows by standing", () => {
    const refuted = narrowed(graph, { kind: "", standing: "refuted", since: "", lacking: "" });
    expect(refuted.nodes.map((each) => each.id)).toEqual(["b"]);
    expect(refuted.edges).toEqual([]);
  });
});

describe("matches", () => {
  test("answers on every readable field, ignoring case and the edges of the needle", () => {
    const [first] = graph.nodes;
    if (first === undefined) throw new Error("the fixture holds nodes");
    expect(matches(first, "  NODE A ")).toBe(true);
    expect(matches(first, "corpus")).toBe(true);
    expect(matches(first, "supported")).toBe(true);
    expect(matches(first, "task")).toBe(false);
    expect(matches(first, "")).toBe(true);
  });
});

describe("narrowed by lacking", () => {
  test("keeps only the nodes from which no edge of the kind runs, reading every edge first", () => {
    // `a` rests on `b`, so lacking `rests_on` drops `a` and keeps `b` and `c`;
    // narrowing to claims as well hides `c` without changing what `a` lacks.
    const ours = narrowed(graph, { kind: "", standing: "", since: "", lacking: "corpus:rests_on" });
    expect(ours.nodes.map((each) => each.id)).toEqual(["b", "c"]);
    expect(ours.edges.map((each) => each.kind)).toEqual(["coordination:blocks"]);
    const claims = narrowed(graph, {
      kind: "corpus:claim",
      standing: "",
      since: "",
      lacking: "corpus:rests_on",
    });
    expect(claims.nodes.map((each) => each.id)).toEqual(["b"]);
  });
});
