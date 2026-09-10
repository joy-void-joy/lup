// The explorer mounted as a page: the list, the search, the node route and
// the graph pane, over a three-node log served by a fixture. Every assertion
// reads what a reader would see or what the server was asked, never a
// component's insides.
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { StrictMode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import type { EdgeView, GraphView, KindsView, NodeDetail, NodeView } from "../generated/views";
import {
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
  visit,
  type Call,
  type Mounted,
} from "../testing";
import { router } from "./router";

function node(
  id: string,
  slug: string,
  kind: string,
  title: string,
  standing: string,
  reason: string,
  sound: boolean,
): NodeView {
  return {
    id,
    slug,
    kind,
    title,
    standing,
    reason,
    sound,
    text: `${title}, in full`,
    priority: 1,
    moved: "2026-09-09T10:00:00+00:00",
  };
}

const nodes: NodeView[] = [
  node("n1", "alpha", "corpus:claim", "Alpha rests on beta", "supported", "two sources agree", true),
  node("n2", "beta", "corpus:claim", "Beta was retracted", "refuted", "the source withdrew it", false),
  node("n3", "gamma", "coordination:task", "Gamma follows up", "open", "", true),
];
const edges: EdgeView[] = [
  { kind: "corpus:rests_on", source: "n1", target: "n2" },
  { kind: "coordination:blocks", source: "n2", target: "n3" },
];
const graph: GraphView = {
  nodes,
  edges,
  kinds: ["corpus:claim", "coordination:task"],
  standings: ["supported", "refuted", "open"],
};
const kinds: KindsView = {
  nodes: [
    { kind: "corpus:claim", name: "claim", summary: "Something a source asserts", fields: ["source", "quote"] },
    { kind: "coordination:task", name: "task", summary: "Work somebody took on", fields: ["owner"] },
  ],
  edges: [
    { kind: "corpus:rests_on", name: "rests_on", summary: "One claim depends on another", fields: [] },
    { kind: "coordination:blocks", name: "blocks", summary: "One task waits on another", fields: [] },
  ],
};

/** The node in full, its weight and edges derived from the graph the way the server derives them. */
function detail(shown: NodeView): NodeDetail {
  const edgesIn = edges.filter((edge) => edge.target === shown.id);
  return {
    node: shown,
    fields: { source: `memo-${shown.slug}` },
    incoming: [...new Set(edgesIn.map((edge) => edge.kind))].map((kind) => ({
      kind,
      count: edgesIn.filter((edge) => edge.kind === kind).length,
    })),
    edges_in: edgesIn,
    edges_out: edges.filter((edge) => edge.source === shown.id),
    attachments: [],
  };
}

// A node is reached by slug from the list and by id from an edge, so the
// server answers both spellings.
const routes = {
  "api/graph": graph,
  "api/kinds": kinds,
  ...Object.fromEntries(
    nodes.flatMap((each) => [
      [`api/node/${each.id}`, detail(each)],
      [`api/node/${each.slug}`, detail(each)],
    ]),
  ),
};

function page(): Mounted {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return mount(
    <StrictMode>
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </StrictMode>,
  );
}

const rows = (root: ParentNode) => root.querySelectorAll(".rows a.row");

describe("the explorer", () => {
  let calls: Call[];
  let shown: Mounted;

  beforeEach(async () => {
    stubLayout();
    stubCanvas();
    window.history.replaceState(null, "", "/");
    calls = serve(routes);
    shown = page();
    await visit("/");
    await until(() => rows(shown.root).length === 3, "the three nodes");
  });

  afterEach(() => shown.unmount());

  test("lists every node with its standing, and the kinds the log declares", () => {
    expect(one(shown.root, ".brand").textContent).toBe("Ledger explorer");
    expect(texts(shown.root, ".rows a.row .title")).toEqual([
      "Alpha rests on beta",
      "Beta was retracted",
      "Gamma follows up",
    ]);
    expect(texts(shown.root, ".rows a.row .standing")).toEqual(["supported", "refuted", "open"]);
    expect(one(shown.root, ".rows a.row .standing.unsound").getAttribute("title")).toBe(
      "the source withdrew it",
    );
    expect(shown.root.textContent).toContain("3 of 3 node(s)");
    expect(one(shown.root, ".kinds").textContent).toContain("Something a source asserts");
    expect(one(shown.root, ".kinds").textContent).toContain("One task waits on another");
    expect(calls.map((call) => call.path).sort()).toEqual(["api/graph", "api/kinds"]);
  });

  test("the search box narrows the list and rides in the URL, asking the server nothing", async () => {
    await type(one(shown.root, 'input[type="search"]'), "gamma");
    await until(() => rows(shown.root).length === 1, "one row");
    expect(texts(shown.root, ".rows a.row .title")).toEqual(["Gamma follows up"]);
    expect(shown.root.textContent).toContain("1 of 3 node(s)");
    expect(decodeURIComponent(window.location.hash)).toContain("q=gamma");
    expect(calls.filter((call) => call.path === "api/graph")).toHaveLength(1);
  });

  test("a row opens its node with every edge counted, and the hash route reaches another", async () => {
    await click(one(shown.root, 'a.row[href$="/node/beta"]'));
    await until(() => shown.root.querySelector("article.node h1") !== null, "the node page");
    expect(window.location.hash).toBe("#/node/beta");
    expect(one(shown.root, "article.node h1").textContent).toBe("Beta was retracted");
    expect(one(shown.root, "article.node h1").className).toBe("unsound");
    expect(one(shown.root, "article.node .standing").textContent).toBe(
      "refuted — the source withdrew it",
    );
    expect(texts(shown.root, ".counts li")).toEqual(["1 corpus:rests_on"]);
    expect(texts(shown.root, ".edges li")).toEqual(["corpus:rests_on n1", "coordination:blocks n3"]);
    expect(texts(shown.root, ".fields dt")).toEqual(["source"]);
    expect(texts(shown.root, ".fields dd")).toEqual(['"memo-beta"']);
    expect(calls[calls.length - 1]?.path).toBe("api/node/beta");

    await visit("/node/n1");
    await until(
      () => shown.root.querySelector("article.node h1")?.textContent === "Alpha rests on beta",
      "the node the address bar named",
    );
    expect(shown.root.textContent).toContain("Nothing points at this node.");
    expect(texts(shown.root, ".edges li")).toEqual(["corpus:rests_on n2"]);
    expect(calls[calls.length - 1]?.path).toBe("api/node/n1");
  });

  test("the graph view hands the same nodes to cytoscape, which draws onto its canvases", async () => {
    await click(labelled(shown.root, ".views a", "graph"));
    await until(() => shown.root.querySelectorAll(".graph canvas").length > 0, "the graph's canvases");
    expect(shown.root.querySelector(".rows")).toBeNull();
    expect(decodeURIComponent(window.location.hash)).toContain("view=graph");
    expect(one(shown.root, '.views a[aria-current="page"]').textContent).toBe("graph");
  });
});
