// Narrowing a graph the page already holds, the way the server narrows one it
// serves. An exported page carries the whole log and cannot ask for less, so
// the same three filters `api/graph` takes run here over what is held, and
// search runs here in both modes — the graph in hand carries every field it
// reads. Pure functions, so `bun test` holds them to the server's semantics.
import type { GraphView, NodeView } from "../generated/views";

export type GraphQuery = { kind: string; standing: string; since: string };

/** A moment as milliseconds, or null where the spelling is empty or unreadable. */
function moment(spelling: string): number | null {
  if (spelling === "") return null;
  const parsed = Date.parse(spelling);
  return Number.isNaN(parsed) ? null : parsed;
}

/** The graph narrowed as `api/graph` narrows it: kind, standing, moved since. */
export function narrowed(graph: GraphView, query: GraphQuery): GraphView {
  const since = moment(query.since);
  const nodes = graph.nodes.filter(
    (node) =>
      (query.kind === "" || node.kind === query.kind) &&
      (query.standing === "" || node.standing === query.standing) &&
      (since === null || Date.parse(node.moved) > since),
  );
  const shown = new Set(nodes.map((node) => node.id));
  return {
    ...graph,
    nodes,
    // An edge survives only where both its ends did, so a narrowed graph
    // never draws a line to a node it is not showing.
    edges: graph.edges.filter((edge) => shown.has(edge.source) && shown.has(edge.target)),
  };
}

/** Whether a node answers a search — one of its readable fields carries the words. */
export function matches(node: NodeView, needle: string): boolean {
  const wanted = needle.trim().toLowerCase();
  if (wanted === "") return true;
  return [node.title, node.text, node.slug, node.id, node.kind, node.standing].some((field) =>
    field.toLowerCase().includes(wanted),
  );
}
