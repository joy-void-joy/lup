// How the page reads the ledger: from the routes the server answers, or from
// the data an export embedded on the mount point. The same view models either
// way — compiled from the pydantic side — so a component never knows which.
import type { ExportView, GraphView, KindsView, NodeDetail } from "../generated/views";
import { narrowed, type GraphQuery } from "./narrow";

let held: ExportView | null | undefined;

/** What an exported page carries, parsed once; null where a server answers instead. */
export function embedded(): ExportView | null {
  if (held === undefined) {
    const raw = document.getElementById("root")?.dataset["lupExport"];
    held = raw === undefined ? null : (JSON.parse(raw) as ExportView);
  }
  return held;
}

async function read<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${path}: HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function loadGraph(query: GraphQuery): Promise<GraphView> {
  const view = embedded();
  if (view !== null) {
    return narrowed(view.graph, query);
  }
  const params = new URLSearchParams();
  if (query.kind !== "") params.set("kind", query.kind);
  if (query.standing !== "") params.set("standing", query.standing);
  if (query.since !== "") params.set("since", query.since);
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  return read<GraphView>(`api/graph${suffix}`);
}

export async function loadNode(spelling: string): Promise<NodeDetail> {
  const view = embedded();
  if (view !== null) {
    const found = view.details.find(
      (detail) => detail.node.id === spelling || detail.node.slug === spelling,
    );
    if (found === undefined) {
      throw new Error(`no node has the id or slug ${JSON.stringify(spelling)}`);
    }
    return found;
  }
  return read<NodeDetail>(`api/node/${encodeURIComponent(spelling)}`);
}

export async function loadKinds(): Promise<KindsView> {
  const view = embedded();
  return view !== null ? view.kinds : read<KindsView>("api/kinds");
}
