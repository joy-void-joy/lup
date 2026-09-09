// The log as a reader browses it: filters on the left, and on the right either
// every matching node as a sorted, virtualised list or the same nodes drawn as
// a graph. Every filter is in the URL, so a reader hands another one exactly
// what they were looking at. Table owns sorting and the row model; Virtual
// owns which rows are on screen; the markup is ours.
import { useMemo, useRef } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  createColumnHelper,
  createSortedRowModel,
  rowSortingFeature,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { KindInfo, NodeView } from "../generated/views";
import { loadGraph, loadKinds } from "./api";
import { GraphPane } from "./GraphPane";
import { matches } from "./narrow";
import { browseRoute, type BrowseSearch } from "./router";
import { Standing } from "./Standing";

const features = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
});
const helper = createColumnHelper<typeof features, NodeView>();
const columns = helper.columns([
  helper.accessor("kind", { header: "Kind" }),
  helper.accessor("title", { header: "Title" }),
  helper.accessor("standing", { header: "Standing" }),
  helper.accessor("priority", { header: "Priority" }),
  helper.accessor("moved", { header: "Moved" }),
]);
const NO_NODES: NodeView[] = [];
const ROW_HEIGHT = 32;

function moved(spelling: string): string {
  const at = new Date(spelling);
  return Number.isNaN(at.getTime()) ? spelling : at.toLocaleString();
}

function Kinds({ nodes, edges }: { nodes: KindInfo[]; edges: KindInfo[] }) {
  return (
    <details className="kinds">
      <summary>Declared kinds</summary>
      {[...nodes, ...edges].map((kind) => (
        <p key={kind.kind} title={kind.fields.join("\n")}>
          <code>{kind.kind}</code> {kind.summary}
        </p>
      ))}
    </details>
  );
}

function Rows({ data }: { data: NodeView[] }) {
  const table = useTable({ features, columns, data });
  const rows = table.getRowModel().rows;
  const scroller = useRef<HTMLDivElement | null>(null);
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scroller.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
    getItemKey: (index) => rows[index]?.id ?? index,
  });
  return (
    <div ref={scroller} className="results">
      {table.getHeaderGroups().map((group) => (
        <div key={group.id} className="row head">
          {group.headers.map((header) => (
            <button
              key={header.id}
              type="button"
              className="sort"
              onClick={header.column.getToggleSortingHandler()}
            >
              <table.FlexRender header={header} />
              {{ asc: " ↑", desc: " ↓" }[String(header.column.getIsSorted())] ?? ""}
            </button>
          ))}
        </div>
      ))}
      {rows.length === 0 && <p className="muted">Nothing matches.</p>}
      <div className="rows" style={{ height: virtualizer.getTotalSize() }}>
        {virtualizer.getVirtualItems().map((item) => {
          const row = rows[item.index];
          if (row === undefined) return null;
          const node = row.original;
          return (
            <Link
              key={row.id}
              to="/node/$id"
              params={{ id: node.slug !== "" ? node.slug : node.id }}
              className="row"
              style={{ transform: `translateY(${item.start}px)`, height: item.size }}
            >
              <code>{node.kind}</code>
              <span className="title" title={node.text}>
                {node.title}
              </span>
              <Standing label={node.standing} reason={node.reason} sound={node.sound} brief />
              <span>{node.priority}</span>
              <span className="muted">{moved(node.moved)}</span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

export function Browse() {
  const search = browseRoute.useSearch();
  const navigate = useNavigate();
  const graph = useQuery({
    queryKey: ["graph", search.kind, search.standing, search.since],
    queryFn: () => loadGraph({ kind: search.kind, standing: search.standing, since: search.since }),
  });
  const kinds = useQuery({ queryKey: ["kinds"], queryFn: loadKinds });
  const data = useMemo(
    () => (graph.data?.nodes ?? NO_NODES).filter((node) => matches(node, search.q)),
    [graph.data, search.q],
  );

  function amend(change: Partial<BrowseSearch>) {
    void navigate({ to: "/", search: { ...search, ...change }, replace: true });
  }

  return (
    <div className="browse">
      <aside className="filters">
        <label>
          Search
          <input
            type="search"
            value={search.q}
            placeholder="title, text, slug, id"
            onChange={(event) => amend({ q: event.target.value })}
          />
        </label>
        <label>
          Kind
          <select value={search.kind} onChange={(event) => amend({ kind: event.target.value })}>
            <option value="">any</option>
            {(graph.data?.kinds ?? []).map((kind) => (
              <option key={kind} value={kind}>
                {kind}
              </option>
            ))}
          </select>
        </label>
        <label>
          Standing
          <select
            value={search.standing}
            onChange={(event) => amend({ standing: event.target.value })}
          >
            <option value="">any</option>
            {(graph.data?.standings ?? []).map((standing) => (
              <option key={standing} value={standing}>
                {standing}
              </option>
            ))}
          </select>
        </label>
        <label>
          Moved since
          <input
            type="datetime-local"
            value={search.since}
            onChange={(event) => amend({ since: event.target.value })}
          />
        </label>
        <div className="views">
          <Link to="/" search={{ ...search, view: "list" }} aria-current={search.view === "list" ? "page" : undefined}>
            list
          </Link>
          <Link to="/" search={{ ...search, view: "graph" }} aria-current={search.view === "graph" ? "page" : undefined}>
            graph
          </Link>
        </div>
        <p className="muted">
          {graph.data === undefined ? "" : `${data.length} of ${graph.data.nodes.length} node(s)`}
        </p>
        {kinds.data !== undefined && <Kinds nodes={kinds.data.nodes} edges={kinds.data.edges} />}
      </aside>
      {graph.isPending && <p className="muted">Reading the ledger…</p>}
      {graph.isError && <p className="error">{String(graph.error)}</p>}
      {graph.data !== undefined && search.view === "graph" && (
        <GraphPane
          graph={{
            ...graph.data,
            nodes: data,
            edges: graph.data.edges.filter(
              (edge) =>
                data.some((node) => node.id === edge.source) &&
                data.some((node) => node.id === edge.target),
            ),
          }}
        />
      )}
      {graph.data !== undefined && search.view === "list" && <Rows data={data} />}
    </div>
  );
}
