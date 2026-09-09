// The explorer's shell: enough to prove the seam end to end — the bundle is
// built, served, and typed against the JSON the server sends — before the
// explorer itself is built over it. `GraphView` is compiled from the pydantic
// model at build time, so a field renamed on the Python side fails here
// rather than in a browser.
import { useEffect, useState } from "react";
import type { GraphView } from "../generated/views";

type Loaded =
  | { state: "loading" }
  | { state: "absent"; status: number }
  | { state: "ready"; graph: GraphView };

async function readGraph(): Promise<Loaded> {
  const response = await fetch("api/graph");
  if (!response.ok) {
    return { state: "absent", status: response.status };
  }
  return { state: "ready", graph: (await response.json()) as GraphView };
}

export function App() {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });

  useEffect(() => {
    let live = true;
    readGraph().then((result) => {
      if (live) setLoaded(result);
    });
    return () => {
      live = false;
    };
  }, []);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", margin: "2rem" }}>
      <h1>Ledger explorer</h1>
      {loaded.state === "loading" && <p>Reading the ledger…</p>}
      {loaded.state === "absent" && (
        <p>
          No ledger is served at <code>api/graph</code> (HTTP {loaded.status}).
        </p>
      )}
      {loaded.state === "ready" && (
        <p>
          {loaded.graph.nodes.length} node(s), {loaded.graph.edges.length}{" "}
          edge(s); kinds: {loaded.graph.kinds.join(", ") || "none"}.
        </p>
      )}
    </main>
  );
}
